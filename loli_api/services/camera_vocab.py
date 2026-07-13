"""
Camera / shot vocabulary for hero-shot generation.

Framing, camera-angle and expression enums are mapped to short photographic
phrases and composed into the generation prompt's "shot block". This lives in
its own module (mirroring scene_vocab.py) so the camera vocabulary is
self-contained.

These phrases describe ONLY camera/framing/expression — never identity.
Framing + angle phrases are assembled deterministically (they are never produced
by the LLM, exactly like the locked identity tokens); the LLM-written scene must
not introduce any camera/framing language of its own.
"""
from typing import List, Optional

from models.enums import DemeanorType
from services.attribute_phrases import phrase


# One entry for EVERY ShotFramingType / CameraAngleType / ExpressionType value
# (coverage is enforced by tests).
FRAMING_PHRASES = {
    "portrait_closeup": "close-up portrait, head and shoulders in frame",
    "chest_up": "chest-up portrait",
    "waist_up": "waist-up portrait",
    "three_quarter": "three-quarter shot from the knees up",
    "full_body": "full-body shot, whole figure in frame",
    "selfie": "selfie-style photo taken at arm's length",
}

CAMERA_ANGLE_PHRASES = {
    "eye_level": "shot at eye level, facing the camera, centered composition",
    "high_angle": "shot from a high angle looking down at her",
    "low_angle": "shot from a low angle looking up at her",
    "three_quarter_view": "body turned in three-quarter view toward the camera",
    "side_profile": "side profile view",
}

EXPRESSION_PHRASES = {
    "soft_smile": "a soft pleasant smile",
    "neutral": "a calm relaxed expression",
    "playful": "a playful teasing expression",
    "seductive": "a sultry seductive gaze",
    "confident": "a confident self-assured expression",
    "laughing": "a bright genuine laugh",
}

# Scene-time phrases for the generation prompt. Deliberately assertive ("scene
# set ...") because the base model has a strong daylight bias — these are
# VERIFIED tokens (part of framing_tokens) so the polisher can never drop them,
# and the photo-style wrapper switches to a matching grade (prompt_constants).
TIME_OF_DAY_PHRASES = {
    "early_morning": "scene set in the dim quiet of early morning",
    "morning": "scene set in fresh morning light",
    "daytime": "scene set in bright daytime",
    "golden_hour": "scene set during golden hour",
    "sunset": "scene set at sunset",
    "evening": "scene set in the evening after dark",
    "night": "scene set at night, dark nighttime environment",
}

LIGHTING_PHRASES = {
    "natural_soft": "soft natural light",
    "bright_daylight": "bright daylight",
    "golden_warm": "warm golden light",
    "moody_dim": "moody dim lighting",
    "neon": "vivid neon lighting",
    "candlelit": "warm candlelight",
    "studio_softbox": "studio softbox lighting",
    "backlit_rim": "backlit with a soft rim light",
    "overcast": "soft overcast light",
}


# ---------------------------------------------------------------------------
# WS3 seeded shot/pose variety.
#
# When character-generation variety is ON (a variety_seed is threaded into the
# assembler) and the caller sent no explicit shot, the assembler synthesizes a
# varied shot and appends a body-position phrase from these pools instead of the
# single hero default — so a batch of cards stops looking identical. Values reuse
# the EXISTING phrase tables above; repetition in the framing/angle pools encodes
# weighting (keep the rotation coherent: mostly waist_up/chest_up at eye level,
# with occasional wider crops / turned angles). Phrases describe camera + stance
# ONLY — never identity, outfit, or scene — so they compose with any locked block.
# ---------------------------------------------------------------------------
_FRAMING_VARIETY_POOL = [
    "waist_up", "waist_up", "waist_up",
    "chest_up", "chest_up",
    "portrait_closeup",
    "three_quarter",
    "full_body",
]
_CAMERA_ANGLE_VARIETY_POOL = [
    "eye_level", "eye_level", "eye_level", "eye_level",
    "three_quarter_view", "three_quarter_view",
    "side_profile",
    "high_angle",
    "low_angle",
]
_EXPRESSION_VARIETY_POOL = [
    "soft_smile", "neutral", "playful", "seductive", "confident", "laughing",
]

