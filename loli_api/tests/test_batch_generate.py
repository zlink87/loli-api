"""
Tests for POST /v1/generate/batch (Batch Character Creation dispatch).

Covers: N items -> N jobIds routed to the isolated creation_queue (NOT the interactive
self.queue) with job_type kept "text_to_image" (poll response identical to single); the
atomic 429 when the batch can't fit entirely (and nothing is enqueued); optional id echo.

Uses a REAL JobManager (queues are exercised) + direct endpoint calls, mirroring
test_persona_endpoint.py's direct-call style. Runs under pytest or directly:
    python loli_api/tests/test_batch_generate.py
"""
import asyncio

from fastapi import HTTPException

from models.requests import PersonaOptions, GenerateImageRequest, BatchGenerateRequest
from models.enums import JobStatus
from services.job_manager import JobManager
from api.v1.endpoints import generate as ep


def _item(id=None, name="Sakura"):
    persona = PersonaOptions(
        ethnicity="asian", age=26, hairStyle="ponytail", hairColor="black",
        eyeColor="brown", name=name,
    )
    return GenerateImageRequest(id=id, persona=persona)


def test_batch_dispatch_returns_n_jobids_on_creation_queue():
    async def scenario():
        jm = JobManager(max_queue_size=10, creation_queue_max_size=100)
        ep.set_job_manager(jm)
        req = BatchGenerateRequest(items=[_item("draft-a1"), _item("draft-b2", "Val")])
        resp = await ep.create_batch_generate_jobs(req, user={"sub": "admin"})
        jobs = [await jm.get_job(i.jobId) for i in resp.items]
        return jm, resp, jobs

    jm, resp, jobs = asyncio.run(scenario())

    assert len(resp.items) == 2
    assert [i.index for i in resp.items] == [0, 1]
    assert [i.id for i in resp.items] == ["draft-a1", "draft-b2"]  # client refs echoed
    assert all(i.status == JobStatus.QUEUED for i in resp.items)
    assert all(i.jobId for i in resp.items)

    # Routed to the dedicated creation queue, NOT the interactive single-generate queue.
    assert jm.creation_queue.qsize() == 2
    assert jm.queue.qsize() == 0

    # job_type stays text_to_image so GET /v1/jobs/{jobId} is identical to single-generate.
    assert all(j.job_type == "text_to_image" for j in jobs)


def test_batch_429_when_queue_cant_fit_all_and_enqueues_none():
    async def scenario():
        jm = JobManager(max_queue_size=10, creation_queue_max_size=2)
        ep.set_job_manager(jm)
        req = BatchGenerateRequest(items=[_item(), _item(), _item()])  # 3 > cap 2
        raised = None
        try:
            await ep.create_batch_generate_jobs(req, user={"sub": "admin"})
        except HTTPException as e:
            raised = e
        return jm, raised

    jm, raised = asyncio.run(scenario())

    assert raised is not None and raised.status_code == 429
    assert jm.creation_queue.qsize() == 0  # atomic: none enqueued on rejection


def test_batch_at_exact_capacity_succeeds():
    async def scenario():
        jm = JobManager(max_queue_size=10, creation_queue_max_size=2)
        ep.set_job_manager(jm)
        req = BatchGenerateRequest(items=[_item(), _item()])  # exactly cap 2
        resp = await ep.create_batch_generate_jobs(req, user={"sub": "admin"})
        return jm, resp

    jm, resp = asyncio.run(scenario())
    assert len(resp.items) == 2
    assert jm.creation_queue.qsize() == 2


def test_batch_id_optional_echoes_none():
    async def scenario():
        jm = JobManager(creation_queue_max_size=100)
        ep.set_job_manager(jm)
        resp = await ep.create_batch_generate_jobs(
            BatchGenerateRequest(items=[_item()]), user={"sub": "admin"}
        )
        return resp

    resp = asyncio.run(scenario())
    assert resp.items[0].id is None
    assert resp.items[0].index == 0


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
