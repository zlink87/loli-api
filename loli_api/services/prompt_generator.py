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

from models.requests import PersonaOptions
from services import attribute_phrases as ap
from services import prompt_constants as pc

logger = logging.getLogger(__name__)

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

# Grok is a POLISHER ONLY. It receives a LOCKED BLOCK + a DRAFT and must reproduce
# every locked token verbatim. It must not invent or change identity attributes.
POLISH_SYSTEM_PROMPT = '''You are a prompt editor for a photorealistic NSFW image generator.
You will be given a LOCKED BLOCK (immutable identity facts) and a DRAFT prompt.

Your job: rewrite the DRAFT into one fluent, vivid, concrete visual prompt for a diffusion model.

HARD RULES:
- Reproduce EVERY phrase in the LOCKED BLOCK verbatim. Do NOT change ethnicity, age, skin tone, hair style, hair color, eye color, body type, or breast size.
- Keep any user free-text intent (scene, mood, setting). Do not contradict it.
- Be objective and concrete. No metaphors. No negative phrasing (describe only what IS present).
- Add tasteful photographic detail: shot/lens, soft warm lighting, natural skin texture, beautiful composition.
- Target 120-220 words.

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


def _persona_flavor(persona: PersonaOptions) -> str:
    parts = [
        ap.phrase(ap.PERSONALITY_PHRASES, persona.personality),
        ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation),
        ap.phrase(ap.RELATIONSHIP_PHRASES, persona.relationship),
        ap.kinks_phrase(persona.kinks),
    ]
    return ", ".join(p for p in parts if p)


def assemble_generation_prompt(
    persona: PersonaOptions,
    free_text: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Deterministically assemble a character-generation prompt.

    Returns (positive, negative, locked_block).
    """
    scaffold = ap.phrase(ap.STYLE_PHRASES, persona.style, ap.STYLE_PHRASES["realistic"])
    locked = identity_block(persona)
    flavor = _persona_flavor(persona)

    parts = [scaffold, locked]
    if flavor:
        parts.append(flavor)
    if free_text and free_text.strip():
        parts.append(free_text.strip())  # admin free-text, always verbatim
    parts.append("masterpiece, best quality, highly detailed, sharp focus, natural skin texture")

    positive = ", ".join(p for p in parts if p)
    negative = pc.generation_negative()
    return positive, negative, locked


def assemble_edit_prompt(
    descriptor: str,
    what: str,
    free_text: Optional[str] = None,
    extra_negative: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Deterministically assemble an edit prompt (outfit/pose/background).

    Args:
        descriptor: The edit instruction (e.g. the outfit/pose/scene text).
        what: What is being changed, for the identity clause (e.g. "the clothing").
        free_text: Optional admin free-text, appended verbatim.
        extra_negative: Optional extra negative (e.g. admin negativePrompt).

    Returns (positive, negative).
    """
    parts = [descriptor.strip()] if descriptor else []
    if free_text and free_text.strip():
        parts.append(free_text.strip())
    parts.append(pc.identity_clause(what))
    positive = ", ".join(p for p in parts if p)
    negative = pc.edit_negative(extra_negative)
    return positive, negative


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def verify_locked(text: str, tokens: List[str]) -> bool:
    """True if every locked token appears (normalized substring) in text."""
    norm = _normalize(text)
    for tok in tokens:
        if _normalize(tok) not in norm:
            return False
    return True


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
    ) -> Tuple[str, Optional[dict]]:
        """
        Backward-compatible entry point: returns (positive_prompt, token_usage).
        token_usage is None when the deterministic prompt is used (no Grok call).
        """
        positive, _negative, _locked, usage = await self.generate_generation_prompt(
            persona, context, is_enhance
        )
        return positive, usage

    async def generate_generation_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None,
        is_enhance: bool = True,
    ) -> Tuple[str, str, str, Optional[dict]]:
        """
        Full character-generation prompt builder.
        Returns (positive, negative, locked_block, token_usage).
        """
        positive, negative, locked = assemble_generation_prompt(persona, context)
        tokens = locked_tokens(persona)

        if not is_enhance or not self.api_key:
            logger.info(f"Using deterministic prompt for '{persona.name}' (enhance={is_enhance})")
            return positive, negative, locked, None

        polished, usage = await self._polish_with_grok(positive, locked, tokens)
        if polished is None:
            logger.warning(f"Grok polish unavailable/failed for '{persona.name}'; using deterministic")
            return positive, negative, locked, None

        return polished, negative, locked, usage

    async def _polish_with_grok(
        self,
        draft: str,
        locked_block: str,
        tokens: List[str],
    ) -> Tuple[Optional[str], Optional[dict]]:
        """Polish a draft with Grok, verifying the locked block survived. None on failure."""
        user_prompt = f"LOCKED BLOCK:\n{locked_block}\n\nDRAFT:\n{draft}"
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
    ) -> str:
        """Deterministic prompt (kept for callers that want the no-model path explicitly)."""
        positive, _negative, _locked = assemble_generation_prompt(persona, context)
        return positive
