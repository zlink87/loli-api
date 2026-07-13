"""
BatchPipelineWorker — a dedicated worker for Story Batch items, isolated from the
interactive /v1/edit pipeline queue so a large batch never starves single edits.

It reuses the existing PipelineBackgroundWorker as a stateless "engine" for step
execution (download -> pose -> outfit -> background chaining on RunPod) via its
_determine_active_steps / _run_step methods, but drains job_manager.batch_pipeline_queue
and writes outputs to the `batch_edits/` folder. Run M of these for M-way parallelism
(keep RunPod max_workers >= M).
"""
import asyncio
import logging
import traceback
from datetime import datetime
from typing import Optional

from config import settings
from models.enums import JobStatus
from services.job_manager import JobManager, Job
from services.workflow_meta import TIER_V1
from workers.pipeline_worker import PipelineBackgroundWorker, _download_image

logger = logging.getLogger(__name__)

STORAGE_FOLDER = "batch_edits"


def _is_oom(msg: str) -> bool:
    m = (msg or "").lower()
    return "out of memory" in m or "outofmemoryerror" in m


def _check_cropstitch_outfit_required(outfit_meta: Optional[dict], require: bool) -> None:
    """
    WS3.2 startup guard: raise if ``BATCH_REQUIRE_CROPSTITCH_OUTFIT`` is set but the
    batch engine's RESOLVED outfit template (``PipelineBackgroundWorker.workflow_meta
    ["outfit"]``, populated by ``_load_workflows()`` -> ``workflow_meta.describe_
    template``) is tier "v1" (the legacy whole-frame graph) rather than a
    crop-and-stitch tier (rapid_cropstitch / 2511full).

    Exists so a mis-deployed environment (e.g. a CI-built image missing the
    gitignored ``.env``, so ``COMFYUI_OUTFIT_WORKFLOW_PATH_2511``/``_V2``/
    ``COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH`` all read empty and the tier-precedence
    chain silently lands on V1) fails LOUD at boot instead of silently shipping
    degraded batch outfit quality — see Phase 0 diagnostics in the quality/realism
    plan. Factored out of ``start()`` so the tier comparison is unit-testable with a
    plain dict, no live engine required.

    Args:
        outfit_meta: ``engine.workflow_meta.get("outfit")`` — a
            ``{"path": ..., "tier": ..., "sampler": {...}}`` dict, or None if the
            engine hasn't loaded its templates yet.
        require: ``settings.BATCH_REQUIRE_CROPSTITCH_OUTFIT``.

    Raises:
        RuntimeError: naming the resolved path, when ``require`` is True and the
            resolved tier is "v1".
    """
    if not require:
        return
    tier = (outfit_meta or {}).get("tier")
    if tier == TIER_V1:
        path = (outfit_meta or {}).get("path", "<unknown — workflow_meta not populated>")
        raise RuntimeError(
            "BATCH_REQUIRE_CROPSTITCH_OUTFIT=true but the batch engine's resolved "
            f"outfit workflow is tier 'v1' (legacy whole-frame, not crop-and-stitch): "
            f"{path}. This usually means COMFYUI_OUTFIT_WORKFLOW_PATH_2511 / _V2 / "
            "COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH all resolved empty in this environment "
            "(e.g. a CI-built image without the gitignored .env). Fix the deployment "
            "env, or set BATCH_REQUIRE_CROPSTITCH_OUTFIT=false to explicitly allow V1."
        )


