"""
Single source of truth for reusable prompt fragments.

Previously negatives were duplicated and inconsistent across workflow JSON files
(strong on outfit, empty on pose/character-gen). These constants are injected by the
prompt assembler and the workflow preparers so every generation/edit shares the same
anti-deformity and identity-preservation language.
"""
import re
from typing import Optional

from config import settings

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
# NOTE: "beautified face / airbrushed face" were intentionally REMOVED — they
# fought the retouched POLISHED finish (below) that matches the generated hero,
# and face identity is already guaranteed structurally (V2 stitches the face back
# byte-exact outside the mask; pose stamps it via ReActor), so those terms only
# suppressed the desired retouched skin on the regenerated region.
IDENTITY_NEGATIVE = (
    "different face, altered identity, face swap, changed facial features, "
    "different person, different hairstyle, different hair color, different eye color, "
    "different skin tone, aged, younger"
)

# Anti-airbrush SKIN negative for EDIT workflows only (appended by edit_negative).
# Commit 7804c2c8 removed the "beautified/airbrushed FACE" terms because the face is
# composited/stitched back byte-exact and those terms fought the retouched finish.
# These SKIN/body terms are safe (they never touch the preserved face) and suppress
# the waxy, over-smoothed body-region look the POLISHED finish can otherwise induce.
#
# Anti-shine terms: rendered skin was coming out oily/glossy "glamour"
# instead of natural matte realism. No skin-TONE words here (no
# "bronzed"/"tan"/"pale") — a tone negative would push a dark-skinned character's
# body lighter than their protected, byte-stitched-back face.
# NOTE: negative prompts only take effect on cfg>1 graphs (the 2511 outfit step).
# The v1 background and pose graphs sample at cfg 1.0, where negative
# conditioning is mathematically inert (nothing is subtracted from the
# unconditional branch) — don't try to fix those steps' skin rendering via this
# negative, it has no effect there; route it through positive prompt language
# (EDIT_PHOTO_STYLE_SUFFIXES) instead.
# WS-S skin-texture doctrine: extended with the anti-airbrush / anti-repaint terms
# the "natural must look natural" work needs on the live-negative tiers. "plastic skin"
# is intentionally NOT repeated here — it already ships in QUALITY_NEGATIVE, which
# edit_negative() always prepends, so re-adding it would only duplicate the token.
EDIT_SKIN_NEGATIVE = (
    "airbrushed skin, waxy skin, waxy smooth skin, over-smoothed skin, overprocessed, "
    "blurry skin texture, blurred facial features, porcelain doll skin, oily skin, "
    "glossy skin, glistening skin, shiny skin, wet-look skin, oiled body, greasy sheen, "
    "oversaturated colors, HDR, crushed blacks, harsh high contrast"
)

