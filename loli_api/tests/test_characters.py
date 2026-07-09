"""
Tests for POST /v1/characters `generate_persona` (create the character AND generate
+ persist its full chat persona in the SAME call). Uses fake stores + a spy writer,
mirroring test_persona_endpoint.py's fakes (that file covers the existing two-step
POST /v1/characters/{id}/persona flow this one now also reaches from creation).

Runs under pytest or directly: python loli_api/tests/test_characters.py
"""
import asyncio
from datetime import datetime, timezone

from models.requests import PersonaOptions
from models.character import CharacterCreate, CharacterRead
from api.v1.endpoints import characters as ep


def _persona(**overrides):
    fields = dict(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
        occupation="stripper", personality="nympho", relationship="sugar_baby",
    )
    fields.update(overrides)
    return PersonaOptions(**fields)


def _character_create_body(**overrides):
    # Bypass the SSRF host allowlist for the test URL (same technique as
    # test_batch_store.py's _character_create_body()).
    import models.character as _mc
    _mc.validate_source_image = lambda u: u  # type: ignore

    fields = dict(
        persona=_persona(),
        hero_image_url="https://x.supabase.co/img.png",
    )
    fields.update(overrides)
    return CharacterCreate(**fields)


class _FakeCharacterStore:
    """Fakes CharacterStore.create()/.get() (endpoint-level, extends
    test_persona_endpoint.py's _FakeCharStore with the .create() this endpoint needs).

    create() always returns a fresh row with chat_persona_id=None — same as the real
    store, which only learns chat_persona_id later via ChatPersonaStore.apply(). A
    test can set `chat_persona_id_after_apply` beforehand to simulate that DB write
    being visible on the endpoint's post-generation get() call, to prove the endpoint
    actually re-fetches instead of returning the stale create()-time object.
    """

    def __init__(self):
        self.created = None
        self.get_calls = 0
        self.chat_persona_id_after_apply = None

    async def create(self, body: CharacterCreate) -> CharacterRead:
        now = datetime.now(timezone.utc)
        self.created = CharacterRead(
            id="c1",
            name=body.name or body.persona.name,
            persona=body.persona,
            hero_image_url=body.hero_image_url,
            bio=body.bio,
            chat_persona_id=None,
            status="draft",
            created_at=now,
            updated_at=now,
        )
        return self.created

    async def get(self, character_id):
        self.get_calls += 1
        if self.chat_persona_id_after_apply is not None:
            return self.created.model_copy(
                update={"chat_persona_id": self.chat_persona_id_after_apply}
            )
        return self.created


class _SpyWriter:
    """Records exactly what create_character passed to write(); returns synthetic
    values keyed by the (string-normalized) requested field names.
    """

    def __init__(self):
        self.calls = []

    async def write(self, persona, fields, enrichment, *, name=None):
        field_names = [getattr(f, "value", f) for f in fields]
        self.calls.append(
            {"persona": persona, "fields": field_names, "enrichment": enrichment, "name": name}
        )
        return {f: f"generated-{f}" for f in field_names}, "venice"


class _RaisingWriter:
    async def write(self, *a, **kw):
        raise RuntimeError("venice down")


class _SpyChatPersonaStore:
    def __init__(self, chat_persona_id="p_new"):
        self.applied = None
        self.chat_persona_id = chat_persona_id

    async def apply(self, character_id, *, generated, existing_persona_id=None,
                    model_id=None, name_default=None):
        self.applied = {
            "character_id": character_id, "generated": generated,
            "existing_persona_id": existing_persona_id, "model_id": model_id,
            "name_default": name_default,
        }
        return {
            "chat_persona_id": self.chat_persona_id,
            "persona": {"id": self.chat_persona_id, "name": name_default},
            "welcome_message": generated.get("welcome_message"),
            "bio": generated.get("bio"),
        }


class _RaisingChatPersonaStore:
    async def apply(self, *a, **kw):
        raise RuntimeError("supabase down")


class _FakeLogger:
    """Swapped in for ep.logger to assert warning/error calls without caplog — this
    suite's test functions all run standalone via __main__ too (see the trailer
    below), so pytest-only fixtures like caplog aren't used anywhere in it.
    """

    def __init__(self):
        self.warnings = []
        self.errors = []
        self.infos = []

    def warning(self, msg, *a, **kw):
        self.warnings.append(msg)

    def error(self, msg, *a, **kw):
        self.errors.append(msg)

    def info(self, msg, *a, **kw):
        self.infos.append(msg)


def _setup(store, writer=None, chat_store=None):
    ep.set_character_store(store)
    ep.set_persona_writer(writer)
    ep.set_chat_persona_store(chat_store)


def _run_with_fake_logger(body):
    """Runs create_character with ep.logger swapped for a spy, restoring it after."""
    fake_logger = _FakeLogger()
    orig_logger, ep.logger = ep.logger, fake_logger
    try:
        character = asyncio.run(ep.create_character(body, user={}))
    finally:
        ep.logger = orig_logger
    return character, fake_logger


def test_generate_persona_false_is_back_compatible():
    # Both omitted (defaults False) and explicit False must behave byte-identical to
    # pre-feature creation: persona writer/store are never touched.
    for body in (_character_create_body(), _character_create_body(generate_persona=False)):
        store = _FakeCharacterStore()
        writer = _SpyWriter()
        chat_store = _SpyChatPersonaStore()
        _setup(store, writer, chat_store)

        character = asyncio.run(ep.create_character(body, user={}))

        assert character == store.created
        assert character.chat_persona_id is None
        assert writer.calls == []
        assert chat_store.applied is None
        assert store.get_calls == 0


