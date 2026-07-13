"""
scene_mapper — pure mapping from a planned SceneSpec to a PipelineEditRequest.

The source image is ALWAYS the character's hero photo (never regenerated). Batch
controls are re-applied here defensively (nudity clamp, sfw, allow/block filters),
and a >=1-active-step invariant is guaranteed so PipelineEditRequest's model
validator (which requires at least one of pose/outfit/prompt) never rejects.

Pure and side-effect free -> unit-testable and safe to run in dry-run mode.
"""
from typing import List, Optional

from models.enums import NudityLevel, OutfitType
from models.batch import BatchControls, SeedStrategy
from models.scene import SceneSpec
from models.requests import PipelineEditRequest
from services import scene_vocab as sv
from services import attribute_phrases as ap
from services import prompt_constants as pc

_NUDITY_LADDER = [
    NudityLevel.LOW,
    NudityLevel.SUGGESTIVE,
    NudityLevel.MEDIUM,
    NudityLevel.REVEALING,
    NudityLevel.HIGH,
]


def _val(v):
    return ap._val(v)


def _clamp_nudity(level, controls: BatchControls) -> NudityLevel:
    if controls.sfw_only:
        return NudityLevel.LOW
    try:
        idx = _NUDITY_LADDER.index(NudityLevel(_val(level)))
    except (ValueError, TypeError):
        idx = 0
    max_idx = _NUDITY_LADDER.index(NudityLevel(_val(controls.max_nudity)))
    return _NUDITY_LADDER[min(idx, max_idx)]


def _effective_outfit(scene: SceneSpec, controls: BatchControls) -> Optional[OutfitType]:
    outfit = scene.outfit
    if outfit is None:
        return None
    if controls.sfw_only and outfit == OutfitType.NAKED:
        return None
    if outfit in (controls.blocked_outfits or []):
        return None
    if controls.allowed_outfits and outfit not in controls.allowed_outfits:
        return None
    return outfit


def _clean_scene_part(text: Optional[str]) -> Optional[str]:
    """
    Clean ONE AI-authored, identity-free scene part (``setting``/``activity``) for the
    background prompt. Run through scene_vocab.strip_companions so a stray "with a
    partner"/crowd tail can't paint extra people into the background (returns None when
    nothing meaningful survives), then dropped entirely (None, not word-surgered) if it
    contains generic glamour/stock-photo filler (see
    prompt_constants.has_banned_style_words): that filler fights the scene's own
    location/lighting attributes rather than describing it, and word-surgery on an
    already-written sentence leaves broken grammar, so the safer move is to skip a bad
    part and keep the rest of the composition.

    ``beat_description`` is deliberately NEVER fed through here: it is the human-facing
    narrative caption (persona name, actions, companions — e.g. "Lily practices a new
    dance with a partner"), which leaks narrative/people into the scene render.
    ``setting`` is the field the director writes for the render; the caption stays
    gallery-only. ``scene.narrative`` (free story prose) likewise stays gallery-only so
    it can never leak identity/style into a render.
    """
    cleaned = sv.strip_companions(text)
    if not cleaned or pc.has_banned_style_words(cleaned):
        return None
    return cleaned


def _norm_attr(v) -> Optional[str]:
    """Raw enum-ish value -> plain text, with underscores normalized to spaces
    (e.g. ``BreastSize.EXTRA_LARGE`` / "extra_large" -> "extra large"). None-safe."""
    val = _val(v)
    if not val:
        return None
    return str(val).replace("_", " ")


