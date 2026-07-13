"""
Tests for VIDEO job cancel routing (RUNPOD_VIDEO_ENDPOINT_ID): a video (reel) job
must be cancelled on the dedicated video RunPod client when one is attached, since
it was submitted there rather than to the main endpoint; every other job type must
keep cancelling on the main client unconditionally. See
JobManager.attach_video_runpod_client and JobManager.cancel_job
(services/job_manager.py).

Runs under pytest or directly: python loli_api/tests/test_video_endpoint_routing.py
"""
import asyncio

import models.requests as _mr
from models.enums import JobStatus, MotionType, OutfitType
from models.requests import OutfitEditRequest, VideoGenerateRequest
from services.job_manager import JobManager

_mr.validate_source_image = lambda u: u  # type: ignore -- bypass SSRF allowlist (offline test)


class _FakeRunpodClient:
    """Records cancel(runpod_id) calls; mirrors RunPodServerlessClient's async cancel."""

    def __init__(self):
        self.cancelled_ids = []

    async def cancel(self, runpod_id: str) -> bool:
        self.cancelled_ids.append(runpod_id)
        return True


def _video_request() -> VideoGenerateRequest:
    return VideoGenerateRequest(source_image_id="char_img_1", motion=MotionType.SUBTLE_IDLE)


def _image_request() -> OutfitEditRequest:
    return OutfitEditRequest(source_image="https://example.com/src.png", outfit=OutfitType.BIKINI)


async def _submitted_job(job_manager: JobManager, request, job_type: str, runpod_id: str):
    """
    Create a job and bring it to the same state a real in-flight RunPod submission
    would: a runpod_id attached and a non-terminal (RUNNING) status. Uses only the
    public JobManager API (create_job / set_runpod_id / update_job_status).
    """
    job = await job_manager.create_job(request, user_id="admin", job_type=job_type)
    await job_manager.set_runpod_id(job.job_id, runpod_id)
    await job_manager.update_job_status(job.job_id, JobStatus.RUNNING)
    return job


# --- routing: video jobs use the dedicated video client, image jobs use the main one ---
def test_cancel_routes_video_job_to_dedicated_video_client():
    async def run():
        job_manager = JobManager()
        main_client = _FakeRunpodClient()
        video_client = _FakeRunpodClient()
        job_manager.attach_runpod_client(main_client)
        job_manager.attach_video_runpod_client(video_client)

        job = await _submitted_job(job_manager, _video_request(), "video_gen", "rp-video-1")
        cancelled = await job_manager.cancel_job(job.job_id, "admin")

        assert cancelled is True
        assert video_client.cancelled_ids == ["rp-video-1"]
        assert main_client.cancelled_ids == []  # never touches the main client

    asyncio.run(run())


def test_cancel_routes_image_job_to_main_client():
    async def run():
        job_manager = JobManager()
        main_client = _FakeRunpodClient()
        video_client = _FakeRunpodClient()
        job_manager.attach_runpod_client(main_client)
        job_manager.attach_video_runpod_client(video_client)

        job = await _submitted_job(job_manager, _image_request(), "outfit_edit", "rp-image-1")
        cancelled = await job_manager.cancel_job(job.job_id, "admin")

        assert cancelled is True
        assert main_client.cancelled_ids == ["rp-image-1"]
        assert video_client.cancelled_ids == []  # image jobs never touch the video client

    asyncio.run(run())


# --- fallback: no dedicated video client attached -> video jobs use the main client ---
def test_cancel_video_job_falls_back_to_main_client_when_no_video_client_attached():
    async def run():
        job_manager = JobManager()
        main_client = _FakeRunpodClient()
        job_manager.attach_runpod_client(main_client)
        # attach_video_runpod_client is never called -> _video_runpod_client stays None.

        job = await _submitted_job(job_manager, _video_request(), "video_gen", "rp-video-2")
        cancelled = await job_manager.cancel_job(job.job_id, "admin")

        assert cancelled is True
        assert main_client.cancelled_ids == ["rp-video-2"]

    asyncio.run(run())


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
