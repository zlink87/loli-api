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


# Time-of-day lighting sentences for the POLISHED wrapper. The default polished
# wrapper hardcodes a warm daylight grade, which fights (and usually beats) a
# "night"/"dark" request in the prompt — the model splits the difference into a
# muddy dusk. When shot.timeOfDay is set, the wrapper's lighting sentence is
# swapped for a matching one so the finish stays POLISHED at any hour.
# Times absent from this map (morning/daytime/...) keep the default sentence.
_POLISHED_DAY_LINE = (
    "Your photographs have a soft flattering key light, a warm color grade, gentle "
    "background bokeh, flawless yet natural skin, and a clean composition focused "
    "on the subject.\n"
)
_POLISHED_TIME_LINES = {
    "night": (
        "Your photographs are taken at night: a dark low-key nighttime environment "
        "lit by warm practical light sources, a moody cinematic color grade, gentle "
        "background bokeh, flawless yet natural skin, and a clean composition "
        "focused on the subject.\n"
    ),
    "evening": (
        "Your photographs are taken in the evening after dark: soft ambient dusk "
        "light with warm artificial accents, a cinematic evening color grade, gentle "
        "background bokeh, flawless yet natural skin, and a clean composition "
        "focused on the subject.\n"
    ),
    "sunset": (
        "Your photographs are taken at sunset: warm golden backlight, a rich sunset "
        "color grade, gentle background bokeh, flawless yet natural skin, and a "
        "clean composition focused on the subject.\n"
    ),
    "golden_hour": (
        "Your photographs are taken during golden hour: warm low-angle golden light, "
        "a rich warm color grade, gentle background bokeh, flawless yet natural skin, "
        "and a clean composition focused on the subject.\n"
    ),
    "early_morning": (
        "Your photographs are taken in the dim early morning: soft cool dawn light, "
        "a gentle muted color grade, gentle background bokeh, flawless yet natural "
        "skin, and a clean composition focused on the subject.\n"
    ),
}


def photo_style_template(style, time_of_day=None) -> str:
    """
    Resolve the node-125 wrapper text for a photo style + optional time of day.

    * Unknown/None style -> "" (caller keeps the workflow's baked-in text).
    * polished + a mapped time -> the polished template with its lighting
      sentence swapped for the time-matched one (same structure, same {$@}).
    * studio/candid_phone ignore time (controlled studio light / legacy raw).
    """
    style_val = getattr(style, "value", style)
    base = PHOTO_STYLE_TEMPLATES.get(style_val, "")
    if not base:
        return ""
    time_val = getattr(time_of_day, "value", time_of_day)
    if style_val == "polished" and time_val in _POLISHED_TIME_LINES:
        return base.replace(_POLISHED_DAY_LINE, _POLISHED_TIME_LINES[time_val])
    return base


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


# Nudity-suppression negatives for the character-GENERATION path, keyed by
# NudityLevel value. The generation base model is NSFW-tuned, so without these
# it renders nude by default even when the prompt describes an outfit. LOW hard-
# suppresses all nudity so a clothed character stays clothed; MEDIUM allows
# partial exposure but blocks explicit full-frontal; HIGH suppresses nothing.
NUDITY_SUPPRESSION = {
    # Focused on actual body exposure, NOT clothing styles — so legitimately
    # skimpy LOW outfits (bikini, lace bodysuit, sheer summer dress) still render.
    "low": (
        "nude, naked, fully nude, topless, bottomless, exposed breasts, "
        "exposed nipples, bare breasts, exposed genitals, exposed vulva, "
        "exposed buttocks, bare ass, full frontal nudity"
    ),
    "medium": (
        "full frontal nudity, fully nude, completely naked, exposed genitals, "
        "exposed vulva, spread legs, explicit"
    ),
    "high": "",
}


def generation_negative(extra: Optional[str] = None, nudity_level=None) -> str:
    """
    Full negative prompt for character generation (quality + adult + nudity
    suppression for the requested level + optional extra).

    ``nudity_level`` accepts a NudityLevel, its string value, or None (treated as
    'low' so generation is clothed-by-default and never silently renders nude).
    """
    parts = [QUALITY_NEGATIVE, ADULT_APPEARANCE_NEGATIVE]
    key = getattr(nudity_level, "value", nudity_level) or "low"
    suppression = NUDITY_SUPPRESSION.get(key, NUDITY_SUPPRESSION["low"])
    if suppression:
        parts.append(suppression)
    if extra and extra.strip():
        parts.append(extra.strip())
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Image-to-video (reel) prompt fragments. Prompting is the only in-graph identity
# lever for WAN i2v (the SAM/inpaint/face-swap image machinery does not apply to
# the diffusion motion); a per-frame ReActor pass is the stronger post-fix.
# ---------------------------------------------------------------------------
VIDEO_CONSISTENCY_CLAUSE = (
    "keep the subject's face, hair, and outfit consistent throughout the clip; "
    "smooth natural motion, no morphing, no warping, no identity change"
)

# Motion/temporal quality negative for video generation.
VIDEO_MOTION_NEGATIVE = (
    "static, frozen, blurry, distorted, deformed, morphing, flickering, warping, "
    "jitter, stutter, duplicate face, changing face, face distortion, extra limbs, "
    "bad anatomy, low quality, jpeg artifacts, watermark, text"
)


def video_negative(extra: Optional[str] = None) -> str:
    """Full negative prompt for video generation (motion + quality + adult + optional extra)."""
    parts = [VIDEO_MOTION_NEGATIVE, QUALITY_NEGATIVE, ADULT_APPEARANCE_NEGATIVE]
    if extra and extra.strip():
        parts.append(extra.strip())
    return ", ".join(parts)


def identity_clause(what: str) -> str:
    return IDENTITY_PRESERVATION_CLAUSE.format(what=what)


def pose_identity_clause() -> str:
    """Identity-preservation clause for the pose workflow (anchors to image 1)."""
    return POSE_IDENTITY_CLAUSE
