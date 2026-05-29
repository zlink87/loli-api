"""
Background worker for processing image generation jobs.
Based on queue_worker pattern from app.py lines 1915-2075.
"""
import asyncio
import base64
import json
import random
import traceback
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

from services.job_manager import JobManager, Job
from services.comfyui_client import ComfyUIClient
from services.runpod_client import RunPodServerlessClient
from services import runpod_runner
from services.prompt_generator import PromptGenerator
from services.storage_service import StorageService
from services.supabase_storage_service import SupabaseStorageService
from services.notification_service import NotificationService
from models.enums import JobStatus

logger = logging.getLogger(__name__)


def _is_oom_error(error_msg: str) -> bool:
    """Check if error is a CUDA out-of-memory error."""
    lower = error_msg.lower()
    return "out of memory" in lower or "outofmemoryerror" in lower


class BackgroundWorker:
    """
    Async worker that processes jobs from the queue.
    Follows the queue_worker pattern from existing app.py.

    Workflow:
    1. Get job from queue
    2. Generate prompt using xAI Grok-4
    3. Prepare ComfyUI workflow with parameters
    4. Execute workflow and wait for completion
    5. Save output image and generate signed URL
    6. Update job status
    """

    def __init__(
        self,
        job_manager: JobManager,
        comfyui_client: ComfyUIClient,
        prompt_generator: PromptGenerator,
        storage_service: StorageService,
        workflow_path: str,
        notification_service: Optional[NotificationService] = None,
        supabase_storage_service: Optional[SupabaseStorageService] = None,
        runpod_client: Optional[RunPodServerlessClient] = None
    ):
        """
        Initialize background worker.

        Args:
            job_manager: Job queue and state manager
            comfyui_client: ComfyUI WebSocket client
            prompt_generator: xAI prompt generation service
            storage_service: Local storage service
            workflow_path: Path to ComfyUI workflow JSON
            notification_service: Google Chat notification service (optional)
            supabase_storage_service: Supabase storage service (optional, used if provided)
        """
        self.job_manager = job_manager
        self.comfyui = comfyui_client
        self.runpod_client = runpod_client
        self.prompt_gen = prompt_generator
        self.storage = storage_service
        self.supabase_storage = supabase_storage_service
        self.workflow_path = workflow_path
        self.notification = notification_service
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._workflow_template: Optional[dict] = None

    async def start(self) -> None:
        """Start the background worker."""
        self._running = True

        # Load workflow template
        await self._load_workflow()

        self._task = asyncio.create_task(self._worker_loop())
        logger.info("Background worker started")

    async def stop(self) -> None:
        """Stop the background worker gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Background worker stopped")

    async def _load_workflow(self) -> None:
        """Load the workflow template from file."""
        try:
            workflow_file = Path(self.workflow_path)
            if not workflow_file.exists():
                raise FileNotFoundError(f"Workflow file not found: {self.workflow_path}")

            with open(workflow_file, 'r', encoding='utf-8') as f:
                self._workflow_template = json.load(f)

            logger.info(f"Loaded workflow template: {self.workflow_path}")
        except Exception as e:
            logger.error(f"Failed to load workflow: {e}")
            raise

    async def _worker_loop(self) -> None:
        """Main worker loop processing jobs."""
        logger.info("Worker loop started, waiting for jobs...")

        while self._running:
            try:
                # Get next job from queue (blocking)
                job_id = await self.job_manager.get_next_job()
                job = await self.job_manager.get_job(job_id)

                if not job:
                    logger.warning(f"Job {job_id} not found in registry")
                    self.job_manager.mark_done()
                    continue

                # Skip cancelled jobs
                if job.status == JobStatus.FAILED:
                    logger.info(f"Skipping cancelled job {job_id}")
                    self.job_manager.mark_done()
                    continue

                logger.info(f"Processing job {job_id} for user {job.user_id}")
                await self._process_job(job)

            except asyncio.CancelledError:
                logger.info("Worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    async def _process_job(self, job: Job) -> None:
        """
        Process a single job.

        Steps:
        1. Update status to RUNNING
        2. Generate prompt using xAI Grok-4
        3. Prepare workflow with parameters
        4. Execute workflow in ComfyUI
        5. Save output image
        6. Generate signed preview URL
        7. Update job as succeeded
        """
        # Safety guard: only process character generation jobs
        if hasattr(job, 'job_type') and job.job_type != "text_to_image":
            logger.warning(f"Skipping non-character job {job.job_id} (type={job.job_type})")
            self.job_manager.mark_done()
            return

        start_time = datetime.utcnow()
        prompt_duration = 0.0
        image_duration = 0.0
        character_prompt = ""
        preview_url = ""
        # Timestamps for job lifecycle
        prompt_generated_at = None
        image_generated_at = None
        completed_at = None

        try:
            # Step 1: Update status to RUNNING
            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.RUNNING,
                progress=0.0
            )
            logger.info(f"[JOB] {job.job_id} | Status: RUNNING | User: {job.user_id}")

            # Step 2: Generate prompt or use context directly
            context = job.request.context if hasattr(job.request, 'context') else None
            is_enhance = job.request.isEnhance if hasattr(job.request, 'isEnhance') else True

            prompt_start = datetime.utcnow()
            logger.info(f"[PROMPT] {job.job_id} | START: {prompt_start.strftime('%Y-%m-%d %H:%M:%S')}")

            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.RUNNING,
                progress=0.1
            )

            # Token usage info (will be populated if xAI Grok polishing is used)
            token_usage = None
            negative_prompt = None

            # Deterministic assembly from persona enums + admin free-text. When
            # is_enhance is True, Grok polishes the draft but cannot change the
            # locked identity attributes; otherwise the deterministic prompt is used.
            try:
                character_prompt, negative_prompt, _locked, token_usage = (
                    await self.prompt_gen.generate_generation_prompt(
                        persona=job.request.persona,
                        context=context,
                        is_enhance=is_enhance,
                    )
                )
            except Exception as e:
                logger.error(f"[PROMPT] {job.job_id} | ERROR: {e}")
                raise RuntimeError(f"Prompt generation failed: {e}")

            prompt_end = datetime.utcnow()
            prompt_duration = (prompt_end - prompt_start).total_seconds()
            prompt_generated_at = prompt_end

            logger.info(f"[PROMPT] {job.job_id} | CONTENT: \"{character_prompt}...\"" if len(character_prompt) > 100 else f"[PROMPT] {job.job_id} | CONTENT: \"{character_prompt}\"")
            logger.info(f"[PROMPT] {job.job_id} | END: {prompt_end.strftime('%Y-%m-%d %H:%M:%S')} | Duration: {prompt_duration:.2f}s")

            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.RUNNING,
                progress=0.2,
                prompt_used=character_prompt,
                prompt_generated_at=prompt_generated_at
            )

            # Step 3: Prepare workflow

            # Output overrides are optional; only apply if explicitly provided
            output = job.request.output
            seed = None
            resolution = None
            aspect_ratio = None
            batch_size = None
            if output:
                if "seed" in output.model_fields_set:
                    seed = output.seed
                if "resolution" in output.model_fields_set:
                    resolution = output.resolution
                if "aspectRatio" in output.model_fields_set:
                    aspect_ratio = output.aspectRatio
                if "n" in output.model_fields_set:
                    batch_size = output.n

            # Generate random seed if not provided
            if seed is None:
                seed = random.randint(0, 2**32 - 1)

            workflow = ComfyUIClient.prepare_character_workflow(
                workflow_template=self._workflow_template,
                character_prompt=character_prompt,
                seed=seed,
                filename_prefix=f"CHAR_{job.job_id[:8]}",
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                batch_size=batch_size,
                negative_prompt=negative_prompt
            )

            logger.info(f"[WORKFLOW] {job.job_id} | Seed: {seed}")

            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.RUNNING,
                progress=0.3,
                seed_used=seed
            )

            # Step 4: Execute workflow in ComfyUI (with OOM retry)
            image_start = datetime.utcnow()
            logger.info(f"[IMAGE] {job.job_id} | START: {image_start.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"[IMAGE] {job.job_id} | PROMPT: \"{character_prompt}...\"" if len(character_prompt) > 100 else f"[IMAGE] {job.job_id} | PROMPT: \"{character_prompt}\"")

            try:
                outputs = await runpod_runner.run_workflow(
                    self.runpod_client,
                    self.job_manager,
                    job.job_id,
                    workflow,
                    images=None,
                )
            except Exception as e:
                logger.error(f"[IMAGE] {job.job_id} | ERROR: {e}")
                raise RuntimeError(f"Image generation failed: {e}")

            image_end = datetime.utcnow()
            image_duration = (image_end - image_start).total_seconds()
            image_generated_at = image_end
            logger.info(f"[IMAGE] {job.job_id} | END: {image_end.strftime('%Y-%m-%d %H:%M:%S')} | Duration: {image_duration:.2f}s")

            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.RUNNING,
                progress=0.8,
                image_generated_at=image_generated_at
            )

            # Step 5: Resolve output image
            if not outputs:
                raise RuntimeError("No images generated from workflow")
            first = outputs[0]

            # Use request.id from payload as the image identifier
            # Falls back to job_id if request.id is not provided
            image_id = job.request.id if job.request.id else job.job_id

            # Step 6: Persist result.
            if first.get("url"):
                # Worker uploaded directly to S3/Supabase — just record the URL.
                preview_url = first["url"]
                image_hash = None
                expires_at = None
                relative_path = first.get("filename") or preview_url
                logger.info(f"[STORAGE] {job.job_id} | RunPod worker uploaded: {preview_url}")
            else:
                data = first.get("data")
                if not data:
                    raise RuntimeError("No image data in workflow output")
                image_data = base64.b64decode(data)
                if self.supabase_storage:
                    logger.info(f"[STORAGE] {job.job_id} | Using SUPABASE | image_id={image_id}")
                    preview_url, image_hash = await asyncio.to_thread(
                        self.supabase_storage.upload_image,
                        image=image_data,
                        image_id=image_id
                    )
                    expires_at = None  # Supabase public URLs don't expire
                    relative_path = f"character_creation/{image_id}.png"
                    logger.info(f"[STORAGE] {job.job_id} | SUPABASE UPLOAD SUCCESS | URL: {preview_url}")
                else:
                    logger.info(f"[STORAGE] {job.job_id} | Using LOCAL storage")
                    relative_path, image_hash = self.storage.save_image(
                        image_data,
                        job.job_id
                    )
                    preview_url, expires_at = self.storage.generate_signed_url(relative_path)
                logger.info(f"[STORAGE] {job.job_id} | LOCAL SAVE SUCCESS | URL: {preview_url}")

            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.RUNNING,
                progress=0.9
            )

            # Step 7: Update job as succeeded
            completed_at = datetime.utcnow()
            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.SUCCEEDED,
                progress=1.0,
                result_path=relative_path,
                preview_url=preview_url,
                preview_expires_at=expires_at,
                image_hash=image_hash,
                completed_at=completed_at
            )

            total_duration = (completed_at - start_time).total_seconds()
            logger.info(
                f"[JOB] {job.job_id} | Status: SUCCEEDED | "
                f"Total: {total_duration:.2f}s | Prompt: {prompt_duration:.2f}s | Image: {image_duration:.2f}s"
            )

            # Send success notification to Google Chat (RESPONSE webhook)
            if self.notification:
                # Serialize request payload for notification
                request_payload = job.request.model_dump(mode="json")

                # Build ResponseData for callback
                response_data = {
                    "id": job.request.id,
                    "url": preview_url
                }

                # Build timestamps
                def format_timestamp(dt):
                    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else None

                timestamps = {
                    "jobCreatedAt": format_timestamp(job.created_at),
                    "promptGeneratedAt": format_timestamp(prompt_generated_at),
                    "imageGeneratedAt": format_timestamp(image_generated_at),
                    "jobCompletedAt": format_timestamp(completed_at)
                }

                await self.notification.send_job_completed(
                    job_id=job.job_id,
                    user_id=job.user_id,
                    prompt_duration=prompt_duration,
                    image_duration=image_duration,
                    total_duration=total_duration,
                    preview_url=preview_url,
                    prompt_used=character_prompt,
                    request_payload=request_payload,
                    response_data=response_data,
                    timestamps=timestamps,
                    token_usage=token_usage,
                    seed_used=seed
                )

        except Exception as e:
            error_msg = str(e)
            total_duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"[JOB] {job.job_id} | Status: FAILED | Error: {error_msg} | Total: {total_duration:.2f}s")
            traceback.print_exc()

            # Determine error code
            error_code = "INTERNAL_ERROR"
            if _is_oom_error(error_msg):
                error_code = "GPU_OOM_ERROR"
            elif "Prompt generation" in error_msg:
                error_code = "PROMPT_GENERATION_ERROR"
            elif "Image generation" in error_msg or "ComfyUI" in error_msg:
                error_code = "PROVIDER_ERROR"
            elif "No image" in error_msg:
                error_code = "NO_OUTPUT_ERROR"

            await self.job_manager.update_job_status(
                job.job_id,
                JobStatus.FAILED,
                error_message=error_msg,
                error_code=error_code
            )

            # Send failure notification to Google Chat (RESPONSE webhook)
            if self.notification:
                await self.notification.send_job_failed(
                    job_id=job.job_id,
                    user_id=job.user_id,
                    error_message=error_msg,
                    error_code=error_code,
                    total_duration=total_duration
                )

        finally:
            self.job_manager.mark_done()

    def _parse_resolution(self, request) -> tuple[int, int]:
        """
        Parse resolution from request.

        Args:
            request: GenerateImageRequest

        Returns:
            Tuple of (width, height)
        """
        # Default dimensions
        width = 944
        height = 1408

        if request.output:
            # Try to parse from resolution string (e.g., "944x1408")
            if request.output.resolution:
                try:
                    parts = request.output.resolution.lower().split("x")
                    if len(parts) == 2:
                        width = int(parts[0])
                        height = int(parts[1])
                except (ValueError, IndexError):
                    logger.warning(f"Invalid resolution: {request.output.resolution}, using default")

            # Or parse from aspect ratio (if resolution not provided)
            elif request.output.aspectRatio:
                # Common aspect ratios
                aspect_ratios = {
                    "1:1": (1024, 1024),
                    "2:3": (944, 1408),
                    "3:2": (1408, 944),
                    "16:9": (1408, 792),
                    "9:16": (792, 1408),
                    "4:3": (1216, 912),
                    "3:4": (912, 1216),
                }
                if request.output.aspectRatio in aspect_ratios:
                    width, height = aspect_ratios[request.output.aspectRatio]

        return width, height


class CleanupWorker:
    """
    Background worker for periodic cleanup tasks.
    """

    def __init__(
        self,
        job_manager: JobManager,
        storage_service: StorageService,
        cleanup_interval_hours: int = 1,
        job_max_age_hours: int = 24,
        image_max_age_days: int = 7
    ):
        self.job_manager = job_manager
        self.storage = storage_service
        self.cleanup_interval = cleanup_interval_hours * 3600
        self.job_max_age = job_max_age_hours
        self.image_max_age = image_max_age_days
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the cleanup worker."""
        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info("Cleanup worker started")

    async def stop(self) -> None:
        """Stop the cleanup worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cleanup worker stopped")

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup loop."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)

                # Cleanup old jobs
                jobs_removed = await self.job_manager.cleanup_old_jobs(self.job_max_age)
                if jobs_removed > 0:
                    logger.info(f"Cleaned up {jobs_removed} old jobs")

                # Cleanup old images
                images_removed = self.storage.cleanup_old_images(self.image_max_age)
                if images_removed > 0:
                    logger.info(f"Cleaned up {images_removed} old images")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
