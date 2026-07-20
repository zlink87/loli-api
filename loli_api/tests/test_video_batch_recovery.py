"""
THE durability suite for VideoBatchReconciler (services/video_batch_orchestrator.py).

The submit-only worker persists a durable ``runpod_request_id`` on the item; the
reconciler owns polling / publish / retry / startup recovery so a deploy never
strands an in-flight clip. This suite pins that behaviour:

  * IN_QUEUE / IN_PROGRESS -> item stays in-flight (runpod_status synced only);
  * COMPLETED with base64 output -> upload + publish -> succeeded with both guards set;
  * COMPLETED with a URL output -> passthrough (no upload), succeeded;
  * FAILED -> retry (reset) while attempts < cap, then failed at the cap;
  * a transient status() exception leaves the item untouched, consuming NO attempt;
  * startup recovery: a running item WITH a handle is re-polled (recovers a clip that
    COMPLETED while we were down); a queued item WITHOUT a handle resets to pending;
    a queued item WITH a handle is treated as in-flight (polled, not reset).

Runs under pytest or directly: python loli_api/tests/test_video_batch_recovery.py
"""
import asyncio
import base64
from types import SimpleNamespace

from services.video_batch_orchestrator import VideoBatchReconciler


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeVideoStore:
    def __init__(self):
        self.batches = []          # list[SimpleNamespace]
        self.items = {}            # id -> row dict
        self.updates = []          # ordered list of (item_id, fields) — publish ordering
        self.reset_ids = []        # item ids passed to reset_item_for_retry

    def add_batch(self, batch_id, status="running", character_id="char-1", defaults=None):
        self.batches.append(SimpleNamespace(
            id=batch_id, status=status, character_id=character_id, defaults=defaults or {},
        ))

    def add_item(self, row):
        self.items[row["id"]] = row
        return row

    async def list_active_batches(self):
        return list(self.batches)

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
        self.reset_ids.append(item_id)
        self.items[item_id].update({
            "status": "pending", "job_id": None, "runpod_request_id": None,
            "runpod_status": None, "submitted_at": None,
            "error_code": None, "error_message": None,
        })  # attempts intentionally preserved

    async def update_batch_aggregate(self, batch_id):
        return None


class FakeImageStore:
    def __init__(self):
        self.images = []
        self.actions = []

    async def get_image(self, image_id):
        return {"metadata": {}}

    async def create_image(self, character_id, **kw):
        self.images.append((character_id, kw))
        return f"cimg-{len(self.images)}"

    async def create_action(self, character_id, **kw):
        self.actions.append((character_id, kw))
        return f"act-{len(self.actions)}"


class FakeRunPod:
    """Returns a fixed status doc; records the ids polled; can be set to raise."""

    def __init__(self, doc=None, raises=False):
        self.doc = doc
        self.raises = raises
        self.polled = []

    async def status(self, rid):
        self.polled.append(rid)
        if self.raises:
            raise RuntimeError("transient RunPod 503")
        return self.doc


class FakeSupaStorage:
    def __init__(self):
        self.calls = []

    def upload_video(self, video, video_id, folder, ext="mp4", content_type="video/mp4"):
        self.calls.append((video_id, folder, ext, content_type))
        return (f"https://storage/{folder}/{video_id}.{ext}", "vhash")


def _settings():
    return SimpleNamespace(
        VIDEO_BATCH_MAX_INFLIGHT=2,
        VIDEO_BATCH_ITEM_MAX_ATTEMPTS=2,
        RUNPOD_POLL_INTERVAL_SECONDS=5,
    )


def _reconciler(store, runpod, images=None, storage=None):
    return VideoBatchReconciler(
        job_manager=None,
        video_batch_store=store,
        character_image_store=images if images is not None else FakeImageStore(),
        video_runpod_client=runpod,
        settings=_settings(),
        supabase_storage_service=storage,
    )


def _item(item_id="i1", batch_id="b1", **over):
    row = {
        "id": item_id, "batch_id": batch_id, "item_index": 0, "status": "running",
        "source_image_id": "still-a", "source_image_url": "https://x/still-a.png",
        "action_kind": "preset", "preset_id": "subtle_idle", "custom_prompt": None,
        "tier": "charm_idle", "motion_text": "subtle idle motion, at the camera",
        "motion_label": "Subtle Idle", "loras": [], "quality_mode": "fast",
        "width": 480, "height": 832, "length": 81, "fps": 16, "seed": 42,
        "negative_prompt": None, "attempts": 1,
        "runpod_request_id": "rp-1", "runpod_status": "IN_QUEUE",
        "character_image_id": None, "action_id": None,
        "video_url": None, "preview_url": None,
    }
    row.update(over)
    return row


def _completed_base64_doc():
    b64 = base64.b64encode(b"FAKE-MP4-BYTES").decode("ascii")
    return {"status": "COMPLETED",
            "output": {"images": [{"filename": "clip.mp4", "type": "base64", "data": b64}]}}


def _completed_url_doc(url="https://cdn/clip.mp4"):
    return {"status": "COMPLETED",
            "output": {"images": [{"filename": "clip.mp4", "type": "s3_url", "data": url}]}}


