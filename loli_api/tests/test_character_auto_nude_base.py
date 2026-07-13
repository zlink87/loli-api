"""
Tests for Part 3 — auto nude-base submission on character creation.

POST /v1/characters (and /bulk) submits the character's identity-locked nude base in
the same call, reusing the EXACT t2i submit path as POST /characters/{id}/nude-base
(nude_base.submit_nude_base_for_new_character -> _submit_t2i_nude_base). It is:
  * opt-OUT via CharacterCreate.generate_nude_base (default True);
  * gated on the nude-base services being wired AND settings.NUDE_BASE_T2I;
  * best-effort — a submission failure is logged and NEVER fails creation.

The persona/trait generation blocks are disabled here (generate_persona=False,
generate_traits=False) so each test isolates the nude-base block.

Runs under pytest or directly: python loli_api/tests/test_character_auto_nude_base.py
"""
import asyncio
import zlib
from datetime import datetime, timezone
from types import SimpleNamespace

# CharacterCreate SSRF-validates hero_image_url; bypass it for the test URL.
import models.character as _mc
_mc.validate_source_image = lambda u: u  # type: ignore

from config import settings
from models.requests import PersonaOptions, NudeBaseGenerateRequest
from models.character import CharacterCreate, CharacterRead
from api.v1.endpoints import characters as cep
from api.v1.endpoints import nude_base as nep


def _persona(**overrides):
    fields = dict(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
    )
    fields.update(overrides)
    return PersonaOptions(**fields)


def _body(**overrides):
    fields = dict(
        persona=_persona(),
        hero_image_url="https://x.supabase.co/hero.png",
        generate_persona=False,   # isolate the nude-base block
        generate_traits=False,
    )
    fields.update(overrides)
    return CharacterCreate(**fields)


class _FakeCharacterStore:
    async def create(self, body: CharacterCreate) -> CharacterRead:
        now = datetime.now(timezone.utc)
        return CharacterRead(
            id="c1", name=body.name or body.persona.name, persona=body.persona,
            hero_image_url=body.hero_image_url, bio=body.bio, chat_persona_id=None,
            status="draft", created_at=now, updated_at=now,
        )

    async def get(self, character_id):
        return None


class _FakeJobManager:
    def __init__(self, raise_on_create=False):
        self.created = []
        self._raise = raise_on_create

    def is_queue_full(self, job_type="text_to_image"):
        return False

    async def create_job(self, request, user_id, job_type="text_to_image"):
        if self._raise:
            raise RuntimeError("job manager exploded")
        self.created.append((request, user_id, job_type))
        return SimpleNamespace(job_id=f"{job_type}_1", request=request, user_id=user_id)

    async def get_job(self, job_id):
        return None


class _FakeNudeStore:
    def __init__(self):
        self.created = []

    async def get_latest(self, character_id):
        return None

    async def create(self, character_id, *, job_id, source_image_url=None):
        self.created.append({"character_id": character_id, "job_id": job_id,
                             "source_image_url": source_image_url})
        from models.nude_base import NudeBaseRead
        now = "2026-07-13T00:00:00Z"
        return NudeBaseRead(
            id="nb1", character_id=character_id, source_image_url=source_image_url,
            image_url=None, image_hash=None, job_id=job_id, status="pending",
            error=None, created_at=now, updated_at=now,
        )


def _wire(*, char_store, job_manager, nude_store, wire_submitter=True):
    """Wire both endpoint modules; returns a teardown that resets the shared globals."""
    cep.set_character_store(char_store)
    cep.set_persona_writer(None)
    cep.set_chat_persona_store(None)
    cep.set_trait_profile_writer(None)
    cep.set_trait_profile_store(None)
    nep.set_job_manager(job_manager)
    nep.set_nude_base_store(nude_store)
    nep.set_character_store(char_store)
    cep.set_nude_base_submitter(
        nep.submit_nude_base_for_new_character if wire_submitter else None
    )

    def _teardown():
        cep.set_nude_base_submitter(None)
        nep.set_job_manager(None)
        nep.set_nude_base_store(None)
        nep.set_character_store(None)

    return _teardown


