"""
Scene-direction writer (WS-SD) — Venice writes HOW EACH PHOTO LOOKS.

Division of labor: the deterministic planner (services.story_planner) decides WHAT each
photo is — outfit, pose, location, nudity, time — all real-world-coherence-guarded. This
module lets Venice add HOW IT LOOKS: 1-3 sentences of concrete photographic staging per
item (the furniture/objects, where in the space she is, the camera feel). It is per-item
DECORATION with HARD validation and a safe fallback — NOT narrative. (The old STORY mode
let Venice author the day and hallucinated; it was retired. This never re-decides a single
scene fact — it only decorates the already-final ones, and anything it emits that would
change a fact, name identity/clothing/a different place, or invent people is rejected.)

Shape (mirrors scene_writer / trait_profile_writer):
  * ONE batched Venice call per batch (a JSON list of every item's facts in, a JSON array
    of directions out) — never one call per item.
  * NEVER RAISES: VeniceClient swallows transport errors; this module swallows the rest.
    Provider "deterministic", no API key, a whole-call error/timeout/bad-JSON, or a single
    item that fails validation -> that item keeps its bare `staging` phrase
    (scene_direction=None) and the mapper falls back to it. direction_source records the
    provenance ("venice" | "fallback" | None).
  * VALIDATED per item (validate_scene_direction, a pure unit-tested function): length,
    no identity/appearance vocab (reusing story_planner's identity scrub patterns), no
    clothing outside the item's own outfit, no foreign-location tokens (reusing the
    planner's _LOCATION_CAPTION_TOKENS), no interacting/named people (anonymous background
    crowd wording allowed ONLY at a public venue), and no story/second-person markers.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from models.enums import OutfitType
from services import scene_vocab as sv
from services import story_planner as sp
from services.venice_client import VeniceClient

logger = logging.getLogger(__name__)


# Hard length cap on a single item's direction (the validator rejects anything longer; the
# SceneSpec.scene_direction field itself allows 340, leaving headroom).
_MAX_DIRECTION_LEN = 320


# ---------------------------------------------------------------------------
# Validator vocab (reuses story_planner helpers where they exist)
# ---------------------------------------------------------------------------
# Truly-EXTRA anatomy/figure words NOT covered by story_planner._APPEARANCE_PATTERNS (which
# cover "<x> hair/eyes/skin", person nouns and ages) NOR by story_planner._IDENTITY_TOKENS
# (ethnicity/hair-color/hair-style/eye-color vocab — now reused directly, see below). The
# ethnicity/hair-person words that used to live here (asian/caucasian/latina/blonde/brunette/
# redhead) are dropped as redundant. Deliberately body/figure nouns only.
_EXTRA_APPEARANCE_RE = re.compile(
    r"\b(?:face|facial|lips?|cheeks?|jaws?|chins?|thighs?|breasts?|cleavage|bust|"
    r"nipples?|slim|slender|curvy|petite|voluptuous|toned|nude|naked|topless|"
    r"ethnic|ethnicity)\b",
    re.IGNORECASE,
)

# Identity vocab reused straight from the planner (ethnicity + hair-color/style + eye-color —
# story_planner._IDENTITY_TOKENS, built from the attribute_phrases maps), so it can never
# drift from what the planner itself scrubs. The old hand list missed most of it (e.g. every
# ethnicity but asian/caucasian/latina). Split into single-word tokens (matched against the
# direction's word set) and multi-word phrases (matched as substrings).
#
# A few identity tokens double as ordinary SCENERY vocabulary — bare colors ("a brown leather
# sofa", "a black side table") and shape/length words ("a short stool", "straight lines"). A
# STANDALONE such word almost always describes the SET, not a person, so it is excluded from
# the token scan to avoid rejecting legitimate staging; the SAME word is still caught in an
# appearance CONTEXT ("brown hair", "straight hair") by _APPEARANCE_PATTERNS below.
_IDENTITY_SCENE_AMBIGUOUS = frozenset({
    "black", "brown", "green", "blue", "pink", "short", "straight", "bun",
})
_IDENTITY_WORD_TOKENS = frozenset(
    t for t in sp._IDENTITY_TOKENS if " " not in t and t not in _IDENTITY_SCENE_AMBIGUOUS
)
_IDENTITY_PHRASES = tuple(sorted(t for t in sp._IDENTITY_TOKENS if " " in t))

# Camera idioms that legitimately contain an appearance HEAD word ("eye level" is the most
# common framing term) — neutralized before the appearance scan so they don't trip the
# reused eyes/… patterns. Only these fixed compounds are excused; a bare "her eyes" still fails.
_CAMERA_IDIOM_RE = re.compile(r"\beye[-\s](?:level|line|height)\b", re.IGNORECASE)

# Second-person / story-voice markers (a direction is a camera instruction, never prose).
_STORY_RE = re.compile(
    r"\b(?:you|your|yours|yourself|"
    r"remembers?|remembering|recalls?|recalling|reminisc\w+|"
    r"feels?|felt|feeling|thinks?|thought|thinking|knows?|knew|"
    r"wonders?|wondered|dreams?|dreaming|wishes?|wished|misses?|missed|"
    r"yearns?|yearning|longs?|longing|imagines?|imagining|remembers)\b",
    re.IGNORECASE,
)

# People words banned in EVERY venue (named/relational/individuated others).
_PEOPLE_BANNED_ALWAYS = frozenset({
    "man", "men", "woman", "women", "guy", "guys", "boy", "boys", "lady", "ladies",
    "couple", "couples", "boyfriend", "girlfriend", "husband", "wife", "friend", "friends",
    "colleague", "colleagues", "partner", "partners", "lover", "lovers", "date",
    "someone", "somebody", "child", "children", "kid", "kids",
})
# Anonymous-BACKGROUND people words tolerated ONLY at a public venue (never in private).
_PEOPLE_BG_OK = frozenset({
    "people", "strangers", "crowd", "crowds", "silhouettes", "patrons",
})

def _val(v) -> Optional[str]:
    return sp._val(v)


def _garment_class(token: str) -> Optional[str]:
    """The garment-CLASS base word a token names, reusing story_planner._GARMENT_CLASS_WORDS
    (single source of truth — no drift) and tolerant of one trailing plural 's'/'es'
    ('skirts'->'skirt', 'dresses'->'dress'). None when the token is not a garment class —
    including furniture-ambiguous fabric words the planner set deliberately omits
    ('leather', 'velvet'), so 'leather sofa' / 'velvet booth' still validate."""
    if token in sp._GARMENT_CLASS_WORDS:
        return token
    if token.endswith("es") and token[:-2] in sp._GARMENT_CLASS_WORDS:
        return token[:-2]
    if token.endswith("s") and token[:-1] in sp._GARMENT_CLASS_WORDS:
        return token[:-1]
    return None


def _words(text: str) -> set:
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def validate_scene_direction(
    direction: Optional[str],
    *,
    location,
    outfit=None,
    outfit_detail: Optional[str] = None,
    venue_public: bool = False,
) -> Optional[str]:
    """
    Return the cleaned direction (whitespace-collapsed, <=320 chars) if it passes EVERY
    rule, else None (the caller then keeps the item's staging phrase). Pure + unit-tested.

    Rules (all must pass):
      * non-empty, <= 320 chars;
      * NO identity/appearance vocab — reuses story_planner._APPEARANCE_PATTERNS (hair/eyes/
        skin/person-noun/age) plus an anatomy list (face/lips/breast/nude/…);
      * NO story/second-person markers (she remembers…, you…, names via people rule);
      * NO people — banned words (man/woman/couple/friend/…) fail everywhere; anonymous
        background words (people/strangers/crowd) fail in a PRIVATE venue and pass only at a
        public one;
      * NO clothing word outside the item's OWN outfit words (so it can't name/change the
        garment);
      * NO foreign-location tokens — reuses story_planner._caption_foreign_location, so a
        direction may reference its OWN place but never a DIFFERENT one.
    """
    if not isinstance(direction, str):
        return None
    text = re.sub(r"\s+", " ", direction).strip()
    if not text or len(text) > _MAX_DIRECTION_LEN:
        return None
    low = text.lower()

    words = _words(text)

    # Identity / appearance — reuse the planner's own identity machinery so this can't drift.
    # Neutralize the "eye level"/"eye-line"/"eye height" camera idioms first so they don't
    # trip the reused eyes-pattern (a bare "her eyes" is untouched and still fails).
    #   1. contextual appearance (story_planner._APPEARANCE_PATTERNS): "<x> hair/eyes/skin",
    #      person nouns, ages — catches "brown hair"/"green eyes" even for scene-ambiguous colors;
    #   2. the planner's full identity vocab (_IDENTITY_TOKENS, minus scene-ambiguous bare words)
    #      as standalone words + multi-word phrases — the coverage the hand list lacked;
    #   3. the truly-extra anatomy/figure words.
    probe = _CAMERA_IDIOM_RE.sub(" ", text)
    if any(p.search(probe) for p in sp._APPEARANCE_PATTERNS):
        return None
    if words & _IDENTITY_WORD_TOKENS:
        return None
    if any(phrase in low for phrase in _IDENTITY_PHRASES):
        return None
    if _EXTRA_APPEARANCE_RE.search(text):
        return None

    # Story / second-person voice.
    if _STORY_RE.search(text):
        return None

    # People: relational/individuated names are never allowed; background-crowd words are
    # allowed only at a public venue.
    if words & _PEOPLE_BANNED_ALWAYS:
        return None
    if (words & _PEOPLE_BG_OK) and not venue_public:
        return None

    # Clothing: any garment CLASS the direction names (reusing the planner's set) must be
    # covered by the item's OWN outfit words (enum value + outfit_detail); otherwise the
    # direction is naming/adding a garment. Both sides normalize to the base class (plural-
    # tolerant) so a stray "dresses" is caught while the item's own "dress" still passes.
    outfit_words = _words((_val(outfit) or "").replace("_", " "))
    outfit_words |= _words(outfit_detail or "")
    outfit_classes = set()
    for w in outfit_words:
        cls = _garment_class(w)
        if cls:
            outfit_classes.add(cls)
    for w in words:
        cls = _garment_class(w)
        if cls and cls not in outfit_classes:
            return None

    # Location: must not name a DIFFERENT location's tokens. Suppressed when the direction
    # ALSO names its OWN location — some locations legitimately SHARE a token (office /
    # home_office both carry "office", the two kitchens "kitchen", the two studios "studio"),
    # and an intra-family reference is harmless (mirrors story_planner._reconcile_captions).
    final_val = _val(location)
    if not sp._caption_names_location(low, sp._LOCATION_CAPTION_TOKENS.get(final_val, ())) \
            and sp._caption_foreign_location(low, final_val):
        return None

    return text


# ---------------------------------------------------------------------------
# Venice prompt
# ---------------------------------------------------------------------------
SCENE_DIRECTION_SYSTEM_PROMPT = (
    "You are a photographic staging director for a solo photo series of ONE fixed model. "
    "For EACH item you are given its already-decided facts (place, time, her pose, her "
    "outfit, nudity band, a staging suggestion). You write ONLY how the shot LOOKS: 1-3 "
    "short sentences (<=320 characters total) of concrete visual staging — the furniture "
    "and objects around her, exactly WHERE in the space she is, and the camera feel "
    "(angle, distance, depth of field). Camera-instruction language for an image model, "
    "not prose.\n\n"
    "HARD RESTRICTIONS (a violation makes the item unusable):\n"
    "- NEVER describe HER: no face, body, hair, skin, age, ethnicity, figure or identity "
    "of any kind.\n"
    "- NEVER name or change her CLOTHING — the outfit is already decided; describe the "
    "SET, not the wardrobe.\n"
    "- NEVER add interacting or named people. Anonymous background crowd wording (e.g. "
    "'a blurred crowd', 'distant strangers') is allowed ONLY where venue_public is true; "
    "at a private venue she is completely alone.\n"
    "- NEVER contradict or relocate the scene: stay inside the given place, and do not "
    "name a DIFFERENT location.\n"
    "- NO story, narrative, names, memories, feelings or second person ('you').\n"
    "- NO explicitness beyond the stated nudity band; keep it about the SET.\n\n"
    "Output STRICT JSON only: an array [{\"index\": <int>, \"direction\": \"<text>\"}, ...] "
    "with one object per item, same indices as the input. No markdown, no commentary."
)


class SceneDirectionWriter:
    """Batched Venice scene-direction generator; never raises on transport."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "venice-uncensored",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        timeout: float = 20.0,
    ):
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def write_batch(
        self, items: List[Dict[str, Any]], *, hint: str = ""
    ) -> Optional[List[Optional[str]]]:
        """
        ONE Venice call for the whole batch. Returns a list of raw direction strings indexed
        by item index (missing/extra indices -> None at that slot), or None on any whole-call
        failure (disabled, empty response, unparseable JSON). The caller validates each entry.
        """
        if not self.enabled or not items:
            return None
        # self.max_tokens is a FLOOR, not a fixed cap: a large batch (one call, all items)
        # needs room for every item's direction, so scale up to ~130 tokens/item + a 400
        # header. Without this a 50-item batch would truncate mid-array and the whole call
        # falls back silently (every item keeps its bare staging phrase).
        effective_max_tokens = max(self.max_tokens, 400 + 130 * len(items))
        content, _usage = await self._client.chat(
            [
                {"role": "system", "content": SCENE_DIRECTION_SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(items, hint)},
            ],
            temperature=self.temperature,
            max_tokens=effective_max_tokens,
        )
        if not content:
            return None
        return _parse_directions(content, len(items))


