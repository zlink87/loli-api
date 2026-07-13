"""
Server-side identity-anchor population for the standalone edit endpoints.

Batch items get their per-character identity anchors from scene_mapper
(identityAnchors already set on the PipelineEditRequest). The standalone edit
endpoints (/v1/edit/outfit, /pose, /background, /edit) have no character context
by default, so a dark-skinned character's body is repainted white because no
skin-tone text reaches the edit prompt. This helper lets those endpoints load the
character by id and populate identityAnchors before enqueuing, reusing the SAME
identity_anchor_text builder the batch path uses.

Best-effort by design: a missing store, an unknown character, or any store error
logs a warning and leaves the request unchanged (the edit still runs, just without
anchors) — this must NEVER turn into a 500 on the edit path.
"""
import logging
from typing import List, Optional

from services.scene_mapper import identity_anchor_text
from services import scene_vocab as sv
from models.trait_profile import TraitProfile

logger = logging.getLogger(__name__)


async def populate_identity_anchors(store, request) -> None:
    """
    If ``request.characterId`` is set and ``request.identityAnchors`` is absent,
    load the character via ``store`` and set ``request.identityAnchors`` from its
    persona (skin tone / hair / eyes / build).

    No-ops (leaving the request untouched) when:
      * the request carries no characterId, or already has explicit identityAnchors
        (an explicit caller value is never overridden);
      * ``store`` is None (character store not configured / Supabase not wired);
      * the character id is unknown;
      * the persona yields no anchorable attributes (identity_anchor_text -> None);
      * the store raises for any reason (logged, swallowed).
    """
    character_id = getattr(request, "characterId", None)
    if not character_id:
        return
    if getattr(request, "identityAnchors", None):
        # Explicit caller-provided anchors win; never override them.
        return
    if store is None:
        logger.warning(
            "characterId=%s provided but character store not configured; "
            "proceeding without identity anchors",
            character_id,
        )
        return

    try:
        character = await store.get(character_id)
    except Exception as e:  # noqa: BLE001 — anchors are protective, not critical
        logger.warning(
            "Failed to load character %s for identity anchors: %s; proceeding without",
            character_id, e,
        )
        return

    if character is None:
        logger.warning(
            "characterId=%s not found; proceeding without identity anchors",
            character_id,
        )
        return

    anchors = identity_anchor_text(character)
    if anchors:
        request.identityAnchors = anchors
        logger.info("Populated identityAnchors for character %s", character_id)


async def populate_home_style(trait_store, request) -> None:
    """
    WS-T (trait reach for edits). If ``request.characterId`` is set, the request
    targets a HOME-like ``location`` (``scene_vocab.is_home_like_location``), and
    ``interiorStyle``/``colorPalette`` are absent, load the character's trait profile
    and fill those two from it — so a MANUAL home edit renders her OWN styled room /
    palette, exactly the personal home a batch produces (batches bake the same text via
    ``scene_mapper``). The background prompt build then threads them through
    ``scene_vocab.build_scene_background_text``.

    No-ops (leaving the request untouched) when:
      * the request carries no ``characterId``;
      * the location is NOT home-like — a non-home scene (cafe/street/gym/…) never
        carries a personal room or palette (WS-S palette scope), so this returns early
        BEFORE any store call;
      * BOTH ``interiorStyle`` and ``colorPalette`` are already set (explicit caller
        values always win; each is filled independently);
      * ``trait_store`` is None (trait store not configured / Supabase not wired);
      * the character has no profile row, or an empty profile lacks both fields;
      * the store raises for any reason (logged, swallowed).

    Never raises and NEVER touches identity/nudity — home styling only.
    """
    character_id = getattr(request, "characterId", None)
    if not character_id:
        return
    # Home-style is scoped to home-ish rooms only (matches scene_mapper's WS-S gate).
    # Checked BEFORE the store round-trip so non-home edits stay a pure no-op.
    location = getattr(request, "location", None)
    if not sv.is_home_like_location(location):
        return
    have_style = getattr(request, "interiorStyle", None) is not None
    have_palette = getattr(request, "colorPalette", None) is not None
    if have_style and have_palette:
        return  # both explicit — nothing to derive
    if trait_store is None:
        logger.warning(
            "characterId=%s provided but trait profile store not configured; "
            "proceeding without home style",
            character_id,
        )
        return

    try:
        row = await trait_store.get(character_id)
    except Exception as e:  # noqa: BLE001 — home style is protective, not critical
        logger.warning(
            "Failed to load trait profile for character %s: %s; proceeding without home style",
            character_id, e,
        )
        return

    if not row:
        return
    profile = TraitProfile.coerce(row.get("profile") or {})
    filled = []
    if not have_style and profile.interior_style is not None:
        request.interiorStyle = profile.interior_style
        filled.append("interiorStyle")
    if not have_palette and profile.color_palette is not None:
        request.colorPalette = profile.color_palette
        filled.append("colorPalette")
    if filled:
        logger.info(
            "Populated home style %s for character %s (location=%s)",
            filled, character_id, getattr(location, "value", location),
        )


async def never_wears_warnings(trait_store, request) -> Optional[List[str]]:
    """
    WS-T outfit-edit advisory (NON-BLOCKING). If ``request.characterId`` is set and
    ``request.outfit`` is in the character's trait-profile ``never_wears`` list, return
    a single-item advisory ``["<outfit> is in this character's never-wears list"]`` for
    the response's ``traitWarnings`` field. The admin choice always wins — the edit is
    NEVER blocked; this only surfaces the conflict for the panel.

    Returns None (no advisory) when:
      * the request carries no ``characterId`` or no ``outfit``;
      * ``trait_store`` is None (not configured);
      * the character has no profile row;
      * the requested outfit is not in ``never_wears``;
      * the store raises for any reason (logged, swallowed).

    Never raises.
    """
    character_id = getattr(request, "characterId", None)
    outfit = getattr(request, "outfit", None)
    if not character_id or outfit is None:
        return None
    if trait_store is None:
        return None

    try:
        row = await trait_store.get(character_id)
    except Exception as e:  # noqa: BLE001 — the advisory is optional, never critical
        logger.warning(
            "Failed to load trait profile for character %s: %s; skipping never-wears advisory",
            character_id, e,
        )
        return None

    if not row:
        return None
    profile = TraitProfile.coerce(row.get("profile") or {})
    if outfit in profile.never_wears:
        label = str(getattr(outfit, "value", outfit)).replace("_", " ")
        return [f"{label} is in this character's never-wears list"]
    return None
