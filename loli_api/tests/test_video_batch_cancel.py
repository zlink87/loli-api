"""
Tests for VideoBatchOrchestrator.cancel_batch (services/video_batch_orchestrator.py).

Cancelling a batch must abort in-flight RunPod jobs directly via each item's durable
``runpod_request_id`` on the DEDICATED video client (never the main endpoint), then
mark the still-open items + the batch 'cancelled'. Items that were never submitted
(no runpod_request_id) can't be cancelled remotely but must still be marked; already
terminal items (succeeded/failed) are left alone.

Runs under pytest or directly: python loli_api/tests/test_video_batch_cancel.py
"""
import asyncio
from types import SimpleNamespace

from services.video_batch_orchestrator import VideoBatchOrchestrator


class FakeVideoStore:
    def __init__(self):
        self.batches = {}
        self.items = {}
        self.batch_status = {}

    def add_batch(self, batch_id, character_id="char-1", status="running"):
        self.batches[batch_id] = SimpleNamespace(
            id=batch_id, character_id=character_id, status=status, defaults={},
        )

    def add_item(self, row):
        self.items[row["id"]] = row

    async def get_batch(self, batch_id):
        return self.batches.get(batch_id)

    async def list_item_rows(self, batch_id, statuses=None):
        rows = [r for r in self.items.values() if r.get("batch_id") == batch_id]
        if statuses:
            rows = [r for r in rows if r["status"] in statuses]
        return sorted(rows, key=lambda r: r["item_index"])

    async def update_item(self, item_id, **fields):
        self.items[item_id].update(fields)

    async def set_batch_status(self, batch_id, status, error=None):
        self.batch_status[batch_id] = status
        if batch_id in self.batches:
            self.batches[batch_id].status = status

    async def update_batch_aggregate(self, batch_id):
        return None


class FakeVideoRunPod:
    """Records the runpod_request_ids passed to cancel()."""

    def __init__(self):
        self.cancelled_ids = []

    async def cancel(self, runpod_id):
        self.cancelled_ids.append(runpod_id)
        return True


def _item(item_id, index, status, runpod_request_id=None, batch_id="b1"):
    return {
        "id": item_id, "batch_id": batch_id, "item_index": index, "status": status,
        "runpod_request_id": runpod_request_id,
    }


def _orch(store, video_runpod_client):
    return VideoBatchOrchestrator(
        job_manager=None,
        character_store=None,
        video_batch_store=store,
        character_image_store=None,
        motion_writer=None,
        settings=SimpleNamespace(),
        video_runpod_client=video_runpod_client,
    )


def test_cancel_aborts_inflight_and_marks_items_and_batch():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        store.add_item(_item("i1", 0, "running", runpod_request_id="rp-1"))
        store.add_item(_item("i2", 1, "queued", runpod_request_id="rp-2"))
        store.add_item(_item("i3", 2, "pending", runpod_request_id=None))
        store.add_item(_item("i4", 3, "succeeded", runpod_request_id="rp-4"))  # terminal
        client = FakeVideoRunPod()
        orch = _orch(store, client)

        ok = await orch.cancel_batch("b1")

        assert ok is True
        # only the in-flight items (running/queued WITH a handle) were aborted remotely.
        assert client.cancelled_ids == ["rp-1", "rp-2"]
        # running / queued / pending all marked cancelled...
        assert store.items["i1"]["status"] == "cancelled"
        assert store.items["i2"]["status"] == "cancelled"
        assert store.items["i3"]["status"] == "cancelled"
        # ...the already-succeeded item is untouched.
        assert store.items["i4"]["status"] == "succeeded"
        # the batch is marked cancelled.
        assert store.batch_status["b1"] == "cancelled"
    asyncio.run(run())


def test_cancel_marks_never_submitted_item_without_remote_call():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        # pending item, never submitted -> no runpod handle to cancel.
        store.add_item(_item("i1", 0, "pending", runpod_request_id=None))
        client = FakeVideoRunPod()
        orch = _orch(store, client)

        ok = await orch.cancel_batch("b1")

        assert ok is True
        assert client.cancelled_ids == []              # nothing to cancel remotely
        assert store.items["i1"]["status"] == "cancelled"  # still marked
        assert store.batch_status["b1"] == "cancelled"
    asyncio.run(run())


def test_cancel_uses_the_dedicated_video_client_passed_at_call_time():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        store.add_item(_item("i1", 0, "running", runpod_request_id="rp-9"))
        # No client wired on the orchestrator; one is provided at call time instead.
        orch = _orch(store, video_runpod_client=None)
        call_client = FakeVideoRunPod()

        ok = await orch.cancel_batch("b1", video_runpod_client=call_client)

        assert ok is True
        assert call_client.cancelled_ids == ["rp-9"]
        assert store.items["i1"]["status"] == "cancelled"
    asyncio.run(run())


def test_cancel_unknown_batch_returns_false():
    async def run():
        store = FakeVideoStore()
        orch = _orch(store, FakeVideoRunPod())
        assert await orch.cancel_batch("nope") is False
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
