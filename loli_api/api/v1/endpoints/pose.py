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
from services import pose_assets
from services import prompt_constants as pc
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
# Pose Descriptions - Text descriptions of each target pose, injected into the
# workflow prompt (node 114). The reference image itself is resolved and shipped
# per-request via services/pose_assets.py (worker_filename -> node 170).
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
def build_pose_prompt(
    pose: PoseType,
    activity: Optional[str] = None,
    expression: Optional[str] = None,
) -> str:
    """
    Build a dynamic text prompt for the pose workflow based on pose type.

    Args:
        pose: The pose type
        activity: Optional identity-free action phrase (e.g. SceneSpec.activity,
            routed here by scene_mapper when a pose step is active) appended as
            ", while {activity}". None = unchanged base prompt (interactive
            /v1/edit/pose never sets this).
        expression: Optional facial expression/mood (e.g. SceneSpec.expression)
            appended as ", {expression} expression". Expression/mood ONLY — never
            facial features. Has no effect on non-posed items: the face there is
            byte-locked by the composite-back in prepare_outfit_workflow, so
            there is nothing for a prompted expression to act on outside a pose
            step. None = unchanged base prompt.

    Returns:
        A descriptive prompt string for the ComfyUI workflow
    """
    desc = POSE_DESCRIPTIONS.get(pose, "natural pose")
    clause = pc.pose_identity_clause()
    prompt = (
        f"Make the person in image 1 do the exact same pose of the person in image 2. "
        f"The target pose is: {desc}. {clause}. "
        f"The new pose should match image 2 accurately. "
        f"Adapt the background and environment to suit the pose naturally."
    )
    if activity and activity.strip():
        prompt += f", while {activity.strip()}"
    if expression and expression.strip():
        prompt += f", {expression.strip()} expression"
    return prompt


def get_pose_reference(pose: PoseType) -> str:
    """
    Get the reference image filename (flat name) for a pose.

    The actual PNG bytes are shipped per-request as a base64 ``input.images[]``
    entry (see services/pose_assets.py); this returns the flat filename that the
    workflow's LoadImage node (170) should reference.

    Args:
        pose: The pose type

    Returns:
        ComfyUI input filename for the reference pose image
        (e.g. ``pose_ref_sitting.png``)

    Raises:
        ValueError: if ``pose`` is not a known PoseType member (kept for the
            existing 422 mapping in ``edit_pose``).
    """
    if not isinstance(pose, PoseType):
        raise ValueError(f"No reference image for pose: {pose}")
    return pose_assets.worker_filename(pose)


