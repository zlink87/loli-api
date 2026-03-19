"""
Job status endpoint.
GET /v1/jobs/{jobId} - Poll job status.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any
import logging

from models.responses import JobStatusResponse, JobResultItem, JobError
from models.enums import JobStatus
from auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Jobs"])

# These will be injected from main.py
_job_manager = None


def set_job_manager(job_manager):
    """Set the job manager instance (called from main.py)."""
    global _job_manager
    _job_manager = job_manager


def get_job_manager():
    """Get the job manager instance."""
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="""
Poll for the status of a generation job.

**Status progression:** queued -> running -> succeeded/failed

When status is 'succeeded', the response includes:
- `results`: Array with preview URLs
- `expiresAt`: When the preview URLs expire
- `promptUsed`: The generated prompt that was used
- `seedUsed`: The seed value used for generation

When status is 'failed', the response includes:
- `error`: Error details with code and message
    """,
    responses={
        200: {
            "description": "Job status retrieved",
            "model": JobStatusResponse
        },
        401: {
            "description": "Unauthorized"
        },
        404: {
            "description": "Job not found"
        }
    }
)
async def get_job_status(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Retrieve the current status of a job.

    **Parameters:**
    - `job_id`: The job identifier returned from POST /v1/generate/image

    **Returns:**
    - Full job status including progress, results (if completed), and error details (if failed)

    **Note:** Jobs are scoped to the authenticated user. You can only access your own jobs.
    """
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    # Get job (with ownership check)
    job = await job_manager.get_job_for_user(job_id, user_id)

    if not job:
        # Check if job exists but belongs to another user
        job_exists = await job_manager.get_job(job_id)
        if job_exists:
            logger.warning(f"User {user_id} tried to access job {job_id} owned by {job_exists.user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found"
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    # Build response
    response = JobStatusResponse(
        jobId=job.job_id,
        type=job.job_type,
        status=job.status,
        progress=job.progress,
        reviewRequired=(job.job_type == "text_to_image"),
        createdAt=job.created_at,
        updatedAt=job.updated_at
    )

    # Add results if succeeded
    if job.status == JobStatus.SUCCEEDED and job.preview_url:
        response.results = [
            JobResultItem(
                type="image",
                previewUrl=job.preview_url,
                sha256=job.image_hash
            )
        ]
        response.expiresAt = job.preview_expires_at
        response.promptUsed = job.prompt_used
        response.seedUsed = job.seed_used

    # Add error if failed
    elif job.status == JobStatus.FAILED:
        response.error = JobError(
            code=job.error_code or "UNKNOWN_ERROR",
            message=job.error_message or "An unknown error occurred"
        )

    # Add metadata for running jobs
    elif job.status == JobStatus.RUNNING:
        response.promptUsed = job.prompt_used
        response.seedUsed = job.seed_used

    return response


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a queued job",
    description="Cancel a job that is still in the queue. Running jobs cannot be cancelled.",
    responses={
        204: {
            "description": "Job cancelled successfully"
        },
        400: {
            "description": "Job cannot be cancelled (not in queued state)"
        },
        401: {
            "description": "Unauthorized"
        },
        404: {
            "description": "Job not found"
        }
    }
)
async def cancel_job(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Cancel a queued job.

    **Note:** Only jobs in 'queued' status can be cancelled.
    Jobs that are already running or completed cannot be cancelled.
    """
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    success = await job_manager.cancel_job(job_id, user_id)

    if not success:
        job = await job_manager.get_job_for_user(job_id, user_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job cannot be cancelled (status: {job.status.value})"
        )

    logger.info(f"Job {job_id} cancelled by user {user_id}")
    return None