def _run(fn):
    prev = settings.NUDE_BASE_T2I
    try:
        return fn()
    finally:
        settings.NUDE_BASE_T2I = prev


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_flag_on_submits_nude_base_job():
    def body_fn():
        settings.NUDE_BASE_T2I = True
        jm, nude = _FakeJobManager(), _FakeNudeStore()
        teardown = _wire(char_store=_FakeCharacterStore(), job_manager=jm, nude_store=nude)
        try:
            character = asyncio.run(cep.create_character(_body(), user={"sub": "admin-9"}))
        finally:
            teardown()

        assert character.id == "c1"
        # A nude_base job was created via the SAME t2i submit path (persona + hero + seed).
        assert len(jm.created) == 1
        request, user_id, job_type = jm.created[0]
        assert job_type == "nude_base"
        assert isinstance(request, NudeBaseGenerateRequest)
        assert request.character_id == "c1"
        assert request.hero_image_url == "https://x.supabase.co/hero.png"
        assert request.seed == zlib.crc32(b"c1")     # deterministic per-character
        assert request.persona.name == "Nora"
        assert user_id == "admin-9"                  # acting admin threaded through
        # A pending base row was recorded against that job.
        assert nude.created == [{
            "character_id": "c1", "job_id": "nude_base_1",
            "source_image_url": "https://x.supabase.co/hero.png",
        }]

    _run(body_fn)


def test_flag_off_does_not_submit():
    def body_fn():
        settings.NUDE_BASE_T2I = True
        jm, nude = _FakeJobManager(), _FakeNudeStore()
        teardown = _wire(char_store=_FakeCharacterStore(), job_manager=jm, nude_store=nude)
        try:
            character = asyncio.run(cep.create_character(
                _body(generate_nude_base=False), user={"sub": "admin"}
            ))
        finally:
            teardown()
        assert character.id == "c1"
        assert jm.created == []       # opt-out honored
        assert nude.created == []

    _run(body_fn)


def test_t2i_flag_off_does_not_submit_even_with_generate_flag_on():
    def body_fn():
        settings.NUDE_BASE_T2I = False   # legacy edit path is never auto-triggered
        jm, nude = _FakeJobManager(), _FakeNudeStore()
        teardown = _wire(char_store=_FakeCharacterStore(), job_manager=jm, nude_store=nude)
        try:
            character = asyncio.run(cep.create_character(_body(), user={"sub": "admin"}))
        finally:
            teardown()
        assert character.id == "c1"
        assert jm.created == [] and nude.created == []

    _run(body_fn)


def test_submitter_unwired_is_noop():
    def body_fn():
        settings.NUDE_BASE_T2I = True
        jm, nude = _FakeJobManager(), _FakeNudeStore()
        teardown = _wire(char_store=_FakeCharacterStore(), job_manager=jm, nude_store=nude,
                         wire_submitter=False)  # nude-base services not wired into characters
        try:
            character = asyncio.run(cep.create_character(_body(), user={"sub": "admin"}))
        finally:
            teardown()
        assert character.id == "c1"
        assert jm.created == [] and nude.created == []

    _run(body_fn)


def test_submission_failure_does_not_fail_creation():
    def body_fn():
        settings.NUDE_BASE_T2I = True
        jm = _FakeJobManager(raise_on_create=True)   # create_job blows up
        nude = _FakeNudeStore()
        teardown = _wire(char_store=_FakeCharacterStore(), job_manager=jm, nude_store=nude)
        orig_logger, cep.logger = cep.logger, _SpyLogger()
        try:
            character = asyncio.run(cep.create_character(_body(), user={"sub": "admin"}))
            assert character.id == "c1"          # creation STILL succeeded
            assert nude.created == []            # never reached the pending-row write
            assert cep.logger.errors             # the failure was logged
        finally:
            cep.logger = orig_logger
            teardown()

    _run(body_fn)


def test_bulk_creation_also_auto_submits():
    from models.character import BulkCharacterCreate

    def body_fn():
        settings.NUDE_BASE_T2I = True
        jm, nude = _FakeJobManager(), _FakeNudeStore()
        teardown = _wire(char_store=_FakeCharacterStore(), job_manager=jm, nude_store=nude)
        try:
            resp = asyncio.run(cep.create_characters_bulk(
                BulkCharacterCreate(items=[_body(), _body()]), user={"sub": "admin"}
            ))
        finally:
            teardown()
        assert all(r.status == "created" for r in resp.results)
        assert len(jm.created) == 2                        # one nude_base job per item
        assert all(jt == "nude_base" for _, _, jt in jm.created)

    _run(body_fn)


class _SpyLogger:
    def __init__(self):
        self.warnings, self.errors, self.infos = [], [], []

    def warning(self, msg, *a, **kw):
        self.warnings.append(msg)

    def error(self, msg, *a, **kw):
        self.errors.append(msg)

    def info(self, msg, *a, **kw):
        self.infos.append(msg)


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
