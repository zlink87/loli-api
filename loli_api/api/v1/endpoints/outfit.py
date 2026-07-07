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
) -> dict:
    """
    Prepare the outfit workflow with injected parameters.

    Identity is preserved by construction: the GroundingDINO+SAM node (202)
    produces a *clothing-only* mask, which feeds GrowMaskWithBlur (119) ->
    InpaintModelConditioning (121). The KSampler only denoises inside that mask;
    the face, hair, skin and body pixels are composited back from the original
    encode, so they cannot drift. We only steer the mask *region* here (which is
    what the old SAM3 text prompts did); the inpaint chain is untouched.

    Key nodes in test_final_API.json:
        108    LoadImage             -> inputs.image   (source image filename)
        16     easy positive         -> inputs.positive (clothing change prompt)
        106    KSampler              -> inputs.seed
        202    GroundingDinoSAMSegment -> inputs.prompt (what region to mask)
        119    GrowMaskWithBlur      -> inputs.expand/blur_radius (mask feathering)

    The mask direction mirrors the previous SAM3 behaviour:
      - undressing (HIGH / NAKED): mask the existing clothing to remove/replace it
      - dressing (LOW): mask the bare torso/body region to cover it
      - MEDIUM / unspecified: keep the template default ("clothing, dress, ...")

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

    # Node 117: Negative prompt (quality + adult + identity preservation + user override)
    if "117" in wf:
        wf["117"]["inputs"]["negative"] = pc.edit_negative(negative_prompt)
        logger.debug("Set node 117 negative (quality + adult + identity)")

    # Node 106: Seed
    if seed is not None and "106" in wf:
        wf["106"]["inputs"]["seed"] = seed
        logger.debug(f"Set node 106 seed: {seed}")

    # Adaptive mask target (GroundingDINO+SAM text prompt) based on nudity direction.
    if nudity_level == NudityLevel.HIGH or outfit == OutfitType.NAKED:
        # Going toward nudity: mask the existing clothing so it is removed/replaced.
        if "202" in wf:
            wf["202"]["inputs"]["prompt"] = (
                "clothing, dress, shirt, top, bra, underwear, pants, skirt, shorts"
            )
            logger.debug("Segment 202: targeting clothing for removal")
    elif nudity_level == NudityLevel.LOW:
        # Dressing up (possibly from bare skin): mask the torso/body region to cover.
        if "202" in wf:
            wf["202"]["inputs"]["prompt"] = (
                "torso, chest, waist, hips, stomach, upper body"
            )
            logger.debug("Segment 202: targeting body region for dressing")
        # Widen + feather the mask for smoother dressing transitions.
        if "119" in wf:
            wf["119"]["inputs"]["expand"] = 10
            wf["119"]["inputs"]["blur_radius"] = 8
            logger.debug("Increased mask grow for dressing transition")

    # Default (MEDIUM or unspecified): keep the template's clothing prompt on node 202.

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
