"""
Tests for the trait-profile endpoint glue (WS-B): GET/generate/PUT/preview/backfill
404s + write semantics, dry_run writing nothing, backfill best-effort (skip existing,
capture per-character errors), and the CharacterCreate.generate_traits create flag.

Uses fake stores + the deterministic (keyless) writer. Endpoints are called directly
as async functions with an already-resolved `user` dict (same as the persona tests).

Runs under pytest or directly: python loli_api/tests/test_trait_profile_endpoint.py
"""
import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException

from models.requests import PersonaOptions
from models.character import CharacterCreate, CharacterRead
from models.trait_profile import (
    TraitProfileGenerateRequest,
    TraitProfilePreviewRequest,
    TraitProfileUpdate,
)
from services.trait_profile_writer import TraitProfileWriter
from api.v1.endpoints import trait_profile as ep
from api.v1.endpoints import characters as chars


def _persona(name="Nora"):
    return PersonaOptions(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name=name,
        occupation="dancer", personality="temptress", relationship="sugar_baby",
    )


def _char(character_id="c1", bio="A night-shift dancer."):
    now = datetime.now(timezone.utc)
    return CharacterRead(
        id=character_id, name="Nora", persona=_persona(), hero_image_url="https://x/y.png",
        bio=bio, chat_persona_id=None, status="draft", created_at=now, updated_at=now,
    )


class _FakeCharStore:
    def __init__(self, characters=None):
        # dict cid -> CharacterRead
        self.characters = {c.id: c for c in (characters or [])}
        self.created = []

    async def get(self, cid):
        return self.characters.get(cid)

    async def list(self, limit=50, offset=0):
        rows = list(self.characters.values())
        return rows[offset:offset + limit]

    async def create(self, body: CharacterCreate) -> CharacterRead:
        now = datetime.now(timezone.utc)
        c = CharacterRead(
            id=f"c{len(self.created)}", name=body.name or body.persona.name,
            persona=body.persona, hero_image_url=body.hero_image_url, bio=body.bio,
            chat_persona_id=None, status="draft", created_at=now, updated_at=now,
        )
        self.created.append(c)
        self.characters[c.id] = c
        return c


class _FakeTraitStore:
    def __init__(self, existing=None):
        self.existing = dict(existing or {})  # cid -> row
        self.applied = []  # (cid, generated, provider)

    async def get(self, cid):
        return self.existing.get(cid)

    async def apply(self, cid, *, generated, provider=None):
        row = {"character_id": cid, "profile": dict(generated), "provider": provider}
        self.existing[cid] = row
        self.applied.append((cid, generated, provider))
        return row


class _RaisingWriter:
    async def write(self, persona, fields, enrichment, *, character_id=None, bio=None):
        raise RuntimeError("venice exploded")


def _setup(char_store, trait_store, writer=None):
    ep.set_trait_profile_writer(writer if writer is not None else TraitProfileWriter(api_key=""))
    ep.set_character_store(char_store)
    ep.set_trait_profile_store(trait_store)
    return char_store, trait_store


# --- GET ---
def test_get_404_when_character_missing():
    _setup(_FakeCharStore(), _FakeTraitStore())
    raised = False
    try:
        asyncio.run(ep.get_trait_profile("nope", user={}))
    except HTTPException as e:
        raised = e.status_code == 404
    assert raised


def test_get_404_when_profile_missing():
    _setup(_FakeCharStore([_char()]), _FakeTraitStore())
    raised = False
    try:
        asyncio.run(ep.get_trait_profile("c1", user={}))
    except HTTPException as e:
        raised = e.status_code == 404
    assert raised


def test_get_returns_profile_when_present():
    trait = _FakeTraitStore(existing={"c1": {"character_id": "c1",
                                             "profile": {"wardrobe_styles": ["elegant"]},
                                             "provider": "venice"}})
    _setup(_FakeCharStore([_char()]), trait)
    resp = asyncio.run(ep.get_trait_profile("c1", user={}))
    assert resp.character_id == "c1"
    assert resp.provider == "venice"
    assert [w.value for w in resp.profile.wardrobe_styles] == ["elegant"]


# --- generate ---
def test_generate_persists_and_records_provider():
    char_store = _FakeCharStore([_char()])
    trait = _FakeTraitStore()
    _setup(char_store, trait)
    resp = asyncio.run(ep.generate_trait_profile("c1", TraitProfileGenerateRequest(), user={}))
    assert resp.persisted is True
    assert resp.provider == "deterministic"
    assert len(trait.applied) == 1
    cid, generated, provider = trait.applied[0]
    assert cid == "c1" and provider == "deterministic"
    # a full generation writes all trait fields
    assert "wardrobe_styles" in generated and "zodiac" in generated


def test_generate_dry_run_writes_nothing():
    trait = _FakeTraitStore()
    _setup(_FakeCharStore([_char()]), trait)
    resp = asyncio.run(
        ep.generate_trait_profile("c1", TraitProfileGenerateRequest(dry_run=True), user={})
    )
    assert resp.persisted is False
    assert trait.applied == []
    assert resp.profile is not None


