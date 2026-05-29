"""
Pose edit endpoint.
POST /v1/edit/pose - Create async pose edit job using ComfyUI workflow.
"""
import copy
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import get_current_user
from models.enums import PoseType, JobStatus
from models.requests import PoseEditRequest
from models.responses import JobCreateResponse
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pose Edit"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_pose_workflow_path: Optional[str] = None
_pose_workflow_template: Optional[dict] = None


# ---------------------------------------------------------------------------
# Pose Reference Images - Maps pose types to ComfyUI input filenames
# These files should exist in the ComfyUI input directory under poses/
# ---------------------------------------------------------------------------
POSE_DESCRIPTIONS: Dict[PoseType, str] = {
    PoseType.STANDING_LEANING: "standing and leaning against a wall or surface, relaxed casual pose",
    PoseType.SITTING: "sitting upright on a chair or seat, legs together, relaxed posture",
    PoseType.SITTING_LEGS_WIDE_OPEN: "sitting with legs spread wide open, provocative seated pose",
    PoseType.SOFA: "sitting comfortably on a sofa, relaxed, leaning back slightly",
    PoseType.LYING_BACK: "lying on her back on a bed or soft surface, relaxed, looking up",
    PoseType.LYING_STOMACH: "lying face down on her stomach, head turned to one side",
    PoseType.KNEELING: "kneeling on the ground or bed, upright torso, knees apart",
    PoseType.BENDING_OVER: "bending over at the waist, looking back over shoulder",
    PoseType.HANDS_BEHIND_HEAD: "standing with hands behind head, chest out, confident pose",
    PoseType.SQUATTING: "squatting down low, knees bent wide, balanced posture",
    PoseType.ALL_FOURS: "on all fours, hands and knees on the ground or bed",
    PoseType.SPREAD_LEGS: "lying back or sitting with legs spread wide apart",
    PoseType.EATING: "sitting at a table eating, casual everyday pose",
    PoseType.JOGGING: "jogging or running, dynamic motion pose",
    PoseType.OPENING_FRIDGE: "standing and reaching into an open refrigerator",
    PoseType.COOKING: "standing in a kitchen cooking, hands busy with food preparation",
}

POSE_REFERENCES: Dict[PoseType, str] = {
    PoseType.STANDING_LEANING: "poses/standing_leaning.png",
    PoseType.SITTING: "poses/Sitting.jpeg",
    PoseType.SITTING_LEGS_WIDE_OPEN: "poses/sitting_legs_wide_open.png",
    PoseType.SOFA: "poses/sofa.jpeg",
    PoseType.LYING_BACK: "poses/lying_back.png",
    PoseType.LYING_STOMACH: "poses/lying_stomach.png",
    PoseType.KNEELING: "poses/kneeling.png",
    PoseType.BENDING_OVER: "poses/bending_over.png",
    PoseType.HANDS_BEHIND_HEAD: "poses/hands_behind_head.png",
    PoseType.SQUATTING: "poses/squatting.jpeg",
    PoseType.ALL_FOURS: "poses/all_fours.png",
    PoseType.SPREAD_LEGS: "poses/spread_legs.png",
    PoseType.EATING: "poses/eating.jpeg",
    PoseType.JOGGING: "poses/jogging.jpg",
    PoseType.OPENING_FRIDGE: "poses/opening_fridge.jpeg",
    PoseType.COOKING: "poses/cooking.png",
}


# ---------------------------------------------------------------------------
# Service configuration functions (called from main.py via router)
# ---------------------------------------------------------------------------
def set_job_manager(job_manager) -> None:
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


def set_pose_workflow_path(workflow_path: str) -> None:
    global _pose_workflow_path, _pose_workflow_template
    _pose_workflow_path = workflow_path
    try:
        with open(workflow_path, 'r', encoding='utf-8') as f:
            _pose_workflow_template = json.load(f)
        logger.info(f"Loaded pose workflow template: {workflow_path}")
    except Exception as e:
        logger.error(f"Failed to load pose workflow: {e}")
        _pose_workflow_template = None


def get_job_manager():
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    return _notification_service


