"""
Tests for WS-T — trait reach for the standalone edit endpoints.

Three slices:
  1. services.character_anchors.populate_home_style — a characterId + a HOME-like
     location auto-fills interiorStyle/colorPalette from the trait profile (explicit
     values win, non-home locations are a pure no-op, best-effort / never raises).
  2. api.v1.endpoints.background.build_background_prompt — when her home taste is
     present the scene is recomposed as her styled INTERIOR_ROOM_PHRASES room + palette
     (matching batches); absent it, the raw prompt is used byte-identically.
  3. services.character_anchors.never_wears_warnings + the outfit endpoint advisory —
     an outfit in the character's never-wears list returns a non-blocking traitWarnings
     entry (the edit is still enqueued).

Runs under pytest or directly: python loli_api/tests/test_edit_trait_reach.py
"""
import asyncio
from types import SimpleNamespace

# The edit request models SSRF-validate source_image; these tests exercise trait
# logic, not the allowlist, so make the validator a passthrough.
import models.requests as _mr
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import InteriorStyleType, PaletteType, OutfitType
from models.requests import BackgroundEditRequest, PipelineEditRequest, OutfitEditRequest
from services import scene_vocab as sv
from services.character_anchors import populate_home_style, never_wears_warnings
from api.v1.endpoints.background import build_background_prompt


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeTraitStore:
    def __init__(self, row):
        self._row = row
        self.calls = 0

    async def get(self, character_id):
        self.calls += 1
        return self._row


class _RaisingTraitStore:
    def __init__(self):
        self.calls = 0

    async def get(self, character_id):
        self.calls += 1
        raise RuntimeError("supabase down")


def _profile_row(interior_style="luxury_glam", color_palette="bold_dark", never_wears=None):
    return {"profile": {
        "interior_style": interior_style,
        "color_palette": color_palette,
        "never_wears": never_wears or [],
    }}


def _bg(**overrides):
    fields = dict(source_image="https://x.supabase.co/i.png", prompt="her place")
    fields.update(overrides)
    return BackgroundEditRequest(**fields)


# ---------------------------------------------------------------------------
# 1 — populate_home_style
# ---------------------------------------------------------------------------
def test_home_location_fills_style_and_palette():
    store = _FakeTraitStore(_profile_row())
    req = _bg(characterId="c1", location="home_bedroom")
    asyncio.run(populate_home_style(store, req))
    assert req.interiorStyle == InteriorStyleType.LUXURY_GLAM
    assert req.colorPalette == PaletteType.BOLD_DARK
    assert store.calls == 1


def test_pipeline_request_home_location_fills_too():
    # The same helper works on PipelineEditRequest (its `location` field already exists).
    store = _FakeTraitStore(_profile_row(interior_style="scandinavian_light",
                                         color_palette="crisp_white"))
    req = PipelineEditRequest(
        source_image="https://x.supabase.co/i.png", prompt="scene", characterId="c1",
        location="home_living_room",
    )
    asyncio.run(populate_home_style(store, req))
    assert req.interiorStyle == InteriorStyleType.SCANDINAVIAN_LIGHT
    assert req.colorPalette == PaletteType.CRISP_WHITE


def test_explicit_interior_style_wins_palette_still_filled():
    store = _FakeTraitStore(_profile_row())  # profile = LUXURY_GLAM
    req = _bg(characterId="c1", location="home_bedroom",
              interiorStyle=InteriorStyleType.MODERN_MINIMAL)
    asyncio.run(populate_home_style(store, req))
    assert req.interiorStyle == InteriorStyleType.MODERN_MINIMAL  # explicit kept
    assert req.colorPalette == PaletteType.BOLD_DARK              # filled independently


def test_both_explicit_never_queries_store():
    store = _FakeTraitStore(_profile_row())
    req = _bg(characterId="c1", location="home_bedroom",
              interiorStyle=InteriorStyleType.RUSTIC_WARM, colorPalette=PaletteType.EARTHY_GREEN)
    asyncio.run(populate_home_style(store, req))
    assert req.interiorStyle == InteriorStyleType.RUSTIC_WARM
    assert req.colorPalette == PaletteType.EARTHY_GREEN
    assert store.calls == 0  # both explicit -> store untouched


def test_non_home_location_is_pure_noop_no_store_call():
    store = _FakeTraitStore(_profile_row())
    for loc in ("cafe", "beach", "gym", "office", "city_street"):
        req = _bg(characterId="c1", location=loc)
        asyncio.run(populate_home_style(store, req))
        assert req.interiorStyle is None and req.colorPalette is None, loc
    assert store.calls == 0  # non-home short-circuits BEFORE the store round-trip


def test_no_character_id_is_noop():
    store = _FakeTraitStore(_profile_row())
    req = _bg(location="home_bedroom")  # no characterId
    asyncio.run(populate_home_style(store, req))
    assert req.interiorStyle is None and req.colorPalette is None
    assert store.calls == 0


def test_store_none_degrades_gracefully():
    req = _bg(characterId="c1", location="home_bedroom")
    asyncio.run(populate_home_style(None, req))  # store not configured
    assert req.interiorStyle is None and req.colorPalette is None


def test_unknown_character_row_none_is_noop():
    store = _FakeTraitStore(None)  # character has no profile row
    req = _bg(characterId="ghost", location="home_bedroom")
    asyncio.run(populate_home_style(store, req))
    assert req.interiorStyle is None and req.colorPalette is None
    assert store.calls == 1


def test_store_raises_is_swallowed():
    store = _RaisingTraitStore()
    req = _bg(characterId="c1", location="home_bedroom")
    asyncio.run(populate_home_style(store, req))  # must not raise
    assert req.interiorStyle is None and req.colorPalette is None
    assert store.calls == 1


