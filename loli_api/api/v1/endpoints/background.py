"""
Background/scene edit endpoint.
POST /v1/edit/background - Create async background edit job using ComfyUI workflow.

Uses the SAME workflow template as outfit editing (test_final_API.json),
but overrides the SAM3 text prompts to target background/scene instead of
body/clothes, and uses a scene-oriented positive prompt.
"""
import copy
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import get_current_user
from models.enums import JobStatus
from models.requests import BackgroundEditRequest
from models.responses import JobCreateResponse
from services.notification_service import NotificationService
from services import prompt_constants as pc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Background Edit"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_background_workflow_path: Optional[str] = None
_background_workflow_template: Optional[dict] = None


# ---------------------------------------------------------------------------
# Service configuration functions (called from main.py via router)
# ---------------------------------------------------------------------------
def set_job_manager(job_manager) -> None:
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


def set_background_workflow_path(workflow_path: str) -> None:
    """Set and load background workflow template (same file as outfit)."""
    global _background_workflow_path, _background_workflow_template
    _background_workflow_path = workflow_path
    try:
        with open(workflow_path, 'r', encoding='utf-8') as f:
            _background_workflow_template = json.load(f)
        logger.info(f"Loaded background workflow template: {workflow_path}")
    except Exception as e:
        logger.error(f"Failed to load background workflow: {e}")
        _background_workflow_template = None


def get_job_manager():
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    return _notification_service


# ---------------------------------------------------------------------------
# Helper functions (used by BackgroundEditWorker and PipelineWorker via import)
# ---------------------------------------------------------------------------
def build_background_prompt(prompt: str) -> str:
    """
    Build the positive prompt for environment/scene editing.
    Conceptualized as "environment change" — the person stays identical but
    lighting/shadows adapt naturally to the new scene.

    Args:
        prompt: User-provided scene/environment description

    Returns:
        Complete prompt string for the workflow
    """
    prompt_parts = [
        f"Change the environment and background to: {prompt}",
        pc.identity_clause("the background and surroundings"),
        "adapt lighting and shadows on the person to match the new environment naturally",
        "blend the person seamlessly into the new scene",
    ]
    return ", ".join(prompt_parts)


def prepare_background_workflow(
    template: dict,
    image_name: str,
    prompt: str,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> dict:
    """
    Prepare the environment/scene workflow with injected parameters.

    Uses the same template as outfit (test_final_API.json), but masks the
    *person* and inverts it so the inpaint region is the BACKGROUND. The person
    (face, hair, body, outfit) is composited back untouched from the original
    encode, so identity cannot drift while the scene changes.

    Rewiring vs. the outfit default:
        202  GroundingDinoSAMSegment -> prompt = the PERSON (segment the subject)
        204  InvertMask              -> already inverts node 202's person mask
        119  GrowMaskWithBlur.mask   -> repointed to node 204 (inverted = background)

    Injected nodes:
        108  LoadImage         -> inputs.image    (source image filename)
        16   easy positive     -> inputs.positive (scene change prompt)
        106  KSampler          -> inputs.seed
        119  GrowMaskWithBlur  -> expand/blur_radius (mask feathering)

    Args:
        template: Base workflow template (same as outfit)
        image_name: ComfyUI image filename
        prompt: Positive prompt (already built via build_background_prompt)
        seed: Optional seed value
        negative_prompt: Optional negative prompt override

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

    # Node 117: Negative prompt (quality + identity preservation + user override)
    if "117" in wf:
        wf["117"]["inputs"]["negative"] = pc.edit_negative(negative_prompt)
        logger.debug("Set node 117 negative (quality + identity)")

    # Node 106: Seed
    if seed is not None and "106" in wf:
        wf["106"]["inputs"]["seed"] = seed
        logger.debug(f"Set node 106 seed: {seed}")

    # Segment the PERSON (node 202) instead of the clothing. Single robust term —
    # GroundingDINO expects period-separated phrases and "person" alone boxes the
    # full subject; node 204 inverts it so the inpaint region is the background
    # and the person (incl. face/hair) is composited back untouched.
    if "202" in wf:
        wf["202"]["inputs"]["prompt"] = "person"
        logger.debug("Set node 202: person detection (for inverted background mask)")

    # Node 211 (head-protect mask) is unused on the background path (the whole
    # person is protected), but LoadImage validates file existence — point it at
    # the source file so validation passes without staging a mask.
    if "211" in wf:
        wf["211"]["inputs"]["image"] = image_name

    # Repoint the grow/blur mask to the INVERTED person mask (node 204) so the
    # inpaint region is the background, not the subject. Falls back silently if
    # the node is absent (e.g. an older template without node 204).
    if "119" in wf and "204" in wf:
        wf["119"]["inputs"]["mask"] = ["204", 0]
        logger.debug("Repointed node 119 mask -> inverted person mask (background)")

    # Increase mask feathering for smoother person-to-scene blending.
    if "119" in wf:
        wf["119"]["inputs"]["expand"] = 10
        wf["119"]["inputs"]["blur_radius"] = 10
        logger.debug("Increased mask feathering for environment blending")

    return wf


# ---------------------------------------------------------------------------
# API Endpoint
# ---------------------------------------------------------------------------
@router.post(
    "/edit/background",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create background edit job",
    description="""
Submit a background/scene edit request. Returns immediately with job ID for polling.

The job is queued and processed asynchronously. Use GET /v1/jobs/{jobId} to poll for status.

**Flow:**
1. Submit request with source image and scene/background prompt
2. Receive jobId immediately (202 Accepted)
3. Poll GET /v1/jobs/{jobId} for status
4. When status is 'succeeded', access preview_url to see the image
    """,
    responses={
        202: {"description": "Job created successfully", "model": JobCreateResponse},
        401: {"description": "Unauthorized - Invalid or missing JWT token"},
        422: {"description": "Validation error - Invalid request body"},
        429: {"description": "Too many requests - Queue is full"},
        500: {"description": "Internal server error"},
    },
)
async def edit_background(
    request: BackgroundEditRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Create a new background/scene edit job.

    The job is queued immediately and processed asynchronously by the
    background edit worker.
    """
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    try:
        if job_manager.is_queue_full(job_type="background_edit"):
            logger.warning(
                f"Background edit queue full, rejecting request from user {user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Background edit queue is full. Please try again later.",
            )

        # Log payload
        notification_service = get_notification_service()
        if notification_service:
            payload_dict = request.model_dump(mode="json")
            await notification_service.send_request_received(user_id, payload_dict)

        # Create job
        job = await job_manager.create_job(
            request, user_id, job_type="background_edit"
        )

        logger.info(
            f"Created background edit job {job.job_id} for user {user_id} "
            f"(prompt: {request.prompt[:60]}...)"
        )

        return JobCreateResponse(
            jobId=job.job_id,
            status=JobStatus.QUEUED,
            reviewRequired=False,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error creating background job for user {user_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create background edit job. Please try again.",
        )