# ---------------------------------------------------------------------------
# Helper functions (used by PoseBackgroundWorker via import)
# ---------------------------------------------------------------------------
def build_pose_prompt(pose: PoseType) -> str:
    """
    Build a dynamic text prompt for the pose workflow based on pose type.

    Args:
        pose: The pose type

    Returns:
        A descriptive prompt string for the ComfyUI workflow
    """
    desc = POSE_DESCRIPTIONS.get(pose, "natural pose")
    return (
        f"Make the person in image 1 do the exact same pose of the person in image 2. "
        f"The target pose is: {desc}. "
        f"Keep the original appearance, body proportion, skin type, facial features, "
        f"hair style, hair color, and outfit from image 1. "
        f"The new pose should match image 2 accurately. "
        f"Adapt the background and environment to suit the pose naturally."
    )


def get_pose_reference(pose: PoseType) -> str:
    """
    Get the reference image filename for a pose.

    Args:
        pose: The pose type

    Returns:
        ComfyUI input filename for the reference pose image
    """
    ref = POSE_REFERENCES.get(pose)
    if not ref:
        raise ValueError(f"No reference image for pose: {pose.value}")
    return ref


def prepare_pose_workflow(
    template: dict,
    source_image: str,
    reference_image: str,
    prompt: Optional[str] = None,
    seed: Optional[int] = None,
) -> dict:
    """
    Prepare the pose workflow with injected parameters.

    Workflow nodes:
        109  LoadImage  -> inputs.image  (source character image = image1)
        170  LoadImage  -> inputs.image  (reference pose image = image2)
        114  CLIPTextEncode (or similar) -> inputs.prompt  (text prompt)
        3    KSampler   -> inputs.seed

    Args:
        template: Base workflow template
        source_image: ComfyUI filename for source character image
        reference_image: ComfyUI filename for reference pose image
        prompt: Optional text prompt to inject into node 114
        seed: Optional seed value

    Returns:
        Prepared workflow dict
    """
    wf = copy.deepcopy(template)

    # Node 109: Source character image
    if "109" in wf:
        wf["109"]["inputs"]["image"] = source_image
        logger.debug(f"Set node 109 source image: {source_image}")

    # Node 170: Reference pose image
    if "170" in wf:
        wf["170"]["inputs"]["image"] = reference_image
        logger.debug(f"Set node 170 reference image: {reference_image}")

    # Node 114: Text prompt
    if prompt is not None and "114" in wf:
        wf["114"]["inputs"]["prompt"] = prompt
        logger.debug(f"Set node 114 prompt: {prompt[:80]}...")

    # Node 3: Seed + quality bump.
    if "3" in wf:
        if seed is not None:
            wf["3"]["inputs"]["seed"] = seed
            logger.debug(f"Set node 3 seed: {seed}")
        # Bump steps for fewer artifacts (was 4; 6 gives cleaner results on Qwen edit).
        try:
            if int(wf["3"]["inputs"].get("steps", 0)) < 6:
                wf["3"]["inputs"]["steps"] = 6
                logger.debug("Bumped pose KSampler steps to 6")
        except (TypeError, ValueError):
            pass

    return wf


# ---------------------------------------------------------------------------
# API Endpoint
# ---------------------------------------------------------------------------
@router.post(
    "/edit/pose",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create pose edit job",
    description="""
Submit a pose edit request. Returns immediately with job ID for polling.

The job is queued and processed asynchronously. Use GET /v1/jobs/{jobId} to poll for status.

**Flow:**
1. Submit request with source image and target pose
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
async def edit_pose(
    request: PoseEditRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    try:
        if job_manager.is_queue_full(job_type="pose_edit"):
            logger.warning(f"Pose queue full, rejecting request from user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Pose edit queue is full. Please try again later.",
            )

        # Validate reference image exists for the pose
        try:
            get_pose_reference(request.pose)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )

        # Log payload
        notification_service = get_notification_service()
        if notification_service:
            payload_dict = request.model_dump(mode="json")
            await notification_service.send_request_received(user_id, payload_dict)

        # Create job
        job = await job_manager.create_job(request, user_id, job_type="pose_edit")

        logger.info(
            f"Created pose edit job {job.job_id} for user {user_id} "
            f"(pose: {request.pose.value})"
        )

        return JobCreateResponse(
            jobId=job.job_id,
            status=JobStatus.QUEUED,
            reviewRequired=False,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating pose job for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create pose edit job. Please try again.",
        )
