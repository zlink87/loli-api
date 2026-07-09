"""
Tests for the outfit enum <-> outfit_detail coherence fix (the #1 story-batch bug:
"the render keeps the avatar's clothes / the caption says one thing, the picture shows
another"). Covers the caption->OutfitType keyword map, the ungated outfit-fill in
validate_and_repair, the enum<->detail reconcile, allow/block safety, the flipped
batch default, and the tightened story-director prompt rules.

Runs under pytest or directly: python loli_api/tests/test_outfit_fill.py
"""
from models.enums import NudityLevel, OutfitType, LocationType
from models.requests import PersonaOptions
from models.batch import BatchControls
from models.scene import SceneSpec
from services.story_planner import (
    Character, validate_and_repair, _outfit_from_detail, _reconcile_outfit,
    STORY_DIRECTOR_SYSTEM_PROMPT, VeniceScenePlanner,
)


def _character(occupation="nurse"):
    persona = PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation=occupation, personality="temptress", relationship="girlfriend",
    )
    return Character(persona=persona)


def _scene(**kw):
    base = dict(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
        location=LocationType.HOME_BEDROOM, nudityLevel=NudityLevel.LOW,
    )
    base.update(kw)
    return SceneSpec(**base)


# ---------------------------------------------------------------------------
# _outfit_from_detail: caption -> concrete OutfitType
# ---------------------------------------------------------------------------
def test_outfit_from_detail_maps_representative_captions():
    T = OutfitType
    assert _outfit_from_detail("soft satin pajamas") == T.SILK_PAJAMAS
    assert _outfit_from_detail("a deep red evening gown") == T.RED_EVENING_GOWN
    assert _outfit_from_detail("her little black dress") == T.LITTLE_BLACK_DRESS
    assert _outfit_from_detail("a tiny string bikini") == T.BIKINI
    assert _outfit_from_detail("a plush satin robe") == T.SATIN_ROBE
    # longest / most-specific phrase wins: "crop top" beats the "leather"/"jeans" beside it
    assert _outfit_from_detail("leather crop top and high-waisted jeans") == T.CROP_TOP_CARGO


def test_outfit_from_detail_unknown_or_empty_returns_none():
    assert _outfit_from_detail("") is None
    assert _outfit_from_detail(None) is None
    assert _outfit_from_detail("something unremarkable and vague") is None


def test_outfit_from_detail_is_word_boundary_safe():
    # "fur" must not fire inside "furniture"; nothing else here maps either.
    assert _outfit_from_detail("she is dusting the furniture") is None


def test_outfit_from_detail_never_returns_naked():
    # A caption describes clothing; nudity is the ramp's job, so NAKED is never derived.
    assert _outfit_from_detail("completely naked and bare") is None


# ---------------------------------------------------------------------------
# Ungated fill: THE regression for the reported bug
# ---------------------------------------------------------------------------
def test_low_beat_with_caption_but_null_enum_is_filled_from_caption():
    # outfit=None, nudity=low, outfit_detail set -> previously the outfit step was skipped
    # and the avatar's own clothes rendered while the gallery showed the caption. Now the
    # null enum is filled FROM the caption so the step runs and the render matches the text.
    scene = _scene(outfit=None, nudityLevel=NudityLevel.LOW, outfit_detail="soft satin pajamas")
    out = validate_and_repair([scene], _character(), 1, BatchControls(base_seed=1),
                              enforce_beat_pool=False)
    assert out[0].outfit is not None
    assert out[0].outfit == OutfitType.SILK_PAJAMAS


def test_low_beat_null_enum_and_no_caption_stays_none():
    # No outfit SIGNAL at all (low nudity, no caption) -> nothing to place, enum stays None
    # (so a deliberately-blocked-to-None outfit is never silently re-populated).
    scene = _scene(outfit=None, nudityLevel=NudityLevel.LOW, outfit_detail=None)
    out = validate_and_repair([scene], _character(), 1, BatchControls(base_seed=1),
                              enforce_beat_pool=False)
    assert out[0].outfit is None


def test_fill_is_deterministic_for_same_seed():
    scene = _scene(outfit=None, nudityLevel=NudityLevel.MEDIUM)
    controls = BatchControls(max_nudity=NudityLevel.HIGH, start_nudity=NudityLevel.MEDIUM, base_seed=7)
    a = validate_and_repair([scene.model_copy(deep=True)], _character(), 1, controls,
                            enforce_beat_pool=False)
    b = validate_and_repair([scene.model_copy(deep=True)], _character(), 1, controls,
                            enforce_beat_pool=False)
    assert a[0].outfit == b[0].outfit and a[0].outfit is not None


# ---------------------------------------------------------------------------
# Fill respects allow/block + never introduces NAKED
# ---------------------------------------------------------------------------
def test_fill_respects_blocked_and_never_naked():
    controls = BatchControls(
        max_nudity=NudityLevel.HIGH, start_nudity=NudityLevel.MEDIUM,
        blocked_outfits=[OutfitType.NAKED, OutfitType.BIKINI], base_seed=9,
    )
    scenes = [
        _scene(beat_index=i, global_index=i, outfit=None, nudityLevel=NudityLevel.MEDIUM)
        for i in range(6)
    ]
    out = validate_and_repair(scenes, _character(), 6, controls, enforce_beat_pool=False)
    for s in out:
        assert s.outfit is not None
        assert s.outfit != OutfitType.NAKED
        assert s.outfit != OutfitType.BIKINI


