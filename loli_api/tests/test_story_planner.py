"""
Tests for the story planner: deterministic reproducibility, count guarantee,
controls enforcement, LLM-output repair, provider selection, and vocab coverage.

Runs under pytest or directly: python loli_api/tests/test_story_planner.py
"""
import asyncio
from types import SimpleNamespace

from models.enums import (
    NudityLevel, OutfitType, LocationType, TimeOfDayType, LightingType, PoseType,
)
from models.requests import PersonaOptions
from models.batch import BatchControls
from models.scene import SceneSpec
from services import scene_vocab as sv
from services import story_planner as sp
from services.story_planner import (
    Character, DeterministicScenePlanner, validate_and_repair, plan_scenes,
    _parse_arcs_json, _coerce_enum, _nudity_index,
)


def _character(occupation="nurse", likes=None, dislikes=None):
    persona = PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation=occupation, personality="temptress", relationship="girlfriend",
    )
    return Character(persona=persona, likes=likes or [], dislikes=dislikes or [])


def _fake_settings(venice="", anthropic="", provider=""):
    return SimpleNamespace(
        VENICE_API_KEY=venice, VENICE_BASE_URL="https://api.venice.ai/api/v1",
        VENICE_MODEL="venice-uncensored",
        ANTHROPIC_API_KEY=anthropic, ANTHROPIC_MODEL="claude-sonnet-4-5",
        STORY_PLANNER_PROVIDER=provider,
    )


# --- vocab coverage ---
def test_vocab_coverage():
    for loc in LocationType:
        assert sv.LOCATION_PHRASES.get(loc.value), f"missing location phrase: {loc.value}"
    for t in TimeOfDayType:
        assert sv.TIME_OF_DAY_PHRASES.get(t.value), f"missing time phrase: {t.value}"
    for li in LightingType:
        assert sv.LIGHTING_PHRASES.get(li.value), f"missing lighting phrase: {li.value}"


def test_vocab_has_no_ageon_language():
    banned = ("youthful", "childlike", "teen", "young")
    for text in list(sv.LOCATION_PHRASES.values()) + list(sv.TIME_OF_DAY_PHRASES.values()) \
            + list(sv.LIGHTING_PHRASES.values()):
        low = text.lower()
        assert not any(b in low for b in banned), f"age-down language in: {text}"


# --- batch defaults (dressed-by-default) ---
def test_batch_controls_defaults_to_low_nudity_and_natural_style():
    from models.enums import PhotoStyleType

    controls = BatchControls()
    assert controls.max_nudity == NudityLevel.LOW
    assert controls.photo_style == PhotoStyleType.NATURAL


# --- deterministic planner ---
def test_deterministic_is_reproducible():
    char = _character()
    controls = BatchControls(base_seed=42)
    a = DeterministicScenePlanner().plan_scenes_sync(char, 12, controls)
    b = DeterministicScenePlanner().plan_scenes_sync(char, 12, controls)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]


def test_count_guarantee():
    char = _character()
    for n in (1, 20, 35, 50):
        scenes = DeterministicScenePlanner().plan_scenes_sync(char, n, BatchControls(base_seed=1))
        assert len(scenes) == n, f"expected {n}, got {len(scenes)}"


def test_max_nudity_never_exceeded():
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.LOW, base_seed=1)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 20, controls)
    assert all(s.nudityLevel == NudityLevel.LOW for s in scenes)


def test_building_escalation_is_non_decreasing():
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=1)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 24, controls)
    idxs = [_nudity_index(s.nudityLevel) for s in scenes]
    assert idxs == sorted(idxs), f"not non-decreasing: {idxs}"


def test_blocked_outfit_never_appears():
    char = _character()
    controls = BatchControls(blocked_outfits=[OutfitType.NURSE_UNIFORM, OutfitType.NAKED], base_seed=3)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 30, controls)
    assert all(s.outfit != OutfitType.NURSE_UNIFORM for s in scenes)


def test_blocked_location_never_appears():
    char = _character()
    controls = BatchControls(blocked_locations=[LocationType.HOSPITAL_WARD], base_seed=3)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 30, controls)
    assert all(s.location != LocationType.HOSPITAL_WARD for s in scenes)


