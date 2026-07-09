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
    "You write ONE short scene/environment sentence for a character photo. Describe "
    "ONLY the environment, the activity she is doing, the mood, and the time of day. "
    "It must be strictly IDENTITY-FREE: never mention appearance or identity — no hair, "
    "eyes, skin, body, figure, breasts, ethnicity, age, or words like woman/girl/blonde. "
    "Keep it to a single vivid sentence, at most about 20 words.\n\n"
    "Output ONLY valid JSON: {\"scene\": \"...\"}. No markdown, no commentary, no extra keys."
)

# Deterministic, identity-free fallbacks (environment + activity + mood + time-of-day).
# A generous, generic pool used when Venice is disabled/unavailable; the choice is
# varied by the request so repeated clicks don't always return the same scene.
_FALLBACK_SCENES = [
    "relaxing on a sunlit apartment balcony in the warm late afternoon",
    "curled up on a cozy sofa with a hot drink while rain taps the window",
    "strolling through a quiet leafy park at golden hour",
    "sitting by a cafe window on a bright, calm morning",
    "unwinding in a softly lit bedroom late at night",
    "leaning on a rooftop railing as the city lights flicker on at dusk",
    "reading in a warm library nook on a lazy afternoon",
    "walking barefoot along a quiet beach as the sun sets",
    "cooking in a bright modern kitchen on a slow Sunday morning",
    "browsing a bustling street market under strings of evening lights",
    "watching the rain from a snug window seat with a blanket",
    "sipping wine on a candlelit terrace on a mild summer evening",
]

# Small occupation-themed openers so the scene nods to persona.occupation when known.
# Keys are real OccupationType values (models/enums.py). All strictly identity-free
# (place/activity/mood only).
_OCCUPATION_SCENES = {
    "nurse": "unwinding at home after a long hospital shift under soft evening light",
    "student": "studying at a cozy library table late into the quiet evening",
    "cook": "plating a dish in a warm restaurant kitchen during the dinner rush",
    "bartender": "wiping down the counter of a dim, moody cocktail bar at night",
    "yoga_instructor": "stretching on a mat in a calm, sunlit studio at dawn",
    "fitness_coach": "cooling down in a bright gym after an early-morning session",
    "model": "resting backstage between shots under warm studio lighting",
    "photographer": "reviewing shots by a wide window in a bright loft studio",
    "librarian": "reshelving books in a quiet, sunlit library on a slow afternoon",
    "artist": "painting at an easel in a light-filled studio on a lazy afternoon",
    "dancer": "catching her breath in a mirrored studio after rehearsal at dusk",
    "writer": "typing at a cluttered desk by a rainy window late at night",
    "secretary": "tidying a bright office desk in the calm of early morning",
    "florist": "arranging bouquets in a fragrant flower shop on a bright morning",
    "singer_musician": "soundchecking on a small stage under warm amber lights",
    "flight_attendant": "sipping coffee in a quiet airport lounge before a night flight",
    "hairdresser": "sweeping up a cozy salon as the last light fades outside",
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
