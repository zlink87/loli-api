"""
Base class for edit workers (outfit, pose, background).
Extracts common patterns: init, start/stop lifecycle, workflow loading,
image download/upload, OOM retry, output saving, error handling.
"""
import asyncio
import base64
import json
import traceback
import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
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

logger = logging.getLogger(__name__)


class BaseEditWorker(ABC):
    """
    Abstract base class for edit workers that share the same init signature
    and common processing patterns (outfit, pose, background edit).

    Subclasses must implement:
        - worker_name: property returning a display name (e.g. "Outfit")
        - _get_next_job(): get next job_id from the appropriate queue
        - _mark_job_done(): mark the queue task as done
        - _process_job(job): process a single job
    """

    # Subclasses can override these for different OOM retry behaviour
    max_oom_attempts: int = 3
    oom_retry_delay: int = 1  # seconds

    def __init__(
        self,
        job_manager: JobManager,
        comfyui_client: ComfyUIClient,
        storage_service: StorageService,
        workflow_path: str,
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
        self.workflow_path = workflow_path
        self.image_cache = image_cache_service
        self.notification = notification_service
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._workflow_template: Optional[dict] = None
        # Source images to send with the next RunPod submission (set by prepare_source_image).
        self._pending_images: Optional[list] = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def worker_name(self) -> str:
        """Human-readable name used in log messages, e.g. 'Outfit'."""
        ...

    @abstractmethod
    async def _get_next_job(self) -> str:
        """Block until the next job_id is available from the queue."""
        ...

    @abstractmethod
    def _mark_job_done(self) -> None:
        """Signal the queue that the current job is finished."""
        ...

    @abstractmethod
    async def _process_job(self, job: Job) -> None:
        """Process a single job. Implemented by each concrete worker."""
        ...

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background worker."""
        self._running = True
        await self._load_workflow()
        self._task = asyncio.create_task(self._worker_loop())
        logger.info(f"{self.worker_name} background worker started")

    async def stop(self) -> None:
        """Stop the background worker gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"{self.worker_name} background worker stopped")

    async def _load_workflow(self) -> None:
        """Load the workflow template from file."""
        try:
            workflow_file = Path(self.workflow_path)
            if not workflow_file.exists():
                raise FileNotFoundError(
                    f"{self.worker_name} workflow not found: {self.workflow_path}"
                )
            with open(workflow_file, "r", encoding="utf-8") as f:
                self._workflow_template = json.load(f)
            logger.info(
                f"Loaded {self.worker_name.lower()} workflow template: {self.workflow_path}"
            )
        except Exception as e:
            logger.error(f"Failed to load {self.worker_name.lower()} workflow: {e}")
            raise

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        """Main worker loop — dequeue jobs and dispatch to _process_job."""
        name_lower = self.worker_name.lower()
        log_tag = self._log_tag
        logger.info(f"{self.worker_name} worker loop started, waiting for jobs...")

        while self._running:
            try:
                job_id = await self._get_next_job()
                job = await self.job_manager.get_job(job_id)

                if not job:
                    logger.warning(f"{self.worker_name} job {job_id} not found in registry")
                    self._mark_job_done()
                    continue

                # Skip cancelled jobs
                if job.status == JobStatus.FAILED:
                    logger.info(f"Skipping cancelled {name_lower} job {job_id}")
                    self._mark_job_done()
                    continue

                logger.info(
                    f"Processing {name_lower} job {job_id} for user {job.user_id}"
                )
                await self._process_job(job)

            except asyncio.CancelledError:
                logger.info(f"{self.worker_name} worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in {name_lower} worker loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_oom_error(error_msg: str) -> bool:
        """Check if error is a CUDA out-of-memory error."""
        lower = error_msg.lower()
        return "out of memory" in lower or "outofmemoryerror" in lower

    @staticmethod
    def download_image(url: str, timeout: int = 30) -> bytes:
        """Download image from URL. Raises RuntimeError on failure."""
        try:
            response = http_requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.content
        except http_requests.RequestException as e:
            raise RuntimeError(f"Failed to download source image: {e}")

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    @property
    def _log_tag(self) -> str:
        """Log prefix, e.g. '[OUTFIT]'."""
        return f"[{self.worker_name.upper()}]"

    async def prepare_source_image(
        self, job: Job, source_url: str, prefix: str
    ) -> str:
        """
        Download the source image and stage it for the RunPod submission as a
        base64 ``input.images[]`` entry. Returns the image NAME that the workflow's
        LoadImage node should reference (worker-comfyui writes the file under this
        name in the worker's ComfyUI input dir).

        ``prefix`` is used for the image name, e.g. "outfit", "pose", "bg".
        """
        log_tag = self._log_tag

        await self.job_manager.update_job_status(
            job.job_id, JobStatus.RUNNING, progress=0.1
        )

        logger.info(f"{log_tag} {job.job_id} | Downloading source image...")
        image_bytes = await asyncio.to_thread(self.download_image, source_url)
        logger.info(f"{log_tag} {job.job_id} | Downloaded {len(image_bytes)} bytes")

        # Determine content type / extension from the URL.
        content_type = "image/png"
        src_lower = source_url.lower()
        if src_lower.endswith(".jpg") or src_lower.endswith(".jpeg"):
            content_type = "image/jpeg"
        elif src_lower.endswith(".webp"):
            content_type = "image/webp"

        ext = content_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"
        image_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"

        b64 = base64.b64encode(image_bytes).decode("ascii")
        self._pending_images = [
            {"name": image_name, "image": f"data:{content_type};base64,{b64}"}
        ]

        await self.job_manager.update_job_status(
            job.job_id, JobStatus.RUNNING, progress=0.2
        )
        return image_name

    async def submit_and_save(
        self, job: Job, workflow: dict, folder: str
    ) -> tuple:
        """
        Submit a prepared workflow to RunPod, wait for completion, and persist the
        output. Returns (relative_path, preview_url, expires_at, image_hash).

        If the worker uploaded the result to S3/Supabase (preferred), the returned
        URL is recorded directly. Otherwise base64 output is uploaded via
        ``save_output_image``.
        """
        if self.runpod_client is None:
            raise RuntimeError("RunPod client not configured")

        outputs = await runpod_runner.run_workflow(
            self.runpod_client,
            self.job_manager,
            job.job_id,
            workflow,
            images=self._pending_images,
        )
        self._pending_images = None

        if not outputs:
            raise RuntimeError("No images returned from RunPod workflow")

        first = outputs[0]
        if first.get("url"):
            return first.get("filename") or first["url"], first["url"], None, None

        data = first.get("data")
        if not data:
            raise RuntimeError("No image data in RunPod output")
        image_bytes = base64.b64decode(data)
        return await self.save_output_image(image_bytes, job.job_id, folder)

    async def save_output_image(
        self, image_data: bytes, job_id: str, folder: str
    ) -> tuple:
        """
        Save output image to Supabase or local storage.

        Returns (relative_path, preview_url, expires_at, image_hash).
        """
        log_tag = self._log_tag

        if self.supabase_storage:
            logger.info(f"{log_tag} {job_id} | Uploading to Supabase")
            preview_url, image_hash = await asyncio.to_thread(
                self.supabase_storage.upload_image,
                image=image_data,
                image_id=job_id,
                folder=folder,
            )
            expires_at = None
            relative_path = f"{folder}/{job_id}.png"
        else:
            logger.info(f"{log_tag} {job_id} | Saving to local storage")
            relative_path, image_hash = self.storage.save_image(image_data, job_id)
            preview_url, expires_at = self.storage.generate_signed_url(relative_path)

        return relative_path, preview_url, expires_at, image_hash

    async def handle_job_failure(
        self,
        job: Job,
        error_msg: str,
        error_code_prefix: str,
        start_time: datetime,
    ) -> None:
        """
        Common error handling: determine error code, update job status, send
        failure notification.

        ``error_code_prefix`` is the default error code, e.g. "OUTFIT_EDIT_ERROR".
        """
        log_tag = self._log_tag
        total_duration = (datetime.utcnow() - start_time).total_seconds()

        logger.error(
            f"{log_tag} {job.job_id} | Status: FAILED | "
            f"Error: {error_msg} | Total: {total_duration:.2f}s"
        )
        traceback.print_exc()

        error_code = error_code_prefix
        if self.is_oom_error(error_msg):
            error_code = "GPU_OOM_ERROR"
        elif "download" in error_msg.lower():
            error_code = "DOWNLOAD_ERROR"
        elif "upload" in error_msg.lower() or "ComfyUI" in error_msg:
            error_code = "PROVIDER_ERROR"
        elif "No image" in error_msg:
            error_code = "NO_OUTPUT_ERROR"

        await self.job_manager.update_job_status(
            job.job_id,
            JobStatus.FAILED,
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