# ---------------------------------------------------------------------------
# Poll: non-terminal
# ---------------------------------------------------------------------------
def test_in_progress_keeps_item_inflight_syncs_status():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        row = store.add_item(_item(status="running", runpod_status="IN_QUEUE"))
        images = FakeImageStore()
        rec = _reconciler(store, FakeRunPod({"status": "IN_PROGRESS"}), images=images)

        await rec._poll_item(store.batches[0], row)

        assert store.items["i1"]["status"] == "running"           # still in-flight
        assert store.items["i1"]["runpod_status"] == "IN_PROGRESS"  # synced
        assert store.items["i1"]["attempts"] == 1                  # no attempt consumed
        assert images.images == [] and images.actions == []        # nothing published
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Poll: COMPLETED
# ---------------------------------------------------------------------------
def test_completed_base64_uploads_publishes_and_succeeds():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        row = store.add_item(_item())
        images, storage = FakeImageStore(), FakeSupaStorage()
        rec = _reconciler(store, FakeRunPod(_completed_base64_doc()), images=images, storage=storage)

        await rec._poll_item(store.batches[0], row)

        it = store.items["i1"]
        assert it["status"] == "succeeded"
        assert storage.calls, "base64 output must be uploaded to storage"
        assert it["video_url"].endswith(".mp4")
        # both publish guards persisted, gallery row + DRAFT action created.
        assert it["character_image_id"] is not None
        assert it["action_id"] is not None
        assert len(images.images) == 1 and len(images.actions) == 1
        _, img_kw = images.images[0]
        assert img_kw["image_type"] == "video"
        _, act_kw = images.actions[0]
        assert act_kw["is_active"] is False  # DRAFT — admin publishes after review
        assert act_kw["media_type"] == "video"
    asyncio.run(run())


def test_completed_url_output_passthrough_no_upload():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        row = store.add_item(_item())
        images, storage = FakeImageStore(), FakeSupaStorage()
        rec = _reconciler(store, FakeRunPod(_completed_url_doc("https://cdn/clip.mp4")),
                          images=images, storage=storage)

        await rec._poll_item(store.batches[0], row)

        it = store.items["i1"]
        assert it["status"] == "succeeded"
        assert it["video_url"] == "https://cdn/clip.mp4"  # passthrough
        assert storage.calls == []                        # never uploaded a URL output
        assert it["character_image_id"] is not None and it["action_id"] is not None
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Poll: FAILED -> retry then cap
# ---------------------------------------------------------------------------
def test_failed_under_cap_retries():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        store.add_item(_item(attempts=1))  # cap is 2, so 1 < 2 -> retry
        rec = _reconciler(store, FakeRunPod({"status": "FAILED", "error": "boom"}))

        await rec._poll_item(store.batches[0], store.items["i1"])

        assert store.reset_ids == ["i1"]              # reset for a retry
        assert store.items["i1"]["status"] == "pending"
        assert store.items["i1"]["attempts"] == 1     # attempts preserved across the reset
    asyncio.run(run())


def test_failed_at_cap_marks_failed():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        store.add_item(_item(attempts=2))  # == cap -> terminal failure
        rec = _reconciler(store, FakeRunPod({"status": "FAILED", "error": "boom"}))

        await rec._poll_item(store.batches[0], store.items["i1"])

        assert store.reset_ids == []                  # no more retries
        assert store.items["i1"]["status"] == "failed"
        assert store.items["i1"]["error_code"] == "VIDEO_RUNPOD_FAILED"
        assert "boom" in store.items["i1"]["error_message"]
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Poll: transient error is not attempt-consuming
# ---------------------------------------------------------------------------
def test_transient_status_error_leaves_item_untouched():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1")
        store.add_item(_item(status="running", attempts=1))
        rec = _reconciler(store, FakeRunPod(raises=True))

        await rec._poll_item(store.batches[0], store.items["i1"])

        # A transient poll error is swallowed: no writes, no reset, no attempt burned.
        assert store.updates == []
        assert store.reset_ids == []
        assert store.items["i1"]["status"] == "running"
        assert store.items["i1"]["attempts"] == 1
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------
def test_recovery_running_item_with_handle_is_repolled_and_recovered():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1", status="running")
        store.add_item(_item(status="running", runpod_request_id="rp-9"))
        runpod = FakeRunPod(_completed_base64_doc())
        images, storage = FakeImageStore(), FakeSupaStorage()
        rec = _reconciler(store, runpod, images=images, storage=storage)

        await rec._recover_on_startup()

        assert runpod.polled == ["rp-9"]                  # the durable handle was re-polled
        assert store.items["i1"]["status"] == "succeeded"  # COMPLETED_WHILE_DOWN recovered
        assert store.items["i1"]["character_image_id"] is not None
    asyncio.run(run())


def test_recovery_queued_item_without_handle_resets_to_pending():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1", status="running")
        store.add_item(_item(status="queued", runpod_request_id=None, runpod_status=None))
        runpod = FakeRunPod(_completed_base64_doc())
        rec = _reconciler(store, runpod)

        await rec._recover_on_startup()

        assert runpod.polled == []                    # never submitted -> nothing to poll
        assert store.reset_ids == ["i1"]              # safely reset for a fresh enqueue
        assert store.items["i1"]["status"] == "pending"
    asyncio.run(run())


def test_recovery_queued_item_with_handle_is_treated_as_inflight():
    async def run():
        store = FakeVideoStore(); store.add_batch("b1", status="running")
        store.add_item(_item(status="queued", runpod_request_id="rp-7", runpod_status="IN_QUEUE"))
        runpod = FakeRunPod({"status": "IN_PROGRESS"})
        rec = _reconciler(store, runpod)

        await rec._recover_on_startup()

        assert runpod.polled == ["rp-7"]              # polled, treated as in-flight
        assert store.reset_ids == []                  # NOT reset (a real submission exists)
        assert store.items["i1"]["status"] == "running"
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
