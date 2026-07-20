"""
VideoBatchWorker — a dedicated, SUBMIT-ONLY worker for video-batch items.

The worker does the minimum: dequeue a batch item's job, download + stage the
source still, select the template (lightning vs baseline per quality_mode/tier),
prepare the WAN 2.2 i2v workflow (runtime preset-LoRA insertion + interpolate for
the lightning path), then ``runpod_client.submit()`` and persist
``runpod_request_id`` + ``status='running'`` + ``submitted_at`` +
``runpod_status='IN_QUEUE'`` on the item row. IT DOES NOT POLL — the
``VideoBatchReconciler`` owns polling / persistence / retry / recovery, so a deploy
never strands an in-flight clip (the durable ``runpod_request_id`` recovers it).

Run a pool of ``VIDEO_BATCH_WORKER_POOL_SIZE`` of these; keep the RunPod video
endpoint's max_workers >= that.

The item's resolved render inputs travel on the job's ``request`` as a
``VideoBatchJobRequest`` (built by the reconciler at enqueue), so the worker needs
no read to prepare the workflow — only one write to persist the RunPod handle.
"""
import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import json

from config import settings
from models.enums import JobStatus
from models.requests import (
    VIDEO_DEFAULT_WIDTH,
    VIDEO_DEFAULT_HEIGHT,
    VIDEO_DEFAULT_LENGTH,
    VIDEO_DEFAULT_FPS,
)
from services import prompt_constants as pc
from services.job_manager import Job, JobManager
from services.comfyui_client import ComfyUIClient
from services.runpod_client import RunPodServerlessClient
from services.storage_service import StorageService
from services.supabase_storage_service import SupabaseStorageService
from services.notification_service import NotificationService
from services.image_cache_service import ImageCacheService
from services.video_workflow import (
    build_catalog_prompt,
    select_video_template,
    prepare_lightning_video_workflow,
    prepare_video_workflow,
)
from workers.base_worker import BaseEditWorker, MAX_PENDING_IMAGES_BYTES

logger = logging.getLogger(__name__)

VIDEO_BATCH_JOB_TYPE = "video_batch"


@dataclass
class VideoBatchJobRequest:
    """Carrier for one video-batch item's resolved render inputs.

    Built by the reconciler at enqueue from the durable item row + batch defaults,
    handed to the worker via ``Job.request``. Everything here was resolved AT LAUNCH
    (motion text, loras, dims, seed), so the worker stays network-free apart from the
    RunPod submit + one item-row write.
    """

    batch_id: str
    item_id: str
    character_id: str
    source_image: str            # resolved still URL
    motion_text: str             # raw motion description (build_catalog_prompt composes the WAN prompt)
    quality_mode: str            # 'fast' | 'max'
    tier: Optional[str] = None   # catalog tier (explicit forces lightning); None for custom
    negative_prompt: Optional[str] = None
    seed: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    length: Optional[int] = None
    fps: Optional[int] = None
    loras: List[dict] = field(default_factory=list)
    interpolate: bool = False


