"""
Single source of truth for reusable prompt fragments.

Previously negatives were duplicated and inconsistent across workflow JSON files
(strong on outfit, empty on pose/character-gen). These constants are injected by the
prompt assembler and the workflow preparers so every generation/edit shares the same
anti-deformity and identity-preservation language.
"""
from typing import Optional

# Anti-deformity / quality negative. Merged from the strongest strings that were
# hardcoded in test_final_API.json and edit_final_AIO.json.
QUALITY_NEGATIVE = (
    "blurry, low resolution, low quality, lowres, worst quality, jpeg artifacts, "
    "deformed hands, bad hands, extra fingers, fused fingers, missing fingers, "
    "mutated hands, poorly drawn hands, extra limbs, missing limbs, extra arms, "
    "extra legs, deformed face, distorted face, asymmetrical eyes, cross-eyed, "
    "malformed, mutated, bad anatomy, disproportionate body, bad proportions, "
    "melted features, plastic skin, watermark, text, logo, signature, "
    "cartoonish, 3d render, doll, mannequin"
)

# Identity-preservation negative, for EDIT workflows (outfit/pose/background).
IDENTITY_NEGATIVE = (
    "different face, altered identity, face swap, changed facial features, "
    "different person, different hairstyle, different hair color, different eye color, "
    "different skin tone, aged, younger, beautified face, airbrushed face"
)

# Positive identity-preservation clause appended to edit prompts. {what} is the
# thing being changed (e.g. "the clothing", "the pose", "the background").
IDENTITY_PRESERVATION_CLAUSE = (
    "keep the exact same face, hair, hairstyle, hair color, skin tone, eye color, "
    "and all physical features of the person completely unchanged; only change {what}"
)


def edit_negative(extra: Optional[str] = None) -> str:
    """Full negative prompt for edit workflows (quality + identity + optional extra)."""
    parts = [QUALITY_NEGATIVE, IDENTITY_NEGATIVE]
    if extra and extra.strip():
        parts.append(extra.strip())
    return ", ".join(parts)


def generation_negative(extra: Optional[str] = None) -> str:
    """Full negative prompt for character generation (quality only)."""
    parts = [QUALITY_NEGATIVE]
    if extra and extra.strip():
        parts.append(extra.strip())
    return ", ".join(parts)


def identity_clause(what: str) -> str:
    return IDENTITY_PRESERVATION_CLAUSE.format(what=what)
