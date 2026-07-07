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


def framing_tokens(shot) -> List[str]:
    """
    The deterministic shot phrases (framing + angle) that are always present.
    Deliberately excludes expression — that is mood, which the scene may embellish.
    """
    tokens = [
        phrase(FRAMING_PHRASES, getattr(shot, "framing", None)),
        phrase(CAMERA_ANGLE_PHRASES, getattr(shot, "angle", None)),
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
    """Framing + angle + resolved expression, comma-joined (the 'shot block')."""
    parts = list(framing_tokens(shot))
    expr = resolve_expression(shot, personality)
    if expr:
        parts.append(expr)
    return ", ".join(parts)
