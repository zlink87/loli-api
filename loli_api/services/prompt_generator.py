"""
Prompt generation service.

Character-generation prompts are assembled DETERMINISTICALLY from the admin's
selected attributes (enums) plus their raw scene text, verbatim — no LLM sits
between the admin's input and the rendered prompt. (Story batches are a
separate feature and still use Venice to plan scenes; see services/story_planner.py.)

This used to also have an LLM ("Venice") rewrite the scene text before assembly
("Enhance Quality" / isEnhance). That step was removed 2026-07-08: it reliably
dropped or replaced explicit user scene requests (e.g. a "school dance" hint
would sometimes come back as a generic studio-portrait scene), which is exactly
the kind of unpredictability the deterministic assembler exists to avoid.
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic assembly (no model in the loop for identity OR scene)
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
    identity, clothing clause, scene/free text, persona flavor, quality suffix.
    shot=None falls back to hero defaults (waist-up, eye level) so every caller
    gets a consistent crop.

    The scene clause (the admin's raw text, used verbatim) sits right after
    clothing and BEFORE persona flavor (personality/occupation/kinks phrases)
    deliberately: the generation model is a fast turbo model that weights
    earlier tokens heavily, and the requested scene (e.g. "school dance") must
    not be buried behind flavor text or it gets diluted.

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
    if free_text and free_text.strip():
        parts.append(free_text.strip())  # admin free-text, always verbatim
    if flavor:
        parts.append(flavor)
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


class PromptGenerator:
    """Deterministically assembles character-generation prompts from persona
    enums, outfit/nudity selection, and an optional raw scene hint (used
    verbatim — no LLM rewriting)."""

    async def generate_generation_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None,
        shot: Optional[ShotOptions] = None,
        outfit: Optional[OutfitType] = None,
        nudity_level: NudityLevel = NudityLevel.LOW,
        accessories: Optional[List[AccessoryType]] = None,
    ) -> Tuple[str, str, str]:
        """
        Full character-generation prompt builder.

        Identity + framing + clothing are assembled deterministically (always
        present); `context` (the admin's scene hint) is used verbatim.
        Returns (positive, negative, locked_block).
        """
        if shot is None:
            shot = ShotOptions()
        return assemble_generation_prompt(
            persona, context, shot=shot,
            outfit=outfit, nudity_level=nudity_level, accessories=accessories,
        )
