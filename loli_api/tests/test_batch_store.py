"""
Mapping tests for CharacterStore, BatchStore and CharacterImageStore against the
REAL product schema (characters / character_images / chat_persona_actions +
character_batches / character_batch_items).

Uses a fake Supabase client that records the query chain and asserts the exact
tables, payload columns and delete ordering.

Runs under pytest or directly: python loli_api/tests/test_batch_store.py
"""
import asyncio

from services.character_store import CharacterStore, _persona_to_columns, _row_to_persona
from services.character_image_store import CharacterImageStore, action_label
from services.batch_store import BatchStore
from models.batch import BatchControls
from models.requests import PersonaOptions


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

    def delete(self):
        self.rec["op"] = "delete"
        return self

    def eq(self, k, v):
        self.rec["eqs"].append((k, v))
        return self

    def in_(self, k, v):
        self.rec["eqs"].append((k, list(v)))
        return self

    def order(self, *a, **k):
        return self

    def range(self, *a, **k):
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


_CHARACTER_ROW = {
    "id": "c1",
    "name": "Estella",
    "style": "realistic",
    "ethnicity": "caucasian",
    "age": 28,
    "hair_style": "straight",
    "hair_color": "blonde",
    "eye_color": "green",
    "body_type": "curvy",
    "breast_size": "medium",
    "personality": "temptress",
    "relationship": "girlfriend",
    "occupation": "nurse",
    "kinks": ["playful_teasing"],
    "voice": None,
    "context": "A night-shift nurse.",
    "profile_image_url": "https://x.supabase.co/img.png",
    "status": "draft",
    "created_at": "2026-07-07T00:00:00Z",
    "updated_at": "2026-07-07T00:00:00Z",
}


def _character_create_body():
    import models.character as _mc
    _mc.validate_source_image = lambda u: u  # type: ignore
    from models.character import CharacterCreate

    persona = {
        "ethnicity": "caucasian", "age": 28, "hairStyle": "straight",
        "hairColor": "blonde", "eyeColor": "green", "bodyType": "curvy",
        "breastSize": "medium", "name": "Estella", "personality": "temptress",
        "relationship": "girlfriend", "occupation": "nurse",
        "kinks": ["playful_teasing"],
    }
    return CharacterCreate(
        persona=persona,
        hero_image_url="https://x.supabase.co/img.png",
        bio="A night-shift nurse.",
    )


def test_character_create_targets_real_table_with_flat_columns():
    client = _FakeClient(default_data=[_CHARACTER_ROW])
    store = CharacterStore(client)
    asyncio.run(store.create(_character_create_body()))

    calls = client.calls_for("characters")
    assert calls, "insert must target the real characters table"
    payload = calls[0]["payload"]
    # persona flattened into typed columns
    assert payload["ethnicity"] == "caucasian"
    assert payload["hair_style"] == "straight"
    assert payload["breast_size"] == "medium"
    assert payload["kinks"] == ["playful_teasing"]
    # bio -> context; hero photo -> all three image columns; draft status
    assert payload["context"] == "A night-shift nurse."
    for col in ("profile_image_url", "avatar_image_url", "chat_avatar_url"):
        assert payload[col] == "https://x.supabase.co/img.png"
    assert payload["status"] == "draft"
    # no ownership column on the real table
    assert "owner_id" not in payload
    assert "persona" not in payload  # no JSON blob


def test_character_row_round_trips_to_persona():
    client = _FakeClient(default_data=[_CHARACTER_ROW])
    store = CharacterStore(client)
    char = asyncio.run(store.get("c1"))
    assert char is not None
    assert char.persona.ethnicity.value == "caucasian"
    assert char.persona.hairStyle.value == "straight"
    assert char.persona.name == "Estella"
    assert char.hero_image_url == "https://x.supabase.co/img.png"
    assert char.bio == "A night-shift nurse."
    assert char.status == "draft"


# --- culture persona column (optional, degrade-safe) ---
def _persona(**overrides):
    fields = dict(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
    )
    fields.update(overrides)
    return PersonaOptions(**fields)


def test_persona_to_columns_emits_culture():
    # set -> the enum value; absent -> None (byte-identical to a culture-less persona)
    assert _persona_to_columns(_persona(culture="goth"))["culture"] == "goth"
    assert _persona_to_columns(_persona())["culture"] is None


def test_character_row_round_trips_culture():
    row = dict(_CHARACTER_ROW, culture="e_girl")
    persona = _row_to_persona(row)
    assert persona.culture is not None and persona.culture.value == "e_girl"


def test_character_row_missing_culture_key_reads_none():
    # An old row (pre-migration payload) simply has no culture key -> None, never raises.
    assert "culture" not in _CHARACTER_ROW
    assert _row_to_persona(_CHARACTER_ROW).culture is None


def test_character_row_garbage_culture_degrades_to_none():
    # A garbage/future stored value must not brick GET /v1/characters.
    for bad in ("not_a_culture", "GOTH!!", 123, ""):
        assert _row_to_persona(dict(_CHARACTER_ROW, culture=bad)).culture is None


def test_character_delete_is_fk_safe_ordered():
    client = _FakeClient(default_data=[{"id": "c1"}])
    store = CharacterStore(client)
    ok = asyncio.run(store.delete("c1"))
    assert ok
    tables = [c["table"] for c in client.calls]
    assert tables == ["chat_persona_actions", "character_images", "characters"]
    # every delete scoped to the character
    assert ("character_id", "c1") in client.calls[0]["eqs"]
    assert ("character_id", "c1") in client.calls[1]["eqs"]
    assert ("id", "c1") in client.calls[2]["eqs"]


