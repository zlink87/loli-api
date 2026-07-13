"""
Unified pipeline edit endpoint.
POST /v1/edit - Create async pipeline edit job that chains pose, outfit,
and background steps in configurable order.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import get_current_user
from models.enums import JobStatus
from models.requests import PipelineEditRequest
from models.responses import JobCreateResponse
from services import pose_assets
from services.character_anchors import populate_identity_anchors
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pipeline Edit"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py via configure_services)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
# Optional (Supabase-gated) character store, wired in router.configure_services.
# Used only to auto-populate identityAnchors from PipelineEditRequest.characterId;
# None (store not configured) degrades gracefully — see populate_identity_anchors.
_character_store = None


def set_job_manager(job_manager) -> None:
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


def set_character_store(store) -> None:
    """Set the (optional) character store used to resolve identityAnchors."""
    global _character_store
    _character_store = store


def get_job_manager():
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    return _notification_service


# ---------------------------------------------------------------------------
# Shared job submission (used by POST /v1/edit AND internal callers, e.g. the
# nude-base generator in api/v1/endpoints/nude_base.py)
# ---------------------------------------------------------------------------
async def submit_pipeline_edit_job(request: PipelineEditRequest, user_id: str):
    """
    Enqueue a pipeline_edit job the exact way ``pipeline_edit`` does — validate
    the pose reference (if a pose step is requested), enforce the pipeline
    queue cap (429), mirror the request to the notification webhook, then
    ``job_manager.create_job(..., job_type="pipeline_edit")``. Returns the
    created Job; the caller shapes its own HTTP response.

    Factored so a non-request-bound internal caller (nude-base generation)
    reuses the identical submission path — same queue, same worker, same
    outfitDenoise/outfitPromptMode/lighting plumbing — rather than duplicating it.
    """
    job_manager = get_job_manager()

    if request.pose is not None and not pose_assets.asset_path(request.pose).exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Pose reference not installed for pose '{request.pose.value}'. "
                f"Run scripts/generate_pose_refs.py."
            ),
        )

    if job_manager.is_queue_full(job_type="pipeline_edit"):
        logger.warning(f"Pipeline queue full, rejecting request from user {user_id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Pipeline edit queue is full. Please try again later.",
        )

    # Trait-aware edit: resolve identityAnchors from characterId when a standalone
    # caller supplied an id but not explicit anchors (best-effort; never raises).
    # Batch items already arrive with identityAnchors set by scene_mapper, so this
    # is a no-op for them. pipeline_worker consumes request.identityAnchors.
    await populate_identity_anchors(_character_store, request)

    notification_service = get_notification_service()
    if notification_service:
        await notification_service.send_request_received(user_id, request.model_dump(mode="json"))

    return await job_manager.create_job(request, user_id, job_type="pipeline_edit")


# ---------------------------------------------------------------------------
# API Endpoint
# ---------------------------------------------------------------------------
@router.post(
    "/edit",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create unified pipeline edit job",
    description="""
Submit a unified edit request that can combine pose, outfit, and background
editing steps in a single pipeline. Returns immediately with a job ID for polling.

**Pipeline order** (default: pose -> outfit -> background):
- Only steps with provided parameters will run.
- Override the order with the `pipeline_order` field.

**Flow:**
1. Submit request with source image and at least one step parameter
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
async def pipeline_edit(
    request: PipelineEditRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Create a new unified pipeline edit job.

    The job is queued immediately and processed asynchronously by the
    pipeline background worker, which chains the requested steps.
    """
    user_id = current_user.get("sub", "anonymous")

    try:
        job = await submit_pipeline_edit_job(request, user_id)

        # Build summary of active steps
        active = []
        if request.pose is not None:
            active.append(f"pose={request.pose.value}")
        if request.outfit is not None:
            active.append(f"outfit={request.outfit.value}")
        if request.prompt is not None:
            active.append("background")

        logger.info(
            f"Created pipeline edit job {job.job_id} for user {user_id} "
            f"(steps: {', '.join(active)})"
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
            f"Error creating pipeline job for user {user_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create pipeline edit job. Please try again.",
        )
