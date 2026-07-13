"""
Background worker for image-to-video (reel) jobs.

Mirrors PoseBackgroundWorker: download the source still, stage it, run the WAN
2.2 i2v workflow on RunPod, save the mp4, then PERSIST the reel to the character
(a character_images video row + a DRAFT chat_persona_actions row the admin later
publishes). Admin-only; requires the Supabase character-image store.
"""
import asyncio
import base64
import random
import logging
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import json

from config import settings
from services.job_manager import Job, JobManager
from services.comfyui_client import ComfyUIClient
from services.runpod_client import RunPodServerlessClient
from services.storage_service import StorageService
from services.supabase_storage_service import SupabaseStorageService
from services.notification_service import NotificationService
from services.image_cache_service import ImageCacheService
from services.character_image_store import action_keywords
from models.enums import JobStatus
from models.requests import (
    VIDEO_DEFAULT_WIDTH,
    VIDEO_DEFAULT_HEIGHT,
    VIDEO_DEFAULT_LENGTH,
    VIDEO_DEFAULT_FPS,
)
from services import prompt_constants as pc

from api.v1.endpoints.video import (
    build_video_prompt,
    prepare_video_workflow,
    prepare_flf2v_workflow,
    motion_label,
)
from services.end_frame import resolve_end_frame_bytes

from workers.base_worker import BaseEditWorker

logger = logging.getLogger(__name__)


