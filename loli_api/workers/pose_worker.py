"""
Background worker for processing pose edit jobs.
Mirrors OutfitBackgroundWorker pattern but processes PoseEditRequest jobs.
"""
import asyncio
import random
import traceback
import logging
from datetime import datetime

from services.job_manager import Job
from models.enums import JobStatus

from api.v1.endpoints.pose import (
    build_pose_prompt,
    get_pose_reference,
    prepare_pose_workflow,
)

from workers.base_worker import BaseEditWorker

logger = logging.getLogger(__name__)


class PoseBackgroundWorker(BaseEditWorker):
    """
    Async worker that processes pose edit jobs from the queue.

    Workflow:
    1. Get job from pose queue
    2. Download source image (or use cache)
    3. Upload to ComfyUI
    4. Get reference pose image filename
    5. Execute ComfyUI workflow (prompt is hardcoded in workflow)
    6. Save output image
    7. Update job status
    """

    max_oom_attempts = 3
    oom_retry_delay = 1  # seconds

    @property
    def worker_name(self) -> str:
        return "Pose"

    async def _get_next_job(self) -> str:
        return await self.job_manager.get_next_pose_job()

    def _mark_job_done(self) -> None:
        self.job_manager.mark_pose_done()

    async def _process_job(self, job: Job) -> None:
        start_time = datetime.utcnow()
        request = job.request

        try:
            # Step 1: Mark RUNNING
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.0
            )
            logger.info(f"[POSE] {job.job_id} | Status: RUNNING | User: {job.user_id}")

            # Step 2: Download source image and stage it for the RunPod submission
            source_name = await self.prepare_source_image(
                job, request.source_image, "pose"
            )

            # Step 3: Get reference pose image (must exist in the worker's ComfyUI
            # input dir — baked onto the RunPod network volume, see RUNPOD_SETUP.md)
            reference_image = get_pose_reference(request.pose)
            logger.info(f"[POSE] {job.job_id} | Reference image: {reference_image}")

            # Step 4: Prepare seed and prompt
            seed = request.seed if request.seed is not None else random.randint(1, 999_999_999)
            prompt = build_pose_prompt(request.pose)
            logger.info(f"[POSE] {job.job_id} | Pose: {request.pose.value} | Seed: {seed}")
            logger.info(f"[POSE] {job.job_id} | Prompt: {prompt[:80]}...")

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.3,
                prompt_used=prompt, seed_used=seed
            )

            # Step 5: Prepare workflow and run on RunPod
            workflow = prepare_pose_workflow(
                self._workflow_template, source_name, reference_image, prompt=prompt, seed=seed
            )

            image_start = datetime.utcnow()
            relative_path, preview_url, expires_at, image_hash = (
                await self.submit_and_save(job, workflow, "pose_edits")
            )
            image_duration = (datetime.utcnow() - image_start).total_seconds()
            logger.info(f"[POSE] {job.job_id} | Workflow done in {image_duration:.2f}s")

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.9,
                image_generated_at=datetime.utcnow()
            )

            # Step 8: Mark SUCCEEDED
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
                f"[POSE] {job.job_id} | Status: SUCCEEDED | "
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
                    filename=f"pose_edit_{request.pose.value}",
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
            error_msg = str(e)
            total_duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(
                f"[POSE] {job.job_id} | Status: FAILED | "
                f"Error: {error_msg} | Total: {total_duration:.2f}s"
            )
            traceback.print_exc()

            # Pose has an extra error code for missing reference
            error_code = "POSE_EDIT_ERROR"
            if self.is_oom_error(error_msg):
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
            self._mark_job_done()
