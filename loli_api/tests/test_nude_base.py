"""
Tests for the per-character nude-base feature:

  * NudeBaseStore round-trips against the character_nude_bases table (fake Supabase
    client): create (pending), get_active_url (status-scoped), update_status.
  * POST /nude-base builds the correct NAKED / high-nudity outfit_edit job and records
    a pending base row (mock job_manager + stores).
  * GET /nude-base reconcile-on-read finalizes the base when its job has succeeded /
    failed, and stays pending while the job is still running.
  * BatchReconciler activation: the enqueued scene edits source from the nude base when
    one exists, and fall back to the clothed hero when it does not / the store is
    unwired (back-compat).

Runs under pytest or directly: python loli_api/tests/test_nude_base.py
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

# The endpoint + mapper build requests whose source_image is SSRF-validated; these
# tests exercise feature logic, not the allowlist, so make the validator a passthrough.
import models.requests as _mr
_mr.validate_source_image = lambda u: u  # type: ignore

from config import settings
from models.enums import JobStatus, NudityLevel, OutfitType, LocationType
from models.nude_base import NudeBaseRead
from models.requests import PersonaOptions
from models.batch import BatchControls
from models.scene import SceneSpec
from services.nude_base_store import NudeBaseStore
from services.batch_orchestrator import BatchReconciler
from api.v1.endpoints import nude_base as ep
from api.v1.endpoints import pipeline as pipeline_ep


# ---------------------------------------------------------------------------
# Fake Supabase client (mirrors tests/test_batch_store.py)
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, client, rec):
        self.client = client
        self.rec = rec

    def select(self, *a):
        self.rec["op"] = "select"
        return self

    def insert(self, payload):
        self.rec["op"] = "insert"
        self.rec["payload"] = payload
        return self

    def update(self, payload):
        self.rec["op"] = "update"
        self.rec["payload"] = payload
        return self

    def eq(self, k, v):
        self.rec["eqs"].append((k, v))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _FakeResp(self.client.data_for(self.rec["table"]))


class _FakeClient:
    def __init__(self, default_data=None, table_data=None):
        self.calls = []
        self.default_data = default_data if default_data is not None else []
        self.table_data = table_data or {}

    def data_for(self, table):
        return self.table_data.get(table, self.default_data)

    def table(self, name):
        rec = {"table": name, "eqs": []}
        self.calls.append(rec)
        return _FakeQuery(self, rec)

    def calls_for(self, table):
        return [c for c in self.calls if c["table"] == table]


_NUDE_ROW = {
    "id": "nb1",
    "character_id": "c1",
    "source_image_url": "https://x.supabase.co/hero.png",
    "image_url": None,
    "image_hash": None,
    "job_id": "outjob_abc",
    "status": "pending",
    "error": None,
    "created_at": "2026-07-09T00:00:00Z",
    "updated_at": "2026-07-09T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Storage round-trip
# ---------------------------------------------------------------------------
def test_create_targets_character_nude_bases_pending():
    client = _FakeClient(default_data=[_NUDE_ROW])
    store = NudeBaseStore(client)
    nb = asyncio.run(store.create("c1", job_id="outjob_abc", source_image_url="https://x.supabase.co/hero.png"))

    calls = client.calls_for("character_nude_bases")
    assert calls, "insert must target character_nude_bases"
    payload = calls[0]["payload"]
    assert payload["character_id"] == "c1"
    assert payload["job_id"] == "outjob_abc"
    assert payload["source_image_url"] == "https://x.supabase.co/hero.png"
    assert payload["status"] == "pending"
    assert "owner_id" not in payload  # loli-api-owned table, no owner scoping
    assert nb.status == "pending"
    assert nb.job_id == "outjob_abc"


def test_get_active_url_is_status_scoped_to_succeeded():
    client = _FakeClient(table_data={"character_nude_bases": [{"image_url": "https://x/nude.png"}]})
    store = NudeBaseStore(client)
    url = asyncio.run(store.get_active_url("c1"))
    assert url == "https://x/nude.png"
    eqs = client.calls_for("character_nude_bases")[0]["eqs"]
    assert ("character_id", "c1") in eqs
    assert ("status", "succeeded") in eqs  # never returns a pending/failed row


def test_get_active_url_none_when_no_succeeded_row():
    client = _FakeClient(default_data=[])
    store = NudeBaseStore(client)
    assert asyncio.run(store.get_active_url("c1")) is None


def test_update_status_succeeded_writes_image_url():
    succeeded = dict(_NUDE_ROW, status="succeeded", image_url="https://x/nude.png", image_hash="h")
    client = _FakeClient(default_data=[succeeded])
    store = NudeBaseStore(client)
    nb = asyncio.run(store.update_status("nb1", "succeeded", image_url="https://x/nude.png", image_hash="h"))
    payload = client.calls_for("character_nude_bases")[0]["payload"]
    assert payload == {"status": "succeeded", "image_url": "https://x/nude.png", "image_hash": "h"}
    assert nb.image_url == "https://x/nude.png"


# ---------------------------------------------------------------------------
# Endpoint fakes
# ---------------------------------------------------------------------------
def _persona():
    return PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation="nurse",
    )


def _character(hero="https://x.supabase.co/hero.png"):
    return SimpleNamespace(id="c1", persona=_persona(), hero_image_url=hero)


def _nb_row(status="pending", job_id="outjob_abc", image_url=None, error=None):
    now = datetime.now(timezone.utc)
    return NudeBaseRead(
        id="nb1", character_id="c1", source_image_url="https://x.supabase.co/hero.png",
        image_url=image_url, image_hash=None, job_id=job_id, status=status, error=error,
        created_at=now, updated_at=now,
    )


class _FakeJobManager:
    def __init__(self, job=None):
        self.created = []
        self._job = job

    def is_queue_full(self, job_type="text_to_image"):
        return False

    async def create_job(self, request, user_id, job_type="text_to_image"):
        job = SimpleNamespace(job_id="outjob_new", request=request, user_id=user_id)
        self.created.append((request, user_id, job_type))
        return job

    async def get_job(self, job_id):
        return self._job


class _FakeCharStore:
    def __init__(self, character):
        self.character = character

    async def get(self, cid):
        return self.character


class _FakeNudeStore:
    def __init__(self, latest=None):
        self._latest = latest
        self.created = []
        self.updates = []

    async def get_latest(self, character_id):
        return self._latest

    async def create(self, character_id, *, job_id, source_image_url=None):
        self.created.append({"character_id": character_id, "job_id": job_id, "source_image_url": source_image_url})
        return _nb_row(status="pending", job_id=job_id)

    async def update_status(self, nude_base_id, status, *, image_url=None, image_hash=None, error=None):
        self.updates.append({"id": nude_base_id, "status": status, "image_url": image_url,
                             "image_hash": image_hash, "error": error})
        return _nb_row(status=status, image_url=image_url, error=error)


def _wire(job_manager, char_store, nude_store):
    pipeline_ep.set_job_manager(job_manager)
    pipeline_ep.set_notification_service(None)  # no webhook in tests
    ep.set_job_manager(job_manager)
    ep.set_character_store(char_store)
    ep.set_nude_base_store(nude_store)


# ---------------------------------------------------------------------------
# POST /nude-base
# ---------------------------------------------------------------------------
def test_post_builds_naked_high_nudity_outfit_job():
    # LEGACY edit-based path (settings.NUDE_BASE_T2I=False). WS-N makes the t2i base
    # + face lock the DEFAULT; this asserts the fallback path stays byte-identical.
    prev = settings.NUDE_BASE_T2I
    settings.NUDE_BASE_T2I = False
    try:
        jm = _FakeJobManager()
        nude = _FakeNudeStore(latest=None)  # nothing pending -> fresh generation
        _wire(jm, _FakeCharStore(_character()), nude)

        resp = asyncio.run(ep.generate_nude_base("c1", user={"sub": "admin-1"}))

        # exactly one pipeline_edit job: NAKED at high nudity in the NEUTRAL "nude_base"
        # prompt mode (a calm reference body, not the arousal-styled tier), pushed hard
        # (outfit denoise) so the source garment is actually removed, plus a background
        # step (via `prompt`) clearing the scene to a plain SOLO backdrop (background
        # denoise + soloSubject) — all in one job.
        assert len(jm.created) == 1
        request, user_id, job_type = jm.created[0]
        assert job_type == "pipeline_edit"
        assert request.outfit == OutfitType.NAKED
        assert request.nudityLevel == NudityLevel.HIGH
        assert request.source_image == "https://x.supabase.co/hero.png"
        assert request.sourceDressed is False  # NAKED is never a GARMENT_MODE_OUTFITS target
        assert request.outfitDenoise == 0.92
        assert request.outfitPromptMode == "nude_base"
        assert request.prompt and "plain" in request.prompt and "grey studio" in request.prompt
        # Solo backdrop (A5): clears the hero's crowd/props to an empty studio.
        assert "only person in the frame" in request.prompt
        assert request.backgroundDenoise == 0.95
        assert request.soloSubject is True

        # a pending base row was recorded against that job
        assert nude.created == [{
            "character_id": "c1", "job_id": "outjob_new",
            "source_image_url": "https://x.supabase.co/hero.png",
        }]
        assert resp.status == "pending"
        assert resp.jobId == "outjob_new"
        assert resp.imageUrl is None
    finally:
        settings.NUDE_BASE_T2I = prev


def test_post_is_idempotent_while_a_job_is_live():
    # A pending row whose job is still running -> no duplicate job/render.
    live_job = SimpleNamespace(status=JobStatus.RUNNING, preview_url=None, image_hash=None)
    jm = _FakeJobManager(job=live_job)
    nude = _FakeNudeStore(latest=_nb_row(status="pending", job_id="outjob_abc"))
    _wire(jm, _FakeCharStore(_character()), nude)

    resp = asyncio.run(ep.generate_nude_base("c1", user={"sub": "admin-1"}))
    assert jm.created == []          # nothing new enqueued
    assert nude.created == []        # no new row
    assert resp.jobId == "outjob_abc"


def test_post_404_when_character_missing():
    jm = _FakeJobManager()
    _wire(jm, _FakeCharStore(None), _FakeNudeStore())
    try:
        asyncio.run(ep.generate_nude_base("c1", user={"sub": "admin-1"}))
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 404


# ---------------------------------------------------------------------------
# GET /nude-base (reconcile-on-read)
# ---------------------------------------------------------------------------
def test_get_finalizes_on_job_success():
    done = SimpleNamespace(status=JobStatus.SUCCEEDED, preview_url="https://x/nude.png",
                           image_hash="deadbeef", error_message=None)
    jm = _FakeJobManager(job=done)
    nude = _FakeNudeStore(latest=_nb_row(status="pending", job_id="outjob_abc"))
    _wire(jm, _FakeCharStore(_character()), nude)

    resp = asyncio.run(ep.get_nude_base("c1", user={"sub": "admin-1"}))

    assert nude.updates and nude.updates[0]["status"] == "succeeded"
    assert nude.updates[0]["image_url"] == "https://x/nude.png"
    assert nude.updates[0]["image_hash"] == "deadbeef"
    assert resp.status == "succeeded"
    assert resp.imageUrl == "https://x/nude.png"


def test_get_stays_pending_while_job_running():
    running = SimpleNamespace(status=JobStatus.RUNNING, preview_url=None, image_hash=None, error_message=None)
    jm = _FakeJobManager(job=running)
    nude = _FakeNudeStore(latest=_nb_row(status="pending", job_id="outjob_abc"))
    _wire(jm, _FakeCharStore(_character()), nude)

    resp = asyncio.run(ep.get_nude_base("c1", user={"sub": "admin-1"}))
    assert nude.updates == []  # nothing finalized yet
    assert resp.status == "pending"


def test_get_marks_failed_on_job_failure():
    failed = SimpleNamespace(status=JobStatus.FAILED, preview_url=None, image_hash=None,
                             error_message="GPU_OOM")
    jm = _FakeJobManager(job=failed)
    nude = _FakeNudeStore(latest=_nb_row(status="pending", job_id="outjob_abc"))
    _wire(jm, _FakeCharStore(_character()), nude)

    resp = asyncio.run(ep.get_nude_base("c1", user={"sub": "admin-1"}))
    assert nude.updates[0]["status"] == "failed"
    assert resp.status == "failed"
    assert resp.error == "GPU_OOM"


def test_get_404_when_no_base():
    jm = _FakeJobManager()
    _wire(jm, _FakeCharStore(_character()), _FakeNudeStore(latest=None))
    try:
        asyncio.run(ep.get_nude_base("c1", user={"sub": "admin-1"}))
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 404


# ---------------------------------------------------------------------------
# BatchReconciler activation (the payoff: scenes source from the nude base)
# ---------------------------------------------------------------------------
def _settings():
    return SimpleNamespace(BATCH_MAX_INFLIGHT=3, BATCH_ITEM_MAX_ATTEMPTS=2, RUNPOD_POLL_INTERVAL_SECONDS=1)


def _scene_spec():
    return SceneSpec(
        arc_id="morning", arc_title="Slow morning", beat_index=0, global_index=0,
        beat_description="by the window", outfit=OutfitType.COCKTAIL_DRESS,
        location=LocationType.HOME_BEDROOM,
    ).model_dump(mode="json")


class _EnqueueBatchStore:
    def __init__(self, item):
        self.item = item
        self.updates = []

    async def list_items(self, batch_id, statuses=None):
        return [self.item]

    async def update_item_result(self, item_id, **fields):
        self.updates.append((item_id, fields))

    async def update_batch_aggregate(self, batch_id):
        return None

    async def _get_item(self, item_id):
        return {}


class _CaptureJobManager:
    def __init__(self):
        self.requests = []

    async def get_job(self, job_id):
        return None

    async def create_job(self, request, owner, job_type="text_to_image"):
        self.requests.append(request)
        return SimpleNamespace(job_id=f"batjob_{len(self.requests)}")


def _batch():
    return SimpleNamespace(id="b1", character_id="c1", status="running",
                           controls=BatchControls(), likes=[], dislikes=[])


def _pending_item():
    return SimpleNamespace(id="i1", scene_index=0, status="pending", job_id=None,
                           seed=None, attempts=0, scene_spec=_scene_spec())


def _run_reconcile(nude_store):
    jm = _CaptureJobManager()
    bs = _EnqueueBatchStore(_pending_item())
    rec = BatchReconciler(
        job_manager=jm, character_store=_FakeCharStore(_character()), batch_store=bs,
        settings=_settings(), nude_base_store=nude_store,
    )
    asyncio.run(rec._reconcile_batch(_batch(), {}, {}))
    assert jm.requests, "an item should have been enqueued"
    return jm.requests[0]


def test_batch_uses_nude_base_when_present():
    class _Store:
        async def get_active_url(self, cid):
            return "https://x/nude.png"
    req = _run_reconcile(_Store())
    assert req.source_image == "https://x/nude.png"  # additive dressing engaged


def test_batch_falls_back_to_hero_when_no_nude_base():
    class _Store:
        async def get_active_url(self, cid):
            return None
    req = _run_reconcile(_Store())
    assert req.source_image == "https://x.supabase.co/hero.png"  # unchanged behavior


def test_batch_backcompat_when_store_unwired():
    req = _run_reconcile(None)  # nude_base_store never configured
    assert req.source_image == "https://x.supabase.co/hero.png"


def test_resolve_nude_base_url_swallows_errors():
    class _Boom:
        async def get_active_url(self, cid):
            raise RuntimeError("db down")
    rec = BatchReconciler(job_manager=None, character_store=None, batch_store=None,
                          settings=_settings(), nude_base_store=_Boom())
    assert asyncio.run(rec._resolve_nude_base_url("c1")) is None  # never stalls the batch


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