# WS-B trait profiles: a character's demeanor swaps the default expression pool
# above for one weighted toward her personality, so a shy character reads gentle
# and a sultry one reads sultry across a batch — without touching the rng draw
# ORDER (framing, angle, expression) that varied_shot_fields consumes, so seeded
# tests stay byte-identical when demeanor is None. Values are EXISTING
# ExpressionType keys (EXPRESSION_PHRASES above); repetition encodes weighting.
# One entry per DemeanorType (coverage enforced by tests).
DEMEANOR_EXPRESSION_POOLS = {
    DemeanorType.SHY: ["soft_smile", "soft_smile", "soft_smile", "neutral", "neutral", "playful"],
    DemeanorType.CONFIDENT: ["confident", "confident", "confident", "soft_smile", "soft_smile", "seductive"],
    DemeanorType.PLAYFUL: ["playful", "playful", "playful", "laughing", "laughing", "soft_smile"],
    DemeanorType.SULTRY: ["seductive", "seductive", "seductive", "confident", "confident", "neutral"],
    DemeanorType.ELEGANT: ["soft_smile", "soft_smile", "neutral", "neutral", "confident", "seductive"],
    DemeanorType.ENERGETIC: ["laughing", "laughing", "laughing", "playful", "playful", "soft_smile"],
    DemeanorType.COZY: ["soft_smile", "soft_smile", "soft_smile", "neutral", "laughing", "playful"],
    DemeanorType.MYSTERIOUS: ["neutral", "neutral", "neutral", "seductive", "seductive", "soft_smile"],
}

POSE_VARIETY_PHRASES = [
    "standing with her weight on one hip, one hand in her pocket",
    "seated, leaning slightly toward the camera",
    "glancing back over her shoulder",
    "leaning against a wall, arms loosely crossed",
    "one hand resting at the nape of her neck",
    "standing with arms relaxed at her sides, chin slightly lifted",
    "perched on the edge of a seat, leaning forward on one elbow",
    "turning at the waist to glance toward the camera",
    "one hand tucked into her waistband, weight shifted onto one leg",
    "gently tucking a strand of hair back, head tilted",
]


def varied_shot_fields(rng, demeanor=None) -> dict:
    """
    Seeded weighted pick of framing/angle/expression enum VALUES (WS3). Consumes
    the rng in a fixed order (framing, angle, expression) so it stays reproducible.
    The returned dict feeds ShotOptions(**fields); repetition in the pools weights
    the rotation toward coherent hero crops.

    WS-B: when ``demeanor`` is given (a DemeanorType or its value), ONLY the
    expression pool is swapped for that demeanor's weighted pool — the framing and
    angle draws, and the rng draw ORDER/COUNT, are unchanged, so a None demeanor is
    byte-identical to the legacy behavior (rng-parity with existing seeded tests).
    An unknown demeanor falls back to the default expression pool.
    """
    expr_pool = _EXPRESSION_VARIETY_POOL
    if demeanor is not None:
        try:
            key = demeanor if isinstance(demeanor, DemeanorType) else DemeanorType(
                getattr(demeanor, "value", demeanor)
            )
            expr_pool = DEMEANOR_EXPRESSION_POOLS.get(key, _EXPRESSION_VARIETY_POOL)
        except (ValueError, TypeError):
            expr_pool = _EXPRESSION_VARIETY_POOL
    return {
        "framing": rng.choice(_FRAMING_VARIETY_POOL),
        "angle": rng.choice(_CAMERA_ANGLE_VARIETY_POOL),
        "expression": rng.choice(expr_pool),
    }


def pose_variety_phrase(rng) -> str:
    """Seeded pick of a scene-neutral, identity-free body-position phrase (WS3)."""
    return rng.choice(POSE_VARIETY_PHRASES)


def framing_tokens(shot) -> List[str]:
    """
    The deterministic shot phrases that MUST survive prompt polish: framing +
    angle + (when requested) time of day. Deliberately excludes expression —
    that is mood, which the scene may embellish.
    """
    tokens = [
        phrase(FRAMING_PHRASES, getattr(shot, "framing", None)),
        phrase(CAMERA_ANGLE_PHRASES, getattr(shot, "angle", None)),
        phrase(TIME_OF_DAY_PHRASES, getattr(shot, "timeOfDay", None)),
    ]
    return [t for t in tokens if t]


def resolve_expression(shot, personality=None) -> Optional[str]:
    """
    Resolve the expression phrase for a shot:
      * explicit shot.expression wins;
      * else the persona's personality expression stands (returns None here —
        the personality phrase is emitted by _persona_flavor as today);
      * else default to a soft pleasant smile so hero shots always read warm.
    """
    expression = getattr(shot, "expression", None)
    if expression is not None:
        return phrase(EXPRESSION_PHRASES, expression)
    if personality is not None:
        return None  # personality's expression phrase stands
    return EXPRESSION_PHRASES["soft_smile"]


def compose_shot_block(shot, personality=None) -> str:
    """Framing + angle + time + lighting + resolved expression, comma-joined."""
    parts = list(framing_tokens(shot))
    lighting = phrase(LIGHTING_PHRASES, getattr(shot, "lighting", None))
    if lighting:
        parts.append(lighting)
    expr = resolve_expression(shot, personality)
    if expr:
        parts.append(expr)
    return ", ".join(parts)
