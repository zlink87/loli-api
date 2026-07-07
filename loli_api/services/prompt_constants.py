"""
Single source of truth for reusable prompt fragments.

Previously negatives were duplicated and inconsistent across workflow JSON files
(strong on outfit, empty on pose/character-gen). These constants are injected by the
prompt assembler and the workflow preparers so every generation/edit shares the same
anti-deformity and identity-preservation language.
"""
from typing import Optional

# Anti-deformity / quality negative. Merged from the strongest strings that were
# hardcoded in test_final_API.json and edit_final_AIO.json (the latter is a
# dev-only template used only by test_edit_chain.py, not a production workflow).
QUALITY_NEGATIVE = (
    "blurry, low resolution, low quality, lowres, worst quality, jpeg artifacts, "
    "deformed hands, bad hands, extra fingers, fused fingers, missing fingers, "
    "mutated hands, poorly drawn hands, extra limbs, missing limbs, extra arms, "
    "extra legs, deformed face, distorted face, asymmetrical eyes, cross-eyed, "
    "malformed, mutated, bad anatomy, disproportionate body, bad proportions, "
    "melted features, plastic skin, watermark, text, logo, signature, "
    "cartoonish, 3d render, doll, mannequin"
)

# Adult-appearance negative. Defense-in-depth: even though Pydantic enforces
# age >= 18 and the numeric age is a locked token, this explicitly suppresses any
# youthful/underage rendering. Included in BOTH generation and edit negatives.
ADULT_APPEARANCE_NEGATIVE = (
    "child, children, kid, toddler, infant, baby, teenager, teen, adolescent, "
    "underage, minor, preteen, prepubescent, youthful appearance, childlike face, "
    "school age, loli, shota"
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

# Pose-specific identity clause. The pose workflow uses two-image conditioning
# (image 1 = source character, image 2 = pose reference), so the language must
# explicitly anchor every identity attribute (including outfit) to image 1.
POSE_IDENTITY_CLAUSE = (
    "Keep the original appearance, body proportion, skin tone, facial features, "
    "hair style, hair color, eye color, and outfit from image 1 completely unchanged"
)


# ---------------------------------------------------------------------------
# Workflow-side photo-style templates (node 125 of the character-gen workflow).
#
# The generation workflow substitutes the API prompt into this wrapper via a
# StringReplace chain: node 31 replaces {$@} with the assembled prompt AFTER
# Grok polish, inside ComfyUI — so the photographic finish here is structurally
# immune to the polisher. INVARIANTS (unit-tested):
#   * every template MUST contain the literal token {$@};
#   * {$spicy-content-with} is optional — node 146 erases it when present and
#     no-ops when absent.
# Keyed by PhotoStyleType values (models/enums.py).
# ---------------------------------------------------------------------------
PHOTO_STYLE_TEMPLATES = {
    "polished": (
        "YOUR CONTEXT:\n"
        "Your photographs are professionally retouched editorial glamour portraits.\n"
        "Your photographs have a soft flattering key light, a warm color grade, gentle "
        "background bokeh, flawless yet natural skin, and a clean composition focused "
        "on the subject.\n"
        "---\n"
        "YOUR PHOTO:\n"
        "{$@}"
    ),
    "studio": (
        "YOUR CONTEXT:\n"
        "Your photographs are high-end studio portraits on a seamless backdrop.\n"
        "Your photographs have controlled softbox lighting, crisp focus, refined warm "
        "color grading, and a clean uncluttered background.\n"
        "---\n"
        "YOUR PHOTO:\n"
        "{$@}"
    ),
    # BYTE-IDENTICAL to the workflow JSON's baked-in node 125 value — preserves
    # the legacy raw/candid phone-cam aesthetic as a selectable option.
    "candid_phone": (
        "YOUR CONTEXT:\n"
        "Your photographs has android phone cam-quality.\n"
        "Your photographs exhibit {$spicy-content-with} surprising compositions, sharp "
        "complex backgrounds, natural lighting, and candid moments that feel immediate "
        "and authentic.\n"
        "Your photographs are actual gritty candid photographic background.\n"
        "---\n"
        "YOUR PHOTO:\n"
        "{$@}"
    ),
}


# ---------------------------------------------------------------------------
# Edit-pipeline photo-style clauses.
#
# The EDIT workflows (pose/outfit/background) have no node-125 wrapper — their
# prompts are imperative instructions injected straight into a plain positive
# field — so the finish is applied Python-side as a short appended sentence
# rather than the generation-side "YOUR CONTEXT / YOUR PHOTO" template above.
# Wording deliberately stays on lighting/grade/finish and NEVER touches
# identity (face/hair/features remain governed by the identity clauses).
# Keyed by PhotoStyleType values; "candid_phone" is empty so the legacy raw
# look stays byte-identical.
# ---------------------------------------------------------------------------
EDIT_PHOTO_STYLE_SUFFIXES = {
    "polished": (
        "Give the photo a professionally retouched editorial glamour finish: "
        "soft flattering key light, warm color grade, gentle background bokeh, "
        "flawless yet natural skin."
    ),
    "studio": (
        "Give the photo a high-end studio finish: controlled softbox lighting, "
        "crisp focus, refined warm color grading, clean uncluttered look."
    ),
    "candid_phone": "",
}


def apply_edit_photo_style(prompt: str, style=None) -> str:
    """
    Append the photo-style clause for `style` to an edit-step prompt.

    Accepts a PhotoStyleType, its string value, or None. Returns the prompt
    unchanged for None, unknown styles, or styles with an empty clause
    (candid_phone = legacy behavior).
    """
    if not style:
        return prompt
    key = getattr(style, "value", style)
    suffix = EDIT_PHOTO_STYLE_SUFFIXES.get(key)
    if not suffix:
        return prompt
    base = (prompt or "").rstrip()
    if base and not base.endswith((".", "!", "?")):
        base += "."
    return f"{base} {suffix}" if base else suffix


def edit_negative(extra: Optional[str] = None) -> str:
    """Full negative prompt for edit workflows (quality + adult + identity + optional extra)."""
    parts = [QUALITY_NEGATIVE, ADULT_APPEARANCE_NEGATIVE, IDENTITY_NEGATIVE]
    if extra and extra.strip():
        parts.append(extra.strip())
    return ", ".join(parts)


def generation_negative(extra: Optional[str] = None) -> str:
    """Full negative prompt for character generation (quality + adult)."""
    parts = [QUALITY_NEGATIVE, ADULT_APPEARANCE_NEGATIVE]
    if extra and extra.strip():
        parts.append(extra.strip())
    return ", ".join(parts)


def identity_clause(what: str) -> str:
    return IDENTITY_PRESERVATION_CLAUSE.format(what=what)


def pose_identity_clause() -> str:
    """Identity-preservation clause for the pose workflow (anchors to image 1)."""
    return POSE_IDENTITY_CLAUSE
