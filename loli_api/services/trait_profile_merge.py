"""
trait_profile_merge — fold a character's saved TraitProfile (and optional culture)
into a batch's controls.

`apply_trait_profile(controls, likes, dislikes, profile, occupation, culture=None)` is
a PURE function (no I/O, no mutation of its inputs — it returns a fresh BatchControls and
fresh likes/dislikes lists) that turns the character's durable taste into the SOFT
bias fields the planner already consumes. Called once at launch by the
BatchOrchestrator, BEFORE the batch row is persisted, so the stored controls carry
the effective bias and the reconciler re-derives the same Character with zero changes.

The optional `culture` (a CultureType, its raw value, or None) contributes an ADDITIONAL
soft bias from the subculture vocabulary (services.culture_vocab): wardrobe styles +
favored outfits/locations/poses, plus a fallback demeanor/interior_style/color_palette.
Culture is strictly ADDITIVE and lowest-priority — admin beats profile beats culture —
and obeys EVERY rule below identically (it is never a hard filter and never touches nudity).

HARD CONTRACT (asserted by test_trait_profile_merge):
  * NUDITY ENVELOPE IS NEVER READ OR WRITTEN. max_nudity / start_nudity / sfw_only /
    content_rating / escalation are byte-identical pre/post. A trait profile OR a culture
    can bias WHAT she wears and WHERE she is, never HOW nude she is — nudity belongs to
    controls. Culture obeys this identical rule: it never reads or writes the envelope.
  * ADMIN WINS. An explicit admin allowlist (allowed_outfits / allowed_locations) makes
    the merge skip ALL profile AND culture outfit / location fields respectively; an
    explicitly-set demeanor / interior_style / color_palette / favored_poses is left
    untouched (fill-only). Batch-typed likes / dislikes win WHOLESALE (only an empty list
    is filled from the profile). Culture likes are NOT sourced here (they arrive via the
    trait profile itself) to avoid double-sourcing.
  * NO-OP only when BOTH profile is None AND there is no culture spec — an un-profiled,
    un-cultured character launches exactly as before.

The individual rules (blocklist unions, style->outfit expansion, work-location
protection) are documented inline against the plan's B2.2 spec.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from models.batch import BatchControls
from models.enums import OutfitType, LocationType, PoseType
from models.trait_profile import TraitProfile
from services.outfit_vocab import outfits_for_styles
from services.story_templates import work_locations_for
from services.culture_vocab import (
    spec_for,
    culture_wardrobe_styles,
    culture_favored_outfits,
    culture_favored_locations,
    culture_favored_poses,
    culture_interior_style,
    culture_color_palette,
    culture_demeanor,
)


def apply_trait_profile(
    controls: BatchControls,
    likes: List[str],
    dislikes: List[str],
    profile: Optional[TraitProfile],
    occupation,
    culture=None,
) -> Tuple[BatchControls, List[str], List[str]]:
    """
    Return (controls, likes, dislikes) with the character's TraitProfile + optional
    `culture` folded in as a soft bias. Pure: the inputs are never mutated. No-op (inputs
    echoed) when BOTH `profile` is None AND `culture` maps to no spec. See the module
    docstring for the admin > profile > culture / nudity-never-touched contract.
    """
    if profile is None and spec_for(culture) is None:
        return controls, list(likes or []), list(dislikes or [])

    # Profile-derived pieces are treated as empty when there is no profile (culture-only).
    prof_never_wears = list(profile.never_wears or []) if profile else []
    prof_wardrobe_styles = profile.wardrobe_styles if profile else []
    prof_favorite_outfits = list(profile.favorite_outfits or []) if profile else []
    prof_avoided_locations = list(profile.avoided_locations or []) if profile else []
    prof_favorite_locations = list(profile.favorite_locations or []) if profile else []

    updates: dict = {}

    # --- OUTFIT fields (skipped entirely when the admin set an outfit allowlist) ---
    if not controls.allowed_outfits:
        # blocked_outfits ∪= never_wears (order-preserving, deduped; the default [NAKED]
        # and any admin blocks are retained). Culture NEVER blocks — its favors are additive.
        blocked = list(controls.blocked_outfits or [])
        for o in prof_never_wears:
            if o not in blocked:
                blocked.append(o)
        updates["blocked_outfits"] = blocked
        blocked_set = set(blocked)

        # wardrobe_outfits = (profile style-mapped ∪ favorites ∪ culture style-mapped ∪
        # culture favors) − blocked − {NAKED}; set only when non-empty. Ordered by OutfitType
        # declaration order for a stable, reproducible persisted row.
        wardrobe_set = (
            outfits_for_styles(prof_wardrobe_styles)
            | set(prof_favorite_outfits)
            | outfits_for_styles(culture_wardrobe_styles(culture))
            | culture_favored_outfits(culture)
        )
        wardrobe_set -= blocked_set
        wardrobe_set.discard(OutfitType.NAKED)
        wardrobe = [o for o in OutfitType if o in wardrobe_set]
        if wardrobe:
            updates["wardrobe_outfits"] = wardrobe

        # favored_outfits = profile favorites first (order preserved), then culture favors
        # not already present (OutfitType declaration order), − blocked − {NAKED}. Non-empty only.
        favored: List[OutfitType] = []
        for o in prof_favorite_outfits:
            if o not in blocked_set and o != OutfitType.NAKED and o not in favored:
                favored.append(o)
        culture_out_favs = culture_favored_outfits(culture)
        for o in OutfitType:
            if o in culture_out_favs and o not in blocked_set and o != OutfitType.NAKED \
                    and o not in favored:
                favored.append(o)
        if favored:
            updates["favored_outfits"] = favored

    # --- LOCATION fields (skipped entirely when the admin set a location allowlist) ---
    if not controls.allowed_locations:
        # blocked_locations ∪= (avoided − work_locations_for(occupation)): an avoided place
        # she nonetheless WORKS at is NOT blocked (a nurse who "avoids hospitals" off the
        # clock must still be shown at the ward for her work chapter — work overrides taste).
        # Culture NEVER blocks a location.
        work_locs = set(work_locations_for(occupation))
        blocked_loc = list(controls.blocked_locations or [])
        for loc in prof_avoided_locations:
            if loc in work_locs:
                continue
            if loc not in blocked_loc:
                blocked_loc.append(loc)
        updates["blocked_locations"] = blocked_loc
        blocked_loc_set = set(blocked_loc)

        # favored_locations = profile favorites first (order preserved), then culture favors
        # not already present (LocationType declaration order), − blocked. A location the
        # profile explicitly AVOIDS is never culture-favored (explicit dislikes beat
        # subculture defaults). Non-empty only.
        favored_loc = [
            loc for loc in prof_favorite_locations if loc not in blocked_loc_set
        ]
        avoided_set = set(prof_avoided_locations)
        culture_loc_favs = culture_favored_locations(culture)
        for loc in LocationType:
            if loc in culture_loc_favs and loc not in blocked_loc_set \
                    and loc not in avoided_set and loc not in favored_loc:
                favored_loc.append(loc)
        if favored_loc:
            updates["favored_locations"] = favored_loc

    # --- demeanor / interior_style / color_palette / favored_poses: FILL-ONLY ---
    # Priority admin > profile > culture: an explicit control wins; else the profile fills;
    # else the culture fills as a last resort.
    if not controls.demeanor:
        if profile and profile.demeanor:
            updates["demeanor"] = list(profile.demeanor)
        elif culture_demeanor(culture):
            updates["demeanor"] = culture_demeanor(culture)
    if controls.interior_style is None:
        if profile and profile.interior_style is not None:
            updates["interior_style"] = profile.interior_style
        elif culture_interior_style(culture) is not None:
            updates["interior_style"] = culture_interior_style(culture)
    if controls.color_palette is None:
        if profile and profile.color_palette is not None:
            updates["color_palette"] = profile.color_palette
        elif culture_color_palette(culture) is not None:
            updates["color_palette"] = culture_color_palette(culture)
    # favored_poses has no profile source — admin > culture only. PoseType declaration
    # order for reproducibility.
    if not controls.favored_poses:
        culture_poses = culture_favored_poses(culture)
        if culture_poses:
            updates["favored_poses"] = [p for p in PoseType if p in culture_poses]

    new_controls = controls.model_copy(update=updates) if updates else controls

    # --- likes / dislikes: FILL-ONLY WHOLESALE (batch-typed values win) ---
    # A non-empty batch list is kept verbatim; an empty one is filled from the profile.
    # Culture likes are NOT sourced here — they ride in via the trait profile itself, so
    # adding them again would double-source.
    prof_likes = profile.likes if profile else None
    prof_dislikes = profile.dislikes if profile else None
    new_likes = list(likes) if likes else list(prof_likes or [])
    new_dislikes = list(dislikes) if dislikes else list(prof_dislikes or [])

    return new_controls, new_likes, new_dislikes