# --- validate_and_repair ---
def test_validate_and_repair_pads_to_count():
    char = _character()
    short = DeterministicScenePlanner().plan_scenes_sync(char, 2, BatchControls(base_seed=1))
    repaired = validate_and_repair(short, char, 6, BatchControls(base_seed=1))
    assert len(repaired) == 6
    assert [s.global_index for s in repaired] == list(range(6))


def test_validate_and_repair_clamps_nudity():
    char = _character()
    scene = SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
        nudityLevel=NudityLevel.HIGH, location=LocationType.HOME_BEDROOM,
    )
    out = validate_and_repair([scene], char, 1, BatchControls(max_nudity=NudityLevel.MEDIUM, base_seed=1))
    assert out[0].nudityLevel == NudityLevel.MEDIUM


def test_validate_and_repair_enforces_beat_pool_coherence():
    """
    An out-of-pool combination (e.g. an LLM planner going rogue) is repaired
    to something from THAT beat position's own hand-authored pool, never left
    as an incoherent pairing like a bikini in an office beat.
    """
    char = _character(occupation="nurse")  # (morning_home, on_the_ward, evening_unwind)
    controls = BatchControls(base_seed=7)
    # Beat 3 (global_index 3) is the first "on_the_ward" beat -> hospital_ward
    # + nurse_uniform only. Feed it something from a completely different pool.
    bad = SceneSpec(
        arc_id="x", arc_title="X", beat_index=0, global_index=3, beat_description="b",
        pose=PoseType.ALL_FOURS, outfit=OutfitType.BIKINI, nudityLevel=NudityLevel.LOW,
        location=LocationType.BEACH, time_of_day=TimeOfDayType.NIGHT, lighting=LightingType.NEON,
    )
    filler = [
        SceneSpec(arc_id="x", arc_title="X", beat_index=i, global_index=i, beat_description="b",
                  location=LocationType.HOME_LIVING_ROOM)
        for i in range(3)
    ]
    out = validate_and_repair(filler + [bad], char, 6, controls)
    repaired = out[3]
    assert repaired.location == LocationType.HOSPITAL_WARD
    assert repaired.outfit == OutfitType.NURSE_UNIFORM
    # Reproducible: repairing the same input twice gives the same result.
    out2 = validate_and_repair(filler + [bad], char, 6, controls)
    assert out2[3].outfit == repaired.outfit and out2[3].location == repaired.location


def test_manual_scenes_are_not_coherence_repaired():
    """
    Manual/admin-supplied scenes are an intentional exact override, not a
    planner guess — validate_and_repair must NOT force them into a beat's
    hand-authored pool (enforce_beat_pool=False), even though other repairs
    (nudity ceiling, allow/block) still apply.
    """
    char = _character(occupation="nurse")
    controls = BatchControls(base_seed=1)
    # A bikini at the beach in beat position 3 (the hospital-ward slot) would
    # be repaired away if coherence enforcement ran — it must survive here.
    manual_scene = SceneSpec(
        arc_id="manual", arc_title="Manual", beat_index=0, global_index=3, beat_description="b",
        outfit=OutfitType.BIKINI, location=LocationType.BEACH,
    )
    out = validate_and_repair([manual_scene], char, 1, controls, enforce_beat_pool=False)
    assert out[0].outfit == OutfitType.BIKINI
    assert out[0].location == LocationType.BEACH


# --- LLM output repair (offline) ---
def test_coerce_enum_repairs_near_miss():
    # The stale "sitting_casual" example (see requests.py) repairs to a real pose.
    assert _coerce_enum(PoseType, "sitting_casual") == PoseType.SITTING


def test_parse_arcs_json_valid():
    raw = (
        '{"arcs":[{"arc_id":"x","arc_title":"X","beats":['
        '{"beat_description":"b","pose":"sitting","outfit":"bikini",'
        '"nudityLevel":"low","location":"beach","time_of_day":"sunset","lighting":"golden_warm"}]}]}'
    )
    scenes = _parse_arcs_json(raw)
    assert len(scenes) == 1
    assert scenes[0].pose == PoseType.SITTING
    assert scenes[0].location == LocationType.BEACH


