"""
Tests for the video-batch publish path:

  * publish-before-terminal ordering — the gallery row + DRAFT action + both
    idempotency guards are written BEFORE the item flips to 'succeeded';
  * idempotency — an item that already carries character_image_id + action_id does
    NOT create a second gallery row / action on a re-poll;
  * a publish failure leaves the item non-terminal (the next tick retries);
  * VideoBatchOrchestrator.publish_batch flips every succeeded item's DRAFT action
    active and returns the published count (items without an action_id are skipped).

Runs under pytest or directly: python loli_api/tests/test_video_batch_publish.py
"""
import asyncio
from types import SimpleNamespace

from services.video_batch_orchestrator import (
    VideoBatchReconciler,
    VideoBatchOrchestrator,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeVideoStore:
    def __init__(self):
        self.batches = {}   # id -> SimpleNamespace
        self.items = {}     # id -> row dict
        self.updates = []   # ordered (item_id, fields)

    def add_batch(self, batch_id, character_id="char-1", status="running"):
        self.batches[batch_id] = SimpleNamespace(
            id=batch_id, character_id=character_id, status=status, defaults={},
        )
        return self.batches[batch_id]

    def add_item(self, row):
        self.items[row["id"]] = row
        return row

    async def get_batch(self, batch_id):
        return self.batches.get(batch_id)

    async def list_active_batches(self):
        return list(self.batches.values())

    async def list_item_rows(self, batch_id, statuses=None):
        rows = [r for r in self.items.values() if r.get("batch_id") == batch_id]
        if statuses:
            rows = [r for r in rows if r["status"] in statuses]
        return sorted(rows, key=lambda r: r["item_index"])

    async def get_item_row(self, item_id, batch_id=None):
        return self.items.get(item_id)

    async def update_item(self, item_id, **fields):
        self.updates.append((item_id, fields))
        self.items[item_id].update(fields)

    async def reset_item_for_retry(self, item_id):
        self.items[item_id].update({"status": "pending", "runpod_request_id": None})

    async def update_batch_aggregate(self, batch_id):
        return None


class FakeImageStore:
    def __init__(self, fail_on_image=False):
        self.images = []
        self.actions = []
        self.activated = []          # (action_id, character_id, is_active)
        self.fail_on_image = fail_on_image

    async def get_image(self, image_id):
        return {"metadata": {}}

    async def create_image(self, character_id, **kw):
        if self.fail_on_image:
            raise RuntimeError("supabase down")
        self.images.append((character_id, kw))
        return f"cimg-{len(self.images)}"

    async def create_action(self, character_id, **kw):
        self.actions.append((character_id, kw))
        return f"act-{len(self.actions)}"

    async def set_action_active(self, action_id, character_id, is_active=True):
        self.activated.append((action_id, character_id, is_active))
        return {"id": action_id, "is_active": is_active}


class FakeRunPod:
    def __init__(self, doc):
        self.doc = doc

    async def status(self, rid):
        return self.doc


def _settings():
    return SimpleNamespace(
        VIDEO_BATCH_MAX_INFLIGHT=2,
        VIDEO_BATCH_ITEM_MAX_ATTEMPTS=2,
        RUNPOD_POLL_INTERVAL_SECONDS=5,
    )


def _completed_url_doc(url="https://cdn/clip.mp4"):
    return {"status": "COMPLETED",
            "output": {"images": [{"filename": "clip.mp4", "type": "s3_url", "data": url}]}}


def _item(item_id="i1", batch_id="b1", **over):
    row = {
        "id": item_id, "batch_id": batch_id, "item_index": 0, "status": "running",
        "source_image_id": "still-a", "source_image_url": "https://x/still-a.png",
        "action_kind": "preset", "preset_id": "subtle_idle", "tier": "charm_idle",
        "motion_text": "subtle idle motion, at the camera", "motion_label": "Subtle Idle",
        "loras": [], "quality_mode": "fast", "seed": 42, "attempts": 1,
        "runpod_request_id": "rp-1", "runpod_status": "IN_PROGRESS",
        "character_image_id": None, "action_id": None,
        "video_url": None, "preview_url": None,
    }
    row.update(over)
    return row


def _reconciler(store, images, runpod):
    return VideoBatchReconciler(
        job_manager=None,
        video_batch_store=store,
        character_image_store=images,
        video_runpod_client=runpod,
        settings=_settings(),
        supabase_storage_service=None,  # URL outputs need no storage
    )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------
def test_guards_and_publish_precede_terminal_status():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        store.add_item(_item())
        images = FakeImageStore()
        rec = _reconciler(store, images, FakeRunPod(_completed_url_doc()))

        await rec._poll_item(store.batches["b1"], store.items["i1"])

        # The terminal 'succeeded' write is the LAST update; both guards land before it.
        assert store.updates[-1][1].get("status") == "succeeded"
        # exactly one terminal write, and it's the final one.
        terminal_positions = [
            n for n, (_i, f) in enumerate(store.updates) if f.get("status") == "succeeded"
        ]
        assert terminal_positions == [len(store.updates) - 1]

        guard_positions = [
            n for n, (_i, f) in enumerate(store.updates)
            if "character_image_id" in f or "action_id" in f
        ]
        assert guard_positions, "publish guards must be persisted"
        assert max(guard_positions) < terminal_positions[0], (
            "guards must be written BEFORE the item goes terminal"
        )
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
def test_existing_guards_skip_duplicate_publish_on_repoll():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        # Item already published (guards set) but lingering non-terminal.
        store.add_item(_item(character_image_id="cimg-existing", action_id="act-existing"))
        images = FakeImageStore()
        rec = _reconciler(store, images, FakeRunPod(_completed_url_doc()))

        await rec._poll_item(store.batches["b1"], store.items["i1"])

        # No duplicate gallery row / action; the item still settles to succeeded.
        assert images.images == []
        assert images.actions == []
        assert store.items["i1"]["status"] == "succeeded"
        assert store.items["i1"]["character_image_id"] == "cimg-existing"
        assert store.items["i1"]["action_id"] == "act-existing"
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Publish failure keeps the item non-terminal
# ---------------------------------------------------------------------------
def test_publish_failure_leaves_item_non_terminal():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        store.add_item(_item())
        images = FakeImageStore(fail_on_image=True)
        rec = _reconciler(store, images, FakeRunPod(_completed_url_doc()))

        await rec._poll_item(store.batches["b1"], store.items["i1"])

        # Nothing published, and crucially the item was NOT flipped to succeeded —
        # the next tick retries the whole publish.
        assert images.images == []
        assert store.items["i1"]["status"] != "succeeded"
        assert not any(f.get("status") == "succeeded" for _i, f in store.updates)
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Bulk publish
# ---------------------------------------------------------------------------
def _orchestrator(store, images):
    return VideoBatchOrchestrator(
        job_manager=None,
        character_store=None,
        video_batch_store=store,
        character_image_store=images,
        motion_writer=None,
        settings=_settings(),
    )


def test_publish_batch_flips_succeeded_actions_and_counts():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1", character_id="char-1")
        store.add_item(_item("i1", status="succeeded", action_id="act-1", item_index=0))
        store.add_item(_item("i2", status="succeeded", action_id="act-2", item_index=1))
        # a succeeded item with NO action_id (publish couldn't create it) -> skipped.
        store.add_item(_item("i3", status="succeeded", action_id=None, item_index=2))
        # a non-succeeded item -> not even listed.
        store.add_item(_item("i4", status="failed", action_id="act-4", item_index=3))
        images = FakeImageStore()
        orch = _orchestrator(store, images)

        published = await orch.publish_batch("b1")

        assert published == 2
        assert images.activated == [
            ("act-1", "char-1", True),
            ("act-2", "char-1", True),
        ]
    asyncio.run(run())


def test_publish_batch_unknown_batch_returns_none():
    async def run():
        store = FakeVideoStore()
        orch = _orchestrator(store, FakeImageStore())
        assert await orch.publish_batch("nope") is None
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
