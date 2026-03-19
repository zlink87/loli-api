"""
Image generation endpoint.
POST /v1/generate/image - Create character image generation job.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional
import logging

from models.requests import GenerateImageRequest
from models.responses import JobCreateResponse
from models.enums import JobStatus
from auth.dependencies import get_current_user
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Generation"])

# These will be injected from main.py
_job_manager = None
_notification_service: Optional[NotificationService] = None


def set_job_manager(job_manager):
    """Set the job manager instance (called from main.py)."""
    global _job_manager
    _job_manager = job_manager


def set_notification_service(notification_service: NotificationService):
    """Set the notification service instance (called from main.py)."""
    global _notification_service
    _notification_service = notification_service


def get_job_manager():
    """Get the job manager instance."""
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    """Get the notification service instance."""
    return _notification_service


@router.post(
    "/generate/image",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create character image generation job",
    description="""
Submit a character creation request. Returns immediately with job ID for polling.

The job is queued and processed asynchronously. Use GET /v1/jobs/{jobId} to poll for status.

**Flow:**
1. Submit request with persona parameters
2. Receive jobId immediately (202 Accepted)
3. Poll GET /v1/jobs/{jobId} for status
4. When status is 'succeeded', access preview_url to see the image
    """,
    responses={
        202: {
            "description": "Job created successfully",
            "model": JobCreateResponse
        },
        401: {
            "description": "Unauthorized - Invalid or missing JWT token"
        },
        422: {
            "description": "Validation error - Invalid request body"
        },
        429: {
            "description": "Too many requests - Queue is full"
        },
        500: {
            "description": "Internal server error"
        }
    }
)
async def create_generate_job(
    request: GenerateImageRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Create a new image generation job.

    The job is queued immediately and processed asynchronously by the background worker.
    The generated prompt is created using xAI Grok-4 based on the persona parameters.

    **Request Body:**
    - `persona` (required): Character persona configuration
    - `prompt` (optional): Additional prompt text
    - `negativePrompt` (optional): Negative prompt additions
    - `output` (optional): Output configuration (resolution, seed, etc.)

    **Returns:**
    - `jobId`: Unique identifier to poll for status
    - `status`: Initial status (always "queued")
    - `reviewRequired`: Whether the result needs review before saving
    """
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    try:
        # Check queue capacity
        if job_manager.is_queue_full():
            logger.warning(f"Queue full, rejecting request from user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Job queue is full. Please try again later."
            )

        # Validate persona age >= 18 (already validated by Pydantic, but double-check)
        if request.persona.age < 18:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Age must be at least 18"
            )

        # Send payload to Google Chat webhook for logging
        notification_service = get_notification_service()
        if notification_service:
            payload_dict = request.model_dump(mode="json")
            await notification_service.send_request_received(user_id, payload_dict)

        # Create job
        job = await job_manager.create_job(request, user_id)

        logger.info(
            f"Created job {job.job_id} for user {user_id} "
            f"(character: {request.persona.name}, "
            f"style: {request.persona.style.value})"
        )

        return JobCreateResponse(
            jobId=job.job_id,
            status=JobStatus.QUEUED,
            reviewRequired=True
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating job for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create job. Please try again."
        )