# NOTE (W7): The pose workflow (edit_pose_action.json) has NO negative
# conditioning BY DESIGN. It runs the KSampler at cfg=1 and routes the negative
# branch through ConditioningZeroOut, so any negative-prompt text is
# mathematically inert. PoseEditRequest.negativePrompt is therefore accepted for
# request-shape parity but deliberately not wired here. Do NOT wire a negative
# prompt into this workflow without also raising cfg above 1 AND adding a real
# negative encoder node — otherwise you change the sampler math and the intended
# behavior. This is intentional; do not "fix" it.
def prepare_pose_workflow(
    template: dict,
    source_image: str,
    reference_image: str,
    prompt: Optional[str] = None,
    seed: Optional[int] = None,
    debug_save_pre_reactor: bool = False,
    reactor_restore_visibility: float = -1.0,
    reactor_codeformer_weight: float = -1.0,
) -> dict:
    """
    Prepare the pose workflow with injected parameters.

    Workflow nodes:
        109  LoadImage        -> inputs.image  (source character image = image1)
        170  LoadImage        -> inputs.image  (reference pose image = image2)
        114  CLIPTextEncode (or similar) -> inputs.prompt  (text prompt)
        3    KSampler         -> inputs.seed
        8    VAEDecode        -> the PRE-ReActor frame (raw pose regen)
        200  ReActorFaceSwap  -> inputs.face_restore_visibility / codeformer_weight
        164  SaveImage        -> the POST-ReActor final output (images=["200",0])
        300  SaveImage        -> WS4.1 debug-only node, injected when
                                  debug_save_pre_reactor=True (images=["8",0])

    Args:
        template: Base workflow template
        source_image: ComfyUI filename for source character image
        reference_image: ComfyUI filename for reference pose image
        prompt: Optional text prompt to inject into node 114
        seed: Optional seed value
        debug_save_pre_reactor: WS4.1 diagnostic flag (default OFF). When
            True, injects a second SaveImage node ("300") reading node 8
            (VAEDecode) directly — the pose regen BEFORE the ReActor
            face-swap runs — so it can be compared against the normal node
            164 (post-swap) output to classify face-misalignment causes.
            False (default) leaves the workflow byte-identical to before
            this param existed.
        reactor_restore_visibility: WS4.2 tuning knob (default -1.0 = no
            override). When >= 0, overrides node 200's
            ``face_restore_visibility`` (template default 0.8).
        reactor_codeformer_weight: WS4.2 tuning knob (default -1.0 = no
            override). When >= 0, overrides node 200's ``codeformer_weight``
            (template default 0.25).

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
        # Bump steps for fewer artifacts. The pose step is a full-frame re-diffusion
        # (node 3 denoise=1.0) with no mask to confine it and inert negatives (cfg=1),
        # so it is the dominant source of extra-limb / anatomy artifacts in a batch.
        # More steps is the main lever we have here (denoise can't drop — it's a genuine
        # pose transfer — and cfg can't rise on this distilled checkpoint). 4 -> 8.
        try:
            if int(wf["3"]["inputs"].get("steps", 0)) < 8:
                wf["3"]["inputs"]["steps"] = 8
                logger.debug("Bumped pose KSampler steps to 8")
        except (TypeError, ValueError):
            pass

    # WS4.1: optional pre-ReActor debug capture. Injects a second SaveImage
    # reading directly off node 8 (VAEDecode, the raw pose regen BEFORE the
    # ReActor face-swap) so it can be compared against the normal node 164
    # output (post-swap) when classifying face-misalignment causes (inswapper
    # low-res paste / codeformer over-restoration / blend-seam / head-angle
    # mismatch). Node id "300" is free (see module's verified node map).
    # Mirrors node 164's exact dict shape (inputs/class_type/_meta). Guarded
    # on "8" being present so an unexpected/future template shape degrades to
    # a no-op instead of a KeyError; default False -> no node 300 at all, so
    # the workflow is byte-identical to before this param existed.
    if debug_save_pre_reactor and "8" in wf:
        wf["300"] = {
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": "pose_preface",
            },
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image (pre-ReActor debug)"},
        }
        logger.debug("Injected debug SaveImage node 300 (pre-ReActor frame, prefix=pose_preface)")

    # WS4.2: optional ReActor tuning knobs (node 200). >= 0 overrides the
    # template's baked face_restore_visibility (0.8) / codeformer_weight
    # (0.25); the default -1.0 sentinel leaves them untouched (0.0 is itself
    # a valid override, so it can't double as "no override" here). Guarded on
    # "200" being present for the same reason as the debug node above.
    if "200" in wf:
        if reactor_restore_visibility >= 0:
            wf["200"]["inputs"]["face_restore_visibility"] = reactor_restore_visibility
            logger.debug(
                f"Overrode node 200 face_restore_visibility: {reactor_restore_visibility}"
            )
        if reactor_codeformer_weight >= 0:
            wf["200"]["inputs"]["codeformer_weight"] = reactor_codeformer_weight
            logger.debug(
                f"Overrode node 200 codeformer_weight: {reactor_codeformer_weight}"
            )

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

        # Validate the pose reference asset is actually installed on disk.
        # References ship per-request as base64; a missing PNG means the
        # generator has not been run yet, so fail fast with a clear 422.
        if not pose_assets.asset_path(request.pose).exists():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Pose reference not installed for pose '{request.pose.value}'. "
                    f"Run scripts/generate_pose_refs.py."
                ),
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