class VideoBackgroundWorker(BaseEditWorker):
    """Async worker that processes image-to-video (reel) jobs from the video queue."""

    max_oom_attempts = 1
    oom_retry_delay = 5  # seconds

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
        character_image_store=None,
        flf2v_workflow_path: str = "",
    ):
        super().__init__(
            job_manager=job_manager,
            comfyui_client=comfyui_client,
            storage_service=storage_service,
            workflow_path=workflow_path,
            image_cache_service=image_cache_service,
            notification_service=notification_service,
            supabase_storage_service=supabase_storage_service,
            runpod_client=runpod_client,
        )
        self.character_image_store = character_image_store
        # OFF by default: empty path -> FLF2V branch is never taken. Loaded once at
        # startup (analogous to base_worker's _workflow_template) so per-job work
        # never touches disk.
        self.flf2v_workflow_path = flf2v_workflow_path
        self._flf2v_template: Optional[dict] = None

    @property
    def worker_name(self) -> str:
        return "Video"

    async def _get_next_job(self) -> str:
        return await self.job_manager.get_next_video_job()

    def _mark_job_done(self) -> None:
        self.job_manager.mark_video_done()

    async def _load_workflow(self) -> None:
        """Load the default i2v template, then the optional FLF2V template.

        A missing/broken FLF2V template must NOT stop the worker: it only disables
        the (opt-in, OFF-by-default) FLF2V branch, leaving the normal i2v path
        untouched. So load it guarded and log a warning on failure.
        """
        await super()._load_workflow()

        if not self.flf2v_workflow_path:
            return
        try:
            flf2v_file = Path(self.flf2v_workflow_path)
            if not flf2v_file.exists():
                raise FileNotFoundError(
                    f"FLF2V workflow not found: {self.flf2v_workflow_path}"
                )
            with open(flf2v_file, "r", encoding="utf-8") as f:
                self._flf2v_template = json.load(f)
            logger.info(f"Loaded FLF2V workflow template: {self.flf2v_workflow_path}")
        except Exception as e:  # noqa: BLE001 - degrade to i2v, never hard-fail startup
            self._flf2v_template = None
            logger.warning(
                f"[VIDEO] FLF2V template load failed ({e}); FLF2V branch disabled, "
                f"reels use the normal i2v path"
            )

    async def _stage_end_frame(self, job: Job) -> str:
        """Build the FLF2V end frame from the just-staged source bytes and stage it.

        Must be called AFTER prepare_source_image (which sets _last_source_bytes and
        seeds _pending_images with the start frame). Appends the end frame as a
        second base64 input.images[] entry (like stage_pose_reference) and returns
        the flat filename the wan_i2v_flf2v.json end-image LoadImage (node 53) reads.
        """
        source_bytes = self._last_source_bytes
        if not source_bytes:
            raise RuntimeError("no staged source bytes to derive the end frame from")

        # Tier 2 deterministic crop-zoom (PIL, CPU-bound) — offload to a thread.
        end_bytes = await asyncio.to_thread(resolve_end_frame_bytes, source_bytes)

        end_name = f"video_end_{uuid.uuid4().hex[:12]}.png"
        b64 = base64.b64encode(end_bytes).decode("ascii")
        if self._pending_images is None:
            self._pending_images = []
        self._pending_images.append(
            {"name": end_name, "image": f"data:image/png;base64,{b64}"}
        )
        logger.info(f"[VIDEO] {job.job_id} | Staged FLF2V end frame: {end_name}")
        return end_name

    async def _process_job(self, job: Job) -> None:
        start_time = datetime.utcnow()
        request = job.request

        try:
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.0
            )
            logger.info(f"[VIDEO] {job.job_id} | Status: RUNNING | User: {job.user_id}")

            # Step 1: Download the source still and stage it for RunPod.
            source_name = await self.prepare_source_image(
                job, request.source_image, "video"
            )

            # Step 2: Build prompt + resolve generation params.
            seed = request.seed if request.seed is not None else random.randint(1, 999_999_999)
            prompt = build_video_prompt(request.motion, request.motionPrompt)
            negative = pc.video_negative(request.negativePrompt)
            length = request.length or VIDEO_DEFAULT_LENGTH
            fps = request.fps or VIDEO_DEFAULT_FPS
            logger.info(
                f"[VIDEO] {job.job_id} | Motion: {request.motion.value} | "
                f"Seed: {seed} | Length: {length} @ {fps}fps"
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.3,
                prompt_used=prompt, seed_used=seed,
            )

            # Step 3: Prepare workflow and run on RunPod (longer video timeouts).
            # FLF2V branch is opt-in (request.useFlf2v) AND requires the FLF2V
            # template to have loaded (empty config path -> _flf2v_template is None
            # -> branch never taken). Any end-frame failure degrades to the normal
            # i2v path — it must never hard-fail the job.
            width = request.width or VIDEO_DEFAULT_WIDTH
            height = request.height or VIDEO_DEFAULT_HEIGHT
            use_flf2v = bool(getattr(request, "useFlf2v", False)) and (
                self._flf2v_template is not None
            )
            workflow = None
            if use_flf2v:
                try:
                    end_name = await self._stage_end_frame(job)
                    workflow = prepare_flf2v_workflow(
                        self._flf2v_template,
                        source_name,
                        end_name,
                        prompt=prompt,
                        negative_prompt=negative,
                        seed=seed,
                        width=width,
                        height=height,
                        length=length,
                        fps=fps,
                    )
                    logger.info(f"[VIDEO] {job.job_id} | Using FLF2V path")
                except Exception as flf_err:  # noqa: BLE001 - degrade to i2v
                    logger.warning(
                        f"[VIDEO] {job.job_id} | FLF2V end-frame prep failed "
                        f"({flf_err}); falling back to i2v"
                    )
                    workflow = None

            if workflow is None:
                workflow = prepare_video_workflow(
                    self._workflow_template,
                    source_name,
                    prompt=prompt,
                    negative_prompt=negative,
                    seed=seed,
                    width=width,
                    height=height,
                    length=length,
                    fps=fps,
                )

            gen_start = datetime.utcnow()
            relative_path, preview_url, expires_at, video_hash, media_type = (
                await self._submit_and_save_media(
                    job, workflow, "character_videos",
                    execution_timeout_ms=settings.RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS,
                    ttl_ms=settings.RUNPOD_VIDEO_TTL_MS,
                )
            )
            gen_duration = (datetime.utcnow() - gen_start).total_seconds()
            logger.info(f"[VIDEO] {job.job_id} | Clip generated in {gen_duration:.2f}s")

            # Step 4: Persist the reel to the character (gallery row + DRAFT action).
            # A persistence failure must NOT be reported as a clean SUCCEEDED: the
            # clip would silently vanish from the admin review queue (which reads
            # the character_images / chat_persona_actions rows, not the job). Mark
            # the job FAILED with a distinct code, but keep the preview_url/hash on
            # the record so the generated clip is still recoverable manually.
            try:
                await self._persist_reel(job, request, preview_url, seed, prompt, video_hash)
            except Exception as persist_err:  # noqa: BLE001 - surface, don't swallow
                logger.error(
                    f"[VIDEO] {job.job_id} | Reel persistence failed: {persist_err}"
                )
                traceback.print_exc()
                await self.job_manager.update_job_status(
                    job.job_id, JobStatus.FAILED,
                    error_message=f"Clip generated but persistence failed: {persist_err}",
                    error_code="REEL_PERSIST_ERROR",
                    result_path=relative_path,
                    preview_url=preview_url,
                    preview_expires_at=expires_at,
                    image_hash=video_hash,
                    media_type=media_type,
                )
                return

            completed_at = datetime.utcnow()
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.SUCCEEDED, progress=1.0,
                result_path=relative_path,
                preview_url=preview_url,
                preview_expires_at=expires_at,
                image_hash=video_hash,
                media_type=media_type,
                completed_at=completed_at,
            )

            total_duration = (completed_at - start_time).total_seconds()
            logger.info(
                f"[VIDEO] {job.job_id} | Status: SUCCEEDED | "
                f"Total: {total_duration:.2f}s | Clip: {gen_duration:.2f}s"
            )

            if self.notification and preview_url:
                try:
                    await self.notification.send_edit_completed(
                        edit_id=job.job_id,
                        filename=f"reel_{request.motion.value}",
                        input_url=request.source_image,
                        image_urls=[preview_url],
                        total_duration=total_duration,
                        user_id=job.user_id,
                        image_duration=gen_duration,
                        prompt_used=prompt,
                        seed_used=seed,
                        request_payload=request.model_dump(mode="json"),
                        timestamps={},
                    )
                except Exception:  # noqa: BLE001 - notification is best-effort
                    pass

        except Exception as e:
            await self.handle_job_failure(job, str(e), "VIDEO_GEN_ERROR", start_time)

        finally:
            self._mark_job_done()

    async def _persist_reel(
        self, job: Job, request, video_url: str, seed: int, prompt: str, video_hash
    ) -> None:
        """Write the character_images video row + its DRAFT chat quick action."""
        if not self.character_image_store or not request.character_id:
            logger.warning(
                f"[VIDEO] {job.job_id} | No character store / character_id — "
                f"skipping persistence (clip still returned via job poll)"
            )
            return
        # NOTE: this intentionally does NOT swallow exceptions. The caller
        # (_process_job) catches a persistence failure and marks the job FAILED
        # with REEL_PERSIST_ERROR (keeping the preview_url) rather than reporting
        # a SUCCEEDED job whose clip never reached the review queue.
        image_id = await self.character_image_store.create_image(
            request.character_id,
            image_url=video_url,
            original_image_url=request.source_image,
            prompt=prompt,
            seed=seed,
            image_type="video",
            source_image_id=request.source_image_id,
            metadata={
                "media_type": "video",
                "motion": request.motion.value,
                "job_id": job.job_id,
                "video_hash": video_hash,
            },
        )
        label = request.motionLabel or motion_label(request.motion)

        # Best-effort keyword enrichment off the source still's scene. Must NEVER
        # raise: this runs after create_image already succeeded, and an exception
        # here would bubble up to _process_job's persistence try/except and mark an
        # otherwise-fine reel FAILED (REEL_PERSIST_ERROR) over a missing keyword.
        source_scene = None
        try:
            source_image = await self.character_image_store.get_image(request.source_image_id)
            if source_image:
                source_scene = (source_image.get("metadata") or {}).get("scene_spec")
        except Exception as e:  # noqa: BLE001 - keywords are best-effort, never a gate
            logger.warning(
                f"[VIDEO] {job.job_id} | source scene lookup for keywords failed: {e}"
            )
            source_scene = None

        await self.character_image_store.create_action(
            request.character_id,
            character_image_id=image_id,
            media_url=video_url,
            label=label,
            media_type="video",
            is_active=False,  # DRAFT — admin publishes after review
            trigger_keywords=action_keywords(source_scene, extra_texts=[label, request.motion.value]),
        )
        logger.info(
            f"[VIDEO] {job.job_id} | Persisted reel -> character_images {image_id} "
            f"(+ draft action) for character {request.character_id}"
        )