def identity_anchor_text(character) -> Optional[str]:
    """
    Compact, concrete identity-anchor phrase built from ``character.persona``'s
    drift-prone attributes: hair style+color, eye color, body type+breast size.

    D1: across a story batch the pose step fully re-diffuses the frame guided only
    by a GENERIC clause (prompt_constants.POSE_IDENTITY_CLAUSE — "keep the original
    ... hair style, hair color, eye color ..."), which binds weakly on a distilled
    edit model; hair structure/color and body proportions drift photo-to-photo as a
    result. This helper turns the character's OWN attribute values into a short
    factual list (e.g. "straight blonde hair, green eyes, curvy build with medium
    breasts") that build_pose_prompt / outfit.build_prompt append as a concrete
    per-character anchor alongside that generic clause.

    Values are the raw enum-value strings with underscores normalized to spaces,
    NOT the flowery attribute_phrases.py catalog — so any attribute value degrades
    to plain text instead of silently vanishing when it isn't in a hand-curated map.
    The one exception is the SKIN-TONE part, which is looked up through
    attribute_phrases.skin_tone_phrase so the anchor carries a paintable visual
    descriptor ("warm dark-brown skin") rather than the demographic label.

    Includes a skin-tone part (placed FIRST — skin tone is the most drift-prone
    attribute during a body repaint) derived from ``persona.ethnicity``. Edits
    repaint the body (outfit denoise 0.85-0.9, pose denoise 1.0 full-frame) while
    ReActor restores only the face, so without a skin-tone token in the edit prompt
    a dark-skinned character comes back with a white body. This is why the earlier
    "ethnicity is governed at generation time" rationale was WRONG for edits: the
    ETHNICITY_PHRASES block only reaches the text-to-image generation prompt, never
    the edit prompts these anchors feed, so the edit path needs its own skin-tone
    signal. The demographic LABEL itself (name/age, and the "a Black woman" style
    ethnicity label) is still excluded — only the skin-tone descriptor rides along,
    a visual attribute rather than a category word that would fight the render.

    Each part (skin / hair / eyes / build+breasts) is included only when its source
    attribute is present, so a partial profile degrades gracefully. Returns None
    when ``character``/``character.persona`` is missing, or none of the source
    attributes are set, so callers can skip the clause entirely rather than emit an
    empty one.
    """
    persona = getattr(character, "persona", None)
    if persona is None:
        return None

    skin_tone = ap.skin_tone_phrase(getattr(persona, "ethnicity", None))
    hair_style = _norm_attr(getattr(persona, "hairStyle", None))
    hair_color = _norm_attr(getattr(persona, "hairColor", None))
    eye_color = _norm_attr(getattr(persona, "eyeColor", None))
    body_type = _norm_attr(getattr(persona, "bodyType", None))
    breast_size = _norm_attr(getattr(persona, "breastSize", None))

    parts: List[str] = []
    # Skin tone leads: it is the attribute most prone to drift when the body is
    # re-diffused, and the one the white-body-on-dark-skin bug is about.
    if skin_tone:
        parts.append(skin_tone)
    if hair_style and hair_color:
        parts.append(f"{hair_style} {hair_color} hair")
    elif hair_style or hair_color:
        parts.append(f"{hair_style or hair_color} hair")

    if eye_color:
        parts.append(f"{eye_color} eyes")

    if body_type and breast_size:
        parts.append(f"{body_type} build with {breast_size} breasts")
    elif body_type:
        parts.append(f"{body_type} build")
    elif breast_size:
        parts.append(f"{breast_size} breasts")

    return ", ".join(parts) if parts else None


def resolve_seed(controls: BatchControls, scene_index: int) -> Optional[int]:
    """Per-item seed from the batch seed strategy."""
    strategy = _val(controls.seed_strategy)
    if strategy == SeedStrategy.RANDOM.value or controls.base_seed is None:
        return None
    if strategy == SeedStrategy.FIXED.value:
        return controls.base_seed
    # per_item
    return ((controls.base_seed + scene_index * 7919) % 1_000_000_000) or 1


