"""
Phase 3 — single-photo edit + rerun.

Covers:
  * PATCH validation via story_planner.apply_item_scene_edit (blocked outfit -> 422,
    nudity above max_nudity -> 422, free-text scrub, valid edit applied);
  * the PATCH / rerun endpoints' 404/409/422 gating (pending item is not editable);
  * BatchOrchestrator.rerun_item state machine (completed batch -> running, counters
    stay consistent, seed kept vs reseeded, previous gallery image superseded);
  * the reconciler re-enqueues a rerun (now-pending) item via _enqueue_item.

Runs under pytest or directly: python loli_api/tests/test_batch_item_rerun.py
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

# The reconcile-enqueue test builds a PipelineEditRequest whose source_image is
# SSRF-validated; this test exercises the rerun feature, not the allowlist, so make
# the validator a passthrough (mirrors tests/test_nude_base.py).
import models.requests as _mr
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import NudityLevel, OutfitType, LocationType, PoseType
from models.batch import BatchControls, BatchItemEdit, BatchItemRerun
from models.scene import SceneSpec
from services import story_planner
from services import scene_vocab as sv
from services.batch_store import _row_to_item, _row_to_batch
from services.batch_orchestrator import BatchOrchestrator, BatchReconciler
from api.v1.endpoints import batches as ep


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _scene_spec(**overrides):
    base = dict(
        arc_id="morning", arc_title="Slow morning", beat_index=0, global_index=0,
        beat_description="by the window", outfit=OutfitType.COCKTAIL_DRESS,
        nudityLevel=NudityLevel.LOW, location=LocationType.HOME_BEDROOM,
    )
    base.update(overrides)
    return SceneSpec(**base).model_dump(mode="json")


def _batch_row(status="completed", controls=None, **overrides):
    now = datetime.now(timezone.utc)
    row = dict(
        id="b1", character_id="c1", count=2,
        controls=(controls or BatchControls()).model_dump(mode="json"),
        likes=[], dislikes=[], status=status, progress=1.0,
        items_total=2, items_succeeded=2, items_failed=0, error=None,
        created_at=now, updated_at=now,
    )
    row.update(overrides)
    return row


def _item_row(item_id="i1", status="succeeded", seed=100, character_image_id="img-1", **overrides):
    row = dict(
        id=item_id, batch_id="b1", scene_index=0, status=status,
        scene_spec=_scene_spec(), job_id=None, preview_url="https://x/p.png",
        image_url="https://x/i.png", image_hash="hash", seed=seed, arc="morning",
        beat=0, attempts=1, error_code=None, error_message=None,
        character_image_id=character_image_id,
    )
    row.update(overrides)
    return row


class _FakeStore:
    """In-memory BatchStore double operating on raw dict rows (uses the real
    _row_to_* mappers, so it mirrors the production projection faithfully)."""

    def __init__(self, batch_row, item_rows):
        self.batch = batch_row
        self.items = {r["id"]: r for r in item_rows}

    async def get_batch(self, batch_id):
        return _row_to_batch(self.batch) if self.batch["id"] == batch_id else None

    async def get_item(self, item_id, batch_id=None):
        r = self.items.get(item_id)
        if r is None or (batch_id is not None and r["batch_id"] != batch_id):
            return None
        return _row_to_item(r)

    async def update_item_scene_spec(self, item_id, scene_spec):
        self.items[item_id]["scene_spec"] = scene_spec

    async def reset_item_for_rerun(self, item_id, seed=None):
        r = self.items[item_id]
        r.update(
            status="pending", job_id=None, error_code=None, error_message=None,
            character_image_id=None, preview_url=None, image_url=None,
            image_hash=None, attempts=0,
        )
        if seed is not None:
            r["seed"] = seed

    async def set_batch_status(self, batch_id, status, error=None):
        self.batch["status"] = status

    async def update_batch_aggregate(self, batch_id):
        items = list(self.items.values())
        total = len(items)
        succeeded = sum(1 for i in items if i["status"] == "succeeded")
        failed = sum(1 for i in items if i["status"] == "failed")
        cancelled = sum(1 for i in items if i["status"] == "cancelled")
        done = succeeded + failed + cancelled
        if total == 0:
            st = "planning"
        elif done < total:
            st = "running"
        elif cancelled and (succeeded + failed) == 0:
            st = "cancelled"
        elif failed == 0:
            st = "completed"
        elif succeeded == 0:
            st = "failed"
        else:
            st = "partial"
        self.batch.update(
            items_total=total, items_succeeded=succeeded, items_failed=failed,
            progress=done / total if total else 0.0, status=st,
        )
        return _row_to_batch(self.batch)


class _FakeImageStore:
    def __init__(self):
        self.deleted = []

    async def delete_image(self, character_id, image_id):
        self.deleted.append((character_id, image_id))
        return {"id": image_id}


# --------------------------------------------------------------------------- #
# 1. apply_item_scene_edit — validation + scrub                                #
# --------------------------------------------------------------------------- #
def test_edit_blocked_outfit_rejected():
    controls = BatchControls(blocked_outfits=[OutfitType.BIKINI])
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"outfit": "bikini"}, controls)


def test_edit_outfit_not_in_allowlist_rejected():
    controls = BatchControls(allowed_outfits=[OutfitType.COCKTAIL_DRESS])
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"outfit": "business_suit"}, controls)


def test_edit_nudity_above_max_rejected():
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM)
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"nudity_level": "high"}, controls)


def test_edit_nudity_at_max_allowed():
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, blocked_outfits=[])
    updated = story_planner.apply_item_scene_edit(_scene_spec(), {"nudity_level": "medium"}, controls)
    assert updated.nudityLevel == NudityLevel.MEDIUM


def test_edit_sfw_only_blocks_nudity_and_naked():
    controls = BatchControls(sfw_only=True)
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"nudity_level": "medium"}, controls)
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"outfit": "naked"}, controls)


def test_edit_blocked_pose_and_location_rejected():
    controls = BatchControls(
        blocked_poses=[PoseType.ALL_FOURS], blocked_locations=[LocationType.BEACH]
    )
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"pose": "all_fours"}, controls)
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"location": "beach"}, controls)


def test_edit_invalid_enum_value_rejected():
    with pytest.raises(story_planner.SceneEditError):
        story_planner.apply_item_scene_edit(_scene_spec(), {"location": "moon_base"}, BatchControls())


def test_edit_freetext_is_scrubbed():
    # Identity tokens + a companion tail must be stripped from the stored fields.
    edit = {
        "activity": "dancing with a partner",
        "setting": "a sunlit loft, a blonde woman by the window",
        "expression": "soft smile with parted lips",
    }
    updated = story_planner.apply_item_scene_edit(_scene_spec(), edit, BatchControls())
    assert "partner" not in (updated.activity or "").lower()
    assert "blonde" not in (updated.setting or "").lower()
    assert "woman" not in (updated.setting or "").lower()
    assert "lips" not in (updated.expression or "").lower()


def test_edit_applies_valid_enum_and_clears_nullable():
    controls = BatchControls(blocked_outfits=[])
    updated = story_planner.apply_item_scene_edit(
        _scene_spec(pose=PoseType.SITTING),
        {"location": "cafe", "outfit": "velvet_dress", "pose": None},
        controls,
    )
    assert updated.location == LocationType.CAFE
    assert updated.outfit == OutfitType.VELVET_DRESS
    assert updated.pose is None


def test_edit_near_miss_enum_repaired():
    # difflib repair, same as the planner: "cocktaildress" -> cocktail_dress.
    updated = story_planner.apply_item_scene_edit(
        _scene_spec(), {"location": "home_kitchen"}, BatchControls()
    )
    assert updated.location == LocationType.HOME_KITCHEN


_STALE_DIRECTION = "A blurred crowd fills the neon-lit floor behind the low booth."


def test_edit_fact_change_clears_stale_scene_direction():
    # A location change invalidates a Venice direction authored for the OLD place (it names a
    # crowd that only made sense at the nightclub) -> both direction fields are cleared, so the
    # mapper falls back to the freshly re-derived staging.
    stored = _scene_spec(
        pose=PoseType.SITTING, location=LocationType.NIGHTCLUB,
        staging="perched on a bar stool at the counter",
        scene_direction=_STALE_DIRECTION, direction_source="venice",
    )
    updated = story_planner.apply_item_scene_edit(
        stored, {"location": "home_bedroom"}, BatchControls()
    )
    assert updated.location == LocationType.HOME_BEDROOM
    assert updated.scene_direction is None
    assert updated.direction_source is None


def test_edit_fact_change_restages_from_new_location_deterministically():
    # Staging is re-derived from the NEW (location, pose) and stays class-coherent (a sitting
    # scene draws a sitting anchor from the new location's pool), never the stale phrase.
    stored = _scene_spec(
        pose=PoseType.SITTING, location=LocationType.NIGHTCLUB,
        staging="perched on a bar stool at the counter",
    )
    updated = story_planner.apply_item_scene_edit(
        stored, {"location": "home_bedroom"}, BatchControls()
    )
    options = sv.staging_options(LocationType.HOME_BEDROOM, PoseType.SITTING)
    assert updated.staging in options
    assert updated.staging != "perched on a bar stool at the counter"
    # No RNG -> a repeated identical edit yields the exact same staging.
    again = story_planner.apply_item_scene_edit(
        stored, {"location": "home_bedroom"}, BatchControls()
    )
    assert again.staging == updated.staging


def test_edit_pose_change_restages_to_new_pose_class():
    # Changing the POSE re-derives staging into the NEW pose-class's pool at the same location.
    stored = _scene_spec(
        pose=PoseType.SITTING, location=LocationType.HOME_BEDROOM,
        staging="sitting on the edge of the bed",
    )
    updated = story_planner.apply_item_scene_edit(
        stored, {"pose": "lying_back"}, BatchControls()
    )
    assert sv.pose_class(updated.pose) == sv.POSE_CLASS_LYING
    assert updated.staging in sv.staging_options(LocationType.HOME_BEDROOM, PoseType.LYING_BACK)


def test_edit_clearing_pose_drops_staging():
    # Clearing the pose (no pose step) buckets to OTHER -> no staging anchor.
    stored = _scene_spec(
        pose=PoseType.SITTING, location=LocationType.HOME_BEDROOM,
        staging="sitting on the edge of the bed",
    )
    updated = story_planner.apply_item_scene_edit(stored, {"pose": None}, BatchControls())
    assert updated.pose is None
    assert updated.staging is None


def test_edit_freetext_only_leaves_direction_and_staging_untouched():
    # An expression-only (non-fact) edit must NOT clear the direction or re-derive staging.
    stored = _scene_spec(
        pose=PoseType.SITTING, location=LocationType.NIGHTCLUB,
        staging="perched on a bar stool at the counter",
        scene_direction=_STALE_DIRECTION, direction_source="venice",
    )
    updated = story_planner.apply_item_scene_edit(
        stored, {"expression": "a soft knowing smile"}, BatchControls()
    )
    assert updated.staging == "perched on a bar stool at the counter"
    assert updated.scene_direction == _STALE_DIRECTION
    assert updated.direction_source == "venice"
    assert "soft knowing smile" in (updated.expression or "").lower()


# --------------------------------------------------------------------------- #
# 2. PATCH / rerun endpoint gating                                             #
# --------------------------------------------------------------------------- #
def _wire(store, orchestrator=None):
    ep.set_batch_store(store)
    ep.set_orchestrator(orchestrator or SimpleNamespace())


def test_patch_endpoint_blocked_outfit_422():
    controls = BatchControls(blocked_outfits=[OutfitType.BIKINI])
    store = _FakeStore(_batch_row(controls=controls), [_item_row()])
    _wire(store)
    with pytest.raises(ep.HTTPException) as ei:
        asyncio.run(ep.edit_batch_item("b1", "i1", BatchItemEdit(outfit="bikini"), user={}))
    assert ei.value.status_code == 422


def test_patch_endpoint_pending_item_409():
    store = _FakeStore(_batch_row(status="running"), [_item_row(status="pending")])
    _wire(store)
    with pytest.raises(ep.HTTPException) as ei:
        asyncio.run(ep.edit_batch_item("b1", "i1", BatchItemEdit(location="cafe"), user={}))
    assert ei.value.status_code == 409


def test_patch_endpoint_unknown_item_404():
    store = _FakeStore(_batch_row(), [_item_row()])
    _wire(store)
    with pytest.raises(ep.HTTPException) as ei:
        asyncio.run(ep.edit_batch_item("b1", "nope", BatchItemEdit(location="cafe"), user={}))
    assert ei.value.status_code == 404


def test_patch_endpoint_success_persists_scene_spec():
    store = _FakeStore(_batch_row(), [_item_row()])
    _wire(store)
    result = asyncio.run(
        ep.edit_batch_item("b1", "i1", BatchItemEdit(location="cafe"), user={})
    )
    assert result.scene_spec["location"] == "cafe"
    assert store.items["i1"]["scene_spec"]["location"] == "cafe"


def test_rerun_endpoint_pending_item_409():
    store = _FakeStore(_batch_row(status="running"), [_item_row(status="pending")])
    orch = BatchOrchestrator(None, None, store, SimpleNamespace())
    _wire(store, orch)
    with pytest.raises(ep.HTTPException) as ei:
        asyncio.run(ep.rerun_batch_item("b1", "i1", BatchItemRerun(), user={}))
    assert ei.value.status_code == 409


# --------------------------------------------------------------------------- #
# 3. rerun_item state machine                                                  #
# --------------------------------------------------------------------------- #
def test_rerun_flips_completed_batch_to_running_and_resets_item():
    store = _FakeStore(_batch_row(status="completed"), [_item_row(), _item_row(item_id="i2")])
    images = _FakeImageStore()
    orch = BatchOrchestrator(None, None, store, SimpleNamespace(), character_image_store=images)

    batch = asyncio.run(orch.rerun_item("b1", "i1", seed=None))

    # batch reopened, counters recomputed consistently (one item now pending).
    assert batch.status == "running"
    assert batch.items_succeeded == 1  # i2 still succeeded, i1 dropped out
    assert batch.items_failed == 0
    assert store.items["i1"]["status"] == "pending"
    assert store.items["i1"]["character_image_id"] is None
    assert store.items["i1"]["image_url"] is None
    # previous gallery image superseded (deleted) so the rerun replaces it.
    assert images.deleted == [("c1", "img-1")]


def test_rerun_keeps_stored_seed_by_default():
    store = _FakeStore(_batch_row(), [_item_row(seed=555)])
    orch = BatchOrchestrator(None, None, store, SimpleNamespace(), character_image_store=_FakeImageStore())
    asyncio.run(orch.rerun_item("b1", "i1", seed=None))
    assert store.items["i1"]["seed"] == 555  # unchanged


def test_rerun_applies_new_seed():
    store = _FakeStore(_batch_row(), [_item_row(seed=555)])
    orch = BatchOrchestrator(None, None, store, SimpleNamespace(), character_image_store=_FakeImageStore())
    asyncio.run(orch.rerun_item("b1", "i1", seed=999))
    assert store.items["i1"]["seed"] == 999


def test_rerun_endpoint_reseed_changes_seed():
    store = _FakeStore(_batch_row(), [_item_row(seed=555)])
    orch = BatchOrchestrator(None, None, store, SimpleNamespace(), character_image_store=_FakeImageStore())
    _wire(store, orch)
    asyncio.run(ep.rerun_batch_item("b1", "i1", BatchItemRerun(reseed=True), user={}))
    assert store.items["i1"]["seed"] != 555
    assert 1 <= store.items["i1"]["seed"] <= 1_000_000_000


def test_rerun_endpoint_explicit_new_seed():
    store = _FakeStore(_batch_row(), [_item_row(seed=555)])
    orch = BatchOrchestrator(None, None, store, SimpleNamespace(), character_image_store=_FakeImageStore())
    _wire(store, orch)
    asyncio.run(ep.rerun_batch_item("b1", "i1", BatchItemRerun(new_seed=4242), user={}))
    assert store.items["i1"]["seed"] == 4242


def test_rerun_missing_batch_returns_none():
    store = _FakeStore(_batch_row(), [_item_row()])
    orch = BatchOrchestrator(None, None, store, SimpleNamespace(), character_image_store=_FakeImageStore())
    assert asyncio.run(orch.rerun_item("nope", "i1")) is None


# --------------------------------------------------------------------------- #
# 4. reconciler re-enqueues the now-pending rerun item                         #
# --------------------------------------------------------------------------- #
class _ReconcileStore:
    """Minimal store for a single running batch with one pending item."""

    def __init__(self, item_row):
        self.item = item_row
        self.updates = []

    async def list_items(self, batch_id, statuses=None):
        return [_row_to_item(self.item)]

    async def update_item_result(self, item_id, **fields):
        self.updates.append((item_id, fields))
        self.item.update(fields)

    async def update_batch_aggregate(self, batch_id):
        return None

    async def _get_item(self, item_id):
        return self.item


class _CaptureJobManager:
    def __init__(self):
        self.requests = []

    async def get_job(self, job_id):
        return None

    async def create_job(self, request, owner, job_type="text_to_image"):
        self.requests.append(request)
        return SimpleNamespace(job_id=f"batjob_{len(self.requests)}")


class _CharStore:
    async def get(self, cid):
        return SimpleNamespace(
            id="c1",
            persona=_persona(),
            hero_image_url="https://x.supabase.co/hero.png",
        )


def _persona():
    from models.requests import PersonaOptions
    return PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation="nurse",
    )


def test_reconciler_reenqueues_rerun_item():
    # An item reset by a rerun is 'pending' with no job_id; the reconcile loop must
    # enqueue it exactly like any other pending item (via _enqueue_item -> create_job).
    item = _item_row(status="pending", job_id=None, character_image_id=None, seed=321)
    store = _ReconcileStore(item)
    jm = _CaptureJobManager()
    rec = BatchReconciler(
        job_manager=jm, character_store=_CharStore(), batch_store=store,
        settings=SimpleNamespace(
            BATCH_MAX_INFLIGHT=3, BATCH_ITEM_MAX_ATTEMPTS=2, RUNPOD_POLL_INTERVAL_SECONDS=1
        ),
    )
    batch = SimpleNamespace(
        id="b1", character_id="c1", status="running",
        controls=BatchControls(), likes=[], dislikes=[],
    )
    asyncio.run(rec._reconcile_batch(batch, {}, {}))

    assert jm.requests, "the rerun (pending) item should have been enqueued"
    assert jm.requests[0].seed == 321  # the rerun seed carries through to the job
    # item transitioned pending -> queued with a job id
    assert any(f.get("status") == "queued" for _, f in store.updates)


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
        else:
            pass
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
