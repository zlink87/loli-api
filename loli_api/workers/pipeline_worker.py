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
from api.v1.endpoints.outfit import build_prompt, prepare_outfit_workflow
from api.v1.endpoints.pose import build_pose_prompt, prepare_pose_workflow
from api.v1.endpoints.background import build_background_prompt, prepare_background_workflow

from services import head_mask as head_mask_service
from services import pose_assets
from services.prompt_constants import apply_edit_photo_style

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
        self.image_cache = image_cache_service
        self.notification = notification_service
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Workflow templates loaded on start
        self._pose_template: Optional[dict] = None
        self._outfit_template: Optional[dict] = None

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
        """Load workflow templates from files (background reuses outfit template)."""
        for label, path, attr in [
            ("pose", self.pose_workflow_path, "_pose_template"),
            ("outfit/background", self.outfit_workflow_path, "_outfit_template"),
        ]:
            try:
                workflow_file = Path(path)
                if not workflow_file.exists():
                    raise FileNotFoundError(f"{label} workflow not found: {path}")
                with open(workflow_file, "r", encoding="utf-8") as f:
                    setattr(self, attr, json.load(f))
                logger.info(f"Loaded {label} workflow template: {path}")
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
        is_final_step: bool = True,
    ) -> dict:
        """
        Build the ComfyUI workflow for a pipeline step, with source_name as input.

        For the pose step, ``pose_ref_name`` is the flat filename of the staged
        pose reference (node 170); for the outfit step, ``head_mask_name`` is the
        flat filename of the staged server-computed head-protect mask (node 211).
        Both are computed once in ``_run_step`` so the same names feed the nodes
        and the base64 ``input.images[]`` entries.
        """
        # Optional photographic-finish clause. Applied ONLY on the last active
        # step: earlier revisions applied it at every step, and 2-3 re-diffusions
        # of the same "warm grade / bokeh" language each compounded the effect
        # into oversaturated, plastic-looking output. One application at the end
        # gives a consistent finish without the re-diffusion pileup.
        photo_style = getattr(request, "photoStyle", None) if is_final_step else None

        if step_name == "pose":
            logger.info(f"[PIPELINE] {job_id} | pose | Reference: {pose_ref_name}")
            prompt = apply_edit_photo_style(build_pose_prompt(request.pose), photo_style)
            return prepare_pose_workflow(
                self._pose_template, source_name, pose_ref_name, prompt=prompt, seed=seed
            )
        if step_name == "outfit":
            prompt = apply_edit_photo_style(
                build_prompt(request.outfit, request.accessories, request.nudityLevel),
                photo_style,
            )
            logger.info(f"[PIPELINE] {job_id} | outfit | Prompt: {prompt[:80]}...")
            return prepare_outfit_workflow(
                self._outfit_template, source_name, prompt, seed=seed,
                nudity_level=request.nudityLevel, outfit=request.outfit,
                head_mask_name=head_mask_name,
            )
        if step_name == "background":
            prompt = apply_edit_photo_style(build_background_prompt(request.prompt), photo_style)
            logger.info(f"[PIPELINE] {job_id} | background | Prompt: {prompt[:80]}...")
            return prepare_background_workflow(
                self._outfit_template, source_name, prompt, seed=seed,
                negative_prompt=request.negativePrompt,
                nudity_level=request.nudityLevel,
            )
        raise RuntimeError(f"Unknown pipeline step: {step_name}")

    async def _run_step(
        self, step_name: str, request, source_bytes: bytes, seed: int, job_id: str,
        progress_start: float, progress_end: float,
        is_final_step: bool = True,
    ) -> bytes:
        """
        Run one pipeline step on RunPod with source_bytes as the input image.
        Returns the output image bytes (downloading the worker's S3 URL if needed).
        """
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
                    f"({'face found' if face_found else 'no face — black mask'})"
                )
            except Exception as e:  # noqa: BLE001 — protective, not critical
                logger.warning(f"[PIPELINE] {job_id} | Head mask failed: {e}")

        workflow = self._build_step_workflow(
            step_name, request, source_name, seed, job_id,
            pose_ref_name=pose_ref_name, head_mask_name=head_mask_name,
            is_final_step=is_final_step,
        )

        outputs = await runpod_runner.run_workflow(
            self.runpod_client, self.job_manager, job_id, workflow,
            images=images, progress_start=progress_start, progress_end=progress_end,
        )
        if not outputs:
            raise RuntimeError(f"No images returned from {step_name} step")
        first = outputs[0]
        if first.get("url"):
            return await asyncio.to_thread(_download_image, first["url"])
        data = first.get("data")
        if not data:
            raise RuntimeError(f"No image data from {step_name} step")
        return base64.b64decode(data)

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

                current_bytes = await self._run_step(
                    step_name, request, current_bytes, seed, job.job_id,
                    progress_start=step_progress_start, progress_end=step_progress_end,
                    is_final_step=(i == num_steps - 1),
                )

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
