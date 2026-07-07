"""
Prompt generation service.

The locked identity block and shot/framing block are always assembled
DETERMINISTICALLY from the admin's selected attributes (enums), so they are
guaranteed present by construction. The Venice LLM is used only to *write the
scene* — environment, wardrobe atmosphere, lighting, mood and action — from a
short user hint (or nothing) plus the persona vibe. That scene clause takes the
place of the raw user free-text; it is verified not to invent a contradicting
physical attribute, and on failure/absence the pipeline falls back to the raw
hint. A Venice outage / isEnhance=False still yields a complete, identity-faithful,
quality-scaffolded prompt.
"""
import logging
import re
from typing import List, Optional, Tuple

from models.requests import PersonaOptions, ShotOptions
from models.enums import NudityLevel, OutfitType, AccessoryType
from services import attribute_phrases as ap
from services import camera_vocab as cv
from services import prompt_constants as pc
from services import outfit_vocab as ov
from services.venice_client import VeniceClient

logger = logging.getLogger(__name__)

# Hard cap on the LLM-written scene clause. Z-Image Turbo is a fast turbo diffusion
# model that prefers short prompts; a scene that runs over this is rejected in
# favor of the raw user hint (never mid-sentence truncated).
MAX_SCENE_WORDS = 90

# Venice pricing per 1M tokens (USD): {"model": {"input", "cached", "output"}}.
# Venice bills in VCU rather than fixed per-token USD, so this is left empty and
# cost is reported as $0 / best-effort; token counts are always logged.
VENICE_PRICING: dict = {}

# Venice is a SCENE WRITER. It receives the persona vibe + clothing context + an
# optional user hint and returns ONLY a scene clause. It must never describe the
# person's identity (that is assembled deterministically) nor introduce any
# camera/framing language (that was the root cause of inconsistent hero-shot crops).
SCENE_SYSTEM_PROMPT = '''You are a scene writer for a photorealistic NSFW image generator.
You will be given a PERSONA SUMMARY (the character's vibe: personality, occupation, relationship, kinks), a CLOTHING/NUDITY CONTEXT, and an optional USER HINT.

Your job: write ONE vivid, concrete scene clause describing the setting the character is in.

HARD RULES:
- Describe ONLY the environment, setting, wardrobe atmosphere, lighting, mood, and the character's action or posture in that setting.
- NEVER describe the person's face, age, ethnicity, skin tone, hair, eyes, body type, or breasts. Those identity facts are fixed elsewhere and must not appear here.
- NEVER add camera, crop, shot, framing, or lens language.
- If a USER HINT is given, build the scene around it and do not contradict it. If no hint is given, invent a fitting scene for the persona.
- Be objective and concrete. No metaphors. No negative phrasing (describe only what IS present).
- Target 30-70 words. This feeds a fast turbo diffusion model that prefers short prompts.

OUTPUT: only the scene clause text. No preamble, no analysis, no quotes.
'''


# ---------------------------------------------------------------------------
# Deterministic assembly (no model in the loop for identity)
# ---------------------------------------------------------------------------

def locked_tokens(persona: PersonaOptions) -> List[str]:
    """The identity phrases that MUST survive any polishing."""
    tokens = [
        ap.age_phrase(persona.age),
        ap.phrase(ap.ETHNICITY_PHRASES, persona.ethnicity),
        ap.hair_phrase(persona.hairStyle, persona.hairColor),
        ap.phrase(ap.EYE_COLOR_PHRASES, persona.eyeColor),
        ap.phrase(ap.BODY_TYPE_PHRASES, persona.bodyType),
        ap.phrase(ap.BREAST_SIZE_PHRASES, persona.breastSize),
    ]
    return [t for t in tokens if t]


def identity_block(persona: PersonaOptions) -> str:
    """The locked identity block — the contract that must survive."""
    return ", ".join(locked_tokens(persona))


