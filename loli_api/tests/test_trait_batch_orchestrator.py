"""
Orchestrator wiring tests (Phase B2, deliverable 4): BatchOrchestrator.launch_batch folds
the character's saved TraitProfile into the effective controls/likes/dislikes BEFORE the
batch row is persisted (so the row carries the effective values and the reconciler needs no
changes), respects body.use_trait_profile, and NEVER lets a profile problem block a launch.

Runs under pytest or directly: python loli_api/tests/test_trait_batch_orchestrator.py
"""
import asyncio
from types import SimpleNamespace

import models.requests as _mr
_mr.validate_source_image = lambda u: u  # type: ignore

import services.batch_orchestrator as bo
from services.batch_orchestrator import BatchOrchestrator
from services.story_planner import DeterministicScenePlanner
from models.batch import BatchCreate, BatchControls
from models.enums import OutfitType as O, InteriorStyleType, DemeanorType
from models.requests import PersonaOptions


def _persona():
    return PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation="model", personality="temptress", relationship="girlfriend",
    )


_PROFILE_ROW = {
    "profile": {
        "wardrobe_styles": ["elegant", "glamorous"],
        "favorite_outfits": ["red_evening_gown"],
        "never_wears": ["bikini"],
        "demeanor": ["elegant"],
        "interior_style": "luxury_glam",
        "color_palette": "jewel_tones",
        "likes": ["silk"],
        "dislikes": ["gyms"],
    },
    "provider": "venice",
}


class _FakeCharStore:
    def __init__(self):
        self._ns = SimpleNamespace(persona=_persona(), hero_image_url="https://x/h.png", bio=None)

    async def get(self, cid):
        return self._ns


class _FakeBatchStore:
    def __init__(self):
        self.batch = SimpleNamespace(id="batch-1")
        self.created = {}

    async def create_batch(self, character_id, count, controls, *, likes=None, dislikes=None):
        self.created = {"controls": controls, "likes": likes, "dislikes": dislikes}
        return self.batch

    async def set_planner_provider(self, batch_id, provider):
        return None

    async def insert_items(self, batch_id, rows):
        return rows

    async def set_batch_status(self, *a, **k):
        return None

    async def get_batch(self, batch_id):
        return self.batch


class _FakeTraitStore:
    def __init__(self, row=_PROFILE_ROW, raises=False):
        self._row = row
        self._raises = raises

    async def get(self, character_id):
        if self._raises:
            raise RuntimeError("table not migrated")
        return self._row


_SETTINGS = SimpleNamespace(
    RUNPOD_AVG_STEP_SECONDS=5, BATCH_WORKER_POOL_SIZE=3, RUNPOD_GPU_USD_PER_SECOND=0.0,
)


def _run(trait_store, body):
    """Launch a batch with a monkeypatched deterministic planner; return the batch store."""
    async def _fake_plan_scenes(character, count, controls, *, settings, **kw):
        scenes = DeterministicScenePlanner().plan_scenes_sync(character, count, controls)
        return scenes, "deterministic"

    orig = bo.story_planner.plan_scenes
    bo.story_planner.plan_scenes = _fake_plan_scenes
    try:
        store = _FakeBatchStore()
        orch = BatchOrchestrator(
            job_manager=None, character_store=_FakeCharStore(), batch_store=store,
            settings=_SETTINGS, trait_profile_store=trait_store,
        )
        asyncio.run(orch.launch_batch("char-1", body))
        return store
    finally:
        bo.story_planner.plan_scenes = orig


def test_profile_is_merged_before_create_batch():
    body = BatchCreate(count=6, controls=BatchControls(max_nudity="medium", base_seed=1), dry_run=True)
    store = _run(_FakeTraitStore(), body)
    persisted = store.created["controls"]
    # The PERSISTED controls carry the merged bias (not the raw body controls).
    assert persisted.wardrobe_outfits and O.RED_EVENING_GOWN in persisted.wardrobe_outfits
    assert O.BIKINI in persisted.blocked_outfits              # never_wears unioned in
    assert persisted.demeanor == [DemeanorType.ELEGANT]
    assert persisted.interior_style == InteriorStyleType.LUXURY_GLAM
    # likes/dislikes filled from the profile (batch sent none).
    assert store.created["likes"] == ["silk"] and store.created["dislikes"] == ["gyms"]
    # Nudity envelope untouched.
    assert persisted.max_nudity.value == "medium"


def test_use_trait_profile_false_skips_the_merge():
    body = BatchCreate(
        count=6, controls=BatchControls(max_nudity="medium", base_seed=1),
        dry_run=True, use_trait_profile=False,
    )
    store = _run(_FakeTraitStore(), body)
    persisted = store.created["controls"]
    assert persisted.wardrobe_outfits is None
    assert O.BIKINI not in persisted.blocked_outfits
    assert store.created["likes"] == [] and store.created["dislikes"] == []


def test_missing_profile_row_is_a_noop():
    body = BatchCreate(count=6, controls=BatchControls(max_nudity="medium", base_seed=1), dry_run=True)
    store = _run(_FakeTraitStore(row=None), body)
    assert store.created["controls"].wardrobe_outfits is None


def test_trait_store_error_never_blocks_launch():
    body = BatchCreate(count=6, controls=BatchControls(max_nudity="medium", base_seed=1), dry_run=True)
    # A raising store must not propagate — the batch still launches, just without bias.
    store = _run(_FakeTraitStore(raises=True), body)
    assert store.created["controls"].wardrobe_outfits is None
    assert store.created["controls"].max_nudity.value == "medium"


def test_no_trait_store_is_inert():
    body = BatchCreate(count=6, controls=BatchControls(max_nudity="medium", base_seed=1), dry_run=True)
    store = _run(None, body)
    assert store.created["controls"].wardrobe_outfits is None


def test_explicit_admin_controls_win_over_profile():
    # An admin allowlist skips the profile's outfit fields even with a profile present.
    body = BatchCreate(
        count=6,
        controls=BatchControls(max_nudity="medium", base_seed=1,
                               allowed_outfits=[O.COCKTAIL_DRESS, O.SATIN_SLIP_DRESS]),
        dry_run=True,
    )
    store = _run(_FakeTraitStore(), body)
    persisted = store.created["controls"]
    assert persisted.allowed_outfits == [O.COCKTAIL_DRESS, O.SATIN_SLIP_DRESS]
    assert persisted.wardrobe_outfits is None                 # outfit fields skipped
    assert O.BIKINI not in persisted.blocked_outfits
    # ...but non-outfit taste (demeanor/interior) still applies.
    assert persisted.demeanor == [DemeanorType.ELEGANT]


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