def test_parse_arcs_json_repairs_bad_pose_and_missing_location():
    raw = (
        '{"arcs":[{"arc_id":"x","arc_title":"X","beats":['
        '{"beat_description":"b","pose":"sitting_casual","nudityLevel":"low"}]}]}'
    )
    scenes = _parse_arcs_json(raw)
    assert len(scenes) == 1
    assert scenes[0].pose == PoseType.SITTING
    assert scenes[0].location == LocationType.HOME_LIVING_ROOM  # substituted


def test_parse_arcs_json_malformed_returns_empty():
    assert _parse_arcs_json("not json at all") == []
    assert _parse_arcs_json("") == []


# --- provider selection ---
def test_nsfw_never_selects_claude():
    char = _character()
    settings = _fake_settings(venice="", anthropic="claude-key")  # claude available, but batch is nsfw
    controls = BatchControls(content_rating="nsfw", base_seed=1)
    scenes, provider = asyncio.run(plan_scenes(char, 10, controls, settings=settings))
    assert provider == "deterministic"
    assert len(scenes) == 10


def test_provider_override_claude_on_nsfw_falls_back():
    char = _character()
    settings = _fake_settings(anthropic="claude-key")
    controls = BatchControls(content_rating="nsfw", base_seed=1)
    scenes, provider = asyncio.run(
        plan_scenes(char, 8, controls, settings=settings, provider_override="claude")
    )
    # claude is gated out of nsfw -> deterministic fallback fills the plan.
    assert provider == "deterministic"
    assert len(scenes) == 8


def test_manual_provider_uses_supplied_scenes():
    char = _character()
    settings = _fake_settings()
    manual = [{
        "beat_description": "manual beat", "pose": "sitting", "location": "cafe",
        "nudityLevel": "low",
    }]
    controls = BatchControls(base_seed=1)
    scenes, provider = asyncio.run(
        plan_scenes(char, 1, controls, settings=settings, manual_scenes=manual)
    )
    assert provider == "manual"
    assert scenes[0].location == LocationType.CAFE


# --- AI gate: identity scrub on planner free-text ---
def test_scrub_identity_strips_appearance_from_background_text():
    """
    A planner (Venice/Claude) must not be able to smuggle person-appearance
    descriptors into the background prompt: the person is described ONLY by the
    hero photo; free text describes the SCENE. The masks are the hard guarantee;
    this gate is defense-in-depth.
    """
    import models.requests as _mr
    from services.scene_mapper import scene_to_pipeline_request

    _mr.validate_source_image = lambda u: u  # bypass SSRF allowlist (offline test)
    char = _character()
    char.hero_photo_url = "https://example.com/hero.png"
    malicious = SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0,
        beat_description="a stunning young redhead with green eyes relaxes",
        location=LocationType.CAFE,
        background_text=(
            "a cozy cafe where a stunning young redhead woman with silky auburn hair, "
            "piercing green eyes and sun-tanned skin sips coffee"
        ),
    )
    out = validate_and_repair([malicious], char, 1, BatchControls(base_seed=1))
    banned = (
        "hair", "eyes", "skin", "redhead", "blonde", "brunette",
        "woman", "girl", "young", "auburn", "tanned",
    )
    for field in (out[0].background_text or "", out[0].beat_description or ""):
        low = field.lower()
        for b in banned:
            assert b not in low, f"appearance token {b!r} survived scrub: {field!r}"

    # And the final pipeline prompt built from the scene carries none of it either.
    req = scene_to_pipeline_request(char, out[0], BatchControls(base_seed=1))
    low = (req.prompt or "").lower()
    for b in banned:
        assert b not in low, f"appearance token {b!r} reached pipeline prompt: {req.prompt!r}"


def test_scrub_identity_preserves_scene_language():
    from services.story_planner import _scrub_identity
    clean = "a sunlit cafe terrace with wicker chairs, warm golden hour light, soft bokeh"
    assert _scrub_identity(clean) == clean


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