def test_default_fields_exclude_bio_when_bio_typed():
    store = _FakeCharacterStore()
    writer = _SpyWriter()
    _setup(store, writer, _SpyChatPersonaStore())

    body = _character_create_body(generate_persona=True, bio="Something I typed")
    asyncio.run(ep.create_character(body, user={}))

    fields = set(writer.calls[0]["fields"])
    assert fields == {
        "system_prompt", "greeting_message", "tone", "style",
        "boundaries", "summary", "welcome_message",
    }
    assert "bio" not in fields
    assert "name" not in fields


def test_default_fields_include_bio_when_no_bio_typed():
    store = _FakeCharacterStore()
    writer = _SpyWriter()
    _setup(store, writer, _SpyChatPersonaStore())

    body = _character_create_body(generate_persona=True)  # bio omitted entirely
    asyncio.run(ep.create_character(body, user={}))

    fields = set(writer.calls[0]["fields"])
    assert "bio" in fields
    assert "name" not in fields
    assert len(fields) == 8


def test_default_fields_include_bio_when_bio_is_blank_string():
    # A whitespace-only bio doesn't count as "typed" — bio generation still runs.
    store = _FakeCharacterStore()
    writer = _SpyWriter()
    _setup(store, writer, _SpyChatPersonaStore())

    body = _character_create_body(generate_persona=True, bio="   ")
    asyncio.run(ep.create_character(body, user={}))

    assert "bio" in set(writer.calls[0]["fields"])


def test_explicit_persona_fields_overrides_default_even_with_bio_typed():
    store = _FakeCharacterStore()
    writer = _SpyWriter()
    _setup(store, writer, _SpyChatPersonaStore())

    body = _character_create_body(
        generate_persona=True, bio="Something I typed", persona_fields=["bio"],
    )
    asyncio.run(ep.create_character(body, user={}))

    assert writer.calls[0]["fields"] == ["bio"]


def test_response_reflects_generation_via_refetch():
    store = _FakeCharacterStore()
    writer = _SpyWriter()
    chat_store = _SpyChatPersonaStore(chat_persona_id="p_new")
    _setup(store, writer, chat_store)
    # Simulates chat_persona_store.apply() having written characters.chat_persona_id.
    store.chat_persona_id_after_apply = "p_new"

    body = _character_create_body(generate_persona=True)
    character = asyncio.run(ep.create_character(body, user={}))

    # The object store.create() returned is stale (chat_persona_id=None) — prove the
    # endpoint returned the RE-FETCHED row, not that stale object.
    assert store.created.chat_persona_id is None
    assert store.get_calls == 1
    assert character.chat_persona_id == "p_new"


def test_write_failure_does_not_fail_creation():
    store = _FakeCharacterStore()
    chat_store = _SpyChatPersonaStore()
    _setup(store, _RaisingWriter(), chat_store)

    body = _character_create_body(generate_persona=True)
    character, fake_logger = _run_with_fake_logger(body)

    assert character.id == "c1"  # creation still succeeded
    assert character.chat_persona_id is None  # no re-fetch (failed before apply)
    assert chat_store.applied is None  # apply() never reached
    assert store.get_calls == 0
    assert fake_logger.errors  # the failure was logged


def test_apply_failure_does_not_fail_creation():
    store = _FakeCharacterStore()
    writer = _SpyWriter()
    _setup(store, writer, _RaisingChatPersonaStore())

    body = _character_create_body(generate_persona=True)
    character, fake_logger = _run_with_fake_logger(body)

    assert character.id == "c1"  # creation still succeeded
    assert writer.calls  # write() DID run before apply() blew up
    assert store.get_calls == 0
    assert fake_logger.errors


def test_missing_persona_services_degrades_gracefully():
    store = _FakeCharacterStore()
    _setup(store, None, None)  # persona services never wired

    body = _character_create_body(generate_persona=True)
    character, fake_logger = _run_with_fake_logger(body)

    assert character == store.created
    assert store.get_calls == 0
    assert fake_logger.warnings


def test_missing_chat_persona_store_only_also_degrades_gracefully():
    store = _FakeCharacterStore()
    _setup(store, _SpyWriter(), None)  # writer present, store missing

    body = _character_create_body(generate_persona=True)
    character = asyncio.run(ep.create_character(body, user={}))

    assert character == store.created


def test_enrichment_and_model_id_pass_through_to_writer_and_store():
    store = _FakeCharacterStore()
    writer = _SpyWriter()
    chat_store = _SpyChatPersonaStore()
    _setup(store, writer, chat_store)

    body = _character_create_body(
        generate_persona=True,
        persona_fields=["tone"],
        persona_enrichment={"likes": ["coffee"], "language": "French"},
        persona_model_id="venice-uncensored",
    )
    asyncio.run(ep.create_character(body, user={}))

    assert writer.calls[0]["enrichment"]["likes"] == ["coffee"]
    assert writer.calls[0]["enrichment"]["language"] == "French"
    assert writer.calls[0]["name"] == "Nora"
    assert chat_store.applied["model_id"] == "venice-uncensored"


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