def scene_to_pipeline_request(
    character,
    scene: SceneSpec,
    controls: BatchControls,
    seed: Optional[int] = None,
) -> PipelineEditRequest:
    """Build the PipelineEditRequest that renders `scene` by editing the hero photo."""
    pose = scene.pose if scene.pose not in (controls.blocked_poses or []) else None
    outfit = _effective_outfit(scene, controls)
    nudity = _clamp_nudity(scene.nudityLevel, controls)

    # Outfit-step-only knob (WS3.2): dead weight when there's no outfit step (outfit
    # is None) or nothing to strengthen against (NAKED has no "current clothing" to
    # override — build_prompt's NAKED branch doesn't consult it), so it's gated on a
    # non-NAKED effective outfit. Batch avatars are DRESSED by default, so a swap must
    # actively REMOVE the source garment, not just describe a new one over it — otherwise
    # the edit tends to reconstruct the original clothes. So for a real (non-NAKED) outfit
    # we default to a STRONGER denoise (0.85) unless the admin set an explicit value; an
    # explicit admin choice still wins. None when there's no outfit step / NAKED.
    outfit_denoise = (
        (controls.outfit_denoise if controls.outfit_denoise is not None else 0.85)
        if (outfit is not None and outfit != OutfitType.NAKED)
        else None
    )

    # Additive dressing on a nude base (B2). The swap SOURCE is the character's nude
    # base (see source_image below) whenever nude_base_url is populated. On a bare
    # body the "replace" lead ("remove the current outfit and replace it…") is
    # INCOHERENT — there is no outfit on a nude body to remove, so it no-ops the
    # garment for some outfits and leaves the body bare. So for a nude source + a real
    # garment (non-NAKED) we force outfit_prompt_mode="dress" (build_prompt's additive
    # dress-onto-bare-body lead), overriding controls.outfit_prompt_mode. NAKED never
    # gets "dress" (there is nothing to add), and a non-nude (hero) source keeps the
    # admin/controls value. (Deliberately NOT keyed off sourceDressed — that is
    # default-False for every caller and proves nothing about the source.)
    nude_source = bool(getattr(character, "nude_base_url", None))
    if nude_source and outfit is not None and outfit != OutfitType.NAKED:
        outfit_prompt_mode = "dress"
    else:
        outfit_prompt_mode = controls.outfit_prompt_mode

    # C3 setting-led scenery: the director's ``setting`` sentence LEADS the composed
    # background text (lead_text), with the location enum phrase following as an anchor,
    # then time/lighting/mood — so the authored place description drives the render
    # instead of trailing ~30 canned location phrases. ``activity`` is dual-routed: it
    # rides the pose step's own prompt when a pose step is active (see
    # api.v1.endpoints.pose.build_pose_prompt) — folding it into the background too
    # would say the same thing on two separate render channels — and only falls back to
    # the background free-text tail when there is no pose step, so it isn't lost.
    setting_text = _clean_scene_part(scene.setting)
    activity_text = _clean_scene_part(scene.activity) if pose is None else None
    if activity_text and activity_text == setting_text:
        activity_text = None  # de-dup identical parts
    background_text = scene.background_text or sv.build_scene_background_text(
        location=scene.location,
        time_of_day=scene.time_of_day,
        lighting=scene.lighting,
        mood_kinks=scene.mood_kinks,
        mood_personality=scene.mood_personality,
        free_text=activity_text,
        lead_text=setting_text,
        # WS-B home scenery: her styled room replaces the generic home phrase, and the
        # palette clause joins the lighting section. Both come from the (merged) controls,
        # so an un-profiled batch (both None) composes byte-identically to before.
        interior_style=controls.interior_style,
        color_palette=controls.color_palette,
    )

    # Guarantee at least one active step (PipelineEditRequest requires >=1).
    if pose is None and outfit is None and not (background_text and background_text.strip()):
        # Compose a neutral background from the persona so the request is valid.
        persona_bits = ", ".join(
            p for p in [
                ap.phrase(ap.OCCUPATION_PHRASES, character.persona.occupation),
                ap.phrase(ap.RELATIONSHIP_PHRASES, character.persona.relationship),
            ] if p
        )
        background_text = sv.build_scene_background_text(
            location=scene.location, free_text=persona_bits or "a tasteful natural setting",
            interior_style=controls.interior_style, color_palette=controls.color_palette,
        )

    if seed is None:
        seed = scene.seed if scene.seed is not None else resolve_seed(controls, scene.global_index)

    return PipelineEditRequest(
        # NOTE: the planner Character dataclass field is hero_photo_url (story_planner.py).
        # Prefer a nude/undressed base (nude_base_url) as the swap SOURCE so a new garment
        # renders onto a clean body instead of fighting the hero's existing clothes; None
        # today (populated by a later agent) -> falls back to the hero photo unchanged.
        source_image=getattr(character, "nude_base_url", None) or character.hero_photo_url,
        pose=pose,
        # C1a freeform pose text: identity-free and single-consumer (read only by the
        # pose step's build_pose_prompt, which simply doesn't run when the step is
        # absent), so it passes straight through unconditionally — same treatment as
        # outfitDetail/expression below. getattr keeps back-compat with legacy
        # scene_spec jsonb / test stand-ins that predate the field.
        poseDetail=getattr(scene, "pose_detail", None),
        outfit=outfit,
        # WS2 structured description channels: outfit_detail/expression are
        # identity-free and single-consumer (read only by the outfit/pose step
        # builders respectively, which simply don't run when their step is absent),
        # so they pass straight through unconditionally — same treatment as
        # accessories/background_text below.
        outfitDetail=scene.outfit_detail,
        expression=scene.expression,
        # activity is dual-routed (background text vs the pose step — see
        # _render_free_text above): only set here when the pose step will actually
        # consume it, so it's never duplicated-but-unread on the request.
        activity=(scene.activity if pose is not None else None),
        outfitDenoise=outfit_denoise,
        # Batch source avatars are dressed-by-default, so BatchControls.outfit_prompt_mode
        # defaults to "replace" (explicit remove-then-replace lead-in); an explicit admin
        # "standard"/"replace" passes straight through — EXCEPT a nude-base source, where
        # the mapper forces "dress" (additive) above because "replace" is incoherent there.
        outfitPromptMode=outfit_prompt_mode,
        # Detail-dominant (B3): when the planner set this, the outfit step renders
        # outfit_detail alone and skips the enum's tier prose (the enum only gates the
        # step + drives the nudity ramp). getattr keeps back-compat with legacy scenes /
        # test stand-ins that predate the field.
        outfitDetailDominant=bool(getattr(scene, "outfit_detail_dominant", False)),
        nudityLevel=nudity,
        accessories=scene.accessories,
        # Additive scene metadata (identity-free enum-value strings) for the pose step (W3/B1).
        # lighting/timeOfDay re-light/re-time the re-diffused frame; location is the scene the
        # pose step must KEEP (build_pose_prompt's keep-background anchor). Always safe to set.
        lighting=_val(scene.lighting),
        timeOfDay=_val(scene.time_of_day),
        location=_val(scene.location),
        # D1: concrete per-character identity anchors (hair/eyes/build), threaded to
        # BOTH the pose and outfit steps. Unlike lighting/timeOfDay/location above,
        # this is NOT identity-free — it carries the character's own attribute
        # values so the pose step's full re-diffusion binds to something concrete
        # instead of only the generic "keep the same hair…" clause. None when the
        # persona has none of the five source attributes set.
        identityAnchors=identity_anchor_text(character),
        prompt=background_text or None,
        negativePrompt=None,
        seed=seed,
        pipeline_order=controls.pipeline_order,
        photoStyle=controls.photo_style,
        # D2: admin-tunable pose-step ReActor knobs (node 200). None = engine/
        # settings default (see BatchControls.reactor_restore_visibility /
        # reactor_codeformer_weight docstrings).
        reactorRestoreVisibility=controls.reactor_restore_visibility,
        reactorCodeformerWeight=controls.reactor_codeformer_weight,
    )
