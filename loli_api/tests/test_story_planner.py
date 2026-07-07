"""
Tests for the story planner: deterministic reproducibility, count guarantee,
controls enforcement, Grok-output repair, provider selection, and vocab coverage.

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


def _fake_settings(xai="", anthropic="", provider=""):
    return SimpleNamespace(
        XAI_API_KEY=xai, XAI_BASE_URL="https://api.x.ai/v1", XAI_MODEL="grok-4",
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


# --- Grok output repair (offline) ---
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
    settings = _fake_settings(xai="", anthropic="claude-key")  # claude available, but batch is nsfw
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