def test_fill_derive_falls_back_when_caption_names_blocked_outfit():
    # Caption says bikini, but bikini is blocked -> the derive is rejected and a pool pick
    # (never the blocked/NAKED type) is used instead.
    controls = BatchControls(
        max_nudity=NudityLevel.HIGH, start_nudity=NudityLevel.MEDIUM,
        blocked_outfits=[OutfitType.NAKED, OutfitType.BIKINI], base_seed=3,
    )
    scene = _scene(outfit=None, nudityLevel=NudityLevel.MEDIUM,
                   location=LocationType.BEACH, outfit_detail="a tiny bikini")
    out = validate_and_repair([scene], _character(), 1, controls, enforce_beat_pool=False)
    assert out[0].outfit is not None
    assert out[0].outfit not in (OutfitType.BIKINI, OutfitType.NAKED)


# ---------------------------------------------------------------------------
# Enum <-> detail reconcile (caption is authoritative)
# ---------------------------------------------------------------------------
def test_reconcile_overrides_enum_to_match_detail():
    # outfit=satin_robe but the caption clearly says a crop top + jeans -> the caption wins.
    scene = _scene(outfit=OutfitType.SATIN_ROBE,
                   outfit_detail="leather crop top and high-waisted jeans")
    out = validate_and_repair([scene], _character(), 1, BatchControls(base_seed=1),
                              enforce_beat_pool=False)
    assert out[0].outfit == OutfitType.CROP_TOP_CARGO
    assert out[0].outfit_detail  # kept: now consistent with the enum


def test_reconcile_little_black_dress_becomes_satin_robe():
    scene = _scene(outfit=OutfitType.LITTLE_BLACK_DRESS, outfit_detail="a plush satin robe")
    out = validate_and_repair([scene], _character(), 1, BatchControls(base_seed=1),
                              enforce_beat_pool=False)
    assert out[0].outfit == OutfitType.SATIN_ROBE


def test_reconcile_drops_detail_on_mismatch_with_no_confident_target():
    # enum=business_suit, caption names a DIFFERENT class ("dress") that maps to no specific
    # keyword -> keep the enum, drop the contradicting caption so the render can't conflict.
    scene = _scene(outfit=OutfitType.BUSINESS_SUIT, outfit_detail="a flowing chiffon dress")
    out = validate_and_repair([scene], _character(), 1, BatchControls(base_seed=1),
                              enforce_beat_pool=False)
    assert out[0].outfit == OutfitType.BUSINESS_SUIT  # enum kept
    assert out[0].outfit_detail is None               # contradicting caption dropped


def test_reconcile_keeps_consistent_detail_untouched():
    # A caption consistent with the enum's own class ("suit") -> both preserved.
    scene = _scene(outfit=OutfitType.BUSINESS_SUIT, outfit_detail="charcoal pinstripe suit")
    out = validate_and_repair([scene], _character(), 1, BatchControls(base_seed=1),
                              enforce_beat_pool=False)
    assert out[0].outfit == OutfitType.BUSINESS_SUIT
    assert out[0].outfit_detail and "suit" in out[0].outfit_detail


def test_reconcile_noop_when_no_outfit_or_no_detail():
    # Direct unit check: nothing to reconcile if either side is missing.
    s1 = _scene(outfit=None, outfit_detail="a satin robe")
    _reconcile_outfit(s1, BatchControls())
    assert s1.outfit is None and s1.outfit_detail == "a satin robe"
    s2 = _scene(outfit=OutfitType.BUSINESS_SUIT, outfit_detail=None)
    _reconcile_outfit(s2, BatchControls())
    assert s2.outfit == OutfitType.BUSINESS_SUIT


# ---------------------------------------------------------------------------
# Batch default flip
# ---------------------------------------------------------------------------
def test_batch_controls_defaults_outfit_prompt_mode_to_replace():
    assert BatchControls().outfit_prompt_mode == "replace"
    # legacy jsonb (no new keys) still parses and picks up the new default.
    assert BatchControls(**{"max_nudity": "medium"}).outfit_prompt_mode == "replace"


# ---------------------------------------------------------------------------
# Story-director prompt rules (WS1.c)
# ---------------------------------------------------------------------------
def test_director_prompt_requires_non_null_outfit_matching_detail():
    p = STORY_DIRECTOR_SYSTEM_PROMPT
    assert "every beat MUST set a non-null" in p         # outfit is mandatory on every beat
    assert "MUST describe the SAME garment" in p         # outfit_detail matches the outfit enum


def test_director_user_prompt_reinforces_mandatory_outfit():
    planner = VeniceScenePlanner(api_key="x")
    controls = BatchControls(start_nudity="low", max_nudity="high", story_mode=True)
    prompt = planner._build_director_user_prompt(_character(occupation="nurse"), 8, controls)
    low = prompt.lower()
    assert "every photo" in low and "never null" in low


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
