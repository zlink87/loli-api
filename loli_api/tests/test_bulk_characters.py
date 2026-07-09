"""
Tests for POST /v1/characters/bulk (Batch Character Creation "Save all").

Covers: per-item INDEPENDENT save (partial success — a failing item does not roll back
the good ones), request-order results, reuse of the same generate_persona path as the
single POST /v1/characters, and the whole-request 503 when the store is unconfigured.

Mirrors test_characters.py's fakes. Runs under pytest or directly:
    python loli_api/tests/test_bulk_characters.py
"""
import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException

from models.requests import PersonaOptions
from models.character import CharacterCreate, CharacterRead, BulkCharacterCreate
from api.v1.endpoints import characters as ep


def _persona(**overrides):
    fields = dict(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
    )
    fields.update(overrides)
    return PersonaOptions(**fields)


def _body(**overrides):
    # Bypass the SSRF host allowlist for the test URL (same technique as test_characters.py).
    import models.character as _mc
    _mc.validate_source_image = lambda u: u  # type: ignore

    fields = dict(persona=_persona(), hero_image_url="https://x.supabase.co/img.png")
    fields.update(overrides)
    return CharacterCreate(**fields)


class _FakeStore:
    """CharacterStore stand-in. `create` raises for a configured display name to
    simulate a per-item DB failure; every other item is created independently."""

    def __init__(self, fail_on_name=None):
        self.fail_on_name = fail_on_name
        self.created = []

    async def create(self, body: CharacterCreate) -> CharacterRead:
        display = body.name or body.persona.name
        if self.fail_on_name and display == self.fail_on_name:
            raise RuntimeError("duplicate slug")
        now = datetime.now(timezone.utc)
        c = CharacterRead(
            id=f"c{len(self.created)}", name=display, persona=body.persona,
            hero_image_url=body.hero_image_url, bio=body.bio, chat_persona_id=None,
            status="draft", created_at=now, updated_at=now,
        )
        self.created.append(c)
        return c

    async def get(self, character_id):
        for c in self.created:
            if c.id == character_id:
                return c
        return None


class _SpyWriter:
    def __init__(self):
        self.calls = []

    async def write(self, persona, fields, enrichment, *, name=None):
        field_names = [getattr(f, "value", f) for f in fields]
        self.calls.append({"fields": field_names, "name": name})
        return {f: f"generated-{f}" for f in field_names}, "venice"


class _SpyChatPersonaStore:
    def __init__(self):
        self.applied = []

    async def apply(self, character_id, *, generated, existing_persona_id=None,
                    model_id=None, name_default=None):
        self.applied.append(character_id)
        return {
            "chat_persona_id": "p_new",
            "persona": {"id": "p_new", "name": name_default},
            "welcome_message": generated.get("welcome_message"),
            "bio": generated.get("bio"),
        }


def _setup(store, writer=None, chat_store=None):
    ep.set_character_store(store)
    ep.set_persona_writer(writer)
    ep.set_chat_persona_store(chat_store)


def test_bulk_partial_success_preserves_order_and_good_rows():
    store = _FakeStore(fail_on_name="Bad")
    _setup(store)
    body = BulkCharacterCreate(items=[
        _body(persona=_persona(name="Good")),
        _body(persona=_persona(name="Bad")),
        _body(persona=_persona(name="Also")),
    ])

    resp = asyncio.run(ep.create_characters_bulk(body, user={}))

    assert [r.index for r in resp.results] == [0, 1, 2]  # request order
    assert resp.results[0].status == "created"
    assert resp.results[0].character.name == "Good"
    assert resp.results[1].status == "failed"
    assert resp.results[1].error.code == "CREATE_ERROR"
    assert "duplicate slug" in resp.results[1].error.message
    assert resp.results[1].character is None
    assert resp.results[2].status == "created"
    assert resp.results[2].character.name == "Also"
    # The bad item did NOT roll back the two good ones.
    assert [c.name for c in store.created] == ["Good", "Also"]


def test_bulk_all_created():
    store = _FakeStore()
    _setup(store)
    body = BulkCharacterCreate(items=[_body(persona=_persona(name="A")), _body(persona=_persona(name="B"))])
    resp = asyncio.run(ep.create_characters_bulk(body, user={}))
    assert all(r.status == "created" for r in resp.results)
    assert len(resp.results) == 2


def test_bulk_reuses_generate_persona_path():
    store = _FakeStore()
    writer = _SpyWriter()
    chat = _SpyChatPersonaStore()
    _setup(store, writer, chat)

    body = BulkCharacterCreate(items=[_body(generate_persona=True)])
    resp = asyncio.run(ep.create_characters_bulk(body, user={}))

    assert resp.results[0].status == "created"
    assert writer.calls, "persona writer should be invoked for generate_persona items"
    assert chat.applied == ["c0"]  # chat persona persisted for the created character


def test_bulk_unconfigured_store_503s_whole_request():
    _setup(None)  # store never wired
    body = BulkCharacterCreate(items=[_body()])
    raised = None
    try:
        asyncio.run(ep.create_characters_bulk(body, user={}))
    except HTTPException as e:
        raised = e
    assert raised is not None and raised.status_code == 503


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