def _persona_flavor(persona: PersonaOptions, suppress_expression: bool = False) -> str:
    """Persona flavor phrases. suppress_expression drops the personality's
    expression phrase when an explicit shot expression override is set (avoids
    two conflicting expression clauses)."""
    parts = [
        "" if suppress_expression else ap.phrase(ap.PERSONALITY_PHRASES, persona.personality),
        ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation),
        ap.phrase(ap.RELATIONSHIP_PHRASES, persona.relationship),
        ap.kinks_phrase(persona.kinks),
    ]
    return ", ".join(p for p in parts if p)


def assemble_generation_prompt(
    persona: PersonaOptions,
    free_text: Optional[str] = None,
    shot: Optional[ShotOptions] = None,
    outfit: Optional[OutfitType] = None,
    nudity_level: NudityLevel = NudityLevel.LOW,
    accessories: Optional[List[AccessoryType]] = None,
) -> Tuple[str, str, str]:
    """
    Deterministically assemble a character-generation prompt.

    Assembly order: scaffold, shot block (framing+angle+expression), locked
    identity, clothing clause, persona flavor, free text, quality suffix.
    shot=None falls back to hero defaults (waist-up, eye level) so every caller
    gets a consistent crop.

    The clothing clause is injected early (right after locked identity, ahead of
    the flavor/free-text) because the generation base model is NSFW-tuned and
    weights early tokens heavily; paired with the nudity-graded negative it makes
    the requested nudity level actually stick instead of defaulting to nude.

    Returns (positive, negative, locked_block).
    """
    if shot is None:
        shot = ShotOptions()
    scaffold = ap.phrase(ap.STYLE_PHRASES, persona.style, ap.STYLE_PHRASES["realistic"])
    shot_block = cv.compose_shot_block(shot, personality=persona.personality)
    locked = identity_block(persona)
    clothing = ov.generation_outfit_clause(outfit, nudity_level, accessories)
    flavor = _persona_flavor(persona, suppress_expression=shot.expression is not None)

    parts = [scaffold, shot_block, locked]
    if clothing:
        parts.append(clothing)
    if flavor:
        parts.append(flavor)
    if free_text and free_text.strip():
        parts.append(free_text.strip())  # admin free-text, always verbatim
    # Short suffix: "masterpiece/best quality" are SD1.5-era tags wasted on
    # Z-Image; "sharp focus" lives in the scaffold; lighting/polish language is
    # owned by the workflow-side photo-style wrapper (node 125).
    parts.append("highly detailed, natural skin texture")

    positive = ", ".join(p for p in parts if p)
    negative = pc.generation_negative(nudity_level=nudity_level)
    return positive, negative, locked


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def verify_locked(text: str, tokens: List[str]) -> bool:
    """True if every locked token appears (normalized substring) in text."""
    norm = _normalize(text)
    for tok in tokens:
        if _normalize(tok) not in norm:
            return False
    return True


# Curated, distinctive search tokens per attribute family. Keyed by the same enum
# value used in attribute_phrases; the value is the word/phrase to look for with a
# word-boundary regex. Deliberately narrow to avoid false positives (e.g. "red"
# would collide with "red dress", so redhead is searched as "redhead").
_HAIR_COLOR_TOKENS = {
    "brunette": ["brunette"],
    "blonde": ["blonde", "blond"],
    "black": ["black"],
    "redhead": ["redhead", "red hair", "auburn", "ginger"],
    "pink": ["pink hair"],
}
_EYE_COLOR_TOKENS = {
    # Searched with the noun to avoid colliding with clothing/scene colors.
    "brown": ["brown eyes"],
    "blue": ["blue eyes"],
    "green": ["green eyes"],
}
_ETHNICITY_TOKENS = {
    "caucasian": ["caucasian"],
    "asian": ["asian"],
    "black_afro": ["black woman", "afro"],
    "latina": ["latina", "hispanic"],
    "arab": ["arab", "middle eastern"],
}

