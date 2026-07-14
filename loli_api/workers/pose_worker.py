"""
Background worker for processing pose edit jobs.
Mirrors OutfitBackgroundWorker pattern but processes PoseEditRequest jobs.
"""
import asyncio
import random
import traceback
import logging
from datetime import datetime
from typing import Optional, Tuple

from config import settings
from services.job_manager import Job
from services.prompt_constants import apply_edit_photo_style
from models.enums import JobStatus, PhotoStyleType

from api.v1.endpoints.pose import (
    build_pose_prompt,
    prepare_pose_workflow,
    pose_template_has_face_ref_conditioning,
    _natural_lora_scales,
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

    def _build_edit_workflow(
        self,
        request,
        source_name: str,
        reference_image: str,
        seed: int,
        face_ref_name: Optional[str] = None,
    ) -> Tuple[str, dict]:
        """
        Build the ``(prompt, workflow)`` for a standalone pose edit — the interactive-path
        twin of ``pipeline_worker._build_step_workflow``'s pose branch. Threads the SAME
        settings-driven render-quality knobs so an interactive ``/v1/edit/pose`` renders at
        batch parity:

          * ReActor node-200 tuning — ``face_restore_visibility`` / ``codeformer_weight``
            from ``settings.POSE_REACTOR_*`` (the -1.0 sentinel = leave the graph's baked
            value untouched), plus the optional sharper
            ``settings.POSE_REACTOR_FACE_RESTORE_MODEL``;
          * output canvas size — node 93 megapixels from ``settings.POSE_OUTPUT_MEGAPIXELS``
            (0.0 = keep the template's baked size);
          * natural/candid LoRA scaling — nodes 304/305/306 dialed down via
            ``_natural_lora_scales(request.photoStyle)``. PoseEditRequest carries no
            photoStyle, so this is None (baked strengths) today, but stays parity-correct if
            the request ever gains one;
          * the live 2511 negative (``negativePrompt``) — inert on the v1 cfg-1 graph.

        ``face_ref_conditioning`` gates on BOTH the loaded template exposing the image3
        encoder input (the faceref graph) AND a dedicated hero donor actually being staged
        (``face_ref_name``). The interactive pose path stages no dedicated donor — a
        PoseEditRequest carries no hero image and the endpoint resolves only identityAnchors
        (text), not a face URL — so ``face_ref_name`` is None here and the "render that same
        face" clause stays absent even on the faceref graph (node 210 there falls back to the
        source for the ReActor stamp only). Kept as a parameter so the guard reads identically
        to the pipeline's and is directly unit-testable.

        Pure/synchronous and side-effect-free (no I/O), so it is unit-testable without the
        full RunPod round-trip.
        """
        face_ref_conditioning = (
            pose_template_has_face_ref_conditioning(self._workflow_template)
            and face_ref_name is not None
        )
        prompt = apply_edit_photo_style(
            # Trait-aware edit: identityAnchors (skin tone/hair/build) is populated in the
            # endpoint from characterId. The pose step fully re-diffuses the frame, so this
            # anchor keeps the character's real skin tone. None (no character) leaves the
            # prompt unchanged.
            build_pose_prompt(
                request.pose,
                identity_anchors=getattr(request, "identityAnchors", None),
                face_ref_conditioning=face_ref_conditioning,
            ),
            PhotoStyleType.POLISHED,
        )
        # D3: negativePrompt goes LIVE only on the Tier-A 2511 pose graph
        # (prepare_pose_workflow gates the injection on the template marker); on the v1 cfg-1
        # graph it stays inert, matching PoseEditRequest.negativePrompt's documented "IGNORED
        # on v1" contract. PoseEditRequest carries no nudity level, so the negative uses
        # edit_negative's 'low' default.
        workflow = prepare_pose_workflow(
            self._workflow_template, source_name, reference_image, prompt=prompt, seed=seed,
            negative_prompt=getattr(request, "negativePrompt", None),
            # ReActor node-200 knobs from the server-wide settings (batch parity). The -1.0
            # sentinel default on both means "leave the graph's baked 0.65/0.7 alone".
            reactor_restore_visibility=settings.POSE_REACTOR_RESTORE_VISIBILITY,
            reactor_codeformer_weight=settings.POSE_REACTOR_CODEFORMER_WEIGHT,
            # Dark asset (ships OFF): sharper face-restore model for node 200. Empty setting
            # -> None -> prepare_pose_workflow no-ops (baked CodeFormer kept).
            face_restore_model=settings.POSE_REACTOR_FACE_RESTORE_MODEL or None,
            # Output canvas size (node 93). 0.0 (default) -> None -> baked size kept.
            output_megapixels=(
                settings.POSE_OUTPUT_MEGAPIXELS
                if settings.POSE_OUTPUT_MEGAPIXELS > 0
                else None
            ),
            # Natural/candid LoRA scaling (nodes 304/305/306). None for POLISHED / no style.
            lora_scales=_natural_lora_scales(getattr(request, "photoStyle", None)),
            # Dedicated ReActor face donor (node 210). None on the interactive path -> node
            # 210 falls back to the source image (donor == source), unchanged behavior.
            face_ref_image=face_ref_name,
        )
        return prompt, workflow

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

            # Step 3: Stage the pose reference image. Its PNG bytes ship with the
            # RunPod submission as a second base64 input.images[] entry (no
            # network-volume dependency); the returned flat filename is what the
            # workflow's LoadImage node (170) references.
            reference_image = await self.stage_pose_reference(request.pose)
            logger.info(f"[POSE] {job.job_id} | Reference image: {reference_image}")

            # Step 4/5: Prepare seed, prompt, and workflow with the SAME batch-parity
            # render-quality knobs (ReActor node-200 tuning, sharper face-restore model,
            # output resolution, natural/candid LoRA scaling, live 2511 negative — see
            # _build_edit_workflow). The interactive pose path stages no dedicated hero donor
            # (PoseEditRequest carries no faceRefImage), so face_ref_name is None -> node 210
            # falls back to the source and the faceref "render that same face" clause stays
            # absent even if prod points this worker at the faceref graph.
            seed = request.seed if request.seed is not None else random.randint(1, 999_999_999)
            prompt, workflow = self._build_edit_workflow(
                request, source_name, reference_image, seed, face_ref_name=None,
            )
            logger.info(f"[POSE] {job.job_id} | Pose: {request.pose.value} | Seed: {seed}")
            logger.info(f"[POSE] {job.job_id} | Prompt: {prompt[:80]}...")

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.3,
                prompt_used=prompt, seed_used=seed
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
