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
_NUDITY_LADDER: List[NudityLevel] = [NudityLevel.LOW, NudityLevel.MEDIUM, NudityLevel.HIGH]


# ---------------------------------------------------------------------------
# Character container (planner-local; DB-independent)
# ---------------------------------------------------------------------------
@dataclass
class Character:
    persona: PersonaOptions
    likes: List[str] = field(default_factory=list)
    dislikes: List[str] = field(default_factory=list)
    hero_photo_url: Optional[str] = None


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
        arcs = st.ARC_TEMPLATES.get(occ, st.GENERIC_ARCS)
        arcs = self._select_and_size_arcs(arcs, count, controls.arc_count)

        like_kw = _keyword_set(character.likes)
        dislike_kw = _keyword_set(character.dislikes)

        scenes: List[SceneSpec] = []
        gidx = 0
        for arc, beat_count in arcs:
            for b in range(beat_count):
                tmpl = arc.beats[b % len(arc.beats)]
                pose = self._pick_pose(tmpl, rng, like_kw, dislike_kw, controls)
                outfit = self._pick_outfit(tmpl, rng, like_kw, dislike_kw, controls)
                location = self._pick_location(tmpl, rng, like_kw, dislike_kw, controls)
                nudity = _nudity_for(tmpl.nudity_bias, gidx, count, controls)
                scenes.append(
                    SceneSpec(
                        arc_id=arc.arc_id,
                        arc_title=arc.arc_title,
                        beat_index=b,
                        global_index=gidx,
                        beat_description=tmpl.beat_description,
                        pose=pose,
                        outfit=outfit,
                        nudityLevel=nudity,
                        location=location,
                        time_of_day=rng.choice(tmpl.time_pool),
                        lighting=rng.choice(tmpl.lighting_pool),
                        mood_kinks=character.persona.kinks,
                        mood_personality=character.persona.personality,
                        seed=_derive_seed(controls, gidx),
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
        pool = [p for p in tmpl.pose_pool if p not in (controls.blocked_poses or [])]
        if not pool:
            return None
        return _weighted_pick(pool, rng, like_kw, dislike_kw, {})

    def _pick_outfit(self, tmpl, rng, like_kw, dislike_kw, controls):
        pool = []
        for o in tmpl.outfit_pool:
            if controls.sfw_only and o == OutfitType.NAKED:
                continue
            if o in (controls.blocked_outfits or []):
                continue
            if controls.allowed_outfits and o not in controls.allowed_outfits:
                continue
            pool.append(o)
        if not pool:
            return None  # skip outfit step for this scene
        return _weighted_pick(pool, rng, like_kw, dislike_kw, {})

    def _pick_location(self, tmpl, rng, like_kw, dislike_kw, controls):
        pool = []
        for loc in tmpl.location_pool:
            if loc in (controls.blocked_locations or []):
                continue
            if controls.allowed_locations and loc not in controls.allowed_locations:
                continue
            pool.append(loc)
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


def _nudity_for(bias: str, gidx: int, count: int, controls: BatchControls) -> NudityLevel:
    """
    Nudity for a beat, respecting the max_nudity ceiling and escalation style.

    'building' is monotonically non-decreasing across global_index (guaranteed).
    'flat' uses the beat's own bias, capped at the ceiling.
    """
    if controls.sfw_only:
        return NudityLevel.LOW
    max_idx = _nudity_index(controls.max_nudity)
    if _val(controls.escalation) == "building":
        if count <= 1:
            idx = max_idx
        else:
            idx = int((gidx / (count - 1)) * max_idx + 1e-9)
    else:  # flat
        target = {"low": 0, "medium": 1, "escalate": 1}.get(bias, 0)
        idx = min(target, max_idx)
    idx = max(0, min(idx, max_idx))
    return _NUDITY_LADDER[idx]


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
You plan a sequence of image "beats" grouped into a few narrative ARCS (e.g. a day in the life, or an escalation).

You must output ONLY valid JSON of the form:
{"arcs":[{"arc_id":"snake_case_id","arc_title":"Short title","beats":[BEAT, ...]}, ...]}

Each BEAT is:
{"beat_description":"one short sentence","pose":<pose|null>,"outfit":<outfit|null>,
 "nudityLevel":"low|medium|high","accessories":[<accessory>...]|null,
 "location":<location>,"time_of_day":<time>,"lighting":<lighting>,
 "mood_kinks":[<kink>...]|null,"mood_personality":<personality>|null}

HARD RULES:
- Choose values ONLY from the allowed lists provided. Do NOT invent values.
- Do NOT describe the person's face, age, ethnicity, hair, eyes, body, or breasts anywhere. Only scene attributes.
- Make the sequence feel organic and coherent for THIS character's profession, personality, likes and dislikes.
- Avoid anything matching the character's dislikes.
- nudityLevel must never exceed the stated maximum.
- Output the requested number of beats total across all arcs. No prose, no markdown, only the JSON object.
"""


class VeniceScenePlanner(StoryPlanner):
    name = "venice"
    supports_nsfw = True

    def __init__(self, api_key: str, base_url: str = "https://api.venice.ai/api/v1",
                 model: str = "venice-uncensored", timeout: float = 100.0):
        self.api_key = api_key
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    async def plan_scenes(
        self, character: Character, count: int, controls: BatchControls
    ) -> List[SceneSpec]:
        if not self.api_key:
            return []
        user_prompt = self._build_user_prompt(character, count, controls)
        raw = await self._call_venice(user_prompt)
        if raw is None:
            return []
        return _parse_arcs_json(raw)

    def _build_user_prompt(self, character: Character, count: int, controls: BatchControls) -> str:
        persona = character.persona
        summary_parts = [
            f"occupation: {ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation) or 'unspecified'}",
            f"personality: {ap.phrase(ap.PERSONALITY_PHRASES, persona.personality) or 'unspecified'}",
            f"relationship vibe: {ap.phrase(ap.RELATIONSHIP_PHRASES, persona.relationship) or 'unspecified'}",
            f"likes: {', '.join(character.likes) or 'none given'}",
            f"dislikes: {', '.join(character.dislikes) or 'none given'}",
        ]
        allowed = {
            "pose": _allowed_values(PoseType, blocked=controls.blocked_poses),
            "outfit": _allowed_values(
                OutfitType,
                allowed=controls.allowed_outfits,
                blocked=(controls.blocked_outfits or [])
                + ([OutfitType.NAKED] if controls.sfw_only else []),
            ),
            "accessory": _allowed_values(AccessoryType),
            "location": _allowed_values(
                LocationType, allowed=controls.allowed_locations, blocked=controls.blocked_locations
            ),
            "time_of_day": _allowed_values(TimeOfDayType),
            "lighting": _allowed_values(LightingType),
            "kink": _allowed_values(KinkType),
            "personality": _allowed_values(PersonalityType),
        }
        max_nudity = "low" if controls.sfw_only else _val(controls.max_nudity)
        n_arcs = controls.arc_count or _auto_arc_count(count)
        return (
            f"CHARACTER:\n" + "\n".join(summary_parts) + "\n\n"
            f"PLAN: {count} beats total, grouped into about {n_arcs} arcs, "
            f"escalation style '{_val(controls.escalation)}'.\n"
            f"Maximum nudityLevel allowed: {max_nudity}.\n\n"
            f"ALLOWED VALUES (choose only from these):\n"
            + "\n".join(f"{k}: {', '.join(v)}" for k, v in allowed.items())
        )

    async def _call_venice(self, user_prompt: str) -> Optional[str]:
        content, _usage = await self._client.chat(
            [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4000,
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
            spec = _raw_beat_to_scene(raw_beat, arc_id, arc_title, b, gidx)
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


def _raw_beat_to_scene(raw: dict, arc_id: str, arc_title: str, beat_index: int, global_index: int) -> Optional[SceneSpec]:
    location = _coerce_enum(LocationType, raw.get("location"))
    if location is None:
        location = LocationType.HOME_LIVING_ROOM  # required field; substitute neutral
    nudity = _coerce_enum(NudityLevel, raw.get("nudityLevel")) or NudityLevel.LOW
    accessories_raw = raw.get("accessories") or []
    accessories = [a for a in (_coerce_enum(AccessoryType, x) for x in accessories_raw) if a] or None
    kinks_raw = raw.get("mood_kinks") or []
    mood_kinks = [k for k in (_coerce_enum(KinkType, x) for x in kinks_raw) if k][:3] or None
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


def validate_and_repair(
    scenes: List[SceneSpec],
    character: Character,
    count: int,
    controls: BatchControls,
) -> List[SceneSpec]:
    """Coerce/repair enums, clamp nudity, enforce allow/block, guarantee exactly `count`."""
    max_idx = _nudity_index(controls.max_nudity)
    repaired: List[SceneSpec] = []
    for scene in scenes[:count]:
        s = scene.model_copy(deep=True)

        # Nudity ceiling (hard clamp) + sfw.
        if controls.sfw_only:
            s.nudityLevel = NudityLevel.LOW
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

        # Scrub identity tokens from free-text (defense-in-depth).
        if s.background_text:
            s.background_text = _scrub_identity(s.background_text)
        s.beat_description = _scrub_identity(s.beat_description)

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


# ---------------------------------------------------------------------------
# Provider selection + top-level entry point
# ---------------------------------------------------------------------------
def build_planner(name: str, *, settings) -> StoryPlanner:
    if name == "venice":
        return VeniceScenePlanner(
            api_key=settings.VENICE_API_KEY,
            base_url=settings.VENICE_BASE_URL,
            model=settings.VENICE_MODEL,
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
        return validate_and_repair(scenes, character, count, controls), "manual"

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
            return validate_and_repair(scenes, character, count, controls), name

    # Deterministic never returns empty for count>=1, but guard anyway.
    scenes = DeterministicScenePlanner().plan_scenes_sync(character, count, controls)
    return validate_and_repair(scenes, character, count, controls), "deterministic"
