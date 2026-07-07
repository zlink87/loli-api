"""
Prompt generation service.

Prompts are assembled DETERMINISTICALLY from the admin's selected attributes (enums)
plus any free-text the admin writes. xAI Grok is demoted to an optional *polisher*
that may improve fluency/scene detail but is FORBIDDEN from changing the locked
identity attributes — its output is verified and discarded if any locked token is lost.
This guarantees the admin's selections and free-text always survive, and that a Grok
outage / isEnhance=False still yields a complete, identity-faithful, quality-scaffolded
prompt.
"""
import httpx
import logging
import re
from typing import List, Optional, Tuple

from models.requests import PersonaOptions, ShotOptions
from services import attribute_phrases as ap
from services import camera_vocab as cv
from services import prompt_constants as pc

logger = logging.getLogger(__name__)

# Hard cap on polished-prompt length. Z-Image Turbo is a fast turbo diffusion
# model that prefers short prompts; a polish that runs over this is rejected in
# favor of the deterministic draft (never mid-sentence truncated).
MAX_POLISHED_WORDS = 110

# xAI Grok pricing per 1M tokens (USD): {"model": {"input", "cached", "output"}}
GROK_PRICING = {
    "grok-4-1-fast-reasoning": {"input": 0.20, "cached": 0.05, "output": 0.50},
    "grok-4-1-fast-non-reasoning": {"input": 0.20, "cached": 0.05, "output": 0.50},
    "grok-4-fast-reasoning": {"input": 0.20, "cached": 0.05, "output": 0.50},
    "grok-4-fast-non-reasoning": {"input": 0.20, "cached": 0.05, "output": 0.50},
    "grok-4-0709": {"input": 3.00, "cached": 0.75, "output": 15.00},
    "grok-code-fast-1": {"input": 0.20, "cached": 0.02, "output": 1.50},
    "grok-3": {"input": 3.00, "cached": 0.75, "output": 15.00},
    "grok-3-mini": {"input": 0.30, "cached": 0.075, "output": 0.50},
}

