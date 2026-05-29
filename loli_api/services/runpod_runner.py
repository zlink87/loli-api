"""
Shared RunPod execution helper used by the workers.

Submits a prepared ComfyUI workflow to the RunPod Serverless endpoint, polls the
job to a terminal state (updating progress on the local Job), and returns the
normalized output image descriptors. This replaces the local ComfyUI WebSocket
execute loop. RunPod owns the GPU, autoscaling, and per-job execution timeout
(via policy.executionTimeout), so the in-process OOM-retry loop is no longer needed.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional

from config import settings
from models.enums import JobStatus
from services.runpod_client import (
    RunPodServerlessClient,
    RunPodError,
    RUNPOD_SUCCESS_STATUS,
    RUNPOD_TERMINAL_STATUSES,
)

logger = logging.getLogger(__name__)


async def run_workflow(
    runpod_client: RunPodServerlessClient,
    job_manager,
    job_id: str,
    workflow: dict,
    images: Optional[List[Dict[str, str]]] = None,
    webhook_url: Optional[str] = None,
    progress_start: float = 0.3,
    progress_end: float = 0.9,
) -> List[Dict[str, Optional[str]]]:
    """
    Submit a workflow to RunPod and wait for completion.

    Returns the normalized output list from ``RunPodServerlessClient.parse_output``.
    Raises RunPodError on submission failure and RuntimeError on terminal job failure
    (FAILED / CANCELLED / TIMED_OUT) or local timeout.
    """
    runpod_id = await runpod_client.submit(
        workflow,
        images=images,
        webhook_url=webhook_url,
        execution_timeout_ms=settings.RUNPOD_EXECUTION_TIMEOUT_MS,
        ttl_ms=settings.RUNPOD_TTL_MS,
    )

    # Record the RunPod id so a webhook/reconciler can map it back to this job.
    if hasattr(job_manager, "set_runpod_id"):
        await job_manager.set_runpod_id(job_id, runpod_id)

    await job_manager.update_job_status(job_id, JobStatus.RUNNING, progress=progress_start)
    logger.info(f"[RUNPOD] {job_id} | submitted as {runpod_id}, polling...")

    poll_interval = max(1, settings.RUNPOD_POLL_INTERVAL_SECONDS)
    # Local safety deadline slightly beyond RunPod's own executionTimeout.
    deadline = time.monotonic() + (settings.RUNPOD_EXECUTION_TIMEOUT_MS / 1000.0) + 60

    while True:
        if time.monotonic() > deadline:
            await runpod_client.cancel(runpod_id)
            raise RuntimeError(f"RunPod job {runpod_id} exceeded local timeout")

        try:
            doc = await runpod_client.status(runpod_id)
        except RunPodError as exc:
            logger.warning(f"[RUNPOD] {job_id} | status poll error: {exc}")
            await asyncio.sleep(poll_interval)
            continue

        st = (doc.get("status") or "").upper()
        if st in RUNPOD_TERMINAL_STATUSES:
            if st == RUNPOD_SUCCESS_STATUS:
                outputs = RunPodServerlessClient.parse_output(doc.get("output"))
                logger.info(f"[RUNPOD] {job_id} | completed with {len(outputs)} image(s)")
                return outputs
            error_msg = RunPodServerlessClient.extract_error(doc)
            raise RuntimeError(f"RunPod job {st}: {error_msg}")

        # Still IN_QUEUE / IN_PROGRESS — nudge progress toward progress_end.
        mid = progress_start + (progress_end - progress_start) * 0.5
        await job_manager.update_job_status(job_id, JobStatus.RUNNING, progress=mid)
        await asyncio.sleep(poll_interval)
