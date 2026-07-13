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
)
from models.batch import BatchControls
from models.scene import SceneSpec
from services import attribute_phrases as ap
from services import scene_vocab as sv
from services import story_templates as st
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
    return [p for p in tmpl.pose_pool if p not in (controls.blocked_poses or [])]


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
    return pool


def _allowed_location_pool(tmpl, controls: BatchControls) -> List[LocationType]:
    pool = []
    for loc in tmpl.location_pool:
        if loc in (controls.blocked_locations or []):
            continue
        if controls.allowed_locations and loc not in controls.allowed_locations:
            continue
        pool.append(loc)
    return pool


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
                time_of_day = _nearest_time_in_pool(
                    time_ramp[gidx] if gidx < len(time_ramp) else tmpl.time_pool[0], tmpl.time_pool
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
                        lighting=rng.choice(tmpl.lighting_pool),
                        mood_kinks=character.persona.kinks,
                        mood_personality=character.persona.personality,
                        seed=_derive_seed(controls, gidx),
                        narrative=narrative,
                        story_title=story_title,
                    )
                )
                gidx += 1
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
        return _weighted_pick(pool, rng, like_kw, dislike_kw, {})

    def _pick_outfit(self, tmpl, rng, like_kw, dislike_kw, controls):
        pool = _allowed_outfit_pool(tmpl, controls)
        if not pool:
            return None  # skip outfit step for this scene
        return _weighted_pick(pool, rng, like_kw, dislike_kw, {})

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
        return _weighted_pick(pool, rng, like_kw, dislike_kw, sv.LOCATION_PHRASES)


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


def _weighted_pick(pool, rng, like_kw: set, dislike_kw: set, phrase_map: dict):
    candidates = list(pool)
    if not candidates:
        return None
    # Soft-exclude dislikes, but never empty the pool.
    kept = [c for c in candidates if not (_enum_keywords(c, phrase_map) & dislike_kw)]
    if not kept:
        kept = candidates
    weights = [3.0 if (_enum_keywords(c, phrase_map) & like_kw) else 1.0 for c in kept]
    return rng.choices(kept, weights=weights, k=1)[0]


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
            lighting_pool = [_val(li) for li in slot.tmpl.lighting_pool]
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
    if s.lighting not in slot.tmpl.lighting_pool:
        s.lighting = rng.choice(list(slot.tmpl.lighting_pool))

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

