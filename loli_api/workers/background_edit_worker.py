"""
Background worker for processing background/scene edit jobs.
Mirrors OutfitBackgroundWorker pattern but uses SAM3 background masking.
Uses the same workflow template as outfit editing with overridden SAM3 prompts.
"""
import asyncio
import random
import logging
from datetime import datetime

from services.job_manager import Job
from services.prompt_constants import apply_edit_photo_style
from models.enums import JobStatus, PhotoStyleType

# Import helpers from background endpoint module
from api.v1.endpoints.background import (
    build_background_prompt,
    prepare_background_workflow,
)

from workers.base_worker import BaseEditWorker

logger = logging.getLogger(__name__)


class BackgroundEditWorker(BaseEditWorker):
    """
    Async worker that processes background/scene edit jobs from the queue.

    Workflow:
    1. Get job from background edit queue
    2. Download source image (or use cache)
    3. Upload to ComfyUI
    4. Build background prompt
    5. Execute ComfyUI workflow (outfit template with SAM3 overrides)
    6. Save output image
    7. Update job status
    """

    max_oom_attempts = 2
    oom_retry_delay = 20  # seconds

    @property
    def worker_name(self) -> str:
        return "Background edit"

    async def _get_next_job(self) -> str:
        return await self.job_manager.get_next_background_job()

    def _mark_job_done(self) -> None:
        self.job_manager.mark_background_done()

    async def _process_job(self, job: Job) -> None:
        """Process a single background edit job."""
        start_time = datetime.utcnow()
        request = job.request

        try:
            # Step 1: Mark RUNNING
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.0
            )
            logger.info(
                f"[BACKGROUND] {job.job_id} | Status: RUNNING | User: {job.user_id}"
            )

            # Step 2: Download source image and stage it for the RunPod submission
            source_name = await self.prepare_source_image(
                job, request.source_image, "bg"
            )

            # Step 3: Build prompt
            prompt = apply_edit_photo_style(
                # Trait-aware edit: identityAnchors (skin tone/hair/build) is populated
                # in the endpoint from characterId; keeps skin tone correct where the
                # background edit relights the subject. None leaves the prompt unchanged.
                # WS-T: interiorStyle/colorPalette (populated for a HOME-like location)
                # recompose the scene as her styled room; None -> raw prompt (unchanged).
                build_background_prompt(
                    request.prompt,
                    identity_anchors=getattr(request, "identityAnchors", None),
                    location=getattr(request, "location", None),
                    interior_style=getattr(request, "interiorStyle", None),
                    color_palette=getattr(request, "colorPalette", None),
                ),
                PhotoStyleType.POLISHED,
            )
            seed = (
                request.seed
                if request.seed is not None
                else random.randint(1, 999_999_999)
            )
            logger.info(
                f"[BACKGROUND] {job.job_id} | Prompt: {prompt[:80]}... | Seed: {seed}"
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.3,
                prompt_used=prompt, seed_used=seed,
            )

            # Step 4: Prepare workflow and run on RunPod
            workflow = prepare_background_workflow(
                self._workflow_template,
                source_name,
                prompt,
                seed=seed,
                negative_prompt=request.negativePrompt,
            )

            image_start = datetime.utcnow()
            relative_path, preview_url, expires_at, image_hash = (
                await self.submit_and_save(job, workflow, "background_edits")
            )
            image_duration = (datetime.utcnow() - image_start).total_seconds()
            logger.info(
                f"[BACKGROUND] {job.job_id} | Workflow done in {image_duration:.2f}s"
            )

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.9,
                image_generated_at=datetime.utcnow(),
            )

            # Step 7: Mark SUCCEEDED
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
                f"[BACKGROUND] {job.job_id} | Status: SUCCEEDED | "
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
                    filename=f"background_edit",
                    input_url=request.source_image,
                    image_urls=[preview_url],
                    total_duration=total_duration,
                    user_id=job.user_id,
                    image_duration=image_duration,
                    prompt_used=prompt,
                    seed_used=seed,
                    request_payload=request_payload,
                    timestamps=timestamps,
                )

        except Exception as e:
            await self.handle_job_failure(
                job, str(e), "BACKGROUND_EDIT_ERROR", start_time
            )

        finally:
            self._mark_job_done()
