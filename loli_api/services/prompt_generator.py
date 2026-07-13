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
import random
import re
from typing import List, Optional, Tuple

from models.requests import PersonaOptions, ShotOptions
from models.enums import NudityLevel, OutfitType, AccessoryType
from services import attribute_phrases as ap
from services import camera_vocab as cv
from services import prompt_constants as pc
from services import outfit_vocab as ov
from services import culture_vocab as cvoc

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


def _persona_flavor(
    persona: PersonaOptions,
    suppress_expression: bool = False,
    nudity_level: NudityLevel = NudityLevel.LOW,
) -> str:
    """Persona flavor phrases. suppress_expression drops the personality's
    expression phrase when an explicit shot expression override is set (avoids
    two conflicting expression clauses).

    At modest nudity (LOW/SUGGESTIVE) the kink mood phrase is dropped: those
    heated, undress-pulling moods fight the graded clothing with nothing to
    oppose them at cfg=1 (the negative is inert), so on a clothed card they only
    muddy the aesthetic. Personality/occupation/relationship still express. At
    MEDIUM+ the kink mood stays (today's behavior)."""
    key = getattr(nudity_level, "value", nudity_level)
    drop_kinks = key in ("low", "suggestive")
    parts = [
        "" if suppress_expression else ap.phrase(ap.PERSONALITY_PHRASES, persona.personality),
        ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation),
        ap.phrase(ap.RELATIONSHIP_PHRASES, persona.relationship),
        "" if drop_kinks else ap.kinks_phrase(persona.kinks),
    ]
    return ", ".join(p for p in parts if p)


