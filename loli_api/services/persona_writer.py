"""
Persona writer — Venice writes the free-text chat-persona / bio gaps in a Candy.ai
voice from the admin's selected character options.

Mirrors the VeniceScenePlanner pattern (system + user prompt -> JSON -> tolerant
extract -> per-field clamp), but for prose fields instead of scenes. Key rules:

  * PER-FIELD: only the requested fields are generated/returned.
  * PER-FIELD VOICE: every field has its own grammatical voice (3rd-person system
    prompt — client-facing description ABOUT her, never addressed to her or to an
    AI —, 1st-person greeting/welcome with any asterisk *action* describing HER OWN
    action, 3rd-person bio/summary, adjective-list tone/style). The system prompt
    states this and each _FIELD_SPECS.instruction encodes it with a few-shot example.
  * RAW TRAIT LABELS: personality/relationship/occupation/kinks are passed as their
    raw labels (e.g. "nympho", "sugar baby", "stripper", "oral play"), NOT the
    attribute_phrases image-expression maps (those describe camera expressions and
    would corrupt the prose). Only the factual appearance helpers are reused.
  * NEVER RAISES: VeniceClient swallows errors; on any miss we deterministically
    fill that field, so the endpoint always returns usable values.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from models.requests import PersonaOptions
from services import attribute_phrases as ap
from services.culture_vocab import culture_hint
from services.venice_client import VeniceClient

logger = logging.getLogger(__name__)


# Lightweight ethnicity word for prose (the ap.ETHNICITY_PHRASES values are full
# photographic descriptors like "a Latina woman with warm tan skin").
_ETH_WORD = {
    "caucasian": "Caucasian",
    "asian": "Asian",
    "black_afro": "Black",
    "latina": "Latina",
    "arab": "Middle Eastern",
}

# Per-field voice/tense/form contract + length clamp. `instruction` is what the model
# is told for that field; `max_chars` clamps the returned value.
_FIELD_SPECS: Dict[str, Dict] = {
    "system_prompt": {
        "label": "system_prompt",
        "max_chars": 4000,
        "instruction": (
            "A character-profile description, written in THIRD PERSON about her for the "
            "client reading it (never addressed to her, never addressed to an AI), present "
            "tense. Begin \"{name} is a {age}-year-old {ethnicity} woman.\" then describe "
            "her Personality, her relationship to the user, Occupation, Interests, and a "
            "short Background/current scene — natural profile prose, not a list. Forbidden: "
            "\"You are...\" or any second-person address to the character; AI-directive "
            "language such as \"Stay in character\", \"Never break character\", or "
            "\"mention being an AI\"; instruction-manual tone."
        ),
    },
    "greeting_message": {
        "label": "greeting_message",
        "max_chars": 1000,
        "instruction": (
            "Her FIRST message to the user, FIRST PERSON, in-character, present tense — "
            "casual, warm and flirty. 1-2 sentences. e.g. \"Hey there, I'm Jade... what "
            "brings you here tonight?\""
        ),
    },
    "welcome_message": {
        "label": "welcome_message",
        "max_chars": 1000,
        "instruction": (
            "The opening scene message she sends when a chat starts, FIRST PERSON, "
            "in-character, present tense; may open with a brief *action* in asterisks "
            "describing HER OWN action (e.g. \"*I lean back in my chair and smile.*\") and "
            "sets the scene. The asterisk action must never be assigned to the user and must "
            "never start with \"You\". 1-3 sentences."
        ),
    },
    "bio": {
        "label": "bio",
        "max_chars": 2000,
        "instruction": (
            "An 'About me' teaser in THIRD PERSON about her, present tense, with a direct "
            "hook to the reader (\"you\"); punchy and enticing, tasteful, 1-3 sentences. A "
            "tasteful emoji or two is welcome. e.g. \"This hot next-door girl is always "
            "poolside, driving you crazy. Behind that smile is a secret, dirty past.\""
        ),
    },
    "summary": {
        "label": "summary",
        "max_chars": 400,
        "instruction": (
            "A one-line THIRD-PERSON logline of this persona for the admin (neutral, "
            "present tense). e.g. \"A flirty night-shift nurse who loves slow mornings.\""
        ),
    },
    "tone": {
        "label": "tone",
        "max_chars": 120,
        "instruction": (
            "2-4 comma-separated adjectives describing her tone. No sentence. "
            "e.g. \"playful, flirty\""
        ),
    },
    "style": {
        "label": "style",
        "max_chars": 120,
        "instruction": (
            "2-4 comma-separated adjectives describing her chat style. No sentence. "
            "e.g. \"casual, intimate\""
        ),
    },
    "boundaries": {
        "label": "boundaries",
        "max_chars": 800,
        "instruction": (
            "A short comma-separated list of topics/behaviors to avoid. "
            "e.g. \"no violence, no minors, no non-consent, no illegal content\""
        ),
    },
    "name": {
        "label": "name",
        "max_chars": 60,
        "instruction": "ONLY a fitting display name for the persona. Just the name.",
    },
}

PERSONA_FIELDS = tuple(_FIELD_SPECS.keys())

PERSONA_SYSTEM_PROMPT = (
    "You are a senior character writer for an 18+ AI-companion app in the style of "
    "Candy.ai: flirty, immersive, natural adult writing (no euphemistic filler, no "
    "clinical tone). You are given a character's fixed options and must write ONLY the "
    "requested profile fields.\n\n"
    "CRITICAL — each field has its OWN voice; do NOT write them all the same way. Follow "
    "each field's instruction exactly for person (1st/2nd/3rd), tense and form.\n\n"
    "HARD RULES:\n"
    "- Output ONLY a single valid JSON object whose keys are EXACTLY the requested field "
    "names and whose values are plain strings. No markdown, no commentary, no extra keys.\n"
    "- Write in English unless another output language is specified.\n"
    "- Honor the character's likes and avoid the dislikes.\n"
    "- Keep every value within its stated length. Never mention being an AI."
)


def _label(value) -> str:
    """Raw enum/string label, humanized (underscores -> spaces). '' for None."""
    if value is None:
        return ""
    v = getattr(value, "value", value)
    return str(v).replace("_", " ").strip()


def _labels(values) -> str:
    if not values:
        return ""
    return ", ".join(p for p in (_label(v) for v in values) if p)


def _norm_field(f) -> str:
    return getattr(f, "value", f)


def _character_facts(persona: PersonaOptions, enrichment: Optional[dict], name: str) -> str:
    """A compact, prose-friendly fact sheet the model turns into the requested fields."""
    e = enrichment or {}
    eth_val = getattr(persona.ethnicity, "value", persona.ethnicity)
    lines = [
        f"name: {name}",
        f"age: {persona.age}",
        f"appearance (factual, for context): {ap.phrase(ap.ETHNICITY_PHRASES, persona.ethnicity)}"
        f", {ap.hair_phrase(persona.hairStyle, persona.hairColor)}, "
        f"{ap.phrase(ap.EYE_COLOR_PHRASES, persona.eyeColor)}",
        f"ethnicity word: {_ETH_WORD.get(eth_val, 'woman')}",
        f"culture/subculture: {culture_hint(persona.culture) or 'unspecified'}",
        f"personality: {_label(persona.personality) or 'unspecified'}",
        f"relationship to the user: {_label(persona.relationship) or 'unspecified'}",
        f"occupation: {_label(persona.occupation) or 'unspecified'}",
        f"interests/kinks: {_labels(persona.kinks) or 'none given'}",
        f"likes: {_labels(e.get('likes')) or 'none given'}",
        f"dislikes: {_labels(e.get('dislikes')) or 'none given'}",
        f"hobbies/interests: {_labels((e.get('hobbies') or []) + (e.get('interests') or [])) or 'none given'}",
    ]
    if e.get("language"):
        lines.append(f"output language: {e['language']}")
    return "\n".join(lines)


class PersonaWriter:
    """Generates the requested persona/bio fields; never raises."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "venice-uncensored",
        temperature: float = 0.8,
        max_tokens: int = 1200,
        timeout: float = 100.0,
    ):
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def write(
        self,
        persona: PersonaOptions,
        fields: List,
        enrichment: Optional[dict] = None,
        *,
        name: Optional[str] = None,
    ) -> Tuple[Dict[str, str], str]:
        """Return ({field: value} for exactly the requested fields, provider)."""
        req = [f for f in (_norm_field(x) for x in fields) if f in _FIELD_SPECS]
        if not req:
            return {}, "deterministic"
        display_name = (name or persona.name or "she").strip()

        det = self._deterministic_fields(persona, req, enrichment, display_name)
        if not self.enabled:
            return det, "deterministic"

        content, _usage = await self._client.chat(
            [
                {"role": "system", "content": PERSONA_SYSTEM_PROMPT},
                {"role": "user", "content": self._build_user_prompt(persona, req, enrichment, display_name)},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        parsed = _extract_json_object(content) if content else None

        out: Dict[str, str] = {}
        from_venice = 0
        for f in req:
            val = parsed.get(f) if isinstance(parsed, dict) else None
            if isinstance(val, str) and val.strip():
                out[f] = val.strip()[: _FIELD_SPECS[f]["max_chars"]]
                from_venice += 1
            else:
                out[f] = det[f]
        if from_venice == 0:
            provider = "deterministic"
        elif from_venice == len(req):
            provider = "venice"
        else:
            provider = "mixed"
        return out, provider

    def _build_user_prompt(
        self, persona: PersonaOptions, fields: List[str], enrichment: Optional[dict], name: str
    ) -> str:
        facts = _character_facts(persona, enrichment, name)
        field_lines = [
            f'- "{f}": {_FIELD_SPECS[f]["instruction"]} (max {_FIELD_SPECS[f]["max_chars"]} chars)'
            for f in fields
        ]
        return (
            "CHARACTER:\n" + facts + "\n\n"
            "Write ONLY these fields, each in its own voice, as a single JSON object with "
            "exactly these keys:\n" + "\n".join(field_lines)
        )

    def _deterministic_fields(
        self, persona: PersonaOptions, fields: List[str], enrichment: Optional[dict], name: str
    ) -> Dict[str, str]:
        """Template fallback that still respects each field's voice contract."""
        e = enrichment or {}
        eth_val = getattr(persona.ethnicity, "value", persona.ethnicity)
        eth = _ETH_WORD.get(eth_val, "woman")
        personality = _label(persona.personality) or "playful"
        relationship = _label(persona.relationship) or "companion"
        occupation = _label(persona.occupation) or ""
        interests = _labels(persona.kinks) or _labels(e.get("likes"))
        occ_clause = f" {occupation}" if occupation else ""

        def clamp(field: str, text: str) -> str:
            return text.strip()[: _FIELD_SPECS[field]["max_chars"]]

        templates = {
            "name": name,
            "system_prompt": (
                f"{name} is a {persona.age}-year-old {eth} woman. "
                f"Personality: {personality}. Her relationship to the user: {relationship}. "
                + (f"Occupation: {occupation}. " if occupation else "")
                + (f"Interests: {interests}. " if interests else "")
                + f"Background: {name} is warm and easy to talk to, always glad to pick up "
                "right where things left off."
            ),
            "greeting_message": f"Hey there, I'm {name}... what brings you here tonight?",
            "welcome_message": (
                f"*I glance up with a slow smile.* There you are. "
                "I was hoping you'd show up."
            ),
            "bio": (
                f"Meet {name} — a {personality}{occ_clause} who knows exactly how to keep "
                "you on your toes. Get closer and find out what she's hiding. 😏"
            ),
            "summary": f"A {personality}{occ_clause} with a {relationship} vibe.".replace("  ", " "),
            "tone": "playful, flirty",
            "style": "casual, intimate",
            "boundaries": "no violence, no minors, no non-consent, no illegal content",
        }
        return {f: clamp(f, templates.get(f, "")) for f in fields}


def _extract_json_object(raw: Optional[str]) -> Optional[dict]:
    """Tolerant JSON extraction (mirrors story_planner._extract_json_object)."""
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
