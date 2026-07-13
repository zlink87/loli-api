"""
Scene writer — Venice writes a short, IDENTITY-FREE scene/environment sentence the
admin drops into a Batch Character Creation draft's ``context`` field
(POST /v1/scenes/randomize).

Mirrors the MotionWriter pattern (system + user prompt -> JSON -> tolerant extract ->
clamp) but for a render-safe scene string. Key rules:

  * IDENTITY-FREE: the sentence describes environment / activity / mood / time-of-day
    ONLY — never appearance/identity (hair, eyes, body, ethnicity, age, breasts). After
    the LLM responds we ALSO scrub any identity tokens with story_planner._scrub_identity
    (defense-in-depth), so the scene can never fight the persona's locked identity.
  * NEVER RAISES: VeniceClient swallows errors; on any miss (disabled, empty response,
    unparseable JSON, missing/empty field, or a scene the scrub emptied) we fall back to
    a deterministic curated scene varied by the input, so the endpoint always returns a
    usable, identity-free scene.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Tuple

from services.venice_client import VeniceClient

# Reuse (do NOT reinvent) the story planner's identity scrub + token set — the same
# defense-in-depth applied to render-safe SceneSpec free-text.
from services.story_planner import _scrub_identity

logger = logging.getLogger(__name__)

# Hard cap on the returned scene (matches the render-safe SceneSpec.setting limit).
_MAX_SCENE_LEN = 400

SCENE_SYSTEM_PROMPT = (
    "You write ONE literal scene/environment sentence for a character photo — a CAMERA "
    "INSTRUCTION for an image model, NOT a story. Name a concrete PLACE, ONE visible "
    "ACTIVITY she is doing, and the LIGHT or time of day, using only what a camera can "
    "see: objects, surfaces, furniture, light sources. NO metaphors or similes (no "
    "'like...', 'as if...'), NO mood-prose or feelings (no 'cozy', 'serene', 'lost in "
    "thought', 'tension easing into calm'), NO narration — physical detail only. "
    "It must be strictly IDENTITY-FREE: never mention appearance or identity — no hair, "
    "eyes, skin, body, figure, breasts, ethnicity, age, or words like woman/girl/blonde. "
    "Keep it to a single sentence, at most about 20 words.\n\n"
    "Output ONLY valid JSON: {\"scene\": \"...\"}. No markdown, no commentary, no extra keys."
)

# Deterministic, identity-free fallbacks — literal (place + visible activity + light/
# time-of-day), no mood-prose, since each lands VERBATIM in the image prompt. A generous,
# generic pool used when Venice is disabled/unavailable; the choice is varied by the
# request so repeated clicks don't always return the same scene.
_FALLBACK_SCENES = [
    "standing at an apartment balcony railing with a coffee mug in late afternoon sun",
    "sitting on a sofa with a hot mug, rain running down the window",
    "walking a tree-lined park path at golden hour",
    "sitting at a cafe window table with a coffee cup in morning light",
    "sitting on a bed in a lamp-lit bedroom late at night",
    "leaning on a rooftop railing as city lights switch on at dusk",
    "reading a book at a library table in afternoon light",
    "walking barefoot along the shoreline as the sun sets",
    "cooking at a stove in a bright kitchen on a Sunday morning",
    "browsing stalls at a street market under strings of evening lights",
    "sitting on a window seat under a blanket, watching rain on the glass",
    "sitting at a candlelit terrace table with a wine glass on a summer evening",
]

# Small occupation-themed openers so the scene nods to persona.occupation when known.
# Keys are real OccupationType values (models/enums.py). All strictly identity-free and
# literal (place + visible activity + light only), no mood-prose.
_OCCUPATION_SCENES = {
    "nurse": "sitting on a sofa at home in soft evening light after a hospital shift",
    "student": "studying at a library table stacked with books in the evening",
    "cook": "plating a dish at a steel counter in a restaurant kitchen during dinner service",
    "bartender": "wiping down the counter of a dim cocktail bar at night",
    "yoga_instructor": "stretching on a mat by tall windows in soft dawn light",
    "fitness_coach": "resting on a bench in a bright gym after an early-morning workout",
    "model": "sitting backstage on a stool between shots under warm lights",
    "photographer": "reviewing photos on a camera by a wide loft window in daylight",
    "librarian": "reshelving books between tall library shelves in afternoon light",
    "artist": "painting at an easel by a large window in afternoon light",
    "dancer": "resting against a mirrored wall in a dance hall after rehearsal at dusk",
    "writer": "typing at a cluttered desk by a rain-streaked window late at night",
    "secretary": "tidying a bright office desk in the early morning",
    "florist": "arranging bouquets on a workbench in a flower shop in morning light",
    "singer_musician": "soundchecking with a microphone on a small stage under amber lights",
    "flight_attendant": "sitting with a coffee cup in an airport lounge before a night flight",
    "hairdresser": "sweeping the floor of a salon as daylight fades in the windows",
}


class SceneWriter:
    """Writes a short, identity-free scene sentence; never raises."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "venice-uncensored",
        temperature: float = 0.9,
        max_tokens: int = 160,
        timeout: float = 100.0,
    ):
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def randomize(self, persona=None, hint: Optional[str] = None) -> Tuple[str, str]:
        """Return (scene_text, provider).

        provider is "venice" when the LLM produced a usable, identity-free scene, else
        "deterministic" (a curated fallback varied by the input). Never raises. The scene
        is always identity-scrubbed before it is returned.
        """
        fallback = _pick_fallback_scene(persona, hint)

        if not self.enabled:
            return fallback, "deterministic"

        content, _usage = await self._client.chat(
            [
                {"role": "system", "content": SCENE_SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(persona, hint)},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        if not content:
            return fallback, "deterministic"

        parsed = _extract_json_object(content)
        if not isinstance(parsed, dict):
            return fallback, "deterministic"

        scene = parsed.get("scene")
        if not (isinstance(scene, str) and scene.strip()):
            return fallback, "deterministic"

        # Identity safety: scrub any appearance/identity tokens the LLM slipped in, then
        # clamp. If nothing survives, use the deterministic fallback instead.
        scrubbed = _scrub_identity(scene.strip())
        scrubbed = (scrubbed or "").strip()[:_MAX_SCENE_LEN].strip(" ,.;")
        if not scrubbed:
            return fallback, "deterministic"

        return scrubbed, "venice"


def _build_user_message(persona, hint: Optional[str]) -> str:
    """Compose the user prompt, theming the scene by persona traits + an optional hint."""
    parts = []
    occupation = _get(persona, "occupation")
    personality = _get(persona, "personality")
    relationship = _get(persona, "relationship")
    if occupation:
        parts.append(f"Her occupation is {str(occupation).replace('_', ' ')}.")
    if personality:
        parts.append(f"Her personality is {str(personality).replace('_', ' ')}.")
    if relationship:
        parts.append(f"Relationship context: {str(relationship).replace('_', ' ')}.")
    if hint and hint.strip():
        parts.append(f"Scene hint to build on: {hint.strip()}")
    parts.append(
        "Write one short, identity-free scene sentence (environment, activity, mood, "
        "time of day only)."
    )
    return " ".join(parts)


def _pick_fallback_scene(persona, hint: Optional[str]) -> str:
    """A deterministic, identity-free scene varied by the input (occupation/personality/hint)."""
    occupation = _get(persona, "occupation")
    key = str(occupation).lower() if occupation else ""
    if key in _OCCUPATION_SCENES:
        return _OCCUPATION_SCENES[key]

    personality = _get(persona, "personality")
    seed_str = f"{key}|{personality or ''}|{(hint or '').strip().lower()}"
    # Stable, process-independent index (hash() is salted per-process, so avoid it).
    idx = sum(ord(c) for c in seed_str) % len(_FALLBACK_SCENES) if seed_str.strip("|") else 0
    return _FALLBACK_SCENES[idx]


def _get(persona, attr: str):
    """Read a persona attribute tolerantly (Pydantic object, dict, or None)."""
    if persona is None:
        return None
    if isinstance(persona, dict):
        val = persona.get(attr)
    else:
        val = getattr(persona, attr, None)
    # Enums coerce to their .value for a clean, human phrase.
    return getattr(val, "value", val)


def _extract_json_object(raw: Optional[str]) -> Optional[dict]:
    """Tolerant JSON extraction (mirrors motion_writer._extract_json_object)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
