"""
scene_mapper — pure mapping from a planned SceneSpec to a PipelineEditRequest.

The source image is ALWAYS the character's hero photo (never regenerated). Batch
controls are re-applied here defensively (nudity clamp, sfw, allow/block filters),
and a >=1-active-step invariant is guaranteed so PipelineEditRequest's model
validator (which requires at least one of pose/outfit/prompt) never rejects.

Pure and side-effect free -> unit-testable and safe to run in dry-run mode.
"""
from typing import Optional

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
            location=scene.location, free_text=persona_bits or "a tasteful natural setting"
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
        prompt=background_text or None,
        negativePrompt=None,
        seed=seed,
        pipeline_order=controls.pipeline_order,
        photoStyle=controls.photo_style,
    )
