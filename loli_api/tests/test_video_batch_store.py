"""
Tests for VideoBatchStore (services/video_batch_store.py) against an in-memory
fake of the supabase-py PostgREST client (chainable
table().insert/select/update.eq/in_/limit/order.execute).

Covers the CRUD surface the orchestrator/reconciler lean on plus the two
subtle reset contracts and the aggregate status derivation:
  * reset_item_for_retry clears the job/runpod/error fields -> pending but KEEPS
    attempts (the retry cap still applies across dispatches);
  * reset_item_for_rerun ALSO clears the publish guards + stale URLs and RESETS
    attempts to 0;
  * update_batch_aggregate: all succeeded -> completed, mix -> partial,
    all failed -> failed, any non-terminal -> running.

Runs under pytest or directly: python loli_api/tests/test_video_batch_store.py
"""
import asyncio
import itertools
from datetime import datetime, timedelta, timezone

from services.video_batch_store import VideoBatchStore


# ---------------------------------------------------------------------------
# In-memory PostgREST-style fake.
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table):
        self._table = table
        self._op = None
        self._payload = None
        self._eq = []       # list of (col, value)
        self._in = []       # list of (col, [values])
        self._limit = None
        self._order = None
        self._order_desc = False

    # -- builders --
    def insert(self, records):
        self._op, self._payload = "insert", records
        return self

    def update(self, fields):
        self._op, self._payload = "update", fields
        return self

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def eq(self, col, val):
        self._eq.append((col, val))
        return self

    def in_(self, col, vals):
        self._in.append((col, list(vals)))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, col, desc=False):
        self._order, self._order_desc = col, desc
        return self

    def execute(self):
        return self._table._execute(self)


class _FakeTable:
    def __init__(self, db, name):
        self._db = db
        self._name = name

    @property
    def _rows(self):
        return self._db.data.setdefault(self._name, [])

    def _matches(self, row, q):
        for col, val in q._eq:
            if row.get(col) != val:
                return False
        for col, vals in q._in:
            if row.get(col) not in vals:
                return False
        return True

    def _execute(self, q):
        if q._op == "insert":
            records = q._payload if isinstance(q._payload, list) else [q._payload]
            inserted = []
            for rec in records:
                row = dict(rec)
                row.setdefault("id", f"{self._name}-{next(self._db.ids)}")
                stamp = self._db.next_stamp()
                row.setdefault("created_at", stamp)
                row.setdefault("updated_at", stamp)
                self._rows.append(row)
                inserted.append(dict(row))
            return _Result(inserted)

        if q._op == "update":
            updated = []
            for row in self._rows:
                if self._matches(row, q):
                    row.update(q._payload)
                    row["updated_at"] = self._db.next_stamp()
                    updated.append(dict(row))
            return _Result(updated)

        # select
        rows = [dict(r) for r in self._rows if self._matches(r, q)]
        if q._order:
            rows.sort(key=lambda r: r.get(q._order), reverse=q._order_desc)
        if q._limit is not None:
            rows = rows[: q._limit]
        return _Result(rows)


class _FakeClient:
    def __init__(self):
        self.data = {}
        self.ids = itertools.count(1)
        self._clock = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def next_stamp(self):
        self._clock += timedelta(seconds=1)
        return self._clock

    def table(self, name):
        # supabase-py's client.table(name) returns the query builder itself
        # (with .insert/.select/.update on it), so mirror that.
        return _Query(_FakeTable(self, name))


def _store():
    return VideoBatchStore(_FakeClient())


