"""
RunPod Serverless client.

Replaces the network role of the local ComfyUI WebSocket client. The app still
builds the ComfyUI workflow graph (see ``comfyui_client.prepare_*``); this client
only handles transport: submitting the workflow to a RunPod Serverless endpoint
running ``runpod-workers/worker-comfyui``, polling status, and cancelling.

RunPod Serverless REST API (https://docs.runpod.io/serverless/endpoints/send-requests):
    POST   {base}/v2/{endpoint_id}/run         -> {"id": ..., "status": "IN_QUEUE"}
    GET    {base}/v2/{endpoint_id}/status/{id}  -> {"status": ..., "output": ...}
    POST   {base}/v2/{endpoint_id}/cancel/{id}
    GET    {base}/v2/{endpoint_id}/health

worker-comfyui input/output contract:
    input  = {"workflow": <ComfyUI API-format graph>,
              "images": [{"name": "src.png", "image": "<base64>"}]}
    output = {"images": [{"filename": ..., "type": "base64"|"s3_url", "data": ...}]}
              (when the worker is configured with S3, ``type`` is "s3_url" and the
               URL lives in ``data``; we also accept a ``url`` field defensively)
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# RunPod job statuses
RUNPOD_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
RUNPOD_SUCCESS_STATUS = "COMPLETED"


class RunPodError(RuntimeError):
    """Raised when a RunPod API call fails."""


class RunPodServerlessClient:
    """Async client for a single RunPod Serverless ComfyUI endpoint."""

    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        base_url: str = "https://api.runpod.ai/v2",
        default_execution_timeout_ms: int = 600_000,
        default_ttl_ms: int = 3_600_000,
        request_timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.base_url = base_url.rstrip("/")
        self.default_execution_timeout_ms = default_execution_timeout_ms
        self.default_ttl_ms = default_ttl_ms
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=request_timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        # Timestamp of the last REAL (non-warm-up) job submission. Read by the
        # optional keep-warm service to decide whether a session is still active.
        self.last_activity: Optional[datetime] = None

    @property
    def _endpoint_url(self) -> str:
        return f"{self.base_url}/{self.endpoint_id}"

    def is_configured(self) -> bool:
        return bool(self.api_key and self.endpoint_id)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, json_body: Optional[dict] = None) -> dict:
        """Issue a request with retries on 429/5xx and transient network errors."""
        url = f"{self._endpoint_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await self._client.request(method, url, json=json_body)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise RunPodError(f"RunPod {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
                if not resp.content:
                    return {}
                return resp.json()
            except (httpx.HTTPError, RunPodError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    backoff = min(2 ** attempt, 8)
                    logger.warning(
                        f"RunPod {method} {path} attempt {attempt}/{self.max_retries} failed: {exc}; "
                        f"retrying in {backoff}s"
                    )
                    await asyncio.sleep(backoff)
        raise RunPodError(f"RunPod {method} {path} failed after {self.max_retries} attempts: {last_exc}")

    async def submit(
        self,
        workflow: dict,
        images: Optional[List[Dict[str, str]]] = None,
        webhook_url: Optional[str] = None,
        execution_timeout_ms: Optional[int] = None,
        ttl_ms: Optional[int] = None,
        extra_input: Optional[dict] = None,
        track_activity: bool = True,
    ) -> str:
        """
        Submit a workflow to the endpoint (async /run). Returns the RunPod job id.

        Args:
            workflow: ComfyUI API-format graph (the prepared dict).
            images: Optional list of {"name", "image"(base64)} for input images.
            webhook_url: Optional URL RunPod POSTs the final job document to.
            execution_timeout_ms: Per-job active-runtime cap (policy.executionTimeout).
            ttl_ms: Total job lifespan from submission (policy.ttl).
            extra_input: Extra keys to merge into ``input`` (e.g. comfy_org_api_key).
            track_activity: When True (default) record this as real activity for the
                keep-warm service. The keep-warm pinger passes False so its own
                warm-up jobs don't perpetuate the warm window forever.
        """
        if not self.is_configured():
            raise RunPodError("RunPod client is not configured (missing API key or endpoint id)")

        if track_activity:
            self.last_activity = datetime.utcnow()

        job_input: Dict[str, Any] = {"workflow": workflow}
        if images:
            job_input["images"] = images
        if extra_input:
            job_input.update(extra_input)

        body: Dict[str, Any] = {
            "input": job_input,
            "policy": {
                "executionTimeout": execution_timeout_ms or self.default_execution_timeout_ms,
                "ttl": ttl_ms or self.default_ttl_ms,
            },
        }
        if webhook_url:
            body["webhook"] = webhook_url

        result = await self._request("POST", "/run", body)
        runpod_id = result.get("id")
        if not runpod_id:
            raise RunPodError(f"RunPod /run returned no job id: {result}")
        logger.info(f"Submitted RunPod job {runpod_id} (status={result.get('status')})")
        return runpod_id

    async def status(self, runpod_id: str) -> dict:
        """GET /status/{id}. Returns the raw job document (status, output, error...)."""
        return await self._request("GET", f"/status/{runpod_id}")

    async def run_and_wait(
        self,
        workflow: dict,
        images: Optional[List[Dict[str, str]]] = None,
        execution_timeout_ms: Optional[int] = None,
        ttl_ms: Optional[int] = None,
        poll_interval_seconds: float = 3.0,
        max_wait_seconds: float = 300.0,
    ) -> dict:
        """
        Submit a workflow and poll until terminal (async — does NOT block the event
        loop). Returns the terminal job document on COMPLETED; raises RunPodError
        otherwise. Used by the synchronous /v1/edit/image endpoint.
        """
        runpod_id = await self.submit(
            workflow,
            images=images,
            execution_timeout_ms=execution_timeout_ms,
            ttl_ms=ttl_ms,
        )
        waited = 0.0
        while waited <= max_wait_seconds:
            doc = await self.status(runpod_id)
            st = (doc.get("status") or "").upper()
            if st in RUNPOD_TERMINAL_STATUSES:
                if st == RUNPOD_SUCCESS_STATUS:
                    return doc
                raise RunPodError(f"RunPod job {st}: {self.extract_error(doc)}")
            await asyncio.sleep(poll_interval_seconds)
            waited += poll_interval_seconds
        await self.cancel(runpod_id)
        raise RunPodError(f"RunPod job {runpod_id} timed out after {max_wait_seconds}s")

    async def cancel(self, runpod_id: str) -> bool:
        """POST /cancel/{id}. Returns True if the cancel request was accepted."""
        try:
            await self._request("POST", f"/cancel/{runpod_id}")
            return True
        except RunPodError as exc:
            logger.warning(f"RunPod cancel {runpod_id} failed: {exc}")
            return False

    async def health(self) -> dict:
        """GET /health. Endpoint worker/queue status."""
        return await self._request("GET", "/health")

    # Filename extensions we treat on the raw-bytes (non-PIL) path.
    _VIDEO_EXT_CONTENT_TYPE = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
        "gif": "image/gif",  # animated; stored/served raw, not re-encoded
    }

    @staticmethod
    def parse_output(output: Optional[dict]) -> List[Dict[str, Optional[str]]]:
        """
        Normalize worker-comfyui output into a list of media descriptors:
            [{"filename", "type", "url"|None, "data"|None, "kind", "content_type"}, ...]

        ``url`` is set when the worker uploaded to S3/Supabase (preferred).
        ``data`` holds base64 when no S3 upload was configured (dev fallback).

        ``kind`` is "image" or "video", classified by the output filename
        EXTENSION first (so a VHS mp4 is detected regardless of which output key
        the worker uses), falling back to the source key. Video output can arrive
        under ``images`` (some worker-comfyui builds flatten everything there),
        ``gifs`` (VHS_VideoCombine's legacy key), or ``videos`` — scan all three.
        ``filename/type/url/data`` are preserved unchanged so existing
        image-only consumers keep working.
        """
        if not output:
            return []
        normalized: List[Dict[str, Optional[str]]] = []
        for key in ("images", "gifs", "videos"):
            items = output.get(key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                img_type = item.get("type")
                data = item.get("data")
                url = item.get("url")
                filename = item.get("filename")
                # worker-comfyui puts the S3 URL in `data` when type == "s3_url"
                if img_type in ("s3_url", "url") and data and not url:
                    url = data
                    data = None

                # Classify by extension first, then by which key it came under.
                ext = ""
                if filename and "." in filename:
                    ext = filename.rsplit(".", 1)[-1].lower()
                content_type = RunPodServerlessClient._VIDEO_EXT_CONTENT_TYPE.get(ext)
                if content_type is not None:
                    # A .gif is an animated image but stays on the raw-bytes path;
                    # everything else in the map is real video.
                    kind = "image" if ext == "gif" else "video"
                elif key in ("gifs", "videos"):
                    # Unknown extension but under a video key -> treat as video.
                    kind = "video"
                    content_type = "video/mp4"
                else:
                    kind = "image"
                    content_type = "image/png"

                normalized.append(
                    {
                        "filename": filename,
                        "type": img_type,
                        "url": url,
                        "data": data if img_type in ("base64", None) else None,
                        "kind": kind,
                        "content_type": content_type,
                    }
                )
        return normalized

    @staticmethod
    def extract_error(job_doc: dict) -> str:
        """Best-effort human-readable error string from a terminal job document."""
        err = job_doc.get("error")
        if err:
            return str(err)
        output = job_doc.get("output")
        if isinstance(output, dict) and output.get("errors"):
            return "; ".join(str(e) for e in output["errors"])
        if isinstance(output, str):
            return output
        return f"RunPod job ended with status {job_doc.get('status')}"
