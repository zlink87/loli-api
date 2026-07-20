"""
Image-to-video (reel) endpoints — ADMIN ONLY.

An admin picks one of a character's existing gallery stills and generates a short
looping video clip (WAN 2.2 i2v) from it. The clip is generated asynchronously
(poll GET /v1/jobs/{jobId}), persisted to the character as a `character_images`
video row + a DRAFT `chat_persona_actions` row (is_active=false), and only shown
in chat after an admin publishes it.

Routes (all require_admin, character-scoped):
    POST /v1/characters/{character_id}/videos                       -> start generation
    GET  /v1/characters/{character_id}/videos                       -> review queue
    POST /v1/characters/{character_id}/videos/{action_id}/publish   -> publish a draft

The prompt/workflow helpers here are imported by workers/video_worker.py, mirroring
how pose_worker imports from pose.py.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.admin import require_admin
from models.enums import JobStatus
from models.requests import VideoGenerateRequest, VIDEO_DEFAULT_FPS
from models.responses import JobCreateResponse
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/characters", tags=["Reels"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py via router.configure_services)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_character_image_store = None
_motion_writer = None


def set_job_manager(job_manager) -> None:
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


def set_character_image_store(store) -> None:
    global _character_image_store
    _character_image_store = store


def set_motion_writer(writer) -> None:
    global _motion_writer
    _motion_writer = writer


def get_job_manager():
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    return _notification_service


def get_character_image_store():
    if _character_image_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reels require the Supabase DB (character image store not configured)",
        )
    return _character_image_store


def get_motion_writer():
    """The Venice-backed motion interpreter, or None when it was never wired."""
    return _motion_writer


# ---------------------------------------------------------------------------
# Motion presets + workflow-prep helpers now live in services/video_workflow.py
# so the per-character video-batch subsystem can share them without importing this
# route module. They are RE-EXPORTED here for back-compat: the reel route below and
# the test suite (tests/test_video_motion.py) still import these names from
# api.v1.endpoints.video. See services/video_workflow.py for the implementations.
# ---------------------------------------------------------------------------
from services.video_workflow import (  # noqa: F401  (re-export for back-compat)
    MOTION_DESCRIPTIONS,
    build_video_prompt,
    motion_label,
    prepare_flf2v_workflow,
    prepare_video_workflow,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post(
    "/{character_id}/videos",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a reel from a character's still (admin)",
)
async def create_video(
    character_id: str,
    request: VideoGenerateRequest,
    user: Dict[str, Any] = Depends(require_admin),
):
    job_manager = get_job_manager()
    store = get_character_image_store()
    user_id = user.get("sub", "admin")

    # Resolve + validate the chosen source still.
    still = await store.get_image(request.source_image_id)
    if not still or still.get("character_id") != character_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="source_image_id not found for this character",
        )
    if still.get("image_type") == "video":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_image_id refers to a video; pick a still image",
        )
    source_url = still.get("image_url")
    if not source_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source still has no image_url",
        )

    if job_manager.is_queue_full(job_type="video_gen"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Video generation queue is full. Please try again later.",
        )

    # Fill the server-side fields the worker needs.
    request.character_id = character_id
    request.source_image = source_url

    # Custom motion → route the free text through Venice for a WAN-friendly
    # description + button label. Falls back to the raw text when the writer is
    # unwired (None) or disabled; build_video_prompt still handles the raw text.
    if request.motionPrompt and request.motionPrompt.strip():
        writer = get_motion_writer()
        if writer is not None:
            desc, label, provider = await writer.interpret(request.motionPrompt)
            request.motionPrompt = desc
            request.motionLabel = label
            logger.info(
                f"[VIDEO] motion interpreted via {provider} for character {character_id}"
            )

    notification_service = get_notification_service()
    if notification_service:
        try:
            await notification_service.send_request_received(
                user_id, request.model_dump(mode="json")
            )
        except Exception:  # noqa: BLE001 - notification is best-effort
            pass

    job = await job_manager.create_job(request, user_id, job_type="video_gen")
    logger.info(
        f"Created video job {job.job_id} for character {character_id} "
        f"(motion: {request.motion.value}, source: {request.source_image_id})"
    )
    return JobCreateResponse(jobId=job.job_id, status=JobStatus.QUEUED, reviewRequired=True)


@router.get(
    "/{character_id}/videos",
    response_model=List[dict],
    summary="List a character's reels (drafts + published) for review (admin)",
)
async def list_videos(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_image_store()
    return await store.list_character_videos(character_id)


@router.post(
    "/{character_id}/videos/{action_id}/publish",
    summary="Publish a draft reel so it appears in chat (admin)",
)
async def publish_video(
    character_id: str,
    action_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_image_store()
    updated = await store.set_action_active(action_id, character_id, is_active=True)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reel action not found for this character",
        )
    logger.info(f"Published reel action {action_id} for character {character_id}")
    return {"actionId": action_id, "isPublished": True}