def _facts_for_scene(index: int, scene, controls) -> Dict[str, Any]:
    """The identity-free fact bundle handed to Venice for one item (no explicit prose)."""
    facts: Dict[str, Any] = {
        "index": index,
        "location": sv.location_phrase(scene.location) or _val(scene.location),
        "venue_public": bool(sv.is_public_venue(scene.location)),
        "time_of_day": (sv.time_of_day_phrase(scene.time_of_day) or _val(scene.time_of_day)),
        "nudity_band": _val(scene.nudityLevel),
    }
    if scene.pose is not None:
        facts["pose"] = (_val(scene.pose) or "").replace("_", " ")
    if scene.outfit is not None:
        note = (scene.outfit_detail or "").strip()
        facts["outfit"] = (_val(scene.outfit) or "").replace("_", " ") + (f" ({note})" if note else "")
    if getattr(scene, "staging", None):
        facts["staging_suggestion"] = scene.staging
    return facts


def _demeanor_hint(controls) -> str:
    vals = []
    for d in (getattr(controls, "demeanor", None) or []):
        v = _val(d)
        if v:
            vals.append(v.replace("_", " "))
    return ", ".join(vals)


def _build_user_prompt(items: List[Dict[str, Any]], hint: str = "") -> str:
    payload = json.dumps(items, ensure_ascii=False)
    hint_line = (
        f"Overall styling vibe for the set: {hint}. Let it colour the staging, never the "
        f"restrictions.\n\n" if hint else ""
    )
    return (
        f"{hint_line}Write staging for these {len(items)} items. For EACH, return one object "
        f"{{\"index\", \"direction\"}} — 1-3 sentences (<=320 chars) of concrete visual "
        f"staging that fits its facts and obeys every restriction.\n\nITEMS:\n{payload}"
    )


