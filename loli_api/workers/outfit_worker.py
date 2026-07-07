"""
Background worker for processing outfit edit jobs.
Mirrors BackgroundWorker pattern but processes OutfitEditRequest jobs.
"""
import asyncio
import base64
import random
import logging
import uuid
from datetime import datetime

from services.job_manager import Job
from services import head_mask
from models.enums import JobStatus

# Import helpers from outfit endpoint module
from api.v1.endpoints.outfit import (
    build_prompt,
    prepare_outfit_workflow,
)

from workers.base_worker import BaseEditWorker

logger = logging.getLogger(__name__)


class OutfitBackgroundWorker(BaseEditWorker):
    """
    Async worker that processes outfit edit jobs from the queue.

    Workflow:
    1. Get job from outfit queue
    2. Download source image (or use cache)
    3. Upload to ComfyUI
    4. Build prompt from outfit + accessories
    5. Execute ComfyUI workflow
    6. Save output image
    7. Update job status
    """

    max_oom_attempts = 3
    oom_retry_delay = 1  # seconds

    @property
    def worker_name(self) -> str:
        return "Outfit"

    async def _get_next_job(self) -> str:
        return await self.job_manager.get_next_outfit_job()

    def _mark_job_done(self) -> None:
        self.job_manager.mark_outfit_done()

    async def _process_job(self, job: Job) -> None:
        """
        Process a single outfit edit job.

        Steps:
        1. Update status to RUNNING
        2. Download source image / check cache
        3. Upload to ComfyUI
        4. Build prompt from outfit + accessories
        5. Prepare and execute workflow
        6. Save output image
        7. Update job as succeeded
        """
        start_time = datetime.utcnow()
        request = job.request

        try:
            # Step 1: Mark RUNNING
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.0
            )
            logger.info(f"[OUTFIT] {job.job_id} | Status: RUNNING | User: {job.user_id}")

            # Step 2: Download source image and stage it for the RunPod submission
            source_name = await self.prepare_source_image(
                job, request.source_image, "outfit"
            )

            # Step 2b: server-computed head-protect mask (YuNet — reliable on the
            # stylized hero renders that break on-worker face detection). Shipped
            # as a second input image; the workflow subtracts it from the person
            # mask so the head is never in the edit region.
            head_mask_name = None
            try:
                mask_bytes, face_found = await asyncio.to_thread(
                    head_mask.build_head_mask, self._last_source_bytes
                )
                head_mask_name = f"headmask_{uuid.uuid4().hex[:12]}.png"
                self._pending_images.append({
                    "name": head_mask_name,
                    "image": "data:image/png;base64,"
                             + base64.b64encode(mask_bytes).decode("ascii"),
                })
                logger.info(
                    f"[OUTFIT] {job.job_id} | Head mask staged "
                    f"({'face found' if face_found else 'no face — black mask'})"
                )
            except Exception as e:  # noqa: BLE001 — mask is protective, not critical
                logger.warning(f"[OUTFIT] {job.job_id} | Head mask failed: {e}")

            # Step 3: Build prompt
            prompt = build_prompt(request.outfit, request.accessories, request.nudityLevel)
            seed = request.seed if request.seed is not None else random.randint(1, 999_999_999)
            logger.info(f"[OUTFIT] {job.job_id} | Prompt: {prompt[:80]}... | Seed: {seed}")

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.3,
                prompt_used=prompt, seed_used=seed
            )

            # Step 4: Prepare workflow and run on RunPod
            workflow = prepare_outfit_workflow(
                self._workflow_template, source_name, prompt, seed=seed,
                nudity_level=request.nudityLevel, outfit=request.outfit,
                negative_prompt=request.negativePrompt,
                head_mask_name=head_mask_name,
            )

            image_start = datetime.utcnow()
            relative_path, preview_url, expires_at, image_hash = (
                await self.submit_and_save(job, workflow, "outfit_edits")
            )
            image_duration = (datetime.utcnow() - image_start).total_seconds()
            logger.info(f"[OUTFIT] {job.job_id} | Workflow done in {image_duration:.2f}s")

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.8,
                image_generated_at=datetime.utcnow()
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.9
            )

            # Step 7: Mark SUCCEEDED
            completed_at = datetime.utcnow()
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.SUCCEEDED, progress=1.0,
                result_path=relative_path,
                preview_url=preview_url,
                preview_expires_at=expires_at,
                image_hash=image_hash,
                completed_at=completed_at
            )

            total_duration = (completed_at - start_time).total_seconds()
            logger.info(
                f"[OUTFIT] {job.job_id} | Status: SUCCEEDED | "
                f"Total: {total_duration:.2f}s | Image: {image_duration:.2f}s"
            )

            # Send notification (payload log + completion log)
            if self.notification and preview_url:
                request_payload = request.model_dump(mode="json")

                def format_ts(dt):
                    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else None

                timestamps = {
                    "Job Created": format_ts(job.created_at),
                    "Image Generated": format_ts(datetime.utcnow()),
                    "Job Completed": format_ts(completed_at)
                }

                await self.notification.send_edit_completed(
                    edit_id=job.job_id,
                    filename=f"outfit_edit_{request.outfit.value}",
                    input_url=request.source_image,
                    image_urls=[preview_url],
                    total_duration=total_duration,
                    user_id=job.user_id,
                    image_duration=image_duration,
                    prompt_used=prompt,
                    seed_used=seed,
                    request_payload=request_payload,
                    timestamps=timestamps
                )

        except Exception as e:
            await self.handle_job_failure(
                job, str(e), "OUTFIT_EDIT_ERROR", start_time
            )

        finally:
            self._mark_job_done()