_POSE_LOCATION_GUARD: Dict[str, set] = {
    PoseType.COOKING.value: _KITCHENS,
    PoseType.OPENING_FRIDGE.value: _KITCHENS,
    PoseType.EATING.value: _KITCHENS | {
        LocationType.CAFE.value, LocationType.RESTAURANT.value, LocationType.HOME_LIVING_ROOM.value,
    },
    PoseType.JOGGING.value: _OUTDOORS | {LocationType.GYM.value},
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
    allowed = _POSE_LOCATION_GUARD.get(_val(pose))
    return allowed is None or _val(location) in allowed


def _outfit_ok_at(outfit, location) -> bool:
    allowed = _OUTFIT_LOCATION_GUARD.get(_val(outfit))
    return allowed is None or _val(location) in allowed


def _variety_pose_candidates(scene: SceneSpec, slot, controls: BatchControls) -> List[PoseType]:
    base = _allowed_pose_pool(slot.tmpl, controls) if slot is not None \
        else [p for p in PoseType if p not in (controls.blocked_poses or [])]
    return [p for p in base if _pose_ok_at(p, scene.location)]


def _variety_outfit_candidates(scene: SceneSpec, slot, controls: BatchControls) -> List[OutfitType]:
    base = _allowed_outfit_pool(slot.tmpl, controls) if slot is not None else _outfit_fill_pool(controls)
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
        if s.pose is not None and pose_counts.get(_val(s.pose), 0) >= pose_cap:
            candidates = [
                p for p in _variety_pose_candidates(s, slot, controls)
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

    ``enforce_nudity_ramp`` clamps each photo DOWN to the per-photo guided-ceiling
    ramp (and auto-fills an outfit for a medium/high scene that has none, since
    nudity renders only through the outfit step). ``enforce_variety`` runs the
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

        # Nudity clamp. sfw_only -> LOW. Guided-ceiling: clamp DOWN to the per-photo
        # ramp ceiling when enforcing the arc, else the flat max_nudity ceiling. Never
        # forces a level UP (an LLM "low" mid-batch stays low).
        if controls.sfw_only:
            s.nudityLevel = NudityLevel.LOW
        elif enforce_nudity_ramp and i < len(ramp):
            s.nudityLevel = _NUDITY_LADDER[min(_nudity_index(s.nudityLevel), _nudity_index(ramp[i]))]
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
        # own time_pool permits — coherence beats a perfect curve, so a daytime-only
        # beat is never forced to night; with no pool (director path) set it outright.
        if enforce_time_ramp and i < len(time_ramp):
            if i < len(slots):
                s.time_of_day = _nearest_time_in_pool(time_ramp[i], slots[i].tmpl.time_pool)
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
                fill_pool = _outfit_fill_pool(controls)
                if fill_pool:
                    fill_rng = random.Random((controls.base_seed or 0) + 700001 * (i + 1))
                    s.outfit = fill_rng.choice(fill_pool)
                    # A caption with NO confident enum mapping (derived is None — e.g.
                    # "cotton robe", "towel wrapped snugly"): the just-picked random enum
                    # exists ONLY to gate the outfit step and feed variety bookkeeping — it
                    # does NOT describe what she wears. Mark the scene detail-dominant so the
                    # outfit step renders the CAPTION alone (build_prompt skips the random
                    # enum's tier prose) and the gallery card matches the image. A caption
                    # that DID map but to a blocked/disallowed type stays enum-driven:
                    # honoring it would re-introduce the blocked garment.
                    if s.outfit_detail and derived is None:
                        s.outfit_detail_dominant = True

        # Enum<->detail reconcile: when the LLM set an outfit but the caption describes a
        # different garment, the caption wins (override the enum) or the contradicting
        # caption is dropped — so the outfit step never gets self-contradicting signals.
        # Runs right after the fill (a just-filled enum already matches its detail -> no-op).
        _reconcile_outfit(s, controls)

        # Caption-first outfits (C2): the director's garment caption is ALWAYS the rendered
        # garment text now — whenever a scene carries an outfit_detail (and a real,
        # non-NAKED outfit gates the step), mark it detail-dominant so the outfit step
        # renders the caption ALONE and the enum's tier prose only supplies the
        # garment-neutral exposure clause (the nudity ramp) via the existing
        # detail-dominant mechanism. This widens the earlier unmapped/conflict-only rule
        # (the fill/reconcile settings above remain in place — now subsumed but harmless).
        # EXCEPTION: a caption that confidently names a BLOCKED/disallowed garment stays
        # enum-driven — rendering that caption alone would re-introduce the blocked type
        # (the same allow/block-wins rule the fill above applies).
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
    story_mode = getattr(controls, "story_mode", False)

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

    # Build the provider order.
    configured = provider_override or getattr(settings, "STORY_PLANNER_PROVIDER", "") or ""
    if configured:
        order = [configured]
    else:
        order = []
        if settings.VENICE_API_KEY:
            order.append("venice")
        if not is_nsfw and settings.ANTHROPIC_API_KEY:
            order.append("claude")
        order.append("deterministic")

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
            # Venice in story-director mode (story_mode) picks FREELY from the full vocab —
            # snapping it back to hand-authored beat pools would undo the whole point. The
            # deterministic planner's picks are already in-pool, so enforcement there is a
            # safe no-op; legacy scene-only Venice still gets snapped (it was given menus).
            enforce = not (name == "venice" and story_mode)
            return (
                validate_and_repair(scenes, character, count, controls, enforce_beat_pool=enforce),
                name,
            )

    # Deterministic never returns empty for count>=1, but guard anyway.
    scenes = DeterministicScenePlanner().plan_scenes_sync(character, count, controls)
    return validate_and_repair(scenes, character, count, controls), "deterministic"