def assemble_generation_prompt(
    persona: PersonaOptions,
    free_text: Optional[str] = None,
    shot: Optional[ShotOptions] = None,
    outfit: Optional[OutfitType] = None,
    nudity_level: NudityLevel = NudityLevel.LOW,
    accessories: Optional[List[AccessoryType]] = None,
    variety_seed: Optional[int] = None,
    pose_text: Optional[str] = None,
    wardrobe_styles=None,
    demeanor=None,
) -> Tuple[str, str, str]:
    """
    Deterministically assemble a character-generation prompt.

    Assembly order: scaffold, shot block (framing+angle+expression), locked
    identity, culture styling clause, clothing clause, body-position phrase,
    scene/free text, persona flavor, quality suffix.

    Variety (WS3) is controlled entirely by ``variety_seed``:
      * None -> the legacy behavior exactly: the plain hero-default shot
        (waist-up, eye level) when no explicit shot is given, the single default
        clothing string, and no body-position phrase. This is the kill-switch path.
      * set  -> a LOCAL random.Random(variety_seed) drives a seeded varied shot
        (only when no explicit shot AND no pose_text override), a seeded default
        clothing pick, and a seeded body-position phrase — so batch items (distinct
        seeds) differ while each seed stays reproducible.
    ``pose_text``, when given, is used verbatim as the body-position phrase in
    place of any pool pick (and suppresses the seeded shot rotation).

    ``wardrobe_styles``/``demeanor`` (WS-B / B3, a character's trait profile) are
    soft pass-throughs: wardrobe_styles narrows the seeded default-clothing pool to
    her styles (only on the no-explicit-outfit variety path), and demeanor swaps the
    seeded expression pool toward her personality (only on the synthesized-shot
    path). Both default None and are then byte-identical to the pre-WS-B behavior —
    they never change the rng draw order/count, so seeded tests are unaffected.

    ``persona.culture`` (optional subculture) rides ON the persona. It does two
    fill-only things, both draw-count-invariant: (1) when the caller left
    ``wardrobe_styles``/``demeanor`` unset it derives them from the culture (an
    explicit value always wins), so the seeded pools shift CONTENTS only, never the
    rng order/count; and (2) its makeup/styling render phrase is inserted right after
    the locked identity block and before the clothing clause. It never enters
    ``locked``/``identity_block`` — the locked return value and verify contract stay
    byte-identical. A None/unknown culture is a full no-op (byte-identical output).

    The scene clause (the admin's raw text, used verbatim) sits after the
    clothing/body-position clauses and BEFORE persona flavor deliberately: the
    generation model is a fast turbo model that weights earlier tokens heavily,
    and the requested scene (e.g. "school dance") must not be buried behind flavor
    text or it gets diluted.

    Nudity level is enforced entirely by POSITIVE tokens — the graded clothing
    clause, the LOW/SUGGESTIVE coverage guard, and the flavor gating that drops
    kink moods at modest levels — because the generation graph samples at cfg=1,
    where the negative prompt is mathematically inert (it is retained for
    provenance/parity but subtracts nothing). The clothing clause is injected
    early (right after locked identity) because the NSFW-tuned base weights early
    tokens heavily.

    Returns (positive, negative, locked_block).
    """
    rng = random.Random(variety_seed) if variety_seed is not None else None
    pose_override = bool(pose_text and pose_text.strip())

    # Culture (an optional persona dimension) FILLS wardrobe_styles / demeanor only
    # when the caller left them unset — an explicit value always wins. This runs
    # BEFORE the shot synthesis below so the derived demeanor steers the seeded
    # expression pool. Draw-count-invariant: varied_shot_fields / _wardrobe_filter_pool
    # only shift POOL CONTENTS (never the rng draw order/count), so a None/unknown
    # culture leaves both derivations empty and the output byte-identical.
    culture = getattr(persona, "culture", None)
    if not wardrobe_styles:
        derived_ws = list(cvoc.culture_wardrobe_styles(culture))
        if derived_ws:
            wardrobe_styles = derived_ws
    if demeanor is None:
        derived_demeanor = cvoc.culture_demeanor(culture)
        if derived_demeanor:
            demeanor = derived_demeanor[0]

    # Shot: an explicit client shot always wins. With variety on and no pose_text
    # override, synthesize a seeded varied shot; otherwise the plain hero default.
    if shot is None:
        if rng is not None and not pose_override:
            shot = ShotOptions(**cv.varied_shot_fields(rng, demeanor=demeanor))
        else:
            shot = ShotOptions()

    scaffold = ap.phrase(ap.STYLE_PHRASES, persona.style, ap.STYLE_PHRASES["realistic"])
    shot_block = cv.compose_shot_block(shot, personality=persona.personality)
    locked = identity_block(persona)
    clothing = ov.generation_outfit_clause(
        outfit, nudity_level, accessories, variety_seed=variety_seed,
        wardrobe_styles=wardrobe_styles,
    )
    flavor = _persona_flavor(
        persona,
        suppress_expression=shot.expression is not None,
        nudity_level=nudity_level,
    )

    # Body-position segment: explicit pose_text wins (verbatim); else a seeded
    # pool pick when variety is on; else nothing (legacy).
    if pose_override:
        pose_segment = pose_text.strip()
    elif rng is not None:
        pose_segment = cv.pose_variety_phrase(rng)
    else:
        pose_segment = ""

    # Culture styling (makeup/jewelry render phrase) sits right after the locked
    # identity block and before the clothing clause — NEVER inside locked_tokens()/
    # identity_block(), so the `locked` return value + verify contract stay identical.
    culture_styling = cvoc.culture_render_phrase(culture)

    parts = [scaffold, shot_block, locked]
    if culture_styling:
        parts.append(culture_styling)
    if clothing:
        parts.append(clothing)
    if pose_segment:
        parts.append(pose_segment)
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
        variety_seed: Optional[int] = None,
        pose_text: Optional[str] = None,
        wardrobe_styles=None,
        demeanor=None,
    ) -> Tuple[str, str, str]:
        """
        Full character-generation prompt builder.

        Identity + framing + clothing are assembled deterministically (always
        present); `context` (the admin's scene hint) is used verbatim. The RAW
        `shot` (may be None) is threaded straight through so assembly owns the
        fallback — never defaulted here, or the seeded shot rotation could never
        engage. `variety_seed`/`pose_text` drive WS3 variety (see
        assemble_generation_prompt). `wardrobe_styles`/`demeanor` (WS-B / B3) soft-
        bias the seeded clothing pool / expression pool; both default None =
        byte-identical. Returns (positive, negative, locked_block).
        """
        return assemble_generation_prompt(
            persona, context, shot=shot,
            outfit=outfit, nudity_level=nudity_level, accessories=accessories,
            variety_seed=variety_seed, pose_text=pose_text,
            wardrobe_styles=wardrobe_styles, demeanor=demeanor,
        )
