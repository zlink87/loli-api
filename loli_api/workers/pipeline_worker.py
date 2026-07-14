"""
Background worker for processing unified pipeline edit jobs.
Chains pose, outfit, and background steps in configurable order,
passing the output of each step as input to the next.
"""
import asyncio
import base64
import json
import random
import traceback
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path

import requests as http_requests

from config import settings
from services.job_manager import JobManager, Job
from services.comfyui_client import ComfyUIClient
from services.runpod_client import RunPodServerlessClient
from services import runpod_runner
from services.storage_service import StorageService
from services.supabase_storage_service import SupabaseStorageService
from services.notification_service import NotificationService
from services.image_cache_service import ImageCacheService
from models.enums import JobStatus

# Import helpers from existing endpoint modules
from api.v1.endpoints.outfit import build_prompt, prepare_outfit_workflow, outfit_continuity_text
from api.v1.endpoints.pose import (
    build_pose_prompt,
    prepare_pose_workflow,
    pose_template_has_face_ref_conditioning,
    # WS-N2: single source of truth for the natural/candid LoRA-scale decision now lives
    # in the pose endpoint (alongside build_pose_prompt / prepare_pose_workflow) so the
    # batch pipeline, the interactive pose worker, and the interactive outfit worker all
    # share one implementation instead of importing worker->worker.
    _natural_lora_scales,
)
from api.v1.endpoints.background import build_background_prompt, prepare_background_workflow

from services import head_mask as head_mask_service
from services import pose_assets
from services import attribute_phrases as ap
from services.prompt_constants import apply_edit_photo_style
from services.workflow_meta import describe_template

logger = logging.getLogger(__name__)

# Default order in which pipeline steps execute.
# Pose runs LAST deliberately: the pose workflow ends with a ReActor face-swap
# that stamps the hero's face onto the reposed body — if outfit/background ran
# after it, their re-diffusion could repaint that face. Outfit and background
# are masked (face pixel-protected), so they are safe to run first.
DEFAULT_PIPELINE_ORDER = ["outfit", "background", "pose"]


def _is_oom_error(error_msg: str) -> bool:
    """Check if error is a CUDA out-of-memory error."""
    lower = error_msg.lower()
    return "out of memory" in lower or "outofmemoryerror" in lower


def _download_image(url: str, timeout: int = 30) -> bytes:
    """Download image from URL. Raises RuntimeError on failure."""
    try:
        response = http_requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.content
    except http_requests.RequestException as e:
        raise RuntimeError(f"Failed to download source image: {e}")


def _stage_image(image_bytes: bytes, prefix: str) -> tuple:
    """Encode bytes as a RunPod input.images[] entry. Returns (name, images_list)."""
    name = f"{prefix}_{uuid.uuid4().hex[:12]}.png"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return name, [{"name": name, "image": f"data:image/png;base64,{b64}"}]


def _maybe_crop_face_donor(face_bytes: bytes, job_id: str = "") -> bytes:
    """Return the donor bytes to stage for node 210. When ``settings.FACE_REF_CROP`` is on,
    crop to the primary face region (so the hero's own scenery never enters the pose graph's
    image3 reference latents); otherwise, or on a detector miss / tiny crop / crop error,
    return the FULL image unchanged. Never raises — ReActor re-detects the donor itself, so a
    full-image fallback is always swap-safe. Flag off -> byte-identical to legacy staging."""
    if not settings.FACE_REF_CROP:
        return face_bytes
    try:
        cropped, did_crop = head_mask_service.crop_face_donor(face_bytes)
    except Exception as e:  # noqa: BLE001 — protective, a crop error must never fail the job
        logger.warning(f"[PIPELINE] {job_id} | Face ref crop failed, staging full image: {e}")
        return face_bytes
    if did_crop:
        logger.info(f"[PIPELINE] {job_id} | pose | Face ref cropped to face region")
        return cropped
    logger.info(f"[PIPELINE] {job_id} | pose | Face ref crop fell back to full image (no face / tiny crop)")
    return face_bytes


def _select_primary_output(
    outputs: List[Dict[str, Optional[str]]], primary_prefix: str = "pose_edit"
) -> Optional[Dict[str, Optional[str]]]:
    """
    Pick the PRIMARY output entry from a worker-comfyui ``outputs`` list (the
    normalized shape ``RunPodServerlessClient.parse_output`` returns: dicts
    carrying at least ``filename``/``type``/``url``/``data``).

    Normally a step's workflow has exactly one SaveImage node, so ``outputs``
    has one entry and picking ``outputs[0]`` (the old behavior) is fine. WS4.1
    adds a SECOND SaveImage to the pose workflow (node "300", filename prefix
    "pose_preface") for pre-ReActor debugging alongside the real one (node
    164, prefix "pose_edit") when ``settings.POSE_DEBUG_SAVE_PRE_REACTOR`` is
    on — and RunPod does not guarantee output list ordering, so blindly taking
    ``outputs[0]`` could hand the PRE-swap debug frame to the next pipeline
    step instead of the real post-ReActor one. This matches by filename
    PREFIX (worker-comfyui appends a counter/suffix to ``filename_prefix``,
    e.g. ``pose_edit_00001_.png``), so it's independent of list order.

    Falls back to ``outputs[0]`` when nothing matches the prefix (the normal
    single-SaveImage steps — outfit/background use prefix "edit_out", and
    pose with the debug flag off only ever produces the one "pose_edit"
    entry), so existing behavior is unchanged whenever there's nothing to
    disambiguate. Returns None on an empty list rather than raising, so
    callers keep control of the "no images" error message.
    """
    for entry in outputs:
        filename = entry.get("filename") or ""
        if filename.startswith(primary_prefix):
            return entry
    return outputs[0] if outputs else None


