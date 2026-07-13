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
from models.enums import PoseType, JobStatus, NudityLevel
from models.requests import PoseEditRequest
from models.responses import JobCreateResponse
from services import pose_assets
from services import prompt_constants as pc
from services import scene_vocab as sv
from services.character_anchors import populate_identity_anchors
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
# Optional (Supabase-gated) character store, wired in router.configure_services.
# Used only to auto-populate identityAnchors from PoseEditRequest.characterId;
# None (store not configured) degrades gracefully — see populate_identity_anchors.
_character_store = None


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


def set_character_store(store) -> None:
    """Set the (optional) character store used to resolve identityAnchors."""
    global _character_store
    _character_store = store


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
    lighting: Optional[str] = None,
    time_of_day: Optional[str] = None,
    outfit_text: Optional[str] = None,
    location: Optional[str] = None,
    pose_detail: Optional[str] = None,
    identity_anchors: Optional[str] = None,
) -> str:
    """
    Build a dynamic text prompt for the pose workflow based on pose type.

    B1 (scene/outfit fidelity): the pose step is the LAST pipeline step and fully
    re-diffuses the whole frame (edit_pose_action.json: denoise 1.0, cfg 1, negatives
    inert via ConditioningZeroOut — so ONLY positive-prompt text can steer it). With
    no outfit/scene/solo language it stochastically strips clothing, re-invents the
    location, and paints in extra people from an activity like "dancing with a
    partner". This builder now carries three positive-prompt guards against that:
    a keep-the-background instruction (replacing the old "adapt the background"
    licence to re-invent it), an optional state-of-dress continuity sentence, an
    optional scene-location anchor, and an ALWAYS-ON solo constraint.

    Args:
        pose: The pose type
        activity: Optional identity-free action phrase (e.g. SceneSpec.activity,
            routed here by scene_mapper when a pose step is active) appended as
            ", while {activity}". Run through services.scene_vocab.strip_companions()
            first (defensive) so multi-person phrasing ("… with a partner",
            "… full of passersby") can't paint extra people into the solo frame;
            if that leaves nothing meaningful the clause is skipped. None = unchanged
            base prompt (interactive /v1/edit/pose never sets this).
        expression: Optional facial expression/mood (e.g. SceneSpec.expression)
            appended as ", {expression} expression". Expression/mood ONLY — never
            facial features. Has no effect on non-posed items: the face there is
            byte-locked by the composite-back in prepare_outfit_workflow, so
            there is nothing for a prompted expression to act on outside a pose
            step. None = unchanged base prompt.
        lighting: Optional raw lighting enum-VALUE string (e.g.
            PipelineEditRequest.lighting, sourced from SceneSpec.lighting —
            values like "moody_dim"/"candlelit"/"neon"). Phrase-ified here via
            services.scene_vocab.lighting_phrase() — the SAME LIGHTING_PHRASES
            map scene_mapper.build_scene_background_text uses for the
            background step, so tone matches — and appended as
            ", in {lighting phrase}". This is the primary fix for batch photos
            always rendering bright: the pose step is the only pipeline step
            that fully re-diffuses the frame (denoise=1.0), so it is the one
            place a lighting clause can actually re-light the person instead
            of just the (person-masked-out) background. None, or a value
            absent from the map, leaves the prompt unchanged — never injects
            a raw enum string like "moody_dim" into the prompt.
        time_of_day: Optional raw time-of-day enum-VALUE string (e.g.
            PipelineEditRequest.timeOfDay, sourced from SceneSpec.time_of_day —
            values like "evening"/"night"/"golden_hour"). Phrase-ified via
            services.scene_vocab.time_of_day_phrase() and appended as
            ", {time_of_day phrase}" (the phrase already carries its own
            preposition, e.g. "at sunset" / "late at night"). Same
            graceful-skip behavior as lighting.
        outfit_text: Optional garment/state-of-dress text the reposed frame must
            preserve — the outfit continuity fix. Produced by
            api.v1.endpoints.outfit.outfit_continuity_text() (the outfit_detail, or
            the outfit's nudity tier prose) and threaded here by
            workers.pipeline_worker so the full re-diffusion keeps what the outfit
            step actually rendered instead of stripping it. Phrasing adapts to the
            text: a plain garment becomes "In image 1 she is wearing {outfit_text};
            keep her state of dress and every garment exactly as in image 1, fully
            intact.", while text that already begins with a state-of-dress word
            ("completely naked"/"topless"/"wearing"/"nude" — i.e. NAKED-tier prose)
            becomes "In image 1 she is {outfit_text}; keep her state of dress exactly
            as in image 1." so a NAKED tier never reads as "wearing completely
            naked". None (no outfit step / interactive caller) appends nothing.
        location: Optional raw location enum-VALUE string (e.g.
            PipelineEditRequest.location, sourced from SceneSpec.location — values
            like "home_bedroom"/"beach"/"cafe"). Phrase-ified via
            services.scene_vocab.location_phrase() (the SAME LOCATION_PHRASES map
            the background step uses) and appended right after the keep-background
            sentence as "The scene is {location phrase}." to re-anchor the scene the
            full re-diffusion must stay in. None, or a value absent from the map,
            appends nothing (never injects a raw enum string).
        pose_detail: Optional identity-free freeform body-position/action sentence
            (e.g. SceneSpec.pose_detail via PipelineEditRequest.poseDetail). When it
            survives strip_companions (same defensive scrub as ``activity``), it
            REPLACES the canned POSE_DESCRIPTIONS[pose] text in the "The target pose
            is: {…}" sentence — the pose ENUM still picks the reference image
            (image 2); the freeform text only sharpens the described target so the
            director's own wording drives the render instead of ~16 baked phrases.
            None/empty (or companion-only after the scrub) falls back to
            POSE_DESCRIPTIONS[pose] exactly as today. Everything else in the prompt
            (keep-background, solo, outfit continuity, …) is unchanged.
        identity_anchors: Optional concrete identity-attribute phrase for THIS
            character (e.g. from services.scene_mapper.identity_anchor_text —
            "straight blonde hair, green eyes, curvy build with medium breasts").
            D1: the pose step fully re-diffuses the frame guided only by the generic
            pose_identity_clause() ("keep the original ... hair style, hair color,
            eye color ..."), which binds weakly on this distilled model — hair
            structure/color and body proportions drift photo-to-photo as a result.
            When set, appended right after that clause as "She has {anchors}; keep
            these and her body proportions and build exactly as in image 1,
            completely unchanged." None/empty (interactive /v1/edit/pose and any
            caller without a character profile) appends nothing — unchanged
            behavior.

    Returns:
        A descriptive prompt string for the ComfyUI workflow
    """
    desc = POSE_DESCRIPTIONS.get(pose, "natural pose")
    # Freeform pose text (C1a): the director's own body-position sentence replaces
    # the canned enum description; companion-scrubbed like `activity` so a stray
    # "… with a partner" can't paint an extra person into the solo frame.
    pose_detail_clean = sv.strip_companions(pose_detail)
    if pose_detail_clean and pose_detail_clean.strip():
        desc = pose_detail_clean.strip()
    clause = pc.pose_identity_clause()
    # Keep-the-background instruction REPLACES the former "Adapt the background and
    # environment to suit the pose naturally." — that sentence was the licence the
    # full re-diffusion used to re-invent the location (bedroom -> road).
    prompt = (
        f"Make the person in image 1 do the exact same pose of the person in image 2. "
        f"The target pose is: {desc}. {clause}. "
    )
    # D1: concrete per-character identity anchors, placed immediately adjacent to
    # the generic pose_identity_clause() above — a real hair color / eye color /
    # build binds far better on this distilled model than the clause's generic
    # "keep the original ... hair style, hair color ..." instruction alone.
    if identity_anchors and identity_anchors.strip():
        prompt += (
            f"She has {identity_anchors.strip()}; keep these and her body "
            f"proportions and build exactly as in image 1, completely unchanged. "
        )
    prompt += (
        f"The new pose should match image 2 accurately. "
        f"Keep the same background, location and environment as image 1, adjusting "
        f"only perspective to fit the new pose."
    )
    # Scene-location anchor, right after the keep-background sentence.
    location_text = sv.location_phrase(location)
    if location_text:
        prompt += f" The scene is {location_text}."
    # State-of-dress continuity. NAKED-tier prose already begins with a state word,
    # so phrase it as "she is {text}" (not "she is wearing completely naked …").
    if outfit_text and outfit_text.strip():
        garment = outfit_text.strip()
        if garment.lower().startswith(("completely naked", "topless", "wearing", "nude")):
            prompt += (
                f" In image 1 she is {garment}; keep her state of dress exactly as "
                f"in image 1."
            )
        else:
            prompt += (
                f" In image 1 she is wearing {garment}; keep her state of dress and "
                f"every garment exactly as in image 1, fully intact."
            )
    # Solo constraint — ALWAYS appended (even for bare interactive callers): the full
    # re-diffusion otherwise duplicates the subject or paints companions in.
    prompt += (
        " She is completely alone in the frame — exactly one person, no other people."
    )
    # Defensive companion scrub before the activity clause folds in (a stray
    # "… with a partner" would otherwise re-add the extra person the solo sentence
    # just forbade). None/empty result -> skip the clause entirely.
    activity_clean = sv.strip_companions(activity)
    if activity_clean and activity_clean.strip():
        prompt += f", while {activity_clean.strip()}"
    if expression and expression.strip():
        prompt += f", {expression.strip()} expression"
    lighting_text = sv.lighting_phrase(lighting)
    if lighting_text:
        prompt += f", in {lighting_text}"
    time_of_day_text = sv.time_of_day_phrase(time_of_day)
    if time_of_day_text:
        prompt += f", {time_of_day_text}"
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