_BATCH_ROW = {
    "id": "b1", "character_id": "c1", "count": 6,
    "controls": {}, "likes": ["silk"], "dislikes": ["gyms"],
    "status": "planning", "progress": 0.0,
    "items_total": 0, "items_succeeded": 0, "items_failed": 0,
    "error": None,
    "created_at": "2026-07-07T00:00:00Z", "updated_at": "2026-07-07T00:00:00Z",
}


def test_batch_create_targets_character_batches_and_persists_likes():
    client = _FakeClient(default_data=[_BATCH_ROW])
    store = BatchStore(client)
    batch = asyncio.run(
        store.create_batch("c1", 6, BatchControls(), likes=["silk"], dislikes=["gyms"])
    )
    calls = client.calls_for("character_batches")
    assert calls, "insert must target character_batches"
    payload = calls[0]["payload"]
    assert payload["character_id"] == "c1"
    assert payload["likes"] == ["silk"]
    assert payload["dislikes"] == ["gyms"]
    assert "owner_id" not in payload
    assert batch.likes == ["silk"]


def test_batch_items_target_character_batch_items():
    client = _FakeClient(default_data=[])
    store = BatchStore(client)
    asyncio.run(store.list_items("b1"))
    assert client.calls_for("character_batch_items")


def test_merge_item_debug_read_modify_writes_pipeline_request():
    # Phase 5 observability: merge_item_debug must preserve existing pipeline_request
    # keys (e.g. the planned "prompt") while adding/overwriting "_debug".
    client = _FakeClient(table_data={
        "character_batch_items": [{"pipeline_request": {"prompt": "kitchen at dawn"}}],
    })
    store = BatchStore(client)
    debug_payload = {
        "steps": [{"step": "outfit", "tier": "2511full", "positive": "P", "negative": "N"}],
        "planner_provider": "deterministic",
    }
    asyncio.run(store.merge_item_debug("i1", debug_payload))

    calls = client.calls_for("character_batch_items")
    update_calls = [c for c in calls if c["op"] == "update"]
    assert update_calls, "merge_item_debug must issue an update"
    payload = update_calls[-1]["payload"]
    assert payload["pipeline_request"]["prompt"] == "kitchen at dawn"  # preserved
    assert payload["pipeline_request"]["_debug"] == debug_payload
    assert ("id", "i1") in update_calls[-1]["eqs"]


def test_merge_item_debug_missing_row_is_a_noop():
    client = _FakeClient(table_data={"character_batch_items": []})
    store = BatchStore(client)
    asyncio.run(store.merge_item_debug("missing", {"steps": []}))
    assert not [c for c in client.calls_for("character_batch_items") if c["op"] == "update"]


def test_active_batches_query_is_status_scoped():
    client = _FakeClient(default_data=[])
    store = BatchStore(client)
    asyncio.run(store.list_active_batches())
    eqs = client.calls_for("character_batches")[0]["eqs"]
    assert any(k == "status" for k, _ in eqs)


def test_image_store_payloads():
    client = _FakeClient(table_data={
        "character_images": [{"id": "img-1"}],
        "chat_persona_actions": [{"id": "act-1"}],
    })
    store = CharacterImageStore(client)

    image_id = asyncio.run(store.create_image(
        "c1",
        image_url="https://x/batch_edits/j1.png",
        original_image_url="https://x/preview.png",
        prompt="in a bedroom",
        seed=42,
        outfit="silk_pajamas",
        accessories=["necklace"],
        metadata={"batch_id": "b1", "scene_index": 0},
    ))
    assert image_id == "img-1"
    img_payload = client.calls_for("character_images")[0]["payload"]
    assert img_payload["character_id"] == "c1"
    assert img_payload["image_type"] == "gallery"
    assert img_payload["provider"] == "runpod-comfyui"
    assert img_payload["is_avatar"] is False
    assert img_payload["accessories"] == ["necklace"]
    assert img_payload["metadata"]["batch_id"] == "b1"

    action_id = asyncio.run(store.create_action(
        "c1",
        character_image_id=image_id,
        media_url="https://x/batch_edits/j1.png",
        label="Morning coffee",
        suggested_prompt="Morning coffee in bed",
        sort_order=3,
        trigger_keywords=["home", "bedroom"],
    ))
    assert action_id == "act-1"
    act_payload = client.calls_for("chat_persona_actions")[0]["payload"]
    assert act_payload["character_image_id"] == "img-1"
    assert act_payload["media_type"] == "image"
    assert act_payload["trigger_type"] == "manual"
    assert act_payload["sort_order"] == 3
    assert act_payload["is_active"] is True
    assert act_payload["trigger_keywords"] == ["home", "bedroom"]

    # Omitted trigger_keywords persists as an empty list, not None.
    asyncio.run(store.create_action(
        "c1",
        character_image_id=image_id,
        media_url="https://x/batch_edits/j1.png",
        label="No keywords",
    ))
    no_kw_payload = client.calls_for("chat_persona_actions")[1]["payload"]
    assert no_kw_payload["trigger_keywords"] == []


def test_action_label_fallbacks_and_truncation():
    assert action_label("Morning coffee", "Arc", 0) == "Morning coffee"
    assert action_label(None, "A day off", 0) == "A day off"
    assert action_label("", "", 4) == "Photo 5"
    long = "x" * 100
    assert len(action_label(long, None, 0)) <= 40


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