# Phase 5 observability: node-id contract for reading back the EXACT final
# positive/negative prompt text a step's workflow will render, straight off
# the injected workflow dict `_build_step_workflow` just returned. Mirrors the
# node maps documented in `prepare_outfit_workflow`/`prepare_pose_workflow`/
# `prepare_background_workflow`'s own docstrings — kept here as a small,
# read-only lookup rather than re-deriving it from the request/response, so a
# bad image is attributable to "what the planner asked for" (scene_spec) vs.
# "what actually got rendered" (this) in one look. Node 115 (pose negative)
# only exists on the Tier-A 2511 pose graph, so pose on the v1 template
# reports negative=None — that matches the v1 tier's inert-negative design
# (cfg=1, ConditioningZeroOut) rather than fabricating a value nothing uses.
_POSITIVE_NODE_BY_STEP = {
    "pose": ("114", "prompt"),
    "outfit": ("16", "positive"),
    "background": ("16", "positive"),
}
_NEGATIVE_NODE_BY_STEP = {
    "pose": ("115", "prompt"),
    "outfit": ("117", "negative"),
    "background": ("117", "negative"),
}
# Truncation cap for persisted debug prompts (per Phase 5 plan: ~2000 chars) so
# a pathological caption can't bloat the batch item's pipeline_request jsonb
# or the character_images metadata blob.
_DEBUG_PROMPT_TRUNC_CHARS = 2000


def _truncate_debug_prompt(text: Optional[str]) -> Optional[str]:
    if not isinstance(text, str):
        return None
    return text[:_DEBUG_PROMPT_TRUNC_CHARS]


def _extract_step_prompts(step_name: str, workflow: dict) -> Dict[str, Optional[str]]:
    """
    Read back the composed positive/negative prompt text off a JUST-BUILT step
    workflow dict (the same one ``_build_step_workflow`` returns), keyed by the
    node ids each step builder actually writes to. Zero signature churn on
    ``_build_step_workflow`` itself (it stays a pure dict-in/dict-out builder
    that many tests call directly) — this is a separate, read-only pass over
    its output.

    Returns ``{"positive": str|None, "negative": str|None}``, each truncated
    to ``_DEBUG_PROMPT_TRUNC_CHARS``. An unrecognized step name or a workflow
    missing the expected node yields None for that side rather than raising —
    debug capture must never fail the pipeline.
    """
    positive = None
    negative = None
    pos_node, pos_key = _POSITIVE_NODE_BY_STEP.get(step_name, (None, None))
    if pos_node and pos_node in workflow:
        positive = workflow[pos_node].get("inputs", {}).get(pos_key)
    neg_node, neg_key = _NEGATIVE_NODE_BY_STEP.get(step_name, (None, None))
    if neg_node and neg_node in workflow:
        negative = workflow[neg_node].get("inputs", {}).get(neg_key)
    return {
        "positive": _truncate_debug_prompt(positive),
        "negative": _truncate_debug_prompt(negative),
    }


def _extract_applied_lora_scales(workflow: dict, photo_style) -> Optional[Dict[str, float]]:
    """
    Read back the LoRA strengths WS-N2 actually wrote onto this JUST-BUILT pose workflow —
    mirroring ``_extract_step_prompts``' read-after-build approach. Returns the {node_id:
    strength_model} pairs that natural/candid scaling targeted AND that exist on this graph
    (so the v1 Rapid pose graph, which carries none of those LoRA nodes, yields None),
    else None. Used only to populate the step ``_debug`` meta; never affects the render.
    """
    scales = _natural_lora_scales(photo_style)
    if not scales:
        return None
    applied = {
        nid: workflow[nid]["inputs"]["strength_model"]
        for nid in scales
        if nid in workflow
        and isinstance(workflow[nid].get("inputs"), dict)
        and "strength_model" in workflow[nid]["inputs"]
    }
    return applied or None


