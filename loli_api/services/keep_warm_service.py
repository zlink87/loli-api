"""
Optional keep-warm pinger for the RunPod Serverless endpoint.

Purpose: during an active session, keep one RunPod worker from scaling to zero so
real requests don't pay a multi-minute cold start. It submits a lightweight
warm-up job every ``interval_seconds``, but ONLY while the last REAL job was
within ``window_minutes`` — so it costs nothing when the system is truly idle.

This is a COMPLEMENT to (not a replacement for) the RunPod dashboard settings
(raise the idle timeout, enable FlashBoot), which are the primary, free
cold-start mitigation. OFF by default (``settings.WARMUP_ENABLED``).

Note: a RunPod ``/health`` probe does NOT hold a worker warm — only a real
``/run`` job occupies a worker, which is why this submits an actual (throwaway)
workflow. Point ``WARMUP_WORKFLOW_PATH`` at a minimal 1-step / tiny-resolution
graph to keep each ping cheap; it falls back to the generation workflow.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class KeepWarmService:
    """Submits warm-up jobs to hold a RunPod worker warm during active sessions."""

    def __init__(
        self,
        runpod_client,
        *,
        enabled: bool,
        interval_seconds: int,
        window_minutes: int,
        workflow_path: str,
    ):
        self.client = runpod_client
        self.enabled = enabled
        # Floor the cadence so a misconfiguration can't hammer the endpoint.
        self.interval_seconds = max(30, interval_seconds)
        self.window = timedelta(minutes=window_minutes)
        self.workflow_path = workflow_path
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._workflow: Optional[dict] = None

    def _load_workflow(self) -> Optional[dict]:
        """Load + cache the warm-up workflow template. Returns None on failure."""
        if self._workflow is not None:
            return self._workflow
        try:
            path = Path(self.workflow_path)
            if not path.exists():
                logger.error(f"[KEEP-WARM] warm-up workflow not found: {self.workflow_path}")
                return None
            with open(path, "r", encoding="utf-8") as f:
                self._workflow = json.load(f)
            return self._workflow
        except Exception as e:  # noqa: BLE001
            logger.error(f"[KEEP-WARM] failed to load warm-up workflow: {e}")
            return None

    async def start(self) -> None:
        if not self.enabled:
            logger.info("[KEEP-WARM] disabled (WARMUP_ENABLED=false)")
            return
        if not self.client.is_configured():
            logger.warning("[KEEP-WARM] RunPod client not configured; not started")
            return
        if self._load_workflow() is None:
            logger.warning("[KEEP-WARM] no warm-up workflow available; not started")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"[KEEP-WARM] started: ping every {self.interval_seconds}s while a session "
            f"is active (window {self.window}, workflow {self.workflow_path})"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[KEEP-WARM] stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                await self._maybe_ping()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                logger.error(f"[KEEP-WARM] loop error: {e}", exc_info=True)

    async def _maybe_ping(self) -> None:
        """Submit one warm-up job iff a real job ran within the warm window."""
        last = self.client.last_activity
        if last is None:
            return  # no real traffic yet — nothing to keep warm
        if datetime.utcnow() - last > self.window:
            return  # session idle past the window — let the worker scale to zero
        wf = self._load_workflow()
        if wf is None:
            return
        try:
            # track_activity=False so warm-up jobs don't perpetuate the window.
            runpod_id = await self.client.submit(wf, track_activity=False)
            logger.info(f"[KEEP-WARM] warm-up job submitted ({runpod_id})")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[KEEP-WARM] warm-up submit failed: {e}")
