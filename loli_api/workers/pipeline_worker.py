"""
Background worker for processing unified pipeline edit jobs.
Chains pose, outfit, and background steps in configurable order,
passing the output of each step as input to the next.
"""
import asyncio
import copy
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
from services.storage_service import StorageService
from services.supabase_storage_service import SupabaseStorageService
from services.notification_service import NotificationService
from services.image_cache_service import ImageCacheService
from models.enums import JobStatus

# Import helpers from existing endpoint modules
from api.v1.endpoints.outfit import build_prompt, prepare_outfit_workflow
from api.v1.endpoints.pose import get_pose_reference, prepare_pose_workflow
from api.v1.endpoints.background import build_background_prompt, prepare_background_workflow

logger = logging.getLogger(__name__)

# OOM retry settings
MAX_OOM_ATTEMPTS = 3
OOM_RETRY_DELAY = 2  # seconds

# Default order in which pipeline steps execute
DEFAULT_PIPELINE_ORDER = ["pose", "outfit", "background"]

# Output node IDs for each step's workflow
POSE_OUTPUT_NODES = ["164", "8", "6"]
OUTFIT_OUTPUT_NODES = ["116"]
BACKGROUND_OUTPUT_NODES = ["116"]


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


def _extract_output_images(output_images: dict, node_ids: List[str]) -> bytes:
    """
    Extract the first output image from workflow results,
    checking the given node IDs in order.

    Returns:
        Raw image bytes
    """
    images = None
    for node_id in node_ids:
        if isinstance(output_images, dict) and node_id in output_images:
            images = output_images[node_id]
            break
    if not images:
        images = next(iter(output_images.values()), []) if output_images else []
    if not images:
        raise RuntimeError("No images returned from workflow")
    return images[0]


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
    ):
        self.job_manager = job_manager
        self.comfyui_client = comfyui_client
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

    async def _upload_image_to_comfyui(
        self, comfyui: ComfyUIClient, image_bytes: bytes, prefix: str
    ) -> str:
        """Upload image bytes to ComfyUI and return the filename."""
        upload_filename = f"{prefix}_{uuid.uuid4().hex[:12]}.png"

        def _upload():
            comfyui.connect()
            result = comfyui.upload_image_bytes(
                upload_filename, image_bytes, content_type="image/png"
            )
            comfyui.disconnect()
            return result

        return await asyncio.to_thread(_upload)

    async def _execute_workflow_with_retry(
        self, comfyui: ComfyUIClient, workflow: dict, job_id: str, step_name: str
    ) -> dict:
        """Execute a ComfyUI workflow with OOM retry logic."""
        output_images = None
        for attempt in range(1, MAX_OOM_ATTEMPTS + 1):
            try:
                def _execute():
                    comfyui.connect()
                    result = comfyui.execute_workflow(workflow)
                    comfyui.disconnect()
                    return result

                logger.info(
                    f"[PIPELINE] {job_id} | {step_name} | "
                    f"Executing workflow (attempt {attempt}/{MAX_OOM_ATTEMPTS})..."
                )
                output_images = await asyncio.to_thread(_execute)
                return output_images
            except Exception as e:
                error_msg = str(e)
                if attempt < MAX_OOM_ATTEMPTS and _is_oom_error(error_msg):
                    logger.warning(
                        f"[PIPELINE] {job_id} | {step_name} | OOM on attempt {attempt}, "
                        f"retrying in {OOM_RETRY_DELAY}s..."
                    )
                    await asyncio.sleep(OOM_RETRY_DELAY)
                    continue
                raise RuntimeError(f"{step_name} workflow execution failed: {e}")

    async def _run_pose_step(
        self, comfyui: ComfyUIClient, request, comfyui_filename: str, seed: int, job_id: str
    ) -> bytes:
        """Run the pose editing step. Returns output image bytes."""
        reference_image = get_pose_reference(request.pose)
        logger.info(f"[PIPELINE] {job_id} | pose | Reference: {reference_image}")

        workflow = prepare_pose_workflow(
            self._pose_template, comfyui_filename, reference_image, seed=seed
        )

        output_images = await self._execute_workflow_with_retry(
            comfyui, workflow, job_id, "pose"
        )
        return _extract_output_images(output_images, POSE_OUTPUT_NODES)

    async def _run_outfit_step(
        self, comfyui: ComfyUIClient, request, comfyui_filename: str, seed: int, job_id: str
    ) -> bytes:
        """Run the outfit editing step. Returns output image bytes."""
        prompt = build_prompt(request.outfit, request.accessories, request.nudityLevel)
        logger.info(f"[PIPELINE] {job_id} | outfit | Prompt: {prompt[:80]}...")

        workflow = prepare_outfit_workflow(
            self._outfit_template, comfyui_filename, prompt, seed=seed
        )

        output_images = await self._execute_workflow_with_retry(
            comfyui, workflow, job_id, "outfit"
        )
        return _extract_output_images(output_images, OUTFIT_OUTPUT_NODES)

    async def _run_background_step(
        self, comfyui: ComfyUIClient, request, comfyui_filename: str, seed: int, job_id: str,
    ) -> bytes:
        """
        Run the background/scene editing step. Returns output image bytes.

        Uses the same workflow template as outfit, but overrides SAM3 text
        prompts to target background/scene and uses a scene-oriented prompt.
        """
        prompt = build_background_prompt(request.prompt)
        logger.info(f"[PIPELINE] {job_id} | background | Prompt: {prompt[:80]}...")

        workflow = prepare_background_workflow(
            self._outfit_template,
            comfyui_filename,
            prompt,
            seed=seed,
            negative_prompt=request.negativePrompt,
        )

        output_images = await self._execute_workflow_with_retry(
            comfyui, workflow, job_id, "background"
        )
        return _extract_output_images(output_images, BACKGROUND_OUTPUT_NODES)

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

            # Step 2: Download / cache source image
            comfyui = ComfyUIClient(server_address=self.comfyui_client.server_address)
            comfyui_filename = None
            image_bytes = None  # Track source image bytes for dimension extraction

            if self.image_cache:
                cached = self.image_cache.get(request.source_image)
                if cached:
                    comfyui_filename = cached.comfyui_filename
                    logger.info(f"[PIPELINE] {job.job_id} | Cache hit: {comfyui_filename}")

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.05
            )

            if not comfyui_filename:
                logger.info(f"[PIPELINE] {job.job_id} | Cache miss, downloading...")
                image_bytes = await asyncio.to_thread(
                    _download_image, request.source_image
                )
                logger.info(
                    f"[PIPELINE] {job.job_id} | Downloaded {len(image_bytes)} bytes"
                )

                # Determine content type from URL
                content_type = "image/png"
                src_lower = request.source_image.lower()
                if src_lower.endswith(".jpg") or src_lower.endswith(".jpeg"):
                    content_type = "image/jpeg"
                elif src_lower.endswith(".webp"):
                    content_type = "image/webp"

                ext = content_type.split("/")[-1]
                if ext == "jpeg":
                    ext = "jpg"
                upload_filename = f"pipeline_{uuid.uuid4().hex[:12]}.{ext}"

                def _upload_to_comfyui():
                    comfyui.connect()
                    result = comfyui.upload_image_bytes(
                        upload_filename, image_bytes, content_type=content_type
                    )
                    comfyui.disconnect()
                    return result

                try:
                    comfyui_filename = await asyncio.to_thread(_upload_to_comfyui)
                    logger.info(
                        f"[PIPELINE] {job.job_id} | Uploaded as {comfyui_filename}"
                    )
                    if self.image_cache:
                        self.image_cache.put(request.source_image, comfyui_filename)
                except Exception as e:
                    raise RuntimeError(f"Failed to upload image to ComfyUI: {e}")

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

            # Step 4: Execute each step, chaining outputs
            step_runners = {
                "pose": self._run_pose_step,
                "outfit": self._run_outfit_step,
                "background": self._run_background_step,
            }

            num_steps = len(active_steps)
            # Progress range: 0.15 to 0.85 divided among steps
            progress_per_step = 0.70 / num_steps if num_steps > 0 else 0.70
            current_comfyui_filename = comfyui_filename
            image_start = datetime.utcnow()

            for i, step_name in enumerate(active_steps):
                step_progress_start = 0.15 + (i * progress_per_step)

                await self.job_manager.update_job_status(
                    job.job_id, JobStatus.RUNNING, progress=step_progress_start
                )

                logger.info(
                    f"[PIPELINE] {job.job_id} | Step {i+1}/{num_steps}: {step_name}"
                )

                runner = step_runners[step_name]
                output_bytes = await runner(
                    comfyui, request, current_comfyui_filename, seed, job.job_id
                )

                logger.info(
                    f"[PIPELINE] {job.job_id} | {step_name} complete, "
                    f"output: {len(output_bytes)} bytes"
                )

                # If there are more steps, re-upload output as input for next step
                if i < num_steps - 1:
                    current_comfyui_filename = await self._upload_image_to_comfyui(
                        comfyui, output_bytes, f"pipe_{step_name}"
                    )
                    logger.info(
                        f"[PIPELINE] {job.job_id} | Re-uploaded as {current_comfyui_filename}"
                    )

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