class PipelineBackgroundWorker:
    """
    Async worker that processes unified pipeline edit jobs.

    Workflow:
    1. Get job from pipeline queue
    2. Download source image (or use cache)
    3. Upload to ComfyUI
    4. Determine active steps from request params
    5. For each active step in order:
       a. Prepare step-specific workflow
       b. Execute workflow with OOM retry
       c. Extract output image bytes
       d. Re-upload output as input for next step
    6. Save final output image
    7. Update job status
    """

    def __init__(
        self,
        job_manager: JobManager,
        comfyui_client: ComfyUIClient,
        storage_service: StorageService,
        pose_workflow_path: str,
        outfit_workflow_path: str,
        background_workflow_path: Optional[str] = None,
        image_cache_service: Optional[ImageCacheService] = None,
        notification_service: Optional[NotificationService] = None,
        supabase_storage_service: Optional[SupabaseStorageService] = None,
        runpod_client: Optional[RunPodServerlessClient] = None,
    ):
        self.job_manager = job_manager
        self.comfyui_client = comfyui_client
        self.runpod_client = runpod_client
        self.storage = storage_service
        self.supabase_storage = supabase_storage_service
        self.pose_workflow_path = pose_workflow_path
        self.outfit_workflow_path = outfit_workflow_path
        # The background step uses its OWN template (a V1 whole-person graph), NOT the
        # outfit template. The outfit step may point at a crop-and-stitch graph (V2 /
        # Tier-A 2511), whose node topology lacks the InvertMask/GrowMaskWithBlur nodes
        # (204/119) that prepare_background_workflow rewires — feeding it a crop-stitch
        # template silently skips the person-mask inversion and regenerates the person
        # instead of the background. Defaults to the outfit path for backward compat.
        self.background_workflow_path = background_workflow_path or outfit_workflow_path
        self.image_cache = image_cache_service
        self.notification = notification_service
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Workflow templates loaded on start
        self._pose_template: Optional[dict] = None
        self._outfit_template: Optional[dict] = None
        self._background_template: Optional[dict] = None
        # WS3.1 observability: per-step resolved workflow info, keyed by step
        # label ("pose"/"outfit"/"background"), populated by _load_workflows().
        # {"path": <resolved abs path str>, "tier": ..., "sampler": {...}}
        self.workflow_meta: Dict[str, dict] = {}

    async def start(self) -> None:
        """Start the pipeline background worker."""
        self._running = True
        await self._load_workflows()
        self._task = asyncio.create_task(self._worker_loop())
        logger.info("Pipeline background worker started")

    async def stop(self) -> None:
        """Stop the pipeline background worker gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Pipeline background worker stopped")

    async def _load_workflows(self) -> None:
        """Load workflow templates from files (outfit and background are separate)."""
        for label, path, attr in [
            ("pose", self.pose_workflow_path, "_pose_template"),
            ("outfit", self.outfit_workflow_path, "_outfit_template"),
            ("background", self.background_workflow_path, "_background_template"),
        ]:
            try:
                workflow_file = Path(path)
                if not workflow_file.exists():
                    raise FileNotFoundError(f"{label} workflow not found: {path}")
                with open(workflow_file, "r", encoding="utf-8") as f:
                    template = json.load(f)
                setattr(self, attr, template)
                logger.info(f"Loaded {label} workflow template: {path}")

                # WS3.1 observability: record which tier actually loaded (as opposed
                # to which env var was configured) so a mis-deployed environment that
                # silently degrades to V1 shows up in logs/debug endpoints instead of
                # only in the rendered image quality. Tagged uniquely
                # ([WORKFLOW-RESOLVED]) so it doesn't collide with the identically
                # worded "Loaded ... workflow template:" line above, which several
                # engines (interactive outfit worker, pipeline, batch) all emit.
                resolved_path = str(workflow_file.resolve())
                meta = describe_template(template)
                self.workflow_meta[label] = {"path": resolved_path, **meta}
                logger.info(
                    f"[WORKFLOW-RESOLVED] {label} -> {resolved_path} tier={meta['tier']}"
                )
            except Exception as e:
                logger.error(f"Failed to load {label} workflow: {e}")
                raise

    async def _worker_loop(self) -> None:
        """Main worker loop processing pipeline jobs."""
        logger.info("Pipeline worker loop started, waiting for jobs...")

        while self._running:
            try:
                job_id = await self.job_manager.get_next_pipeline_job()
                job = await self.job_manager.get_job(job_id)

                if not job:
                    logger.warning(f"Pipeline job {job_id} not found in registry")
                    self.job_manager.mark_pipeline_done()
                    continue

                # Skip cancelled jobs
                if job.status == JobStatus.FAILED:
                    logger.info(f"Skipping cancelled pipeline job {job_id}")
                    self.job_manager.mark_pipeline_done()
                    continue

                logger.info(f"Processing pipeline job {job_id} for user {job.user_id}")
                await self._process_job(job)

            except asyncio.CancelledError:
                logger.info("Pipeline worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in pipeline worker loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    def _determine_active_steps(self, request) -> List[str]:
        """
        Determine which pipeline steps are active based on request params.
        Returns a list of step names in the configured order.
        """
        # Single-pass batch collapse (scene_mapper-set flag): the pose step re-diffuses
        # the whole frame and now also dresses + re-scenes from the nude base, so the
        # separate outfit/background steps are dropped — one pose-graph job renders it
        # all. Gated on a pose (the pose graph is what runs). getattr keeps interactive /
        # test requests (no singlePassEdit field) on the legacy path.
        if getattr(request, "singlePassEdit", False) and request.pose is not None:
            return ["pose"]

        order = request.pipeline_order if request.pipeline_order else DEFAULT_PIPELINE_ORDER

        # Map step names to their enabling condition
        step_enabled = {
            "pose": request.pose is not None,
            "outfit": request.outfit is not None,
            "background": request.prompt is not None,
        }

        return [step for step in order if step_enabled.get(step, False)]

    def _build_step_workflow(
        self, step_name: str, request, source_name: str, seed: int, job_id: str,
        pose_ref_name: Optional[str] = None,
        head_mask_name: Optional[str] = None,
        face_ref_name: Optional[str] = None,
        is_final_step: bool = True,
    ) -> dict:
        """
        Build the ComfyUI workflow for a pipeline step, with source_name as input.

        For the pose step, ``pose_ref_name`` is the flat filename of the staged
        pose reference (node 170); for the outfit step, ``head_mask_name`` is the
        flat filename of the staged server-computed head-protect mask (node 211).
        Both are computed once in ``_run_step`` so the same names feed the nodes
        and the base64 ``input.images[]`` entries.

        WS2/WS3.2: ``request.activity``/``expression`` (pose step) and
        ``request.outfitDetail``/``outfitDenoise``/``outfitPromptMode`` (outfit
        step) are read via ``getattr(..., None)``/defensive defaults so any
        request object missing them (e.g. a hand-built test stand-in, or the
        legacy interactive endpoints' own request models, which don't carry
        these fields at all) degrades to the pre-WS2/WS3.2 behavior exactly.

        W3: ``request.lighting``/``timeOfDay`` (raw enum-value strings, e.g.
        "moody_dim"/"night") are read the same defensive way and routed to the
        pose step's ``build_pose_prompt`` (the primary lighting fix — see its
        docstring) and, for ``lighting`` only, to the outfit step's
        ``build_prompt`` (secondary/cheap — the outfit step composites the
        person back over the source, so it mostly affects the regenerated
        crop). Both builders phrase-ify the raw value via
        ``services.scene_vocab`` and no-op on None/unrecognized values.

        ``request.photoStyle`` is routed to the person-RENDERING steps
        (pose, outfit) unconditionally, and to the background step only when
        background is the sole active step — see the comment above
        ``photo_style`` below for why. ``is_final_step`` is still accepted
        (``batch_pipeline_worker.py`` threads it through) but no longer gates
        photo style.

        D1: ``request.identityAnchors`` (a concrete per-character hair/eyes/build
        phrase, e.g. from services.scene_mapper.identity_anchor_text) is read the
        same defensive way and routed to BOTH the pose step's ``build_pose_prompt``
        and the outfit step's ``build_prompt`` — both steps re-diffuse the body
        region, so a concrete anchor helps identity fidelity in each.

        D2: ``request.reactorRestoreVisibility``/``reactorCodeformerWeight``
        (pose-step ReActor node-200 tuning, 0.0-1.0) override the server-wide
        ``settings.POSE_REACTOR_RESTORE_VISIBILITY`` / ``POSE_REACTOR_CODEFORMER_WEIGHT``
        defaults when set; None (the common case) keeps the settings value,
        preserving the pre-D2 behavior exactly.
        """
        # Optional photographic-finish clause, routed to the person-RENDERING
        # steps (pose, outfit) UNCONDITIONALLY: those are the steps that actually
        # re-diffuse the body, so the natural-skin/anti-glamour finish has to
        # land there to have any effect. The background step masks the person
        # OUT and composites them back untouched, so wrapping background too
        # would only dress up the discarded scene pixels — UNLESS background is
        # the only active step (a background-only edit has no mask/composite to
        # skip, so it keeps today's legacy behavior of getting the clause).
        #
        # Earlier revisions gated this on `is_final_step` (apply once, on
        # whichever step ran last) to avoid 2-3 re-diffusions of the same "warm
        # grade" language compounding into oversaturated, plastic output. That
        # worked for a typical interactive edit (one step) but broke nude-base
        # jobs, whose steps are outfit -> background: background ran last, so
        # the natural-skin suffix landed on the masked-out background instead of
        # ever reaching the body render. `is_final_step` is kept as a parameter
        # for caller compatibility but no longer gates photo style here.
        photo_style = getattr(request, "photoStyle", None)
        if step_name == "background" and (request.outfit is not None or request.pose is not None):
            photo_style = None

        # Pubic grooming (WS pubic-hair): the scene mapper sets request.pubicHair (the
        # grooming enum value) ONLY for a NAKED-class outfit at HIGH nudity. Resolve it to
        # its phrase once here so the outfit step (build_prompt) and the pose step's
        # continuity text (outfit_continuity_text) carry the SAME descriptor, appended to
        # the NAKED tier prose. None (every dressed / sub-HIGH item, and interactive
        # callers) -> None -> both builders append nothing, byte-identical to before.
        pubic_hair_value = getattr(request, "pubicHair", None)
        grooming_phrase = ap.pubic_hair_phrase(pubic_hair_value) if pubic_hair_value else None

        if step_name == "pose":
            logger.info(f"[PIPELINE] {job_id} | pose | Reference: {pose_ref_name}")
            # Single-pass batch collapse: this one pose step dresses + re-scenes from the
            # nude base. dress_mode flips the outfit-continuity phrasing to an ADDITIVE
            # "Dress her in:" (there is no garment on the nude base to "keep"), and
            # scene_text replaces the "keep the same background" clause with the composed
            # scene ("Place her in:"). Both default off for the legacy multi-step path
            # (outfit/background already rendered), keeping that prompt byte-identical.
            single_pass_edit = getattr(request, "singlePassEdit", False)
            prompt = apply_edit_photo_style(
                build_pose_prompt(
                    request.pose,
                    activity=getattr(request, "activity", None),
                    expression=getattr(request, "expression", None),
                    # C1a: freeform director pose text replaces the canned enum
                    # description in "The target pose is:" (the enum still picked
                    # the reference image); None (interactive/legacy requests)
                    # keeps the enum description exactly as before.
                    pose_detail=getattr(request, "poseDetail", None),
                    # W3 lighting fix: the pose step is the only step that fully
                    # re-diffuses the frame, so it's the one place a lighting/
                    # time-of-day clause can actually re-light the person (the
                    # background step masks the person OUT and composites them
                    # back untouched). Raw enum-value strings off the request;
                    # build_pose_prompt phrase-ifies them via scene_vocab.
                    lighting=getattr(request, "lighting", None),
                    time_of_day=getattr(request, "timeOfDay", None),
                    # B1 fidelity: because this last step re-diffuses the whole frame,
                    # feed it the state-of-dress it must preserve (else clothing is
                    # stripped stochastically) and the location it must stay in (else
                    # the scene is re-invented). outfit_text is None when no outfit
                    # step ran (nothing to preserve); location no-ops on None/unknown.
                    outfit_text=(
                        outfit_continuity_text(
                            request.outfit,
                            request.nudityLevel,
                            getattr(request, "outfitDetail", None),
                            # Pubic-grooming descriptor (NAKED+HIGH only) — APPENDED after
                            # the tier prose so a NAKED tier keeps its leading state-of-undress
                            # word. None for every other item (appends nothing).
                            grooming=grooming_phrase,
                        )
                        if request.outfit is not None
                        else None
                    ),
                    location=getattr(request, "location", None),
                    # D1: concrete per-character identity anchor (hair/eyes/build);
                    # None (interactive callers / no character profile) appends
                    # nothing, same as every other getattr-defensive field above.
                    identity_anchors=getattr(request, "identityAnchors", None),
                    # WS-STAGE: scenery anchor for this (location, pose-class), e.g.
                    # "perched on a bar stool at the counter". In the multi-step path it is
                    # appended to the target-pose sentence; in single-pass build_pose_prompt
                    # suppresses that append (it already rides scene_text below). None
                    # (interactive/legacy) appends nothing.
                    staging=getattr(request, "stagingText", None),
                    # WS-STAGE Part B: the item's nudity level drives the public-venue solo
                    # policy — HIGH nudity (or the NAKED outfit) keeps STRICT solo even in a
                    # public venue. Defensive getattr for non-batch stand-ins.
                    nudity_level=getattr(request, "nudityLevel", None),
                    # The outfit ENUM value lets the solo policy detect NAKED robustly, even
                    # when outfit_continuity_text prepends a caption detail that would defeat a
                    # prose-prefix sniff of outfit_text. None -> the prefix fallback.
                    outfit_enum=(
                        request.outfit.value
                        if hasattr(request.outfit, "value")
                        else request.outfit
                    ),
                    # Single-pass: dress additively from the nude base, and place her in
                    # the composed scene text (request.prompt) instead of "keep image 1's
                    # background". Both no-ops (default) on the legacy multi-step path.
                    dress_mode=single_pass_edit,
                    scene_text=(request.prompt if single_pass_edit else None),
                    # WS-F: only the faceref pose graph wires the hero donor (node 210)
                    # into the prompt ENCODERS as image3, so only there does the extra
                    # "render that same face" clause have a conditioning image to bind to.
                    # GUARD (both-conditions): the clause is added ONLY when the template
                    # exposes the image3 encoder input AND a DEDICATED hero donor was
                    # actually staged (face_ref_name). Without a staged donor, node 210
                    # falls back to the step source image for the ReActor stamp only — there
                    # is no separate hero face for "image 3" to point at — so the clause
                    # would be a lie. A batch item whose scene_mapper set faceRefImage stages
                    # one (clause on); an item / interactive request without one does not
                    # (clause off), even on the faceref graph.
                    face_ref_conditioning=(
                        pose_template_has_face_ref_conditioning(self._pose_template)
                        and face_ref_name is not None
                    ),
                ),
                photo_style,
            )
            # D2: per-request ReActor overrides win when set; None (the common
            # case) falls back to the server-wide settings default exactly as
            # before D2 existed.
            reactor_restore_visibility = getattr(request, "reactorRestoreVisibility", None)
            if reactor_restore_visibility is None:
                reactor_restore_visibility = settings.POSE_REACTOR_RESTORE_VISIBILITY
            reactor_codeformer_weight = getattr(request, "reactorCodeformerWeight", None)
            if reactor_codeformer_weight is None:
                reactor_codeformer_weight = settings.POSE_REACTOR_CODEFORMER_WEIGHT
            return prepare_pose_workflow(
                self._pose_template, source_name, pose_ref_name, prompt=prompt, seed=seed,
                debug_save_pre_reactor=settings.POSE_DEBUG_SAVE_PRE_REACTOR,
                reactor_restore_visibility=reactor_restore_visibility,
                reactor_codeformer_weight=reactor_codeformer_weight,
                # D3: LIVE negative on the Tier-A 2511 pose graph ONLY (prepare_pose_workflow
                # gates this on the template marker — no-op on the v1 cfg-1 graph). getattr
                # keeps a test stand-in without these fields on the pre-D3 path.
                negative_prompt=getattr(request, "negativePrompt", None),
                nudity_level=getattr(request, "nudityLevel", None),
                # WS-S: the dedicated ReActor face donor (sharp hero) staged in _run_step.
                # None -> node 210 falls back to source_name (unchanged donor==source).
                face_ref_image=face_ref_name,
                # Pose output resolution (node 93). >0 scales the canvas up (prod raises
                # the single-pass output to ~1.74 MP); 0.0 (default) keeps the template's
                # baked 1.0 MP, so this passes None and the graph is untouched.
                output_megapixels=(
                    settings.POSE_OUTPUT_MEGAPIXELS
                    if settings.POSE_OUTPUT_MEGAPIXELS > 0
                    else None
                ),
                # Dark asset (07-14, ships OFF): sharper face-restore model override
                # for node 200. Empty setting (default, until ops stages the file on
                # the volume and flips it) -> None -> prepare_pose_workflow no-ops.
                face_restore_model=settings.POSE_REACTOR_FACE_RESTORE_MODEL or None,
                # WS-N2: dial the LoRA stack (304/305/306) DOWN for natural/candid so the
                # render stops looking editorial; None for polished/studio/None (baked
                # strengths kept). photo_style here is request.photoStyle (the pose branch
                # never nulls it — only background does). No-op on a graph without those
                # LoRA nodes (v1 Rapid pose graph).
                lora_scales=_natural_lora_scales(photo_style),
                # Turbo finishing pass (07-14, ships DARK): low-denoise Z-Image-Turbo
                # re-skin strength (node 407 on the turbofinish pose graph only). The
                # -1.0 sentinel (default, until ops flips POSE_TURBO_FINISH_DENOISE)
                # leaves the graph's baked 0.32; prepare_pose_workflow no-ops on any pose
                # graph without node 407.
                turbo_finish_denoise=settings.POSE_TURBO_FINISH_DENOISE,
                # CFG experiment knob (07-14): >0 overrides the 2511 sampler's baked
                # cfg 2.5 (node 3) so glam/contrast can be A/B'd at 2.0-2.2 with one
                # env line. -1.0 sentinel (default) = baked; the preparer additionally
                # gates on the 2511 template marker so the distilled v1 graph (cfg 1
                # by design) can never be touched.
                cfg_scale=(
                    settings.POSE_CFG_SCALE if settings.POSE_CFG_SCALE > 0 else None
                ),
                # Anatomy-detail LoRA slot (07-14, ships DARK until ops names a file):
                # injected ONLY on explicit-tier items — request.pubicHair is set by
                # scene_mapper exactly when effective outfit == NAKED and clamped
                # nudity == HIGH (the same exposure gate the grooming phrase uses), so
                # dressed/suggestive renders never load the LoRA. Empty setting ->
                # None -> no injection anywhere.
                anatomy_lora_name=(
                    settings.POSE_ANATOMY_LORA_NAME or None
                    if getattr(request, "pubicHair", None) is not None
                    else None
                ),
                anatomy_lora_strength=settings.POSE_ANATOMY_LORA_STRENGTH,
            )
        if step_name == "outfit":
            prompt = apply_edit_photo_style(
                build_prompt(
                    request.outfit, request.accessories, request.nudityLevel,
                    outfit_detail=getattr(request, "outfitDetail", None),
                    # Thread the request's outfitPromptMode through verbatim
                    # ("standard"/"replace"/"nude_base"); None (default / a test
                    # stand-in without the field) normalizes to "standard", the
                    # historical behavior.
                    prompt_mode=(getattr(request, "outfitPromptMode", None) or "standard"),
                    # Detail-dominant (B3): render outfitDetail alone (skip the enum's
                    # tier prose) when the planner flagged a caption that had no confident
                    # enum mapping / conflicted with the enum. getattr keeps back-compat.
                    detail_dominant=bool(getattr(request, "outfitDetailDominant", False)),
                    # Secondary/cheap lighting signal (see build_prompt docstring):
                    # the outfit step composites the person back over the source,
                    # so this mainly affects the regenerated crop, not a full relight.
                    lighting=getattr(request, "lighting", None),
                    # D1: concrete per-character identity anchor (hair/eyes/build) —
                    # the outfit step re-diffuses the body region too, so it benefits
                    # from the same anchor as the pose step. None = unchanged.
                    identity_anchors=getattr(request, "identityAnchors", None),
                    # Pubic-grooming descriptor (NAKED+HIGH only) — appended to the NAKED
                    # branch's prose. None for every dressed / sub-HIGH item (unchanged).
                    grooming=grooming_phrase,
                ),
                photo_style,
            )
            logger.info(f"[PIPELINE] {job_id} | outfit | Prompt: {prompt[:80]}...")
            return prepare_outfit_workflow(
                self._outfit_template, source_name, prompt, seed=seed,
                nudity_level=request.nudityLevel, outfit=request.outfit,
                head_mask_name=head_mask_name,
                source_dressed=getattr(request, "sourceDressed", False),
                denoise=getattr(request, "outfitDenoise", None),
                # WS-N2 parity: the outfit 2511/skinlora crop-stitch graphs carry the SAME
                # URP/NSFW/skin LoRA stack (nodes 304/305/306) as the pose graph, so dial it
                # DOWN for natural/candid here too. photo_style is request.photoStyle (the
                # outfit branch, unlike background, never nulls it). No-op on the legacy V1 /
                # plain crop-stitch graphs, which carry none of those LoRA nodes.
                lora_scales=_natural_lora_scales(photo_style),
            )
        if step_name == "background":
            # WS-T: interiorStyle/colorPalette (populated by populate_home_style for a
            # HOME-like location on a standalone /v1/edit) recompose the scene as her
            # styled room. Batch items leave both None (scene_mapper bakes the styled
            # room straight into request.prompt), so this is a no-op for them — read
            # defensively so a request object without the fields degrades cleanly.
            prompt = apply_edit_photo_style(
                build_background_prompt(
                    request.prompt,
                    location=getattr(request, "location", None),
                    interior_style=getattr(request, "interiorStyle", None),
                    color_palette=getattr(request, "colorPalette", None),
                ),
                photo_style,
            )
            logger.info(f"[PIPELINE] {job_id} | background | Prompt: {prompt[:80]}...")
            return prepare_background_workflow(
                self._background_template, source_name, prompt, seed=seed,
                negative_prompt=request.negativePrompt,
                nudity_level=request.nudityLevel,
                # A5 (nude base / solo backdrop): backgroundDenoise strengthens
                # scene removal on the cfg-1.0 V1 graph; soloSubject + the env
                # threshold drop low-confidence background passersby out of the
                # protected person mask. Both read defensively (getattr) so a
                # request object without these fields degrades to prior behavior;
                # person_threshold is the env value, gated behind soloSubject in
                # prepare_background_workflow (0.0 default = disabled).
                denoise=getattr(request, "backgroundDenoise", None),
                solo_subject=getattr(request, "soloSubject", False),
                person_threshold=settings.SOLO_BG_PERSON_THRESHOLD,
            )
        raise RuntimeError(f"Unknown pipeline step: {step_name}")

    async def _run_step(
        self, step_name: str, request, source_bytes: bytes, seed: int, job_id: str,
        progress_start: float, progress_end: float,
        is_final_step: bool = True,
    ) -> tuple:
        """
        Run one pipeline step on RunPod with source_bytes as the input image.

        Returns ``(image_bytes, step_prompts)`` — the output image bytes
        (downloading the worker's S3 URL if needed) alongside the EXACT
        positive/negative prompt text this step's workflow was built with
        (Phase 5 observability; see ``_extract_step_prompts``). Callers append
        ``step_prompts`` onto ``job.debug_meta["steps"]`` so a bad image is
        attributable to planner vs. render in one look.
        """
        step_meta = self.workflow_meta.get(step_name, {})
        step_path = step_meta.get("path")
        logger.info(
            f"[PIPELINE] {job_id} | {step_name} | workflow tier={step_meta.get('tier', 'unknown')} "
            f"path={Path(step_path).name if step_path else 'unknown'}"
        )

        source_name, images = _stage_image(source_bytes, f"pipe_{step_name}")

        # Pose steps need the reference PNG shipped alongside the source image as a
        # second base64 input.images[] entry. Resolve the (name, data_uri) pair
        # once so the SAME flat name feeds both node 170 and the images entry.
        pose_ref_name: Optional[str] = None
        if step_name == "pose":
            pose_ref_name, pose_ref_uri = await asyncio.to_thread(
                pose_assets.load_pose_reference_b64, request.pose
            )
            images.append({"name": pose_ref_name, "image": pose_ref_uri})

        # WS-S: the pose step also ships the DEDICATED ReActor face donor — the sharp
        # ORIGINAL hero photo (request.faceRefImage, set by scene_mapper) — as another
        # base64 input.images[] entry, so the graph's node 210 swaps the face from a
        # clean source instead of the multiply-edited pipeline intermediate (node 109).
        # Best-effort: a download failure leaves face_ref_name None -> node 210 falls
        # back to the source image (unchanged donor==source), never fails the job.
        face_ref_name: Optional[str] = None
        if step_name == "pose":
            face_ref_url = getattr(request, "faceRefImage", None)
            if face_ref_url:
                try:
                    face_bytes = await asyncio.to_thread(_download_image, face_ref_url)
                    # WS-FRC: crop the donor to the face region BEFORE staging so the hero
                    # photo's own scenery never enters node 210's image3 conditioning (which
                    # was diluting the scene text). Flag-gated + fallback-safe; no-op when off.
                    face_bytes = await asyncio.to_thread(
                        _maybe_crop_face_donor, face_bytes, job_id
                    )
                    face_ref_name = f"faceref_{uuid.uuid4().hex[:12]}.png"
                    images.append({
                        "name": face_ref_name,
                        "image": "data:image/png;base64,"
                                 + base64.b64encode(face_bytes).decode("ascii"),
                    })
                    logger.info(f"[PIPELINE] {job_id} | pose | Face ref (hero) staged")
                except Exception as e:  # noqa: BLE001 — protective, not critical
                    logger.warning(f"[PIPELINE] {job_id} | Face ref download failed: {e}")
                    face_ref_name = None

        # Outfit steps ship the server-computed head-protect mask (YuNet —
        # reliable on stylized hero renders where on-worker face detection is
        # not). Subtracted from the person mask so the head is never editable.
        head_mask_name: Optional[str] = None
        if step_name == "outfit":
            try:
                mask_bytes, face_found = await asyncio.to_thread(
                    head_mask_service.build_head_mask, source_bytes
                )
                head_mask_name = f"headmask_{uuid.uuid4().hex[:12]}.png"
                images.append({
                    "name": head_mask_name,
                    "image": "data:image/png;base64,"
                             + base64.b64encode(mask_bytes).decode("ascii"),
                })
                logger.info(
                    f"[PIPELINE] {job_id} | outfit | Head mask staged "
                    f"({'face found' if face_found else 'no face — fallback box (fail-closed)'})"
                )
            except Exception as e:  # noqa: BLE001 — protective, not critical
                logger.warning(f"[PIPELINE] {job_id} | Head mask failed: {e}")

        workflow = self._build_step_workflow(
            step_name, request, source_name, seed, job_id,
            pose_ref_name=pose_ref_name, head_mask_name=head_mask_name,
            face_ref_name=face_ref_name,
            is_final_step=is_final_step,
        )
        # Phase 5 observability: capture the EXACT composed prompt strings right
        # off the workflow we're about to submit — before any network I/O, so
        # this is a pure local read with no cross-request race risk even though
        # the engine (self) is shared across concurrent BatchPipelineWorker
        # instances/jobs.
        step_prompts = _extract_step_prompts(step_name, workflow)

        # WS-N2 observability: record the style-scaled LoRA strengths actually written to
        # this pose step's workflow (natural/candid only; absent otherwise so the debug
        # entry shape stays backward-compatible). Read straight off the built workflow,
        # like the prompt read-back above, and folded into step_prompts so it rides the
        # existing return channel up to the loop that assembles job.debug_meta["steps"].
        if step_name == "pose":
            applied_scales = _extract_applied_lora_scales(
                workflow, getattr(request, "photoStyle", None)
            )
            if applied_scales:
                step_prompts["loraScales"] = applied_scales

        outputs = await runpod_runner.run_workflow(
            self.runpod_client, self.job_manager, job_id, workflow,
            images=images, progress_start=progress_start, progress_end=progress_end,
        )
        if not outputs:
            raise RuntimeError(f"No images returned from {step_name} step")

        # WS4.1: with the pre-ReActor debug SaveImage active, the pose step's
        # outputs list carries TWO entries and RunPod does not guarantee
        # ordering — always continue the pipeline on the real post-ReActor
        # "pose_edit" one, never the debug "pose_preface" frame.
        primary = _select_primary_output(outputs, primary_prefix="pose_edit")
        if primary is None:
            raise RuntimeError(f"No images returned from {step_name} step")

        if step_name == "pose" and settings.POSE_DEBUG_SAVE_PRE_REACTOR:
            await self._capture_pose_debug_frame(outputs, primary, job_id)

        if primary.get("url"):
            image_bytes = await asyncio.to_thread(_download_image, primary["url"])
            return image_bytes, step_prompts
        data = primary.get("data")
        if not data:
            raise RuntimeError(f"No image data from {step_name} step")
        return base64.b64decode(data), step_prompts

    async def _capture_pose_debug_frame(
        self,
        outputs: List[Dict[str, Optional[str]]],
        primary: Dict[str, Optional[str]],
        job_id: str,
    ) -> None:
        """
        WS4.1: when POSE_DEBUG_SAVE_PRE_REACTOR is on, the pose workflow's
        outputs list carries a second entry (filename prefix "pose_preface")
        alongside the primary "pose_edit" one — the raw pose regen BEFORE the
        ReActor face-swap (node 8, VAEDecode; see prepare_pose_workflow).
        Persist it to the same storage backend the pipeline already uses for
        real output images (Supabase when configured, else local disk), under
        a debug_frames/{job_id}_pre_reactor key, so it can be pulled up next
        to the final face-swapped output when classifying misalignment causes
        (inswapper low-res paste / codeformer over-restoration / blend-seam /
        head-angle mismatch). Always logs the resolved URL too
        (``[POSE-DEBUG] {job_id} pre_reactor frame: {url}``) so the frame is
        retrievable even if persistence itself fails.

        Best-effort by design: a failure here must never fail the pipeline
        job — it only means the diagnostic artifact is lost, not the batch
        item — so every failure path is caught and logged, never raised.
        """
        debug_entry = next(
            (
                o for o in outputs
                if o is not primary and (o.get("filename") or "").startswith("pose_preface")
            ),
            None,
        )
        if debug_entry is None:
            logger.debug(f"[POSE-DEBUG] {job_id} | no pose_preface frame in outputs")
            return

        try:
            if debug_entry.get("url"):
                debug_bytes = await asyncio.to_thread(_download_image, debug_entry["url"])
            else:
                data = debug_entry.get("data")
                if not data:
                    logger.warning(f"[POSE-DEBUG] {job_id} | pre_reactor entry has no url/data")
                    return
                debug_bytes = base64.b64decode(data)

            debug_id = f"{job_id}_pre_reactor"
            if self.supabase_storage:
                debug_url, _ = await asyncio.to_thread(
                    self.supabase_storage.upload_image,
                    image=debug_bytes,
                    image_id=debug_id,
                    folder="debug_frames",
                )
            else:
                relative_path, _ = self.storage.save_image(debug_bytes, debug_id)
                debug_url, _ = self.storage.generate_signed_url(relative_path)

            logger.info(f"[POSE-DEBUG] {job_id} pre_reactor frame: {debug_url}")
        except Exception as e:  # noqa: BLE001 — diagnostic capture must never fail the job
            logger.warning(f"[POSE-DEBUG] {job_id} | failed to persist pre_reactor frame: {e}")

    async def _process_job(self, job: Job) -> None:
        """
        Process a single pipeline edit job.

        Steps:
        1. Update status to RUNNING
        2. Download source image / check cache
        3. Upload to ComfyUI
        4. Determine active steps
        5. Execute each step, chaining outputs
        6. Save final output image
        7. Update job as succeeded
        """
        start_time = datetime.utcnow()
        request = job.request

        try:
            # Step 1: Mark RUNNING
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.0
            )
            logger.info(f"[PIPELINE] {job.job_id} | Status: RUNNING | User: {job.user_id}")

            # Step 2: Download the source image (bytes are chained between steps)
            logger.info(f"[PIPELINE] {job.job_id} | Downloading source image...")
            current_bytes = await asyncio.to_thread(
                _download_image, request.source_image
            )
            logger.info(
                f"[PIPELINE] {job.job_id} | Downloaded {len(current_bytes)} bytes"
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.1
            )

            # Step 3: Determine active steps and seed
            active_steps = self._determine_active_steps(request)
            seed = (
                request.seed
                if request.seed is not None
                else random.randint(1, 999_999_999)
            )

            logger.info(
                f"[PIPELINE] {job.job_id} | Active steps: {active_steps} | Seed: {seed}"
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.15, seed_used=seed
            )

            # Step 4: Execute each step on RunPod, chaining output bytes to next input
            num_steps = len(active_steps)
            # Progress range: 0.15 to 0.85 divided among steps
            progress_per_step = 0.70 / num_steps if num_steps > 0 else 0.70
            image_start = datetime.utcnow()

            for i, step_name in enumerate(active_steps):
                step_progress_start = 0.15 + (i * progress_per_step)
                step_progress_end = 0.15 + ((i + 1) * progress_per_step)

                logger.info(
                    f"[PIPELINE] {job.job_id} | Step {i+1}/{num_steps}: {step_name}"
                )

                current_bytes, step_prompts = await self._run_step(
                    step_name, request, current_bytes, seed, job.job_id,
                    progress_start=step_progress_start, progress_end=step_progress_end,
                    is_final_step=(i == num_steps - 1),
                )

                # WS3.1 observability: record which workflow tier/path actually ran
                # this step, live, on the Job itself — surfaced later in
                # character_images.metadata by batch_orchestrator._publish_image.
                # Phase 5: also carries the EXACT composed positive/negative prompt
                # text (from _run_step's step_prompts) so a bad image is
                # attributable to planner (scene_spec) vs. render (this) in one look.
                step_meta = self.workflow_meta.get(step_name, {})
                step_debug = {
                    "step": step_name,
                    "workflow_path": step_meta.get("path"),
                    "tier": step_meta.get("tier"),
                    "seed": seed,
                    "positive_prompt": step_prompts.get("positive"),
                    "negative_prompt": step_prompts.get("negative"),
                }
                # WS-N2: only present when natural/candid scaling actually wrote LoRA
                # strengths this step — keeps the debug entry shape backward-compatible.
                lora_scales_applied = step_prompts.get("loraScales")
                if lora_scales_applied:
                    step_debug["loraScales"] = lora_scales_applied
                job.debug_meta.setdefault("steps", []).append(step_debug)

                logger.info(
                    f"[PIPELINE] {job.job_id} | {step_name} complete, "
                    f"output: {len(current_bytes)} bytes"
                )

            output_bytes = current_bytes
            image_duration = (datetime.utcnow() - image_start).total_seconds()
            logger.info(
                f"[PIPELINE] {job.job_id} | All steps done in {image_duration:.2f}s"
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.85,
                image_generated_at=datetime.utcnow()
            )

            # Step 5: Save final output
            # output_bytes holds the final image from the last step
            image_data = output_bytes

            if self.supabase_storage:
                logger.info(f"[PIPELINE] {job.job_id} | Uploading to Supabase")
                preview_url, image_hash = await asyncio.to_thread(
                    self.supabase_storage.upload_image,
                    image=image_data,
                    image_id=job.job_id,
                    folder="pipeline_edits",
                )
                expires_at = None
                relative_path = f"pipeline_edits/{job.job_id}.png"
            else:
                logger.info(f"[PIPELINE] {job.job_id} | Saving to local storage")
                relative_path, image_hash = self.storage.save_image(
                    image_data, job.job_id
                )
                preview_url, expires_at = self.storage.generate_signed_url(
                    relative_path
                )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.9
            )

            # Step 6: Mark SUCCEEDED
            completed_at = datetime.utcnow()
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.SUCCEEDED, progress=1.0,
                result_path=relative_path,
                preview_url=preview_url,
                preview_expires_at=expires_at,
                image_hash=image_hash,
                completed_at=completed_at,
            )

            total_duration = (completed_at - start_time).total_seconds()
            logger.info(
                f"[PIPELINE] {job.job_id} | Status: SUCCEEDED | "
                f"Steps: {active_steps} | "
                f"Total: {total_duration:.2f}s | Image: {image_duration:.2f}s"
            )

            # Send notification
            if self.notification and preview_url:
                request_payload = request.model_dump(mode="json")

                def format_ts(dt):
                    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else None

                timestamps = {
                    "Job Created": format_ts(job.created_at),
                    "Image Generated": format_ts(datetime.utcnow()),
                    "Job Completed": format_ts(completed_at),
                }

                await self.notification.send_edit_completed(
                    edit_id=job.job_id,
                    filename=f"pipeline_edit_{'_'.join(active_steps)}",
                    input_url=request.source_image,
                    image_urls=[preview_url],
                    total_duration=total_duration,
                    user_id=job.user_id,
                    image_duration=image_duration,
                    prompt_used=f"steps={active_steps}",
                    seed_used=seed,
                    request_payload=request_payload,
                    timestamps=timestamps,
                )

        except Exception as e:
            error_msg = str(e)
            total_duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(
                f"[PIPELINE] {job.job_id} | Status: FAILED | "
                f"Error: {error_msg} | Total: {total_duration:.2f}s"
            )
            traceback.print_exc()

            error_code = "PIPELINE_EDIT_ERROR"
            if _is_oom_error(error_msg):
                error_code = "GPU_OOM_ERROR"
            elif "download" in error_msg.lower():
                error_code = "DOWNLOAD_ERROR"
            elif "upload" in error_msg.lower() or "ComfyUI" in error_msg:
                error_code = "PROVIDER_ERROR"
            elif "No image" in error_msg:
                error_code = "NO_OUTPUT_ERROR"
            elif "No reference" in error_msg:
                error_code = "MISSING_REFERENCE_ERROR"

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.FAILED,
                error_message=error_msg,
                error_code=error_code,
            )

            if self.notification:
                await self.notification.send_job_failed(
                    job_id=job.job_id,
                    user_id=job.user_id,
                    error_message=error_msg,
                    error_code=error_code,
                    total_duration=total_duration,
                )

        finally:
            self.job_manager.mark_pipeline_done()