def _item_row(index, **overrides):
    row = {
        "item_index": index,
        "source_image_id": f"still-{index}",
        "source_image_url": f"https://x/still-{index}.png",
        "action_kind": "preset",
        "preset_id": "subtle_idle",
        "custom_prompt": None,
        "tier": "charm_idle",
        "motion_text": "subtle idle motion, at the camera",
        "motion_label": "Subtle Idle",
        "loras": [],
        "quality_mode": "fast",
        "width": 480, "height": 832, "length": 81, "fps": 16,
        "seed": 100 + index,
        "negative_prompt": None,
        "status": "pending",
        "attempts": 0,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def test_create_batch_and_get():
    async def run():
        store = _store()
        batch = await store.create_batch("char-1", "fast", {"interpolate": True})
        assert batch.character_id == "char-1"
        assert batch.quality_mode == "fast"
        assert batch.status == "planning"
        assert batch.defaults == {"interpolate": True}
        again = await store.get_batch(batch.id)
        assert again is not None and again.id == batch.id
        assert await store.get_batch("does-not-exist") is None
    asyncio.run(run())


def test_insert_items_sets_total_and_lists_sorted():
    async def run():
        store = _store()
        batch = await store.create_batch("char-1", "fast", {})
        # Insert out of order; list must come back sorted by item_index.
        await store.insert_items(batch.id, [_item_row(2), _item_row(0), _item_row(1)])
        items = await store.list_items(batch.id)
        assert [i.item_index for i in items] == [0, 1, 2]
        # items_total was written back onto the batch.
        refreshed = await store.get_batch(batch.id)
        assert refreshed.items_total == 3
    asyncio.run(run())


def test_list_batches_scoped_and_newest_first():
    async def run():
        store = _store()
        b1 = await store.create_batch("char-1", "fast", {})
        b2 = await store.create_batch("char-1", "max", {})
        await store.create_batch("char-2", "fast", {})
        scoped = await store.list_batches(character_id="char-1")
        assert {b.id for b in scoped} == {b1.id, b2.id}
        # order created_at desc -> the later insert (b2) leads.
        assert scoped[0].id == b2.id
        assert len(await store.list_batches()) == 3
    asyncio.run(run())


def test_update_item_and_get_item():
    async def run():
        store = _store()
        batch = await store.create_batch("char-1", "fast", {})
        [item] = await store.insert_items(batch.id, [_item_row(0)])
        await store.update_item(item.id, status="running", runpod_status="IN_PROGRESS")
        got = await store.get_item(item.id)
        assert got.status == "running"
        assert got.runpod_status == "IN_PROGRESS"
    asyncio.run(run())


def test_update_item_by_runpod_id_targets_the_right_row():
    async def run():
        store = _store()
        batch = await store.create_batch("char-1", "fast", {})
        rows = await store.insert_items(
            batch.id,
            [
                _item_row(0, runpod_request_id="rp-A", status="running"),
                _item_row(1, runpod_request_id="rp-B", status="running"),
            ],
        )
        await store.update_item_by_runpod_id("rp-B", status="succeeded", video_url="u")
        by_id = {i.item_index: i for i in await store.list_items(batch.id)}
        assert by_id[1].status == "succeeded" and by_id[1].video_url == "u"
        assert by_id[0].status == "running"  # rp-A untouched
        # sanity: the ids differ, we really targeted by runpod handle
        assert rows[0].id != rows[1].id
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Reset contracts
# ---------------------------------------------------------------------------
def test_reset_item_for_retry_clears_runpod_and_errors_keeps_attempts():
    async def run():
        store = _store()
        batch = await store.create_batch("char-1", "fast", {})
        [item] = await store.insert_items(
            batch.id,
            [_item_row(
                0,
                status="failed",
                job_id="job-1",
                runpod_request_id="rp-1",
                runpod_status="FAILED",
                error_code="VIDEO_RUNPOD_FAILED",
                error_message="boom",
                attempts=1,
                character_image_id="cimg-1",
                action_id="act-1",
            )],
        )
        await store.reset_item_for_retry(item.id)
        row = await store.get_item_row(item.id)
        assert row["status"] == "pending"
        assert row["job_id"] is None
        assert row["runpod_request_id"] is None
        assert row["runpod_status"] is None
        assert row["error_code"] is None
        assert row["error_message"] is None
        # attempts is preserved so the retry cap keeps applying across dispatches.
        assert row["attempts"] == 1
        # publish guards are NOT part of the retry reset (only rerun clears those).
        assert row["character_image_id"] == "cimg-1"
        assert row["action_id"] == "act-1"
    asyncio.run(run())


def test_reset_item_for_rerun_clears_publish_guards_and_resets_attempts():
    async def run():
        store = _store()
        batch = await store.create_batch("char-1", "fast", {})
        [item] = await store.insert_items(
            batch.id,
            [_item_row(
                0,
                status="succeeded",
                runpod_request_id="rp-1",
                runpod_status="COMPLETED",
                attempts=2,
                character_image_id="cimg-1",
                action_id="act-1",
                video_url="https://x/clip.mp4",
                preview_url="https://x/clip.mp4",
                seed=555,
            )],
        )
        await store.reset_item_for_rerun(item.id)
        row = await store.get_item_row(item.id)
        assert row["status"] == "pending"
        assert row["character_image_id"] is None
        assert row["action_id"] is None
        assert row["video_url"] is None
        assert row["preview_url"] is None
        assert row["attempts"] == 0            # rerun resets the cap
        assert row["seed"] == 555              # seed kept when not overridden
    asyncio.run(run())


def test_reset_item_for_rerun_can_override_seed_and_action():
    async def run():
        store = _store()
        batch = await store.create_batch("char-1", "fast", {})
        [item] = await store.insert_items(
            batch.id, [_item_row(0, status="failed", seed=1)]
        )
        new_action = {
            "action_kind": "custom",
            "preset_id": None,
            "custom_prompt": "give a slow wave",
            "tier": None,
            "motion_text": "waving slowly at the camera",
            "motion_label": "Slow Wave",
            "loras": [],
        }
        await store.reset_item_for_rerun(item.id, seed=999, action=new_action)
        row = await store.get_item_row(item.id)
        assert row["seed"] == 999
        assert row["action_kind"] == "custom"
        assert row["custom_prompt"] == "give a slow wave"
        assert row["motion_text"] == "waving slowly at the camera"
        assert row["motion_label"] == "Slow Wave"
        assert row["preset_id"] is None
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Aggregate status derivation
# ---------------------------------------------------------------------------
async def _batch_with_items(store, statuses):
    batch = await store.create_batch("char-1", "fast", {})
    rows = [_item_row(i, status=s) for i, s in enumerate(statuses)]
    await store.insert_items(batch.id, rows)
    return batch


def test_aggregate_all_succeeded_completed():
    async def run():
        store = _store()
        batch = await _batch_with_items(store, ["succeeded", "succeeded"])
        agg = await store.update_batch_aggregate(batch.id)
        assert agg.status == "completed"
        assert agg.items_total == 2
        assert agg.items_succeeded == 2
        assert agg.items_failed == 0
        assert agg.progress == 1.0
    asyncio.run(run())


def test_aggregate_mix_partial():
    async def run():
        store = _store()
        batch = await _batch_with_items(store, ["succeeded", "failed"])
        agg = await store.update_batch_aggregate(batch.id)
        assert agg.status == "partial"
        assert agg.items_succeeded == 1
        assert agg.items_failed == 1
    asyncio.run(run())


def test_aggregate_all_failed_failed():
    async def run():
        store = _store()
        batch = await _batch_with_items(store, ["failed", "failed"])
        agg = await store.update_batch_aggregate(batch.id)
        assert agg.status == "failed"
        assert agg.items_failed == 2
    asyncio.run(run())


def test_aggregate_any_non_terminal_running():
    async def run():
        store = _store()
        # one still in-flight -> the whole batch is 'running' regardless of the rest.
        batch = await _batch_with_items(store, ["succeeded", "running", "failed"])
        agg = await store.update_batch_aggregate(batch.id)
        assert agg.status == "running"
        assert agg.progress < 1.0
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
