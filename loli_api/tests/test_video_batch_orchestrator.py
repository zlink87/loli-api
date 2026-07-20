"""
Tests for VideoBatchOrchestrator.launch_batch (services/video_batch_orchestrator.py)
with in-memory fakes.

Covers the launch-time contract:
  * source-still validation: a video row, a still from another character, or a
    missing id are each rejected (VideoBatchValidationError with the right code);
  * an unknown preset_id is rejected;
  * a preset item snapshots tier + loras (from the catalog) + motion_text + label;
  * a custom item runs the Venice MotionWriter AT LAUNCH and persists its output;
  * an explicit-tier item is gated on VIDEO_BATCH_EXPLICIT_ENABLED and on the
    lightning graph being available;
  * seed strategies (fixed / per_item / random);
  * dry_run -> 'planned' (no enqueue), real -> 'running', and an estimate is returned.

Runs under pytest or directly: python loli_api/tests/test_video_batch_orchestrator.py
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from models.batch import SeedStrategy
from models.video_batch import (
    VideoBatchCreate,
    VideoBatchItemCreate,
    VideoBatchDefaults,
    VideoBatchRead,
)
from services.video_action_catalog import get_preset
from services.video_workflow import resolve_item_loras
from services.video_batch_orchestrator import (
    VideoBatchOrchestrator,
    VideoBatchValidationError,
    CharacterNotFound,
)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeVideoStore:
    def __init__(self):
        self.batches = {}          # id -> dict
        self.items_by_batch = {}   # batch_id -> [row dict]
        self._seq = 0

    async def create_batch(self, character_id, quality_mode, defaults):
        self._seq += 1
        bid = f"batch-{self._seq}"
        self.batches[bid] = {
            "id": bid, "character_id": character_id, "quality_mode": quality_mode,
            "defaults": defaults, "status": "planning", "progress": 0.0,
            "items_total": 0, "items_succeeded": 0, "items_failed": 0, "error": None,
            "created_at": _now(), "updated_at": _now(),
        }
        return VideoBatchRead(**self.batches[bid])

    async def insert_items(self, batch_id, items):
        rows = []
        for i, it in enumerate(items):
            row = dict(it); row["id"] = f"{batch_id}-item-{i}"; row["batch_id"] = batch_id
            rows.append(row)
        self.items_by_batch[batch_id] = rows
        self.batches[batch_id]["items_total"] = len(rows)
        return rows

    async def set_batch_status(self, batch_id, status, error=None):
        self.batches[batch_id]["status"] = status
        if error is not None:
            self.batches[batch_id]["error"] = error

    async def get_batch(self, batch_id):
        b = self.batches.get(batch_id)
        return VideoBatchRead(**b) if b else None

    def rows(self, batch_id):
        return self.items_by_batch.get(batch_id, [])


class FakeCharStore:
    def __init__(self, known=("char-1",)):
        self.known = set(known)

    async def get(self, cid):
        return SimpleNamespace(id=cid) if cid in self.known else None


class FakeImageStore:
    def __init__(self, images):
        self.images = images  # id -> row dict (or None)

    async def get_image(self, image_id):
        return self.images.get(image_id)


class FakeJobManager:
    def __init__(self):
        self.created = []

    async def create_job(self, request, owner, job_type="video_batch"):
        self.created.append((request, owner, job_type))
        return SimpleNamespace(job_id=f"job-{len(self.created)}")


class FakeMotionWriter:
    def __init__(self):
        self.calls = []

    async def interpret(self, text):
        self.calls.append(text)
        return (f"{text}, then a soft smile to the camera", "Custom Move", "venice")


def _settings(**over):
    base = dict(
        VIDEO_BATCH_MAX_INFLIGHT=2,
        VIDEO_BATCH_ITEM_MAX_ATTEMPTS=2,
        RUNPOD_GPU_USD_PER_SECOND=0.0,
        VIDEO_BATCH_EXPLICIT_ENABLED=False,
        COMFYUI_VIDEO_LIGHTNING_WORKFLOW_PATH="workflows/wan_i2v_lightning.json",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _still(character_id="char-1", image_type="gallery"):
    return {
        "character_id": character_id,
        "image_url": "https://x/still.png",
        "image_type": image_type,
        "metadata": {},
    }


def _orch(store=None, images=None, motion_writer=None, settings=None,
          lightning_available=True, job_manager=None):
    return VideoBatchOrchestrator(
        job_manager=job_manager or FakeJobManager(),
        character_store=FakeCharStore(),
        video_batch_store=store or FakeVideoStore(),
        character_image_store=FakeImageStore(images or {"still-a": _still()}),
        motion_writer=motion_writer or FakeMotionWriter(),
        settings=settings or _settings(),
        lightning_available=lightning_available,
    )


def _body(items, **over):
    return VideoBatchCreate(items=items, **over)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_unknown_character_raises():
    async def run():
        orch = _orch()
        with_items = _body([VideoBatchItemCreate(source_image_id="still-a", preset_id="subtle_idle")])
        try:
            await orch.launch_batch("ghost", with_items)
        except CharacterNotFound:
            return
        raise AssertionError("expected CharacterNotFound")
    asyncio.run(run())


def test_source_still_that_is_a_video_is_rejected():
    async def run():
        orch = _orch(images={"vid-1": _still(image_type="video")})
        body = _body([VideoBatchItemCreate(source_image_id="vid-1", preset_id="subtle_idle")])
        try:
            await orch.launch_batch("char-1", body)
        except VideoBatchValidationError as e:
            assert e.status_code == 422
            assert "video" in str(e).lower()
            return
        raise AssertionError("expected a validation error for a video source")
    asyncio.run(run())


def test_source_still_from_another_character_is_rejected():
    async def run():
        orch = _orch(images={"still-x": _still(character_id="char-OTHER")})
        body = _body([VideoBatchItemCreate(source_image_id="still-x", preset_id="subtle_idle")])
        try:
            await orch.launch_batch("char-1", body)
        except VideoBatchValidationError as e:
            assert e.status_code == 404
            return
        raise AssertionError("expected a validation error for a foreign still")
    asyncio.run(run())


def test_missing_source_still_is_rejected():
    async def run():
        orch = _orch(images={})  # get_image returns None
        body = _body([VideoBatchItemCreate(source_image_id="nope", preset_id="subtle_idle")])
        try:
            await orch.launch_batch("char-1", body)
        except VideoBatchValidationError as e:
            assert e.status_code == 404
            return
        raise AssertionError("expected a validation error for a missing still")
    asyncio.run(run())


def test_unknown_preset_id_is_rejected():
    async def run():
        orch = _orch()
        body = _body([VideoBatchItemCreate(source_image_id="still-a", preset_id="does_not_exist")])
        try:
            await orch.launch_batch("char-1", body)
        except VideoBatchValidationError as e:
            assert e.status_code == 422
            assert "unknown preset" in str(e).lower()
            return
        raise AssertionError("expected a validation error for an unknown preset")
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Action snapshots
# ---------------------------------------------------------------------------
def test_preset_item_snapshots_tier_loras_and_motion():
    async def run():
        store = FakeVideoStore()
        orch = _orch(store=store)
        body = _body([VideoBatchItemCreate(source_image_id="still-a", preset_id="subtle_idle")])
        batch, _est = await orch.launch_batch("char-1", body)
        row = store.rows(batch.id)[0]
        preset = get_preset("subtle_idle")
        assert row["action_kind"] == "preset"
        assert row["preset_id"] == "subtle_idle"
        assert row["tier"] == preset.tier.value          # 'charm_idle'
        assert row["motion_text"] == preset.prompt        # catalog snapshot (raw preset text)
        assert row["motion_label"] == preset.label
        assert row["loras"] == resolve_item_loras(preset)  # [] for a non-explicit preset
        assert row["custom_prompt"] is None
        assert row["status"] == "pending"
    asyncio.run(run())


def test_custom_item_interprets_via_motion_writer_at_launch():
    async def run():
        store = FakeVideoStore()
        writer = FakeMotionWriter()
        orch = _orch(store=store, motion_writer=writer)
        body = _body([VideoBatchItemCreate(source_image_id="still-a", custom_prompt="give a slow wink")])
        batch, _est = await orch.launch_batch("char-1", body)
        # MotionWriter.interpret was invoked AT LAUNCH (worker/reconciler stay offline).
        assert writer.calls == ["give a slow wink"]
        row = store.rows(batch.id)[0]
        assert row["action_kind"] == "custom"
        assert row["preset_id"] is None
        assert row["tier"] is None
        assert row["custom_prompt"] == "give a slow wink"
        # The interpreted text (not the raw prompt) is persisted.
        assert row["motion_text"] == "give a slow wink, then a soft smile to the camera"
        assert row["motion_label"] == "Custom Move"
        assert row["loras"] == []
    asyncio.run(run())


def test_custom_item_without_motion_writer_falls_back_to_raw_text():
    async def run():
        store = FakeVideoStore()
        orch = VideoBatchOrchestrator(
            job_manager=FakeJobManager(),
            character_store=FakeCharStore(),
            video_batch_store=store,
            character_image_store=FakeImageStore({"still-a": _still()}),
            motion_writer=None,  # no writer configured
            settings=_settings(),
            lightning_available=True,
        )
        body = _body([VideoBatchItemCreate(source_image_id="still-a", custom_prompt="wave hello")])
        batch, _est = await orch.launch_batch("char-1", body)
        row = store.rows(batch.id)[0]
        assert row["motion_text"] == "wave hello"
        assert row["motion_label"] == "wave hello"[:40]
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Explicit-tier gating
# ---------------------------------------------------------------------------
def test_explicit_rejected_when_flag_disabled():
    async def run():
        orch = _orch(settings=_settings(VIDEO_BATCH_EXPLICIT_ENABLED=False), lightning_available=True)
        body = _body([VideoBatchItemCreate(source_image_id="still-a", preset_id="undress_reveal")])
        try:
            await orch.launch_batch("char-1", body)
        except VideoBatchValidationError as e:
            assert e.status_code == 422
            assert "explicit" in str(e).lower()
            return
        raise AssertionError("explicit item should be rejected when the flag is off")
    asyncio.run(run())


def test_explicit_rejected_when_lightning_unavailable():
    async def run():
        orch = _orch(settings=_settings(VIDEO_BATCH_EXPLICIT_ENABLED=True), lightning_available=False)
        body = _body([VideoBatchItemCreate(source_image_id="still-a", preset_id="undress_reveal")])
        try:
            await orch.launch_batch("char-1", body)
        except VideoBatchValidationError as e:
            assert e.status_code == 422
            assert "lightning" in str(e).lower()
            return
        raise AssertionError("explicit item should be rejected when lightning is unavailable")
    asyncio.run(run())


def test_explicit_accepted_when_enabled_forces_fast_and_snapshots_loras():
    async def run():
        store = FakeVideoStore()
        orch = _orch(store=store, settings=_settings(VIDEO_BATCH_EXPLICIT_ENABLED=True),
                     lightning_available=True)
        # Batch asks for 'max', but an explicit item must be forced to fast (lightning).
        body = _body(
            [VideoBatchItemCreate(source_image_id="still-a", preset_id="undress_reveal")],
            quality_mode="max",
        )
        batch, _est = await orch.launch_batch("char-1", body)
        row = store.rows(batch.id)[0]
        preset = get_preset("undress_reveal")
        assert row["tier"] == "explicit"
        assert row["quality_mode"] == "fast"                 # explicit forces lightning path
        assert row["loras"] == resolve_item_loras(preset)     # the enhancer LoRA snapshot
        assert row["loras"] and row["loras"][0]["name"].endswith("nsfw_wan14b_e15.safetensors")
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Seed strategies
# ---------------------------------------------------------------------------
def _two_item_body(**defaults_over):
    return _body(
        [
            VideoBatchItemCreate(source_image_id="still-a", preset_id="subtle_idle"),
            VideoBatchItemCreate(source_image_id="still-b", preset_id="wave"),
        ],
        defaults=VideoBatchDefaults(**defaults_over),
    )


def _two_still_images():
    return {"still-a": _still(), "still-b": _still()}


def test_seed_strategy_fixed_same_seed_for_all():
    async def run():
        store = FakeVideoStore()
        orch = _orch(store=store, images=_two_still_images())
        body = _two_item_body(seed_strategy=SeedStrategy.FIXED, base_seed=1000)
        batch, _est = await orch.launch_batch("char-1", body)
        seeds = [r["seed"] for r in store.rows(batch.id)]
        assert seeds == [1000, 1000]
    asyncio.run(run())


def test_seed_strategy_per_item_is_derived_deterministically():
    async def run():
        store = FakeVideoStore()
        orch = _orch(store=store, images=_two_still_images())
        body = _two_item_body(seed_strategy=SeedStrategy.PER_ITEM, base_seed=1000)
        batch, _est = await orch.launch_batch("char-1", body)
        seeds = [r["seed"] for r in store.rows(batch.id)]
        # ((base + index*7919) % 1e9) or 1  ->  index0=1000, index1=8919.
        assert seeds == [1000, 8919]
    asyncio.run(run())


def test_seed_strategy_random_leaves_seed_none():
    async def run():
        store = FakeVideoStore()
        orch = _orch(store=store, images=_two_still_images())
        body = _two_item_body(seed_strategy=SeedStrategy.RANDOM)
        batch, _est = await orch.launch_batch("char-1", body)
        seeds = [r["seed"] for r in store.rows(batch.id)]
        assert seeds == [None, None]  # worker picks; reported back later
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Dry-run vs real + estimate
# ---------------------------------------------------------------------------
def test_dry_run_plans_without_enqueue_and_returns_estimate():
    async def run():
        store = FakeVideoStore()
        jm = FakeJobManager()
        orch = _orch(store=store, job_manager=jm)
        body = _body(
            [VideoBatchItemCreate(source_image_id="still-a", preset_id="subtle_idle")],
            dry_run=True,
        )
        batch, estimate = await orch.launch_batch("char-1", body)
        assert batch.status == "planned"
        # launch never enqueues (the reconciler owns enqueueing); doubly true for dry-run.
        assert jm.created == []
        assert estimate.items_total == 1
        # items are still persisted as pending so the plan is previewable.
        assert store.rows(batch.id)[0]["status"] == "pending"
    asyncio.run(run())


def test_real_run_flips_to_running_without_enqueue():
    async def run():
        store = FakeVideoStore()
        jm = FakeJobManager()
        orch = _orch(store=store, job_manager=jm)
        body = _body([VideoBatchItemCreate(source_image_id="still-a", preset_id="subtle_idle")])
        batch, estimate = await orch.launch_batch("char-1", body)
        assert batch.status == "running"
        assert jm.created == []  # enqueue is the reconciler's job, not launch's
        assert estimate.items_total == 1
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
