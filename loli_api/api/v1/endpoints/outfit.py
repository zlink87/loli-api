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


def prepare_outfit_workflow(
    template: dict,
    image_name: str,
    prompt: str,
    seed: Optional[int] = None,
    nudity_level: Optional[NudityLevel] = None,
    outfit: Optional[OutfitType] = None,
    negative_prompt: Optional[str] = None,
    head_mask_name: Optional[str] = None,
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
    # Widen the mask edge so new garment silhouettes (collars, straps, hemlines,
    # sleeves) have room to render without being clipped at the mask boundary.
    # Safe at any nudity level now that node 121 does a real masked edit with
    # pixel-exact composite-back (node 220) — over-masking no longer risks
    # unmasked drift the way it did under the old green-overlay-only config.
    if "119" in wf:
        wf["119"]["inputs"]["expand"] = 20
        wf["119"]["inputs"]["blur_radius"] = 10
        logger.debug("Increased mask grow/blur for outfit silhouette headroom")

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