def test_generate_404_when_character_missing():
    _setup(_FakeCharStore(), _FakeTraitStore())
    raised = False
    try:
        asyncio.run(ep.generate_trait_profile("nope", TraitProfileGenerateRequest(), user={}))
    except HTTPException as e:
        raised = e.status_code == 404
    assert raised


# --- PUT manual ---
def test_put_manual_writes_only_provided_fields_provider_manual():
    trait = _FakeTraitStore()
    _setup(_FakeCharStore([_char()]), trait)
    resp = asyncio.run(
        ep.update_trait_profile("c1", TraitProfileUpdate(likes=["salsa", "wine"]), user={})
    )
    assert resp.provider == "manual"
    cid, generated, provider = trait.applied[0]
    assert provider == "manual"
    assert set(generated.keys()) == {"likes"}  # only the provided field
    assert generated["likes"] == ["salsa", "wine"]


def test_put_manual_coerces_and_strips_naked():
    trait = _FakeTraitStore()
    _setup(_FakeCharStore([_char()]), trait)
    asyncio.run(
        ep.update_trait_profile(
            "c1", TraitProfileUpdate(favorite_outfits=["naked", "bikini"]), user={}
        )
    )
    _, generated, _ = trait.applied[0]
    assert "naked" not in generated["favorite_outfits"]
    assert "bikini" in generated["favorite_outfits"]


def test_put_404_when_character_missing():
    _setup(_FakeCharStore(), _FakeTraitStore())
    raised = False
    try:
        asyncio.run(ep.update_trait_profile("nope", TraitProfileUpdate(likes=["x"]), user={}))
    except HTTPException as e:
        raised = e.status_code == 404
    assert raised


# --- preview ---
def test_preview_writes_nothing_and_returns_profile():
    trait = _FakeTraitStore()
    _setup(_FakeCharStore(), trait)
    resp = asyncio.run(
        ep.preview_trait_profile(
            TraitProfilePreviewRequest(persona=_persona(), fields=["wardrobe_styles", "demeanor"]),
            user={},
        )
    )
    assert trait.applied == []
    assert resp.generated
    assert resp.profile is not None


# --- backfill ---
def test_backfill_skips_existing_and_processes_missing():
    a, b, c = _char("cA"), _char("cB"), _char("cC")
    char_store = _FakeCharStore([a, b, c])
    trait = _FakeTraitStore(existing={"cB": {"character_id": "cB", "profile": {}, "provider": "venice"}})
    _setup(char_store, trait)
    resp = asyncio.run(ep.backfill_trait_profiles(user={}, limit=500))
    processed_ids = {r.character_id for r in resp.results}
    assert processed_ids == {"cA", "cC"}  # cB skipped (already has a profile)
    assert all(r.provider == "deterministic" and r.error is None for r in resp.results)


def test_backfill_captures_per_character_error():
    char_store = _FakeCharStore([_char("cA")])
    trait = _FakeTraitStore()
    _setup(char_store, trait, writer=_RaisingWriter())
    resp = asyncio.run(ep.backfill_trait_profiles(user={}, limit=500))
    assert len(resp.results) == 1
    assert resp.results[0].character_id == "cA"
    assert resp.results[0].error is not None
    assert resp.results[0].provider is None


# --- CharacterCreate.generate_traits create flag ---
def _char_create_body(generate_traits=True):
    import models.character as _mc
    _mc.validate_source_image = lambda u: u  # bypass SSRF allowlist for the test URL
    return CharacterCreate(
        persona=_persona(), hero_image_url="https://x.supabase.co/img.png",
        generate_traits=generate_traits,
    )


def test_create_flag_generates_traits_by_default():
    char_store = _FakeCharStore()
    trait = _FakeTraitStore()
    chars.set_character_store(char_store)
    chars.set_persona_writer(None)
    chars.set_chat_persona_store(None)
    chars.set_trait_profile_writer(TraitProfileWriter(api_key=""))
    chars.set_trait_profile_store(trait)
    asyncio.run(chars.create_character(_char_create_body(generate_traits=True), user={}))
    assert len(trait.applied) == 1  # traits auto-generated on create


def test_create_flag_off_skips_traits():
    char_store = _FakeCharStore()
    trait = _FakeTraitStore()
    chars.set_character_store(char_store)
    chars.set_persona_writer(None)
    chars.set_chat_persona_store(None)
    chars.set_trait_profile_writer(TraitProfileWriter(api_key=""))
    chars.set_trait_profile_store(trait)
    asyncio.run(chars.create_character(_char_create_body(generate_traits=False), user={}))
    assert trait.applied == []
    # reset the module DI so the flag-off state can't leak into later files
    chars.set_trait_profile_writer(None)
    chars.set_trait_profile_store(None)


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
