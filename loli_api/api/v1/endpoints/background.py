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
from models.enums import JobStatus, NudityLevel
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
    nudity_level: Optional[NudityLevel] = None,
    denoise: Optional[float] = None,
    solo_subject: bool = False,
    person_threshold: float = 0.0,
) -> dict:
    """
    Prepare the environment/scene workflow with injected parameters.

    Uses the same template as outfit (test_final_API.json), but masks the
    *person* and inverts it so the inpaint region is the BACKGROUND. Node 121
    runs with noise_mask=true (sampler only touches the inverted/background
    region) and node 220 composites the sampled pixels back onto the original
    source using that same mask, so the person (face, hair, body, outfit) is
    byte-identical to the source and cannot drift while the scene changes.
    ReActorFaceSwap (210) is disabled — redundant once composite-back holds
    the face pixels exactly, and was a source of over-restored/waxy skin.

    Rewiring vs. the outfit default:
        202  GroundingDinoSAMSegment -> prompt = the PERSON (segment the subject)
        204  InvertMask              -> already inverts node 202's person mask
        119  GrowMaskWithBlur.mask   -> repointed to node 204 (inverted = background)

    Injected nodes:
        108  LoadImage         -> inputs.image    (source image filename)
        16   easy positive     -> inputs.positive (scene change prompt)
        106  KSampler          -> inputs.seed, optional inputs.denoise override
        117  easy negative     -> inputs.negative (quality/adult/identity/nudity)
        119  GrowMaskWithBlur  -> expand/blur_radius (mask feathering)
        202  GroundingDinoSAMSegment -> optional inputs.threshold raise (solo subject)

    Args:
        template: Base workflow template (same as outfit)
        image_name: ComfyUI image filename
        prompt: Positive prompt (already built via build_background_prompt)
        seed: Optional seed value
        negative_prompt: Optional negative prompt override
        nudity_level: Optional nudity level (keeps exposure from creeping up
            across a chained outfit->background->pose batch item)
        denoise: Optional KSampler (node 106) denoise override, 0.5-1.0. Higher =
            the new backdrop overrides the source scene more strongly. None leaves
            the template's baked value (~0.80). The template samples at cfg 1.0, so
            a clean solo backdrop needs the extra removal strength here rather than
            from the (inert) negatives.
        solo_subject: When True AND ``person_threshold`` > 0, raise node 202's
            GroundingDINO confidence threshold to ``person_threshold`` so low-
            confidence background people drop OUT of the protected person mask and
            get painted over. FAIL-OPEN: if the MAIN subject scores below the
            threshold the whole frame becomes editable — only pass True for admin-
            reviewed assets (the nude base). Default False leaves node 202 untouched.
        person_threshold: The confidence threshold applied to node 202 when
            ``solo_subject`` is True (typically ``settings.SOLO_BG_PERSON_THRESHOLD``,
            resolved by the caller). 0.0 (default) = disabled — no change even when
            ``solo_subject`` is True.

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

    # Node 117: Negative prompt (quality + identity preservation + nudity + user override)
    if "117" in wf:
        wf["117"]["inputs"]["negative"] = pc.edit_negative(negative_prompt, nudity_level=nudity_level)
        logger.debug("Set node 117 negative (quality + identity + nudity)")

    # Node 106: Seed
    if seed is not None and "106" in wf:
        wf["106"]["inputs"]["seed"] = seed
        logger.debug(f"Set node 106 seed: {seed}")

    # Node 106: denoise override. The V1 template bakes denoise 0.8 and samples at
    # cfg 1.0 (negatives inert), so clearing a busy source scene to a clean backdrop
    # relies on a stronger denoise here rather than on the (mathematically inert)
    # negatives. None leaves the baked value untouched (unchanged legacy behavior).
    if denoise is not None and "106" in wf:
        wf["106"]["inputs"]["denoise"] = denoise
        logger.debug(f"Set node 106 denoise override: {denoise}")

    # Segment the PERSON (node 202) instead of the clothing. Single robust term —
    # GroundingDINO expects period-separated phrases and "person" alone boxes the
    # full subject; node 204 inverts it so the inpaint region is the background
    # and the person (incl. face/hair) is composited back untouched.
    if "202" in wf:
        wf["202"]["inputs"]["prompt"] = "person"
        logger.debug("Set node 202: person detection (for inverted background mask)")

        # Solo-subject (nude base / admin-reviewed assets): raise node 202's
        # GroundingDINO confidence threshold so low-confidence background passersby
        # drop OUT of the protected person mask and get painted over by the new
        # backdrop. Conjunction-gated (both the per-request flag AND a configured
        # env threshold) and FAIL-OPEN — see the docstring. Default off: the
        # template threshold (0.3) is left exactly as-is.
        if solo_subject and person_threshold > 0:
            wf["202"]["inputs"]["threshold"] = person_threshold
            logger.debug(
                f"Solo-subject: raised node 202 person threshold -> {person_threshold}"
            )

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
