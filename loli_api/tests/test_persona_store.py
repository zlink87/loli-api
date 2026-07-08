"""
Tests for ChatPersonaStore.apply (Feature 1): insert+link, never-clobber updates,
bio-only creates no persona, system_prompt NOT-NULL guard, bio->context mapping.

Runs under pytest or directly: python loli_api/tests/test_persona_store.py
"""
import asyncio

from services.chat_persona_store import ChatPersonaStore, _DEFAULT_SYSTEM_PROMPT


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
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

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self.client.data_for(self.rec["table"]))


class _Client:
    def __init__(self, table_data=None):
        self.calls = []
        self.table_data = table_data or {}

    def data_for(self, table):
        return self.table_data.get(table, [])

    def table(self, name):
        rec = {"table": name, "eqs": []}
        self.calls.append(rec)
        return _Query(self, rec)

    def ops(self, table):
        return [c for c in self.calls if c["table"] == table]


def _store(persona_row=None):
    data = {"chat_personas": [persona_row]} if persona_row else {}
    client = _Client(table_data=data)
    return ChatPersonaStore(client), client


# --- create + link ---
def test_apply_creates_persona_and_links_and_maps_bio():
    store, client = _store(persona_row={"id": "p1", "name": "Nora", "system_prompt": "You are Nora."})
    result = asyncio.run(store.apply(
        "c1",
        generated={
            "system_prompt": "You are Nora.",
            "greeting_message": "Hey, I'm Nora.",
            "bio": "This girl is trouble. 😏",
            "welcome_message": "*smiles* hi you.",
        },
        existing_persona_id=None,
        name_default="Nora",
    ))
    persona_calls = client.ops("chat_personas")
    insert = next(c for c in persona_calls if c["op"] == "insert")
    # persona columns only (bio/welcome are character columns, not persona)
    assert insert["payload"]["system_prompt"] == "You are Nora."
    assert insert["payload"]["greeting_message"] == "Hey, I'm Nora."
    assert insert["payload"]["name"] == "Nora"
    assert "bio" not in insert["payload"] and "welcome_message" not in insert["payload"]

    char_update = next(c for c in client.ops("characters") if c["op"] == "update")
    assert char_update["payload"]["chat_persona_id"] == "p1"
    assert char_update["payload"]["context"] == "This girl is trouble. 😏"  # bio -> context
    assert char_update["payload"]["welcome_message"] == "*smiles* hi you."
    assert char_update["eqs"] == [("id", "c1")]

    assert result["chat_persona_id"] == "p1"
    assert result["bio"] == "This girl is trouble. 😏"


# --- never clobber ---
def test_update_existing_writes_only_requested_columns():
    store, client = _store(persona_row={"id": "p1", "tone": "playful, flirty"})
    asyncio.run(store.apply(
        "c1",
        generated={"tone": "playful, flirty"},
        existing_persona_id="p1",
    ))
    update = next(c for c in client.ops("chat_personas") if c["op"] == "update")
    assert update["payload"] == {"tone": "playful, flirty"}  # ONLY tone
    # no characters update (no character columns requested)
    assert not [c for c in client.ops("characters") if c["op"] == "update"]
    # no insert (persona already exists)
    assert not [c for c in client.ops("chat_personas") if c["op"] == "insert"]


def test_model_id_written_only_when_provided():
    store, client = _store(persona_row={"id": "p1"})
    asyncio.run(store.apply("c1", generated={"tone": "x"}, existing_persona_id="p1"))
    upd = next(c for c in client.ops("chat_personas") if c["op"] == "update")
    assert "model_id" not in upd["payload"]

    store2, client2 = _store(persona_row={"id": "p1"})
    asyncio.run(store2.apply("c1", generated={"tone": "x"}, existing_persona_id="p1", model_id="venice-uncensored"))
    upd2 = next(c for c in client2.ops("chat_personas") if c["op"] == "update")
    assert upd2["payload"]["model_id"] == "venice-uncensored"


# --- bio-only creates no persona ---
def test_bio_only_creates_no_persona():
    store, client = _store()
    result = asyncio.run(store.apply(
        "c1", generated={"bio": "just a teaser"}, existing_persona_id=None,
    ))
    assert not [c for c in client.ops("chat_personas") if c["op"] == "insert"]
    char_update = next(c for c in client.ops("characters") if c["op"] == "update")
    assert char_update["payload"] == {"context": "just a teaser"}
    assert "chat_persona_id" not in char_update["payload"]
    assert result["chat_persona_id"] is None
    assert result["persona"] is None


# --- NOT NULL guard ---
def test_insert_without_system_prompt_uses_default():
    store, client = _store(persona_row={"id": "p1"})
    asyncio.run(store.apply(
        "c1", generated={"tone": "playful"}, existing_persona_id=None, name_default="Nora",
    ))
    insert = next(c for c in client.ops("chat_personas") if c["op"] == "insert")
    assert insert["payload"]["system_prompt"] == _DEFAULT_SYSTEM_PROMPT
    assert insert["payload"]["tone"] == "playful"
    assert insert["payload"]["name"] == "Nora"


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
