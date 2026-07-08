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
from services import prompt_constants as pc
from services.outfit_vocab import OUTFIT_DESCRIPTIONS, ACCESSORY_DESCRIPTIONS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Outfit Edit"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_outfit_workflow_path: Optional[str] = None
_outfit_workflow_template: Optional[dict] = None



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


def build_prompt(outfit: OutfitType, accessories: Optional[List[AccessoryType]], nudity_level: NudityLevel = NudityLevel.LOW) -> str:
    """
    Build the positive prompt from outfit and accessories.
    Ensures the person's face, hair, and physical features are never altered.

    Args:
        outfit: The outfit type
        accessories: Optional list of accessories
        nudity_level: Nudity level (low, medium, high)

    Returns:
        Complete prompt string
    """
    outfit_levels = OUTFIT_DESCRIPTIONS.get(outfit)
    if outfit_levels:
        outfit_desc = outfit_levels.get(nudity_level, outfit_levels[NudityLevel.LOW])
    else:
        outfit_desc = str(outfit.value)

    if outfit == OutfitType.NAKED:
        prompt_parts = [
            f"Remove all clothing, the person should be {outfit_desc}",
            pc.identity_clause("the clothing and covering"),
            "only change the clothing and covering, nothing else",
        ]
    else:
        prompt_parts = [
            _outfit_change_lead(outfit, outfit_desc),
            pc.identity_clause("the outfit and clothing"),
            "only change the clothing, nothing else",
        ]

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
    wf["106"]["inputs"]["denoise"] = 0.80

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
) -> dict:
    """
    Prepare the outfit workflow with injected parameters.

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
            source_dressed=source_dressed,
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
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    try:
        # Check queue capacity
        if job_manager.is_queue_full(job_type="outfit_edit"):
            logger.warning(f"Outfit queue full, rejecting request from user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Outfit edit queue is full. Please try again later."
            )

        # Send payload to Google Chat webhook for logging
        notification_service = get_notification_service()
        if notification_service:
            payload_dict = request.model_dump(mode="json")
            await notification_service.send_request_received(user_id, payload_dict)

        # Create job
        job = await job_manager.create_job(request, user_id, job_type="outfit_edit")

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