# Hair-color and ethnicity both legitimately produce the word "black" (black hair
# vs a Black woman). We only treat a bare "black" as a hair-color contradiction
# when NEITHER the requested hair color NOR the requested ethnicity is a black
# variant. These are the enum values that make "black" legitimate.
_BLACK_HAIR_VALUE = "black"
_BLACK_ETHNICITY_VALUE = "black_afro"

# bodyType / breastSize are intentionally NOT scanned in v1: their phrases use
# common adjectives (slim, average, small, medium, large, full) that collide
# constantly with unrelated scene/lighting words, so scanning them would produce
# frequent false positives and reject good polishes.


def _contains_word(norm_text: str, needle: str) -> bool:
    """Word-boundary containment on already-normalized text."""
    return re.search(r"\b" + re.escape(needle) + r"\b", norm_text) is not None


def has_contradiction(text: str, persona: PersonaOptions) -> bool:
    """
    True if ``text`` mentions a distinctive hair-color, eye-color, or ethnicity
    attribute that CONFLICTS with the persona's requested value (a sibling value
    the admin did not select). Used to reject a Venice scene that invented or
    swapped a physical attribute.

    The requested value is always skipped (it is expected to appear). The shared
    "black" hair/ethnicity token is only treated as a contradiction when neither
    the requested hair color nor the requested ethnicity is a black variant.
    """
    norm = _normalize(text)

    requested_hair = ap._val(getattr(persona, "hairColor", None))
    requested_eye = ap._val(getattr(persona, "eyeColor", None))
    requested_ethnicity = ap._val(getattr(persona, "ethnicity", None))

    black_is_legit = (
        requested_hair == _BLACK_HAIR_VALUE
        or requested_ethnicity == _BLACK_ETHNICITY_VALUE
    )

    # Hair color: any sibling color present that was not requested.
    for value, needles in _HAIR_COLOR_TOKENS.items():
        if value == requested_hair:
            continue
        if value == _BLACK_HAIR_VALUE and black_is_legit:
            continue
        if any(_contains_word(norm, n) for n in needles):
            return True

    # Eye color: any sibling eye color present that was not requested.
    for value, needles in _EYE_COLOR_TOKENS.items():
        if value == requested_eye:
            continue
        if any(_contains_word(norm, n) for n in needles):
            return True

    # Ethnicity: any sibling ethnicity present that was not requested.
    for value, needles in _ETHNICITY_TOKENS.items():
        if value == requested_ethnicity:
            continue
        if value == _BLACK_ETHNICITY_VALUE and black_is_legit:
            continue
        if any(_contains_word(norm, n) for n in needles):
            return True

    return False