def _parse_directions(raw: str, n: int) -> Optional[List[Optional[str]]]:
    """Parse the JSON array into a per-index list of raw strings (length n)."""
    data = _extract_json(raw)
    arr = None
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        # tolerate {"directions": [...]} or {"items": [...]}
        for key in ("directions", "items", "results"):
            if isinstance(data.get(key), list):
                arr = data[key]
                break
    if not isinstance(arr, list):
        return None
    out: List[Optional[str]] = [None] * n
    for obj in arr:
        if not isinstance(obj, dict):
            continue
        idx = obj.get("index")
        direction = obj.get("direction")
        if isinstance(idx, bool) or not isinstance(idx, int):
            continue
        if 0 <= idx < n and isinstance(direction, str):
            out[idx] = direction
    return out


def _extract_json(raw: Optional[str]):
    """Tolerant JSON extraction (array or object). Mirrors the other writers."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    # First array, then first object.
    for pattern in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    return None


async def apply_scene_directions(scenes: List, controls, *, settings) -> List:
    """
    Populate scene_direction / direction_source on every scene IN PLACE, AFTER
    validate_and_repair (the facts are final). Returns the same list. NEVER raises.

    Provider (settings.SCENE_DIRECTION_PROVIDER, default "venice"):
      * "deterministic" (or no VENICE_API_KEY) -> Venice is NOT called; every scene keeps
        scene_direction=None / direction_source=None, so the mapper falls back to the bare
        `staging` phrase and the batch is byte-identical to the pre-feature behavior.
      * "venice" -> ONE batched call; each item whose returned direction passes
        validate_scene_direction gets scene_direction=text, direction_source="venice"; every
        other item (invalid, or the whole call failed/timed out) gets scene_direction=None,
        direction_source="fallback".
    """
    if not scenes:
        return scenes
    provider = (getattr(settings, "SCENE_DIRECTION_PROVIDER", "venice") or "venice").strip().lower()
    if provider != "venice":
        return scenes  # deterministic: skip Venice entirely, leave fields untouched (None)

    writer = SceneDirectionWriter(
        api_key=getattr(settings, "VENICE_API_KEY", "") or "",
        base_url=getattr(settings, "VENICE_BASE_URL", "https://api.venice.ai/api/v1"),
        model=(
            getattr(settings, "SCENE_DIRECTION_MODEL", "")
            or getattr(settings, "VENICE_MODEL", "")
            or "venice-uncensored"
        ),
        temperature=getattr(settings, "SCENE_DIRECTION_TEMPERATURE", 0.7),
        max_tokens=getattr(settings, "SCENE_DIRECTION_MAX_TOKENS", 4000),
        timeout=getattr(settings, "SCENE_DIRECTION_TIMEOUT_SECONDS", 20.0),
    )
    if not writer.enabled:
        return scenes  # no key -> deterministic (no network), leave fields None

    items = [_facts_for_scene(i, s, controls) for i, s in enumerate(scenes)]
    try:
        raw = await writer.write_batch(items, hint=_demeanor_hint(controls))
    except Exception as e:  # noqa: BLE001 — a decoration writer must never break a launch
        logger.error(f"SceneDirectionWriter failed; all items fall back: {e}")
        raw = None

    for i, s in enumerate(scenes):
        cand = raw[i] if (raw is not None and i < len(raw)) else None
        valid = None
        if cand:
            valid = validate_scene_direction(
                cand,
                location=s.location,
                outfit=s.outfit,
                outfit_detail=s.outfit_detail,
                venue_public=sv.is_public_venue(s.location),
            )
        if valid:
            s.scene_direction = valid
            s.direction_source = "venice"
        else:
            # Keep the bare staging phrase as the effective direction (mapper falls back).
            s.scene_direction = None
            s.direction_source = "fallback"
    return scenes