def _is_pose_2511_template(template: dict) -> bool:
    """
    True if this is the Tier-A 2511 pose graph (``pose_2511_API.json``).

    Marker: node "301" is a UNETLoader (the native non-distilled Qwen-Image-Edit-2511
    stack), present on the 2511 pose graph but NOT on the v1 Rapid pose graph
    (edit_pose_action.json loads its checkpoint via CheckpointLoaderSimple at node
    163). Mirrors ``_is_cropstitch_template``'s node-id + class_type approach so a
    single ``prepare_pose_workflow`` can drive BOTH templates and branch only where
    the graphs genuinely differ (the live negative — see the D3 NOTE below).
    """
    node = template.get("301")
    return bool(node and node.get("class_type") == "UNETLoader")


# NOTE (W7 / D3): The v1 pose graph (edit_pose_action.json) has NO negative
# conditioning BY DESIGN — it runs the KSampler at cfg=1 and routes the negative
# branch through ConditioningZeroOut, so any negative-prompt text is mathematically
# inert. On that graph PoseEditRequest.negativePrompt stays accepted-but-unwired:
# the injection block below is gated on ``_is_pose_2511_template`` and NEVER touches
# the v1 template. Do NOT wire a negative into the v1 graph without also raising its
# cfg above 1 AND adding a real negative encoder node — that would change the sampler
# math. The Tier-A pose graph (pose_2511_API.json) satisfies exactly those two
# preconditions (cfg 2.5 + a real TextEncodeQwenImageEditPlus negative at node 115),
# so the negative IS wired there — this is the one place the pose step's negatives
# come alive, and only when that template is loaded.
def prepare_pose_workflow(
    template: dict,
    source_image: str,
    reference_image: str,
    prompt: Optional[str] = None,
    seed: Optional[int] = None,
    debug_save_pre_reactor: bool = False,
    reactor_restore_visibility: float = -1.0,
    reactor_codeformer_weight: float = -1.0,
    negative_prompt: Optional[str] = None,
    nudity_level: Optional[NudityLevel] = None,
) -> dict:
    """
    Prepare the pose workflow with injected parameters.

    Workflow nodes:
        109  LoadImage        -> inputs.image  (source character image = image1)
        170  LoadImage        -> inputs.image  (reference pose image = image2)
        114  CLIPTextEncode (or similar) -> inputs.prompt  (positive text prompt)
        115  TextEncodeQwenImageEditPlus -> inputs.prompt  (LIVE negative; 2511 tier ONLY)
        3    KSampler         -> inputs.seed
        8    VAEDecode        -> the PRE-ReActor frame (raw pose regen)
        200  ReActorFaceSwap  -> inputs.face_restore_visibility / codeformer_weight
        164  SaveImage        -> the POST-ReActor final output (images=["200",0])
        300  SaveImage        -> WS4.1 debug-only node, injected when
                                  debug_save_pre_reactor=True (images=["8",0])

    This preparer drives BOTH pose templates off the SAME node-id contract
    (109/170/114/3/8/200/164): the v1 Rapid graph (edit_pose_action.json) and the
    Tier-A graph (pose_2511_API.json). The ONLY tier-specific branch is the negative:
    node 115 (a real negative encoder) exists solely on the 2511 graph and is wired
    from ``pc.edit_negative(...)`` only when ``_is_pose_2511_template`` is true. On v1
    (no node 115, cfg 1) nothing is injected, so v1 stays byte-identical to before.

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
        negative_prompt: D3, 2511-tier ONLY. Optional extra negative terms folded
            into ``pc.edit_negative(...)`` and written to node 115's prompt. On the
            v1 graph this is ignored entirely (no node 115; cfg 1 makes negatives
            inert — see the W7/D3 NOTE above). None = the full standard edit negative
            (quality + adult + identity + skin + nudity-tier) with no extra terms.
        nudity_level: D3, 2511-tier ONLY. NudityLevel (or None = 'low') selecting the
            nudity-suppression block inside ``pc.edit_negative(...)`` for node 115.
            Ignored on the v1 graph.

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

    # Node 115: LIVE negative — Tier-A (2511) pose graph ONLY. The v1 Rapid graph
    # has no node 115 and samples at cfg 1 (negatives inert), so this is gated on
    # the 2511 template marker AND on the node's presence, and never touches v1
    # (see the W7/D3 NOTE above). pc.edit_negative folds the standard
    # quality/adult/identity/skin + nudity-tier negatives with any request extra.
    if _is_pose_2511_template(wf) and "115" in wf:
        wf["115"]["inputs"]["prompt"] = pc.edit_negative(
            negative_prompt, nudity_level=nudity_level
        )
        logger.debug("Set node 115 live negative (2511 pose tier)")

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
        # This is a v1-tier nudge: the Tier-A 2511 pose graph already bakes 20 steps
        # (>= 8), so the guard is a no-op there and leaves its sampler untouched.
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

        # Trait-aware edit: resolve identityAnchors from characterId when the caller
        # supplied an id but not explicit anchors (best-effort; never raises). The
        # pose step's build_pose_prompt already consumes request.identityAnchors.
        await populate_identity_anchors(_character_store, request)

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