# Grok is a POLISHER ONLY. It receives a FRAMING BLOCK + LOCKED BLOCK + DRAFT and
# must reproduce every framing and locked token verbatim. It must not invent or
# change identity attributes, nor introduce its own framing/camera language —
# that freedom was the root cause of inconsistent hero-shot crops.
POLISH_SYSTEM_PROMPT = '''You are a prompt editor for a photorealistic NSFW image generator.
You will be given a FRAMING BLOCK (immutable shot framing), a LOCKED BLOCK (immutable identity facts) and a DRAFT prompt.

Your job: rewrite the DRAFT into one fluent, vivid, concrete visual prompt for a diffusion model.

HARD RULES:
- Reproduce EVERY phrase in the FRAMING BLOCK verbatim, near the START of the prompt. Do NOT change or restate the shot framing, crop, camera angle, or subject orientation.
- Reproduce EVERY phrase in the LOCKED BLOCK verbatim. Do NOT change ethnicity, age, skin tone, hair style, hair color, eye color, body type, or breast size.
- Keep any user free-text intent (scene, mood, setting). Do not contradict it.
- Be objective and concrete. No metaphors. No negative phrasing (describe only what IS present).
- You may embellish ONLY lighting, mood, wardrobe/scene details, and atmosphere. Do NOT add or alter any physical attribute, and do NOT introduce any framing, crop, or camera language beyond the FRAMING BLOCK.
- Target 40-90 words. Be concise; this is for a fast turbo diffusion model that prefers short prompts.

OUTPUT: only the final prompt text. No preamble, no analysis, no quotes.
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
) -> Tuple[str, str, str]:
    """
    Deterministically assemble a character-generation prompt.

    Assembly order: scaffold, shot block (framing+angle+expression), locked
    identity, persona flavor, free text, quality suffix. shot=None falls back
    to hero defaults (waist-up, eye level) so every caller gets a consistent crop.

    Returns (positive, negative, locked_block).
    """
    if shot is None:
        shot = ShotOptions()
    scaffold = ap.phrase(ap.STYLE_PHRASES, persona.style, ap.STYLE_PHRASES["realistic"])
    shot_block = cv.compose_shot_block(shot, personality=persona.personality)
    locked = identity_block(persona)
    flavor = _persona_flavor(persona, suppress_expression=shot.expression is not None)

    parts = [scaffold, shot_block, locked]
    if flavor:
        parts.append(flavor)
    if free_text and free_text.strip():
        parts.append(free_text.strip())  # admin free-text, always verbatim
    # Short suffix: "masterpiece/best quality" are SD1.5-era tags wasted on
    # Z-Image; "sharp focus" lives in the scaffold; lighting/polish language is
    # owned by the workflow-side photo-style wrapper (node 125).
    parts.append("highly detailed, natural skin texture")

    positive = ", ".join(p for p in parts if p)
    negative = pc.generation_negative()
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
    the admin did not select). Used to reject a Grok polish that invented or
    swapped a physical attribute even while keeping the locked tokens present.

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
    """Generates image prompts: deterministic assembly + optional verified Grok polish."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        model: str = "grok-3-mini",
        timeout: float = 100.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def generate_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None,
        is_enhance: bool = True,
        shot: Optional[ShotOptions] = None,
    ) -> Tuple[str, Optional[dict]]:
        """
        Backward-compatible entry point: returns (positive_prompt, token_usage).
        token_usage is None when the deterministic prompt is used (no Grok call).
        """
        positive, _negative, _locked, usage = await self.generate_generation_prompt(
            persona, context, is_enhance, shot=shot
        )
        return positive, usage

    async def generate_generation_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None,
        is_enhance: bool = True,
        shot: Optional[ShotOptions] = None,
    ) -> Tuple[str, str, str, Optional[dict]]:
        """
        Full character-generation prompt builder.
        Returns (positive, negative, locked_block, token_usage).
        """
        if shot is None:
            shot = ShotOptions()
        positive, negative, locked = assemble_generation_prompt(persona, context, shot=shot)
        tokens = locked_tokens(persona)
        f_tokens = cv.framing_tokens(shot)

        if not is_enhance or not self.api_key:
            logger.info(f"Using deterministic prompt for '{persona.name}' (enhance={is_enhance})")
            return positive, negative, locked, None

        polished, usage = await self._polish_with_grok(
            positive, locked, tokens, persona,
            framing_block=", ".join(f_tokens), framing_tokens_list=f_tokens,
        )
        if polished is None:
            logger.warning(f"Grok polish unavailable/failed for '{persona.name}'; using deterministic")
            return positive, negative, locked, None

        return polished, negative, locked, usage

    async def _polish_with_grok(
        self,
        draft: str,
        locked_block: str,
        tokens: List[str],
        persona: PersonaOptions,
        framing_block: str = "",
        framing_tokens_list: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], Optional[dict]]:
        """Polish a draft with Grok, verifying the framing and locked blocks
        survived. None on failure (caller falls back to the deterministic draft,
        which always contains both blocks)."""
        user_prompt = (
            f"FRAMING BLOCK:\n{framing_block}\n\nLOCKED BLOCK:\n{locked_block}\n\nDRAFT:\n{draft}"
        )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": POLISH_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.35,
                        "max_tokens": 1500,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                result = response.json()
                usage = self._account_usage(result.get("usage", {}))
                content = result["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError) as e:
            logger.error(f"Grok polish HTTP error: {e}")
            return None, None
        except (KeyError, IndexError) as e:
            logger.error(f"Grok polish parse error: {e}")
            return None, None
        except Exception as e:  # noqa: BLE001 - never let polishing break generation
            logger.error(f"Grok polish error: {e}")
            return None, None

        if not verify_locked(content, tokens):
            logger.warning("Grok polish dropped a locked identity token; rejecting polished output")
            return None, usage

        if framing_tokens_list and not verify_locked(content, framing_tokens_list):
            logger.warning("Grok polish dropped a framing/angle token; rejecting polished output")
            return None, usage

        if has_contradiction(content, persona):
            logger.warning("Grok polish introduced a contradicting physical attribute; rejecting polished output")
            return None, usage

        if len(content.split()) > MAX_POLISHED_WORDS:
            logger.warning(
                f"Grok polish over length budget "
                f"({len(content.split())} > {MAX_POLISHED_WORDS} words); rejecting polished output"
            )
            return None, usage

        logger.info(f"Grok polish accepted: {len(content)} chars")
        return content, usage

    def _account_usage(self, usage: dict) -> dict:
        """Compute token counts + cost from a chat-completions usage object."""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)

        pricing = GROK_PRICING.get(self.model, {"input": 0, "cached": 0, "output": 0})
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]
        output_cost = ((completion_tokens + reasoning_tokens) / 1_000_000) * pricing["output"]
        total_cost = input_cost + cached_cost + output_cost

        logger.info(
            f"[Grok] {self.model} | prompt:{prompt_tokens} (cached:{cached_tokens}) "
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
    ) -> str:
        """Deterministic prompt (kept for callers that want the no-model path explicitly)."""
        positive, _negative, _locked = assemble_generation_prompt(persona, context, shot=shot)
        return positive