class VideoBatchWorker(BaseEditWorker):
    """Submit-only worker draining the dedicated video-batch queue."""

    # A submit is cheap; there is no in-worker OOM retry (the reconciler owns retry).
    max_oom_attempts = 1
    oom_retry_delay = 1

    def __init__(
        self,
        job_manager: JobManager,
        comfyui_client: ComfyUIClient,
        storage_service: StorageService,
        lightning_workflow_path: str,
        video_batch_store,
        baseline_workflow_path: str = "",
        image_cache_service: Optional[ImageCacheService] = None,
        notification_service: Optional[NotificationService] = None,
        supabase_storage_service: Optional[SupabaseStorageService] = None,
        runpod_client: Optional[RunPodServerlessClient] = None,
        name: str = "video-batch-0",
    ):
        # The lightning graph is the PRIMARY template (fast + explicit paths); load it
        # as the base's workflow_path. The baseline graph (for quality_mode='max') is
        # loaded separately below.
        super().__init__(
            job_manager=job_manager,
            comfyui_client=comfyui_client,
            storage_service=storage_service,
            workflow_path=lightning_workflow_path,
            image_cache_service=image_cache_service,
            notification_service=notification_service,
            supabase_storage_service=supabase_storage_service,
            runpod_client=runpod_client,
        )
        self.video_batch_store = video_batch_store
        self.name = name
        self.baseline_workflow_path = baseline_workflow_path
        self._baseline_template: Optional[dict] = None

    @property
    def worker_name(self) -> str:
        return "VideoBatch"

    async def _get_next_job(self) -> str:
        return await self.job_manager.get_next_video_batch_job()

    def _mark_job_done(self) -> None:
        self.job_manager.mark_video_batch_done()

    async def _load_workflow(self) -> None:
        """Load the lightning (primary) template, then the optional baseline template.

        A missing/broken baseline template must NOT stop the worker: it only disables
        the (opt-in) quality_mode='max' path, leaving the lightning path — the default
        — untouched. So load it guarded and log a warning on failure."""
        await super()._load_workflow()

        if not self.baseline_workflow_path:
            return
        try:
            baseline_file = Path(self.baseline_workflow_path)
            if not baseline_file.exists():
                raise FileNotFoundError(
                    f"Baseline video workflow not found: {self.baseline_workflow_path}"
                )
            with open(baseline_file, "r", encoding="utf-8") as f:
                self._baseline_template = json.load(f)
            logger.info(
                f"[VIDEO-BATCH {self.name}] Loaded baseline template: {self.baseline_workflow_path}"
            )
        except Exception as e:  # noqa: BLE001 — degrade to lightning-only, never hard-fail startup
            self._baseline_template = None
            logger.warning(
                f"[VIDEO-BATCH {self.name}] baseline template load failed ({e}); "
                f"quality_mode='max' items degrade to the lightning graph"
            )

    async def _process_job(self, job: Job) -> None:
        start_time = datetime.utcnow()
        request: VideoBatchJobRequest = job.request

        try:
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.0
            )

            # Step 1: download + stage the source still for RunPod.
            source_name = await self.prepare_source_image(
                job, request.source_image, "vbatch"
            )

            # Step 2: compose prompt + resolve render params.
            prompt = build_catalog_prompt(request.motion_text)
            negative = pc.video_negative(request.negative_prompt)
            width = request.width or VIDEO_DEFAULT_WIDTH
            height = request.height or VIDEO_DEFAULT_HEIGHT
            length = request.length or VIDEO_DEFAULT_LENGTH
            fps = request.fps or VIDEO_DEFAULT_FPS

            # Step 3: pick the template. select_video_template degrades fast->baseline
            # only for NON-explicit items; an explicit item with no lightning template
            # returns (None, "fast") so we surface the misconfiguration loudly rather
            # than silently baselining an NSFW clip.
            template, resolved_mode = select_video_template(
                request.quality_mode,
                request.tier,
                lightning=self._workflow_template,
                baseline=self._baseline_template,
            )
            if template is None:
                raise RuntimeError(
                    "No workflow template resolved for "
                    f"quality_mode={request.quality_mode!r} tier={request.tier!r} "
                    "(lightning graph unavailable for an explicit-tier item)"
                )

            if resolved_mode == "fast":
                workflow = prepare_lightning_video_workflow(
                    template,
                    source_name,
                    prompt=prompt,
                    negative_prompt=negative,
                    seed=request.seed,
                    width=width,
                    height=height,
                    length=length,
                    fps=fps,
                    loras=request.loras,
                    interpolate=request.interpolate,
                )
            else:
                workflow = prepare_video_workflow(
                    template,
                    source_name,
                    prompt=prompt,
                    negative_prompt=negative,
                    seed=request.seed,
                    width=width,
                    height=height,
                    length=length,
                    fps=fps,
                )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.3,
                prompt_used=prompt, seed_used=request.seed,
            )

            # Step 4: submit-only. Defensive payload bound before the /run POST.
            if self.runpod_client is None:
                raise RuntimeError("RunPod client not configured")
            if self._pending_images:
                total_bytes = sum(
                    len(entry.get("image", "")) for entry in self._pending_images
                )
                if total_bytes > MAX_PENDING_IMAGES_BYTES:
                    raise RuntimeError(
                        f"RunPod submission payload too large: {total_bytes} bytes of "
                        f"base64 image data exceeds the {MAX_PENDING_IMAGES_BYTES}-byte limit."
                    )

            runpod_id = await self.runpod_client.submit(
                workflow,
                images=self._pending_images,
                execution_timeout_ms=settings.RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS,
                ttl_ms=settings.RUNPOD_VIDEO_TTL_MS,
            )
            self._pending_images = None

            # Persist the DURABLE handle immediately — this is what makes a deploy
            # recoverable (the reconciler re-polls this runpod_request_id on startup).
            await self.video_batch_store.update_item(
                request.item_id,
                runpod_request_id=runpod_id,
                status="running",
                submitted_at=datetime.now(timezone.utc).isoformat(),
                runpod_status="IN_QUEUE",
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.5
            )
            logger.info(
                f"[VIDEO-BATCH {self.name}] item {request.item_id} SUBMITTED "
                f"runpod={runpod_id} mode={resolved_mode} "
                f"({(datetime.utcnow() - start_time).total_seconds():.1f}s to submit)"
            )

        except Exception as e:  # noqa: BLE001 — a submit failure must not strand the item
            error_msg = str(e)
            logger.error(
                f"[VIDEO-BATCH {self.name}] item {getattr(request, 'item_id', '?')} "
                f"SUBMIT FAILED: {error_msg}"
            )
            traceback.print_exc()
            self._pending_images = None
            await self._handle_submit_failure(request, error_msg)
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.FAILED,
                error_message=error_msg, error_code="VIDEO_BATCH_SUBMIT_ERROR",
            )
        finally:
            self._mark_job_done()

    async def _handle_submit_failure(
        self, request: VideoBatchJobRequest, error_msg: str
    ) -> None:
        """A submit that never reached RunPod: bounded re-enqueue, else mark failed.

        The item is at 'queued' (no runpod_request_id) after a failed submit, which the
        reconciler's normal tick SKIPS (it assumes a worker is mid-submit). So the worker
        must resolve it: reset to 'pending' for a re-enqueue while under the attempt cap
        (attempts was already incremented at enqueue, so this is bounded), else mark it
        failed so it stops looping."""
        try:
            row = await self.video_batch_store.get_item_row(request.item_id)
            attempts = (row or {}).get("attempts") or 0
            if attempts < max(1, int(settings.VIDEO_BATCH_ITEM_MAX_ATTEMPTS)):
                await self.video_batch_store.reset_item_for_retry(request.item_id)
                logger.info(
                    f"[VIDEO-BATCH {self.name}] item {request.item_id} reset to pending "
                    f"after submit failure (attempt {attempts})"
                )
            else:
                await self.video_batch_store.update_item(
                    request.item_id,
                    status="failed",
                    error_code="VIDEO_BATCH_SUBMIT_ERROR",
                    error_message=error_msg[:500],
                )
        except Exception as e:  # noqa: BLE001 — never raise out of the failure handler
            logger.error(
                f"[VIDEO-BATCH {self.name}] failed to record submit failure for "
                f"item {request.item_id}: {e}"
            )