class PromptGenerator:
    """Generates image prompts: deterministic identity/framing assembly + an
    optional Venice-written scene clause."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "venice-uncensored",
        timeout: float = 100.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    async def generate_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None,
        is_enhance: bool = True,
        shot: Optional[ShotOptions] = None,
        outfit: Optional[OutfitType] = None,
        nudity_level: NudityLevel = NudityLevel.LOW,
        accessories: Optional[List[AccessoryType]] = None,
    ) -> Tuple[str, Optional[dict]]:
        """
        Backward-compatible entry point: returns (positive_prompt, token_usage).
        token_usage is None when the deterministic prompt is used (no Venice call).
        """
        positive, _negative, _locked, usage = await self.generate_generation_prompt(
            persona, context, is_enhance, shot=shot,
            outfit=outfit, nudity_level=nudity_level, accessories=accessories,
        )
        return positive, usage

    async def generate_generation_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None,
        is_enhance: bool = True,
        shot: Optional[ShotOptions] = None,
        outfit: Optional[OutfitType] = None,
        nudity_level: NudityLevel = NudityLevel.LOW,
        accessories: Optional[List[AccessoryType]] = None,
    ) -> Tuple[str, str, str, Optional[dict]]:
        """
        Full character-generation prompt builder.

        Identity + framing + clothing are assembled deterministically (always
        present). When enabled, Venice writes the scene clause from the persona
        vibe + user hint and it takes the place of the raw free-text; otherwise
        (or on rejection) the raw hint is used verbatim.
        Returns (positive, negative, locked_block, token_usage).
        """
        if shot is None:
            shot = ShotOptions()

        scene_clause = context  # default: the raw user hint (or None)
        usage = None
        if is_enhance and self._client.enabled:
            flavor = _persona_flavor(persona, suppress_expression=shot.expression is not None)
            clothing = ov.generation_outfit_clause(outfit, nudity_level, accessories)
            written, usage = await self._write_scene(persona, context, flavor, clothing)
            if written is not None:
                scene_clause = written
            else:
                logger.warning(f"Venice scene unavailable/rejected for '{persona.name}'; using raw hint")
        else:
            logger.info(f"Using deterministic prompt for '{persona.name}' (enhance={is_enhance})")

        positive, negative, locked = assemble_generation_prompt(
            persona, scene_clause, shot=shot,
            outfit=outfit, nudity_level=nudity_level, accessories=accessories,
        )
        return positive, negative, locked, usage

    async def _write_scene(
        self,
        persona: PersonaOptions,
        context: Optional[str],
        flavor: str,
        clothing: str,
    ) -> Tuple[Optional[str], Optional[dict]]:
        """Write a scene clause with Venice. Returns (scene, usage). scene is None on
        failure or when the clause invents a contradicting physical attribute / runs
        long, so the caller falls back to the raw user hint."""
        hint = (context or "").strip() or "(none — invent a fitting scene for the persona)"
        user_prompt = (
            f"PERSONA SUMMARY:\n{flavor or 'unspecified vibe'}\n\n"
            f"CLOTHING/NUDITY CONTEXT:\n{clothing or 'as-is'}\n\n"
            f"USER HINT:\n{hint}"
        )
        content, raw_usage = await self._client.chat(
            [
                {"role": "system", "content": SCENE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=400,
        )
        usage = self._account_usage(raw_usage) if raw_usage else None
        if content is None:
            return None, usage

        if has_contradiction(content, persona):
            logger.warning("Venice scene introduced a contradicting physical attribute; falling back to raw hint")
            return None, usage

        if len(content.split()) > MAX_SCENE_WORDS:
            logger.warning(
                f"Venice scene over length budget "
                f"({len(content.split())} > {MAX_SCENE_WORDS} words); falling back to raw hint"
            )
            return None, usage

        logger.info(f"Venice scene accepted: {len(content)} chars")
        return content, usage

    def _account_usage(self, usage: dict) -> dict:
        """Compute token counts + cost from a chat-completions usage object."""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)

        pricing = VENICE_PRICING.get(self.model, {"input": 0, "cached": 0, "output": 0})
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]
        output_cost = ((completion_tokens + reasoning_tokens) / 1_000_000) * pricing["output"]
        total_cost = input_cost + cached_cost + output_cost

        logger.info(
            f"[Venice] {self.model} | prompt:{prompt_tokens} (cached:{cached_tokens}) "
            f"completion:{completion_tokens} reasoning:{reasoning_tokens} | ${total_cost:.6f}"
        )
        return {
            "model": self.model,
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
            "input_cost": input_cost,
            "cached_cost": cached_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
        }

    def build_fallback_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None,
        shot: Optional[ShotOptions] = None,
        outfit: Optional[OutfitType] = None,
        nudity_level: NudityLevel = NudityLevel.LOW,
        accessories: Optional[List[AccessoryType]] = None,
    ) -> str:
        """Deterministic prompt (kept for callers that want the no-model path explicitly)."""
        positive, _negative, _locked = assemble_generation_prompt(
            persona, context, shot=shot,
            outfit=outfit, nudity_level=nudity_level, accessories=accessories,
        )
        return positive
