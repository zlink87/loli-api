"""
Tests for the persona endpoint glue (Feature 1): auto-including system_prompt when a
NEW chat_persona is created, per-field passthrough for an existing persona, dry_run and
preview writing nothing. Uses fake stores + the deterministic (keyless) writer.

Runs under pytest or directly: python loli_api/tests/test_persona_endpoint.py
"""
import asyncio
from datetime import datetime, timezone

from models.requests import PersonaOptions
from models.character import CharacterRead
from models.persona import PersonaGenerateRequest, PersonaPreviewRequest
from services.persona_writer import PersonaWriter
from api.v1.endpoints import persona as ep


def _persona():
    return PersonaOptions(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
        occupation="stripper", personality="nympho", relationship="sugar_baby",
    )


def _char(chat_persona_id=None):
    now = datetime.now(timezone.utc)
    return CharacterRead(
        id="c1", name="Nora", persona=_persona(), hero_image_url="https://x/y.png",
        bio=None, chat_persona_id=chat_persona_id, status="draft",
        created_at=now, updated_at=now,
    )


class _FakeCharStore:
    def __init__(self, character):
        self.character = character

    async def get(self, cid):
        return self.character


class _FakeChatPersonaStore:
    def __init__(self):
        self.applied = None

    async def apply(self, character_id, *, generated, existing_persona_id=None,
                    model_id=None, name_default=None):
        self.applied = {
            "generated": generated, "existing_persona_id": existing_persona_id,
            "model_id": model_id, "name_default": name_default,
        }
        return {
            "chat_persona_id": existing_persona_id or "p_new",
            "persona": {"id": existing_persona_id or "p_new", "name": name_default},
            "welcome_message": generated.get("welcome_message"),
            "bio": generated.get("bio"),
        }


def _setup(character):
    ep.set_persona_writer(PersonaWriter(api_key=""))  # deterministic fallback
    ep.set_character_store(_FakeCharStore(character))
    store = _FakeChatPersonaStore()
    ep.set_chat_persona_store(store)
    return store


def test_new_persona_autoincludes_system_prompt():
    store = _setup(_char(chat_persona_id=None))
    resp = asyncio.run(ep.generate_persona("c1", PersonaGenerateRequest(fields=["tone"]), user={}))
    assert "system_prompt" in resp.generated_fields  # auto-added for the NOT NULL create
    assert "system_prompt" in store.applied["generated"]
    assert resp.persisted is True
    assert resp.chat_persona_id == "p_new"


def test_existing_persona_writes_only_requested():
    store = _setup(_char(chat_persona_id="p1"))
    resp = asyncio.run(ep.generate_persona("c1", PersonaGenerateRequest(fields=["tone"]), user={}))
    assert set(store.applied["generated"].keys()) == {"tone"}  # no auto system_prompt
    assert store.applied["existing_persona_id"] == "p1"
    assert resp.chat_persona_id == "p1"


def test_dry_run_writes_nothing():
    store = _setup(_char(chat_persona_id=None))
    resp = asyncio.run(
        ep.generate_persona("c1", PersonaGenerateRequest(fields=["bio"], dry_run=True), user={})
    )
    assert resp.persisted is False
    assert store.applied is None
    assert "bio" in resp.generated


def test_preview_writes_nothing():
    _setup(_char())
    resp = asyncio.run(
        ep.preview_persona(
            PersonaPreviewRequest(persona=_persona(), fields=["greeting_message"]), user={}
        )
    )
    assert "greeting_message" in resp.generated
    assert resp.generated["greeting_message"]


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
