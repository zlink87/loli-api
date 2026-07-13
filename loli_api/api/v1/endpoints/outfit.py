"""
Outfit edit endpoint.
POST /v1/edit/outfit - Create async outfit edit job using ComfyUI workflow.
"""
import copy
import json
import logging
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from auth.dependencies import get_current_user
from models.enums import OutfitType, AccessoryType, JobStatus, NudityLevel
from models.requests import OutfitEditRequest
from models.responses import JobCreateResponse
from services.notification_service import NotificationService
from services.character_anchors import populate_identity_anchors
from services import prompt_constants as pc
from services import scene_vocab as sv
from services.outfit_vocab import (
    OUTFIT_DESCRIPTIONS,
    ACCESSORY_DESCRIPTIONS,
    NUDE_BASE_BODY_DESCRIPTION,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Outfit Edit"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_outfit_workflow_path: Optional[str] = None
_outfit_workflow_template: Optional[dict] = None
# Optional (Supabase-gated) character store, wired in router.configure_services.
# Used only to auto-populate identityAnchors from OutfitEditRequest.characterId;
# None (store not configured) degrades gracefully — see populate_identity_anchors.
_character_store = None



# Outfit & accessory descriptions now live in services/outfit_vocab.py

# ---------------------------------------------------------------------------
# Service configuration functions (called from main.py)
# ---------------------------------------------------------------------------
def set_job_manager(job_manager) -> None:
    """Set job manager instance."""
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    """Set notification service instance."""
    global _notification_service
    _notification_service = service


def set_character_store(store) -> None:
    """Set the (optional) character store used to resolve identityAnchors."""
    global _character_store
    _character_store = store


def set_outfit_workflow_path(workflow_path: str) -> None:
    """Set and load outfit workflow template."""
    global _outfit_workflow_path, _outfit_workflow_template
    _outfit_workflow_path = workflow_path

    try:
        with open(workflow_path, 'r', encoding='utf-8') as f:
            _outfit_workflow_template = json.load(f)
        logger.info(f"Loaded outfit workflow template: {workflow_path}")
    except Exception as e:
        logger.error(f"Failed to load outfit workflow: {e}")
        _outfit_workflow_template = None


def get_job_manager():
    """Get job manager instance."""
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    """Get notification service instance."""
    return _notification_service


# ---------------------------------------------------------------------------
# Helper functions (used by OutfitBackgroundWorker via import)
# ---------------------------------------------------------------------------
def _outfit_change_lead(outfit: OutfitType, outfit_desc: str) -> str:
    """
    Lead sentence for a (dressed) outfit change.

    Uses the neutral verb "Change the person's outfit to:" rather than
    "Dress the person in ...". At MEDIUM/HIGH nudity the OUTFIT_DESCRIPTIONS
    text describes open, absent, or barely-present clothing, which directly
    contradicts an instruction to "dress" the person; the neutral verb stays
    accurate at every nudity level. ``outfit`` is accepted for signature
    stability / future per-outfit tuning.
    """
    return f"Change the person's outfit to: {outfit_desc}"


def _outfit_replace_lead(outfit: OutfitType, outfit_desc: str) -> str:
    """
    Lead sentence for a (dressed) outfit change in REPLACE mode (WS3.2).

    Dressed-source -> dressed-target swaps sometimes reconstruct the SOURCE
    garment (the edit model tends to use whatever is already on the body as its
    own reference), especially at the default denoise. This lead explicitly
    instructs removal of the current clothing before describing the new one,
    for callers that opt in via ``outfit_prompt_mode="replace"``. ``outfit`` is
    accepted for signature stability, mirroring ``_outfit_change_lead``.
    """
    return (
        f"Remove the person's current clothing completely and replace it with: "
        f"{outfit_desc}; no piece of the previous outfit may remain visible"
    )


def _outfit_dress_lead(outfit: OutfitType, outfit_desc: str) -> str:
    """
    Lead sentence for dressing a NUDE source (PR3 additive dressing).

    Selected via ``prompt_mode="dress"`` — set by the batch mapper when the swap
    SOURCE is the character's nude base (a bare body) and the target is a real
    garment. On a nude body the "replace" lead ("remove the current clothing …")
    is incoherent: there is no garment to remove, so it no-ops for some outfits and
    leaves the body bare. This lead instead states the body is currently nude and
    instructs the model to render the new clothing straight onto it (additive).
    ``outfit`` is accepted for signature stability, mirroring the other lead helpers.
    """
    return (
        f"The person is currently completely nude; dress them in: {outfit_desc}; "
        f"render the clothing fully and realistically on the body exactly as described"
    )


def outfit_continuity_text(
    outfit: Optional[OutfitType],
    nudity_level: NudityLevel,
    outfit_detail: Optional[str],
) -> Optional[str]:
    """
    The garment text the POSE step should preserve (state-of-dress continuity).

    The pose step fully re-diffuses the frame with no outfit language of its own, so
    it stochastically strips or re-invents clothing. build_pose_prompt takes this
    text and tells the model to keep exactly that state of dress. This helper is the
    single source of what "that state" is, matching what the outfit step actually
    rendered:

      * the ``OUTFIT_DESCRIPTIONS[outfit][nudity_level]`` tier prose, with the SAME
        fallbacks build_prompt uses (missing level -> the LOW tier; an outfit absent
        from the map -> ``str(outfit.value)``);
      * ADDITIVELY prefixed with ``outfit_detail`` (stripped) when non-empty — the
        concrete caption the outfit step was sharpened with is comma-joined AHEAD of
        the graded tier prose ("{detail}, {tier prose}") so the pose step preserves
        BOTH the caption garment AND the graded exposure, mirroring build_prompt's
        additive detail-dominant behavior. When the detail equals the tier prose it
        is emitted once (dedupe);
      * ``None`` when ``outfit`` is None — there was no outfit step, so there is no
        state of dress to assert.

    Deliberately dumb and side-effect-free: it only selects text, never phrases the
    continuity sentence (build_pose_prompt does that, because NAKED-tier prose needs
    different phrasing than a garment — see its ``outfit_text`` param).
    """
    if outfit is None:
        return None
    outfit_levels = OUTFIT_DESCRIPTIONS.get(outfit)
    if outfit_levels:
        tier_prose = outfit_levels.get(nudity_level, outfit_levels[NudityLevel.LOW])
    else:
        tier_prose = str(outfit.value)
    detail = outfit_detail.strip() if outfit_detail and outfit_detail.strip() else None
    if detail:
        if detail == tier_prose:
            return detail
        return f"{detail}, {tier_prose}"
    return tier_prose


# Garment-NEUTRAL exposure clauses for the detail-dominant outfit path. When the freeform
# outfit_detail caption REPLACES the enum's tier prose (detail_dominant), the enum's built-in
# nudity ramp is dropped along with that prose — but the nudity level must still render. These
# clauses ramp exposure WITHOUT naming any garment, so they never re-introduce a contradicting
# piece of clothing over the caption's garment. LOW is fully clothed -> empty (no clause
# appended). Keyed by NudityLevel (all 5 tiers present for self-documentation).
_DETAIL_DOMINANT_EXPOSURE: Dict[NudityLevel, str] = {
    NudityLevel.LOW: "",
    NudityLevel.SUGGESTIVE: "worn to tease, hinting at what's underneath",
    NudityLevel.MEDIUM: "worn partially open with real exposure of bare skin",
    NudityLevel.REVEALING: "worn barely closed, breasts nearly spilling free",
    NudityLevel.HIGH: "barely covering anything, breasts and intimate areas fully exposed",
}


def build_prompt(
    outfit: OutfitType,
    accessories: Optional[List[AccessoryType]],
    nudity_level: NudityLevel = NudityLevel.LOW,
    outfit_detail: Optional[str] = None,
    prompt_mode: str = "standard",
    lighting: Optional[str] = None,
    detail_dominant: bool = False,
    identity_anchors: Optional[str] = None,
) -> str:
    """
    Build the positive prompt from outfit and accessories.
    Ensures the person's face, hair, and physical features are never altered.

    Args:
        outfit: The outfit type
        accessories: Optional list of accessories
        nudity_level: Nudity level (low, medium, high)
        outfit_detail: Optional identity-free concrete garment description
            (colors/fabric/fit — e.g. SceneSpec.outfit_detail from the story
            director) appended onto the lead sentence, right after the generic
            OUTFIT_DESCRIPTIONS tier prose it sharpens. None = tier prose only
            (unchanged interactive-endpoint behavior).
        prompt_mode: Lead-in selector (default "standard"). Recognized values:
            * "standard" — the neutral "Change the person's outfit to:" lead on
              the dressed branch (``_outfit_change_lead``); the plain "Remove all
              clothing, the person should be {tier prose}" lead on NAKED. This is
              the historical default behavior (formerly ``replace_mode=False``).
            * "replace" — WS3.2 dressed-branch only: swaps the lead-in for an
              explicit remove-then-replace instruction (``_outfit_replace_lead``)
              so a dressed source stops reconstructing its own garment (formerly
              ``replace_mode=True``). The NAKED branch already reads as a removal,
              so this leaves NAKED unchanged.
            * "nude_base" — NAKED-branch only: renders the neutral per-character
              anatomical base. Swaps the arousal-styled NAKED tier prose for
              ``outfit_vocab.NUDE_BASE_BODY_DESCRIPTION`` AND hardens the removal
              lead to explicitly clear any stray garment/bra/strap/underwear (the
              leftover-strap failure). On the dressed branch it falls through to
              the "standard" lead (nude_base is only ever paired with NAKED).
            * "dress" — dressed-branch only (PR3 additive dressing): swaps the
              lead-in for ``_outfit_dress_lead`` ("the person is currently
              completely nude; dress them in: …"). Set by the batch mapper when the
              swap SOURCE is the character's nude base, where the "replace" removal
              lead is incoherent (nothing to remove) and no-ops the garment. The
              NAKED branch IGNORES "dress" (dressing a NAKED target is a
              contradiction) — it falls through to the standard removal lead.
            Any unrecognized value behaves like "standard".
        lighting: Optional raw lighting enum-VALUE string (e.g.
            PipelineEditRequest.lighting, sourced from SceneSpec.lighting —
            values like "moody_dim"/"candlelit"/"neon"). Phrase-ified via
            services.scene_vocab.lighting_phrase() (the same LIGHTING_PHRASES
            map the background step and the pose step use) and appended onto
            the lead sentence right after outfit_detail as ", in {lighting
            phrase}". The outfit step composites the person back over the
            source, so this mostly affects the newly-rendered garment/crop
            region rather than re-lighting the whole person — a cheap,
            low-risk secondary lighting signal, not the primary fix (that is
            build_pose_prompt's lighting param). None, or a value absent from
            the map, leaves the prompt unchanged.
        detail_dominant: When True AND ``outfit_detail`` is non-empty AND ``outfit`` is
            not NAKED, the caption LEADS the garment description — it is passed to the
            change/replace/dress helper in place of the tier prose — and the enum's
            graded ``OUTFIT_DESCRIPTIONS[outfit][nudity_level]`` tier prose is then
            appended ADDITIVELY after it (", {tier prose}"). This keeps the concrete
            caption garment AND the graded per-nudity-tier explicitness together, rather
            than the old behavior that REPLACED the tier prose with the caption plus a
            generic ``_DETAIL_DOMINANT_EXPOSURE`` clause (which systematically weakened
            explicitness). Used when the planner's director caption had no confident enum
            mapping (or conflicted with the enum), so the enum is a step-gate / nudity
            carrier whose graded prose is still wanted. Only when the outfit enum is
            missing from the map (no tier prose exists) does the garment-neutral
            ``_DETAIL_DOMINANT_EXPOSURE`` clause remain as the fallback nudity ramp.
            ``outfit_detail`` is NOT appended a second time (it IS the lead description
            here). NAKED and empty-detail calls ignore this flag (unchanged behavior);
            default False everywhere else.
        identity_anchors: Optional concrete identity-attribute phrase for THIS
            character (e.g. from services.scene_mapper.identity_anchor_text —
            "straight blonde hair, green eyes, curvy build with medium breasts").
            D1: the outfit step re-diffuses the body region too, so a concrete
            hair/build anchor helps identity fidelity there as well as at the pose
            step. When set, appended right after ``pc.identity_clause(...)`` (on
            BOTH the NAKED and dressed branches) as "she has {anchors}, kept
            exactly unchanged". None/empty (interactive /v1/edit/outfit and any
            caller without a character profile) appends nothing — unchanged
            behavior.

    Returns:
        Complete prompt string
    """
    outfit_levels = OUTFIT_DESCRIPTIONS.get(outfit)
    if outfit_levels:
        outfit_desc = outfit_levels.get(nudity_level, outfit_levels[NudityLevel.LOW])
    else:
        outfit_desc = str(outfit.value)

    lighting_text = sv.lighting_phrase(lighting)
    # D1: concrete per-character identity anchor, appended right after
    # pc.identity_clause(...) on BOTH branches below (computed once here).
    anchors_clause = (
        f"she has {identity_anchors.strip()}, kept exactly unchanged"
        if identity_anchors and identity_anchors.strip()
        else None
    )

    if outfit == OutfitType.NAKED:
        if prompt_mode == "nude_base":
            # Neutral per-character anatomical base: use the calm reference-body
            # description instead of the arousal-styled NAKED tier prose, and
            # harden the removal so no stray garment/bra/strap/underwear survives.
            lead = (
                "Remove all clothing completely so that no garment, bra, strap, or "
                "underwear remains anywhere, the person should be "
                f"{NUDE_BASE_BODY_DESCRIPTION}"
            )
        else:
            lead = f"Remove all clothing, the person should be {outfit_desc}"
        if outfit_detail and outfit_detail.strip():
            lead += f", {outfit_detail.strip()}"
        if lighting_text:
            lead += f", in {lighting_text}"
        prompt_parts = [
            lead,
            pc.identity_clause("the clothing and covering"),
        ]
        if anchors_clause:
            prompt_parts.append(anchors_clause)
        prompt_parts.append("only change the clothing and covering, nothing else")
    else:
        # Dressed branch. In detail-dominant mode the caption LEADS the garment
        # description (the director caption had no confident enum mapping, so it wins the
        # lead position), and the enum's graded tier prose is appended ADDITIVELY after it
        # below — keeping BOTH the concrete caption garment and the graded per-nudity-tier
        # explicitness, rather than replacing the tier prose with a generic exposure clause.
        detail = (outfit_detail or "").strip()
        detail_active = detail_dominant and bool(detail)
        lead_desc = detail if detail_active else outfit_desc

        # "replace" opts into the explicit remove-then-replace lead; "dress" (nude-base
        # source) opts into the additive dress-onto-bare-body lead; every other mode
        # ("standard", "nude_base", or an unrecognized value) uses the neutral change lead.
        if prompt_mode == "replace":
            lead = _outfit_replace_lead(outfit, lead_desc)
        elif prompt_mode == "dress":
            lead = _outfit_dress_lead(outfit, lead_desc)
        else:
            lead = _outfit_change_lead(outfit, lead_desc)

        if detail_active:
            # The caption already leads the description; DON'T append it again. Append the
            # enum's graded tier prose ADDITIVELY so the per-nudity-tier explicitness rides
            # alongside the caption garment. Only when the outfit is absent from the map (no
            # tier prose exists) do we fall back to the garment-neutral exposure clause to
            # carry the nudity ramp (LOW / unknown levels map to "" -> nothing appended).
            if outfit_levels:
                lead += f", {outfit_desc}"
            else:
                exposure = _DETAIL_DOMINANT_EXPOSURE.get(nudity_level, "")
                if exposure:
                    lead += f", {exposure}"
        elif detail:
            lead += f", {detail}"
        if lighting_text:
            lead += f", in {lighting_text}"
        prompt_parts = [
            lead,
            pc.identity_clause("the outfit and clothing"),
        ]
        if anchors_clause:
            prompt_parts.append(anchors_clause)
        prompt_parts.append("only change the clothing, nothing else")

    if accessories:
        accessory_parts = [
            ACCESSORY_DESCRIPTIONS.get(acc, str(acc.value))
            for acc in accessories
        ]
        prompt_parts.append(", ".join(accessory_parts))

    return ", ".join(prompt_parts)


# Outfit types eligible for the tight GARMENT mask (ClothesSegment) instead of the
# whole-PERSON mask in the crop-and-stitch (V2) graph. GARMENT mode edits ONLY the
# existing clothing, so it keeps far more fine detail (sequins, lace) and stops the
# body/anatomy being re-diffused — but it needs a DRESSED source (ClothesSegment finds
# nothing on a nude body). Safety is a conjunction: GARMENT engages only when the caller
# sets sourceDressed=true (there IS clothing to segment) AND the TARGET outfit is listed
# here. Membership marks like-coverage swaps suited to a tight mask; a coverage-INCREASING
# change (e.g. bikini -> fur coat) would clip to the small source mask, so those stay BODY.
# Seeded with the single-piece dress family (where the blocky-detail problem lives);
# validate each new type on a dressed source via outfit_cropstitch_maskpreview before adding.
GARMENT_MODE_OUTFITS: set = {
    OutfitType.COCKTAIL_DRESS,
    OutfitType.BODYCON_DRESS,
    OutfitType.LITTLE_BLACK_DRESS,
    OutfitType.RED_EVENING_GOWN,
    OutfitType.VELVET_DRESS,
    OutfitType.SATIN_SLIP_DRESS,
    OutfitType.WHITE_SUMMER_DRESS,
    OutfitType.FLORAL_MAXI_DRESS,
}


def _is_cropstitch_template(template: dict) -> bool:
    """True if this is the V2 crop-and-stitch graph (has InpaintCropImproved)."""
    node = template.get("235")
    return bool(node and node.get("class_type") == "InpaintCropImproved")


def prepare_outfit_cropstitch_workflow(
    template: dict,
    image_name: str,
    prompt: str,
    seed: Optional[int] = None,
    nudity_level: Optional[NudityLevel] = None,
    outfit: Optional[OutfitType] = None,
    negative_prompt: Optional[str] = None,
    head_mask_name: Optional[str] = None,
    source_dressed: bool = False,
    denoise: Optional[float] = None,
) -> dict:
    """
    Prepare the V2 crop-and-stitch outfit graph (``outfit_cropstitch_API.json``).

    Identity is preserved by construction: the edit is confined to a mask (person
    or garment) MINUS the head, cropped to that region, regenerated at full model
    resolution, and stitched back so every pixel outside the feathered mask —
    including the face — is byte-identical to the source (InpaintStitchImproved).
    This replaces V1's whole-frame, low-effective-resolution re-diffusion that
    mangled the garment/body boundary.

    Mask mode:
      * BODY (default, node 233 destination = node 213 hole-filled person mask):
        universal — works for a nude source (dress-up) and a dressed source alike.
      * GARMENT (node 233 destination = node 230 ClothesSegment mask): tight,
        semantic clothing mask that also excludes hair/skin — but only when the
        source is DRESSED. Enabled only when ``source_dressed`` is true AND the
        target outfit is in ``GARMENT_MODE_OUTFITS``.

    Head protection: the server-computed YuNet mask (node 211 -> 212) is subtracted
    (node 233). With no staged mask, the subtraction is bypassed (node 235 reads the
    base mask directly) so the graph still validates.

    Key nodes in outfit_cropstitch_API.json:
        108  LoadImage             -> source image filename
        211  LoadImage             -> head-protect mask filename
        213  GrowMaskWithBlur      -> hole-filled BODY (person) base mask
        230  ClothesSegment        -> GARMENT base mask (output index 1)
        233  MaskComposite         -> base mask MINUS head (destination = selected base)
        235  InpaintCropImproved   -> crop the edit region to full resolution
        16   easy positive         -> clothing change prompt
        117  easy negative         -> quality/adult/identity/nudity negatives
        106  KSampler              -> seed + denoise
        238  InpaintStitchImproved -> pixel-exact recomposite
    """
    wf = copy.deepcopy(template)

    wf["108"]["inputs"]["image"] = image_name
    wf["16"]["inputs"]["positive"] = prompt
    wf["117"]["inputs"]["negative"] = pc.edit_negative(negative_prompt, nudity_level=nudity_level)
    if seed is not None:
        wf["106"]["inputs"]["seed"] = seed

    # Mask mode: GARMENT (tight clothing) only when the caller says the source is
    # dressed AND the target is an opt-in like-coverage swap; else BODY (person).
    # source_dressed guards the nude case (ClothesSegment would find nothing).
    use_garment = source_dressed and outfit is not None and outfit in GARMENT_MODE_OUTFITS
    base_ref = ["230", 1] if use_garment else ["213", 0]
    wf["233"]["inputs"]["destination"] = base_ref

    # Head protection: subtract the server YuNet mask. If none was staged, bypass
    # the subtraction (crop reads the base mask directly) and keep node 211 valid.
    if head_mask_name:
        wf["211"]["inputs"]["image"] = head_mask_name
    else:
        wf["211"]["inputs"]["image"] = image_name
        wf["235"]["inputs"]["mask"] = base_ref
        logger.debug("No head mask staged; crop reads base mask directly")

    # Denoise: kept modest so the crop-confined regeneration preserves fine garment
    # structure (laces, straps) rather than re-inventing it. Lowered BODY 0.85 -> 0.80
    # (the whole-torso re-diffuse was wiping out clothing detail); a full dress-up over
    # bare skin still applies at 0.80. GARMENT (opt-in, dressed source) shares the value
    # for now — split the ternary back out if the two modes need independent tuning.
    # WS3.2: caller override (BatchControls.outfit_denoise -> PipelineEditRequest.
    # outfitDenoise, 0.5-0.95) — a dressed source -> dressed target swap sometimes
    # needs a stronger denoise than 0.80 to stop the source garment reconstructing
    # itself. None (default / interactive callers) keeps the 0.80 baseline.
    wf["106"]["inputs"]["denoise"] = denoise or 0.80

    logger.debug(
        f"V2 outfit graph prepared: mode={'GARMENT' if use_garment else 'BODY'}, "
        f"outfit={getattr(outfit, 'value', outfit)}"
    )
    return wf


def prepare_outfit_workflow(
    template: dict,
    image_name: str,
    prompt: str,
    seed: Optional[int] = None,
    nudity_level: Optional[NudityLevel] = None,
    outfit: Optional[OutfitType] = None,
    negative_prompt: Optional[str] = None,
    head_mask_name: Optional[str] = None,
    source_dressed: bool = False,
    denoise: Optional[float] = None,
) -> dict:
    """
    Prepare the outfit workflow with injected parameters.

    ``denoise`` (WS3.2, 0.5-0.95, None = engine default) only applies on the V2
    crop-and-stitch graph — forwarded to ``prepare_outfit_cropstitch_workflow``
    below. The legacy V1 whole-frame graph deliberately leaves node 106 denoise at
    the template's baked value regardless of this argument (see the NOTE on the
    mask-feather block further down: aggressive denoise is only safe once
    regeneration is crop-confined, which V1 is not).

    Identity is preserved in layers:
      1. Node 202 segments the PERSON — the edit region. The person mask (not
         garment terms) is deliberate: it is the only config that works BOTH
         for undressing and for dressing a nude source. Node 213
         (GrowMaskWithBlur, fill_holes=true, expand=0, blur_radius=0) fills any
         accidental internal gaps in that raw SAM mask BEFORE it branches to
         the head-subtract (205) / background-invert (204) steps — SAM's
         segmentation over folded fabric/shadow can leave small holes, and once
         composite-back (below) is real, an unfilled hole lets a blurred patch
         of the STALE original image show through mid-garment.
      2. The SERVER-COMPUTED head-protect mask (``head_mask_name`` -> node 211,
         see services/head_mask.py) is subtracted (205) so the head is never in
         the edit region. Computed with YuNet server-side because on-worker face
         detection (GroundingDINO grounding, insightface) fails on stylized hero
         renders — the failure that repainted whole identities in production.
      3. InpaintModelConditioning (121) runs with noise_mask=true: the sampler
         only denoises the masked latent region. Node 220 (ImageCompositeMasked)
         then pastes the sampled pixels back onto the ORIGINAL source image using
         the same mask, so every pixel outside the (feathered) mask — including
         the face — is byte-identical to the source. This replaced an earlier
         noise_mask=false config where the mask was merely a green-overlay hint
         and the sampler silently re-diffused the entire frame.
      4. ReActorFaceSwap (210) is disabled on this path: with a real
         composite-back the face is never touched by the sampler, so a face-swap
         pass is redundant and was the source of a "waxy"/over-restored look.

    Key nodes in test_final_API.json:
        108    LoadImage             -> inputs.image   (source image filename)
        211    LoadImage             -> inputs.image   (head-protect mask filename)
        213    GrowMaskWithBlur      -> fill_holes-only pass on the raw person mask
        16     easy positive         -> inputs.positive (clothing change prompt)
        106    KSampler              -> inputs.seed
        117    easy negative         -> inputs.negative (quality/adult/identity/nudity)
        119    GrowMaskWithBlur      -> inputs.expand/blur_radius (mask feathering)
        220    ImageCompositeMasked  -> pastes sampled pixels back onto the source

    Args:
        template: Base workflow template
        image_name: ComfyUI image filename
        prompt: Positive prompt
        seed: Optional seed value
        nudity_level: Optional nudity level for adaptive masking
        outfit: Optional outfit type for direction detection
        negative_prompt: Optional extra negative prompt terms (appended to
            quality + adult + identity negatives on node 117)
        denoise: Optional outfit-step denoise override (0.5-0.95), V2-only — see
            the WS3.2 note above.

    Returns:
        Prepared workflow dict
    """
    # V2 crop-and-stitch graph has its own preparer; detect by template content so
    # every caller (interactive outfit worker, batch pipeline) auto-routes by which
    # workflow file it loaded — no caller changes needed to cut over.
    if _is_cropstitch_template(template):
        return prepare_outfit_cropstitch_workflow(
            template, image_name, prompt, seed=seed, nudity_level=nudity_level,
            outfit=outfit, negative_prompt=negative_prompt, head_mask_name=head_mask_name,
            source_dressed=source_dressed, denoise=denoise,
        )

    wf = copy.deepcopy(template)

    # Node 108: Source image
    if "108" in wf:
        wf["108"]["inputs"]["image"] = image_name
        logger.debug(f"Set node 108 image: {image_name}")

    # Node 16: Positive prompt
    if "16" in wf:
        wf["16"]["inputs"]["positive"] = prompt
        logger.debug(f"Set node 16 prompt: {prompt[:50]}...")

    # Node 117: Negative prompt (quality + adult + identity + nudity suppression + user override)
    if "117" in wf:
        wf["117"]["inputs"]["negative"] = pc.edit_negative(negative_prompt, nudity_level=nudity_level)
        logger.debug("Set node 117 negative (quality + adult + identity + nudity)")

    # Node 106: Seed
    if seed is not None and "106" in wf:
        wf["106"]["inputs"]["seed"] = seed
        logger.debug(f"Set node 106 seed: {seed}")

    # Node 211: server-computed head-protect mask (white = never edit). The
    # caller stages the PNG alongside the source image. Defensive fallback when
    # no mask was staged: skip the subtraction entirely (119 <- node 213, the
    # hole-filled person mask — NOT raw node 202, which can have accidental
    # internal segmentation gaps that now composite-back would let bleed
    # through as stale-original ghost patches) and point 211 at the source
    # file so graph validation still passes.
    if "211" in wf:
        if head_mask_name:
            wf["211"]["inputs"]["image"] = head_mask_name
            logger.debug(f"Set node 211 head mask: {head_mask_name}")
        else:
            wf["211"]["inputs"]["image"] = image_name
            if "119" in wf and "213" in wf:
                wf["119"]["inputs"]["mask"] = ["213", 0]
            logger.debug("No head mask staged; using hole-filled person mask")

    # Mask target: the template's node 202 segments "person" for EVERY direction —
    # the only config that handles both undressing (garments are on the body) and
    # dressing a nude source (garment-term masks find nothing and produce patchy
    # garbage). The head is protected by the subtracted server-computed mask
    # (node 211/212/205).
    #
    # Feather the mask edge modestly. The previous expand=20/blur=10 grew the
    # whole-PERSON silhouette ~20px outward all around, pushing the editable
    # region into the surrounding background and producing halos / garment bleed
    # at the person's outline (visible as a mangled boundary on in-place edits).
    # A tight 8/4 edge keeps enough headroom for new collars/straps/hemlines
    # (which sit INSIDE the person mask anyway) while cutting the background
    # bleed. Composite-back (node 220) still guarantees pixels outside this edge
    # are byte-exact. NOTE: node 106 denoise is deliberately left at the template
    # value (0.8) here — aggressive, direction-aware denoise is only safe once
    # the Phase-1 crop-and-stitch graph confines regeneration to the garment
    # region (a whole-person mask + high denoise = more full-body drift).
    if "119" in wf:
        wf["119"]["inputs"]["expand"] = 8
        wf["119"]["inputs"]["blur_radius"] = 4
        logger.debug("Set mask grow=8/blur=4 (reduced from 20/10 to cut edge bleed)")

    return wf


# ---------------------------------------------------------------------------
# Shared job submission (used by /v1/edit/outfit AND internal callers, e.g. the
# nude-base generator in api/v1/endpoints/nude_base.py)
# ---------------------------------------------------------------------------
async def submit_outfit_edit_job(request: OutfitEditRequest, user_id: str):
    """
    Enqueue an outfit_edit job the exact way ``edit_outfit`` does — enforce the
    outfit queue cap (429), mirror the request to the notification webhook, then
    ``job_manager.create_job(..., job_type="outfit_edit")``. Returns the created
    Job; the caller shapes its own HTTP response.

    Factored so a non-request-bound internal caller (nude-base generation) reuses
    the identical submission path (same queue, same worker, same identity-locked
    head-mask + crop-stitch flow) rather than duplicating it.
    """
    job_manager = get_job_manager()

    if job_manager.is_queue_full(job_type="outfit_edit"):
        logger.warning(f"Outfit queue full, rejecting request from user {user_id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Outfit edit queue is full. Please try again later."
        )

    # Trait-aware edit: resolve identityAnchors from characterId when the caller
    # supplied an id but not explicit anchors (best-effort; never raises).
    await populate_identity_anchors(_character_store, request)

    notification_service = get_notification_service()
    if notification_service:
        await notification_service.send_request_received(user_id, request.model_dump(mode="json"))

    return await job_manager.create_job(request, user_id, job_type="outfit_edit")


# ---------------------------------------------------------------------------
# API Endpoint
# ---------------------------------------------------------------------------
@router.post(
    "/edit/outfit",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create outfit edit job",
    description="""
Submit an outfit edit request. Returns immediately with job ID for polling.

The job is queued and processed asynchronously. Use GET /v1/jobs/{jobId} to poll for status.

**Flow:**
1. Submit request with source image and outfit type
2. Receive jobId immediately (202 Accepted)
3. Poll GET /v1/jobs/{jobId} for status
4. When status is 'succeeded', access preview_url to see the image
    """,
    responses={
        202: {
            "description": "Job created successfully",
            "model": JobCreateResponse
        },
        401: {"description": "Unauthorized - Invalid or missing JWT token"},
        422: {"description": "Validation error - Invalid request body"},
        429: {"description": "Too many requests - Queue is full"},
        500: {"description": "Internal server error"}
    }
)
async def edit_outfit(
    request: OutfitEditRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Create a new outfit edit job.

    The job is queued immediately and processed asynchronously by the outfit background worker.

    **Request Body:**
    - `source_image` (required): Supabase URL of the source image
    - `outfit` (required): Outfit type to apply
    - `accessories` (optional): List of accessories (max 5)
    - `seed` (optional): Random seed for reproducibility

    **Returns:**
    - `jobId`: Unique identifier to poll for status
    - `status`: Initial status (always "queued")
    """
    user_id = current_user.get("sub", "anonymous")

    try:
        # Queue-cap check + webhook mirror + enqueue (shared with internal callers).
        job = await submit_outfit_edit_job(request, user_id)

        logger.info(
            f"Created outfit edit job {job.job_id} for user {user_id} "
            f"(outfit: {request.outfit.value}, "
            f"accessories: {[a.value for a in request.accessories] if request.accessories else []})"
        )

        return JobCreateResponse(
            jobId=job.job_id,
            status=JobStatus.QUEUED,
            reviewRequired=False
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating outfit job for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create outfit edit job. Please try again."
        )
