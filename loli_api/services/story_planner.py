"""
Story planner — turns a Character + count + controls into N validated SceneSpecs
that read like an organic story flow (a few narrative arcs) driven by the
character's occupation, personality, likes and dislikes.

Providers (pluggable), selected in preference order:
  * VeniceScenePlanner     — primary. Venice (uncensored) tolerates NSFW; emits structured JSON.
  * ClaudeScenePlanner     — SFW-ONLY stub. Anthropic refuses explicit content, so it
                             is never routed NSFW batches; currently defers to
                             deterministic (full wiring can be added when an SFW use
                             case exists).
  * DeterministicScenePlanner — always-available, seedable, NSFW-safe fallback.
  * ManualScenePlanner     — admin-supplied scene list (override / manual mode).

Every provider's output passes through validate_and_repair(), which coerces/repairs
enums, hard-clamps nudity to controls.max_nudity, enforces allow/block filters, and
guarantees exactly `count` scenes. Identity is NEVER touched — a SceneSpec has no
identity fields, and free-text is scrubbed of identity tokens.
"""
from __future__ import annotations

import difflib
import json
import logging
import math
import random
import re
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from models.requests import PersonaOptions
from models.enums import (
    PoseType,
    OutfitType,
    NudityLevel,
    AccessoryType,
    LocationType,
    TimeOfDayType,
    LightingType,
    KinkType,
    PersonalityType,
    DemeanorType,
    WardrobeStyleType,
    PhotoStyleType,
)
from models.batch import BatchControls
from models.scene import SceneSpec
from services import attribute_phrases as ap
from services import scene_vocab as sv
from services import story_templates as st
from services import outfit_vocab as ov
from services.pose_assets import POSE_DESCRIPTIONS, has_pose_ref
from services.venice_client import VeniceClient

logger = logging.getLogger(__name__)

# Nudity ordered from least to most exposed — used for clamping + escalation.
# The canonical 5-level ladder (same order as models/enums.py's NudityLevel); the
# index-based helpers below (_nudity_index/_nudity_ramp + the guided-ceiling clamp)
# read positions off THIS list, so they generalize to any ladder length.
_NUDITY_LADDER: List[NudityLevel] = [
    NudityLevel.LOW, NudityLevel.SUGGESTIVE, NudityLevel.MEDIUM,
    NudityLevel.REVEALING, NudityLevel.HIGH,
]

# Time-of-day ordered chronologically across a single day — used for the per-photo
# time ramp (early_morning -> night, once per day). This IS models/enums.py's
# TimeOfDayType declaration order (verified chronological: early_morning, morning,
# daytime, golden_hour, sunset, evening, night); the time helpers index off it the
# same index-based way the nudity helpers use _NUDITY_LADDER.
_TIME_LADDER: List[TimeOfDayType] = list(TimeOfDayType)


# ---------------------------------------------------------------------------
# Batch expression / gaze pool (A2 — "conscious model" variety)
# ---------------------------------------------------------------------------
# The deterministic planner used to leave SceneSpec.expression None, so every render
# fell through to the edit model's default camera-aware smile — a 24-item batch read as
# the same posed smile 24x. These short literal expression/gaze states are assigned one
# per scene (seeded, adjacency- and usage-capped) and flow through the EXISTING
# SceneSpec.expression -> pose-step expression clause; no new prompt path is added.
#
# Two registers: CAMERA-AWARE (she engages the lens) and CANDID (camera-unaware — a life
# observed, not a photoshoot). ~1/3 of items draw from the candid subset (deterministic).
# Every string is authored to SURVIVE _scrub_expression: NO facial-FEATURE / identity
# tokens (no eyes/lips/teeth/jaw/cheekbone/nose/chin, no hair/skin) — "calm, eyes closed"
# would be gutted by the scrub, so it is written "calm, lids lowered" instead. Kept module-
# local (NOT imported from camera_vocab) per the WS-A file-ownership boundary.
_BATCH_EXPRESSIONS_CAMERA_AWARE: Tuple[str, ...] = (
    "soft smile at the camera",
    "playful grin",
    "warm, easy smile",
    "confident look to the camera",
    "bright, open smile",
    "relaxed, faint smile",
    "amused half-smile",
    "cheerful laugh",
)
_BATCH_EXPRESSIONS_CANDID: Tuple[str, ...] = (
    "soft smile looking away",
    "caught mid-laugh",
    "calm, lids lowered",
    "absorbed in her phone, unaware of the camera",
    "glancing over her shoulder",
    "focused on what she's doing",
    "quietly lost in thought",
    "gazing off to the side",
)
# The full pool (camera-aware first, then candid). ~1/3 candid share is achieved by
# routing every 3rd slot (i % 3 == 2) to the candid subset; see _assign_batch_expressions.
_BATCH_EXPRESSION_POOL: Tuple[str, ...] = (
    _BATCH_EXPRESSIONS_CAMERA_AWARE + _BATCH_EXPRESSIONS_CANDID
)


# ---------------------------------------------------------------------------
# Expression <-> situation compatibility (WS1b real-world-sense guard)
# ---------------------------------------------------------------------------
# Reported failures: bright grins in an intimate scene; bedroom-eyes lowered lids "mid-jog".
# An expression must suit the scene's pose ENERGY, its EXPOSURE and its VENUE. Every pool
# string carries one REGISTER tag; the rules below filter the candidate pool by tag (both at
# pick time in _assign_batch_expressions and in the _enforce_expression_compat repair pass).
# Coverage-tested: every _BATCH_EXPRESSION_POOL string has a tag.
_EXPR_CHEERFUL = "cheerful"   # bright, high-energy grins & laughs
_EXPR_SOFT = "soft"           # gentle, warm smiles
_EXPR_SULTRY = "sultry"       # lowered-lid / intimate
_EXPR_CANDID = "candid"       # camera-unaware, mid-activity
_EXPR_NEUTRAL = "neutral"     # composed, register-flexible

_EXPRESSION_TAGS: Dict[str, str] = {
    # camera-aware register
    "soft smile at the camera": _EXPR_SOFT,
    "playful grin": _EXPR_CHEERFUL,
    "warm, easy smile": _EXPR_SOFT,
    "confident look to the camera": _EXPR_NEUTRAL,
    "bright, open smile": _EXPR_CHEERFUL,
    "relaxed, faint smile": _EXPR_SOFT,
    "amused half-smile": _EXPR_NEUTRAL,
    "cheerful laugh": _EXPR_CHEERFUL,
    # candid register
    "soft smile looking away": _EXPR_SOFT,
    "caught mid-laugh": _EXPR_CHEERFUL,
    "calm, lids lowered": _EXPR_SULTRY,
    "absorbed in her phone, unaware of the camera": _EXPR_CANDID,
    "glancing over her shoulder": _EXPR_CANDID,
    "focused on what she's doing": _EXPR_CANDID,
    "quietly lost in thought": _EXPR_NEUTRAL,
    "gazing off to the side": _EXPR_CANDID,
}

# ATHLETIC pose-class (jogging/squatting) reads wrong with a soft/sultry face -> only the
# high-energy / candid / composed registers.
_ATHLETIC_EXPRESSION_TAGS: frozenset = frozenset({_EXPR_CHEERFUL, _EXPR_CANDID, _EXPR_NEUTRAL})
# HIGH nudity or a NAKED outfit reads wrong with a bright open grin -> only the soft/intimate/
# composed registers.
_EXPOSED_EXPRESSION_TAGS: frozenset = frozenset({_EXPR_SOFT, _EXPR_SULTRY, _EXPR_NEUTRAL})
# The single most intimate state — bedroom-eyes — is out of place in a PUBLIC venue once the
# scene is even mildly revealing (SUGGESTIVE+). Minimal and defensible (one string).
_INTIMATE_EXPRESSIONS: frozenset = frozenset({"calm, lids lowered"})


def _expression_allowed(expr, pose, nudity, location, outfit=None) -> bool:
    """
    Does `expr` suit this scene's pose energy, exposure and venue (WS1b)? An UNTAGGED
    expression (an LLM's free-text — only the curated batch pool is classified) is never
    gated (returns True). Rules:
      * ATHLETIC pose-class -> cheerful/candid/neutral only (no soft/sultry lids mid-jog);
      * HIGH nudity OR a NAKED outfit -> soft/sultry/neutral only (no bright open grins);
      * PUBLIC venue at SUGGESTIVE+ nudity -> exclude the most intimate state(s);
      * everything else unrestricted.
    Pure function of the four scene facts, so both the pick-time filter and the repair pass
    read it the same way.
    """
    tag = _EXPRESSION_TAGS.get(expr)
    if tag is None:
        return True
    if sv.pose_class(pose) == sv.POSE_CLASS_ATHLETIC and tag not in _ATHLETIC_EXPRESSION_TAGS:
        return False
    exposed = (
        _nudity_index(nudity) >= _nudity_index(NudityLevel.HIGH)
        or _val(outfit) == OutfitType.NAKED.value
    )
    if exposed and tag not in _EXPOSED_EXPRESSION_TAGS:
        return False
    if (
        sv.is_public_venue(location)
        and _nudity_index(nudity) >= _nudity_index(NudityLevel.SUGGESTIVE)
        and expr in _INTIMATE_EXPRESSIONS
    ):
        return False
    return True


# ---------------------------------------------------------------------------
# Trait-profile bias maps (WS-B Phase B2)
# ---------------------------------------------------------------------------
# Value-keyed phrase maps handed to _weighted_pick as its `phrase_map`, so likes/dislikes
# finally match real garment/pose WORDS instead of only the enum names:
#   * _OUTFIT_PHRASE_MAP — outfit_vocab.OUTFIT_KEYWORD_PHRASES verbatim (already value-keyed).
#   * _POSE_PHRASE_MAP   — POSE_DESCRIPTIONS re-keyed by pose VALUE (POSE_DESCRIPTIONS is
#                          keyed by PoseType; _enum_keywords wants a value->text map).
# Both are inert when likes/dislikes are empty (no keyword to match -> all weights 1.0),
# so a no-likes batch is byte-identical to the pre-B2 empty-map behavior.
_OUTFIT_PHRASE_MAP: Dict[str, str] = ov.OUTFIT_KEYWORD_PHRASES
_POSE_PHRASE_MAP: Dict[str, str] = {p.value: desc for p, desc in POSE_DESCRIPTIONS.items()}

# Demeanor -> a small set of POSES that read as that demeanor. _pick_pose favours these
# (weight 2.0) WITHIN the beat's own allowed pool, so a shy character leans to reserved
# poses and an energetic one to dynamic ones — a soft nudge, never a filter. Every
# DemeanorType is covered (coverage-tested). Explicit/anatomical poses are deliberately
# excluded (they are already gated by nudity/location, not a demeanor's default vibe).
DEMEANOR_POSE_FAVOR: Dict[DemeanorType, frozenset] = {
    DemeanorType.SHY: frozenset({PoseType.SITTING, PoseType.STANDING_LEANING, PoseType.LYING_STOMACH}),
    DemeanorType.CONFIDENT: frozenset({PoseType.HANDS_BEHIND_HEAD, PoseType.STANDING_LEANING, PoseType.SITTING}),
    DemeanorType.PLAYFUL: frozenset({PoseType.JOGGING, PoseType.EATING, PoseType.HANDS_BEHIND_HEAD}),
    DemeanorType.SULTRY: frozenset({PoseType.LYING_BACK, PoseType.BENDING_OVER, PoseType.KNEELING}),
    DemeanorType.ELEGANT: frozenset({PoseType.STANDING_LEANING, PoseType.SITTING, PoseType.SOFA}),
    DemeanorType.ENERGETIC: frozenset({PoseType.JOGGING, PoseType.SQUATTING, PoseType.HANDS_BEHIND_HEAD}),
    DemeanorType.COZY: frozenset({PoseType.SOFA, PoseType.LYING_STOMACH, PoseType.SITTING}),
    DemeanorType.MYSTERIOUS: frozenset({PoseType.STANDING_LEANING, PoseType.LYING_BACK, PoseType.KNEELING}),
}

# Demeanor -> the batch expression/gaze STRINGS (subset of _BATCH_EXPRESSION_POOL) that
# read as that demeanor. _assign_batch_expressions filters each register (camera-aware /
# candid) to these when a demeanor is set, falling back to the full register when the
# demeanor-consistent subset is too small (<2) — so the candid share, adjacency and usage
# caps are all preserved. Each demeanor lists >=2 camera-aware AND >=2 candid entries so
# both registers can be biased. Coverage-tested against _BATCH_EXPRESSION_POOL.
_DEMEANOR_EXPRESSION_FAVOR: Dict[DemeanorType, frozenset] = {
    DemeanorType.SHY: frozenset({
        "soft smile at the camera", "relaxed, faint smile", "amused half-smile",
        "soft smile looking away", "calm, lids lowered", "quietly lost in thought", "gazing off to the side",
    }),
    DemeanorType.CONFIDENT: frozenset({
        "confident look to the camera", "warm, easy smile", "bright, open smile", "amused half-smile",
        "glancing over her shoulder", "focused on what she's doing",
    }),
    DemeanorType.PLAYFUL: frozenset({
        "playful grin", "cheerful laugh", "amused half-smile", "bright, open smile",
        "caught mid-laugh", "glancing over her shoulder",
    }),
    DemeanorType.SULTRY: frozenset({
        "confident look to the camera", "amused half-smile", "relaxed, faint smile", "soft smile at the camera",
        "glancing over her shoulder", "gazing off to the side", "calm, lids lowered",
    }),
    DemeanorType.ELEGANT: frozenset({
        "soft smile at the camera", "relaxed, faint smile", "warm, easy smile", "confident look to the camera",
        "soft smile looking away", "gazing off to the side", "quietly lost in thought",
    }),
    DemeanorType.ENERGETIC: frozenset({
        "cheerful laugh", "bright, open smile", "playful grin", "warm, easy smile",
        "caught mid-laugh", "focused on what she's doing",
    }),
    DemeanorType.COZY: frozenset({
        "warm, easy smile", "relaxed, faint smile", "soft smile at the camera", "amused half-smile",
        "soft smile looking away", "calm, lids lowered", "quietly lost in thought", "focused on what she's doing",
    }),
    DemeanorType.MYSTERIOUS: frozenset({
        "relaxed, faint smile", "amused half-smile", "confident look to the camera", "soft smile at the camera",
        "gazing off to the side", "quietly lost in thought", "calm, lids lowered", "glancing over her shoulder",
    }),
}


def _coerce_demeanor(v) -> Optional[DemeanorType]:
    """A DemeanorType from an enum or raw value; None when unknown."""
    if v is None:
        return None
    if isinstance(v, DemeanorType):
        return v
    try:
        return DemeanorType(getattr(v, "value", v))
    except (ValueError, TypeError):
        return None


def _demeanor_pose_favor(controls: BatchControls) -> set:
    """Union of DEMEANOR_POSE_FAVOR over the batch's demeanor(s); empty when none set."""
    favored: set = set()
    for d in (getattr(controls, "demeanor", None) or []):
        dd = _coerce_demeanor(d)
        if dd is not None:
            favored |= DEMEANOR_POSE_FAVOR.get(dd, frozenset())
    return favored


def _demeanor_expression_favor(controls: BatchControls) -> set:
    """Union of _DEMEANOR_EXPRESSION_FAVOR over the batch's demeanor(s); empty when none."""
    favored: set = set()
    for d in (getattr(controls, "demeanor", None) or []):
        dd = _coerce_demeanor(d)
        if dd is not None:
            favored |= _DEMEANOR_EXPRESSION_FAVOR.get(dd, frozenset())
    return favored


# ---------------------------------------------------------------------------
# Character container (planner-local; DB-independent)
# ---------------------------------------------------------------------------
@dataclass
class Character:
    persona: PersonaOptions
    likes: List[str] = field(default_factory=list)
    dislikes: List[str] = field(default_factory=list)
    hero_photo_url: Optional[str] = None
    # Optional nude/undressed base of this avatar. When present, the scene mapper uses
    # it as the outfit-swap SOURCE instead of hero_photo_url so a new garment renders
    # onto a clean body rather than fighting the hero's existing clothes. Populated by a
    # later agent; None today -> mapper falls back to hero_photo_url (unchanged behavior).
    nude_base_url: Optional[str] = None
    # Free-text persona/context (characters.context). Story-mode uses it for narrative
    # coherence; inert to beat-slot/pool selection.
    bio: Optional[str] = None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _val(v) -> Optional[str]:
    return ap._val(v)


def _nudity_index(level) -> int:
    try:
        return _NUDITY_LADDER.index(NudityLevel(_val(level)))
    except (ValueError, TypeError):
        return 0


def _time_index(time) -> int:
    """Chronological position of a time_of_day on _TIME_LADDER (0 = earliest).
    Mirrors _nudity_index; falls back to 0 (earliest) on an unknown value."""
    try:
        return _TIME_LADDER.index(TimeOfDayType(_val(time)))
    except (ValueError, TypeError):
        return 0


def _keyword_set(items: Optional[List[str]]) -> set:
    words: set = set()
    for it in items or []:
        for w in re.split(r"[^a-z0-9]+", str(it).lower()):
            if len(w) >= 3:
                words.add(w)
    return words


def _enum_keywords(value, phrase_map: dict) -> set:
    key = _val(value) or ""
    text = key.replace("_", " ") + " " + phrase_map.get(key, "")
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w}


def _coerce_enum(enum_cls, value, *, allow_none: bool = False):
    """Coerce a raw value to an enum, repairing near-misses via difflib. None-safe."""
    if value is None:
        return None if allow_none else None
    if isinstance(value, enum_cls):
        return value
    raw = _val(value)
    if raw is None:
        return None
    raw = str(raw).strip().lower()
    valid = {e.value: e for e in enum_cls}
    if raw in valid:
        return valid[raw]
    match = difflib.get_close_matches(raw, list(valid.keys()), n=1, cutoff=0.6)
    if match:
        return valid[match[0]]
    return None


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------
class StoryPlanner(ABC):
    name: str = "base"
    supports_nsfw: bool = True

    @abstractmethod
    async def plan_scenes(
        self, character: Character, count: int, controls: BatchControls
    ) -> List[SceneSpec]:
        ...


# ---------------------------------------------------------------------------
# Beat-pool filtering — shared by the deterministic planner (picks from these
# pools) and the Venice planner (must pick from these SAME pools). Keeping one
# copy of the filter logic is what guarantees both providers can only ever
# produce combinations that already appear together in a hand-authored
# BeatTemplate (services/story_templates.py) — an outfit can never be paired
# with a location/pose it wasn't authored alongside.
# ---------------------------------------------------------------------------
def _allowed_pose_pool(tmpl, controls: BatchControls) -> List[PoseType]:
    pool = [p for p in tmpl.pose_pool if p not in (controls.blocked_poses or [])]
    # POSE PACK ref latch: drop any pose whose reference PNG is not installed, so the planner
    # never picks a pose the render can't reference (load_pose_reference_b64 would raise). Every
    # pose an authored template pools today ships WITH a ref -> this is a strict NO-OP here (the
    # pool is byte-identical), but it hard-guards a future template that pools a pose before its
    # PNG lands, and it is the sibling of the same filter in _controls_pose_vocab (the fallback
    # vocab) that keeps the effective pose vocabulary identical to the pre-POSE-PACK baseline.
    pool = [p for p in pool if has_pose_ref(p)]
    # WS-P pick-time compat: an ATHLETIC pose (jogging/squatting) can only ever pair
    # incoherently when the batch's effective wardrobe has NO athletic-compatible outfit — so
    # remove athletic poses from the pool up front in that case (drop the pose, NEVER the outfit:
    # the wardrobe is identity). This is a formal-wardrobe character (e.g. velvet/maxi dresses)
    # never being served "jogging". The any()-guard keeps this a strict NO-OP — byte-identical
    # pool — for every beat that offers no athletic pose, and for every batch that DOES own an
    # athletic-compatible outfit (the all-compatible regression-lock case). The repair-time pass
    # (_enforce_pose_compat) is the precise per-scene backstop when SOME athletic outfit exists.
    if any(p in ATHLETIC_POSES for p in pool) and not _athletic_poses_allowed(controls):
        pool = [p for p in pool if p not in ATHLETIC_POSES]
    return pool


def _prefer_wardrobe(
    pool: List[OutfitType], controls: BatchControls, *, min_keep: int = 2
) -> List[OutfitType]:
    """
    Soft wardrobe bias (WS-B). When the batch carries controls.wardrobe_outfits, keep only
    the outfits in that set (PLUS any uniform — the four _UNIFORM_OUTFITS are ALWAYS retained
    so a work chapter keeps its uniform regardless of taste) — but ONLY when at least
    ``min_keep`` survive; otherwise return `pool` unchanged. This is the "intersect with
    fallback, never empties" rule: a strong bias that still preserves variety and never
    strands a beat with too few (or zero) options. A no-op — pool returned as-is — when the
    batch has no wardrobe_outfits (so the pre-B2 behavior is byte-identical). Order is
    preserved (a stable slice of `pool`). This is the SINGLE choke point: _allowed_outfit_pool
    routes every deterministic pick, beat-pool repair, Venice menu and slot-based variety
    candidate through it, and the fill / exposure-cap re-pick pools apply it too.
    """
    wardrobe = getattr(controls, "wardrobe_outfits", None)
    if not wardrobe:
        return pool
    ws = set(wardrobe)
    soft = [o for o in pool if o in ws or o in _UNIFORM_OUTFITS]
    return soft if len(soft) >= min_keep else pool


def _allowed_outfit_pool(tmpl, controls: BatchControls) -> List[OutfitType]:
    pool = []
    for o in tmpl.outfit_pool:
        if controls.sfw_only and o == OutfitType.NAKED:
            continue
        if o in (controls.blocked_outfits or []):
            continue
        if controls.allowed_outfits and o not in controls.allowed_outfits:
            continue
        pool.append(o)
    # Soft wardrobe bias LAST, after the hard allow/block filters (never empties; no-op
    # when the batch carries no wardrobe_outfits — see _prefer_wardrobe).
    return _prefer_wardrobe(pool, controls, min_keep=2)


def _allowed_location_pool(tmpl, controls: BatchControls) -> List[LocationType]:
    pool = []
    for loc in tmpl.location_pool:
        if loc in (controls.blocked_locations or []):
            continue
        if controls.allowed_locations and loc not in controls.allowed_locations:
            continue
        pool.append(loc)
    return pool


# Photo styles that read as an unstaged/candid photo rather than a styled shoot. Raw
# string values (not enum members), mirroring scene_mapper.py's _SOFT_PHOTO_STYLES —
# kept as its own copy per this module's existing convention of self-contained
# pool-filter constants (e.g. _NUDITY_LADDER/_TIME_LADDER above) rather than a
# cross-module import of a private name.
_NATURAL_PHOTO_STYLES = ("natural", "candid_phone")

# Substrings that mark a LIGHTING_PHRASES entry as a staged/theatrical light rather
# than an unstaged snapshot's — matched against the rendered PHRASE TEXT (not the enum
# key), so a multi-word phrase like "rim lighting" matches even though its enum value
# is "backlit_rim". Derived from the actual scene_vocab.LIGHTING_PHRASES pool: excludes
# moody_dim ("moody dim low-key lighting"), neon ("vivid neon lighting") and backlit_rim
# ("dramatic backlit rim lighting"); keeps natural_soft, bright_daylight, golden_warm,
# candlelit, studio_softbox, overcast untouched.
_DRAMATIC_LIGHTING_KEYWORDS = ("dramatic", "backlit", "rim lighting", "spotlight", "neon", "moody")


def _allowed_lighting_pool(tmpl, controls: BatchControls, location=None) -> List[LightingType]:
    """
    Lighting pool for a beat, narrowed for:
      1. venue sanity — LIGHTING_LOCATION_COMPAT (defined below, near LOCATION_TIME_
         COMPAT), when `location` is given: the beat's authored lighting_pool
         intersected with what `location` allows (a single LocationType/value, or an
         iterable of candidates — the Venice per-beat menu offers several location
         options at once, so the UNION of what each permits is used, a permissive
         superset; the FINAL choice is narrowed for real by
         _enforce_lighting_location_compat once the provider settles on one location).
         Empty intersection -> the location's FULL allowed set, not the raw pool (venue
         sanity wins over beat authorship). `location=None` skips this step entirely —
         byte-identical to the pre-venue-sanity pool for any caller that opts out.
      2. photo_style natural/candid_phone (PROMPT DE-GLOSS: a "natural" batch was still
         landing dramatic/theatrical light — see _DRAMATIC_LIGHTING_KEYWORDS /
         _is_dramatic_lighting). polished/studio and every other style skip this step
         (byte-identical to whatever step 1 produced).

    Safe fallback chain (natural/candid_phone only): if step 2 would empty step 1's
    result (a beat/location combo with no non-dramatic overlap — e.g. a night-club beat
    whose ONLY authored options are neon/moody), fall back to `location`'s FULL allowed
    set filtered the same way, THEN — only with no `location` context at all — the
    pre-venue-sanity "a theatrical light beats no light" fallback (the historical
    behavior, unchanged). natural_soft belongs to EVERY location's LIGHTING_LOCATION_
    COMPAT set (coverage-tested), so once `location` is known this chain can never
    actually land on a dramatic value — this is what closes the moody_dim leak: three
    hand-authored beats (office/night_out/friends_and_date's "after hours" beat) offer
    ONLY theatrical lighting, so filtering for natural used to empty the pool and the old
    fallback reinstated the raw, still-100%-dramatic pool. Callers filter BEFORE the
    seeded rng.choice pick (never re-draw), so this never disturbs determinism, and every
    returned list is ordered by LightingType's own declaration order (never a raw set/
    frozenset iteration — see _ordered_lighting), so the pick reproduces across process
    restarts too.
    """
    pool = _lighting_location_pool(list(tmpl.lighting_pool), location)
    if _val(controls.photo_style) not in _NATURAL_PHOTO_STYLES:
        return pool
    filtered = [li for li in pool if not _is_dramatic_lighting(li)]
    if filtered:
        return filtered
    if location is not None:
        loc_filtered = [
            li for li in _ordered_lighting(_lighting_locations_allowed(location))
            if not _is_dramatic_lighting(li)
        ]
        if loc_filtered:
            return loc_filtered
    return filtered or pool