# Anatomy-realism negative for the genital area — appended ONLY where that area is
# actually exposed: the HIGH (fully-nude) edit tier (edit_negative below) and the
# nude base (workers.nude_base_worker imports this to extend its own anti-gloss
# negative). Suppresses the smooth, featureless "doll crotch" the NSFW base renders
# when there is nothing steering intimate anatomy. NEVER added to a dressed or
# sub-HIGH edit (it would waste negative budget on a region that isn't in frame), so
# it lives SEPARATELY from the always-on EDIT_SKIN_NEGATIVE. "airbrushed" overlaps
# EDIT_SKIN_NEGATIVE deliberately — the two are appended to different branches, never
# both to the same prompt at once.
ANATOMY_REALISM_NEGATIVE = (
    "airbrushed featureless crotch, doll-like smooth anatomy, deformed genitalia"
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
    # Finish-only wording. Earlier revisions claimed a genre and a setting
    # ("editorial glamour portraits", "studio portraits on a seamless backdrop",
    # "gentle background bokeh") and the edit/turbo models rendered that claim
    # INTO the scene — softboxes in frame, bokeh over a kitchen, warm cast over
    # night shots — overriding the prompt's actual environment. Styles must
    # describe light/color/skin finish only; the scene belongs to the prompt.
    "natural": (
        "YOUR CONTEXT:\n"
        "Your photographs look like real, unstaged photos.\n"
        "Your photographs have accurate natural exposure, true-to-life color balance, "
        "light that matches the scene's own light sources, realistic skin with visible "
        "fine texture and pores, and backgrounds rendered sharp and true to the "
        "described setting.\n"
        "Your subjects wear light everyday makeup, never heavy glamour makeup.\n"
        "---\n"
        "YOUR PHOTO:\n"
        "{$@}"
    ),
    "polished": (
        "YOUR CONTEXT:\n"
        "Your photographs are professionally retouched portraits.\n"
        "Your photographs have a soft flattering key light, a natural true-to-life "
        "color grade, a softly blurred background with shallow depth of field, and "
        "a clean composition focused on the subject, with the setting rendered "
        "exactly as described. Do not smooth, blur, or retouch the skin itself — "
        "keep every pore and fine skin texture exactly real.\n"
        "---\n"
        "YOUR PHOTO:\n"
        "{$@}"
    ),
    "studio": (
        "YOUR CONTEXT:\n"
        "Your photographs are high-end portraits with controlled softbox lighting, "
        "crisp focus, refined neutral color grading, and a softly blurred "
        "background with shallow depth of field, with the setting rendered exactly "
        "as described. Do not smooth, blur, or retouch the skin itself — keep "
        "every pore and fine skin texture exactly real.\n"
        "---\n"
        "YOUR PHOTO:\n"
        "{$@}"
    ),
    # Legacy raw/candid phone-cam aesthetic as a selectable option. WS-S skin-texture
    # doctrine: a texture-preservation line was added so even the "gritty phone-cam"
    # look keeps real skin (no smoothing/airbrush) — so this is no longer byte-identical
    # to the workflow JSON's baked-in node 125 value, but node 125 is overwritten at
    # runtime by photo_style_template() anyway when a style is selected. The
    # {$spicy-content-with} (erased by node 146) and {$@} substitution tokens are kept.
    "candid_phone": (
        "YOUR CONTEXT:\n"
        "Your photographs has android phone cam-quality.\n"
        "Your photographs exhibit {$spicy-content-with} surprising compositions, sharp "
        "complex backgrounds, natural lighting, and candid moments that feel immediate "
        "and authentic.\n"
        "Your photographs show real skin with its natural fine texture and visible "
        "pores.\n"
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
    "Your photographs have a soft flattering key light, a natural true-to-life "
    "color grade, a softly blurred background with shallow depth of field, and "
    "a clean composition focused on the subject, with the setting rendered "
    "exactly as described. Do not smooth, blur, or retouch the skin itself — "
    "keep every pore and fine skin texture exactly real.\n"
)
_POLISHED_TIME_LINES = {
    "night": (
        "Your photographs are taken at night: a dark low-key nighttime environment "
        "lit by the scene's own practical light sources, a natural nighttime color "
        "grade, a softly blurred background with shallow depth of field, and a "
        "clean composition focused on the subject, with the setting rendered "
        "exactly as described. Do not smooth, blur, or retouch the skin itself — "
        "keep every pore and fine skin texture exactly real.\n"
    ),
    "evening": (
        "Your photographs are taken in the evening after dark: soft ambient dusk "
        "light with the scene's own artificial accents, a natural evening color "
        "grade, a softly blurred background with shallow depth of field, and a "
        "clean composition focused on the subject, with the setting rendered "
        "exactly as described. Do not smooth, blur, or retouch the skin itself — "
        "keep every pore and fine skin texture exactly real.\n"
    ),
    "sunset": (
        "Your photographs are taken at sunset: warm golden backlight true to the "
        "hour, a natural sunset color grade, a softly blurred background with "
        "shallow depth of field, and a clean composition focused on the subject, "
        "with the setting rendered exactly as described. Do not smooth, blur, or "
        "retouch the skin itself — keep every pore and fine skin texture exactly "
        "real.\n"
    ),
    "golden_hour": (
        "Your photographs are taken during golden hour: low-angle golden light true "
        "to the hour, a natural color grade, a softly blurred background with "
        "shallow depth of field, and a clean composition focused on the subject, "
        "with the setting rendered exactly as described. Do not smooth, blur, or "
        "retouch the skin itself — keep every pore and fine skin texture exactly "
        "real.\n"
    ),
    "early_morning": (
        "Your photographs are taken in the dim early morning: soft cool dawn light, "
        "a gentle muted color grade, a softly blurred background with shallow "
        "depth of field, and a clean composition focused on the subject, with the "
        "setting rendered exactly as described. Do not smooth, blur, or retouch "
        "the skin itself — keep every pore and fine skin texture exactly real.\n"
    ),
}


# ---------------------------------------------------------------------------
# Color-grade clause (GENERATION styles only). Feedback: hero photos render
# realistic but flat/desaturated -- the "android phone cam-quality" realism
# wording in candid_phone (and the true-to-life restraint in the others) is
# deliberate and stays; this only adds a subtle richness/finish pass on top.
# Driven by settings.GENERATION_COLOR_GRADE so wording is tunable via env
# without a redeploy; empty string disables it entirely (byte-identical
# legacy prompts on every style). This is entirely separate from
# EDIT_PHOTO_STYLE_SUFFIXES below, which serves the qwen edit steps.
#
# candid_phone -- the legacy raw/candid phone-cam look -- gets a fixed,
# deliberately milder clause instead of the tunable value verbatim, so the
# "gritty candid" aesthetic isn't pushed toward a graded/finished look;
# natural/polished/studio (the more "finished" styles already) get the full
# tunable clause. Both are gated by the SAME settings switch.
# ---------------------------------------------------------------------------
_CANDID_COLOR_GRADE_MILD = (
    "natural true-to-life color with a gentle touch of warmth and richness, "
    "no washed-out or faded tones"
)
_COLOR_GRADE_SENTENCE = "Your photographs also have {grade}.\n"


def _with_color_grade(base: str, style_val: str) -> str:
    grade = (settings.GENERATION_COLOR_GRADE or "").strip()
    if not grade or "---\n" not in base:
        return base
    text = _CANDID_COLOR_GRADE_MILD if style_val == "candid_phone" else grade
    sentence = _COLOR_GRADE_SENTENCE.format(grade=text)
    return base.replace("---\n", f"{sentence}---\n", 1)


def photo_style_template(style, time_of_day=None) -> str:
    """
    Resolve the node-125 wrapper text for a photo style + optional time of day.

    * Unknown/None style -> "" (caller keeps the workflow's baked-in text).
    * polished + a mapped time -> the polished template with its lighting
      sentence swapped for the time-matched one (same structure, same {$@}).
    * studio/candid_phone ignore time (controlled studio light / legacy raw).
    * settings.GENERATION_COLOR_GRADE, when non-empty, appends a subtle
      color-grade clause (see _with_color_grade); empty -> no-op, byte-identical
      to the base template (with any time-of-day swap already applied).
    """
    style_val = getattr(style, "value", style)
    base = PHOTO_STYLE_TEMPLATES.get(style_val, "")
    if not base:
        return ""
    time_val = getattr(time_of_day, "value", time_of_day)
    if style_val == "polished" and time_val in _POLISHED_TIME_LINES:
        base = base.replace(_POLISHED_DAY_LINE, _POLISHED_TIME_LINES[time_val])
    return _with_color_grade(base, style_val)


# ---------------------------------------------------------------------------
# Edit-pipeline photo-style clauses.
#
# The EDIT workflows (pose/outfit/background) have no node-125 wrapper — their
# prompts are imperative instructions injected straight into a plain positive
# field — so the finish is applied Python-side.
#
# WS-S: the clause now LEADS the positive (see apply_edit_photo_style) instead of
# trailing it — at the tail it was the weakest binding and lost the fight to the
# URP/NSFW LoRAs + the face repaint, so "natural" never actually read as natural.
# Wording stays on light/exposure/contrast/color/DoF and NEVER touches identity
# (face/hair/features remain governed by the identity clauses), and every non-empty
# clause explicitly preserves real skin texture (no smoothing/airbrush/gloss — the
# "natural must look natural" doctrine). Keyed by PhotoStyleType values;
# "candid_phone" stays empty — the raw phone-cam opt-out adds no retouch clause, so
# it can never smooth skin (fully doctrine-compliant by omission).
# ---------------------------------------------------------------------------
EDIT_PHOTO_STYLE_SUFFIXES = {
    "natural": (
        "Shoot this as a real, unstaged photo: accurate natural exposure, "
        "true-to-life color, light that matches the scene's own light sources, "
        "and realistic skin with visible fine texture and pores, skin tone even "
        "and consistent with the face; light everyday makeup, not a styled photoshoot, "
        "soft balanced contrast, unboosted true-to-life colors, no HDR look."
    ),
    "polished": (
        "Give this a professional photographic retouch of light only: balanced "
        "exposure, gentle contrast, accurate true-to-life color, a soft flattering "
        "key light, and a softly blurred background with shallow depth of field. Do "
        "not smooth, blur, or retouch the skin itself — keep every pore and fine "
        "skin texture exactly real, skin tone even and consistent with the face; "
        "keep every fine detail of the clothing crisp and intact."
    ),
    "studio": (
        "Give this a professional studio photographic retouch of light only: "
        "controlled softbox lighting, balanced exposure, refined neutral color "
        "grading, and a softly blurred background with shallow depth of field. Do "
        "not smooth, blur, or retouch the skin itself — keep every pore and fine "
        "skin texture exactly real, skin tone even and consistent with the face."
    ),
    "candid_phone": "",
}

# Short (6-10 word) tail echo re-stating the finish at the END of a long edit
# instruction, so the style still binds after the imperative body when the clause
# leads. candid_phone stays empty (legacy raw look, no retouch echo). Doctrine:
# texture-preserving, never smoothing.
EDIT_PHOTO_STYLE_TAIL_ECHOES = {
    "natural": "Keep it a real photo with natural skin texture.",
    "polished": "Only light and color are retouched; skin texture stays real.",
    "studio": "Only studio light is retouched; skin texture stays real.",
    "candid_phone": "",
}


def apply_edit_photo_style(prompt: str, style=None) -> str:
    """
    LEAD an edit-step prompt with the photo-style clause for `style`, keeping a
    short tail echo so the finish binds at both ends of the positive.

    WS-S: previously the clause was appended at the TAIL — the weakest binding
    position — where it lost to the LoRAs + face repaint. It now PREPENDS the clause
    (strongest position) and re-states a compact 6-10 word echo at the end. Node
    injection still receives exactly one string, so every wrap call site
    (pipeline/pose/outfit/background workers) is unchanged.

    Accepts a PhotoStyleType, its string value, or None. Returns the prompt
    unchanged for None, unknown styles, or styles with an empty clause
    (candid_phone = legacy raw behavior, adds no retouch language).
    """
    if not style:
        return prompt
    key = getattr(style, "value", style)
    lead = EDIT_PHOTO_STYLE_SUFFIXES.get(key)
    if not lead:
        return prompt
    body = (prompt or "").strip()
    if not body:
        return lead
    if not body.endswith((".", "!", "?")):
        body += "."
    echo = EDIT_PHOTO_STYLE_TAIL_ECHOES.get(key, "")
    return f"{lead} {body} {echo}".rstrip() if echo else f"{lead} {body}"


def edit_negative(extra: Optional[str] = None, nudity_level=None) -> str:
    """
    Full negative prompt for edit workflows (quality + adult + identity +
    nudity suppression for the requested level + optional extra).

    ``nudity_level`` accepts a NudityLevel, its string value, or None (treated
    as 'low', matching the outfit/background prompt builders' own default) so
    an edit never silently renders more exposed than requested.
    """
    parts = [QUALITY_NEGATIVE, ADULT_APPEARANCE_NEGATIVE, IDENTITY_NEGATIVE, EDIT_SKIN_NEGATIVE]
    key = getattr(nudity_level, "value", nudity_level) or "low"
    suppression = NUDITY_SUPPRESSION.get(key, NUDITY_SUPPRESSION["low"])
    if suppression:
        parts.append(suppression)
    # Anatomy-realism negative — HIGH (fully-nude) tier ONLY, where the genital area
    # is actually exposed. Never on a dressed / sub-HIGH edit (those keep the global
    # EDIT_SKIN_NEGATIVE alone), so a dressed edit's negative is byte-identical to before.
    # Keyed by the "high" string (matching NUDITY_SUPPRESSION) to avoid importing the enum.
    if key == "high":
        parts.append(ANATOMY_REALISM_NEGATIVE)
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
    # Between low and medium: still fully blocks explicit/overt nudity (nipples,
    # genitals, total nudity) but drops low's broader breast/buttocks terms so a
    # still-clothed SUGGESTIVE outfit can show tease — cleavage, sideboob, bare skin.
    "suggestive": (
        "nude, naked, fully nude, exposed nipples, exposed genitals, "
        "exposed vulva, full frontal nudity"
    ),
    "medium": (
        "full frontal nudity, fully nude, completely naked, exposed genitals, "
        "exposed vulva, spread legs, explicit"
    ),
    # Between medium and high: only the core genital/full-frontal block remains —
    # lighter than medium (drops "fully nude", "completely naked", "spread legs",
    # "explicit"), heavier than high's empty string. Matches REVEALING's "mostly
    # nude, covering little" — a last sliver of coverage may still remain.
    "revealing": (
        "exposed genitals, exposed vulva, full frontal nudity"
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
# Style/genre words an LLM scene-writer (Venice) reliably injects even when
# told to describe a specific scene: generic glamour-shot and stock-photo
# vocabulary that claims its own setting/finish ("studio", "seamless
# backdrop", "editorial") or is pure marketing filler ("8k", "masterpiece",
# "cinematic", "stunning"). Any of these fights the user's actual requested
# scene and is the direct cause of e.g. a "school dance" hint rendering as a
# plain studio backdrop with softbox lights in frame. Scene text containing
# these is rejected outright (fall back to the raw hint) rather than
# stripped — removing words from an LLM sentence usually breaks the grammar.
# ---------------------------------------------------------------------------
BANNED_STYLE_WORDS = (
    "studio", "softbox", "backdrop", "bokeh", "editorial", "glamour",
    "professional photography", "professional photoshoot", "photoshoot",
    "8k", "4k", "hdr", "masterpiece", "best quality", "ultra detailed",
    "hyper detailed", "highly detailed", "cinematic", "stunning",
    "breathtaking", "flawless", "award winning", "trending on artstation",
    "octane render", "unreal engine",
)
_BANNED_STYLE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BANNED_STYLE_WORDS) + r")\b",
    re.IGNORECASE,
)


def has_banned_style_words(text: str) -> bool:
    """True if `text` contains generic glamour/stock-photo filler that claims
    its own setting or finish instead of describing the requested scene."""
    return bool(_BANNED_STYLE_RE.search(text or ""))


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
