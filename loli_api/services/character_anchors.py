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
from typing import Optional

from services.scene_mapper import identity_anchor_text

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
