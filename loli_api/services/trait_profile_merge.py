"""
trait_profile_merge — fold a character's saved TraitProfile into a batch's controls.

`apply_trait_profile(controls, likes, dislikes, profile, occupation)` is a PURE
function (no I/O, no mutation of its inputs — it returns a fresh BatchControls and
fresh likes/dislikes lists) that turns the character's durable taste into the SOFT
bias fields the planner already consumes. Called once at launch by the
BatchOrchestrator, BEFORE the batch row is persisted, so the stored controls carry
the effective bias and the reconciler re-derives the same Character with zero changes.

HARD CONTRACT (asserted by test_trait_profile_merge):
  * NUDITY ENVELOPE IS NEVER READ OR WRITTEN. max_nudity / start_nudity / sfw_only /
    content_rating / escalation are byte-identical pre/post. A trait profile can bias
    WHAT she wears and WHERE she is, never HOW nude she is — nudity belongs to controls.
  * ADMIN WINS. An explicit admin allowlist (allowed_outfits / allowed_locations) makes
    the merge skip ALL profile outfit / location fields respectively; an explicitly-set
    demeanor / interior_style / color_palette is left untouched (fill-only). Batch-typed
    likes / dislikes win WHOLESALE (only an empty list is filled from the profile).
  * NO-OP on a None profile — an un-profiled character launches exactly as before.

The individual rules (blocklist unions, style->outfit expansion, work-location
protection) are documented inline against the plan's B2.2 spec.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from models.batch import BatchControls
from models.enums import OutfitType
from models.trait_profile import TraitProfile
from services.outfit_vocab import outfits_for_styles
from services.story_templates import work_locations_for


def apply_trait_profile(
    controls: BatchControls,
    likes: List[str],
    dislikes: List[str],
    profile: Optional[TraitProfile],
    occupation,
) -> Tuple[BatchControls, List[str], List[str]]:
    """
    Return (controls, likes, dislikes) with the character's TraitProfile folded in as a
    soft bias. Pure: the inputs are never mutated. No-op (inputs echoed) when `profile`
    is None. See the module docstring for the admin-wins / nudity-never-touched contract.
    """
    if profile is None:
        return controls, list(likes or []), list(dislikes or [])

    updates: dict = {}

    # --- OUTFIT fields (skipped entirely when the admin set an outfit allowlist) ---
    if not controls.allowed_outfits:
        # blocked_outfits ∪= never_wears (order-preserving, deduped; the default [NAKED]
        # and any admin blocks are retained).
        blocked = list(controls.blocked_outfits or [])
        for o in (profile.never_wears or []):
            if o not in blocked:
                blocked.append(o)
        updates["blocked_outfits"] = blocked
        blocked_set = set(blocked)

        # wardrobe_outfits = (style-mapped ∪ favorites) − blocked − {NAKED}; set only when
        # non-empty (a wardrobe of one/zero would either choke the intersect or add nothing).
        # Ordered by OutfitType declaration order for a stable, reproducible persisted row.
        wardrobe_set = outfits_for_styles(profile.wardrobe_styles) | set(profile.favorite_outfits or [])
        wardrobe_set -= blocked_set
        wardrobe_set.discard(OutfitType.NAKED)
        wardrobe = [o for o in OutfitType if o in wardrobe_set]
        if wardrobe:
            updates["wardrobe_outfits"] = wardrobe

        # favored_outfits = favorites − blocked (favorites order preserved; NAKED can't be
        # a favorite but strip defensively). Set only when non-empty.
        favored = [
            o for o in (profile.favorite_outfits or [])
            if o not in blocked_set and o != OutfitType.NAKED
        ]
        if favored:
            updates["favored_outfits"] = favored

    # --- LOCATION fields (skipped entirely when the admin set a location allowlist) ---
    if not controls.allowed_locations:
        # blocked_locations ∪= (avoided − work_locations_for(occupation)): an avoided place
        # she nonetheless WORKS at is NOT blocked (a nurse who "avoids hospitals" off the
        # clock must still be shown at the ward for her work chapter — work overrides taste).
        work_locs = set(work_locations_for(occupation))
        blocked_loc = list(controls.blocked_locations or [])
        for loc in (profile.avoided_locations or []):
            if loc in work_locs:
                continue
            if loc not in blocked_loc:
                blocked_loc.append(loc)
        updates["blocked_locations"] = blocked_loc
        blocked_loc_set = set(blocked_loc)

        # favored_locations = favorites − blocked (favorites order preserved). Non-empty only.
        favored_loc = [
            loc for loc in (profile.favorite_locations or []) if loc not in blocked_loc_set
        ]
        if favored_loc:
            updates["favored_locations"] = favored_loc

    # --- demeanor / interior_style / color_palette: FILL-ONLY (admin-set wins) ---
    if not controls.demeanor and profile.demeanor:
        updates["demeanor"] = list(profile.demeanor)
    if controls.interior_style is None and profile.interior_style is not None:
        updates["interior_style"] = profile.interior_style
    if controls.color_palette is None and profile.color_palette is not None:
        updates["color_palette"] = profile.color_palette

    new_controls = controls.model_copy(update=updates) if updates else controls

    # --- likes / dislikes: FILL-ONLY WHOLESALE (batch-typed values win) ---
    # A non-empty batch list is kept verbatim; an empty one is filled from the profile.
    new_likes = list(likes) if likes else list(profile.likes or [])
    new_dislikes = list(dislikes) if dislikes else list(profile.dislikes or [])

    return new_controls, new_likes, new_dislikes
