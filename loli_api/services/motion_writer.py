"""
Motion writer — Venice turns an admin's freeform "describe your own motion" idea
into a WAN-i2v-friendly motion description plus a short chat-button label.

Mirrors the PersonaWriter pattern (system + user prompt -> JSON -> tolerant
extract -> clamp) but for the reel motion path instead of prose fields. Key rules:

  * ENDS ON A BEAT: the description must resolve on an actionable, camera-facing
    beat (smile / blink / wink / lean) so the WAN clip doesn't cut mid-motion.
  * NEVER RAISES: VeniceClient swallows errors; on any miss (disabled, empty
    response, unparseable JSON, missing fields) we deterministically fall back to
    the raw user text + a truncated label, so create_video always has usable
    values.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Tuple

from services.venice_client import VeniceClient

logger = logging.getLogger(__name__)

# Match the chat-button label cap used in api/v1/endpoints/video.py.
_MAX_LABEL_LEN = 40

MOTION_SYSTEM_PROMPT = (
    "You convert a user's freeform idea for a short looping character video into "
    "two things: (a) a vivid, WAN-i2v motion description that ENDS ON an "
    "actionable, camera-facing beat (a smile, blink, wink, or lean toward the "
    "camera) so the clip resolves rather than cutting mid-motion, and (b) a short "
    "2-4 word button label for the action.\n\n"
    "Output ONLY valid JSON: {\"motion\": \"...\", \"label\": \"...\"}. "
    "No markdown, no commentary, no extra keys."
)


class MotionWriter:
    """Interprets a custom motion prompt into (description, label); never raises."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "venice-uncensored",
        temperature: float = 0.7,
        max_tokens: int = 200,
        timeout: float = 100.0,
    ):
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def interpret(self, user_text: str) -> Tuple[str, str, str]:
        """Return (motion_description, label, provider).

        provider is "venice" when the LLM produced both fields, else
        "deterministic" (raw user text + a truncated label). Never raises.
        """
        raw = (user_text or "").strip()
        fallback_label = raw.replace("\n", " ")[:_MAX_LABEL_LEN]

        if not self.enabled:
            return raw, fallback_label, "deterministic"

        content, _usage = await self._client.chat(
            [
                {"role": "system", "content": MOTION_SYSTEM_PROMPT},
                {"role": "user", "content": raw},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        if not content:
            return raw, fallback_label, "deterministic"

        parsed = _extract_json_object(content)
        if not isinstance(parsed, dict):
            return raw, fallback_label, "deterministic"

        motion = parsed.get("motion")
        label = parsed.get("label")
        if not (isinstance(motion, str) and motion.strip()):
            return raw, fallback_label, "deterministic"
        if not (isinstance(label, str) and label.strip()):
            return raw, fallback_label, "deterministic"

        return motion.strip(), label.strip()[:_MAX_LABEL_LEN], "venice"


def _extract_json_object(raw: Optional[str]) -> Optional[dict]:
    """Tolerant JSON extraction (mirrors persona_writer._extract_json_object)."""
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