class BatchPipelineWorker:
    def __init__(
        self,
        job_manager: JobManager,
        engine: PipelineBackgroundWorker,
        storage_service,
        supabase_storage_service=None,
        notification_service=None,
        name: str = "batch-0",
    ):
        self.job_manager = job_manager
        self.engine = engine
        self.storage = storage_service
        self.supabase_storage = supabase_storage_service
        self.notification = notification_service
        self.name = name
        self._running = False
        self._task = None

    async def start(self) -> None:
        self._running = True
        # Ensure the engine's workflow templates are loaded (without starting its loop).
        # Multiple BatchPipelineWorker instances share ONE engine (main.py), so only
        # the first call actually loads; workflow_meta is populated either way by the
        # time we reach the guard below.
        if self.engine._pose_template is None or self.engine._outfit_template is None:
            await self.engine._load_workflows()
        # WS3.2: fail loud at startup instead of silently degrading to V1 — see
        # _check_cropstitch_outfit_required's docstring.
        _check_cropstitch_outfit_required(
            self.engine.workflow_meta.get("outfit"), settings.BATCH_REQUIRE_CROPSTITCH_OUTFIT
        )
        self._task = asyncio.create_task(self._worker_loop())
        logger.info(f"Batch pipeline worker '{self.name}' started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Batch pipeline worker '{self.name}' stopped")

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                job_id = await self.job_manager.get_next_batch_pipeline_job()
                job = await self.job_manager.get_job(job_id)
                if not job:
                    self.job_manager.mark_batch_pipeline_done()
                    continue
                if job.status == JobStatus.FAILED:  # cancelled before pickup
                    self.job_manager.mark_batch_pipeline_done()
                    continue
                await self._process_job(job)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.error(f"[BATCH-WORKER {self.name}] loop error: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    async def _process_job(self, job: Job) -> None:
        start_time = datetime.utcnow()
        request = job.request
        try:
            await self.job_manager.update_job_status(job.job_id, JobStatus.RUNNING, progress=0.0)

            current_bytes = await asyncio.to_thread(_download_image, request.source_image)
            await self.job_manager.update_job_status(job.job_id, JobStatus.RUNNING, progress=0.1)

            active_steps = self.engine._determine_active_steps(request)
            seed = request.seed if request.seed is not None else None
            if seed is None:
                import random
                seed = random.randint(1, 999_999_999)
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.15, seed_used=seed
            )

            num_steps = len(active_steps) or 1
            per_step = 0.70 / num_steps
            for i, step_name in enumerate(active_steps):
                p_start = 0.15 + i * per_step
                p_end = 0.15 + (i + 1) * per_step
                current_bytes, step_prompts = await self.engine._run_step(
                    step_name, request, current_bytes, seed, job.job_id,
                    progress_start=p_start, progress_end=p_end,
                    is_final_step=(i == num_steps - 1),
                )

                # WS3.1 observability: same per-step debug_meta shape as
                # PipelineBackgroundWorker._process_job, sourced from the shared
                # engine's workflow_meta (this worker only drives step execution
                # via self.engine._run_step; it has no template state of its own).
                # Phase 5: step_prompts (returned by _run_step, a pure local value —
                # safe even though the engine is shared across concurrent batch
                # workers) carries the EXACT composed positive/negative prompt text.
                step_meta = self.engine.workflow_meta.get(step_name, {})
                job.debug_meta.setdefault("steps", []).append({
                    "step": step_name,
                    "workflow_path": step_meta.get("path"),
                    "tier": step_meta.get("tier"),
                    "seed": seed,
                    "positive_prompt": step_prompts.get("positive"),
                    "negative_prompt": step_prompts.get("negative"),
                })

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.85, image_generated_at=datetime.utcnow()
            )

            # Save final output to the batch_edits folder.
            if self.supabase_storage:
                preview_url, image_hash = await asyncio.to_thread(
                    self.supabase_storage.upload_image,
                    image=current_bytes,
                    image_id=job.job_id,
                    folder=STORAGE_FOLDER,
                )
                expires_at = None
                relative_path = f"{STORAGE_FOLDER}/{job.job_id}.png"
            else:
                relative_path, image_hash = self.storage.save_image(current_bytes, job.job_id)
                preview_url, expires_at = self.storage.generate_signed_url(relative_path)

            completed_at = datetime.utcnow()
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.SUCCEEDED, progress=1.0,
                result_path=relative_path, preview_url=preview_url,
                preview_expires_at=expires_at, image_hash=image_hash, completed_at=completed_at,
            )
            logger.info(
                f"[BATCH-WORKER {self.name}] {job.job_id} SUCCEEDED steps={active_steps} "
                f"in {(completed_at - start_time).total_seconds():.1f}s"
            )
        except Exception as e:  # noqa: BLE001
            error_msg = str(e)
            error_code = "BATCH_EDIT_ERROR"
            if _is_oom(error_msg):
                error_code = "GPU_OOM_ERROR"
            elif "download" in error_msg.lower():
                error_code = "DOWNLOAD_ERROR"
            elif "No image" in error_msg:
                error_code = "NO_OUTPUT_ERROR"
            logger.error(f"[BATCH-WORKER {self.name}] {job.job_id} FAILED: {error_msg}")
            traceback.print_exc()
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.FAILED, error_message=error_msg, error_code=error_code
            )
        finally:
            self.job_manager.mark_batch_pipeline_done()
