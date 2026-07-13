"""
Job management service with async queue and UUID-indexed tracking.
Based on ManagedQueue pattern from existing app.py.
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, Union
from dataclasses import dataclass, field

from models.enums import JobStatus
from models.requests import GenerateImageRequest, OutfitEditRequest, PoseEditRequest, BackgroundEditRequest, PipelineEditRequest, VideoGenerateRequest


@dataclass
class Job:
    """Internal job representation."""
    job_id: str
    job_type: str  # "text_to_image", "outfit_edit", "pose_edit", "background_edit", or "pipeline_edit"
    status: JobStatus
    request: Union[GenerateImageRequest, OutfitEditRequest, PoseEditRequest, BackgroundEditRequest, PipelineEditRequest, VideoGenerateRequest]
    user_id: str
    created_at: datetime
    updated_at: datetime
    progress: float = 0.0
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    prompt_used: Optional[str] = None
    seed_used: Optional[int] = None
    preview_url: Optional[str] = None
    preview_expires_at: Optional[datetime] = None
    image_hash: Optional[str] = None
    media_type: str = "image"  # "image" or "video" — set on the result item by jobs.py
    # RunPod serverless tracking
    runpod_id: Optional[str] = None
    runpod_status: Optional[str] = None
    submitted_at: Optional[datetime] = None
    # Timestamps for job lifecycle
    prompt_generated_at: Optional[datetime] = None
    image_generated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # WS3.1 observability: free-form per-job debug info, populated live during
    # execution (e.g. PipelineBackgroundWorker._process_job /
    # BatchPipelineWorker._process_job append {"steps": [{"step", "workflow_path",
    # "tier", "seed"}, ...]}). Not persisted independently — batch_orchestrator
    # copies it into character_images.metadata["workflow_meta"] on publish.
    debug_meta: Dict[str, Any] = field(default_factory=dict)


class JobManager:
    """
    Manages job queue and job state tracking.
    Thread-safe using asyncio.Lock for concurrent access.

    Based on ManagedQueue pattern from app.py lines 1855-1901.
    """

    def __init__(self, max_queue_size: int = 100, creation_queue_max_size: Optional[int] = None):
        """
        Initialize job manager.

        Args:
            max_queue_size: Maximum number of jobs in the per-type interactive queues
            creation_queue_max_size: Maximum number of jobs in the dedicated Batch
                Character Creation queue (POST /v1/generate/batch). Defaults to
                max_queue_size when not provided; set generously so realistic admin
                batches fit in one atomic dispatch.
        """
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.outfit_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.pose_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.background_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.pipeline_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        # Dedicated queue for Story Batch items, isolated from interactive /v1/edit.
        self.batch_pipeline_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        # Dedicated queue for admin image-to-video (reel) jobs.
        self.video_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        # Dedicated queue for Batch Character Creation text_to_image jobs, isolated
        # from the interactive single-generate queue (self.queue) so a big batch can't
        # starve interactive traffic. Jobs on it KEEP job_type="text_to_image" (the
        # poll response is identical to single-generate); only the routing differs.
        _creation_max = creation_queue_max_size if creation_queue_max_size is not None else max_queue_size
        self.creation_queue: asyncio.Queue = asyncio.Queue(maxsize=_creation_max)
        self.jobs: Dict[str, Job] = {}
        # Maps RunPod job id -> local job id, so a webhook/reconciler can map back.
        self.runpod_index: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._max_queue_size = max_queue_size
        self._creation_max_queue_size = _creation_max
        # Optional RunPod client, attached at startup, used to cancel in-flight jobs.
        self._runpod_client = None
        # Optional dedicated RunPod client for VIDEO jobs (RUNPOD_VIDEO_ENDPOINT_ID).
        # None -> cancel_job falls back to _runpod_client, same as before this existed.
        self._video_runpod_client = None

    def attach_runpod_client(self, runpod_client) -> None:
        """Attach the RunPod client so cancel_job can stop in-flight RunPod jobs."""
        self._runpod_client = runpod_client

    def attach_video_runpod_client(self, runpod_client) -> None:
        """
        Attach the dedicated video-endpoint RunPod client, so cancel_job can stop
        in-flight VIDEO jobs on the endpoint they were actually submitted to
        (RUNPOD_VIDEO_ENDPOINT_ID) instead of the main one.
        """
        self._video_runpod_client = runpod_client

    async def set_runpod_id(self, job_id: str, runpod_id: str) -> None:
        """Associate a RunPod job id with a local job."""
        async with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job.runpod_id = runpod_id
                job.submitted_at = datetime.utcnow()
                self.runpod_index[runpod_id] = job_id

    async def get_job_by_runpod_id(self, runpod_id: str) -> Optional[Job]:
        """Look up a local job by its RunPod job id (used by the webhook)."""
        async with self._lock:
            job_id = self.runpod_index.get(runpod_id)
            return self.jobs.get(job_id) if job_id else None

    async def create_job(
        self,
        request: Union[GenerateImageRequest, OutfitEditRequest, PoseEditRequest, BackgroundEditRequest, PipelineEditRequest, VideoGenerateRequest],
        user_id: str,
        job_type: str = "text_to_image",
        queue: str = "default"
    ) -> Job:
        """
        Create and queue a new job.

        Args:
            request: The generation or edit request
            user_id: The user who created the job
            job_type: Job type ("text_to_image", "outfit_edit", or "pose_edit")
            queue: Routing override. "default" routes by job_type (unchanged). "creation"
                routes a text_to_image job to the dedicated Batch Character Creation queue
                (creation_queue) while leaving job.job_type == "text_to_image" — so the
                GET /v1/jobs/{jobId} poll response is identical to single-generate.

        Returns:
            Created Job instance

        Raises:
            asyncio.QueueFull: If queue is at capacity
        """
        prefix_map = {"text_to_image": "imgjob", "outfit_edit": "outjob", "pose_edit": "posjob", "background_edit": "bgjob", "pipeline_edit": "pipjob", "batch_pipeline_edit": "batjob", "video_gen": "vidjob"}
        prefix = prefix_map.get(job_type, "job")
        job_id = f"{prefix}_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        # Extract seed from request
        seed = None
        if job_type == "text_to_image" and hasattr(request, 'output') and request.output and request.output.seed:
            seed = request.output.seed
        elif hasattr(request, 'seed') and request.seed:
            seed = request.seed

        job = Job(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            request=request,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            seed_used=seed
        )

        async with self._lock:
            self.jobs[job_id] = job

        # Route to appropriate queue. An explicit `queue` override wins over job_type
        # routing so batch-creation traffic can be isolated on its own queue while the
        # job KEEPS its "text_to_image" job_type.
        if queue == "creation":
            await self.creation_queue.put(job_id)
        elif job_type == "outfit_edit":
            await self.outfit_queue.put(job_id)
        elif job_type == "pose_edit":
            await self.pose_queue.put(job_id)
        elif job_type == "background_edit":
            await self.background_queue.put(job_id)
        elif job_type == "pipeline_edit":
            await self.pipeline_queue.put(job_id)
        elif job_type == "batch_pipeline_edit":
            await self.batch_pipeline_queue.put(job_id)
        elif job_type == "video_gen":
            await self.video_queue.put(job_id)
        else:
            await self.queue.put(job_id)
        return job

    async def get_job(self, job_id: str) -> Optional[Job]:
        """
        Retrieve a job by ID.

        Args:
            job_id: The job identifier

        Returns:
            Job instance or None if not found
        """
        async with self._lock:
            return self.jobs.get(job_id)

    async def get_job_for_user(
        self,
        job_id: str,
        user_id: str
    ) -> Optional[Job]:
        """
        Retrieve a job by ID, ensuring it belongs to the user.

        Args:
            job_id: The job identifier
            user_id: The user ID to verify ownership

        Returns:
            Job instance or None if not found or not owned by user
        """
        job = await self.get_job(job_id)
        if job and job.user_id == user_id:
            return job
        return None

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
        result_path: Optional[str] = None,
        prompt_used: Optional[str] = None,
        seed_used: Optional[int] = None,
        preview_url: Optional[str] = None,
        preview_expires_at: Optional[datetime] = None,
        image_hash: Optional[str] = None,
        media_type: Optional[str] = None,
        prompt_generated_at: Optional[datetime] = None,
        image_generated_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None
    ) -> Optional[Job]:
        """
        Update job status and metadata.

        Args:
            job_id: The job identifier
            status: New job status
            progress: Progress value (0.0 to 1.0)
            error_message: Error message if failed
            error_code: Error code if failed
            result_path: Path to result file
            prompt_used: The generated prompt
            seed_used: The seed value used
            preview_url: Signed preview URL
            preview_expires_at: Preview URL expiration
            image_hash: SHA256 hash of the image
            prompt_generated_at: Timestamp when prompt was generated
            image_generated_at: Timestamp when image was generated
            completed_at: Timestamp when job completed

        Returns:
            Updated Job instance or None if not found
        """
        async with self._lock:
            if job_id not in self.jobs:
                return None

            job = self.jobs[job_id]
            job.status = status
            job.updated_at = datetime.utcnow()

            if progress is not None:
                job.progress = progress
            if error_message is not None:
                job.error_message = error_message
            if error_code is not None:
                job.error_code = error_code
            if result_path is not None:
                job.result_path = result_path
            if prompt_used is not None:
                job.prompt_used = prompt_used
            if seed_used is not None:
                job.seed_used = seed_used
            if preview_url is not None:
                job.preview_url = preview_url
            if preview_expires_at is not None:
                job.preview_expires_at = preview_expires_at
            if image_hash is not None:
                job.image_hash = image_hash
            if media_type is not None:
                job.media_type = media_type
            if prompt_generated_at is not None:
                job.prompt_generated_at = prompt_generated_at
            if image_generated_at is not None:
                job.image_generated_at = image_generated_at
            if completed_at is not None:
                job.completed_at = completed_at

            return job

    async def get_next_job(self) -> Optional[str]:
        """
        Get the next job ID from the character generation queue (blocking).

        Returns:
            Job ID string
        """
        return await self.queue.get()

    async def get_next_outfit_job(self) -> Optional[str]:
        """
        Get the next job ID from the outfit edit queue (blocking).

        Returns:
            Job ID string
        """
        return await self.outfit_queue.get()

    def mark_done(self) -> None:
        """Mark current character generation queue task as done."""
        self.queue.task_done()

    def mark_outfit_done(self) -> None:
        """Mark current outfit queue task as done."""
        self.outfit_queue.task_done()

    async def get_next_pose_job(self) -> Optional[str]:
        """
        Get the next job ID from the pose edit queue (blocking).

        Returns:
            Job ID string
        """
        return await self.pose_queue.get()

    def mark_pose_done(self) -> None:
        """Mark current pose queue task as done."""
        self.pose_queue.task_done()

    async def get_next_background_job(self) -> Optional[str]:
        """
        Get the next job ID from the background edit queue (blocking).

        Returns:
            Job ID string
        """
        return await self.background_queue.get()

    def mark_background_done(self) -> None:
        """Mark current background queue task as done."""
        self.background_queue.task_done()

    async def get_next_pipeline_job(self) -> Optional[str]:
        """
        Get the next job ID from the pipeline edit queue (blocking).

        Returns:
            Job ID string
        """
        return await self.pipeline_queue.get()

    def mark_pipeline_done(self) -> None:
        """Mark current pipeline queue task as done."""
        self.pipeline_queue.task_done()

    async def get_next_batch_pipeline_job(self) -> Optional[str]:
        """Get the next job ID from the dedicated batch pipeline queue (blocking)."""
        return await self.batch_pipeline_queue.get()

    def mark_batch_pipeline_done(self) -> None:
        """Mark current batch pipeline queue task as done."""
        self.batch_pipeline_queue.task_done()

    async def get_next_video_job(self) -> Optional[str]:
        """Get the next job ID from the video (reel) queue (blocking)."""
        return await self.video_queue.get()

    def mark_video_done(self) -> None:
        """Mark current video queue task as done."""
        self.video_queue.task_done()

    async def get_next_creation_job(self) -> Optional[str]:
        """Get the next job ID from the dedicated Batch Character Creation queue (blocking)."""
        return await self.creation_queue.get()

    def mark_creation_done(self) -> None:
        """Mark current Batch Character Creation queue task as done."""
        self.creation_queue.task_done()

    def can_enqueue_creation(self, count: int) -> bool:
        """
        True if `count` more jobs fit on the creation_queue without exceeding its
        maxsize. Atomic pre-check for POST /v1/generate/batch: the whole batch is
        enqueued only when it fits entirely, so a batch never partially enqueues.
        """
        return self.creation_queue.qsize() + count <= self._creation_max_queue_size

    def queue_size(self, job_type: str = "text_to_image") -> int:
        """Get current queue size for the specified job type."""
        if job_type == "outfit_edit":
            return self.outfit_queue.qsize()
        elif job_type == "pose_edit":
            return self.pose_queue.qsize()
        elif job_type == "background_edit":
            return self.background_queue.qsize()
        elif job_type == "pipeline_edit":
            return self.pipeline_queue.qsize()
        elif job_type == "batch_pipeline_edit":
            return self.batch_pipeline_queue.qsize()
        elif job_type == "video_gen":
            return self.video_queue.qsize()
        elif job_type == "creation":
            return self.creation_queue.qsize()
        return self.queue.qsize()

    def is_queue_full(self, job_type: str = "text_to_image") -> bool:
        """Check if queue is at capacity for the specified job type."""
        if job_type == "creation":
            return self.creation_queue.qsize() >= self._creation_max_queue_size
        if job_type == "outfit_edit":
            return self.outfit_queue.qsize() >= self._max_queue_size
        elif job_type == "pose_edit":
            return self.pose_queue.qsize() >= self._max_queue_size
        elif job_type == "background_edit":
            return self.background_queue.qsize() >= self._max_queue_size
        elif job_type == "pipeline_edit":
            return self.pipeline_queue.qsize() >= self._max_queue_size
        elif job_type == "batch_pipeline_edit":
            return self.batch_pipeline_queue.qsize() >= self._max_queue_size
        elif job_type == "video_gen":
            return self.video_queue.qsize() >= self._max_queue_size
        return self.queue.qsize() >= self._max_queue_size

    async def list_jobs(
        self,
        user_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 50
    ) -> list[Job]:
        """
        List jobs with optional filtering.

        Args:
            user_id: Filter by user ID
            status: Filter by job status
            limit: Maximum number of jobs to return

        Returns:
            List of matching jobs
        """
        async with self._lock:
            jobs = list(self.jobs.values())

        # Apply filters
        if user_id:
            jobs = [j for j in jobs if j.user_id == user_id]
        if status:
            jobs = [j for j in jobs if j.status == status]

        # Sort by created_at descending and limit
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """
        Remove completed jobs older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours for completed jobs

        Returns:
            Number of jobs removed
        """
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        removed = 0

        async with self._lock:
            to_remove = [
                job_id for job_id, job in self.jobs.items()
                if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED)
                and job.updated_at < cutoff
            ]
            for job_id in to_remove:
                del self.jobs[job_id]
                removed += 1

        return removed

    async def cancel_job(self, job_id: str, user_id: str) -> bool:
        """
        Cancel a queued or in-flight job.

        Queued jobs are simply marked cancelled. Running jobs that were already
        submitted to RunPod are cancelled on RunPod first (best effort), then marked
        cancelled locally. Succeeded/failed jobs cannot be cancelled.

        Args:
            job_id: The job identifier
            user_id: The user ID to verify ownership

        Returns:
            True if cancelled, False otherwise
        """
        job = await self.get_job_for_user(job_id, user_id)
        if not job:
            return False

        if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            return False  # terminal jobs cannot be cancelled

        # If it's already running on RunPod, ask RunPod to stop it. VIDEO jobs may
        # have been submitted to the dedicated video endpoint (RUNPOD_VIDEO_ENDPOINT_ID)
        # instead of the main one, so pick the client that matches where it landed;
        # fall back to the main client when no dedicated video client is attached.
        is_video_job = isinstance(job.request, VideoGenerateRequest)
        runpod_client = (
            self._video_runpod_client if is_video_job and self._video_runpod_client is not None
            else self._runpod_client
        )
        if job.runpod_id and runpod_client is not None:
            try:
                await runpod_client.cancel(job.runpod_id)
            except Exception:  # noqa: BLE001 - cancellation is best-effort
                pass

        await self.update_job_status(
            job_id,
            JobStatus.FAILED,
            error_message="Job cancelled by user",
            error_code="CANCELLED"
        )
        return True
