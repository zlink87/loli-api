"""
Tests for TraitProfileStore.apply (WS-B): insert-when-absent, per-field
never-clobber jsonb merge (untouched keys preserved), provider recording, and get.

Uses a fake Supabase client (same shape as test_persona_store.py).

Runs under pytest or directly: python loli_api/tests/test_trait_profile_store.py
"""
import asyncio

from services.trait_profile_store import TraitProfileStore


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
        if self.rec["table"] == self.client.raise_on_table:
            raise RuntimeError(f"boom on {self.rec['table']}")
        return _Resp(self.client.data_for(self.rec["table"]))


class _Client:
    def __init__(self, table_data=None, raise_on_table=None):
        self.calls = []
        self.table_data = table_data or {}
        self.raise_on_table = raise_on_table

    def data_for(self, table):
        return self.table_data.get(table, [])

    def table(self, name):
        rec = {"table": name, "eqs": []}
        self.calls.append(rec)
        return _Query(self, rec)

    def ops(self, table):
        return [c for c in self.calls if c["table"] == table]


_TABLE = "character_trait_profiles"
_CARD_TABLE = "character_profile_cards"


def _store(existing_row=None, raise_on_table=None):
    data = {_TABLE: [existing_row]} if existing_row else {}
    client = _Client(table_data=data, raise_on_table=raise_on_table)
    return TraitProfileStore(client), client


# --- insert when absent ---
def test_apply_inserts_when_absent():
    store, client = _store()
    asyncio.run(store.apply(
        "c1",
        generated={"wardrobe_styles": ["elegant"], "demeanor": ["sultry"]},
        provider="venice",
    ))
    insert = next(c for c in client.ops(_TABLE) if c["op"] == "insert")
    assert insert["payload"]["character_id"] == "c1"
    assert insert["payload"]["profile"] == {"wardrobe_styles": ["elegant"], "demeanor": ["sultry"]}
    assert insert["payload"]["provider"] == "venice"
    # no update when the row is absent
    assert not [c for c in client.ops(_TABLE) if c["op"] == "update"]


# --- never-clobber merge ---
def test_apply_merges_never_clobber():
    existing = {
        "character_id": "c1",
        "profile": {"wardrobe_styles": ["elegant"], "likes": ["x"], "zodiac": "leo"},
        "provider": "venice",
    }
    store, client = _store(existing_row=existing)
    asyncio.run(store.apply("c1", generated={"likes": ["y", "z"]}, provider="mixed"))
    update = next(c for c in client.ops(_TABLE) if c["op"] == "update")
    # only `likes` overwritten; wardrobe_styles + zodiac preserved
    assert update["payload"]["profile"] == {
        "wardrobe_styles": ["elegant"], "likes": ["y", "z"], "zodiac": "leo"
    }
    assert update["payload"]["provider"] == "mixed"
    assert ("character_id", "c1") in update["eqs"]
    # no insert (row already exists)
    assert not [c for c in client.ops(_TABLE) if c["op"] == "insert"]


# --- provider omitted when not given ---
def test_apply_omits_provider_when_none():
    existing = {"character_id": "c1", "profile": {}, "provider": "venice"}
    store, client = _store(existing_row=existing)
    asyncio.run(store.apply("c1", generated={"demeanor": ["shy"]}))
    update = next(c for c in client.ops(_TABLE) if c["op"] == "update")
    assert "provider" not in update["payload"]
    assert update["payload"]["profile"] == {"demeanor": ["shy"]}


# --- public card mirror ---
def test_apply_flattens_card_into_card_table():
    store, client = _store()
    asyncio.run(store.apply(
        "c1",
        generated={
            "short_description": "Wealthy heiress who loves luxury.",
            "display_occupation": "Heiress and Socialite",
            "display_personality": ["Spoiled", "Charming"],
            "display_hobbies": ["Exclusive parties", "Shopping"],
            "language": "English",
            "zodiac": "leo",
            "wardrobe_styles": ["glamorous"],  # non-card field ignored by the card
        },
        provider="venice",
    ))
    card_ops = client.ops(_CARD_TABLE)
    insert = next(c for c in card_ops if c["op"] == "insert")
    p = insert["payload"]
    assert p["character_id"] == "c1"
    assert p["short_description"] == "Wealthy heiress who loves luxury."
    assert p["display_occupation"] == "Heiress and Socialite"
    assert p["display_personality"] == ["Spoiled", "Charming"]
    assert p["display_hobbies"] == ["Exclusive parties", "Shopping"]
    assert p["language"] == "English"
    assert p["zodiac"] == "leo"  # mirrored from the profile
    assert "wardrobe_styles" not in p  # only card columns are flattened


def test_card_write_failure_is_best_effort():
    # The card table blows up, but the profile write must still succeed (no raise).
    store, client = _store(raise_on_table=_CARD_TABLE)
    row = asyncio.run(store.apply("c1", generated={"short_description": "hi"}, provider="venice"))
    # profile row was written (insert on the trait table happened)
    assert any(c["op"] == "insert" for c in client.ops(_TABLE))
    assert row["profile"] == {"short_description": "hi"}


# --- get ---
def test_get_returns_row_or_none():
    store, _ = _store(existing_row={"character_id": "c1", "profile": {"likes": ["x"]}})
    row = asyncio.run(store.get("c1"))
    assert row["profile"] == {"likes": ["x"]}

    store2, _ = _store()
    assert asyncio.run(store2.get("c1")) is None


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
