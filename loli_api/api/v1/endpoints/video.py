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
import copy
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.admin import require_admin
from models.enums import MotionType, JobStatus
from models.requests import VideoGenerateRequest, VIDEO_DEFAULT_FPS
from models.responses import JobCreateResponse
from services import prompt_constants as pc
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/characters", tags=["Reels"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py via router.configure_services)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_character_image_store = None


def set_job_manager(job_manager) -> None:
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


def set_character_image_store(store) -> None:
    global _character_image_store
    _character_image_store = store


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


# ---------------------------------------------------------------------------
# Motion presets — text descriptions injected into the WAN positive prompt.
# ---------------------------------------------------------------------------
MOTION_DESCRIPTIONS: Dict[MotionType, str] = {
    MotionType.SUBTLE_IDLE: "subtle idle motion, gentle breathing, slight head movement, static camera",
    MotionType.SLOW_TURN: "slowly turning head and shoulders toward the camera, smooth motion",
    MotionType.HAIR_IN_WIND: "hair flowing gently in the wind, soft fabric movement, cinematic slow motion",
    MotionType.HAIR_FLIP: "playfully flipping hair back over the shoulder, smooth natural motion",
    MotionType.BLOW_KISS: "smiling warmly and blowing a kiss toward the camera, gentle motion",
    MotionType.WAVE: "waving a hand at the camera with a warm friendly smile",
    MotionType.WALK_TOWARD: "walking slowly toward the camera, confident smooth motion",
    MotionType.LOOK_OVER_SHOULDER: "glancing back over the shoulder toward the camera, subtle turn",
}

_MAX_LABEL_LEN = 40


def motion_label(motion: MotionType) -> str:
    """Short human caption for the chat quick-action button."""
    text = motion.value.replace("_", " ").title()
    return text[:_MAX_LABEL_LEN]


def build_video_prompt(motion: MotionType, extra: Optional[str] = None) -> str:
    """Compose the WAN positive prompt from a motion preset + identity clause."""
    desc = MOTION_DESCRIPTIONS.get(motion, "subtle natural motion, static camera")
    prompt = f"{desc}. {pc.VIDEO_CONSISTENCY_CLAUSE}."
    if extra and extra.strip():
        prompt = f"{extra.strip()}. {prompt}"
    return prompt


def prepare_video_workflow(
    template: dict,
    source_image: str,
    prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    length: Optional[int] = None,
    fps: Optional[int] = None,
) -> dict:
    """
    Prepare the WAN 2.2 i2v workflow (workflows/wan_i2v.json) by mutating the
    pinned anchor node IDs. Mirrors prepare_pose_workflow (deep-copy + guarded
    writes).

    Anchor nodes:
        52  LoadImage        -> inputs.image  (start frame)
        6   CLIPTextEncode   -> inputs.text   (positive / motion prompt)
        7   CLIPTextEncode   -> inputs.text   (negative)
        50  WanImageToVideo  -> inputs.width/height/length
        57  KSamplerAdvanced -> inputs.noise_seed  (high-noise expert)
        58  KSamplerAdvanced -> inputs.noise_seed  (low-noise expert)
        60  VHS_VideoCombine -> inputs.frame_rate
    """
    wf = copy.deepcopy(template)

    if "52" in wf:
        wf["52"]["inputs"]["image"] = source_image

    if prompt is not None and "6" in wf:
        wf["6"]["inputs"]["text"] = prompt

    if negative_prompt is not None and "7" in wf:
        wf["7"]["inputs"]["text"] = negative_prompt

    if "50" in wf:
        if width is not None:
            wf["50"]["inputs"]["width"] = width
        if height is not None:
            wf["50"]["inputs"]["height"] = height
        if length is not None:
            wf["50"]["inputs"]["length"] = length

    # Seed both experts (high-noise then low-noise) so the clip is reproducible.
    if seed is not None:
        for nid in ("57", "58"):
            if nid in wf:
                wf[nid]["inputs"]["noise_seed"] = seed

    if fps is not None and "60" in wf:
        wf["60"]["inputs"]["frame_rate"] = fps

    return wf


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