# ---------------------------------------------------------------------------
# Deterministic planner (always available, seedable, NSFW-safe)
# ---------------------------------------------------------------------------
class DeterministicScenePlanner(StoryPlanner):
    name = "deterministic"
    supports_nsfw = True

    async def plan_scenes(
        self, character: Character, count: int, controls: BatchControls
    ) -> List[SceneSpec]:
        return self.plan_scenes_sync(character, count, controls)

    def plan_scenes_sync(
        self, character: Character, count: int, controls: BatchControls
    ) -> List[SceneSpec]:
        seed = controls.base_seed if controls.base_seed is not None else 0
        rng = random.Random(seed)

        occ = _val(character.persona.occupation)
        arcs = _plan_arcs(character, count, controls)

        like_kw = _keyword_set(character.likes)
        dislike_kw = _keyword_set(character.dislikes)

        # Story mode: a simple templated story so a Venice-off batch is never blank.
        story_mode = getattr(controls, "story_mode", False)
        name = character.persona.name
        story_title = st.deterministic_story_title(name, occ or "") if story_mode else None

        # Per-photo nudity arc (guided ceiling). The deterministic planner assigns
        # ramp[gidx] as each beat's level exactly; validate_and_repair reuses the same
        # ramp as a per-photo ceiling. tmpl.nudity_bias is now a legacy field (unused).
        ramp = _nudity_ramp(count, controls)
        # Per-photo time-of-day curve (chronological, resets each day). Assigned
        # positionally like the nudity ramp — NOT rng.choice per beat, which made
        # time bounce within a block — but snapped to each beat's own time_pool so a
        # curated time never overrides scene coherence (nearest-allowed fallback).
        time_ramp = _time_ramp(count, controls.period_days)

        scenes: List[SceneSpec] = []
        gidx = 0
        for arc, beat_count in arcs:
            for b in range(beat_count):
                tmpl = arc.beats[b % len(arc.beats)]
                # Vary the caption once the arc's short beat pool wraps, so a stretched
                # arc doesn't emit byte-identical beat_description text (verbatim repeats).
                beat_desc = _vary_beat_description(tmpl.beat_description, b // len(arc.beats))
                pose = self._pick_pose(tmpl, rng, like_kw, dislike_kw, controls)
                outfit = self._pick_outfit(tmpl, rng, like_kw, dislike_kw, controls)
                location = self._pick_location(tmpl, rng, like_kw, dislike_kw, controls)
                nudity = ramp[gidx] if gidx < len(ramp) else NudityLevel.LOW
                # WS1a pick-time coherence: narrow the beat's time_pool to what reads as
                # real at THIS scene's (already-picked) location BEFORE the RNG-free
                # nearest-time snap, so e.g. a night venue never lands at midday. Falls back
                # to the full pool if the intersection is empty (see _time_compat_pool).
                time_pool = _time_compat_pool(location, tmpl.time_pool)
                time_of_day = _nearest_time_in_pool(
                    time_ramp[gidx] if gidx < len(time_ramp) else time_pool[0], time_pool
                )
                narrative = None
                if story_mode:
                    mood = sv.scene_mood_phrase(character.persona.kinks, character.persona.personality)
                    narrative = st.deterministic_beat_narrative(name, beat_desc, mood, gidx)
                scenes.append(
                    SceneSpec(
                        arc_id=arc.arc_id,
                        arc_title=arc.arc_title,
                        beat_index=b,
                        global_index=gidx,
                        beat_description=beat_desc,
                        pose=pose,
                        outfit=outfit,
                        nudityLevel=nudity,
                        location=location,
                        time_of_day=time_of_day,
                        # Filtered for venue sanity (LIGHTING_LOCATION_COMPAT, keyed to the
                        # already-picked `location`) THEN photo_style natural/candid_phone
                        # (excludes theatrical phrases like "dramatic backlit rim lighting")
                        # BEFORE this seeded pick, so determinism is preserved — see
                        # _allowed_lighting_pool.
                        lighting=rng.choice(_allowed_lighting_pool(tmpl, controls, location=location)),
                        # mood_kinks/mood_personality are assigned below to a seeded ~1/3
                        # eligible subset (never on LOW/public scenes) so the batch stops
                        # ending every card on the same "sultry, seductive" mood tail.
                        mood_kinks=None,
                        mood_personality=None,
                        seed=_derive_seed(controls, gidx),
                        narrative=narrative,
                        story_title=story_title,
                    )
                )
                gidx += 1
        # A2 / mood-monotony: populate per-item expression (variety) and gate the mood tags
        # to a seeded ~1/3 eligible subset. Both use dedicated offset RNGs so none of the
        # per-beat draws above shift (existing reproducibility is byte-identical bar these
        # two fields).
        _assign_batch_expressions(scenes, controls)
        _assign_batch_moods(character, scenes, controls)
        return scenes

    @staticmethod
    def _select_and_size_arcs(arcs, count: int, arc_count_override: Optional[int]):
        n_arcs = arc_count_override or _auto_arc_count(count)
        n_arcs = max(1, min(n_arcs, len(arcs)))
        chosen = list(arcs[:n_arcs])
        # Distribute `count` beats across arcs as evenly as possible (front-loaded remainder).
        base, rem = divmod(count, n_arcs)
        sizes = [base + (1 if i < rem else 0) for i in range(n_arcs)]
        return [(arc, size) for arc, size in zip(chosen, sizes) if size > 0]

    def _pick_pose(self, tmpl, rng, like_kw, dislike_kw, controls):
        pool = _allowed_pose_pool(tmpl, controls)
        if not pool:
            return None
        # Real pose phrase map (likes match pose words now) + demeanor-favored poses (2.0)
        # + culture favored_poses (3.0, via favored_strong). Culture only RE-WEIGHTS poses
        # already inside the beat's authored pool — it never adds a pose the beat didn't
        # author (the candidate pool stays _allowed_pose_pool output).
        return _weighted_pick(
            pool, rng, like_kw, dislike_kw, _POSE_PHRASE_MAP,
            favored=_demeanor_pose_favor(controls), favored_weight=2.0,
            favored_strong=set(getattr(controls, "favored_poses", None) or []),
        )

    def _pick_outfit(self, tmpl, rng, like_kw, dislike_kw, controls):
        pool = _allowed_outfit_pool(tmpl, controls)
        if not pool:
            return None  # skip outfit step for this scene
        # Real garment phrase map (likes match garment words now) + favored outfits (3.0).
        return _weighted_pick(
            pool, rng, like_kw, dislike_kw, _OUTFIT_PHRASE_MAP,
            favored=set(controls.favored_outfits or []),
        )

    def _pick_location(self, tmpl, rng, like_kw, dislike_kw, controls):
        pool = _allowed_location_pool(tmpl, controls)
        if not pool:
            # Location is required — fall back to an allowed/neutral location.
            if controls.allowed_locations:
                pool = list(controls.allowed_locations)
            else:
                pool = [
                    loc
                    for loc in LocationType
                    if loc not in (controls.blocked_locations or [])
                ] or [LocationType.HOME_LIVING_ROOM]
        return _weighted_pick(
            pool, rng, like_kw, dislike_kw, sv.LOCATION_PHRASES,
            favored=set(controls.favored_locations or []),
        )


@dataclass(frozen=True)
class _BeatSlot:
    """One position in the beat sequence: which arc it belongs to, and the
    hand-authored BeatTemplate (pools) that position must draw from."""
    arc_id: str
    arc_title: str
    beat_in_arc: int
    tmpl: "st.BeatTemplate"


def _plan_arcs(character: Character, count: int, controls: BatchControls) -> List[Tuple["st.ArcTemplate", int]]:
    """
    The ordered (arc, beat_count) plan for the whole batch — the SINGLE source of
    arc selection + sizing, shared by the deterministic planner (plan_scenes_sync)
    and the beat-slot builder (_beat_slots, which feeds the Venice prompt and
    validate_and_repair), so every path agrees on which arc fills which beat.

    period_days<=1: her occupation's arc set (or GENERIC_ARCS), sized across all
    `count` beats — the original single-day behavior, unchanged.

    period_days>1: split `count` into per-day beat budgets (_day_sizes), then size
    EACH day's OWN arc pool to that day's budget. Day 0 is her occupation day (the
    occupation arcs, as today); days 1+ draw from the leisure/day-off pools, rotated
    per day (st.leisure_arcs_for_day), so a multi-day batch reads as different real
    days — a day off, errands, a night out — instead of the same workday repeated.
    """
    occ = _val(character.persona.occupation)
    occ_arcs = st.ARC_TEMPLATES.get(occ, st.GENERIC_ARCS)
    sizes = _day_sizes(count, controls.period_days)
    if len(sizes) <= 1:
        return DeterministicScenePlanner._select_and_size_arcs(occ_arcs, count, controls.arc_count)
    plan: List[Tuple["st.ArcTemplate", int]] = []
    for day_idx, day_count in enumerate(sizes):
        if day_count <= 0:
            continue
        day_arcs = occ_arcs if day_idx == 0 else st.leisure_arcs_for_day(day_idx)
        plan.extend(
            DeterministicScenePlanner._select_and_size_arcs(day_arcs, day_count, controls.arc_count)
        )
    return plan


def _beat_slots(character: Character, count: int, controls: BatchControls) -> List[_BeatSlot]:
    """
    The ordered sequence of beat slots (one per global beat index, 0..count-1)
    that the deterministic planner would use for this character/count/controls
    — same arc selection, same sizing, same occupation lookup, same day rotation
    (all via _plan_arcs). Shared by the Venice prompt builder (presents each beat's
    own allowed pools) and validate_and_repair (enforces every provider's picks stay
    inside them), so "which combinations are possible" is defined in exactly one
    place (services/story_templates.py) regardless of which planner ran.
    """
    slots: List[_BeatSlot] = []
    for arc, beat_count in _plan_arcs(character, count, controls):
        for b in range(beat_count):
            slots.append(_BeatSlot(arc.arc_id, arc.arc_title, b, arc.beats[b % len(arc.beats)]))
    return slots


def _auto_arc_count(count: int) -> int:
    return max(2, min(round(count / 6) or 1, 5))


def _derive_seed(controls: BatchControls, gidx: int) -> Optional[int]:
    strategy = _val(controls.seed_strategy)
    if controls.base_seed is None:
        return None
    if strategy == "fixed":
        return controls.base_seed
    if strategy == "per_item":
        return ((controls.base_seed + gidx * 7919) % 1_000_000_000) or 1
    return None  # random -> worker chooses


def _day_sizes(count: int, period_days: int) -> List[int]:
    """
    Beat budget per day: split `count` beats across the story's days, front-loading
    the remainder (the same divmod idiom _select_and_size_arcs uses to size arcs).
    Never more days than beats (a story can't have an empty day), so period_days is
    capped at `count`. Shared by _time_ramp (the time curve) and _plan_arcs (the arc
    rotation) so both agree on exactly where each day starts and ends.
    """
    n = max(count, 0)
    if n == 0:
        return []
    days = max(1, min(period_days or 1, n))
    base, rem = divmod(n, days)
    return [base + (1 if i < rem else 0) for i in range(days)]


def _nudity_ramp(count: int, controls: BatchControls) -> List[NudityLevel]:
    """
    Per-photo nudity arc for a batch — the guided-ceiling ladder.

    Returns `count` levels, one per global beat index, monotonically non-decreasing
    from a start level up to controls.max_nudity (the finish + ceiling). Used two ways:
      * the deterministic planner assigns ramp[gidx] as each beat's level exactly;
      * validate_and_repair uses ramp[i] as a per-photo CEILING (clamps down, never up).

    Start level = controls.start_nudity if given, else derived from escalation
    ('building' -> low, 'flat' -> max_nudity), clamped to the ceiling. sfw_only -> all
    LOW. count <= 1 -> [max] (a single photo lands at the finish level). This makes
    'flat' + no start_nudity a constant-at-max ramp, i.e. identical to the old
    max-only ceiling behavior (back-compat); 'building' + no start_nudity rises
    low -> max and is now actually enforced.
    """
    n = max(count, 0)
    if controls.sfw_only:
        return [NudityLevel.LOW] * n
    max_idx = _nudity_index(controls.max_nudity)
    if n <= 1:
        return [_NUDITY_LADDER[max_idx]] * n
    if controls.start_nudity is not None:
        start_idx = min(_nudity_index(controls.start_nudity), max_idx)
    elif _val(controls.escalation) == "building":
        start_idx = 0
    else:  # flat (or any unknown escalation) -> constant at the ceiling
        start_idx = max_idx
    span = max_idx - start_idx
    ramp: List[NudityLevel] = []
    for gidx in range(n):
        idx = start_idx + int((gidx / (n - 1)) * span + 1e-9)
        ramp.append(_NUDITY_LADDER[max(0, min(idx, max_idx))])
    return ramp


def _time_ramp(count: int, period_days: int) -> List[TimeOfDayType]:
    """
    Per-photo time-of-day curve for a batch — the chronological sibling of
    _nudity_ramp. Returns `count` times, one per global beat index, that flow
    early_morning -> night ONCE PER DAY and reset at each new day's first beat, so
    a batch's time never bounces around within a block (the reported bug: the
    deterministic planner used to pick time_of_day at random per beat).

    `count` beats are split across `period_days` days (front-loaded remainder, via
    _day_sizes). Within a day's span the walk is monotonically non-decreasing along
    _TIME_LADDER: a day shorter than the 7-slot ladder samples it evenly (spread
    across the whole day, not clustered at dawn — 3 beats land near dawn/midday/
    night, not early_morning/morning/daytime); a day longer than 7 holds adjacent
    beats on the same time (still monotonic, just repeated). A 1-beat day (incl.
    count==1) is a single midday-ish value — a sensible representative, never a
    crash. Used two ways: the deterministic planner assigns it per beat (snapped to
    each beat's allowed time_pool), and validate_and_repair re-applies it as a
    safety net for LLM output that ignored the TIME PLAN.
    """
    n = max(count, 0)
    if n == 0:
        return []
    ladder_len = len(_TIME_LADDER)
    ramp: List[TimeOfDayType] = []
    for size in _day_sizes(n, period_days):
        for j in range(size):
            if size <= 1:
                idx = ladder_len // 2  # a single-beat day -> one representative midday-ish time
            else:
                idx = round(j * (ladder_len - 1) / (size - 1))  # even spread, first->last = dawn->night
            ramp.append(_TIME_LADDER[idx])
    return ramp


def _nearest_time_in_pool(target: TimeOfDayType, pool: Tuple[TimeOfDayType, ...]) -> TimeOfDayType:
    """
    The allowed time closest to `target` by chronological (ladder) distance — the
    curated ramp value if the beat's own hand-authored time_pool permits it, else
    the nearest in-pool time. Coherence wins over a perfect curve: a beat authored
    for daytime (e.g. "cooking breakfast") is never forced to "night" just because
    the ramp points there; it snaps to the closest time the beat actually allows.
    Ties break toward the earlier time (deterministic). Empty pool -> `target`.
    """
    if not pool or target in pool:
        return target
    ti = _time_index(target)
    return min(pool, key=lambda t: (abs(_time_index(t) - ti), _time_index(t)))


# ---------------------------------------------------------------------------
# Time-of-day <-> location coherence (WS1a real-world-sense guard)
# ---------------------------------------------------------------------------
# The reported failure: a "vibrant nightclub" scene set "in the middle of the day".
# The nudity/time ramps and the repair passes pick time and location INDEPENDENTLY (and
# can relocate a scene after its time was set), so a night venue can land at midday and a
# beach at night. LOCATION_TIME_COMPAT is the coherence table: the set of TimeOfDayType
# each place reads as real at. Grouped by named time-sets below; EVERY LocationType value
# is covered (coverage-tested). Enforced two ways, mirroring the nudity ceiling: at pick
# time the deterministic planner snaps time into this set (filtered BEFORE the — RNG-free
# — nearest-time pick, so determinism holds), and _enforce_time_location_compat repairs
# any provider's output on the FINAL location. The rule NEVER relocates — it moves the
# TIME to the nearest allowed value (chronological distance), because the location was
# chosen for scene coherence and the pose/outfit/nudity all hang off it.
_T = TimeOfDayType
# daylight only (dawn -> midday)
_TIME_DAYLIGHT = frozenset({_T.EARLY_MORNING, _T.MORNING, _T.DAYTIME})
# outdoor daylight + the pretty end-of-day light, but no dusk/night (a beach/park at
# "night" reads wrong; golden_hour/sunset are the late boundary).
_TIME_OUTDOOR = _TIME_DAYLIGHT | {_T.GOLDEN_HOUR, _T.SUNSET}
# indoor public/business that closes by night: everything EXCEPT night.
_TIME_NO_NIGHT = _TIME_OUTDOOR | {_T.EVENING}
# dining venues run midday into the night (dinner service), but not pre-dawn.
_TIME_DINING = frozenset({_T.MORNING, _T.DAYTIME, _T.GOLDEN_HOUR, _T.SUNSET, _T.EVENING, _T.NIGHT})
# nightlife only lights up in the evening/night.
_TIME_NIGHTLIFE = frozenset({_T.EVENING, _T.NIGHT})
# anytime — private/flexible interiors that read fine day or night.
_TIME_ANY = frozenset(_T)

LOCATION_TIME_COMPAT: Dict[str, frozenset] = {
    # --- private / flexible interiors + rooftop/stage (day or night both read fine) ---
    LocationType.HOME_BEDROOM.value: _TIME_ANY,
    LocationType.HOME_LIVING_ROOM.value: _TIME_ANY,
    LocationType.HOME_KITCHEN.value: _TIME_ANY,
    LocationType.HOME_BATHROOM.value: _TIME_ANY,
    LocationType.HOME_BALCONY.value: _TIME_ANY,
    LocationType.HOME_OFFICE.value: _TIME_ANY,
    LocationType.HOTEL_ROOM.value: _TIME_ANY,
    LocationType.PHOTO_STUDIO.value: _TIME_ANY,      # closed set, artificial light
    LocationType.LUXURY_LOUNGE.value: _TIME_ANY,     # exclusive VIP interior
    LocationType.CAR_INTERIOR.value: _TIME_ANY,
    LocationType.ROOFTOP.value: _TIME_ANY,           # rooftop terrace/bar works dawn->night
    LocationType.STAGE.value: _TIME_ANY,             # daytime rehearsal or night show
    # --- indoor public / business: no night (closes) ---
    LocationType.OFFICE.value: _TIME_NO_NIGHT,
    LocationType.HOSPITAL_WARD.value: _TIME_NO_NIGHT,
    LocationType.CLASSROOM.value: _TIME_NO_NIGHT,
    LocationType.LIBRARY.value: _TIME_NO_NIGHT,
    LocationType.LAB.value: _TIME_NO_NIGHT,
    LocationType.SALON.value: _TIME_NO_NIGHT,
    LocationType.GYM.value: _TIME_NO_NIGHT,
    LocationType.YOGA_STUDIO.value: _TIME_NO_NIGHT,
    LocationType.CAFE.value: _TIME_NO_NIGHT,
    # --- dining (open into the night) ---
    LocationType.RESTAURANT.value: _TIME_DINING,
    LocationType.RESTAURANT_KITCHEN.value: _TIME_DINING,
    # --- outdoors: daylight + golden/sunset, no deep night ---
    LocationType.BEACH.value: _TIME_OUTDOOR,
    LocationType.PARK.value: _TIME_OUTDOOR,
    LocationType.POOLSIDE.value: _TIME_OUTDOOR,
    LocationType.FOREST_TRAIL.value: _TIME_OUTDOOR,
    LocationType.GARDEN.value: _TIME_OUTDOOR,
    LocationType.CITY_STREET.value: _TIME_OUTDOOR,
    # --- nightlife: evening/night only ---
    LocationType.NIGHTCLUB.value: _TIME_NIGHTLIFE,
    LocationType.BAR.value: _TIME_NIGHTLIFE,
}


def _times_allowed_at(location) -> frozenset:
    """Allowed TimeOfDayType set for a location (enum or value); unmapped/unknown ->
    _TIME_ANY (permissive default, so a new location degrades to 'anytime' not a crash)."""
    return LOCATION_TIME_COMPAT.get(_val(location), _TIME_ANY)


def _time_ok_at(time, location) -> bool:
    """True iff `time` reads as real at `location` (LOCATION_TIME_COMPAT)."""
    try:
        t = TimeOfDayType(_val(time))
    except (ValueError, TypeError):
        return True
    return t in _times_allowed_at(location)


def _nearest_allowed_time(target, location) -> TimeOfDayType:
    """The location-allowed time closest to `target` by chronological distance (ties ->
    earlier), used by both the pick-time snap and _enforce_time_location_compat. `target`
    already allowed -> returned unchanged. Empty allow-set (never happens — every entry is
    non-empty) -> `target` coerced. Coerces `target` and delegates to _nearest_time_in_pool
    over the location's allowed set — the SAME nearest-in-pool logic the beat-time snap uses."""
    try:
        tgt = TimeOfDayType(_val(target))
    except (ValueError, TypeError):
        tgt = _TIME_LADDER[0]
    return _nearest_time_in_pool(tgt, tuple(_times_allowed_at(location)))


def _time_compat_pool(
    location, pool: Tuple[TimeOfDayType, ...]
) -> Tuple[TimeOfDayType, ...]:
    """
    A beat's time_pool narrowed to the times that also read as real at `location`
    (LOCATION_TIME_COMPAT) — the pick-time coherence filter. Applied BEFORE the RNG-free
    _nearest_time_in_pool snap in the deterministic planner, so a beat that authored a
    location+time pair the compat table forbids (the one authored case is "late at the
    office" @ night, which this trims to evening) never emits the incoherent value. Falls
    back to the ORIGINAL pool if the intersection is empty (a beat whose whole time_pool is
    disallowed at a location) — coherence is then finished by the repair pass; a partial
    filter never strands the pick. No-op (returns the pool unchanged, same object order)
    whenever every time already fits, so a coherent beat is byte-identical.
    """
    filtered = tuple(t for t in pool if _time_ok_at(t, location))
    return filtered or tuple(pool)


# ---------------------------------------------------------------------------
# Lighting <-> location coherence (WS-LIGHT real-world-sense guard)
# ---------------------------------------------------------------------------
# There was NO lighting<->venue rule at all: candlelit at a daytime cafe, or studio
# softbox lighting anywhere, was equally "legal" before this table existed. A related,
# sneakier bug this closes: a photo_style=natural batch — which must NEVER show
# theatrical light (_DRAMATIC_LIGHTING_KEYWORDS / _is_dramatic_lighting) — still
# occasionally landed moody_dim, because three hand-authored beats (office/night_out/
# friends_and_date's "after hours" beat) offer ONLY theatrical lighting
# ((moody_dim, neon), nothing else); filtering that pool for "natural" emptied it, and
# the old "a theatrical light beats no light" fallback returned the still-100%-dramatic
# raw pool. LIGHTING_LOCATION_COMPAT is the coherence table (mirrors LOCATION_TIME_COMPAT
# exactly in shape): the set of LightingType values each place reads as real under. EVERY
# LocationType value is covered (coverage-tested), and every entry contains AT LEAST
# natural_soft — which is also the ONLY value guaranteed to survive the natural-style
# dramatic filter — so falling back to a location's full allowed set (see
# _allowed_lighting_pool) can now never resolve to a dramatic value: the moody_dim leak's
# exact hole is closed structurally, not just patched at the three beats that triggered it.
#
# Enforced two ways, mirroring the time guard: at pick time the pool is intersected with
# the location's allowed set BEFORE the natural-style filter (deterministic planner,
# Venice per-beat menu, and the beat-pool repair — see _allowed_lighting_pool), and
# _enforce_lighting_location_compat repairs any provider's output on the FINAL location.
# Unlike time there is no "chronological nearest" concept for light, so the repair (and
# apply_item_scene_edit's edit-time snap) both settle on the FIRST allowed value in
# LightingType's own declaration order — deterministic, and natural_soft-first by
# construction, so an incoherent edit/repair defaults to the safest, most neutral light.
_LI = LightingType

# Locations with no real window/daylight character: closed sets, artificial-light-only
# venues, or curated interiors LOCATION_PHRASES gives no daylight read to (a "dimly lit
# cocktail bar", an "exclusive VIP interior", a parked car's small cabin, photo_studio's
# "closed set, artificial light" — the same note LOCATION_TIME_COMPAT makes for it — and
# a theatrical stage). Backs bright_daylight/overcast and the "+windowed" half of
# golden_warm below: every OTHER location gets those (the permissive default, so a new
# LocationType degrades to "gets daylight" rather than a crash).
_LIGHT_NO_WINDOW: frozenset = frozenset({
    LocationType.PHOTO_STUDIO.value,
    LocationType.STAGE.value,
    LocationType.NIGHTCLUB.value,
    LocationType.BAR.value,
    LocationType.LUXURY_LOUNGE.value,
    LocationType.CAR_INTERIOR.value,
})
_LIGHT_DAYLIT: frozenset = frozenset(
    loc.value for loc in LocationType if loc.value not in _LIGHT_NO_WINDOW
)

# golden_warm additionally reaches two of the no-window venues that still read as a
# "cozy warm glow" without a literal window: a plush lounge's ambient light, and the
# cinematic golden light through a parked car's glass.
_LIGHT_COZY_EXTRA: frozenset = frozenset({
    LocationType.LUXURY_LOUNGE.value, LocationType.CAR_INTERIOR.value,
})

# Evening-romantic interiors a candlelit dinner/bath/bedroom reads as real in: dining
# (restaurant — NOT restaurant_kitchen, a steel-counter service kitchen is never
# candlelit, see LOCATION_PHRASES), every home_* room, hotel_room, luxury_lounge, bar.
_LIGHT_CANDLELIT: frozenset = frozenset({
    LocationType.RESTAURANT.value,
    LocationType.HOME_BEDROOM.value, LocationType.HOME_LIVING_ROOM.value,
    LocationType.HOME_KITCHEN.value, LocationType.HOME_BATHROOM.value,
    LocationType.HOME_BALCONY.value, LocationType.HOME_OFFICE.value,
    LocationType.HOTEL_ROOM.value, LocationType.LUXURY_LOUNGE.value, LocationType.BAR.value,
})

_LIGHT_STUDIO_SET: frozenset = frozenset({LocationType.PHOTO_STUDIO.value, LocationType.STAGE.value})
_LIGHT_BACKLIT_SET: frozenset = frozenset({
    LocationType.PHOTO_STUDIO.value, LocationType.STAGE.value, LocationType.NIGHTCLUB.value,
})
_LIGHT_NEON_SET: frozenset = frozenset({
    LocationType.NIGHTCLUB.value, LocationType.BAR.value, LocationType.STAGE.value,
})
_LIGHT_MOODY_SET: frozenset = frozenset({
    LocationType.NIGHTCLUB.value, LocationType.BAR.value, LocationType.STAGE.value,
    LocationType.HOTEL_ROOM.value, LocationType.HOME_BEDROOM.value, LocationType.LUXURY_LOUNGE.value,
})

# lighting -> locations, authored per the rules in the section docstring above (the
# readable source of truth); LIGHTING_LOCATION_COMPAT (location -> lightings, matching
# LOCATION_TIME_COMPAT's own shape) is DERIVED from this by inversion below, so the two
# views can never drift apart (mirrors scene_vocab.HOME_LIKE_LOCATIONS's derivation).
_LIGHTING_TO_LOCATIONS: Dict[str, frozenset] = {
    _LI.NATURAL_SOFT.value: frozenset(loc.value for loc in LocationType),  # universal
    _LI.BRIGHT_DAYLIGHT.value: _LIGHT_DAYLIT,
    _LI.OVERCAST.value: _LIGHT_DAYLIT,
    _LI.GOLDEN_WARM.value: _LIGHT_DAYLIT | _LIGHT_COZY_EXTRA,
    _LI.CANDLELIT.value: _LIGHT_CANDLELIT,
    _LI.STUDIO_SOFTBOX.value: _LIGHT_STUDIO_SET,
    _LI.BACKLIT_RIM.value: _LIGHT_BACKLIT_SET,
    _LI.NEON.value: _LIGHT_NEON_SET,
    _LI.MOODY_DIM.value: _LIGHT_MOODY_SET,
}

LIGHTING_LOCATION_COMPAT: Dict[str, frozenset] = {
    loc.value: frozenset(
        li for li in LightingType if loc.value in _LIGHTING_TO_LOCATIONS[li.value]
    )
    for loc in LocationType
}


def _ordered_lighting(members) -> List[LightingType]:
    """Any container of LightingType rendered as a list in LightingType's own
    declaration order — deterministic regardless of the input container's internal
    (possibly hash-randomized, for a set/frozenset) iteration order. Every lighting pool
    this module hands to a seeded rng.choice is built this way, never via list(some_set),
    so a repeated plan is byte-identical across process restarts too."""
    return [li for li in LightingType if li in members]


def _lights_allowed_at(location) -> frozenset:
    """Allowed LightingType set for a location (enum or value); unmapped/unknown ->
    every LightingType (permissive default, mirrors _times_allowed_at)."""
    return LIGHTING_LOCATION_COMPAT.get(_val(location), frozenset(LightingType))


def _lighting_ok_at(lighting, location) -> bool:
    """True iff `lighting` reads as real at `location` (LIGHTING_LOCATION_COMPAT)."""
    try:
        li = LightingType(_val(lighting))
    except (ValueError, TypeError):
        return True
    return li in _lights_allowed_at(location)


def _lighting_locations_allowed(location) -> frozenset:
    """LIGHTING_LOCATION_COMPAT union across `location` — a single LocationType/value, or
    an iterable of candidates (the Venice per-beat menu may offer several before the
    provider settles on one). None/empty -> every LightingType (permissive)."""
    if location is None:
        return frozenset(LightingType)
    locs = [location] if isinstance(location, (str, LocationType)) else list(location)
    if not locs:
        return frozenset(LightingType)
    allowed = frozenset()
    for loc in locs:
        allowed |= _lights_allowed_at(loc)
    return allowed


def _lighting_location_pool(pool, location) -> List[LightingType]:
    """
    `pool` (already deterministically ordered, e.g. a beat's own tmpl.lighting_pool)
    narrowed to _lighting_locations_allowed(`location`) — the pick-time coherence filter,
    mirroring _time_compat_pool. Empty intersection -> that allowed set in full
    (LightingType declaration order, never a raw set iteration — see _ordered_lighting),
    so venue sanity wins over beat authorship rather than stranding the beat with zero
    options. `location=None` -> `pool` unchanged (no location context; every existing
    caller always supplies one).
    """
    if location is None:
        return list(pool)
    allowed = _lighting_locations_allowed(location)
    narrowed = [li for li in pool if li in allowed]
    return narrowed or _ordered_lighting(allowed)


def _first_allowed_lighting(location, within=None) -> LightingType:
    """
    Deterministic 'first allowed' LightingType for `location` per
    LIGHTING_LOCATION_COMPAT — the first LightingType (declaration order) present in
    both the location's compat set and `within` (when given; None uses the full compat
    set). No RNG (unlike time-of-day there is no "chronological nearest" concept for
    light). natural_soft is declared first and is a member of every location's set
    (coverage-tested), so with `within=None` this resolves to natural_soft everywhere —
    the safe, neutral value an incoherent edit snaps to (apply_item_scene_edit). `within`
    lets _enforce_lighting_location_compat additionally require the natural-style
    non-dramatic subset without duplicating this same enum-order scan.
    """
    allowed = _lights_allowed_at(location)
    candidates = allowed if within is None else (allowed & within)
    for li in LightingType:
        if li in candidates:
            return li
    return LightingType.NATURAL_SOFT  # unreachable: every location's set is non-empty


def _is_dramatic_lighting(li) -> bool:
    """True iff `li`'s rendered phrase reads as theatrical/staged light
    (_DRAMATIC_LIGHTING_KEYWORDS) — the single exclusion test shared by
    _allowed_lighting_pool (pick time) and _enforce_lighting_location_compat (repair)."""
    return any(kw in sv.lighting_phrase(li).lower() for kw in _DRAMATIC_LIGHTING_KEYWORDS)


def _compress_photo_runs(values, *, start_photo: int = 0) -> List[str]:
    """
    Run-compress a per-photo list into human ranges numbered from start_photo+1,
    e.g. ['photos 1-3: low', 'photo 4: medium']. Shared by the NUDITY PLAN and the
    TIME PLAN so both read the same way; each run's value is rendered via _val.
    """
    groups: List[str] = []
    i0 = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or _val(values[i]) != _val(values[i0]):
            v = _val(values[i0])
            a, b = start_photo + i0 + 1, start_photo + i
            groups.append(f"photo {a}: {v}" if a == b else f"photos {a}-{b}: {v}")
            i0 = i
    return groups


def _format_nudity_plan(ramp: List[NudityLevel]) -> str:
    """Compress a per-photo ramp into human ranges: 'photos 1-3: low; 4-6: medium; 7-8: high'."""
    if not ramp:
        return ""
    return "; ".join(_compress_photo_runs(ramp))


def _format_time_plan(time_ramp: List[TimeOfDayType], count: int, period_days: int) -> str:
    """
    Compress the per-photo time ramp into human ranges, grouped by day — the TIME
    PLAN sibling of _format_nudity_plan, built from the SAME _time_ramp/_day_sizes
    validate_and_repair enforces, so the prompt targets and the safety-net clamp
    agree. Single day: 'photos 1-3: early_morning; ...'. Multiple days:
    'Day 1 — photos 1-4: ...; ... Day 2 — photos 5-8: ...'.
    """
    if not time_ramp:
        return ""
    sizes = _day_sizes(count, period_days)
    multi = sum(1 for s in sizes if s > 0) > 1
    parts: List[str] = []
    start = 0
    day_no = 0
    for size in sizes:
        if size <= 0:
            continue
        day_no += 1
        runs = _compress_photo_runs(time_ramp[start:start + size], start_photo=start)
        prefix = f"Day {day_no} — " if multi else ""
        parts.append(prefix + "; ".join(runs))
        start += size
    return ". ".join(parts)


_BEAT_CYCLE_SUFFIXES: Tuple[str, ...] = (
    "",                            # first pass through the arc's beats: the hand-authored line, verbatim
    ", later that day",
    ", as the afternoon slips by",
    ", as the day winds on",
)


def _vary_beat_description(desc: str, cycle: int) -> str:
    """
    Lightly vary a beat caption when the arc's short beat pool has WRAPPED, so a
    re-cycled BeatTemplate (beat_in_arc >= len(arc.beats)) doesn't surface a
    byte-identical story caption. `cycle` is the wrap count (0 on the first pass ->
    verbatim; >=1 appends a short, identity-free temporal suffix keyed to the pass).
    A minimal fix for the reported verbatim-repeat bug; in multi-day batches the
    day-theme rotation already supplies fresh beats, so this mostly bites within a
    single long day where one arc must stretch across more beats than it authored.
    """
    if cycle <= 0:
        return desc
    suffix = _BEAT_CYCLE_SUFFIXES[cycle % len(_BEAT_CYCLE_SUFFIXES)]
    return f"{desc}{suffix}"[:280]


def _weighted_pick(
    pool, rng, like_kw: set, dislike_kw: set, phrase_map: dict,
    favored: Optional[set] = None, favored_weight: float = 3.0,
    favored_strong: Optional[set] = None, favored_strong_weight: float = 3.0,
):
    """
    Seeded weighted pick from `pool`, soft-excluding dislikes and boosting likes/favorites.

    A candidate's weight is the MAX of its like-match weight (3.0 when its keywords hit a
    like, else 1.0), its favored weight (``favored_weight`` when it is in ``favored``, else
    1.0), and its strong-favored weight (``favored_strong_weight`` when in ``favored_strong``,
    else 1.0) — MAX, never a product, so a candidate that is liked AND favored AND
    strong-favored is 3.0, not compounded (a strong-but-bounded bias). ``favored`` /
    ``favored_strong`` are sets of enum members (WS-B: favored_outfits / favored_locations at
    3.0, demeanor-favored poses at 2.0; culture favored_poses at 3.0 via favored_strong).
    All default to the pre-B2 behavior when unset (favored/favored_strong None + empty
    like/dislike -> all weights 1.0), so a no-likes/no-profile/no-culture pick is byte-identical.
    """
    candidates = list(pool)
    if not candidates:
        return None
    # Soft-exclude dislikes, but never empty the pool.
    kept = [c for c in candidates if not (_enum_keywords(c, phrase_map) & dislike_kw)]
    if not kept:
        kept = candidates
    weights = []
    for c in kept:
        like_w = 3.0 if (_enum_keywords(c, phrase_map) & like_kw) else 1.0
        fav_w = favored_weight if (favored and c in favored) else 1.0
        strong_w = favored_strong_weight if (favored_strong and c in favored_strong) else 1.0
        weights.append(max(like_w, fav_w, strong_w))
    return rng.choices(kept, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# "Conscious model" variety (A2): per-item expression + mood gating
# ---------------------------------------------------------------------------
def _assign_batch_expressions(scenes: List[SceneSpec], controls: BatchControls) -> None:
    """
    Assign a short expression/gaze state to every scene (mutates in place), seeded from
    controls.base_seed so the same batch reproduces exactly. Rules mirror the pose usage
    caps:
      * ~1/3 CANDID share — every 3rd slot (i % 3 == 2) draws from the camera-UNAWARE
        subset, the rest from the camera-aware subset (deterministic, not random, so the
        share is exact);
      * no identical expression on ADJACENT items;
      * per-expression usage cap of max(2, ceil(n/8)) (same formula as the pose cap), so no
        single expression dominates a long batch.
    Uses a dedicated RNG (offset base_seed) so it does NOT perturb the planner's other
    seeded draws (existing reproducibility tests stay byte-identical except for this
    newly-populated field). Best-effort: if the constraints can't all be met for a slot
    (tiny pool exhausted), the least-used still-non-adjacent option is taken, and failing
    that any least-used option — an expression is always assigned (never left None).
    """
    n = len(scenes)
    if n == 0:
        return
    cap = max(2, math.ceil(n / 8))
    # WS-B: when the batch carries a demeanor, bias BOTH registers toward the demeanor-
    # consistent expression strings. Filtering happens per-register below (so the ~1/3
    # candid share, adjacency and usage caps are all untouched); empty favor (no demeanor)
    # leaves the pools — and the seeded output — byte-identical to the pre-B2 behavior.
    favor = _demeanor_expression_favor(controls)
    counts: Dict[str, int] = {}
    prev: Optional[str] = None
    for i in range(n):
        rng = random.Random((controls.base_seed or 0) + 1900009 * (i + 1))
        candid = (i % 3) == 2
        pool = list(_BATCH_EXPRESSIONS_CANDID if candid else _BATCH_EXPRESSIONS_CAMERA_AWARE)
        # WS1b compat (HARD constraint, applied BEFORE the demeanor bias and the seeded
        # shuffle so determinism holds): drop expressions that don't suit THIS scene's pose
        # energy, exposure and venue. Keep the filtered register only when >=2 survive (so
        # the adjacency/variety machinery still has room); otherwise fall back to the full
        # register and let _enforce_expression_compat — the authoritative net on the FINAL
        # scene state — fix it. Uses the scene's CURRENT (pick-time) pose/nudity/location.
        s = scenes[i]
        compat = [
            e for e in pool
            if _expression_allowed(e, s.pose, s.nudityLevel, s.location, s.outfit)
        ]
        if len(compat) >= 2:
            pool = compat
        # Demeanor bias: keep only demeanor-consistent entries when >=2 survive in this
        # register (fallback to the full register otherwise — never starves a register).
        if favor:
            biased = [e for e in pool if e in favor]
            if len(biased) >= 2:
                pool = biased
        rng.shuffle(pool)
        # Prefer: under-cap AND not adjacent-duplicate; then under-cap; then any.
        under_cap = [e for e in pool if counts.get(e, 0) < cap]
        non_adj = [e for e in under_cap if e != prev]
        choice = (non_adj or under_cap or pool)[0]
        # As a last resort if even `pool` somehow left a stale adjacency (both register
        # subsets exhausted under the cap), try the whole cross-register pool for a
        # non-adjacent value (keeps the no-adjacent invariant). Seeded via the same rng so it
        # stays reproducible.
        if choice == prev:
            alt = [e for e in _BATCH_EXPRESSION_POOL if e != prev and counts.get(e, 0) < cap]
            if alt:
                choice = rng.choice(alt)
        scenes[i].expression = choice
        counts[choice] = counts.get(choice, 0) + 1
        prev = choice


def _mood_eligible(nudity, location) -> bool:
    """
    May this scene carry a kink/personality MOOD tag (mood_kinks/mood_personality)?
    The mood phrase renders as "a sultry, seductive expression, intense intimate..."
    (scene_vocab.scene_mood_phrase) — appropriate only where the scene is already
    intimate. Eligible iff the level is above LOW AND the location is private enough that
    its ceiling reaches REVEALING (i.e. NOT a SUGGESTIVE-ceiling public/professional place
    like a classroom, office, gym or street). This is what stops every card in a batch —
    including a fully-clothed classroom shot — ending on the same "sultry, seductive" tail.
    """
    return (
        _nudity_index(nudity) > 0
        and _nudity_index(_location_ceiling(location)) >= _nudity_index(NudityLevel.REVEALING)
    )


def _assign_batch_moods(character: "Character", scenes: List[SceneSpec], controls: BatchControls) -> None:
    """
    Set mood_kinks/mood_personality on a seeded ~1/3 subset of ELIGIBLE scenes (mutates in
    place); clear them everywhere else. Eligibility (_mood_eligible) excludes every LOW and
    every public/professional (SUGGESTIVE-ceiling) scene, so those never carry the intimate
    mood tail. Among the eligible scenes, round(n/3) are chosen with a dedicated RNG (offset
    base_seed, so the planner's other draws are untouched). The chosen scenes get the
    character's kinks + personality as their per-scene mood; the mood phrase itself is still
    rendered downstream by scene_vocab.scene_mood_phrase — this only decides WHICH scenes
    carry it, breaking the "every item is sultry" monotony. validate_and_repair re-applies
    the eligibility strip on the FINAL (post-ceiling-swap) state as a safety net.
    """
    n = len(scenes)
    # Clear first so a non-selected/ineligible scene never keeps a stale mood.
    for s in scenes:
        s.mood_kinks = None
        s.mood_personality = None
    if n == 0:
        return
    eligible = [i for i in range(n) if _mood_eligible(scenes[i].nudityLevel, scenes[i].location)]
    if not eligible:
        return
    target = min(len(eligible), max(1, round(n / 3)))
    rng = random.Random((controls.base_seed or 0) + 2300003)
    chosen = set(rng.sample(eligible, target))
    # Cap the per-item mood payload to at most ONE kink (the first). The mood phrase
    # renders a single clause anyway (scene_vocab.scene_mood_phrase now returns one
    # phrase), and carrying the full kink list bloated the background-step prompt. WHICH
    # items are moody stays the seeded ~1/3 selection above (rng.sample) — only the
    # payload shrinks, so the same seed still yields byte-identical which-items gating.
    kinks = character.persona.kinks or None
    one_kink = [kinks[0]] if kinks else None
    personality = character.persona.personality
    for i in chosen:
        scenes[i].mood_kinks = one_kink
        scenes[i].mood_personality = personality


def _strip_ineligible_moods(scenes: List[SceneSpec]) -> None:
    """
    Final safety net (called from validate_and_repair after the ceiling/exposure passes
    settle each scene's FINAL nudity + location): clear mood_kinks/mood_personality on any
    scene that is no longer mood-eligible (LOW, or a public SUGGESTIVE-ceiling place). A
    whole-scene ceiling SWAP can move a mood-carrying intimate scene onto a low positional
    ramp slot; this strip guarantees the "never on LOW/public" invariant holds on the output
    of EVERY provider (Venice included), not just the deterministic planner. It never ADDS a
    mood, so the deterministic planner's ~1/3 share is preserved (only over-broad moods are
    removed).
    """
    for s in scenes:
        if (s.mood_kinks or s.mood_personality) and not _mood_eligible(s.nudityLevel, s.location):
            s.mood_kinks = None
            s.mood_personality = None


# ---------------------------------------------------------------------------
# Manual planner (admin-supplied scenes)
# ---------------------------------------------------------------------------
class ManualScenePlanner(StoryPlanner):
    name = "manual"
    supports_nsfw = True

    def __init__(self, raw_scenes: List[dict]):
        self.raw_scenes = raw_scenes or []

    async def plan_scenes(
        self, character: Character, count: int, controls: BatchControls
    ) -> List[SceneSpec]:
        scenes: List[SceneSpec] = []
        for i, raw in enumerate(self.raw_scenes[:count]):
            spec = _raw_beat_to_scene(raw, arc_id="manual", arc_title="Manual", beat_index=i, global_index=i)
            if spec is not None:
                scenes.append(spec)
        return scenes


# ---------------------------------------------------------------------------
# Venice planner (primary)
# ---------------------------------------------------------------------------
PLANNER_SYSTEM_PROMPT = """You are a story director for a photorealistic NSFW image series of ONE fixed character.
The user message lists the exact sequence of ARCS and BEATS to fill in. Each beat gives
you a short "vibe" hint and that beat's OWN allowed pose/outfit/location/time_of_day/
lighting options — these lists differ per beat because they were hand-authored to be
scene-coherent (e.g. a nurse uniform only appears in a hospital-ward beat, a bikini only
in a beach/pool/golden-hour beat). This is what keeps the batch from pairing e.g. a
cocktail dress with a gym beat, or a bodycon dress with an "eating dinner" beat that
would make no sense together.

You must output ONLY valid JSON of the form:
{"arcs":[{"arc_id":"snake_case_id","arc_title":"Short title","beats":[BEAT, ...]}, ...]}

Each BEAT is:
{"beat_description":"one short sentence","pose":<pose|null>,"outfit":<outfit|null>,
 "nudityLevel":"low|medium|high","accessories":[<accessory>...]|null,
 "location":<location>,"time_of_day":<time>,"lighting":<lighting>,
 "mood_kinks":[<kink>...]|null,"mood_personality":<personality>|null}

HARD RULES:
- Output the SAME arcs and the SAME number of beats per arc, in the SAME order, as given in the user message.
- For each beat, choose pose/outfit/location/time_of_day/lighting ONLY from THAT beat's own allowed lists in the user message. Never borrow a value from a different beat's list, never invent a value outside any list. If a beat's list is empty/"(none allowed)", output null for that field (pose/outfit only — location/time_of_day/lighting always have at least one option).
- accessories/mood_kinks/mood_personality are chosen from the shared lists at the end of the user message (not beat-specific).
- Write beat_description as a concrete, LITERAL scene sentence that matches the attributes YOU picked for that beat — freely rephrase the beat's "vibe" hint in your own words, but never contradict your own location/outfit/pose choice. Name the place, clothing and action a camera would see; avoid metaphor, mood-narration and atmosphere words with no physical referent. (It is a gallery caption, so a light, plain touch is enough.)
- Do NOT describe the person's face, age, ethnicity, hair, eyes, body, or breasts anywhere. Only scene attributes.
- Make the sequence feel organic for THIS character's personality, likes and dislikes within the given options.
- Avoid anything matching the character's dislikes.
- nudityLevel must never exceed the stated maximum.
- Output the requested number of beats total across all arcs. No prose, no markdown, only the JSON object.
"""


# Story-director mode (story_mode=True): the LLM AUTHORS a cohesive "day in her life"
# and picks freely from the full (controls-filtered) vocab, keeping each scene coherent
# ITSELF instead of being handed a per-beat menu. It emits two render-safe fields —
# `setting` and `activity` — that DO reach the image prompt (via scene_mapper), plus the
# gallery-only `narrative`. This is what makes the AI story actually drive the pictures.
STORY_DIRECTOR_SYSTEM_PROMPT = """You are a story director for a photorealistic NSFW image series of ONE fixed character.
Invent ONE cohesive "day in her life": a real narrative with a beginning, middle and end,
distinct settings, changing activities, shifting moods, and a natural progression of
time-of-day. YOU choose everything from the allowed lists in the user message — you are
NOT filling a fixed template.

Each beat carries TWO registers, and they must NOT sound alike. The STORY register — the
"narrative" field and the gallery caption "beat_description" — is prose for a human reader;
keep it as vivid as you like. The RENDER register — "setting", "activity", "pose_detail",
"outfit_detail" and "expression" — is a set of CAMERA INSTRUCTIONS for a diffusion model:
plain, literal, physically concrete. NEVER let the story voice leak into the render fields.

Output ONLY valid JSON of the form:
{"story_title":"Short evocative title","arcs":[{"arc_id":"snake_case_id","arc_title":"Chapter title","beats":[BEAT, ...]}, ...]}

Each BEAT is:
{"beat_description":"short concrete caption for this photo (scene only)",
 "setting":"ONE sentence describing the PLACE/environment for this photo — a concrete VISUAL place description (scene only, no people)",
 "activity":"short phrase: what she is DOING in this photo (e.g. 'pouring coffee', 'stretching by the window')",
 "pose_detail":"ONE sentence: her exact body position and what her body is doing (e.g. 'curled up on the sofa, mug in both hands, knees tucked'), consistent with the chosen pose",
 "outfit_detail":"<=12 words naming the clothing concretely (colors/fabric/fit/state, e.g. 'faded blue oversized band t-shirt, off one shoulder'), matching the chosen outfit + nudityLevel",
 "expression":"<=6 words: her facial expression/mood ONLY (e.g. 'sleepy soft smile')",
 "narrative":"1-3 sentences of THIRD-PERSON, PRESENT-TENSE story prose (gallery only)",
 "pose":<pose|null>,"outfit":<outfit|null>,"nudityLevel":"low|medium|high",
 "accessories":[<accessory>...]|null,"location":<location>,"time_of_day":<time>,
 "lighting":<lighting>,"mood_kinks":[<kink>...]|null,"mood_personality":<personality>|null}

HARD RULES:
- RENDER FIELDS ARE CAMERA INSTRUCTIONS, NOT PROSE (this governs "setting", "activity",
  "pose_detail", "outfit_detail" and "expression"): write ONLY what a camera can see — objects,
  surfaces, materials, furniture, light sources, body positions, and garment names/colors/
  fabrics. Write what a camera sees, not what a narrator feels. BANNED in these fields:
  metaphors and similes ("like...", "as if..."), emotional or mood abstractions ("tension
  easing", "a rare moment of calm", "lost in thought", "melting into the evening"), story-
  narration voice, and atmosphere words with no physical referent. GOOD vs BAD, per field:
    - setting       BAD: "a cozy nook where the evening melts away"
                    GOOD: "small home office, wooden desk with stacked papers, warm desk lamp, dark window behind"
    - activity      BAD: "savoring a quiet moment to herself"
                    GOOD: "pouring coffee from a steel kettle into a white mug"
    - pose_detail   BAD: "relaxing, at peace with the world"
                    GOOD: "sitting on the desk edge, one foot on the chair, both hands around a mug"
    - outfit_detail BAD: "something comfortable that feels like home"
                    GOOD: "grey cotton sweatshirt, sleeves pushed up, black leggings"
    - expression    BAD: "radiating serene inner contentment"
                    GOOD: "soft sleepy smile" (<=6 words, one plain visible expression)
- DISPLAY vs RENDER: "narrative" and "beat_description" are DISPLAY text shown only in the
  gallery — they are NEVER fed to the image model, so they may keep the storytelling voice.
  Every RENDER field above must stay literal; do not blur the two.
- THE DAY IS HERS: build the whole day around WHO SHE IS — her occupation, relationship,
  personality and kinks. SHE chooses where the day goes; the locations, activities and outfits
  are the ones THIS character would pick, following the DAY SHAPE in the user message.
- Choose pose/outfit/location/time_of_day/lighting ONLY from the exact lists in the user
  message. Use null for POSE only if none fits a beat; OUTFIT is REQUIRED on EVERY beat
  (see the OUTFIT RULE below); location/time_of_day/lighting are always required.
  accessories/mood_kinks/mood_personality come from the shared lists.
- OUTFIT RULE (HARD): every beat MUST set a non-null "outfit" enum chosen from the OUTFITS
  list — NEVER null. If you are unsure, pick the CLOSEST outfit to what she is wearing; a
  null outfit makes the render keep the avatar's original clothes and ignore your caption.
  "outfit_detail" MUST describe the SAME garment as that chosen "outfit" enum at this beat's
  nudityLevel — never a different garment class (do NOT pick outfit "satin_robe" and then
  write "leather crop top and jeans"). The enum and the words must always agree.
  "outfit_detail" is REQUIRED on EVERY beat and IS the exact garment text the render paints
  (the enum only gates the step), so write it like a wardrobe card — colors, fabric, fit and
  state (e.g. 'faded blue oversized band t-shirt, off one shoulder') at this beat's nudityLevel.
- COHERENCE IS YOUR JOB now (no menu enforces it): outfit, location, activity and time must
  make sense together in each beat — no gym clothes in a nightclub, no cocktail dress while
  cooking breakfast, no swimwear in an office.
- VARIETY IS A HARD RULE: never reuse the same outfit+pose pair; consecutive beats must differ
  in activity AND in at least one of pose/location/outfit; no single outfit spans more than 2
  beats (except a work uniform inside the work chapter). beat_description must be DISTINCT for
  every photo — never repeat or lightly reword an earlier caption, even when the location or
  outfit carries over or a later day revisits the same place; describe THIS photo's own moment.
- FLOW: consecutive beats connect. time_of_day advances across the day per the TIME PLAN; the
  setting changes between chapters. Group beats into arcs as CHAPTERS of the one story. When the
  story spans MULTIPLE DAYS, each new day restarts in the early morning and centers on DIFFERENT
  activities from the days before — never replay the same day twice.
- IDENTITY IS PIXEL-LOCKED. In beat_description, setting, activity, pose_detail AND narrative,
  NEVER describe her face, age, ethnicity, hair, eyes, body, breasts or skin. Using her first
  name is fine. Describe places, clothes, actions, light and mood only.
- "outfit_detail" describes ONLY clothing (garment, colors, fabric, fit) — the SAME garment
  as the chosen "outfit" enum at this nudityLevel (per the OUTFIT RULE); "expression" is her
  expression/mood ONLY (e.g. 'soft sleepy smile') — NEVER facial features (eyes, lips, jaw,
  nose, chin, face shape).
- "pose_detail" (REQUIRED on every beat): ONE concrete, identity-free sentence describing her
  body position and what her body is doing in THIS photo (e.g. 'curled up on the sofa, mug in
  both hands, knees tucked'), consistent with the chosen "pose" enum — the enum still selects
  the pose reference image; your sentence is the target-pose text the render follows. Body and
  action only: no other people, no facial-feature language.
- "setting" (REQUIRED on every beat): ONE concrete visual sentence describing the PLACE itself
  — surfaces, furniture, light, weather — it LEADS the rendered background text. No people, no
  persona name, no actions (those belong in "activity" and "pose_detail").
- "narrative": keep the EXACT SAME third-person present voice for EVERY beat; continue directly
  from the previous beat; reflect her personality/likes/persona-context; avoid her dislikes.
- NUDITY: follow the per-photo targets in the user message's NUDITY PLAN. Never exceed a photo's
  target; you may stay lower when the scene demands it, but reach the finish level by the final
  photos. For any photo targeted medium or high, the chosen outfit + outfit_detail must clearly
  show that exposure level (the outfit is always set — see the OUTFIT RULE).
- Emit EXACTLY the requested number of beats total across all arcs. No prose outside JSON, no markdown.
"""


class VeniceScenePlanner(StoryPlanner):
    name = "venice"
    supports_nsfw = True

    def __init__(self, api_key: str, base_url: str = "https://api.venice.ai/api/v1",
                 model: str = "venice-uncensored", timeout: float = 100.0,
                 temperature: float = 0.6):
        self.api_key = api_key
        # Lower temperature keeps the render-bound fields literal/directional (see
        # STORY_DIRECTOR_SYSTEM_PROMPT); injected from settings.STORY_PLANNER_TEMPERATURE
        # by build_planner, mirroring how SceneWriter takes SCENE_WRITER_TEMPERATURE.
        self.temperature = temperature
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    async def plan_scenes(
        self, character: Character, count: int, controls: BatchControls
    ) -> List[SceneSpec]:
        if not self.api_key:
            return []
        story_mode = getattr(controls, "story_mode", False)
        # Story mode -> the story-director prompt (free vocab, authors a cohesive day,
        # emits render-safe setting/activity). Non-story -> the legacy per-beat-menu prompt.
        if story_mode:
            user_prompt = self._build_director_user_prompt(character, count, controls)
        else:
            user_prompt = self._build_user_prompt(character, count, controls)
        raw = await self._call_venice(user_prompt, story_mode=story_mode, count=count)
        if raw is None:
            return []
        return _parse_arcs_json(raw)

    def _build_user_prompt(self, character: Character, count: int, controls: BatchControls) -> str:
        persona = character.persona
        summary_parts = [
            f"name: {persona.name}",
            f"occupation: {ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation) or 'unspecified'}",
            f"personality: {ap.phrase(ap.PERSONALITY_PHRASES, persona.personality) or 'unspecified'}",
            f"relationship vibe: {ap.phrase(ap.RELATIONSHIP_PHRASES, persona.relationship) or 'unspecified'}",
            f"likes: {', '.join(character.likes) or 'none given'}",
            f"dislikes: {', '.join(character.dislikes) or 'none given'}",
        ]
        if character.bio:
            summary_parts.append(f"persona/context: {character.bio.strip()[:600]}")
        max_nudity = "low" if controls.sfw_only else _val(controls.max_nudity)

        # Per-beat menus from the SAME hand-authored pools + filtering the
        # deterministic planner draws from (see _beat_slots/_allowed_*_pool) —
        # Venice picks WITHIN a beat's own pools instead of freely combining
        # any outfit with any location/pose from the full enum.
        slots = _beat_slots(character, count, controls)
        n_arcs = len({slot.arc_id for slot in slots}) or (controls.arc_count or _auto_arc_count(count))

        beat_lines: List[str] = []
        current_arc: Optional[str] = None
        for i, slot in enumerate(slots):
            if slot.arc_id != current_arc:
                current_arc = slot.arc_id
                beat_lines.append(f'\nARC "{slot.arc_id}" ("{slot.arc_title}"):')
            pose_pool = [_val(p) for p in _allowed_pose_pool(slot.tmpl, controls)]
            outfit_pool = [_val(o) for o in _allowed_outfit_pool(slot.tmpl, controls)]
            location_pool = [_val(loc) for loc in _allowed_location_pool(slot.tmpl, controls)]
            if not location_pool:
                fallback = controls.allowed_locations[0] if controls.allowed_locations else LocationType.HOME_LIVING_ROOM
                location_pool = [_val(fallback)]
            time_pool = [_val(t) for t in slot.tmpl.time_pool]
            # Same venue-sanity (LIGHTING_LOCATION_COMPAT, unioned across this beat's OWN
            # location candidates above — Venice hasn't picked ONE yet) + natural/
            # candid_phone theatrical-lighting exclusion the deterministic planner applies
            # (see _allowed_lighting_pool) — Venice must not even be OFFERED an
            # incoherent-for-the-venue or (on a natural-style batch) dramatic/moody/neon
            # option. A permissive superset only: _enforce_lighting_location_compat
            # narrows for real once Venice settles on one location.
            lighting_pool = [
                _val(li) for li in _allowed_lighting_pool(slot.tmpl, controls, location=location_pool)
            ]
            beat_lines.append(
                f'  BEAT {i + 1} (vibe: "{slot.tmpl.beat_description}"):\n'
                f'    pose: {", ".join(pose_pool) or "(none allowed - output null)"}\n'
                f'    outfit: {", ".join(outfit_pool) or "(none allowed - output null)"}\n'
                f'    location: {", ".join(location_pool)}\n'
                f'    time_of_day: {", ".join(time_pool)}\n'
                f'    lighting: {", ".join(lighting_pool)}'
            )

        shared = {
            "accessory": _allowed_values(AccessoryType),
            "kink": _allowed_values(KinkType),
            "personality": _allowed_values(PersonalityType),
        }
        story_block = ""
        if getattr(controls, "story_mode", False):
            story_block = (
                f"\n\nSTORY MODE: Tell ONE continuous story for {persona.name} across these "
                f"{count} beats (one scene per photo). Output a top-level \"story_title\" and, "
                "for each beat, a \"narrative\": 1-3 sentences (max ~55 words) of THIRD-PERSON, "
                "PRESENT-TENSE prose about her by name that continues from the previous beat, "
                "treats each arc as a chapter, reflects her personality/likes/persona-context "
                "and avoids dislikes. Keep the SAME third-person present voice for every beat. "
                "Describe actions, feelings and setting — NEVER her face, age, hair, eyes, body "
                "or skin."
            )
        return (
            f"CHARACTER:\n" + "\n".join(summary_parts) + "\n\n"
            f"PLAN: {count} beats total, grouped into {n_arcs} arcs, "
            f"escalation style '{_val(controls.escalation)}'.\n"
            f"Maximum nudityLevel allowed: {max_nudity}.\n\n"
            f"BEATS (fill in exactly these, in this order — see HARD RULES):"
            + "\n".join(beat_lines) + "\n\n"
            f"SHARED ALLOWED VALUES (any beat, not beat-specific):\n"
            + "\n".join(f"{k}: {', '.join(v)}" for k, v in shared.items())
            + story_block
        )

    def _build_director_user_prompt(self, character: Character, count: int, controls: BatchControls) -> str:
        """
        Story-director user prompt: presents the FULL controls-filtered vocab ONCE (not a
        per-beat menu) and lets the LLM author the day and pick freely. Coherence is the
        model's job (enforced by the system prompt), not a hand-authored BeatTemplate.
        """
        persona = character.persona
        # Her kinks are her SIGNATURE moods — raw enum value + its mood phrase so the
        # director can steer mood_kinks/atmosphere toward who she is.
        kink_bits: List[str] = []
        for k in (persona.kinks or []):
            ph = ap.phrase(ap.KINK_PHRASES, k)
            kink_bits.append(f"{_val(k)} ({ph})" if ph else str(_val(k)))
        kinks_line = ", ".join(kink_bits) or "none given"
        summary_parts = [
            f"name: {persona.name}",
            f"occupation: {ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation) or 'unspecified'}",
            f"personality: {ap.phrase(ap.PERSONALITY_PHRASES, persona.personality) or 'unspecified'}",
            f"relationship vibe: {ap.phrase(ap.RELATIONSHIP_PHRASES, persona.relationship) or 'unspecified'}",
            f"kinks (her signature moods): {kinks_line}",
            f"likes (weave these into her activities and settings): {', '.join(character.likes) or 'none given'}",
            f"dislikes (NEVER plan an activity or setting she dislikes): {', '.join(character.dislikes) or 'none given'}",
        ]
        if character.bio:
            summary_parts.append(f"persona/context: {character.bio.strip()[:600]}")
        max_nudity = "low" if controls.sfw_only else _val(controls.max_nudity)

        # sfw batches also drop NAKED from the offered outfits (defense-in-depth; the
        # nudity clamp in validate_and_repair re-enforces regardless).
        blocked_outfits = list(controls.blocked_outfits or [])
        if controls.sfw_only:
            blocked_outfits.append(OutfitType.NAKED)

        pools = {
            "LOCATIONS": _allowed_values(
                LocationType, allowed=controls.allowed_locations, blocked=controls.blocked_locations
            ),
            "OUTFITS": _allowed_values(
                OutfitType, allowed=controls.allowed_outfits, blocked=blocked_outfits
            ),
            "POSES": _allowed_values(PoseType, blocked=controls.blocked_poses),
            "TIMES": _allowed_values(TimeOfDayType),
            "LIGHTINGS": _allowed_values(LightingType),
            "ACCESSORIES": _allowed_values(AccessoryType),
            "KINKS": _allowed_values(KinkType),
            "PERSONALITIES": _allowed_values(PersonalityType),
        }
        vocab_block = "\n".join(f"{k}: {', '.join(v) or '(none allowed)'}" for k, v in pools.items())

        # DAY SHAPE — structure her day like a real person's, anchoring the ONE work
        # chapter in a place this occupation actually works (filtered by allow/block).
        occ_raw = _val(persona.occupation)
        allowed_locs = {_val(a) for a in controls.allowed_locations} if controls.allowed_locations else None
        blocked_locs = {_val(b) for b in (controls.blocked_locations or [])}
        work_locs = [
            _val(loc) for loc in st.work_locations_for(persona.occupation)
            if _val(loc) not in blocked_locs and (allowed_locs is None or _val(loc) in allowed_locs)
        ] if occ_raw else []
        occ_phrase = ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation) or (occ_raw or "").replace("_", " ")

        # DAY SHAPE differs by span: one wake->sleep day (as before), or N distinct
        # days where day 1 is her occupation day and days 2+ vary the activities so a
        # multi-day batch reads as different real days, not the same workday repeated.
        period_days = controls.period_days
        multi_day = period_days > 1
        if multi_day:
            work_bit = (
                f"one work chapter as a {occ_phrase} at {', '.join(work_locs)}"
                if occ_raw and work_locs else "the anchor activity that defines who she is"
            )
            day_shape_lines = [
                f"DAY SHAPE (structure this as {period_days} DISTINCT days, in chronological order):",
                f"- Day 1 is built around her occupation: open at home (waking, first coffee, getting "
                f"ready), then {work_bit}, then an after-work unwind.",
                "- Days 2+ are DIFFERENT real days — a lazy day off at home, running errands with a "
                "cafe stop, seeing friends, a date night. Vary the activities so no two days repeat; "
                "do NOT put her back at work every day.",
                "- Within EACH day, time_of_day flows early morning -> night ONCE, then RESETS to "
                "early morning for the next day; land each day's final beat on its evening/night peak.",
            ]
        else:
            day_shape_lines = [
                "DAY SHAPE (build her day like a real person's, in this order):",
                "- Open at home: waking slow, first coffee, breakfast, getting ready.",
            ]
            # Drop the work bullet when the occupation is unknown or all its workplaces are blocked.
            if occ_raw and work_locs:
                day_shape_lines.append(
                    f"- ONE work chapter as a {occ_phrase} at {', '.join(work_locs)}, "
                    "with concrete on-the-job activities."
                )
            day_shape_lines.append("- An after-work unwind: home to change or shower, then head out or settle in.")
            day_shape_lines.append(
                "- An evening finish where the story peaks and the nudity plan reaches its height."
            )
            day_shape_lines.append(
                "Example (a nurse's day): coffee -> breakfast -> hospital shift -> home -> shower -> "
                "change -> drinks -> club."
            )
        if count <= 4:
            day_shape_lines.append(
                f"(Only {count} photos here — compress the arc: fewer beats, but keep the progression.)"
            )
        day_shape_block = "\n".join(day_shape_lines)

        # NUDITY PLAN — per-photo guided-ceiling targets from the SAME ramp
        # validate_and_repair enforces, so the prompt and the clamp agree.
        nudity_plan = _format_nudity_plan(_nudity_ramp(count, controls))
        nudity_block = (
            f"NUDITY PLAN (per-photo targets): {nudity_plan}. Never exceed a photo's target; you may "
            f"stay lower when the scene demands it (e.g. at work), but reach {max_nudity} by the final "
            "photos. ALWAYS set an outfit enum on EVERY photo (never null) and make outfit_detail "
            "describe that same garment — a null outfit keeps the avatar's original clothes."
        )

        # TIME PLAN — per-photo chronological targets from the SAME _time_ramp
        # validate_and_repair enforces (its safety net), so the prompt and the clamp
        # agree, exactly like the NUDITY PLAN above pairs with the nudity clamp.
        time_plan = _format_time_plan(_time_ramp(count, period_days), count, period_days)
        time_block = (
            f"TIME PLAN (per-photo time_of_day targets): {time_plan}. Follow the per-photo targets so "
            "the day moves forward; you may deviate slightly for scene coherence, but the overall day "
            + (
                "must flow early morning -> night within EACH day, then reset for the next."
                if multi_day else "must flow early morning -> night across the set."
            )
        )

        variety_line = (
            f"VARIETY: never repeat an outfit+pose combination; use at least {min(count, 5)} distinct "
            f"locations and at least {min(count, 6)} distinct outfits across the set."
        )
        mood_line = (
            "MOOD: for mood_kinks, prefer HER kinks (listed above); reach for others only when a "
            "scene genuinely calls for it."
        )

        arc_hint = str(controls.arc_count) if controls.arc_count else "3-5"
        plan_line = (
            f"PLAN: Write ONE cohesive {period_days}-day story for {persona.name} as {count} photos, "
            "grouped into chapters (arcs) — treat each day as its own run of chapters."
            if multi_day else
            f"PLAN: Write ONE cohesive day-in-the-life story for {persona.name} as {count} photos, "
            f"grouped into {arc_hint} chapters (arcs)."
        )
        return (
            "CHARACTER:\n" + "\n".join(summary_parts) + "\n\n"
            + plan_line + "\n\n"
            + day_shape_block + "\n\n"
            + nudity_block + "\n\n"
            + time_block + "\n\n"
            + variety_line + "\n"
            + mood_line + "\n\n"
            "ALLOWED VALUES (choose freely, keep each scene internally coherent):\n"
            + vocab_block + "\n\n"
            f"Return the JSON from the system prompt: a story_title and arcs whose beats total EXACTLY {count}."
        )

    async def _call_venice(self, user_prompt: str, *, story_mode: bool = False, count: int = 12) -> Optional[str]:
        content, _usage = await self._client.chat(
            [
                {
                    "role": "system",
                    "content": STORY_DIRECTOR_SYSTEM_PROMPT if story_mode else PLANNER_SYSTEM_PROMPT,
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            # Story-director beats each carry setting + activity + narrative, so scale token
            # headroom with beat count rather than a flat cap.
            max_tokens=min(16000, 300 * count + 2000) if story_mode else 4000,
        )
        return content


class ClaudeScenePlanner(StoryPlanner):
    """SFW-only stub. Anthropic refuses explicit content, so this planner is never
    routed NSFW batches; it currently defers to the deterministic planner. Full
    Anthropic wiring can be added when an SFW use case exists."""
    name = "claude"
    supports_nsfw = False

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key
        self.model = model

    async def plan_scenes(
        self, character: Character, count: int, controls: BatchControls
    ) -> List[SceneSpec]:
        return await DeterministicScenePlanner().plan_scenes(character, count, controls)


def _allowed_values(enum_cls, *, allowed=None, blocked=None) -> List[str]:
    allowed_vals = {_val(a) for a in allowed} if allowed else None
    blocked_vals = {_val(b) for b in (blocked or [])}
    out = []
    for e in enum_cls:
        if allowed_vals is not None and e.value not in allowed_vals:
            continue
        if e.value in blocked_vals:
            continue
        out.append(e.value)
    return out


# ---------------------------------------------------------------------------
# Venice/manual JSON -> SceneSpec parsing
# ---------------------------------------------------------------------------
def _parse_arcs_json(raw: str) -> List[SceneSpec]:
    """Parse the planner JSON into SceneSpecs. Returns [] on total structural failure."""
    data = _extract_json_object(raw)
    if data is None:
        return []
    arcs = data.get("arcs")
    if not isinstance(arcs, list):
        return []
    story_title = data.get("story_title")
    scenes: List[SceneSpec] = []
    gidx = 0
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        arc_id = str(arc.get("arc_id") or f"arc_{len(scenes)}")
        arc_title = str(arc.get("arc_title") or "Arc")
        beats = arc.get("beats")
        if not isinstance(beats, list):
            continue
        for b, raw_beat in enumerate(beats):
            if not isinstance(raw_beat, dict):
                continue
            spec = _raw_beat_to_scene(raw_beat, arc_id, arc_title, b, gidx, story_title=story_title)
            if spec is not None:
                scenes.append(spec)
                gidx += 1
    return scenes


def _extract_json_object(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    # Repair attempt: extract the first {...} block.
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _raw_beat_to_scene(
    raw: dict, arc_id: str, arc_title: str, beat_index: int, global_index: int,
    story_title: Optional[str] = None,
) -> Optional[SceneSpec]:
    location = _coerce_enum(LocationType, raw.get("location"))
    if location is None:
        location = LocationType.HOME_LIVING_ROOM  # required field; substitute neutral
    nudity = _coerce_enum(NudityLevel, raw.get("nudityLevel")) or NudityLevel.LOW
    accessories_raw = raw.get("accessories") or []
    accessories = [a for a in (_coerce_enum(AccessoryType, x) for x in accessories_raw) if a] or None
    kinks_raw = raw.get("mood_kinks") or []
    mood_kinks = [k for k in (_coerce_enum(KinkType, x) for x in kinks_raw) if k][:3] or None
    # Story narrative: scrub identity at parse time (again in validate_and_repair).
    narrative_raw = raw.get("narrative")
    narrative = _scrub_narrative(str(narrative_raw)) if narrative_raw else None
    # Render-safe channel (folded into the background prompt) — scrub identity here too.
    setting = _scrub_scene_text(raw.get("setting"), 400)
    activity = _scrub_scene_text(raw.get("activity"), 200)
    # Freeform pose text (C1a): drives the pose step's target-pose sentence; the pose
    # ENUM still selects the reference image. Companion-scrubbed in validate_and_repair
    # (same treatment as activity).
    pose_detail = _scrub_scene_text(raw.get("pose_detail"), 200)
    # Structured description channels (WS2): outfit_detail sharpens the outfit step,
    # expression drives the pose step. Both are identity-scrubbed; expression also has
    # facial-FEATURE tokens stripped (it must carry an expression/mood only).
    outfit_detail = _scrub_scene_text(raw.get("outfit_detail"), 160)
    expression = _scrub_expression(raw.get("expression"))
    try:
        return SceneSpec(
            arc_id=arc_id,
            arc_title=arc_title,
            beat_index=beat_index,
            global_index=global_index,
            beat_description=str(raw.get("beat_description") or arc_title)[:280],
            pose=_coerce_enum(PoseType, raw.get("pose")),
            outfit=_coerce_enum(OutfitType, raw.get("outfit")),
            nudityLevel=nudity,
            accessories=accessories,
            location=location,
            time_of_day=_coerce_enum(TimeOfDayType, raw.get("time_of_day")) or TimeOfDayType.DAYTIME,
            lighting=_coerce_enum(LightingType, raw.get("lighting")) or LightingType.NATURAL_SOFT,
            mood_kinks=mood_kinks,
            mood_personality=_coerce_enum(PersonalityType, raw.get("mood_personality")),
            setting=setting,
            activity=activity,
            pose_detail=pose_detail,
            outfit_detail=outfit_detail,
            expression=expression,
            narrative=narrative,
            story_title=(str(story_title)[:160] if story_title else None),
        )
    except Exception as e:  # noqa: BLE001 - a single bad beat must not kill the plan
        logger.warning(f"Dropping unparseable beat: {e}")
        return None


# ---------------------------------------------------------------------------
# Validation & repair (applied to EVERY provider's output)
# ---------------------------------------------------------------------------
# Identity tokens the planner must never emit in free-text (defense-in-depth).
_IDENTITY_TOKENS = set()
for _m in (ap.ETHNICITY_PHRASES, ap.HAIR_COLOR_PHRASES, ap.HAIR_STYLE_PHRASES, ap.EYE_COLOR_PHRASES):
    for _k in _m:
        _IDENTITY_TOKENS.add(_k.replace("_", " "))


def _enforce_beat_pool(s: SceneSpec, slot: _BeatSlot, controls: BatchControls, seed: int) -> SceneSpec:
    """
    Repair `s` (already a copy) so pose/outfit/location/time_of_day/lighting
    stay within `slot`'s own allowed pools. Off-pool values are re-picked with
    a seeded RNG (reproducible across repeated repairs of the same beat)
    rather than cleared, since a concrete in-pool scene is always preferable
    to a missing one. pose/outfit are only checked when non-None — the
    planner may legitimately skip either step for a beat.
    """
    rng = random.Random(seed)

    pose_pool = _allowed_pose_pool(slot.tmpl, controls)
    if s.pose is not None and s.pose not in pose_pool:
        s.pose = rng.choice(pose_pool) if pose_pool else None
        # The freeform pose_detail was authored for the ORIGINAL pose; after a re-pick
        # it would describe a body position the new reference image doesn't show, so
        # drop it and let the enum description drive (see build_pose_prompt).
        s.pose_detail = None

    outfit_pool = _allowed_outfit_pool(slot.tmpl, controls)
    if s.outfit is not None and s.outfit not in outfit_pool:
        s.outfit = rng.choice(outfit_pool) if outfit_pool else None

    location_pool = _allowed_location_pool(slot.tmpl, controls)
    if location_pool and s.location not in location_pool:
        s.location = rng.choice(location_pool)

    if s.time_of_day not in slot.tmpl.time_pool:
        s.time_of_day = rng.choice(list(slot.tmpl.time_pool))
    # Same venue-sanity (LIGHTING_LOCATION_COMPAT, keyed to THIS scene's now-final
    # location above) + natural/candid_phone theatrical-lighting exclusion as the
    # initial pick (see _allowed_lighting_pool) — an off-pool value from Venice/Manual
    # is repaired INTO the filtered/venue-narrowed pool, never the raw beat pool, so a
    # repair can no longer reintroduce a dramatic/moody/neon light OR an incoherent
    # venue pairing (the root cause of the moody_dim leak — see LIGHTING_LOCATION_COMPAT).
    lighting_pool = _allowed_lighting_pool(slot.tmpl, controls, location=s.location)
    if s.lighting not in lighting_pool:
        s.lighting = rng.choice(lighting_pool)

    return s


# ---------------------------------------------------------------------------
# Variety enforcement (set-level dedup) — plan 1.5
# ---------------------------------------------------------------------------
# Location coherence for the few poses/outfits that only make sense in specific
# places, so a variety re-pick never introduces an incoherent pairing (a "cooking"
# pose outside a kitchen, a bikini in an office). A pose/outfit absent from these
# maps is location-agnostic (allowed anywhere).
_KITCHENS = {LocationType.HOME_KITCHEN.value, LocationType.RESTAURANT_KITCHEN.value}
_OUTDOORS = {
    LocationType.PARK.value, LocationType.CITY_STREET.value, LocationType.FOREST_TRAIL.value,
    LocationType.BEACH.value, LocationType.POOLSIDE.value, LocationType.GARDEN.value,
    LocationType.ROOFTOP.value,
}
_SWIM_SPOTS = {
    LocationType.BEACH.value, LocationType.POOLSIDE.value, LocationType.HOME_BATHROOM.value,
    LocationType.HOTEL_ROOM.value,
}

# WS-P private/interior location groups for the pose<->location guard. Values (not enum
# members) to match _POSE_LOCATION_GUARD's shape. "home_*" is every home interior; private
# interiors add the hotel room + the closed pro photo studio; the lying/lounging group also
# allows semi-private outdoor lounging (poolside/beach) and the VIP lounge. Each group is a
# SUPERSET of the locations the hand-authored templates already pair these poses with (verified
# in test_pose_location_guard_never_breaks_authored_beats), so enforcing the guard never
# "repairs" a coherent authored beat — the sole deliberate exclusion is jogging @ cafe.
_HOME_INTERIORS = {
    LocationType.HOME_BEDROOM.value, LocationType.HOME_LIVING_ROOM.value,
    LocationType.HOME_KITCHEN.value, LocationType.HOME_BATHROOM.value,
    LocationType.HOME_BALCONY.value, LocationType.HOME_OFFICE.value,
}
_PRIVATE_INTERIORS = _HOME_INTERIORS | {
    LocationType.HOTEL_ROOM.value, LocationType.PHOTO_STUDIO.value,
}
_LYING_SPOTS = _PRIVATE_INTERIORS | {
    LocationType.POOLSIDE.value, LocationType.BEACH.value, LocationType.LUXURY_LOUNGE.value,
}
# Jogging/running reads coherent only on a runnable outdoor path or in a gym — NOT a cafe (the
# reported "jogging @ cafe" bug) nor the decorative garden/poolside/rooftop the old _OUTDOORS set
# let through. Judged from LocationType: park/city_street/beach/forest_trail are open paths, the
# gym has treadmills. POSE PACK: running shares this exact set (see _POSE_LOCATION_GUARD).
_JOG_SPOTS = {
    LocationType.PARK.value, LocationType.CITY_STREET.value, LocationType.BEACH.value,
    LocationType.FOREST_TRAIL.value, LocationType.GYM.value,
}

# POSE PACK: bent_over_from_behind is public-legal like its base pose bending_over (which stays
# location-agnostic), but a provocative bend-from-behind must never land in a straight, formal
# professional venue. Allowlist = every location EXCEPT those workplaces (office / classroom /
# library / hospital_ward). Derived from LocationType so a newly added location is permitted by
# default (only the four formal venues are ever excluded).
_FORMAL_WORK_VENUES = {
    LocationType.OFFICE.value, LocationType.CLASSROOM.value,
    LocationType.LIBRARY.value, LocationType.HOSPITAL_WARD.value,
}
_BENT_OVER_FROM_BEHIND_SPOTS = {loc.value for loc in LocationType} - _FORMAL_WORK_VENUES

# Pose -> the set of LOCATION values where that pose reads as coherent (WS-P extends this for
# the reported bad pairs). A pose absent from this map is location-agnostic (allowed anywhere).
# Each entry is DOCUMENTED with its rationale + the authored pairings it must cover:
_POSE_LOCATION_GUARD: Dict[str, set] = {
    # kitchen work — only makes sense at a stove/counter.
    PoseType.COOKING.value: _KITCHENS,
    PoseType.OPENING_FRIDGE.value: _KITCHENS,
    # dining — kitchens, cafe/restaurant, the living room, AND the garden (outdoor dining is
    # authored: OUT_AND_ABOUT "a relaxed moment at a cafe" pools garden). ADDED: garden.
    PoseType.EATING.value: _KITCHENS | {
        LocationType.CAFE.value, LocationType.RESTAURANT.value,
        LocationType.HOME_LIVING_ROOM.value, LocationType.GARDEN.value,
    },
    # WS-P jogging: TIGHTENED to outdoor paths + gym (was _OUTDOORS | {gym}); drops cafe (the
    # bug) and the decorative garden/poolside/rooftop. Covers authored {city_street, park}.
    PoseType.JOGGING.value: _JOG_SPOTS,
    # POSE PACK: running inherits jogging's exact location set (outdoor paths + gym).
    PoseType.RUNNING.value: _JOG_SPOTS,
    # POSE PACK: bent_over_from_behind — public-legal everywhere except the formal workplaces
    # (office/classroom/library/hospital_ward). NOT private-only (it stays legal at public social
    # venues); the allowlist is what keeps it out of a straight professional setting.
    PoseType.BENT_OVER_FROM_BEHIND.value: _BENT_OVER_FROM_BEHIND_SPOTS,
    # WS-P lying_back / lying_stomach: private/intimate lounging places only. Covers authored
    # {home_balcony, home_bathroom, home_bedroom, home_living_room, hotel_room, photo_studio}
    # for lying_back and {home_bedroom} for lying_stomach; poolside/beach lounging allowed too.
    PoseType.LYING_BACK.value: _LYING_SPOTS,
    PoseType.LYING_STOMACH.value: _LYING_SPOTS,
    # WS-P all_fours: private interiors + photo studio, PLUS gym/yoga_studio — the GYM arc's
    # "stretching, glistening after a session" authors all_fours at yoga_studio/gym (a coherent
    # post-workout stretch), so those stay allowed. Covers authored {gym, home_bedroom,
    # hotel_room, photo_studio, yoga_studio}.
    PoseType.ALL_FOURS.value: _PRIVATE_INTERIORS | {
        LocationType.GYM.value, LocationType.YOGA_STUDIO.value,
    },
    # WS-P kneeling: private interiors + photo studio. Covers authored {home_bathroom,
    # home_bedroom, hotel_room, photo_studio}.
    PoseType.KNEELING.value: _PRIVATE_INTERIORS,
}

_OUTFIT_LOCATION_GUARD: Dict[str, set] = {
    OutfitType.BIKINI.value: _SWIM_SPOTS,
    OutfitType.ONE_PIECE_SWIMSUIT.value: _SWIM_SPOTS,
    OutfitType.NURSE_UNIFORM.value: {LocationType.HOSPITAL_WARD.value, LocationType.HOME_BEDROOM.value},
    OutfitType.SCHOOL_UNIFORM.value: {
        LocationType.CLASSROOM.value, LocationType.LIBRARY.value, LocationType.HOME_BEDROOM.value,
    },
    OutfitType.MILITARY_UNIFORM.value: {LocationType.HOME_BEDROOM.value},
    OutfitType.CHEF_UNIFORM.value: {
        LocationType.RESTAURANT_KITCHEN.value, LocationType.HOME_KITCHEN.value, LocationType.HOME_BEDROOM.value,
    },
}

_UNIFORM_OUTFITS = {
    OutfitType.NURSE_UNIFORM, OutfitType.SCHOOL_UNIFORM,
    OutfitType.MILITARY_UNIFORM, OutfitType.CHEF_UNIFORM,
}


# ---------------------------------------------------------------------------
# Provocative-pose propriety (WS1c): spread/all-fours poses need a private venue.
# ---------------------------------------------------------------------------
# The reported failure: a "Sitting Legs Wide Open" (spread) pose planned ON nightclub
# furniture — an explicitly sexual floor/spread pose in an inherently-populated PUBLIC
# venue. These three poses read as coherent ONLY somewhere private (is_public_venue is
# False): the explicit spread poses (spread_legs, sitting_legs_wide_open) and the
# all-fours floor pose. Chosen defensibly from PoseType: the suggestive-but-not-explicit
# reclining/floor poses (lying_back/lying_stomach/kneeling) stay handled by the existing
# _POSE_LOCATION_GUARD (which already keeps them to lounging/private spots); these three
# are the ones whose own POSE_DESCRIPTIONS read as overtly sexual and so must never land
# in a public place. Folded into _pose_ok_at (below), so the SAME swap-first pose-repair
# machinery (_enforce_pose_compat / usage-cap + variety re-picks, full-vocab fallback)
# that fixes pose<->location and pose<->outfit incoherence also relocates these off a
# public venue by SWAPPING THE POSE — never the location. is_public_venue treats a
# forest trail / private garden / lab as private (solitary by nature), so a secluded
# outdoor spread pose is permitted.
#
# ONE PRECEDENCE CAVEAT (see _pose_ok_at): an explicit _POSE_LOCATION_GUARD allowlist entry
# WINS over this private-only rule. all_fours's guard entry deliberately lists gym/yoga_studio
# (a coherent post-workout stretch), so all_fours IS allowed at those two public venues;
# spread_legs and sitting_legs_wide_open have NO guard entry and so stay private-only at every
# other public crowd venue (club/bar/cafe/office/beach/…).
PRIVATE_ONLY_POSES: frozenset = frozenset({
    PoseType.SPREAD_LEGS, PoseType.SITTING_LEGS_WIDE_OPEN, PoseType.ALL_FOURS,
    # POSE PACK (07-14): the new overtly-sexual floor/kneel + straddle poses are private-only
    # too — barred from every inherently-populated PUBLIC venue. None of the three carries a
    # _POSE_LOCATION_GUARD allowlist entry (unlike all_fours, whose gym/yoga_studio entry WINS
    # per _pose_ok_at), so they stay private at EVERY public venue. bent_over_from_behind is
    # deliberately NOT here — it is public-legal (guarded only against formal workplaces).
    PoseType.ALL_FOURS_FROM_BEHIND, PoseType.KNEELING_ARCHED_BACK, PoseType.STRADDLING_CHAIR,
})
_PRIVATE_ONLY_POSE_VALUES: frozenset = frozenset(p.value for p in PRIVATE_ONLY_POSES)


# ---------------------------------------------------------------------------
# Pose <-> outfit coherence (athletic-attire guard) — WS-P
# ---------------------------------------------------------------------------
# The ATHLETIC poses (running/exercise) read as incoherent on formal/elegant attire — the
# reported "Jogging planned with velvet/maxi dresses". The compat RULE: an athletic pose may
# only pair with an outfit whose OUTFIT_STYLE_TAGS intersect this athletic-style set (sporty /
# streetwear / casual). Uniforms are EXEMPT (a work chapter keeps its uniform regardless —
# handled in _pose_outfit_ok, mirroring _prefer_wardrobe's _UNIFORM_OUTFITS retention).
_ATHLETIC_OUTFIT_STYLES: frozenset = frozenset({
    WardrobeStyleType.SPORTY, WardrobeStyleType.STREETWEAR, WardrobeStyleType.CASUAL_MINIMAL,
})
# The athletic pose set: jogging + squatting + running (the PoseType members that are clearly
# sport/exercise). Removed from a batch's pose pools up front when the wardrobe has no
# athletic-compatible outfit (see _allowed_pose_pool), and enforced per-scene at repair time.
# POSE PACK: running joins the set so it inherits jogging's exact wardrobe compat (same
# {sporty, streetwear, casual_minimal} requirement, via POSE_OUTFIT_COMPAT below) — a formal
# dress never gets "running", just as it never got "jogging".
ATHLETIC_POSES: frozenset = frozenset({PoseType.JOGGING, PoseType.SQUATTING, PoseType.RUNNING})
# pose value -> required outfit-style set (same {sporty, streetwear, casual} for every athletic
# pose). Shape mirrors _POSE_LOCATION_GUARD (value-keyed) so _pose_outfit_ok reads off it the
# same way _pose_ok_at reads _POSE_LOCATION_GUARD; a pose absent here is outfit-agnostic.
POSE_OUTFIT_COMPAT: Dict[str, frozenset] = {p.value: _ATHLETIC_OUTFIT_STYLES for p in ATHLETIC_POSES}


def _outfit_fill_pool(controls: BatchControls) -> List[OutfitType]:
    """Outfits eligible for auto-fill / variety re-pick: allowed − blocked − NAKED, stable order."""
    pool: List[OutfitType] = []
    for o in OutfitType:
        if o == OutfitType.NAKED:
            continue
        if o in (controls.blocked_outfits or []):
            continue
        if controls.allowed_outfits and o not in controls.allowed_outfits:
            continue
        pool.append(o)
    return pool


def _outfit_allowed(outfit: Optional[OutfitType], controls: BatchControls) -> bool:
    """
    Does `outfit` pass the batch allow/block filters? Reuses the fill-pool logic (which
    already drops NAKED, blocked, and non-allowlisted types), so a keyword-derived or
    reconciled outfit is only ever accepted when it is a valid fill target. NAKED always
    fails here (a caption describes clothing; nudity is driven by the ramp, not fill).
    """
    return outfit is not None and outfit in _outfit_fill_pool(controls)


# Keyword -> OutfitType map for reading a concrete garment back out of an outfit_detail
# CAPTION. The story director authors outfit_detail as the human-facing description of
# what she wears; when the `outfit` ENUM is null or disagrees with that caption the render
# either skips the outfit step (avatar's own clothes leak through) or mixes contradicting
# signals. This map lets the caption drive/repair the enum. NAKED is deliberately absent —
# a caption names clothing, and nudity is the ramp's job. Distinctive phrases map to their
# type; the LONGEST match wins at lookup time (see _outfit_from_detail), so specific phrases
# ("little black dress", "satin robe", "crop top") beat the generic single words they contain.
_OUTFIT_KEYWORDS: Dict[str, OutfitType] = {
    # dresses / gowns (bare "dress"/"suit" stay UNMAPPED — too ambiguous to be confident)
    "little black dress": OutfitType.LITTLE_BLACK_DRESS,
    "red evening gown": OutfitType.RED_EVENING_GOWN,
    "evening gown": OutfitType.RED_EVENING_GOWN,
    "gown": OutfitType.RED_EVENING_GOWN,
    "cocktail dress": OutfitType.COCKTAIL_DRESS,
    "cocktail": OutfitType.COCKTAIL_DRESS,
    "bodycon dress": OutfitType.BODYCON_DRESS,
    "bodycon": OutfitType.BODYCON_DRESS,
    "white summer dress": OutfitType.WHITE_SUMMER_DRESS,
    "summer dress": OutfitType.WHITE_SUMMER_DRESS,
    "sundress": OutfitType.WHITE_SUMMER_DRESS,  # compound: bare "dress" never matches inside it
    "floral maxi dress": OutfitType.FLORAL_MAXI_DRESS,
    "maxi dress": OutfitType.FLORAL_MAXI_DRESS,
    "floral dress": OutfitType.FLORAL_MAXI_DRESS,
    "velvet dress": OutfitType.VELVET_DRESS,
    "velvet": OutfitType.VELVET_DRESS,
    "satin slip dress": OutfitType.SATIN_SLIP_DRESS,
    "slip dress": OutfitType.SATIN_SLIP_DRESS,
    "polka dot dress": OutfitType.POLKA_DOT_DRESS_50S,
    "polka dot": OutfitType.POLKA_DOT_DRESS_50S,
    # tailored / formal
    "business suit": OutfitType.BUSINESS_SUIT,
    "pantsuit": OutfitType.BUSINESS_SUIT,
    "pant suit": OutfitType.BUSINESS_SUIT,
    "power suit": OutfitType.POWER_SUIT_80S,
    "blazer": OutfitType.BLAZER_TROUSERS,
    "pencil skirt": OutfitType.PENCIL_SKIRT_SET,
    "tuxedo": OutfitType.TUXEDO,
    # casual / street
    "denim jacket": OutfitType.DENIM_JACKET_JEANS,
    "jeans": OutfitType.DENIM_JACKET_JEANS,
    "denim": OutfitType.DENIM_JACKET_JEANS,
    "graphic tee": OutfitType.GRAPHIC_TEE_SHORTS,
    "hoodie": OutfitType.HOODIE_JOGGERS,
    "joggers": OutfitType.HOODIE_JOGGERS,
    "flannel": OutfitType.FLANNEL_SHIRT,
    "crop top": OutfitType.CROP_TOP_CARGO,
    "cargo": OutfitType.CROP_TOP_CARGO,
    "oversized streetwear": OutfitType.OVERSIZED_STREETWEAR,
    "streetwear": OutfitType.OVERSIZED_STREETWEAR,
    "bomber": OutfitType.BOMBER_JACKET_FIT,
    # active
    "yoga": OutfitType.YOGA_OUTFIT,
    "tennis": OutfitType.TENNIS_OUTFIT,
    "running gear": OutfitType.RUNNING_GEAR,
    "gym set": OutfitType.GYM_SET,
    "gym": OutfitType.GYM_SET,
    "sports bra": OutfitType.GYM_SET,
    # swim
    "one piece swimsuit": OutfitType.ONE_PIECE_SWIMSUIT,
    "swimsuit": OutfitType.ONE_PIECE_SWIMSUIT,
    "bikini": OutfitType.BIKINI,
    # outerwear
    "leather jacket": OutfitType.LEATHER_JACKET,
    "leather": OutfitType.LEATHER_JACKET,
    "trench coat": OutfitType.TRENCH_COAT,
    "trench": OutfitType.TRENCH_COAT,
    "puffer": OutfitType.PUFFER_JACKET,
    "fur coat": OutfitType.FUR_COAT,
    "fur": OutfitType.FUR_COAT,
    # cultural
    "kimono": OutfitType.KIMONO,
    "sari": OutfitType.SARI,
    "cheongsam": OutfitType.CHEONGSAM,
    "hanbok": OutfitType.HANBOK,
    "dirndl": OutfitType.DIRNDL,
    # eveningwear / lingerie / loungewear
    "sequin": OutfitType.SEQUIN_TOP_SKIRT,
    "jumpsuit": OutfitType.JUMPSUIT,
    "bell bottoms": OutfitType.BELL_BOTTOMS_70S,
    "silk pajama": OutfitType.SILK_PAJAMAS,
    "pajama": OutfitType.SILK_PAJAMAS,
    "pyjama": OutfitType.SILK_PAJAMAS,
    "camisole": OutfitType.SILK_PAJAMAS,
    "lace bodysuit": OutfitType.LACE_BODYSUIT,
    "bodysuit": OutfitType.LACE_BODYSUIT,
    "satin robe": OutfitType.SATIN_ROBE,
    "robe": OutfitType.SATIN_ROBE,
    # nightwear compounds — bare "gown"/"dress"/"robe" never match inside a single
    # word ("nightgown", "bathrobe", "nightdress"), so map the whole word explicitly.
    # A slip dress is the closest satin-nightgown analogue in the catalogue.
    "nightgown": OutfitType.SATIN_SLIP_DRESS,
    "night gown": OutfitType.SATIN_SLIP_DRESS,
    "nightie": OutfitType.SATIN_SLIP_DRESS,
    "nightdress": OutfitType.SATIN_SLIP_DRESS,
    "negligee": OutfitType.SATIN_SLIP_DRESS,
    "chemise": OutfitType.SATIN_SLIP_DRESS,
    "bathrobe": OutfitType.SATIN_ROBE,
    "dressing gown": OutfitType.SATIN_ROBE,
    # uniforms
    "nurse": OutfitType.NURSE_UNIFORM,
    "school uniform": OutfitType.SCHOOL_UNIFORM,
    "military uniform": OutfitType.MILITARY_UNIFORM,
    "military": OutfitType.MILITARY_UNIFORM,
    "chef": OutfitType.CHEF_UNIFORM,
}
# Longest / most-specific phrase first (ties broken alphabetically for determinism), so a
# lookup returns the tightest match, not whatever generic word it happens to contain first.
_OUTFIT_KEYWORDS_ORDER: List[str] = sorted(_OUTFIT_KEYWORDS, key=lambda p: (-len(p), p))

# Broad garment-CLASS words used only to notice that an outfit_detail names a DIFFERENT
# kind of garment than the enum when no specific keyword matched (the detail-dominant
# branch of _reconcile_outfit). Specific garments live in _OUTFIT_KEYWORDS above; these
# are the coarse classes a mismatch surfaces as. COMPOUND single-word garments are listed
# explicitly (e.g. "nightgown", "bathrobe") because the base class word never matches
# inside them — "\bgown\b" does NOT fire on "nightgown", "\brobe\b" not on "bathrobe".
# NOTE: whole words only, never wildcard-prefixed (a "\w*dress" would false-match
# "undressed", which shows up in scene prose).
_GARMENT_CLASS_WORDS: Tuple[str, ...] = (
    "dress", "gown", "skirt", "suit", "tuxedo", "robe", "bikini", "swimsuit", "lingerie",
    "bodysuit", "leotard", "jacket", "coat", "jeans", "denim", "pajama", "pyjama", "hoodie",
    "uniform", "kimono", "sari", "cheongsam", "hanbok", "dirndl", "jumpsuit", "shorts",
    "leggings", "lace", "sequin", "blazer", "trousers", "pants", "sweater",
    # compounds (base class word can't match inside them) + garments with no enum
    # (towel/bralette/apron): the conflict check must still recognize them as a class.
    "nightgown", "nightdress", "nightie", "negligee", "chemise", "camisole",
    "towel", "bralette", "apron",
)


def _outfit_from_detail(text: str) -> Optional[OutfitType]:
    """
    Best-effort map an outfit_detail CAPTION to a concrete OutfitType by keyword.
    Case-insensitive, word-boundary (so "fur" never matches "furnace"), tolerant of
    plurals and hyphens; the LONGEST / most-specific phrase wins (so "little black dress"
    beats the bare word it contains, "satin robe" beats "robe", "crop top" beats
    "leather"). Returns None when nothing recognizable matches — the caller then falls
    back to a pool pick (fill) or leaves the enum unchanged (reconcile). NAKED is never
    returned (a caption describes clothing; nudity is driven by the ramp, not this map).
    """
    if not text:
        return None
    low = re.sub(r"\s{2,}", " ", re.sub(r"[-/]", " ", str(text).lower()))
    for phrase in _OUTFIT_KEYWORDS_ORDER:
        if re.search(r"\b" + re.escape(phrase) + r"s?\b", low):
            return _OUTFIT_KEYWORDS[phrase]
    return None


def _detail_conflicts_with_outfit(outfit: OutfitType, detail: str) -> bool:
    """
    True when `detail` names a garment CLASS that the `outfit` enum plainly is NOT — used
    only in the conservative branch where no specific keyword matched. Needs a class word
    in the detail that is absent from the enum's own name words (e.g. enum "satin_robe" vs
    detail "chiffon dress"), so an ambiguous caption ("a silky wrap") or one consistent
    with the enum ("charcoal pinstripe suit" vs BUSINESS_SUIT) is never treated as a
    conflict. Keeps _reconcile_outfit from dropping a detail on a mere unknown descriptor.
    """
    low = re.sub(r"[-/]", " ", str(detail).lower())
    own = {w for w in re.split(r"[^a-z0-9]+", _val(outfit) or "") if w}
    classes = {w for w in _GARMENT_CLASS_WORDS if re.search(r"\b" + re.escape(w) + r"s?\b", low)}
    if not classes:
        return False
    return classes.isdisjoint(own)


def _reconcile_outfit(scene: SceneSpec, controls: BatchControls) -> None:
    """
    Make scene.outfit and scene.outfit_detail describe the SAME garment (mutates `scene`).
    The render prompt combines the outfit enum's tier prose with outfit_detail, so when the
    two disagree (production data: outfit=satin_robe but detail="leather crop top and
    high-waisted jeans"; outfit=little_black_dress but detail="satin robe") the image comes
    out confused. The caption is the richer signal the user actually sees, so the RULE is:
      * a confident keyword hit on the detail that is a DIFFERENT, allowed OutfitType
        -> override the enum to match the detail;
      * no confident hit, but the detail clearly names a garment class the enum is not
        -> KEEP the caption and mark the scene detail-dominant, so the outfit step renders
        the CAPTION alone (the enum then only gates the step + carries the nudity ramp) and
        the gallery card matches the image.
    Conservative on purpose: an ambiguous or already-consistent detail is left untouched,
    and a confident-but-blocked target is not forced in (allow/block wins).
    """
    if scene.outfit is None or not scene.outfit_detail:
        return
    derived = _outfit_from_detail(scene.outfit_detail)
    if derived is not None:
        if derived != scene.outfit and _outfit_allowed(derived, controls):
            scene.outfit = derived  # caption wins: enum now matches what she's described wearing
        return
    if _detail_conflicts_with_outfit(scene.outfit, scene.outfit_detail):
        # Contradicting caption with no confident enum target. KEEP it (don't drop) and
        # mark the scene detail-dominant: the outfit step then renders the caption alone
        # and the enum only gates the step, so the card caption and the render agree.
        # (Dropping it — the old behavior — silenced the contradiction but left the card
        # describing a garment the image never showed.)
        scene.outfit_detail_dominant = True


def _pose_ok_at(pose, location) -> bool:
    # PRECEDENCE: an explicit _POSE_LOCATION_GUARD allowlist entry is the AUTHORITATIVE answer
    # for where a pose may go, and it WINS over the WS1c private-only rule below. This is what
    # lets all_fours read as a coherent post-workout stretch at the gym/yoga_studio (both in
    # its guard entry) even though those are public venues — the private-only rule must not
    # silently override an explicit, deliberate allowance.
    allowed = _POSE_LOCATION_GUARD.get(_val(pose))
    if allowed is not None:
        return _val(location) in allowed
    # WS1c provocative-pose propriety: a spread/all-fours pose (PRIVATE_ONLY_POSES) that has NO
    # explicit guard entry is incoherent in an inherently-populated PUBLIC venue
    # (is_public_venue) — rejected here so the pose-repair machinery swaps the POSE (never the
    # location). spread_legs and sitting_legs_wide_open have no guard entry, so they stay
    # private-only at EVERY public venue; a private venue (home/hotel/studio, or a solitary-by-
    # nature forest trail/garden/lab) is allowed. Every consumer of _pose_ok_at — the variety/
    # usage-cap re-picks, _cap_location_candidates, and _enforce_pose_compat — honors this.
    if _val(pose) in _PRIVATE_ONLY_POSE_VALUES and sv.is_public_venue(location):
        return False
    return True


def _outfit_ok_at(outfit, location) -> bool:
    allowed = _OUTFIT_LOCATION_GUARD.get(_val(outfit))
    return allowed is None or _val(location) in allowed


def _outfit_is_athletic(outfit) -> bool:
    """True when `outfit` carries a style tag in the athletic-compatible set
    ({sporty, streetwear, casual_minimal}). Uniforms are professional-tagged, so they are
    naturally False here — they are compat-EXEMPT (see _pose_outfit_ok) but are not themselves
    athletic garments for the 'does the wardrobe offer one' pick-time test."""
    tags = ov.OUTFIT_STYLE_TAGS.get(outfit, frozenset())
    return bool(tags & _ATHLETIC_OUTFIT_STYLES)


def _pose_outfit_ok(pose, outfit) -> bool:
    """
    Pose<->outfit compatibility (WS-P). Non-athletic poses are UNCONSTRAINED (return True). An
    athletic pose (POSE_OUTFIT_COMPAT) may only pair with:
      * a uniform (ALWAYS exempt — the work-chapter carve-out, like _prefer_wardrobe), or
      * an outfit whose OUTFIT_STYLE_TAGS intersect the required athletic-style set.
    A None outfit (the outfit step is skipped -> the avatar's own clothes render) is treated as
    compatible: there is no dress-class garment being painted, so nothing to repair.
    """
    required = POSE_OUTFIT_COMPAT.get(_val(pose))
    if required is None:
        return True
    if outfit is None:
        return True
    if outfit in _UNIFORM_OUTFITS:
        return True
    return bool(ov.OUTFIT_STYLE_TAGS.get(outfit, frozenset()) & required)


def _athletic_poses_allowed(controls: BatchControls) -> bool:
    """
    May ATHLETIC poses (jogging/squatting) appear ANYWHERE in this batch? (WS-P, batch-level.)
    True iff the batch's effective wardrobe offers an athletic-compatible outfit:
    controls.wardrobe_outfits when the trait profile set one (the character's OWN wardrobe —
    identity, used directly so a beat-pool min_keep fallback can't dilute it), else the batch-wide
    fill pool (_outfit_fill_pool: every allow/block-permitted non-NAKED outfit — a superset of the
    template pools post-filter). Uniforms don't count (professional-tagged -> _outfit_is_athletic
    False), so a formal-only or formal-plus-uniform wardrobe correctly reports "no athletic
    outfit". A single batch-level gate (rather than per-beat) so the primary pick pool
    (_allowed_pose_pool) and EVERY slot=None re-pick fallback (_controls_pose_vocab) agree — no
    repair path can re-introduce an athletic pose the pick-time filter is dropping.
    """
    wardrobe = getattr(controls, "wardrobe_outfits", None)
    candidates = wardrobe if wardrobe else _outfit_fill_pool(controls)
    return any(_outfit_is_athletic(o) for o in candidates)


def _controls_pose_vocab(controls: BatchControls) -> List[PoseType]:
    """
    The full controls-filtered pose vocabulary for slot=None re-pick fallbacks (usage caps,
    variety, compat): every PoseType minus blocked_poses, minus ATHLETIC_POSES when the batch has
    no athletic-compatible outfit (_athletic_poses_allowed). Mirrors the athletic drop
    _allowed_pose_pool applies to a beat's own pool, so a fallback re-pick can never re-introduce
    an athletic pose the batch's wardrobe can't dress.
    """
    allow_athletic = _athletic_poses_allowed(controls)
    return [
        p for p in PoseType
        # POSE PACK ref latch: a pose whose reference PNG is not installed is "dark" — never a
        # fallback re-pick candidate. This is what keeps the effective pose vocabulary
        # byte-identical to the pre-POSE-PACK baseline: the 11 appended poses ship refless, so
        # this iterator yields exactly the original installed poses, in the original order, so
        # every seeded fallback re-pick (usage caps / variety / compat) reproduces unchanged
        # until the new references are committed (see services.pose_assets.has_pose_ref).
        if has_pose_ref(p)
        and p not in (controls.blocked_poses or [])
        and (allow_athletic or p not in ATHLETIC_POSES)
    ]


def _variety_pose_candidates(scene: SceneSpec, slot, controls: BatchControls) -> List[PoseType]:
    base = _allowed_pose_pool(slot.tmpl, controls) if slot is not None \
        else _controls_pose_vocab(controls)
    return [p for p in base if _pose_ok_at(p, scene.location)]


def _variety_outfit_candidates(scene: SceneSpec, slot, controls: BatchControls) -> List[OutfitType]:
    # WITH a slot: _allowed_outfit_pool already applies the wardrobe bias (choke point).
    # WITHOUT one: the fill pool gets the same soft wardrobe preference here.
    base = (
        _allowed_outfit_pool(slot.tmpl, controls) if slot is not None
        else _prefer_wardrobe(_outfit_fill_pool(controls), controls, min_keep=2)
    )
    return [o for o in base if o != OutfitType.NAKED and _outfit_ok_at(o, scene.location)]


def _slot_is_single_uniform(slot, controls: BatchControls) -> bool:
    """True when this beat position's allowed outfit pool is exactly one uniform — the
    work-chapter case where repeating that one outfit is intended, so it is exempt from
    the >=3-uses cap."""
    if slot is None:
        return False
    pool = _allowed_outfit_pool(slot.tmpl, controls)
    return len(pool) == 1 and pool[0] in _UNIFORM_OUTFITS


def _enforce_variety(
    scenes: List[SceneSpec], slots: List[_BeatSlot], controls: BatchControls
) -> List[SceneSpec]:
    """
    Single ordered walk enforcing set-level variety (plan 1.5). Per beat, repairs:
      * a duplicate non-None (outfit, pose) pair already seen earlier in the set,
      * an outfit used >= 3 times (unless this beat's slot pool is a single uniform —
        a work chapter is SUPPOSED to hold one uniform across its beats),
      * a (location, pose) identical to the immediately preceding beat.
    Pose is repaired FIRST (leaves the planned outfit intact), then outfit only if the
    offense survives. Candidates respect the block/allow lists and the pose/outfit
    location-coherence guards; NAKED is never introduced and nudityLevel is never touched.
    Seeded per beat so the whole pass is reproducible; an unresolvable beat is left as-is
    and logged.
    """
    if not scenes:
        return scenes

    outfit_counts: Dict[str, int] = {}
    for s in scenes:
        if s.outfit is not None:
            k = _val(s.outfit)
            outfit_counts[k] = outfit_counts.get(k, 0) + 1

    seen_pairs: set = set()

    def _pair_of(sc: SceneSpec) -> Optional[Tuple[str, str]]:
        if sc.outfit is None or sc.pose is None:
            return None
        return (_val(sc.outfit), _val(sc.pose))

    def _offenses(sc: SceneSpec, prev: Optional[SceneSpec], slot) -> Tuple[bool, bool, bool]:
        pair = _pair_of(sc)
        dup = pair is not None and pair in seen_pairs
        over = (
            sc.outfit is not None
            and outfit_counts.get(_val(sc.outfit), 0) >= 3
            and not _slot_is_single_uniform(slot, controls)
        )
        consec = (
            prev is not None
            and sc.pose is not None
            and _val(sc.pose) == _val(prev.pose)
            and _val(sc.location) == _val(prev.location)
        )
        return dup, over, consec

    for i, s in enumerate(scenes):
        slot = slots[i] if i < len(slots) else None
        prev = scenes[i - 1] if i > 0 else None
        rng = random.Random((controls.base_seed or 0) + 500009 * (i + 1))

        dup, over, consec = _offenses(s, prev, slot)
        if dup or over or consec:
            # Repair pose first (only helps dup/consec; leaves the outfit intact).
            if s.pose is not None and (dup or consec):
                order = _variety_pose_candidates(s, slot, controls)
                rng.shuffle(order)
                for p in order:
                    pv = _val(p)
                    if pv == _val(s.pose):
                        continue
                    if s.outfit is not None and (_val(s.outfit), pv) in seen_pairs:
                        continue
                    if prev is not None and pv == _val(prev.pose) and _val(s.location) == _val(prev.location):
                        continue
                    s.pose = p
                    # The freeform pose_detail described the OLD pose — stale after a
                    # re-pick, so drop it (enum description drives; see build_pose_prompt).
                    s.pose_detail = None
                    break
            dup, over, consec = _offenses(s, prev, slot)
            # Then repair outfit (fixes dup/over; respects the usage cap; never NAKED).
            if s.outfit is not None and (dup or over):
                order = _variety_outfit_candidates(s, slot, controls)
                rng.shuffle(order)
                for o in order:
                    ov = _val(o)
                    if ov == _val(s.outfit):
                        continue
                    if s.pose is not None and (ov, _val(s.pose)) in seen_pairs:
                        continue
                    if outfit_counts.get(ov, 0) >= 3:
                        continue
                    outfit_counts[_val(s.outfit)] = outfit_counts.get(_val(s.outfit), 0) - 1
                    outfit_counts[ov] = outfit_counts.get(ov, 0) + 1
                    s.outfit = o
                    break
            dup, over, consec = _offenses(s, prev, slot)
            if dup or over or consec:
                logger.debug(
                    "variety: unresolved beat %d (dup=%s over=%s consec=%s)", i, dup, over, consec
                )

        pair = _pair_of(s)
        if pair is not None:
            seen_pairs.add(pair)
    return scenes


def _cap_location_candidates(scene: SceneSpec, slot, controls: BatchControls) -> List[LocationType]:
    """
    Locations a usage-cap re-pick may move `scene` to: the beat position's own
    hand-authored pool when a slot constrains it (mirrors _variety_pose_candidates),
    else the full controls-filtered enum — always kept coherent with the scene's
    current pose/outfit via the location guards, so a cap re-pick never strands a
    "cooking" pose outside a kitchen or a bikini in an office.
    """
    if slot is not None:
        base = _allowed_location_pool(slot.tmpl, controls)
    else:
        base = [
            loc for loc in LocationType
            if loc not in (controls.blocked_locations or [])
            and (not controls.allowed_locations or loc in controls.allowed_locations)
        ]
    return [loc for loc in base if _pose_ok_at(scene.pose, loc) and _outfit_ok_at(scene.outfit, loc)]


def _enforce_usage_caps(
    scenes: List[SceneSpec], slots: List[_BeatSlot], controls: BatchControls
) -> List[SceneSpec]:
    """
    Per-batch pose/location usage caps (C1b) — the anti-monoculture guard behind the
    reported "pose standing_leaning 8x in a 24-photo batch". No single pose enum may
    be used more than max(2, ceil(count/8)) times and no single location more than
    max(2, ceil(count/6)) times across the set.

    Ordered walk with running counts: the first cap-many uses of a value keep it;
    each overflow use is re-picked deterministically (seeded per beat, the same
    base_seed-derived pattern as the outfit fill_rng) from the allowed pool —
    slot-pool-constrained when a beat pool applies, controls-filtered otherwise,
    respecting blocked_poses/blocked_locations/allowed_locations and the
    pose/outfit<->location coherence guards (_pose_ok_at/_outfit_ok_at) — choosing
    among the LEAST-USED options so the overflow spreads across the vocabulary
    instead of dogpiling onto the next value.

    A re-picked POSE also clears pose_detail: that freeform sentence was authored
    for the OLD pose, and keeping it would describe a body position the new
    reference image doesn't show — with it gone, build_pose_prompt falls back to
    the new enum's own description, so the target text and the reference image
    always agree. Nothing else on the scene is touched.

    Runs AFTER the nudity clamp/fill and the pair-dedup pass (_enforce_variety) so
    it never fights those repairs; an unresolvable overflow (pool exhausted — e.g. a
    work chapter whose beat pool is a single location) is left as-is and logged,
    mirroring _enforce_variety's unresolved-beat behavior.
    """
    n = len(scenes)
    if n == 0:
        return scenes
    pose_cap = max(2, math.ceil(n / 8))
    location_cap = max(2, math.ceil(n / 6))

    pose_counts: Dict[str, int] = {}
    location_counts: Dict[str, int] = {}
    for i, s in enumerate(scenes):
        slot = slots[i] if i < len(slots) else None

        # Pose cap (checked first, so the location re-pick below sees the final pose).
        # The pose cap is GLOBAL: pose_counts is tracked across the WHOLE batch (not
        # per-arc/day), so a multi-day batch does not multiply the allowance. The reported
        # "standing_leaning 8x in a 24-item batch" was NOT per-arc counting — it was the
        # re-pick being confined to this beat's own hand-authored slot pool, which for many
        # beats offered no under-cap alternative, so the overflow survived as "unresolved".
        # Fix: when the slot-constrained pool is exhausted, FALL BACK to the full
        # controls-filtered pose vocab (slot=None candidates, still coherence-guarded by
        # _pose_ok_at), so the global cap actually bites. Poses are largely location-
        # agnostic (only cooking/jogging/eating/opening_fridge are guarded), so dropping the
        # soft beat-pool restriction for an overflow pose is coherent and far better than
        # busting the cap.
        if s.pose is not None and pose_counts.get(_val(s.pose), 0) >= pose_cap:
            candidates = [
                p for p in _variety_pose_candidates(s, slot, controls)
                if _val(p) != _val(s.pose) and pose_counts.get(_val(p), 0) < pose_cap
            ]
            if not candidates:
                candidates = [
                    p for p in _variety_pose_candidates(s, None, controls)
                    if _val(p) != _val(s.pose) and pose_counts.get(_val(p), 0) < pose_cap
                ]
            if candidates:
                rng = random.Random((controls.base_seed or 0) + 900007 * (i + 1))
                least = min(pose_counts.get(_val(p), 0) for p in candidates)
                s.pose = rng.choice([p for p in candidates if pose_counts.get(_val(p), 0) == least])
                # Stale freeform text: pose_detail described the OLD pose (see docstring).
                s.pose_detail = None
            else:
                logger.debug("usage caps: pose overflow unresolved at beat %d", i)
        if s.pose is not None:
            pose_counts[_val(s.pose)] = pose_counts.get(_val(s.pose), 0) + 1

        # Location cap (location is required, so every scene counts).
        if location_counts.get(_val(s.location), 0) >= location_cap:
            candidates = [
                loc for loc in _cap_location_candidates(s, slot, controls)
                if _val(loc) != _val(s.location) and location_counts.get(_val(loc), 0) < location_cap
            ]
            if candidates:
                rng = random.Random((controls.base_seed or 0) + 1100003 * (i + 1))
                least = min(location_counts.get(_val(c), 0) for c in candidates)
                s.location = rng.choice(
                    [c for c in candidates if location_counts.get(_val(c), 0) == least]
                )
            else:
                logger.debug("usage caps: location overflow unresolved at beat %d", i)
        location_counts[_val(s.location)] = location_counts.get(_val(s.location), 0) + 1
    return scenes


# ---------------------------------------------------------------------------
# Location <-> nudity coherence (public-explicitness guard)
# ---------------------------------------------------------------------------
# Per-location nudity CEILING: the MOST explicit level that still reads as coherent at
# each place. The nudity ramp is positional (ramp[i] per photo, monotonic) and picked
# INDEPENDENTLY of where each beat is set, so a HIGH ramp slot can otherwise land on a
# public street/cafe/gym (observed: nudity=high, location=city_street). This table lets
# validate_and_repair keep the two in sync by SWAPPING scenes across ramp positions (the
# ramp stays positional; the scenes move), relocating to a private place only when no
# swap fits. Every LocationType value is covered; an unmapped value defaults to REVEALING
# (permissive, but never full-public nudity). Grouped by how exposed the place is:
LOCATION_NUDITY_CEILING: Dict[str, NudityLevel] = {
    # Fully private interiors -> HIGH (full nudity reads fine, nobody else is present).
    LocationType.HOME_BEDROOM.value: NudityLevel.HIGH,
    LocationType.HOME_LIVING_ROOM.value: NudityLevel.HIGH,
    LocationType.HOME_KITCHEN.value: NudityLevel.HIGH,
    LocationType.HOME_BATHROOM.value: NudityLevel.HIGH,
    LocationType.HOME_OFFICE.value: NudityLevel.HIGH,
    LocationType.HOTEL_ROOM.value: NudityLevel.HIGH,
    LocationType.PHOTO_STUDIO.value: NudityLevel.HIGH,   # closed pro set, private interior
    # Semi-private / plausibly-revealing -> REVEALING (swimwear/robe/overlooked spaces).
    LocationType.HOME_BALCONY.value: NudityLevel.REVEALING,
    LocationType.BEACH.value: NudityLevel.REVEALING,
    LocationType.POOLSIDE.value: NudityLevel.REVEALING,
    LocationType.GARDEN.value: NudityLevel.REVEALING,
    LocationType.ROOFTOP.value: NudityLevel.REVEALING,
    LocationType.LUXURY_LOUNGE.value: NudityLevel.REVEALING,  # exclusive VIP interior
    LocationType.CAR_INTERIOR.value: NudityLevel.REVEALING,   # enclosed personal cabin
    # Clearly PUBLIC places -> SUGGESTIVE (teasing/tight is the most that stays coherent).
    LocationType.OFFICE.value: NudityLevel.SUGGESTIVE,
    LocationType.HOSPITAL_WARD.value: NudityLevel.SUGGESTIVE,
    LocationType.CLASSROOM.value: NudityLevel.SUGGESTIVE,
    LocationType.GYM.value: NudityLevel.SUGGESTIVE,
    LocationType.YOGA_STUDIO.value: NudityLevel.SUGGESTIVE,
    LocationType.RESTAURANT_KITCHEN.value: NudityLevel.SUGGESTIVE,
    LocationType.LIBRARY.value: NudityLevel.SUGGESTIVE,
    LocationType.SALON.value: NudityLevel.SUGGESTIVE,
    LocationType.STAGE.value: NudityLevel.SUGGESTIVE,
    LocationType.LAB.value: NudityLevel.SUGGESTIVE,
    LocationType.PARK.value: NudityLevel.SUGGESTIVE,
    LocationType.CITY_STREET.value: NudityLevel.SUGGESTIVE,
    LocationType.FOREST_TRAIL.value: NudityLevel.SUGGESTIVE,
    LocationType.CAFE.value: NudityLevel.SUGGESTIVE,
    LocationType.RESTAURANT.value: NudityLevel.SUGGESTIVE,
    LocationType.BAR.value: NudityLevel.SUGGESTIVE,
    LocationType.NIGHTCLUB.value: NudityLevel.SUGGESTIVE,
}


def _location_ceiling(location) -> NudityLevel:
    """Per-location nudity ceiling; unmapped/unknown -> REVEALING (permissive, not full public)."""
    return LOCATION_NUDITY_CEILING.get(_val(location), NudityLevel.REVEALING)


def _private_relocation_pool(controls: BatchControls, need_idx: int) -> List[LocationType]:
    """
    Private-enough locations to relocate an over-exposed beat to, ranked home_bedroom-first,
    whose ceiling reaches `need_idx`. Respects blocked_locations and any allowed_locations
    filter, so a relocation never introduces a location the batch forbade.
    """
    ranked = [
        LocationType.HOME_BEDROOM, LocationType.HOTEL_ROOM, LocationType.HOME_BATHROOM,
        LocationType.HOME_LIVING_ROOM, LocationType.HOME_OFFICE, LocationType.HOME_KITCHEN,
        LocationType.PHOTO_STUDIO,
    ]
    out: List[LocationType] = []
    for loc in ranked:
        if loc in (controls.blocked_locations or []):
            continue
        if controls.allowed_locations and loc not in controls.allowed_locations:
            continue
        if _nudity_index(_location_ceiling(loc)) >= need_idx:
            out.append(loc)
    return out


def _enforce_location_nudity_ceiling(
    scenes: List[SceneSpec], ramp: List[NudityLevel], controls: BatchControls
) -> List[SceneSpec]:
    """
    Keep the positional nudity ramp COHERENT with each photo's location: no photo may carry a
    level above its location's LOCATION_NUDITY_CEILING (so a HIGH ramp slot never lands on a
    public street/cafe/gym). The ramp is authoritative and positional — it never drops — so the
    SCENES are made to fit it: for each position that over-exposes its place, SWAP the whole
    scene with another position whose scene fits here AND whose own ramp slot this scene can
    satisfy. A swap is a PERMUTATION — it preserves the location/pose/outfit multiset, so the
    just-run variety + usage-cap guarantees stay intact. Only when no swap fits do we RELOCATE
    the scene to a private place (deterministic/seeded, honoring allow/block/allowed filters,
    home_bedroom-first) — keeping the pose (kept simple; a stray pose is far less bad than public
    explicitness). Finally each position's nudity is re-set from the ramp, clamped to the
    (possibly new) location ceiling — the clamp only bites in the degenerate case where NO private
    location is allowed at all; otherwise the ramp is preserved exactly, so it stays monotonic.

    Runs LAST (after _enforce_variety + _enforce_usage_caps) so it sees the FINAL locations those
    passes produced and gets the final say on the ceiling invariant; because swaps are permutations
    they cannot re-introduce a variety/cap violation. No-op for sfw_only / an all-LOW ramp (LOW <=
    every ceiling).
    """
    n = len(scenes)
    if n == 0 or not ramp or controls.sfw_only:
        return scenes
    if all(_nudity_index(lvl) == 0 for lvl in ramp[:n]):
        return scenes  # all-LOW ramp fits every location — nothing to do

    def fits(location, need_idx: int) -> bool:
        return _nudity_index(_location_ceiling(location)) >= need_idx

    # Highest-nudity positions first: they are the hardest to place, so satisfy them before the
    # easy low slots consume the scarce private-location scenes.
    for i in sorted(range(n), key=lambda k: _nudity_index(ramp[k]), reverse=True):
        need = _nudity_index(ramp[i])
        if fits(scenes[i].location, need):
            continue
        # Prefer the lowest-ramp partners so the over-exposed public scene drifts to a low slot.
        swapped = False
        for j in sorted(range(n), key=lambda k: _nudity_index(ramp[k])):
            if j == i:
                continue
            if fits(scenes[j].location, need) and fits(scenes[i].location, _nudity_index(ramp[j])):
                scenes[i], scenes[j] = scenes[j], scenes[i]
                swapped = True
                break
        if swapped:
            continue
        # No swap fits -> relocate to a private place (seeded pick spreads them; keep the pose).
        pool = _private_relocation_pool(controls, need)
        if pool:
            rng = random.Random((controls.base_seed or 0) + 1300021 * (i + 1))
            scenes[i].location = rng.choice(pool)

    # Re-set nudity from the ramp, clamped to the final location's ceiling (clamp only bites when
    # no private location was allowed at all). Refresh a now-exposed scene that has no outfit so
    # the exposure actually renders (the outfit step only runs when an outfit enum is set).
    # The fill prefers the wardrobe subset (never empties — see _prefer_wardrobe).
    fill_pool = _prefer_wardrobe(_outfit_fill_pool(controls), controls, min_keep=2)
    for i in range(n):
        if i >= len(ramp):
            continue
        lvl_idx = min(_nudity_index(ramp[i]), _nudity_index(_location_ceiling(scenes[i].location)))
        scenes[i].nudityLevel = _NUDITY_LADDER[lvl_idx]
        if scenes[i].nudityLevel != NudityLevel.LOW and scenes[i].outfit is None and fill_pool:
            rng = random.Random((controls.base_seed or 0) + 1700003 * (i + 1))
            scenes[i].outfit = rng.choice(fill_pool)
    return scenes


# ---------------------------------------------------------------------------
# Outfit <-> nudity coherence (exposure-cap guard) — A1
# ---------------------------------------------------------------------------
def _exposure_repick_pool(
    controls: BatchControls, need_idx: int, location
) -> List[OutfitType]:
    """
    Outfits eligible for an exposure-cap re-pick at `location`: batch-allowed (allow/block +
    sfw rules) AND exposure-capable (cap >= need_idx) AND location-coherent
    (_outfit_ok_at). CRUCIAL DIFFERENCE from _outfit_fill_pool: this pool INCLUDES NAKED
    (cap HIGH) whenever content is not sfw_only and NAKED isn't blocked/disallowed — a slot
    that needs full nudity must be able to reach it, and the ordinary fill pool deliberately
    strips NAKED (a caption names clothing). Stable enum order for deterministic seeding.
    """
    out: List[OutfitType] = []
    for o in OutfitType:
        if controls.sfw_only and o == OutfitType.NAKED:
            continue
        if o in (controls.blocked_outfits or []):
            continue
        if controls.allowed_outfits and o not in controls.allowed_outfits:
            continue
        if _nudity_index(ov.outfit_exposure_cap(o)) < need_idx:
            continue
        if not _outfit_ok_at(o, location):
            continue
        out.append(o)
    # Prefer the wardrobe subset when any cap-compliant wardrobe outfit exists (min_keep=1),
    # but CAP COMPLIANCE BEATS WARDROBE: `out` is already cap-constrained, so if no wardrobe
    # outfit is compliant the full compliant pool stands (_prefer_wardrobe falls back).
    return _prefer_wardrobe(out, controls, min_keep=1)


def _enforce_outfit_exposure_cap(
    scenes: List[SceneSpec], ramp: List[NudityLevel], controls: BatchControls
) -> List[SceneSpec]:
    """
    Keep every photo's nudity LABEL within what its OUTFIT can honestly render
    (ov.OUTFIT_EXPOSURE_CAP): no photo may be labeled more explicit than its garment can
    show (so "Mostly nude" never renders a fully-dressed tee + shorts). The sibling of
    _enforce_location_nudity_ceiling, and it runs immediately AFTER it, mirroring its
    swap-first design — but the constraint is the garment, not the place.

    ORDER + INTERPLAY (documented): the location pass runs FIRST and is authoritative for
    each scene's final LOCATION; this pass then treats those locations as fixed and
    reconciles the OUTFIT to the position's need, where a position's need is
    `min(ramp[i], ceiling(final_location))` — i.e. the exact level the location pass left.
    So an exposure re-pick is always constrained by the already-final location ceiling, and
    the two invariants compose: final label <= cap(outfit) AND <= ceiling(location).

    For each position whose outfit can't reach its need:
      (a) SWAP OUTFITS with a partner j so BOTH positions end compliant — e.g. a HIGH-capable
          satin_robe that landed on a low slot trades with the MEDIUM dress stuck on a high
          slot. Only the outfit (+ its outfit_detail/dominant flag) moves; each position
          KEEPS its location, so the location pass's ceiling outcome is preserved exactly (a
          whole-scene swap would drag a public scene onto a high slot and silently undo the
          ceiling pass). The outfit multiset is preserved, so variety/usage-cap counts hold,
          and coherence is re-checked with _outfit_ok_at at each new home.
      (b) else RE-PICK the outfit for this position from _exposure_repick_pool (cap >= need,
          location-coherent, controls-allowed, NAKED included when allowed). The stale
          outfit_detail/dominant flag is dropped (it described the old garment), mirroring
          how a pose re-pick drops pose_detail.
      (c) last resort — no compliant outfit exists at all (e.g. only MEDIUM-capable outfits
          allowed but the slot needs HIGH): the final re-assert below LOWERS the label to
          the outfit's cap. Truthful label beats reaching max. This is the DOCUMENTED
          monotonicity exception — the ramp may dip only when no allowed garment can
          honestly render the target.

    Finally every label is re-asserted to `min(positional need, outfit cap)` with locations
    unchanged, so a swap/re-pick keeps the ramp exactly (cap >= need -> min is need) and only
    (c) yields a dip. No-op for sfw_only / an all-LOW ramp (LOW <= every cap).
    """
    n = len(scenes)
    if n == 0 or not ramp or controls.sfw_only:
        return scenes

    def positional_need(i: int) -> int:
        base = _nudity_index(ramp[i]) if i < len(ramp) else 0
        return min(base, _nudity_index(_location_ceiling(scenes[i].location)))

    def cap_idx(outfit) -> int:
        # No outfit -> nothing to cap (the location pass fills an outfit on every non-LOW
        # scene, so a None here is a zero-need slot); treat as trivially compliant.
        return 999 if outfit is None else _nudity_index(ov.outfit_exposure_cap(outfit))

    if all(positional_need(i) == 0 for i in range(n)):
        return scenes  # all-LOW target fits every garment — nothing to do

    def _outfit_bundle(s: SceneSpec) -> Tuple:
        return (s.outfit, s.outfit_detail, s.outfit_detail_dominant)

    def _set_outfit_bundle(s: SceneSpec, bundle: Tuple) -> None:
        s.outfit, s.outfit_detail, s.outfit_detail_dominant = bundle

    # (a)/(b): hardest (highest-need) positions first, so they claim the scarce
    # exposure-capable garments before the easy low slots.
    for i in sorted(range(n), key=positional_need, reverse=True):
        if cap_idx(scenes[i].outfit) >= positional_need(i):
            continue
        # (a) OUTFIT-only swap — locations stay put (ceiling outcome preserved). Prefer the
        # lowest-need partners so this over-promised garment drifts to a low slot. Require
        # both garments compliant at their new positions AND location-coherent there.
        swapped = False
        for j in sorted(range(n), key=positional_need):
            if j == i or scenes[j].outfit is None:
                continue
            oi, oj = scenes[i].outfit, scenes[j].outfit
            if cap_idx(oj) < positional_need(i) or cap_idx(oi) < positional_need(j):
                continue
            if not _outfit_ok_at(oj, scenes[i].location) or not _outfit_ok_at(oi, scenes[j].location):
                continue
            bundle_i = _outfit_bundle(scenes[i])
            _set_outfit_bundle(scenes[i], _outfit_bundle(scenes[j]))
            _set_outfit_bundle(scenes[j], bundle_i)
            swapped = True
            break
        if swapped:
            continue
        # (b) re-pick the outfit for this position (cap >= need, location-coherent, allowed).
        pool = _exposure_repick_pool(controls, positional_need(i), scenes[i].location)
        if pool:
            rng = random.Random((controls.base_seed or 0) + 1500007 * (i + 1))
            new_outfit = rng.choice(pool)
            if new_outfit != scenes[i].outfit:
                scenes[i].outfit = new_outfit
                # The old caption described the previous garment class — stale now.
                scenes[i].outfit_detail = None
                scenes[i].outfit_detail_dominant = False
        # (c) empty pool -> no compliant garment exists: fall through; the re-assert below
        # lowers this label to the outfit's cap (the documented monotonicity exception).

    # Re-assert every label = min(positional need, outfit cap): ramp preserved wherever a
    # swap/re-pick made the outfit compliant; a truthful dip only where (c) applied.
    for i in range(n):
        need = positional_need(i)
        if scenes[i].outfit is None:
            scenes[i].nudityLevel = _NUDITY_LADDER[need]
        else:
            scenes[i].nudityLevel = _NUDITY_LADDER[min(need, cap_idx(scenes[i].outfit))]
    return scenes


# ---------------------------------------------------------------------------
# Pose <-> outfit + pose <-> location coherence (WS-P repair)
# ---------------------------------------------------------------------------
def _pose_compat_candidates(scene: SceneSpec, slot, controls: BatchControls) -> List[PoseType]:
    """
    Poses a compat re-pick may assign to `scene`: the beat's own allowed pose pool when a slot
    constrains it (mirrors _variety_pose_candidates / _cap_location_candidates), else the full
    controls-filtered pose vocab — kept coherent with the scene's FINAL location AND outfit via
    BOTH guards (_pose_ok_at + _pose_outfit_ok), so a re-pick never strands an athletic pose on
    an elegant dress or a floor pose in a public place.
    """
    base = _allowed_pose_pool(slot.tmpl, controls) if slot is not None \
        else _controls_pose_vocab(controls)
    return [p for p in base if _pose_ok_at(p, scene.location) and _pose_outfit_ok(p, scene.outfit)]


def _enforce_pose_compat(
    scenes: List[SceneSpec], slots: List[_BeatSlot], controls: BatchControls
) -> List[SceneSpec]:
    """
    WS-P repair: every scene's POSE must be coherent with its FINAL location (_POSE_LOCATION_GUARD
    via _pose_ok_at) AND its FINAL outfit (POSE_OUTFIT_COMPAT via _pose_outfit_ok). Fixes both
    reported incoherences in one pass — an athletic pose on an elegant dress (outfit), and
    "jogging @ cafe" (location) — using the SAME swap-first pattern as the ceiling/exposure/
    adjacency guards.

    ORDER (documented at the call site too): runs AFTER _enforce_location_nudity_ceiling +
    _enforce_outfit_exposure_cap, so each scene's location and outfit are already FINAL (the
    exposure pass can re-pick an outfit onto an athletic-pose scene, so this must see the final
    outfit), and BEFORE _enforce_pose_adjacency, so any consecutive-pose duplicate a pose MOVE
    introduces is cleaned up by the very next pass. It never touches nudity/outfit/location/
    expression, so the monotonic ramp, location ceilings, exposure caps and the A2 expression
    invariants are all preserved unchanged.

    Per offending scene, the fix is chosen from this priority ladder — every rung EXCEPT the
    last preserves the pose usage cap (a swap preserves the pose MULTISET exactly; an under-cap
    re-pick stays under the cap):
      1) STRICT SWAP  — swap the pose (+ its matched pose_detail) with a partner j where both
                        ends end location+outfit-compliant AND neither move creates a new pose
                        adjacency. Multiset-preserving -> cap + adjacency both intact.
      2) under-cap, non-adjacent RE-PICK from _pose_compat_candidates (clean: cap + adjacency).
      3) under-cap RE-PICK (may sit adjacent -> the next pass, _enforce_pose_adjacency, fixes it).
      4) LOOSE SWAP   — a compliant partner that creates an adjacency (cleaned up next pass);
                        still multiset-preserving, so the cap is untouched.
      5) any compat RE-PICK — LAST RESORT only (no swap partner and no under-cap pose exist at
                        all); the only rung that may nudge one pose +1 over the cap, mirroring
                        _enforce_usage_caps' own best-effort "unresolved overflow" behavior.
    A re-pick drops the stale pose_detail (it described the old pose). An utterly unresolvable
    scene (no compatible pose anywhere) is left as-is and logged — soft failure, never a crash.
    """
    n = len(scenes)
    if n == 0:
        return scenes
    pose_cap = max(2, math.ceil(n / 8))
    counts: Dict[str, int] = {}
    for s in scenes:
        if s.pose is not None:
            counts[_val(s.pose)] = counts.get(_val(s.pose), 0) + 1

    def compliant(sc: SceneSpec) -> bool:
        return sc.pose is None or (
            _pose_ok_at(sc.pose, sc.location) and _pose_outfit_ok(sc.pose, sc.outfit)
        )

    def neighbors_ok(pose, idx: int, ignore: int) -> bool:
        """No neighbour of `idx` (other than `ignore`, the swap partner) already holds `pose`."""
        pv = _val(pose)
        for nb in (idx - 1, idx + 1):
            if nb == ignore or not (0 <= nb < n):
                continue
            if scenes[nb].pose is not None and _val(scenes[nb].pose) == pv:
                return False
        return True

    def do_swap(i: int, j: int) -> None:
        scenes[i].pose, scenes[j].pose = scenes[j].pose, scenes[i].pose
        scenes[i].pose_detail, scenes[j].pose_detail = scenes[j].pose_detail, scenes[i].pose_detail
        # multiset preserved -> counts unchanged.

    def do_repick(i: int, new_pose) -> None:
        counts[_val(scenes[i].pose)] = counts.get(_val(scenes[i].pose), 0) - 1
        counts[_val(new_pose)] = counts.get(_val(new_pose), 0) + 1
        scenes[i].pose = new_pose
        scenes[i].pose_detail = None  # stale: described the OLD pose (see the other re-picks).

    for i in range(n):
        s = scenes[i]
        if compliant(s):
            continue
        pi = s.pose
        # Multiset-preserving swap partners (both ends location+outfit compliant) — the FIRST
        # (lowest-index, deterministic) strict/loose partner is kept.
        strict_swap: Optional[int] = None
        loose_swap: Optional[int] = None
        for j in range(n):
            if j == i or scenes[j].pose is None:
                continue
            pj = scenes[j].pose
            if _val(pj) == _val(pi):
                continue
            if not (_pose_ok_at(pj, s.location) and _pose_outfit_ok(pj, s.outfit)):
                continue
            if not (_pose_ok_at(pi, scenes[j].location) and _pose_outfit_ok(pi, scenes[j].outfit)):
                continue
            if neighbors_ok(pj, i, j) and neighbors_ok(pi, j, i):
                if strict_swap is None:
                    strict_swap = j
            elif loose_swap is None:
                loose_swap = j
        # Compat re-pick candidates. Draw from the FULL controls-compat vocab (not just this
        # beat's tiny authored pose pool — e.g. the jogging beat authors only {standing_leaning,
        # jogging}, so staying in-pool would force standing_leaning even when it is already at
        # cap). Members of the beat's own pool are PREFERRED (coherence) via the sort key, but
        # breaking out keeps the usage cap + adjacency satisfiable — exactly how _enforce_usage_caps
        # falls back to the full vocab. Seeded-shuffled so ties break deterministically yet spread.
        slot = slots[i] if i < len(slots) else None
        slot_set = set(_pose_compat_candidates(s, slot, controls)) if slot is not None else set()
        cands = [p for p in _pose_compat_candidates(s, None, controls) if _val(p) != _val(pi)]
        rng = random.Random((controls.base_seed or 0) + 2100011 * (i + 1))
        rng.shuffle(cands)
        under_nonadj = [p for p in cands if counts.get(_val(p), 0) < pose_cap and neighbors_ok(p, i, -1)]
        under = [p for p in cands if counts.get(_val(p), 0) < pose_cap]

        def _best(pool):
            # prefer an in-beat-pool pose (coherence), then the least-used (spreads the cap);
            # `pool` is seeded-shuffled so equal keys resolve deterministically.
            return min(pool, key=lambda p: (p not in slot_set, counts.get(_val(p), 0)))

        if strict_swap is not None:              # (1) cap + adjacency preserved
            do_swap(i, strict_swap)
        elif under_nonadj:                        # (2) cap + adjacency preserved
            do_repick(i, _best(under_nonadj))
        elif under:                               # (3) cap preserved (adjacency fixed next pass)
            do_repick(i, _best(under))
        elif loose_swap is not None:              # (4) cap preserved (adjacency fixed next pass)
            do_swap(i, loose_swap)
        elif cands:                               # (5) LAST RESORT — may nudge +1 over cap
            do_repick(i, _best(cands))
        else:
            logger.debug(
                "pose compat: unresolved beat %d (pose=%s loc=%s outfit=%s)",
                i, _val(pi), _val(s.location), _val(s.outfit),
            )
    return scenes


# ---------------------------------------------------------------------------
# Adjacency variety (A2 item 5): no identical pose/expression in consecutive items
# ---------------------------------------------------------------------------
def _enforce_pose_adjacency(scenes: List[SceneSpec], controls: BatchControls) -> List[SceneSpec]:
    """
    Best-effort: no identical pose in two CONSECUTIVE items (a sliding window of 2).

    Primary repair — SWAP the pose field (with its matched pose_detail) between the offending
    position and a donor. A swap preserves the global pose MULTISET (so the usage cap holds) and
    touches neither nudity/outfit/location nor scene order (so the location-ceiling + exposure-cap
    invariants are intact). A donor is valid only when it keeps BOTH ends location-coherent
    (_pose_ok_at) AND pose<->outfit compatible (_pose_outfit_ok — so this pass, which runs AFTER
    _enforce_pose_compat, can never re-introduce an athletic pose on a non-athletic outfit) AND
    creates NO new adjacency at either site.

    Fallback — when NO donor swap fits (the compat constraint can make swaps scarce in a tight
    batch), RE-PICK scenes[i].pose from the controls-compat vocab to a pose that is location- AND
    outfit-compatible here and differs from both neighbours, PREFERRING poses still under the
    usage cap so the cap survives. Only fires when a swap could not resolve the pair, so a batch
    whose adjacencies the swap loop already clears (the common case) is byte-identical to the
    swap-only behaviour. If neither a swap nor a compatible re-pick exists, the pair is left as-is
    — a soft constraint never overrides the hard ones.
    """
    n = len(scenes)
    pose_cap = max(2, math.ceil(n / 8))
    counts: Dict[str, int] = {}
    for s in scenes:
        if s.pose is not None:
            counts[_val(s.pose)] = counts.get(_val(s.pose), 0) + 1
    for i in range(1, n):
        a, b = scenes[i - 1].pose, scenes[i].pose
        if a is None or b is None or _val(a) != _val(b):
            continue
        fixed = False
        for j in range(n):
            if j == i or scenes[j].pose is None:
                continue
            pj = scenes[j].pose
            if _val(pj) == _val(b):
                continue  # identical pose — swapping it in wouldn't break the duplicate
            if not _pose_ok_at(pj, scenes[i].location) or not _pose_ok_at(b, scenes[j].location):
                continue
            # WS-P: a donor swap must also keep BOTH ends pose<->outfit compatible, so this
            # adjacency repair (which runs AFTER _enforce_pose_compat) can never re-introduce an
            # athletic pose on a non-athletic outfit that the compat pass just resolved.
            if not _pose_outfit_ok(pj, scenes[i].outfit) or not _pose_outfit_ok(b, scenes[j].outfit):
                continue
            # pj lands at i: must differ from i's neighbors
            if _val(pj) == _val(scenes[i - 1].pose):
                continue
            if i + 1 < n and scenes[i + 1].pose is not None and _val(pj) == _val(scenes[i + 1].pose):
                continue
            # b lands at j: must differ from j's neighbors
            if j - 1 >= 0 and scenes[j - 1].pose is not None and _val(b) == _val(scenes[j - 1].pose):
                continue
            if j + 1 < n and scenes[j + 1].pose is not None and _val(b) == _val(scenes[j + 1].pose):
                continue
            scenes[i].pose, scenes[j].pose = pj, b
            scenes[i].pose_detail, scenes[j].pose_detail = scenes[j].pose_detail, scenes[i].pose_detail
            fixed = True
            break
        if fixed:
            continue
        # Fallback re-pick (only when no swap donor fit): a compat, non-adjacent pose, preferring
        # under-cap so the usage cap survives. Keeps the WS-P compat guarantee AND clears the
        # adjacency the compat pass may have left in a tight 3-way (compat/cap/adjacency) spot.
        neighbours = {_val(scenes[i - 1].pose)}
        if i + 1 < n and scenes[i + 1].pose is not None:
            neighbours.add(_val(scenes[i + 1].pose))
        cands = [
            p for p in _controls_pose_vocab(controls)
            if _val(p) != _val(b) and _val(p) not in neighbours
            and _pose_ok_at(p, scenes[i].location) and _pose_outfit_ok(p, scenes[i].outfit)
        ]
        if not cands:
            continue
        rng = random.Random((controls.base_seed or 0) + 2500009 * (i + 1))
        rng.shuffle(cands)
        under = [p for p in cands if counts.get(_val(p), 0) < pose_cap]
        new_pose = min(under or cands, key=lambda p: counts.get(_val(p), 0))
        counts[_val(scenes[i].pose)] = counts.get(_val(scenes[i].pose), 0) - 1
        counts[_val(new_pose)] = counts.get(_val(new_pose), 0) + 1
        scenes[i].pose = new_pose
        scenes[i].pose_detail = None  # stale: described the old pose.
    return scenes


def _enforce_expression_adjacency(scenes: List[SceneSpec], controls: BatchControls) -> List[SceneSpec]:
    """
    Best-effort: no identical expression in two consecutive items. Ceiling/exposure SWAPS can
    reorder scenes and put two equal expressions side by side (the deterministic planner
    assigned them adjacency-free on the ORIGINAL order); this restores the invariant on the
    FINAL order by swapping the expression field between positions. A field swap preserves the
    expression multiset, so the ~1/3 candid share and per-expression usage cap are kept.

    WS1b: this runs right AFTER _enforce_expression_compat, so a donor swap must also keep BOTH
    ends situation-COMPATIBLE (_expression_allowed) — otherwise breaking an adjacency could
    re-introduce a bright grin on a HIGH scene the compat pass just fixed. Compat is the hard
    rule and adjacency the soft one: a pair with no compat-preserving donor is left as-is
    (adjacency was already best-effort). Leaves the pair unchanged if no valid donor fits.
    """
    n = len(scenes)

    def ok(expr, idx) -> bool:
        s = scenes[idx]
        return _expression_allowed(expr, s.pose, s.nudityLevel, s.location, s.outfit)

    for i in range(1, n):
        a, b = scenes[i - 1].expression, scenes[i].expression
        if not a or not b or a != b:
            continue
        for j in range(n):
            if j == i or not scenes[j].expression:
                continue
            ej = scenes[j].expression
            if ej == b:
                continue
            if ej == scenes[i - 1].expression:
                continue
            if i + 1 < n and scenes[i + 1].expression and ej == scenes[i + 1].expression:
                continue
            if j - 1 >= 0 and scenes[j - 1].expression and b == scenes[j - 1].expression:
                continue
            if j + 1 < n and scenes[j + 1].expression and b == scenes[j + 1].expression:
                continue
            # WS1b: the swap must not violate expression<->situation compat at either new home.
            if not ok(ej, i) or not ok(b, j):
                continue
            scenes[i].expression, scenes[j].expression = ej, b
            break
    return scenes


# ---------------------------------------------------------------------------
# Expression <-> situation compat repair (WS1b) — the authoritative net.
# ---------------------------------------------------------------------------
def _enforce_expression_compat(scenes: List[SceneSpec], controls: BatchControls) -> List[SceneSpec]:
    """
    Every scene's expression must suit its FINAL pose energy / exposure / venue
    (_expression_allowed). The deterministic planner assigns expressions up front, but the
    ceiling/exposure SWAPS reorder scenes and the WS-P pose moves change pose-class
    AFTERWARD — so a bright grin can end on a now-HIGH scene, or a sultry look on a
    now-jogging one. This restores the invariant on the settled state (Venice/deterministic
    alike).

    Runs AFTER _enforce_pose_compat (poses final) and BEFORE _enforce_expression_adjacency
    (which re-clears any adjacency a move here introduces). Swap-first, mirroring the other
    guards, so the expression MULTISET — hence the ~1/3 candid share and the per-expression
    usage cap — is preserved wherever possible:
      1) SWAP the expression with a partner whose expression is allowed HERE and whose slot
         can take OURS (multiset-preserving);
      2) else RE-PICK from the full pool (allowed here, least-used first, seeded offset RNG).
    An UNTAGGED expression is never gated; a scene with no expression is skipped. A NEUTRAL
    expression ('confident look'/'amused half-smile'/'quietly lost in thought') is allowed
    under every rule, so a compatible option always exists and the pass never strands a scene.
    """
    n = len(scenes)
    if n == 0:
        return scenes
    cap = max(2, math.ceil(n / 8))

    def ok(expr, idx) -> bool:
        s = scenes[idx]
        return _expression_allowed(expr, s.pose, s.nudityLevel, s.location, s.outfit)

    counts: Dict[str, int] = {}
    for s in scenes:
        if s.expression:
            counts[s.expression] = counts.get(s.expression, 0) + 1

    for i in range(n):
        e = scenes[i].expression
        if not e or ok(e, i):
            continue
        # (1) multiset-preserving swap: a partner whose expression suits HERE and whose slot
        #     can take OURS (the FIRST such, deterministic).
        swapped = False
        for j in range(n):
            if j == i or not scenes[j].expression:
                continue
            ej = scenes[j].expression
            if ej == e:
                continue
            if ok(ej, i) and ok(e, j):
                scenes[i].expression, scenes[j].expression = ej, e
                swapped = True
                break
        if swapped:
            continue
        # (2) re-pick from the whole pool (allowed here), least-used first, seeded.
        cands = [x for x in _BATCH_EXPRESSION_POOL if x != e and ok(x, i)]
        if not cands:
            continue
        rng = random.Random((controls.base_seed or 0) + 2700001 * (i + 1))
        rng.shuffle(cands)
        under = [x for x in cands if counts.get(x, 0) < cap]
        new_e = min(under or cands, key=lambda x: counts.get(x, 0))
        counts[e] = counts.get(e, 0) - 1
        counts[new_e] = counts.get(new_e, 0) + 1
        scenes[i].expression = new_e
    return scenes


# ---------------------------------------------------------------------------
# Time-of-day <-> location compat repair (WS1a) — the authoritative net.
# ---------------------------------------------------------------------------
def _enforce_time_location_compat(scenes: List[SceneSpec], controls: BatchControls) -> None:
    """
    Every scene's time_of_day must read as real at its FINAL location (_time_ok_at /
    LOCATION_TIME_COMPAT). The ramp and the repair passes pick time and location
    independently and can relocate a scene AFTER its time was set (a night venue landing at
    midday, a beach at night), so this is the authoritative net on the settled state.

    It NEVER relocates — the location was chosen for scene coherence and the pose/outfit/
    nudity all hang off it — it moves the TIME to the nearest allowed value by chronological
    distance (ties -> earlier). That choice is fully DETERMINISTIC (no RNG needed, so no
    seeded stream is consumed and reproducibility of every other field is byte-identical).
    Runs BEFORE _reconcile_captions so the facts are settled before any caption rebuild.
    No-op for a scene whose time already fits (byte-identical).
    """
    for s in scenes:
        if not _time_ok_at(s.time_of_day, s.location):
            s.time_of_day = _nearest_allowed_time(s.time_of_day, s.location)


# ---------------------------------------------------------------------------
# Lighting <-> location compat repair (WS-LIGHT) — the authoritative net.
# ---------------------------------------------------------------------------
def _enforce_lighting_location_compat(scenes: List[SceneSpec], controls: BatchControls) -> None:
    """
    Every scene's lighting must be a value LIGHTING_LOCATION_COMPAT allows at its FINAL
    location (_lighting_ok_at). Mirrors _enforce_time_location_compat exactly: the
    usage-cap/ceiling/exposure/pose repairs above can all move the LOCATION after
    lighting was first picked or beat-pool-repaired, so this is the authoritative net on
    the settled state.

    Deterministic (no RNG, so no seeded stream is consumed and reproducibility of every
    other field is byte-identical): snaps to the FIRST LightingType (declaration order)
    the FINAL location allows, additionally excluding dramatic/theatrical values
    (_is_dramatic_lighting) when the batch is natural/candid_phone-styled — reusing
    _allowed_lighting_pool's own exclusion logic so a natural batch can never end this
    pass on a moody/neon/backlit light, even at a location (nightclub/bar/luxury_lounge)
    whose compat set otherwise skews theatrical (natural_soft is a member of EVERY
    location's set — see LIGHTING_LOCATION_COMPAT — so this always has a safe value to
    land on: the moody_dim leak's exact hole, closed here too, not just at pick time).

    Runs immediately after _enforce_time_location_compat and BEFORE _reconcile_captions
    (order between the two compat passes doesn't matter — captions never name a lighting
    value — only that both settle before the caption rebuild reads the final scene state).
    No-op for a scene whose lighting already fits (byte-identical).
    """
    natural = _val(controls.photo_style) in _NATURAL_PHOTO_STYLES
    for s in scenes:
        allowed = _lights_allowed_at(s.location)
        candidates = allowed
        if natural:
            non_dramatic = frozenset(li for li in allowed if not _is_dramatic_lighting(li))
            candidates = non_dramatic or allowed
        if s.lighting not in candidates:
            s.lighting = _first_allowed_lighting(s.location, within=candidates)


# ---------------------------------------------------------------------------
# Caption coherence (PLANNER COHERENCE): repair captions the repairs falsified.
# ---------------------------------------------------------------------------
# Lowercase caption tokens that IMPLY a given LocationType. A beat_description is written
# at PLAN time from the arc beat, but the downstream repair passes (nudity ceiling,
# exposure caps, pose/location guards, usage caps, favored-location weighting) can MOVE an
# item's location — leaving a caption like "a relaxed moment at a cafe" on an item whose
# FINAL location is photo_studio, or "posing under studio lights" at home_living_room.
# _reconcile_captions (the final repair pass) rewrites ONLY those lying captions.
#
# Matching is word-boundary-safe (\b...\b on the lowercased caption) so a token never
# fires on a substring of an innocent word ("bar" vs "barefoot", "car" vs "care", "lab"
# vs "label", "park" vs "parking", "sand" vs "sandal"). Genuinely-shared concepts
# intentionally SHARE a token so a legit caption is never rewritten and only cross-family
# moves are caught: the two offices share "office", the two kitchens share "kitchen", the
# two studios share "studio" (an intra-pair swap is visually harmless, and the rule in
# _reconcile_captions suppresses a rewrite whenever the caption already names the FINAL
# location). Derived from LocationType (models/enums.py); EVERY value has an entry
# (coverage-tested).
_LOCATION_CAPTION_TOKENS: Dict[str, tuple] = {
    # --- home ---
    "home_bedroom": ("bedroom",),
    "home_living_room": ("living room", "sofa", "couch"),
    "home_kitchen": ("kitchen",),
    "home_bathroom": ("bathroom", "bathtub", "shower"),
    "home_balcony": ("balcony",),
    "home_office": ("home office", "office"),
    # --- workplace (profession-linked) ---
    "office": ("office", "corporate office", "cubicle"),
    "hospital_ward": ("hospital ward", "hospital", "ward"),
    "classroom": ("classroom",),
    "photo_studio": ("photo studio", "photoshoot", "photo shoot", "studio"),
    "gym": ("gym", "workout"),
    "yoga_studio": ("yoga studio", "yoga", "studio"),
    "restaurant_kitchen": ("restaurant kitchen", "kitchen"),
    "library": ("library", "bookshelves"),
    "salon": ("salon", "hair salon"),
    "stage": ("stage", "spotlight"),
    "lab": ("laboratory", "lab"),
    # --- outdoors ---
    "beach": ("beach", "seaside", "shore", "sand"),
    "park": ("park", "lawn"),
    "city_street": ("street", "sidewalk", "downtown"),
    "forest_trail": ("forest", "trail", "woods"),
    "rooftop": ("rooftop",),
    "poolside": ("poolside", "pool"),
    "garden": ("garden",),
    # --- social venues ---
    "cafe": ("cafe", "coffee shop", "coffee"),
    "restaurant": ("restaurant",),
    "bar": ("cocktail bar", "bar"),
    "nightclub": ("nightclub", "club", "dance floor"),
    "hotel_room": ("hotel",),
    "luxury_lounge": ("luxury lounge", "lounge"),
    "car_interior": ("car interior", "parked car", "car"),
}


def _caption_names_location(caption_low: str, tokens: tuple) -> bool:
    """True iff the (already-lowercased) caption contains any token as a whole word."""
    for tok in tokens:
        if re.search(r"\b" + re.escape(tok) + r"\b", caption_low):
            return True
    return False


def _caption_foreign_location(caption_low: str, final_val: Optional[str]) -> bool:
    """True iff the caption names a location whose enum value is NOT ``final_val``."""
    for loc_val, tokens in _LOCATION_CAPTION_TOKENS.items():
        if loc_val == final_val:
            continue
        if _caption_names_location(caption_low, tokens):
            return True
    return False


def _rewrite_caption(scene: SceneSpec) -> str:
    """
    Deterministically rebuild a beat_description from the scene's FINAL fields — a pure
    function of the scene (no RNG), so reproducibility is preserved. Lead = the
    identity-free ``activity`` if present, else a short pose-derived phrase (the first
    clause of the pose's POSE_DESCRIPTIONS text via _POSE_PHRASE_MAP), else the "a moment"
    fallback — skipping any candidate that itself names a FOREIGN location so the rewrite
    can't re-lie. The final location is rendered through the shared
    scene_vocab.location_phrase helper (never a new table). Identity-scrubbed
    (_scrub_identity, as elsewhere in validate_and_repair) and clamped to the
    SceneSpec.beat_description limit (280).
    """
    final_val = _val(scene.location)
    candidates: List[str] = []
    if scene.activity:
        candidates.append(scene.activity.strip())
    if scene.pose is not None:
        desc = _POSE_PHRASE_MAP.get(_val(scene.pose))
        if desc:
            candidates.append(desc.split(",")[0].strip())
    lead = "a moment"
    for cand in candidates:
        if cand and not _caption_foreign_location(cand.lower(), final_val):
            lead = cand
            break
    loc = sv.location_phrase(scene.location)
    caption = f"{lead} at {loc}" if loc else lead
    caption = _scrub_identity(caption)
    if caption:
        caption = caption[0].upper() + caption[1:]
    return caption[:280]


def _reconcile_captions(scenes: List[SceneSpec]) -> None:
    """
    FINAL caption-coherence pass (mutates in place): rewrite any beat_description that
    names a location the item no longer occupies. Runs LAST in validate_and_repair —
    after every location/outfit/pose repair has settled, the only point where the fields
    are authoritative. A caption that already names its FINAL location (or names no
    location at all) is left BYTE-IDENTICAL; only a caption that names some OTHER location
    and NOT the final one is rewritten (from _rewrite_caption).
    """
    for s in scenes:
        low = (s.beat_description or "").lower()
        final_val = _val(s.location)
        # Already names the final place -> trust it (even if it also names another).
        if _caption_names_location(low, _LOCATION_CAPTION_TOKENS.get(final_val, ())):
            continue
        # Names a DIFFERENT place -> the caption lies; rebuild from the final fields.
        if _caption_foreign_location(low, final_val):
            s.beat_description = _rewrite_caption(s)


# ---------------------------------------------------------------------------
# Scene staging (WS-STAGE Part A): anchor each scene to a concrete surface.
# ---------------------------------------------------------------------------
# Offset for the staging RNG — distinct from every other dedicated-RNG offset in this
# module (expressions 1900009, moods 2300003, fill 700001, exposure 1500007) so the
# staging draw never perturbs those existing seeded picks. Staging is a NEW field assigned
# AFTER all existing draws with its OWN rng, so same-seed reproducibility of every prior
# field is byte-identical; only this field is newly populated.
_STAGING_SEED_OFFSET = 5100011


def _assign_staging(scenes: List[SceneSpec], controls: BatchControls) -> None:
    """
    Assign a scenery-anchored staging fragment to every scene (mutates in place), derived
    DETERMINISTICALLY from (base_seed, scene index, FINAL location, FINAL pose) so a re-run
    with the same seed yields identical stagings. Runs LAST in validate_and_repair, after
    every location/pose repair has settled, so the phrase always matches the scene's FINAL
    location + pose class.

    Coherence guard: the phrase is drawn ONLY from the scene's own pose-class pool at its
    location (scene_vocab.staging_options buckets the pose FIRST), so a sitting scene never
    gets a lying/standing anchor. A (location, class) combo with no pool leaves ``staging``
    None — a clean skip. In particular a lying pose that lands in a location with no lying
    staging is left unanchored (NOT relocated — location repair already ran). A scene with
    no pose (pose step skipped) buckets to OTHER, which is unstaged everywhere -> None.
    """
    for i, s in enumerate(scenes):
        options = sv.staging_options(s.location, s.pose)
        if not options:
            s.staging = None
            continue
        rng = random.Random((controls.base_seed or 0) + _STAGING_SEED_OFFSET * (i + 1))
        s.staging = rng.choice(list(options))


def validate_and_repair(
    scenes: List[SceneSpec],
    character: Character,
    count: int,
    controls: BatchControls,
    *,
    enforce_beat_pool: bool = True,
    enforce_nudity_ramp: bool = True,
    enforce_variety: bool = True,
    enforce_time_ramp: bool = True,
) -> List[SceneSpec]:
    """
    Coerce/repair enums, clamp nudity, enforce allow/block, enforce beat-pool
    coherence (pose/outfit/location stay within the hand-authored combination
    for that beat position), curate time_of_day onto the day-flow ramp, and
    guarantee exactly `count`.

    ``enforce_beat_pool`` gates only the coherence repair. Set False for
    admin-supplied manual scenes: those are an intentional exact override
    (the admin picked this outfit for this location on purpose), not a
    planner's guess that needs sanity-checking against the hand-authored
    pools. The other repairs (nudity ceiling, allow/block, identity scrub,
    count guarantee) still apply — manual mode overrides planner choices, not
    safety controls.

    ``enforce_nudity_ramp`` ASSIGNS each photo's nudity EXACTLY to the per-photo ramp
    value (``ramp[i]``) — the ramp is authoritative for every provider, so no planner
    can under- or over-shoot the arc (this kills nudity drip). It also auto-fills an
    outfit for a medium/high scene that has none, since nudity renders only through the
    outfit step. Only the manual path (``enforce_nudity_ramp=False``) keeps a plain
    down-clamp to ``max_nudity`` on the admin's exact levels. ``enforce_variety`` runs the
    set-level dedup pass plus the per-batch pose/location usage caps
    (_enforce_usage_caps: no pose more than max(2, ceil(count/8)) times, no
    location more than max(2, ceil(count/6))). ``enforce_time_ramp`` overrides each photo's time_of_day
    to the per-photo chronological ramp (_time_ramp) so the day flows forward and
    resets per day — the safety net for LLM output that ignored the TIME PLAN,
    exactly parallel to how the nudity ramp backs the NUDITY PLAN. All three default
    True (venice/deterministic/fallback); the manual path passes them False so an
    admin's exact scene list is left intact.
    """
    max_idx = _nudity_index(controls.max_nudity)
    slots = _beat_slots(character, count, controls) if enforce_beat_pool else []
    ramp = _nudity_ramp(count, controls) if enforce_nudity_ramp else []
    time_ramp = _time_ramp(count, controls.period_days) if enforce_time_ramp else []
    repaired: List[SceneSpec] = []
    for i, scene in enumerate(scenes[:count]):
        s = scene.model_copy(deep=True)

        # Nudity: ASSIGN, don't clamp. Variety batches are independent scenarios (no story
        # reason to let a provider under-shoot), so the ramp is AUTHORITATIVE for every
        # provider: each photo's level is set EXACTLY to ramp[i] — mirroring how the
        # deterministic planner assigns ramp[gidx] up front. This kills "nudity drip" (the
        # old down-only clamp let an LLM "low" mid-batch stay low, weakening the arc).
        # sfw_only is already covered because _nudity_ramp returns all-LOW then. The manual
        # path (enforce_nudity_ramp=False) is the only caller that keeps a plain ceiling
        # clamp — an admin's exact per-scene levels are honored, only capped at max_nudity.
        if controls.sfw_only:
            s.nudityLevel = NudityLevel.LOW
        elif enforce_nudity_ramp and i < len(ramp):
            s.nudityLevel = ramp[i]
        else:
            s.nudityLevel = _NUDITY_LADDER[min(_nudity_index(s.nudityLevel), max_idx)]

        # Outfit allow/block.
        if s.outfit is not None:
            if controls.sfw_only and s.outfit == OutfitType.NAKED:
                s.outfit = None
            elif s.outfit in (controls.blocked_outfits or []):
                s.outfit = None
            elif controls.allowed_outfits and s.outfit not in controls.allowed_outfits:
                s.outfit = None

        # Pose block.
        if s.pose is not None and s.pose in (controls.blocked_poses or []):
            s.pose = None

        # Location allow/block (required — repair to an allowed one).
        if s.location in (controls.blocked_locations or []) or (
            controls.allowed_locations and s.location not in controls.allowed_locations
        ):
            if controls.allowed_locations:
                s.location = controls.allowed_locations[0]
            else:
                s.location = next(
                    (loc for loc in LocationType if loc not in (controls.blocked_locations or [])),
                    LocationType.HOME_LIVING_ROOM,
                )

        # Coherence: pose/outfit/location/time/lighting must stay within THIS
        # beat position's own hand-authored pool — the same pool the
        # deterministic planner draws from — so no provider can pair e.g. a
        # bikini with an office beat, or "eating dinner" with a bodycon dress
        # at a location that pool never includes. Out-of-pool picks are
        # re-picked deterministically (seeded, reproducible) rather than
        # dropped, since a concrete in-pool scene beats a missing one.
        if i < len(slots):
            s = _enforce_beat_pool(s, slots[i], controls, seed=(controls.base_seed or 0) + i)

        # Time-of-day curation — override each photo's time onto the per-photo
        # chronological ramp so the day flows forward and resets per day (the safety
        # net for LLM output that ignored the TIME PLAN, parallel to the nudity ramp).
        # When the beat pool is enforced, snap to the nearest ramp target THIS beat's
        # own time_pool permits — additionally narrowed (WS1a) to the times that read as
        # real at the scene's current location, so coherence beats a perfect curve (a
        # daytime-only beat is never forced to night, and a night venue never to midday);
        # with no pool (director path) set it outright. The FINAL location can still change
        # in the later ceiling/exposure passes, so _enforce_time_location_compat gets the
        # last word below.
        if enforce_time_ramp and i < len(time_ramp):
            if i < len(slots):
                s.time_of_day = _nearest_time_in_pool(
                    time_ramp[i], _time_compat_pool(s.location, slots[i].tmpl.time_pool)
                )
            else:
                s.time_of_day = time_ramp[i]

        # Outfit-fill: the outfit STEP only runs when the request carries an outfit enum
        # (pipeline_worker._determine_active_steps: outfit active iff outfit is not None),
        # and outfit_detail is consumed ONLY inside that step. So a beat that has a caption
        # (outfit_detail) but a null enum silently renders the avatar's OWN clothes while
        # the gallery shows the caption — the #1 reported bug ("caption says velvet dress,
        # render keeps the original outfit"). Fill a null enum whenever the beat carries any
        # outfit SIGNAL: a non-LOW nudity target (nudity renders only through this step) OR
        # an authored outfit_detail. PREFER deriving the enum from the caption so the two
        # agree; else pick deterministically from the allowed pool. Never NAKED; empty pool
        # or no signal -> leave None. Gated with the ramp so manual scenes keep None.
        if enforce_nudity_ramp and s.outfit is None and (
            s.nudityLevel != NudityLevel.LOW or s.outfit_detail
        ):
            derived = _outfit_from_detail(s.outfit_detail) if s.outfit_detail else None
            if derived is not None and _outfit_allowed(derived, controls):
                s.outfit = derived
            else:
                # Prefer the wardrobe subset for the auto-fill (never empties).
                fill_pool = _prefer_wardrobe(_outfit_fill_pool(controls), controls, min_keep=2)
                if fill_pool:
                    fill_rng = random.Random((controls.base_seed or 0) + 700001 * (i + 1))
                    s.outfit = fill_rng.choice(fill_pool)
                    # A caption with NO confident enum mapping (derived is None — e.g.
                    # "cotton robe", "towel wrapped snugly"): the just-picked random enum
                    # exists ONLY to gate the outfit step and feed variety bookkeeping — it
                    # does NOT describe what she wears. Mark the scene detail-dominant so the
                    # outfit step renders the CAPTION as the lead garment text. Under the
                    # additive detail-dominant contract (see build_prompt) the graded tier
                    # exposure prose for the nudity level is appended ALONGSIDE the caption,
                    # so the gallery card matches the image AND the nudity always renders. A
                    # caption that DID map but to a blocked/disallowed type stays enum-driven:
                    # honoring it would re-introduce the blocked garment.
                    if s.outfit_detail and derived is None:
                        s.outfit_detail_dominant = True

        # Enum<->detail reconcile: when the LLM set an outfit but the caption describes a
        # different garment, the caption wins (override the enum) or the contradicting
        # caption is dropped — so the outfit step never gets self-contradicting signals.
        # Runs right after the fill (a just-filled enum already matches its detail -> no-op).
        _reconcile_outfit(s, controls)

        # Caption-first outfits (C2), ADDITIVE contract: whenever a scene carries an
        # outfit_detail (and a real, non-NAKED outfit gates the step), mark it detail-
        # dominant. Detail-dominant is the additive signal to the outfit step: render the
        # director's caption AS the lead garment text AND append the graded tier exposure
        # prose (OUTFIT_DESCRIPTIONS[outfit][nudity_level]) for the nudity level, rather than
        # dropping the graded explicit language for a single generic exposure clause (the
        # rendering half lives in build_prompt's detail_dominant handling). So the caption is
        # always the rendered garment and the explicit tier prose always renders alongside it
        # (the nudity never silently weakens). The fill/reconcile above remain in place (now
        # subsumed but harmless). EXCEPTION: a caption that confidently names a
        # BLOCKED/disallowed garment stays enum-driven — rendering that caption would
        # re-introduce the blocked type (the same allow/block-wins rule the fill above applies).
        if s.outfit is not None and s.outfit != OutfitType.NAKED and s.outfit_detail:
            derived = _outfit_from_detail(s.outfit_detail)
            if derived is None or _outfit_allowed(derived, controls):
                s.outfit_detail_dominant = True

        # Scrub identity tokens from free-text (defense-in-depth).
        if s.background_text:
            s.background_text = _scrub_identity(s.background_text)
        s.beat_description = _scrub_identity(s.beat_description)
        # setting/activity/outfit_detail/expression DO reach the render, so scrubbing them
        # is load-bearing (expression additionally strips facial-feature tokens).
        if s.setting:
            s.setting = _scrub_scene_text(s.setting, 400)
        if s.activity:
            # strip_companions in addition to the identity scrub so the STORED activity is
            # already solo (no "with a partner"/crowd tail); the pose-step scrub in
            # build_pose_prompt stays as a backstop, and the scene mapper scrubs again at
            # map time for the pose-absent (activity -> background) path.
            s.activity = sv.strip_companions(_scrub_scene_text(s.activity, 200))
        if s.pose_detail:
            # Same treatment as activity: pose_detail steers the pose step's full-frame
            # re-diffusion, so the STORED text must already be solo + identity-free; the
            # strip_companions in build_pose_prompt stays as a backstop.
            s.pose_detail = sv.strip_companions(_scrub_scene_text(s.pose_detail, 200))
        if s.outfit_detail:
            s.outfit_detail = _scrub_scene_text(s.outfit_detail, 160)
        if s.expression:
            s.expression = _scrub_expression(s.expression)
        if s.narrative:
            s.narrative = _scrub_narrative(s.narrative)

        # Fill per-item seed if missing and a base seed is available.
        if s.seed is None:
            s.seed = _derive_seed(controls, s.global_index)

        repaired.append(s)

    # Count guarantee: pad from deterministic, truncate excess.
    if len(repaired) < count:
        deficit = count - len(repaired)
        pad = DeterministicScenePlanner().plan_scenes_sync(character, count, controls)
        repaired.extend(pad[len(repaired): len(repaired) + deficit])
    repaired = repaired[:count]

    # Set-level variety pass (after padding so the final set is what gets deduped).
    if enforce_variety:
        repaired = _enforce_variety(repaired, slots, controls)
        # Per-batch pose/location usage caps (C1b), after the pair-dedup and the nudity
        # clamp above so the cap re-picks never fight those repairs (they only move
        # pose/location, and clear a now-stale pose_detail).
        repaired = _enforce_usage_caps(repaired, slots, controls)

    # Location<->nudity coherence, THEN outfit<->nudity coherence — a two-stage atomic
    # guarantee. Both run only when the ramp is authoritative (enforce_nudity_ramp); the
    # manual path keeps the admin's exact levels/outfits/locations untouched.
    #   1. LOCATION pass first: keep the positional ramp from landing explicit exposure on a
    #      public place; authoritative for each scene's FINAL location. Its swaps are
    #      permutations, so they can't re-break the variety/cap guarantees just enforced.
    #   2. OUTFIT (exposure-cap) pass second: with locations now fixed, keep each label
    #      within what its GARMENT can honestly render. Its re-picks are constrained by the
    #      already-final location ceiling, so the invariants compose:
    #      final label <= cap(outfit) AND <= ceiling(location).
    if enforce_nudity_ramp and ramp:
        repaired = _enforce_location_nudity_ceiling(repaired, ramp, controls)
        repaired = _enforce_outfit_exposure_cap(repaired, ramp, controls)

    # Conscious-model variety net + WS-P pose coherence + WS1 real-world-sense guards (ride
    # the variety gate, so the manual path is untouched). FINAL PASS ORDER (each pass sees the
    # previous one's output):
    #   1. _enforce_variety                 — pair-dedup + consecutive (pose,location)
    #   2. _enforce_usage_caps              — per-batch pose/location usage caps
    #   3. _enforce_location_nudity_ceiling — scenes swap so the ramp never over-exposes a place
    #   4. _enforce_outfit_exposure_cap     — outfits swap/re-pick to the label they can render
    #   5. _strip_ineligible_moods          — drop mood tags left on now-LOW/public scenes
    #   6. _enforce_pose_compat  (WS-P+1c)  — pose<->outfit + pose<->location (incl. provocative-
    #                                         pose-needs-a-private-venue via _pose_ok_at), swap-
    #                                         first/re-pick; runs AFTER 3+4 (locations+outfits
    #                                         FINAL) so it sees the final facts
    #   7. _enforce_pose_adjacency          — no identical pose in consecutive items
    #   8. _enforce_expression_compat (1b)  — expression suits FINAL pose energy/exposure/venue;
    #                                         swap-first so the candid share + usage cap survive,
    #                                         runs BEFORE 9 so 9 re-clears any adjacency it makes
    #   9. _enforce_expression_adjacency    — no identical expression in consecutive items
    #  10. _enforce_time_location_compat(1a)— snap each time onto the FINAL location's allowed set
    #                                         (never relocates; deterministic), BEFORE captions
    #  11. _enforce_lighting_location_compat(WS-LIGHT) — snap each lighting onto the FINAL
    #                                         location's allowed set (+ natural-style dramatic
    #                                         exclusion), deterministic, BEFORE captions
    #  12. _reconcile_captions              — rewrite captions the moves above falsified
    # 6 touches ONLY pose/pose_detail (multiset-preserving swaps + cap-aware re-picks); 8 touches
    # ONLY expression (swap-first, so the candid share + usage cap hold and 9 still runs last on
    # the settled multiset); 10 touches ONLY time_of_day and 11 touches ONLY lighting (both
    # deterministic nearest/first-allowed, no RNG). So the nudity ramp, location ceilings,
    # exposure caps and mood strip are all left intact. 12 runs LAST, once location/outfit/pose/
    # time/lighting are final, and only rewrites a beat_description that names a location the
    # item no longer occupies (a coherent caption stays byte-identical).
    if enforce_variety:
        _strip_ineligible_moods(repaired)
        repaired = _enforce_pose_compat(repaired, slots, controls)
        repaired = _enforce_pose_adjacency(repaired, controls)
        # WS1b: fix any expression the pose/ceiling/exposure moves left incompatible with the
        # FINAL pose energy / exposure / venue, THEN restore expression adjacency on the result.
        repaired = _enforce_expression_compat(repaired, controls)
        repaired = _enforce_expression_adjacency(repaired, controls)
        # WS1a: snap any time_of_day the location moves left incoherent onto the nearest value
        # the FINAL location allows (never relocates), before the caption rebuild.
        _enforce_time_location_compat(repaired, controls)
        # WS-LIGHT: snap any lighting the location moves left incoherent (or that a
        # natural-style batch should never have carried) onto the FINAL location's
        # allowed set, before the caption rebuild.
        _enforce_lighting_location_compat(repaired, controls)
        _reconcile_captions(repaired)

    # SCENE STAGING (WS-STAGE, final enrichment): anchor every scene to a concrete
    # surface/furniture in its FINAL location, matched to its FINAL pose class, so the
    # full-frame pose re-diffusion never improvises an absurd seat (the "sitting
    # cross-legged barefoot on the bar counter" bug). Runs UNCONDITIONALLY (both the
    # auto planners and the manual path) since poses/locations are authoritative by this
    # point in every path; derived deterministically from (seed, index, location, pose)
    # with its own RNG so no prior seeded pick shifts.
    _assign_staging(repaired, controls)

    # Re-index global order so downstream ordering is contiguous.
    for i, s in enumerate(repaired):
        s.global_index = i
    return repaired


# Generic appearance patterns a planner might emit OUTSIDE the vocab keys above
# ("silky auburn hair", "piercing green eyes", "sun-tanned skin", "a stunning
# young redhead"). Free text must describe the SCENE only, never the person —
# the person is pixel-protected by the edit masks; this scrub is defense-in-depth.
_APPEARANCE_PATTERNS = [
    re.compile(r"\b(?:\w+[- ]){0,2}\w*\s*hair(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\b(?:\w+[- ]){0,2}\w*\s*eyes?\b", re.IGNORECASE),
    re.compile(r"\b(?:\w+[- ]){0,2}\w*\s*skin(?:ned)?\b", re.IGNORECASE),
    re.compile(r"\b(?:\w+[- ]){0,2}\w*\s*(?:complexion|freckles?|curves|physique|figure)\b", re.IGNORECASE),
    # person nouns with optional descriptor stack: "a stunning young redhead/woman/girl..."
    re.compile(
        r"\b(?:an?\s+)?(?:\w+\s+){0,3}"
        r"(?:woman|girl|lady|man|guy|redhead|blonde|brunette|beauty|babe)\b",
        re.IGNORECASE,
    ),
    # age descriptors
    re.compile(r"\b(?:young|youthful|teen(?:age[dr]?)?|mature|middle[- ]aged|elderly)\b", re.IGNORECASE),
]


def _scrub_identity(text: str) -> str:
    if not text:
        return text
    out = text
    low = out.lower()
    for tok in _IDENTITY_TOKENS:
        if tok and tok in low:
            out = re.sub(re.escape(tok), "", out, flags=re.IGNORECASE)
            low = out.lower()
    # Generic appearance phrases (anything the vocab keys didn't catch).
    for pat in _APPEARANCE_PATTERNS:
        out = pat.sub("", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;])", r"\1", out)
    out = re.sub(r"([,.;])\1+", r"\1", out)
    return out.strip(" ,.;")


def _scrub_narrative(text: str) -> Optional[str]:
    """
    Identity-scrub narrative prose while preserving terminal sentence punctuation
    (so a clean sentence keeps its final '.'/'!'/'?' instead of being trimmed by the
    generic scrub). Returns None if nothing meaningful survives. Clamped to the
    SceneSpec.narrative limit.
    """
    if not text:
        return None
    scrubbed = _scrub_identity(text)
    if not scrubbed:
        return None
    end = text.rstrip()[-1:]
    if end in ".!?" and scrubbed[-1:] not in ".!?":
        scrubbed = scrubbed + end
    return scrubbed[:700]


def _scrub_scene_text(text, limit: int) -> Optional[str]:
    """
    Identity-scrub a render-safe scene field (setting/activity/outfit_detail) and cap its
    length. Returns None if nothing meaningful survives the scrub. These fields DO reach the
    render, so scrubbing here (and again in validate_and_repair) is load-bearing, not
    just cosmetic like narrative.
    """
    if not text:
        return None
    scrubbed = _scrub_identity(str(text))
    return scrubbed[:limit] if scrubbed else None


# Facial-FEATURE tokens the `expression` field must never carry — it is an expression/mood
# only (eyes/skin/hair are already handled by _scrub_identity; these are the extras).
_EXPRESSION_FEATURE_RE = re.compile(
    r"\b(?:lips?|teeth|tooth|jaws?|cheekbones?|noses?|chins?|eyes?)\b", re.IGNORECASE
)


def _scrub_expression(text) -> Optional[str]:
    """
    Scrub the expression/mood field: identity-scrub + cap at 80 (like setting/activity),
    then additionally strip facial-FEATURE tokens (lips/teeth/jaw/cheekbone/nose/chin/eyes)
    so the field can only carry an EXPRESSION/mood, never a description of the face itself.
    Returns None if nothing meaningful survives.
    """
    scrubbed = _scrub_scene_text(text, 80)
    if not scrubbed:
        return None
    scrubbed = _EXPRESSION_FEATURE_RE.sub("", scrubbed)
    scrubbed = re.sub(r"\s{2,}", " ", scrubbed)
    scrubbed = re.sub(r"\s+([,.;])", r"\1", scrubbed).strip(" ,.;")
    return scrubbed or None


# ---------------------------------------------------------------------------
# Single-item scene edit (Phase 3: PATCH one batch item's scene_spec).
#
# Reuses the SAME enum coercion (_coerce_enum), controls filters, and free-text
# scrubs the planner applies at plan time, so an admin edit of one photo can never
# bypass the batch's allow/block lists, sfw_only, or the max_nudity ceiling, and
# free-text detail fields can't leak identity/company into the render.
# ---------------------------------------------------------------------------
class SceneEditError(ValueError):
    """A single-item scene edit carried an invalid enum value or violated the
    batch's stored controls. The endpoint maps this to HTTP 422."""


# Edit-request field -> (SceneSpec attribute, enum class). Enum fields are coerced
# via _coerce_enum (difflib near-miss repair — identical to the planner's parse).
_EDIT_ENUM_FIELDS = {
    "outfit": ("outfit", OutfitType),
    "location": ("location", LocationType),
    "pose": ("pose", PoseType),
    "nudity_level": ("nudityLevel", NudityLevel),
    "time_of_day": ("time_of_day", TimeOfDayType),
    "lighting": ("lighting", LightingType),
}

# Nullable scene steps: an explicit null clears the step (skips it). location /
# nudity_level / time_of_day / lighting are structurally required, so null is rejected.
_EDIT_NULLABLE = {"outfit", "pose"}


def _validate_edit_enum(key: str, value, controls: BatchControls) -> None:
    """Reject an edited enum the batch's stored controls forbid (-> SceneEditError)."""
    if key == "outfit":
        if controls.sfw_only and value == OutfitType.NAKED:
            raise SceneEditError("outfit 'naked' is not allowed on an sfw_only batch")
        if value in (controls.blocked_outfits or []):
            raise SceneEditError(f"outfit '{value.value}' is blocked for this batch")
        if controls.allowed_outfits and value not in controls.allowed_outfits:
            raise SceneEditError(f"outfit '{value.value}' is not in this batch's allowlist")
    elif key == "pose":
        if value in (controls.blocked_poses or []):
            raise SceneEditError(f"pose '{value.value}' is blocked for this batch")
        if not has_pose_ref(value):
            # Same latch as the planner pools and the interactive pose endpoint:
            # a refless pose would only fail later at the worker (missing
            # pose_ref PNG) -- reject the edit up front instead.
            raise SceneEditError(
                f"pose '{value.value}' is not available yet (its reference "
                "image has not been generated)"
            )
    elif key == "location":
        if value in (controls.blocked_locations or []):
            raise SceneEditError(f"location '{value.value}' is blocked for this batch")
        if controls.allowed_locations and value not in controls.allowed_locations:
            raise SceneEditError(f"location '{value.value}' is not in this batch's allowlist")
    elif key == "nudity_level":
        if controls.sfw_only and value != NudityLevel.LOW:
            raise SceneEditError("nudity must be 'low' on an sfw_only batch")
        if _nudity_index(value) > _nudity_index(controls.max_nudity):
            raise SceneEditError(
                f"nudity '{value.value}' exceeds this batch's max_nudity "
                f"'{_val(controls.max_nudity)}'"
            )


def _scrub_edit_field(field: str, value):
    """Apply the planner's free-text scrub for one render-safe detail field."""
    if value is None:
        return None
    if field == "setting":
        return _scrub_scene_text(value, 400)
    if field == "activity":
        return sv.strip_companions(_scrub_scene_text(value, 200))
    if field == "pose_detail":
        return sv.strip_companions(_scrub_scene_text(value, 200))
    if field == "outfit_detail":
        return _scrub_scene_text(value, 160)
    if field == "expression":
        return _scrub_expression(value)
    return value


# Scene FACT edit keys — changing any of these invalidates the fields the planner DERIVED
# from the old facts (the Venice scene_direction, and the staging drawn from the old
# (location, pose-class)), so they are recomputed. Free-text / mood-only edits do not.
_EDIT_FACT_KEYS = ("location", "pose", "outfit", "nudity_level")


def _restage_after_edit(spec: dict) -> Optional[str]:
    """Deterministically re-derive the staging anchor from a spec's NEW (location, pose) after
    a fact edit. NO RNG (a repeated identical edit is byte-stable): the phrase is picked by a
    crc32 of the item's own seed/index + the new location/pose. Mirrors _assign_staging's
    coherence guard — the phrase is drawn ONLY from the scene's own (location, pose-class) pool
    (scene_vocab.staging_options buckets the pose FIRST), so a sitting scene never gets a lying
    anchor — but keyed off the item itself since a PATCH re-derives ONE item in isolation.
    None when the pose step is skipped (pose None) or the (location, class) combo has no pool."""
    pose = spec.get("pose")
    if pose is None:
        return None
    options = sv.staging_options(spec.get("location"), pose)
    if not options:
        return None
    key = f"{spec.get('seed') or spec.get('global_index') or 0}:{spec.get('location')}:{pose}"
    return options[zlib.crc32(key.encode()) % len(options)]


def apply_item_scene_edit(
    scene_spec: dict, edit: dict, controls: BatchControls
) -> SceneSpec:
    """
    Apply a partial edit (only the keys present in ``edit``) onto a stored
    ``scene_spec`` dict, validating each field exactly as the planner would, and
    return the updated SceneSpec.

    Enum fields (outfit, location, pose, nudity_level, time_of_day, lighting) are
    coerced with _coerce_enum then checked against ``controls`` — an outfit/pose/
    location the allow/block lists forbid, or a nudity above ``max_nudity`` (or
    non-LOW under sfw_only), raises SceneEditError. An explicit null clears the
    nullable steps (outfit/pose). A ``lighting`` edit that lands on a value
    LIGHTING_LOCATION_COMPAT disallows at the item's FINAL location (the just-edited
    location, if this same edit also touched it, else the stored one) is snapped to that
    location's first allowed value instead of rejected — repaired, not rejected, like
    every other coherence guard in this module. Free-text detail fields (setting,
    activity, pose_detail, outfit_detail, expression) get the planner's identity scrub,
    companion strip, and length caps (_scrub_scene_text / strip_companions /
    _scrub_expression). Raises SceneEditError on any violation.
    """
    spec = dict(scene_spec or {})

    for key, (attr, enum_cls) in _EDIT_ENUM_FIELDS.items():
        if key not in edit:
            continue
        raw = edit[key]
        if raw is None:
            if key in _EDIT_NULLABLE:
                spec[attr] = None
                continue
            raise SceneEditError(f"{key} cannot be null")
        value = _coerce_enum(enum_cls, raw)
        if value is None:
            raise SceneEditError(f"invalid {key}: {raw!r}")
        _validate_edit_enum(key, value, controls)
        spec[attr] = value.value

    # Lighting <-> location coherence (LIGHTING_LOCATION_COMPAT): only runs when THIS
    # edit itself sets lighting (a location-only edit is left for the planner's own
    # repair pass on the next full replan, not re-validated on a single-item PATCH).
    # spec["location"] already reflects a same-request location edit (processed above,
    # _EDIT_ENUM_FIELDS iterates in its own fixed key order) or else the item's stored
    # location. Deterministic snap, no RNG.
    if "lighting" in edit and not _lighting_ok_at(spec.get("lighting"), spec.get("location")):
        spec["lighting"] = _first_allowed_lighting(spec.get("location")).value

    for key in ("setting", "activity", "pose_detail", "outfit_detail", "expression"):
        if key in edit:
            spec[key] = _scrub_edit_field(key, edit[key])

    # A scene FACT edit (location/pose/outfit/nudity_level) invalidates the fields the planner
    # derived from the OLD facts: a Venice scene_direction authored against the old place/pose
    # may now describe absent furniture or a foreign crowd, and the staging anchor was drawn
    # from the old (location, pose-class). Clear the direction (the mapper then falls back to
    # the bare staging phrase) and re-derive staging deterministically from the NEW facts. A
    # free-text-only or mood-only edit leaves all three untouched.
    if any(k in edit for k in _EDIT_FACT_KEYS):
        spec["scene_direction"] = None
        spec["direction_source"] = None
        spec["staging"] = _restage_after_edit(spec)

    return SceneSpec(**spec)


# ---------------------------------------------------------------------------
# Provider selection + top-level entry point
# ---------------------------------------------------------------------------
def build_planner(name: str, *, settings) -> StoryPlanner:
    if name == "venice":
        return VeniceScenePlanner(
            api_key=settings.VENICE_API_KEY,
            base_url=settings.VENICE_BASE_URL,
            model=settings.VENICE_MODEL,
            temperature=getattr(settings, "STORY_PLANNER_TEMPERATURE", 0.6),
        )
    if name == "claude":
        return ClaudeScenePlanner(api_key=settings.ANTHROPIC_API_KEY, model=settings.ANTHROPIC_MODEL)
    return DeterministicScenePlanner()


async def plan_scenes(
    character: Character,
    count: int,
    controls: BatchControls,
    *,
    settings,
    provider_override: Optional[str] = None,
    manual_scenes: Optional[List[dict]] = None,
) -> Tuple[List[SceneSpec], str]:
    """
    Plan `count` scenes, honoring the provider preference order and the content-rating
    gate. Returns (validated_scenes, provider_name_used).
    """
    is_nsfw = _val(controls.content_rating) != "sfw"

    # Manual override wins.
    if manual_scenes or provider_override == "manual":
        planner = ManualScenePlanner(manual_scenes or [])
        scenes = await planner.plan_scenes(character, count, controls)
        return (
            validate_and_repair(
                scenes, character, count, controls,
                enforce_beat_pool=False, enforce_nudity_ramp=False, enforce_variety=False,
                enforce_time_ramp=False,
            ),
            "manual",
        )

    # Build the provider order. Variety-only batches default to the DETERMINISTIC planner
    # (coherent, correctly-ramped, seeded-variety plans from the controls alone, zero
    # hallucination). Venice/Claude are NO LONGER auto-selected just because a key is set —
    # they are opt-in ONLY via an explicit STORY_PLANNER_PROVIDER (or provider_override).
    # An explicit provider is still honored as before (e.g. STORY_PLANNER_PROVIDER=venice
    # runs the per-beat menu path as a bounded garnish; the NSFW gate below still applies).
    configured = provider_override or getattr(settings, "STORY_PLANNER_PROVIDER", "") or ""
    if configured:
        order = [configured]
    else:
        order = ["deterministic"]

    for name in order:
        planner = build_planner(name, settings=settings)
        # Hard gate: never route NSFW to a non-NSFW provider.
        if is_nsfw and not planner.supports_nsfw:
            continue
        try:
            scenes = await planner.plan_scenes(character, count, controls)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"planner {name} raised {e}; falling back")
            scenes = []
        if scenes:
            # Variety-only: beat-pool coherence is ALWAYS enforced now (story mode is
            # retired, so the free-picking story-director path is unreachable via controls).
            # Venice, when opted in, runs the per-beat MENU path and gets snapped back into
            # the hand-authored pools; the deterministic planner's picks are already in-pool,
            # so enforcement there is a safe no-op. validate_and_repair additionally
            # hard-assigns nudity from the ramp (enforce_nudity_ramp defaults True), so no
            # provider — Venice included — ever chooses the nudity level.
            return (
                validate_and_repair(scenes, character, count, controls, enforce_beat_pool=True),
                name,
            )

    # Deterministic never returns empty for count>=1, but guard anyway.
    scenes = DeterministicScenePlanner().plan_scenes_sync(character, count, controls)
    return validate_and_repair(scenes, character, count, controls), "deterministic"
