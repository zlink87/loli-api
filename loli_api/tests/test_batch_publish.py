"""
Tests for BatchReconciler._handle_succeeded — publishing a finished photo into
the real product tables (character_images + chat_persona_actions) BEFORE the
batch item is marked succeeded, with character_image_id as the idempotency guard.

Runs under pytest or directly: python loli_api/tests/test_batch_publish.py
"""
import asyncio
from types import SimpleNamespace

from models.enums import OutfitType, LocationType
from models.batch import BatchControls
from models.scene import SceneSpec
from services.batch_orchestrator import BatchReconciler


def _settings():
    return SimpleNamespace(
        BATCH_MAX_INFLIGHT=3,
        BATCH_ITEM_MAX_ATTEMPTS=2,
        RUNPOD_POLL_INTERVAL_SECONDS=1,
    )


class _FakeBatchStore:
    def __init__(self):
        self.item_updates = []
        self.item_row = {}

    async def update_item_result(self, item_id, **fields):
        self.item_updates.append((item_id, fields))

    async def _get_item(self, item_id):
        return self.item_row


class _FakeImageStore:
    def __init__(self, fail_on_image=False, fail_on_action=False):
        self.images = []
        self.actions = []
        self.fail_on_image = fail_on_image
        self.fail_on_action = fail_on_action
        self.sequence = []

    async def create_image(self, character_id, **kw):
        if self.fail_on_image:
            raise RuntimeError("supabase down")
        self.sequence.append("image")
        self.images.append((character_id, kw))
        return f"img-{len(self.images)}"

    async def create_action(self, character_id, **kw):
        if self.fail_on_action:
            raise RuntimeError("supabase down")
        self.sequence.append("action")
        self.actions.append((character_id, kw))
        return f"act-{len(self.actions)}"


def _scene_spec():
    return SceneSpec(
        arc_id="morning", arc_title="Slow morning", beat_index=1, global_index=3,
        beat_description="Sipping coffee by the window",
        outfit=OutfitType.SILK_PAJAMAS, location=LocationType.HOME_KITCHEN,
    ).model_dump(mode="json")


def _batch():
    return SimpleNamespace(
        id="b1", character_id="c1", controls=BatchControls(), likes=[], dislikes=[],
    )


def _item(character_image_id=None):
    return SimpleNamespace(
        id="i1", scene_index=3, arc="morning", beat=1, attempts=1,
        scene_spec=_scene_spec(), character_image_id=character_image_id,
    )


def _job():
    return SimpleNamespace(
        job_id="batjob_1", preview_url="https://x/preview.png",
        image_hash="deadbeef", seed_used=42,
    )


def _reconciler(batch_store, image_store):
    return BatchReconciler(
        job_manager=None,
        character_store=None,
        batch_store=batch_store,
        settings=_settings(),
        supabase_storage_service=None,  # image_url falls back to job.preview_url
        character_image_store=image_store,
    )


def test_success_publishes_image_and_action_then_marks_item():
    store, images = _FakeBatchStore(), _FakeImageStore()
    store.item_row = {"pipeline_request": {"prompt": "kitchen at dawn, golden light"}}
    rec = _reconciler(store, images)

    asyncio.run(rec._handle_succeeded(_batch(), _item(), _job()))

    # gallery row + quick action created, in that order
    assert images.sequence == ["image", "action"]
    char_id, img_kw = images.images[0]
    assert char_id == "c1"
    assert img_kw["image_url"] == "https://x/preview.png"
    assert img_kw["prompt"] == "kitchen at dawn, golden light"  # pipeline_request wins
    assert img_kw["seed"] == 42
    assert img_kw["outfit"] == "silk_pajamas"
    assert img_kw["metadata"]["batch_id"] == "b1"
    assert img_kw["metadata"]["image_hash"] == "deadbeef"

    _, act_kw = images.actions[0]
    assert act_kw["character_image_id"] == "img-1"
    assert act_kw["label"] == "Sipping coffee by the window"
    assert act_kw["sort_order"] == 3

    # item marked succeeded exactly once, AFTER publishing, with the image id
    assert len(store.item_updates) == 1
    item_id, fields = store.item_updates[0]
    assert item_id == "i1"
    assert fields["status"] == "succeeded"
    assert fields["character_image_id"] == "img-1"


def test_publish_failure_leaves_item_non_terminal():
    store = _FakeBatchStore()
    images = _FakeImageStore(fail_on_image=True)
    rec = _reconciler(store, images)

    asyncio.run(rec._handle_succeeded(_batch(), _item(), _job()))

    # nothing published, and crucially the item was NOT marked succeeded —
    # the next reconciler tick retries the whole handler.
    assert images.images == []
    assert store.item_updates == []


def test_existing_character_image_id_skips_reinsert():
    store, images = _FakeBatchStore(), _FakeImageStore()
    rec = _reconciler(store, images)

    asyncio.run(rec._handle_succeeded(_batch(), _item(character_image_id="img-9"), _job()))

    assert images.images == []  # no duplicate gallery row
    assert images.actions == []
    _, fields = store.item_updates[0]
    assert fields["status"] == "succeeded"
    assert fields["character_image_id"] == "img-9"


def test_no_image_store_still_marks_item():
    # Deployments without the image store keep the legacy item-only behavior.
    store = _FakeBatchStore()
    rec = _reconciler(store, None)

    asyncio.run(rec._handle_succeeded(_batch(), _item(), _job()))

    _, fields = store.item_updates[0]
    assert fields["status"] == "succeeded"
    assert fields["character_image_id"] is None


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