def test_empty_profile_leaves_request_unchanged():
    store = _FakeTraitStore({"profile": {}})  # no interior_style / color_palette
    req = _bg(characterId="c1", location="home_bedroom")
    asyncio.run(populate_home_style(store, req))
    assert req.interiorStyle is None and req.colorPalette is None


# ---------------------------------------------------------------------------
# 2 — build_background_prompt threading
# ---------------------------------------------------------------------------
def test_build_prompt_home_carries_styled_room_and_palette():
    styled = sv.INTERIOR_ROOM_PHRASES[InteriorStyleType.LUXURY_GLAM]["home_bedroom"]
    built = build_background_prompt(
        "her place", location="home_bedroom",
        interior_style=InteriorStyleType.LUXURY_GLAM, color_palette=PaletteType.BOLD_DARK,
    )
    assert styled in built                    # her exact styled INTERIOR_ROOM_PHRASES room
    assert sv.PALETTE_PHRASES[PaletteType.BOLD_DARK] in built
    assert "her place" in built               # the caller's free text is preserved


def test_build_prompt_no_style_is_byte_identical_parity():
    # With BOTH interior_style/color_palette None the raw prompt path is used —
    # byte-identical to omitting them (unchanged interactive behavior).
    base = build_background_prompt("tropical beach at sunset")
    same = build_background_prompt(
        "tropical beach at sunset", location="beach",
        interior_style=None, color_palette=None,
    )
    assert base == same
    assert base.startswith("Change the environment and background to: tropical beach at sunset,")


def test_build_prompt_style_coexists_with_identity_anchors():
    styled = sv.INTERIOR_ROOM_PHRASES[InteriorStyleType.GIRLY_PASTEL]["home_office"]
    built = build_background_prompt(
        "x", identity_anchors="warm dark-brown skin, curvy build",
        location="home_office", interior_style=InteriorStyleType.GIRLY_PASTEL,
    )
    assert styled in built
    assert "warm dark-brown skin, curvy build" in built  # anchor clause still applied


# ---------------------------------------------------------------------------
# 3 — never_wears advisory
# ---------------------------------------------------------------------------
def _outfit(**overrides):
    fields = dict(source_image="https://x.supabase.co/i.png", outfit=OutfitType.BIKINI)
    fields.update(overrides)
    return OutfitEditRequest(**fields)


def test_never_wears_advisory_present_when_blocked():
    store = _FakeTraitStore(_profile_row(never_wears=["bikini", "jogging"]))
    req = _outfit(outfit=OutfitType.BIKINI, characterId="c1")
    warnings = asyncio.run(never_wears_warnings(store, req))
    assert warnings == ["bikini is in this character's never-wears list"]


def test_never_wears_advisory_absent_when_allowed():
    store = _FakeTraitStore(_profile_row(never_wears=["jogging"]))
    req = _outfit(outfit=OutfitType.RED_EVENING_GOWN, characterId="c1")
    assert asyncio.run(never_wears_warnings(store, req)) is None


def test_never_wears_no_character_id_or_store_is_none():
    store = _FakeTraitStore(_profile_row(never_wears=["bikini"]))
    assert asyncio.run(never_wears_warnings(store, _outfit(outfit=OutfitType.BIKINI))) is None
    assert asyncio.run(never_wears_warnings(None, _outfit(outfit=OutfitType.BIKINI,
                                                          characterId="c1"))) is None


def test_never_wears_store_raises_is_swallowed():
    store = _RaisingTraitStore()
    req = _outfit(outfit=OutfitType.BIKINI, characterId="c1")
    assert asyncio.run(never_wears_warnings(store, req)) is None  # must not raise


# ---------------------------------------------------------------------------
# 3b — endpoint integration: the outfit edit response carries traitWarnings, and the
#      background edit endpoint actually runs populate_home_style before enqueue.
# ---------------------------------------------------------------------------
class _FakeJobManager:
    def __init__(self):
        self.created = []

    def is_queue_full(self, job_type="text_to_image"):
        return False

    async def create_job(self, request, user_id, job_type="text_to_image"):
        self.created.append((request, user_id, job_type))
        return SimpleNamespace(job_id=f"{job_type}_1", request=request, user_id=user_id)


def test_outfit_endpoint_returns_never_wears_advisory():
    from api.v1.endpoints import outfit as oep
    jm = _FakeJobManager()
    oep.set_job_manager(jm)
    oep.set_notification_service(None)
    oep.set_character_store(None)  # identity anchors no-op
    oep.set_trait_profile_store(_FakeTraitStore(_profile_row(never_wears=["bikini"])))
    try:
        resp = asyncio.run(oep.edit_outfit(
            _outfit(outfit=OutfitType.BIKINI, characterId="c1"), current_user={"sub": "admin"}
        ))
        assert resp.traitWarnings == ["bikini is in this character's never-wears list"]
        assert jm.created and jm.created[0][2] == "outfit_edit"  # still enqueued (non-blocking)
    finally:
        oep.set_trait_profile_store(None)  # reset shared module global


def test_background_endpoint_fills_home_style_before_enqueue():
    from api.v1.endpoints import background as bep
    jm = _FakeJobManager()
    bep.set_job_manager(jm)
    bep.set_notification_service(None)
    bep.set_character_store(None)
    bep.set_trait_profile_store(_FakeTraitStore(_profile_row()))
    try:
        asyncio.run(bep.edit_background(
            _bg(characterId="c1", location="home_bedroom"), current_user={"sub": "admin"}
        ))
        enqueued_req = jm.created[0][0]
        assert enqueued_req.interiorStyle == InteriorStyleType.LUXURY_GLAM
        assert enqueued_req.colorPalette == PaletteType.BOLD_DARK
    finally:
        bep.set_trait_profile_store(None)  # reset shared module global


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
