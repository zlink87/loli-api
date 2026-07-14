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
from models.requests import PipelineEditRequest, STAGING_TEXT_MAX_LENGTH
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

# WS-S: more faithful, less airbrushed pose-step ReActor defaults for the "as-shot"
# styles (natural / candid_phone) when the admin hasn't set an explicit value — so
# the face reads real instead of plastic on top of the now-sharp, hero-sourced face
# swap (node 210). CodeFormer semantics are the OPPOSITE of the intuitive reading: a
# HIGH codeformer_weight stays FAITHFUL to the swapped input face (less hallucinated
# repaint), while a LOW weight lets CodeFormer smooth/hallucinate more (the plastic
# look); restore_visibility is how strongly the CodeFormer-restored face is blended
# over the raw swap, so a LOWER visibility leaves more of the raw swap's real skin
# texture. So the "as-shot" styles RAISE codeformer_weight (0.75, truer to the swap)
# and LOWER restore_visibility (0.55, more raw-swap texture). Explicit controls always
# win; every other style keeps the settings default.
_SOFT_PHOTO_STYLES = ("natural", "candid_phone")
_SOFT_STYLE_CODEFORMER_WEIGHT = 0.75
_SOFT_STYLE_RESTORE_VISIBILITY = 0.55


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
    single_pass: Optional[bool] = None,
    single_pass_targets: str = "naked",
) -> PipelineEditRequest:
    """Build the PipelineEditRequest that renders `scene` by editing the hero photo.

    ``single_pass`` (the batch settings flag, passed by the caller so this module stays
    settings-free): when truthy AND the item is eligible — the swap SOURCE is the
    character's nude base, a pose is set, and the effective outfit passes the target gate —
    the request is flagged ``singlePassEdit`` so the pipeline collapses to ONE pose-graph
    job that re-poses + re-scenes (and, in "all" mode, dresses) the already-nude body in a
    single full-frame re-diffusion.

    ``single_pass_targets`` (the BATCH_SINGLE_PASS_TARGETS settings value, threaded here so
    the module stays settings-free — same pattern as ``single_pass``) selects WHICH effective
    outfits are single-pass eligible:
      * "naked" (default): only a NAKED effective outfit collapses. This gate exists because
        the pose graph is a full-frame Qwen-Image-Edit that re-diffuses the entire frame
        anchored to image1 (the nude base) — it is NOT a masked dresser. It reliably
        re-poses/re-scenes a NUDE target (nothing to add), but historically it looked like it
        could not reliably ADD an occluding garment over the nude base (the "Dress her in: …"
        text losing to the bare-body anchor, item rendering NUDE). A real (non-NAKED) garment
        therefore stays on the legacy multi-step path, whose dedicated masked-inpaint OUTFIT
        step clothes the nude base BEFORE the pose step ever runs.
      * "all": the golden 07-14-morning routing — ANY effective outfit collapses; the one
        pose job dresses additively (outfit_prompt_mode="dress", set below). Golden batch
        59ca806c proved single-pass DRESSING works, and commit 7381258e's NAKED-only revert
        instead routed dressed items through the 3-step chain, whose two post-dressing
        full-frame re-diffusions ERODE the garment (items render nude) and re-add plastic
        skin — the quality regression this mode reverts. Flip via Railway env for the A/B.
    Any unrecognized value degrades to "naked" (the safe gate). Not eligible / ``single_pass``
    falsy -> the legacy multi-step request, byte-identical to before these params existed.
    """
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

    # Pubic grooming: the genital area is exposed ONLY on a NAKED-class outfit at HIGH
    # nudity, so thread the character's grooming ENUM VALUE to the pose/outfit builders
    # (via PipelineEditRequest.pubicHair) ONLY there. An unset persona value resolves to
    # the "shaved" default so a NAKED+HIGH item always carries a definite grooming; every
    # dressed / sub-HIGH item leaves it None -> the builders append nothing (unchanged).
    naked_high = outfit == OutfitType.NAKED and nudity == NudityLevel.HIGH
    pubic_hair = (
        (_val(getattr(getattr(character, "persona", None), "pubicHair", None)) or "shaved")
        if naked_high
        else None
    )

    # No-pose face guard: the pose step is the ONLY step that stamps the hero's face
    # (its ReActor pass); the outfit and background steps composite the SOURCE image's own
    # face back byte-exact. With NUDE_BASE_FACE_SWAP defaulting False the nude base carries
    # a RANDOM t2i face, so a POSE-LESS item sourced from the nude base would publish that
    # un-swapped face. A pose-less item therefore falls back to the HERO photo as its swap
    # source (whose face IS the hero's) and is flagged sourceDressed=True so the outfit
    # builder uses its dressed-source (GARMENT/replace) mode — the exact pre-nude-base flow
    # whose composite-back keeps the hero's own face. A POSED item keeps the nude base: the
    # pose step swaps the hero face onto it. So ``nude_source`` below (the effective "swap
    # source is the bare nude base" signal) is gated on a pose being present.
    has_nude_base = bool(getattr(character, "nude_base_url", None))
    nude_source = has_nude_base and pose is not None
    source_dressed = has_nude_base and pose is None

    # Additive dressing on a nude base (B2). On a bare body the "replace" lead ("remove the
    # current outfit and replace it…") is INCOHERENT — there is no outfit on a nude body to
    # remove, so it no-ops the garment for some outfits and leaves the body bare. So for a
    # nude source + a real garment (non-NAKED) we force outfit_prompt_mode="dress"
    # (build_prompt's additive dress-onto-bare-body lead), overriding controls.outfit_prompt_mode.
    # NAKED never gets "dress" (there is nothing to add); a hero source (no nude base, OR the
    # pose-less fallback above) keeps the admin/controls value — "replace" is correct there
    # because the hero is dressed.
    if nude_source and outfit is not None and outfit != OutfitType.NAKED:
        outfit_prompt_mode = "dress"
    else:
        outfit_prompt_mode = controls.outfit_prompt_mode

    # Single-pass eligibility: the pose step re-diffuses the WHOLE frame anchored to the
    # nude base (image1), so a NAKED target has nothing to add — the outfit + background
    # steps only build a throwaway reference and we can collapse to one pose-graph job that
    # re-poses and re-scenes the already-nude body.
    #
    # The outfit gate is target-driven (single_pass_targets / BATCH_SINGLE_PASS_TARGETS):
    #   * "naked" (default): the outfit MUST be NAKED. Rationale kept from the NAKED-only
    #     era — the full-frame re-diffusion is NOT a masked dresser, so a real garment could
    #     render NUDE; those route to the legacy path whose masked-inpaint OUTFIT step
    #     clothes the base first. Requires a NAKED effective outfit (its tier prose IS the
    #     state-of-dress, literally true against a nude base).
    #   * "all": ANY effective outfit (outfit is not None) collapses — the golden
    #     07-14-morning routing. Golden batch 59ca806c proved the one pose job CAN dress
    #     additively (outfit_prompt_mode="dress" above), and the 3-step chain instead ERODES
    #     the garment across its two post-dressing full-frame re-diffusions; "all" reverts
    #     that regression. An unrecognized value falls back to the safe NAKED-only gate.
    # Requires the caller's flag, a nude-base source, a pose, and the target-gated outfit.
    # Not eligible -> legacy request.
    _targets_all = str(single_pass_targets or "naked").strip().lower() == "all"
    outfit_ok = (outfit is not None) if _targets_all else (outfit == OutfitType.NAKED)
    single_pass_edit = bool(single_pass and nude_source and pose is not None and outfit_ok)

    # C3 setting-led scenery: the director's ``setting`` sentence LEADS the composed
    # background text (lead_text), with the location enum phrase following as an anchor,
    # then time/lighting (scenery only — moods no longer ride the background text) — so
    # the authored place description drives the render instead of trailing ~30 canned
    # location phrases. ``activity`` is dual-routed: it
    # rides the pose step's own prompt when a pose step is active (see
    # api.v1.endpoints.pose.build_pose_prompt) — folding it into the background too
    # would say the same thing on two separate render channels — and only falls back to
    # the background free-text tail when there is no pose step, so it isn't lost.
    setting_text = _clean_scene_part(scene.setting)
    activity_text = _clean_scene_part(scene.activity) if pose is None else None
    if activity_text and activity_text == setting_text:
        activity_text = None  # de-dup identical parts
    # WS-S palette scope: the character's styled room + color palette only reach
    # HOME-ish scenes (sv.is_home_like_location, derived from INTERIOR_ROOM_PHRASES).
    # For a non-home location (cafe, street, gym, …) BOTH drop to None — the styled
    # room replacement was already self-gating, but the palette clause was not, so a
    # character's "bold dark palette" used to be stamped over a midday cafe. Gating at
    # the caller is the single clean fix (build_scene_background_text is unchanged).
    home_like = sv.is_home_like_location(scene.location)
    interior_style = controls.interior_style if home_like else None
    color_palette = controls.color_palette if home_like else None
    # Scenery ONLY: moods are deliberately NOT passed (mood_kinks/mood_personality) — the
    # background must describe the place, not persona flavor (the mood function is capped
    # separately). For a single-pass item, ALSO drop time-of-day/lighting here: they flow
    # to the pose tail via the request's lighting/timeOfDay fields (set below), and this
    # scene text becomes the pose prompt's "Place her in:" clause, so composing time/light
    # here too would duplicate that language inside the one pose prompt.
    # WS-STAGE scene staging: the planner-assigned scenery anchor (e.g. "perched on a bar
    # stool at the counter") joins right after the location phrase so the scene text names
    # WHERE in the space she is. Single-pass inherits it automatically (this composed text
    # becomes the pose prompt's "Place her in: …" clause); the 3-step background step gets
    # it too. None (no staging for this location/pose-class) composes byte-identically.
    staging_text = getattr(scene, "staging", None)
    # WS-SD scene direction: when Venice authored a VALIDATED per-item direction (HOW the
    # shot looks — furniture/objects/camera feel), it REPLACES the bare `staging` phrase in
    # the composed scene/background text. `staging` was only a SUGGESTION fed INTO Venice, so
    # composing both would double it. The pose step's stagingText slot also carries the
    # direction, but ONLY when it fits that field's 160-char cap (see below), so a longer
    # direction rides the scene text alone and the pose prompt keeps the short staging phrase.
    # None (deterministic provider / a validation fallback / legacy scenes) -> the bare
    # staging phrase stands, byte-identical to the pre-scene-direction batch.
    # (Local named ``direction_text`` — NOT ``scene_direction`` — so it never shadows the
    # services.scene_direction module.)
    direction_text = getattr(scene, "scene_direction", None)
    bg_staging = direction_text or staging_text
    pose_staging = (
        direction_text
        if (direction_text and len(direction_text) <= STAGING_TEXT_MAX_LENGTH)
        else staging_text
    )
    background_text = scene.background_text or sv.build_scene_background_text(
        location=scene.location,
        time_of_day=(None if single_pass_edit else scene.time_of_day),
        lighting=(None if single_pass_edit else scene.lighting),
        free_text=activity_text,
        lead_text=setting_text,
        # WS-B home scenery: her styled room replaces the generic home phrase, and the
        # palette clause joins the lighting section — but only for home-ish scenes (see
        # the WS-S gate above). An un-profiled batch (both None) composes byte-identically.
        interior_style=interior_style,
        color_palette=color_palette,
        # WS-SD: the Venice direction (if any) stands in for the bare staging phrase here.
        staging=bg_staging,
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
            interior_style=interior_style, color_palette=color_palette,
        )

    if seed is None:
        seed = scene.seed if scene.seed is not None else resolve_seed(controls, scene.global_index)

    # WS-S codeformer dial: on the "as-shot" styles (natural / candid_phone) default
    # the pose-step ReActor to a more faithful, less airbrushed restoration so the face
    # reads real instead of plastic — RAISE codeformer_weight (0.75, truer to the swapped
    # face) and LOWER restore_visibility (0.55, more of the raw swap's skin texture). See
    # the semantics note by the constants above. ONLY when the admin left the knob unset
    # (an explicit control always wins); every other style keeps None -> engine default.
    soft_style = _val(controls.photo_style) in _SOFT_PHOTO_STYLES
    reactor_codeformer = controls.reactor_codeformer_weight
    if reactor_codeformer is None and soft_style:
        reactor_codeformer = _SOFT_STYLE_CODEFORMER_WEIGHT
    reactor_visibility = controls.reactor_restore_visibility
    if reactor_visibility is None and soft_style:
        reactor_visibility = _SOFT_STYLE_RESTORE_VISIBILITY

    return PipelineEditRequest(
        # NOTE: the planner Character dataclass field is hero_photo_url (story_planner.py).
        # Prefer a nude/undressed base (nude_base_url) as the swap SOURCE so a new garment
        # renders onto a clean body instead of fighting the hero's existing clothes — but
        # ONLY for a POSED item (nude_source, above). A pose-less item has no pose step to
        # stamp the hero face, so it falls back to the hero photo (sourceDressed below) to
        # avoid publishing the nude base's un-swapped random face. No nude base -> hero.
        source_image=(
            getattr(character, "nude_base_url", None) if nude_source
            else character.hero_photo_url
        ),
        # WS-S: the ReActor face donor is ALWAYS the sharp original hero photo (never the
        # nude-base/intermediate source_image above), so the pose step swaps the face
        # from a clean image instead of a multiply-edited one. None-safe: getattr keeps
        # test stand-ins without the field working (falls back to source-as-donor).
        faceRefImage=getattr(character, "hero_photo_url", None),
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
        # Pubic grooming enum value — set ONLY for a NAKED-class outfit at HIGH nudity
        # (see `pubic_hair` above); None for every dressed / sub-HIGH item so the pose/
        # outfit builders append nothing there.
        pubicHair=pubic_hair,
        accessories=scene.accessories,
        # Additive scene metadata (identity-free enum-value strings) for the pose step (W3/B1).
        # lighting/timeOfDay re-light/re-time the re-diffused frame; location is the scene the
        # pose step must KEEP (build_pose_prompt's keep-background anchor). Always safe to set.
        lighting=_val(scene.lighting),
        timeOfDay=_val(scene.time_of_day),
        location=_val(scene.location),
        # WS-STAGE / WS-SD: the scenery anchor for THIS (location, pose-class). In the
        # multi-step path the pose step appends it to the target-pose sentence so the full
        # re-diffusion names the seat/surface; in single-pass it already rides the composed
        # scene text above (build_pose_prompt skips the duplicate append when scene_text is
        # present). When a validated Venice direction exists AND fits stagingText's 160-char
        # cap it stands in for the bare staging phrase here too (a longer direction rides the
        # scene text alone — see bg_staging/pose_staging above). None threads nothing.
        stagingText=pose_staging,
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
        # D2 + WS-S: admin-tunable pose-step ReActor knobs (node 200). An explicit
        # control wins; otherwise natural/candid_phone get the more-faithful WS-S
        # defaults (0.75 weight / 0.55 visibility) and every other style stays None ->
        # engine/settings default.
        reactorRestoreVisibility=reactor_visibility,
        reactorCodeformerWeight=reactor_codeformer,
        # Single-pass batch collapse: True only for an eligible nude-base+pose+outfit
        # item (see single_pass_edit above); the pipeline worker then runs ONE pose
        # step that dresses + re-scenes from the source. False -> legacy multi-step.
        singlePassEdit=single_pass_edit,
        # No-pose face guard: True only when a nude base EXISTS but this item has no pose
        # step, so the source falls back to the (dressed) hero photo — the outfit builder
        # then uses its GARMENT/replace dressed-source mode and the composite-back keeps the
        # hero's own face. False for every other item (posed nude-base items, hero-only
        # characters), byte-identical to before.
        sourceDressed=source_dressed,
    )
