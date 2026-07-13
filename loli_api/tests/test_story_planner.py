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
from services import outfit_vocab as ov
from services.story_planner import (
    Character, DeterministicScenePlanner, validate_and_repair, plan_scenes,
    _parse_arcs_json, _coerce_enum, _nudity_index, _nudity_ramp,
    LOCATION_NUDITY_CEILING, _location_ceiling,
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
    # PROMPT DE-GLOSS: batch default reverted to NATURAL (POLISHED's "lightly
    # retouched skin" framing was part of the plastic/glossy look the doctrine
    # removed; polished remains available as an explicit opt-in).
    assert controls.photo_style == PhotoStyleType.NATURAL


def test_story_mode_defaults_off_variety_only():
    # Story mode is retired from the admin flow: the field is accepted for API compat but
    # defaults False so every batch runs the coherent variety planner.
    assert BatchControls().story_mode is False


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


def test_default_provider_order_is_deterministic_first():
    # Variety-only: the deterministic planner is the default. Venice/Claude are NO LONGER
    # auto-selected just because a key is configured — even with BOTH keys set and no
    # explicit STORY_PLANNER_PROVIDER, planning resolves to deterministic.
    char = _character()
    settings = _fake_settings(venice="venice-key", anthropic="claude-key")
    scenes, provider = asyncio.run(
        plan_scenes(char, 12, BatchControls(base_seed=1), settings=settings)
    )
    assert provider == "deterministic"   # venice NOT auto-selected despite the key
    assert len(scenes) == 12


def test_explicit_venice_still_honored_via_setting():
    # An explicit STORY_PLANNER_PROVIDER=venice still builds a venice-first order (opt-in
    # garnish). We assert the ORDER building, not a live call: with no venice key the client
    # returns empty and planning falls back to deterministic without a network hit.
    char = _character()
    settings = _fake_settings(venice="", provider="venice")
    scenes, provider = asyncio.run(
        plan_scenes(char, 6, BatchControls(base_seed=1), settings=settings)
    )
    # venice produced nothing (no key) -> deterministic fallback, but the opt-in was honored.
    assert provider == "deterministic"
    assert len(scenes) == 6


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


# --- WS2: story-planner temperature is settings-driven (was a hardcoded 0.7) ---
def test_venice_planner_temperature_comes_from_settings():
    from services.story_planner import build_planner, VeniceScenePlanner
    settings = _fake_settings(venice="k")
    settings.STORY_PLANNER_TEMPERATURE = 0.42
    planner = build_planner("venice", settings=settings)
    assert isinstance(planner, VeniceScenePlanner)
    assert planner.temperature == 0.42
    # …and _call_venice forwards exactly that to the Venice client (no hardcoded value).
    captured: dict = {}

    async def fake_chat(messages, **kwargs):
        captured.update(kwargs)
        return None, {}

    planner._client.chat = fake_chat
    asyncio.run(planner._call_venice("hi", story_mode=True, count=4))
    assert captured["temperature"] == 0.42


def test_venice_planner_temperature_defaults_when_settings_lacks_attr():
    # A legacy/fake settings object without STORY_PLANNER_TEMPERATURE still builds (0.6 default).
    from services.story_planner import build_planner
    settings = _fake_settings(venice="k")  # no STORY_PLANNER_TEMPERATURE attribute
    planner = build_planner("venice", settings=settings)
    assert planner.temperature == 0.6


def test_planner_system_prompt_asks_for_literal_beat_description():
    from services.story_planner import PLANNER_SYSTEM_PROMPT
    low = PLANNER_SYSTEM_PROMPT.lower()
    assert "literal" in low
    assert "avoid metaphor" in low


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


# --- legacy controls jsonb back-compat (new fields default cleanly) ---
def test_legacy_controls_jsonb_parses_with_new_fields_defaulted():
    # An old `controls` jsonb row (no new keys) must still parse; new knobs default.
    controls = BatchControls(**{"max_nudity": "medium", "escalation": "building"})
    assert controls.start_nudity is None
    assert controls.outfit_denoise is None
    # Batch default flipped to "replace" (dressed-by-default avatars need explicit removal).
    assert controls.outfit_prompt_mode == "replace"


# --- nudity ramp derivation ---
def test_nudity_ramp_building_rises_from_low():
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building")
    ramp = _nudity_ramp(8, controls)
    assert ramp[0] == NudityLevel.LOW
    assert ramp[-1] == NudityLevel.HIGH
    idxs = [_nudity_index(x) for x in ramp]
    assert idxs == sorted(idxs)  # monotonic non-decreasing


def test_nudity_ramp_flat_is_constant_max_backcompat():
    # flat + no start_nudity == the old max-only ceiling behavior (constant at max).
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, escalation="flat")
    assert _nudity_ramp(6, controls) == [NudityLevel.MEDIUM] * 6


def test_nudity_ramp_explicit_start_overrides_escalation():
    controls = BatchControls(
        start_nudity=NudityLevel.MEDIUM, max_nudity=NudityLevel.HIGH, escalation="building"
    )
    ramp = _nudity_ramp(6, controls)
    assert ramp[0] == NudityLevel.MEDIUM
    assert ramp[-1] == NudityLevel.HIGH


def test_nudity_ramp_start_clamped_to_ceiling():
    controls = BatchControls(start_nudity=NudityLevel.HIGH, max_nudity=NudityLevel.LOW)
    assert _nudity_ramp(5, controls) == [NudityLevel.LOW] * 5


def test_nudity_ramp_sfw_all_low():
    controls = BatchControls(sfw_only=True, max_nudity=NudityLevel.HIGH)
    assert _nudity_ramp(6, controls) == [NudityLevel.LOW] * 6


def test_nudity_ramp_count_one_is_finish_level():
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building")
    assert _nudity_ramp(1, controls) == [NudityLevel.HIGH]


def test_deterministic_planner_honors_start_nudity():
    controls = BatchControls(
        start_nudity=NudityLevel.MEDIUM, max_nudity=NudityLevel.HIGH, base_seed=1
    )
    scenes = DeterministicScenePlanner().plan_scenes_sync(_character(), 8, controls)
    idxs = [_nudity_index(s.nudityLevel) for s in scenes]
    assert idxs[0] == _nudity_index(NudityLevel.MEDIUM)  # photo 1 starts at medium
    assert idxs == sorted(idxs)                           # non-decreasing
    assert idxs[-1] == _nudity_index(NudityLevel.HIGH)    # reaches the finish level


# --- nudity: ASSIGN exactly to the ramp (authoritative; no drip, no under/over-shoot) ---
def _flat_scenes(n, nudity, location=LocationType.HOME_BEDROOM):
    return [
        SceneSpec(arc_id="a", arc_title="A", beat_index=i, global_index=i, beat_description="b",
                  location=location, nudityLevel=nudity)
        for i in range(n)
    ]


def test_nudity_assigned_exactly_to_ramp_regardless_of_input():
    # The ramp is authoritative: whatever nudity the provider emitted (HIGH-everywhere OR
    # LOW-everywhere), each photo's level is set EXACTLY to ramp[i] — this is the anti-drip
    # invariant. Both inputs must yield the identical rising ramp.
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=1)
    ramp = _nudity_ramp(8, controls)
    for seed_nudity in (NudityLevel.HIGH, NudityLevel.LOW, NudityLevel.MEDIUM):
        out = validate_and_repair(
            _flat_scenes(8, seed_nudity), _character(), 8, controls, enforce_beat_pool=False
        )
        assert [s.nudityLevel for s in out] == ramp, f"input {seed_nudity} did not snap to the ramp"
    # And the arc still starts low and finishes at max_nudity.
    assert ramp[0] == NudityLevel.LOW
    assert ramp[-1] == NudityLevel.HIGH


def test_nudity_exact_assignment_holds_for_venice_path_scenes():
    # Venice, when opted in, emits its own (possibly wrong) nudity; the exact-assign in
    # validate_and_repair overrides it so the provider never chooses the level. A LOW-emitting
    # provider mid-batch is FORCED up to the ramp (the old clamp would have kept it low).
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=1)
    ramp = _nudity_ramp(8, controls)
    out = validate_and_repair(
        _flat_scenes(8, NudityLevel.LOW), _character(), 8, controls, enforce_beat_pool=False
    )
    assert out[-1].nudityLevel == NudityLevel.HIGH   # forced UP to the ramp finish (was kept LOW before)
    assert [s.nudityLevel for s in out] == ramp


# --- outfit-fill (medium/high scene with no outfit gets a safe garment) ---
def test_outfit_fill_never_naked_or_blocked():
    controls = BatchControls(
        max_nudity=NudityLevel.HIGH, start_nudity=NudityLevel.MEDIUM,
        blocked_outfits=[OutfitType.NAKED, OutfitType.BIKINI], base_seed=9,
    )
    out = validate_and_repair(
        _flat_scenes(6, NudityLevel.MEDIUM), _character(), 6, controls, enforce_beat_pool=False
    )
    for s in out:
        assert s.outfit is not None                 # filled (medium + no outfit)
        assert s.outfit != OutfitType.NAKED         # never NAKED
        assert s.outfit != OutfitType.BIKINI        # blocked respected


def test_outfit_fill_empty_pool_leaves_none():
    # Only NAKED allowed -> nothing safe to fill -> outfit stays None.
    controls = BatchControls(
        max_nudity=NudityLevel.HIGH, start_nudity=NudityLevel.HIGH,
        allowed_outfits=[OutfitType.NAKED], blocked_outfits=[], base_seed=1,
    )
    out = validate_and_repair(
        _flat_scenes(1, NudityLevel.HIGH), _character(), 1, controls, enforce_beat_pool=False
    )
    assert out[0].outfit is None


# --- variety repair ---
def test_variety_repairs_duplicate_pair_pose_first_and_deterministically():
    controls = BatchControls(base_seed=123)
    dup = [
        SceneSpec(arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
                  outfit=OutfitType.WHITE_SUMMER_DRESS, pose=PoseType.STANDING_LEANING,
                  location=LocationType.PARK, nudityLevel=NudityLevel.LOW),
        SceneSpec(arc_id="a", arc_title="A", beat_index=1, global_index=1, beat_description="b",
                  outfit=OutfitType.WHITE_SUMMER_DRESS, pose=PoseType.STANDING_LEANING,
                  location=LocationType.CAFE, nudityLevel=NudityLevel.LOW),
    ]
    out = validate_and_repair([s.model_copy(deep=True) for s in dup], _character(), 2, controls,
                              enforce_beat_pool=False)
    assert (out[0].outfit, out[0].pose) != (out[1].outfit, out[1].pose)  # dup broken
    # pose-before-outfit: the outfit is kept, only the pose changes.
    assert out[1].outfit == OutfitType.WHITE_SUMMER_DRESS
    assert out[1].pose != PoseType.STANDING_LEANING
    # deterministic: same input + seed -> same repair.
    out2 = validate_and_repair([s.model_copy(deep=True) for s in dup], _character(), 2, controls,
                               enforce_beat_pool=False)
    assert (out2[1].outfit, out2[1].pose) == (out[1].outfit, out[1].pose)


def test_variety_repair_respects_blocked_lists():
    controls = BatchControls(
        base_seed=5, blocked_poses=[PoseType.SITTING],
        blocked_outfits=[OutfitType.NAKED, OutfitType.BIKINI, OutfitType.COCKTAIL_DRESS],
    )
    # 3x identical (outfit,pose) at distinct locations -> dups + overused outfit fire repairs.
    same = [
        SceneSpec(arc_id="a", arc_title="A", beat_index=i, global_index=i, beat_description="b",
                  outfit=OutfitType.WHITE_SUMMER_DRESS, pose=PoseType.STANDING_LEANING,
                  location=loc, nudityLevel=NudityLevel.LOW)
        for i, loc in enumerate((LocationType.PARK, LocationType.CAFE, LocationType.GARDEN))
    ]
    out = validate_and_repair([s.model_copy(deep=True) for s in same], _character(), 3, controls,
                              enforce_beat_pool=False)
    for s in out:
        assert s.pose != PoseType.SITTING  # blocked pose never introduced
        assert s.outfit not in (OutfitType.NAKED, OutfitType.BIKINI, OutfitType.COCKTAIL_DRESS)


def test_variety_exempts_single_uniform_work_chapter():
    # A nurse's work chapter wears the one nurse_uniform across many beats — the
    # >=3-uses cap must NOT strip it (single-uniform slot exemption).
    char = _character(occupation="nurse")
    controls = BatchControls(base_seed=1, max_nudity=NudityLevel.LOW)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 12, controls)
    before = sum(1 for s in scenes if s.outfit == OutfitType.NURSE_UNIFORM)
    out = validate_and_repair([s.model_copy(deep=True) for s in scenes], char, 12, controls)
    after = sum(1 for s in out if s.outfit == OutfitType.NURSE_UNIFORM)
    assert before >= 3           # the plan really does repeat the uniform
    assert after == before       # and variety leaves the work uniform intact


def test_manual_path_bypasses_ramp_and_variety():
    controls = BatchControls(max_nudity=NudityLevel.HIGH, base_seed=1)
    manual = [
        SceneSpec(arc_id="m", arc_title="M", beat_index=0, global_index=0, beat_description="b",
                  outfit=None, pose=PoseType.STANDING_LEANING, location=LocationType.HOME_BEDROOM,
                  nudityLevel=NudityLevel.HIGH),
        SceneSpec(arc_id="m", arc_title="M", beat_index=1, global_index=1, beat_description="b",
                  outfit=None, pose=PoseType.STANDING_LEANING, location=LocationType.HOME_BEDROOM,
                  nudityLevel=NudityLevel.HIGH),
    ]
    out = validate_and_repair(
        manual, _character(), 2, controls,
        enforce_beat_pool=False, enforce_nudity_ramp=False, enforce_variety=False,
    )
    assert out[0].nudityLevel == NudityLevel.HIGH        # ramp bypassed (photo 1 stays HIGH)
    assert out[0].outfit is None                          # outfit-fill bypassed
    assert out[0].pose == out[1].pose == PoseType.STANDING_LEANING  # variety bypassed


# --- per-batch pose/location usage caps (C1b) ---
def _monoculture_scenes(n, pose=PoseType.STANDING_LEANING,
                        location=LocationType.HOME_LIVING_ROOM, pose_detail=None):
    return [
        SceneSpec(arc_id="a", arc_title="A", beat_index=i, global_index=i,
                  beat_description=f"b{i}", pose=pose, location=location,
                  pose_detail=pose_detail, nudityLevel=NudityLevel.LOW)
        for i in range(n)
    ]


def test_usage_caps_break_pose_and_location_monoculture():
    # The reported failure: a real 24-item batch used pose "standing_leaning" 8x and
    # parked whole runs in one location. Feed the repairer that exact monoculture
    # (director path: enforce_beat_pool=False, no slot pools constrain the re-picks).
    controls = BatchControls(base_seed=11)
    detail = "leaning against the doorframe, arms crossed"
    scenes = _monoculture_scenes(24, pose_detail=detail)
    out = validate_and_repair([s.model_copy(deep=True) for s in scenes], _character(), 24,
                              controls, enforce_beat_pool=False)
    pose_counts: dict = {}
    loc_counts: dict = {}
    for s in out:
        if s.pose is not None:
            pose_counts[s.pose.value] = pose_counts.get(s.pose.value, 0) + 1
        loc_counts[s.location.value] = loc_counts.get(s.location.value, 0) + 1
    assert max(pose_counts.values()) <= 3, pose_counts   # max(2, ceil(24/8)) = 3
    assert max(loc_counts.values()) <= 4, loc_counts     # max(2, ceil(24/6)) = 4
    # A re-picked pose drops its now-stale freeform pose_detail (it was authored for
    # the OLD pose, and the new reference image no longer shows that body position);
    # a kept pose keeps its detail.
    changed = kept = 0
    for orig, rep in zip(scenes, out):
        if rep.pose != orig.pose:
            changed += 1
            assert rep.pose_detail is None
        else:
            kept += 1
            assert rep.pose_detail == detail
    assert changed and kept                              # both branches exercised
    # Deterministic: same input + base_seed -> identical repair.
    out2 = validate_and_repair([s.model_copy(deep=True) for s in scenes], _character(), 24,
                               controls, enforce_beat_pool=False)
    assert [(s.pose, s.location, s.pose_detail) for s in out] == \
        [(s.pose, s.location, s.pose_detail) for s in out2]


def test_usage_caps_respect_blocked_lists():
    # Cap re-picks draw from the controls-filtered vocab only: a blocked pose or
    # location is never introduced to satisfy a cap.
    controls = BatchControls(
        base_seed=5, blocked_poses=[PoseType.SITTING],
        blocked_locations=[LocationType.BEACH, LocationType.POOLSIDE],
    )
    out = validate_and_repair(_monoculture_scenes(12), _character(), 12, controls,
                              enforce_beat_pool=False)
    for s in out:
        assert s.pose != PoseType.SITTING
        assert s.location not in (LocationType.BEACH, LocationType.POOLSIDE)
    pose_counts: dict = {}
    loc_counts: dict = {}
    for s in out:
        if s.pose is not None:
            pose_counts[s.pose.value] = pose_counts.get(s.pose.value, 0) + 1
        loc_counts[s.location.value] = loc_counts.get(s.location.value, 0) + 1
    assert max(pose_counts.values()) <= 2                # max(2, ceil(12/8)) = 2
    assert max(loc_counts.values()) <= 2                 # max(2, ceil(12/6)) = 2


def test_usage_caps_skipped_on_manual_path():
    # The manual path (enforce_variety=False) keeps an admin's exact repeats intact —
    # the caps ride the variety gate, like the pair-dedup pass.
    controls = BatchControls(base_seed=1)
    out = validate_and_repair(
        _monoculture_scenes(12), _character(), 12, controls,
        enforce_beat_pool=False, enforce_nudity_ramp=False, enforce_variety=False,
        enforce_time_ramp=False,
    )
    assert all(s.pose == PoseType.STANDING_LEANING for s in out)
    assert all(s.location == LocationType.HOME_LIVING_ROOM for s in out)


# --- time ramp derivation (period_days timeline) ---
def test_time_ramp_single_day_is_monotonic_dawn_to_night():
    ramp = sp._time_ramp(8, period_days=1)
    assert len(ramp) == 8
    idxs = [sp._time_index(t) for t in ramp]
    assert idxs == sorted(idxs), f"time bounced: {idxs}"     # monotonic non-decreasing
    assert ramp[0] == TimeOfDayType.EARLY_MORNING            # starts at dawn
    assert ramp[-1] == TimeOfDayType.NIGHT                   # ends at night


def test_time_ramp_multi_day_resets_each_day():
    ramp = sp._time_ramp(24, period_days=3)
    assert len(ramp) == 24
    sizes = sp._day_sizes(24, 3)
    assert sizes == [8, 8, 8]
    start = 0
    for size in sizes:
        seg = ramp[start:start + size]
        idxs = [sp._time_index(t) for t in seg]
        assert seg[0] == TimeOfDayType.EARLY_MORNING         # each day resets to dawn
        assert seg[-1] == TimeOfDayType.NIGHT                # each day ends at night
        assert idxs == sorted(idxs)                          # monotonic within the day
        start += size
    # across a day boundary the time DROPS (late -> dawn), proving the reset.
    assert sp._time_index(ramp[8]) < sp._time_index(ramp[7])


def test_time_ramp_short_days_spread_and_reset():
    # count < 7*period_days: still monotonic per day, spread across the ladder.
    ramp = sp._time_ramp(6, period_days=2)
    assert len(ramp) == 6
    for start in (0, 3):
        seg = ramp[start:start + 3]
        idxs = [sp._time_index(t) for t in seg]
        assert idxs == sorted(idxs)                          # monotonic within the day
        assert seg[0] == TimeOfDayType.EARLY_MORNING
        assert seg[-1] == TimeOfDayType.NIGHT
        assert len(set(idxs)) == 3                           # a 3-beat day spreads, not clustered


def test_time_ramp_count_one_is_single_reasonable_value():
    ramp = sp._time_ramp(1, period_days=1)
    assert len(ramp) == 1
    assert ramp[0] in set(TimeOfDayType)                     # a real time, no crash / no None


def test_nearest_time_in_pool_snaps_to_closest_allowed():
    T = TimeOfDayType
    assert sp._nearest_time_in_pool(T.NIGHT, (T.EVENING, T.NIGHT)) == T.NIGHT       # exact -> as-is
    assert sp._nearest_time_in_pool(T.NIGHT, (T.MORNING, T.DAYTIME)) == T.DAYTIME   # absent -> nearest
    assert sp._nearest_time_in_pool(T.DAYTIME, (T.MORNING, T.GOLDEN_HOUR)) == T.MORNING  # tie -> earlier
    assert sp._nearest_time_in_pool(T.DAYTIME, ()) == T.DAYTIME                     # empty -> unchanged


# --- deterministic planner: chronological time_of_day (the reported bug) ---
def test_deterministic_time_of_day_non_decreasing_single_day():
    # Core regression: time_of_day used to be rng.choice per beat and BOUNCED within a
    # block. Curated onto the day ramp, it must now flow forward — non-decreasing across
    # the whole single-day run.
    char = _character()
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 12, BatchControls(base_seed=7))
    idxs = [sp._time_index(s.time_of_day) for s in scenes]
    assert idxs == sorted(idxs), f"time bounced: {[s.time_of_day.value for s in scenes]}"
    assert idxs[0] == sp._time_index(TimeOfDayType.EARLY_MORNING)  # opens at dawn


def test_deterministic_time_stays_in_beat_pool():
    # Coherence guard: the curated time never leaves the beat's own hand-authored pool
    # (nearest-allowed fallback), so no incoherent forced value.
    char = _character(occupation="nurse")
    controls = BatchControls(base_seed=3)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 20, controls)
    slots = sp._beat_slots(char, 20, controls)
    for s, slot in zip(scenes, slots):
        assert s.time_of_day in slot.tmpl.time_pool


def test_deterministic_multi_day_resets_and_rotates_arcs():
    char = _character(occupation="nurse")
    controls = BatchControls(base_seed=7, period_days=3)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 24, controls)
    assert len(scenes) == 24
    sizes = sp._day_sizes(24, 3)
    bounds = []
    acc = 0
    for size in sizes:
        bounds.append(acc)
        acc += size
    # Each new day resets time downward from the previous day's late finish.
    for k in range(1, len(sizes)):
        first_of_day = bounds[k]
        last_of_prev = bounds[k] - 1
        assert sp._time_index(scenes[first_of_day].time_of_day) < \
            sp._time_index(scenes[last_of_prev].time_of_day), "no time reset at day boundary"
    # Day 1 is the occupation day; days 2+ draw from the leisure pools -> NOT all one set.
    day1_arc_ids = {scenes[i].arc_id for i in range(bounds[0], bounds[1])}
    assert not all(s.arc_id in day1_arc_ids for s in scenes), "days 2+ reused the day-1 arcs"
    all_arc_ids = {s.arc_id for s in scenes}
    assert all_arc_ids & {"lazy_day_home", "errands_and_cafe", "friends_and_date"}, \
        "no leisure arc appeared on the later days"


def test_deterministic_wrapped_beats_are_not_verbatim_repeats():
    # A short arc stretched over more beats than it authored used to emit byte-identical
    # beat_description text (the reported verbatim-repeat bug). The wrapped cycle now
    # gets a light positional variation so no two captions in the run are identical.
    char = _character(occupation="nurse")  # morning_home arc has 3 beats, sized 6 -> wraps
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 12, BatchControls(base_seed=7))
    within_arc = [s.beat_description for s in scenes if s.arc_id == "morning_home"]
    assert len(within_arc) > len(set(within_arc[:3]))       # the arc really does wrap
    assert len(within_arc) == len(set(within_arc))          # yet every caption is distinct


# --- validate_and_repair time enforcement (safety net) ---
def test_validate_enforces_time_ramp_and_manual_bypasses():
    char = _character()
    # Six flat home scenes all wrongly stamped NIGHT (an LLM ignoring the TIME PLAN).
    scattered = [
        SceneSpec(arc_id="a", arc_title="A", beat_index=i, global_index=i, beat_description="b",
                  location=LocationType.HOME_BEDROOM, time_of_day=TimeOfDayType.NIGHT)
        for i in range(6)
    ]
    controls = BatchControls(base_seed=1)
    # enforce_beat_pool=False (director path) -> no pool constrains time, ramp applied outright.
    on = validate_and_repair([s.model_copy(deep=True) for s in scattered], char, 6, controls,
                             enforce_beat_pool=False)
    assert [s.time_of_day for s in on] == sp._time_ramp(6, 1)   # curated onto the ramp
    assert any(s.time_of_day != TimeOfDayType.NIGHT for s in on)
    # Manual path (enforce_time_ramp=False) leaves the times exactly as supplied.
    off = validate_and_repair([s.model_copy(deep=True) for s in scattered], char, 6, controls,
                              enforce_beat_pool=False, enforce_nudity_ramp=False,
                              enforce_variety=False, enforce_time_ramp=False)
    assert all(s.time_of_day == TimeOfDayType.NIGHT for s in off)


# --- nudity ladder fix (5-level) regression ---
def test_nudity_ramp_reaches_revealing_after_ladder_fix():
    # The stale 3-level ladder silently collapsed 'revealing' to an all-LOW ramp.
    ramp = _nudity_ramp(5, BatchControls(max_nudity="revealing", escalation="building"))
    idxs = [_nudity_index(x) for x in ramp]
    assert idxs == sorted(idxs)                       # graded, non-decreasing
    assert ramp[0] == NudityLevel.LOW
    assert ramp[-1] == NudityLevel.REVEALING          # actually reaches revealing (not LOW)
    assert len(set(idxs)) > 1                          # a real ramp, not collapsed


def test_nudity_ramp_spans_suggestive_to_high():
    # start=suggestive, max=high spans the new 5-level ladder end to end.
    ramp = _nudity_ramp(5, BatchControls(start_nudity="suggestive", max_nudity="high"))
    assert ramp[0] == NudityLevel.SUGGESTIVE
    assert ramp[-1] == NudityLevel.HIGH
    idxs = [_nudity_index(x) for x in ramp]
    assert idxs == sorted(idxs)
    assert NudityLevel.REVEALING in ramp               # traverses the new mid-high level


# --- location <-> nudity ceiling (public-explicitness guard) ---
def test_location_nudity_ceiling_covers_every_location():
    # Every LocationType value must have a ceiling, so no location is silently unmapped
    # (the default is permissive REVEALING, but coverage is intentional not accidental).
    for loc in LocationType:
        assert loc.value in LOCATION_NUDITY_CEILING, f"missing ceiling for {loc.value}"


def test_high_ramp_never_exceeds_public_location_ceiling():
    # A public-heavy set (all city_street) with a high building ramp: no photo may end up
    # more explicit than its final location allows. Nudity is authoritative, so the guard
    # RELOCATES the over-exposed high slots to private places rather than lowering nudity.
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=7)
    out = validate_and_repair(
        _flat_scenes(8, NudityLevel.LOW, location=LocationType.CITY_STREET),
        _character(), 8, controls, enforce_beat_pool=False, enforce_variety=False,
    )
    for s in out:
        assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location)), (
            f"{s.nudityLevel} at {s.location} exceeds ceiling"
        )
    # The finish is still high — it moved to a private place, it was not toned down.
    assert out[-1].nudityLevel == NudityLevel.HIGH
    assert _location_ceiling(out[-1].location) == NudityLevel.HIGH


def test_ceiling_enforcement_preserves_monotonic_ramp():
    # Mixed public/private locations give the guard swap partners; the resulting nudity
    # sequence must stay monotonic non-decreasing (the ramp is positional and preserved).
    scenes = _flat_scenes(10, NudityLevel.LOW)
    for i, s in enumerate(scenes):
        s.location = LocationType.CITY_STREET if i % 2 == 0 else LocationType.HOME_BEDROOM
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=3)
    out = validate_and_repair(
        scenes, _character(), 10, controls,
        enforce_beat_pool=False, enforce_variety=False,
    )
    idxs = [_nudity_index(s.nudityLevel) for s in out]
    assert idxs == sorted(idxs), f"ramp no longer monotonic: {idxs}"
    for s in out:
        assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location))


def test_ceiling_enforcement_is_noop_for_sfw():
    # sfw_only -> the ramp is all-LOW, which fits every ceiling, so the guard must not move
    # or relocate anything: locations stay public and nudity stays LOW.
    controls = BatchControls(sfw_only=True, max_nudity=NudityLevel.HIGH, base_seed=1)
    out = validate_and_repair(
        _flat_scenes(6, NudityLevel.LOW, location=LocationType.CITY_STREET),
        _character(), 6, controls, enforce_beat_pool=False, enforce_variety=False,
    )
    assert all(s.nudityLevel == NudityLevel.LOW for s in out)
    assert all(s.location == LocationType.CITY_STREET for s in out)


def test_ceiling_relocation_respects_blocked_locations():
    # When relocating an over-exposed high slot, the guard must never introduce a blocked
    # location — even under the ceiling constraint. Block every private location but the
    # kitchen; relocations must land there and never on a blocked one.
    blocked = [
        LocationType.HOME_BEDROOM, LocationType.HOTEL_ROOM, LocationType.HOME_BATHROOM,
        LocationType.HOME_LIVING_ROOM, LocationType.HOME_OFFICE, LocationType.PHOTO_STUDIO,
    ]
    controls = BatchControls(
        max_nudity=NudityLevel.HIGH, escalation="building",
        blocked_locations=blocked, base_seed=2,
    )
    out = validate_and_repair(
        _flat_scenes(8, NudityLevel.LOW, location=LocationType.CITY_STREET),
        _character(), 8, controls, enforce_beat_pool=False, enforce_variety=False,
    )
    for s in out:
        assert s.location not in blocked, f"relocated onto blocked {s.location}"
        assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location))


# ---------------------------------------------------------------------------
# WS-A / A1: outfit exposure cap (label always matches what the garment can show)
# ---------------------------------------------------------------------------
import math

from models.enums import OutfitType as _OutfitType


def _planned(char, n, controls):
    """A full deterministic plan run through validate_and_repair — the real batch path."""
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, n, controls)
    return validate_and_repair(scenes, char, n, controls)


def test_exposure_cap_covers_every_outfit():
    # Every OutfitType must be mapped, so no garment is silently unmapped (the helper's
    # MEDIUM default then only guards a None passed by a caller).
    for o in OutfitType:
        assert o in ov.OUTFIT_EXPOSURE_CAP, f"missing exposure cap for {o.value}"
    # And the caps are real NudityLevels within the ladder.
    for cap in ov.OUTFIT_EXPOSURE_CAP.values():
        assert cap in set(NudityLevel)
    # NAKED is the only-and-always HIGH anchor; the reported bug item stays MEDIUM.
    assert ov.OUTFIT_EXPOSURE_CAP[OutfitType.NAKED] == NudityLevel.HIGH
    assert ov.outfit_exposure_cap(OutfitType.GRAPHIC_TEE_SHORTS) == NudityLevel.MEDIUM
    assert ov.outfit_exposure_cap(None) == NudityLevel.MEDIUM  # defensive default


def test_every_planned_item_within_outfit_cap_and_location_ceiling():
    # The core A1 guarantee, on a demanding batch (high building ramp, multi-day, nurse):
    # every item's nudity is <= its outfit's exposure cap AND <= its location's ceiling.
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    out = _planned(char, 24, controls)
    for s in out:
        if s.outfit is not None:
            assert _nudity_index(s.nudityLevel) <= _nudity_index(ov.outfit_exposure_cap(s.outfit)), (
                f"{s.nudityLevel} exceeds cap of {s.outfit} ({ov.outfit_exposure_cap(s.outfit)})"
            )
        assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location)), (
            f"{s.nudityLevel} exceeds ceiling of {s.location}"
        )


def test_high_batch_final_items_carry_high_capable_outfits():
    # A max_nudity=high batch's HIGH-labeled items must carry a HIGH-capable outfit (NAKED is
    # reachable and appears among the options when allowed) — never a dressed MEDIUM garment
    # wearing a "high" label.
    char = _character(occupation="model")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=5)
    out = _planned(char, 16, controls)
    high_items = [s for s in out if s.nudityLevel == NudityLevel.HIGH]
    assert high_items, "expected at least one HIGH item in a high building ramp"
    for s in high_items:
        assert s.outfit is not None
        assert ov.outfit_exposure_cap(s.outfit) == NudityLevel.HIGH, (
            f"HIGH item wears {s.outfit} capped at {ov.outfit_exposure_cap(s.outfit)}"
        )
    # NAKED is reachable: with the exposure re-pick pool including it, a high batch that does
    # not block NAKED can land it (assert it is at least an eligible HIGH-capable option).
    assert ov.OUTFIT_EXPOSURE_CAP[OutfitType.NAKED] == NudityLevel.HIGH


def test_exposure_last_resort_lowers_label_when_no_high_capable_allowed():
    # Documented monotonicity EXCEPTION: block NAKED and every non-naked HIGH-capable outfit
    # (satin_robe/kimono/trench_coat). Now nothing can honestly render HIGH, so the guard
    # lowers the label to the best achievable cap (REVEALING) rather than lie — truthful
    # label beats reaching max.
    blocked = [OutfitType.NAKED, OutfitType.SATIN_ROBE, OutfitType.KIMONO, OutfitType.TRENCH_COAT]
    char = _character(occupation="model")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             blocked_outfits=blocked, base_seed=3)
    out = _planned(char, 12, controls)
    assert all(s.outfit not in blocked for s in out), "a blocked outfit was introduced"
    # No item reaches HIGH (no allowed garment can render it) — the truthful dip.
    assert max(_nudity_index(s.nudityLevel) for s in out) == _nudity_index(NudityLevel.REVEALING)
    # But every label is still honest w.r.t. its garment.
    for s in out:
        if s.outfit is not None:
            assert _nudity_index(s.nudityLevel) <= _nudity_index(ov.outfit_exposure_cap(s.outfit))


def test_exposure_cap_pass_is_byte_identical_noop_for_sfw():
    # A1 contract: the exposure-cap pass must not touch an sfw batch (all-LOW ramp fits every
    # garment). Assert the function itself is identity on sfw input.
    char = _character()
    controls = BatchControls(sfw_only=True, max_nudity=NudityLevel.HIGH, base_seed=1)
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, 12, controls)
    before = [s.model_dump() for s in scenes]
    sp._enforce_outfit_exposure_cap(scenes, _nudity_ramp(12, controls), controls)
    assert [s.model_dump() for s in scenes] == before
    # And a full sfw plan stays LOW with no NAKED introduced.
    out = _planned(char, 12, controls)
    assert all(s.nudityLevel == NudityLevel.LOW for s in out)
    assert all(s.outfit != OutfitType.NAKED for s in out)


def test_exposure_repick_never_introduces_blocked_outfit():
    # An exposure re-pick draws only from the controls-allowed pool: a blocked outfit is never
    # introduced to satisfy a cap, even under a demanding high ramp.
    blocked = [OutfitType.NAKED, OutfitType.BIKINI, OutfitType.SATIN_SLIP_DRESS]
    char = _character(occupation="model")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             blocked_outfits=blocked, base_seed=9)
    out = _planned(char, 16, controls)
    assert all(s.outfit not in blocked for s in out)


# ---------------------------------------------------------------------------
# WS-A / A2: conscious-model variety — per-item expression + candid share
# ---------------------------------------------------------------------------
def test_every_item_has_an_expression():
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, base_seed=4)
    out = _planned(char, 16, controls)
    assert all(s.expression for s in out), "an item was left with no expression"
    # Every assigned expression comes from the batch pool (survives _scrub_expression intact).
    for s in out:
        assert s.expression in set(sp._BATCH_EXPRESSION_POOL)


def test_expressions_are_varied_at_least_four_distinct_per_eight():
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, base_seed=4)
    out = _planned(char, 16, controls)
    exprs = [s.expression for s in out]
    for start in range(0, len(exprs) - 7):
        window = exprs[start:start + 8]
        assert len(set(window)) >= 4, f"window {start} too repetitive: {window}"


def test_no_adjacent_duplicate_expressions():
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    out = _planned(char, 24, controls)
    for i in range(1, len(out)):
        assert out[i].expression != out[i - 1].expression, f"adjacent expression dup at {i}"


def test_candid_share_within_band():
    # ~1/3 of items carry a CANDID (camera-unaware) expression; the band is generous.
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, base_seed=4)
    out = _planned(char, 24, controls)
    candid = sum(1 for s in out if s.expression in set(sp._BATCH_EXPRESSIONS_CANDID))
    share = candid / len(out)
    assert 0.25 <= share <= 0.45, f"candid share {share} outside band"


def test_expressions_are_seeded_reproducible():
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=13)
    a = _planned(char, 20, controls)
    b = _planned(char, 20, controls)
    assert [s.expression for s in a] == [s.expression for s in b]


def test_expression_survives_scrub_unchanged():
    # The pool strings must carry NO facial-feature/identity tokens, so _scrub_expression is a
    # no-op on them (otherwise the render would receive a gutted string).
    from services.story_planner import _scrub_expression
    for e in sp._BATCH_EXPRESSION_POOL:
        assert _scrub_expression(e) == e, f"scrub altered pool expression: {e!r}"


# ---------------------------------------------------------------------------
# WS-A / A2: pose adjacency + GLOBAL pose usage cap
# ---------------------------------------------------------------------------
def test_no_adjacent_duplicate_poses_in_twelve_item_plan():
    # No identical pose in any window of 2 (consecutive), on a template with enough pose
    # variety (nurse, single day).
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, base_seed=21)
    out = _planned(char, 12, controls)
    for i in range(1, len(out)):
        if out[i].pose is not None and out[i - 1].pose is not None:
            assert out[i].pose != out[i - 1].pose, f"adjacent pose dup at {i}: {out[i].pose}"


def test_pose_cap_is_global_across_multi_day_batch():
    # The reported "standing_leaning 8x in a 24-item batch": the pose usage cap is GLOBAL
    # across the whole (multi-day) batch, so no pose exceeds max(2, ceil(24/8)) = 3. Before
    # the fix a slot-constrained re-pick left overflow "unresolved"; the broadened fallback
    # makes the global cap bite.
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    out = _planned(char, 24, controls)
    cap = max(2, math.ceil(24 / 8))
    counts: dict = {}
    for s in out:
        if s.pose is not None:
            counts[s.pose.value] = counts.get(s.pose.value, 0) + 1
    assert max(counts.values()) <= cap, counts
    # …and adjacency still holds alongside the global cap.
    for i in range(1, len(out)):
        if out[i].pose is not None and out[i - 1].pose is not None:
            assert out[i].pose != out[i - 1].pose


# ---------------------------------------------------------------------------
# WS-A / A2 (coordinator add): mood-phrase monotony — gate mood tags
# ---------------------------------------------------------------------------
def test_mood_tags_present_on_about_one_third():
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    out = _planned(char, 24, controls)
    with_mood = sum(1 for s in out if s.mood_kinks or s.mood_personality)
    share = with_mood / len(out)
    assert 0.2 <= share <= 0.5, f"mood share {share} outside band"


def test_mood_tags_absent_on_low_and_public_items():
    # The classroom/street/office fix: no LOW item and no public (SUGGESTIVE-ceiling) item may
    # carry the intimate "sultry, seductive" mood tail.
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    out = _planned(char, 24, controls)
    for s in out:
        if s.mood_kinks or s.mood_personality:
            assert s.nudityLevel != NudityLevel.LOW, "mood on a LOW item"
            assert _location_ceiling(s.location) != NudityLevel.SUGGESTIVE, (
                f"mood on a public {s.location} item"
            )


def test_mood_tags_are_seeded_reproducible():
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    a = _planned(char, 24, controls)
    b = _planned(char, 24, controls)
    assert [(s.mood_kinks, s.mood_personality) for s in a] == \
        [(s.mood_kinks, s.mood_personality) for s in b]


def test_sfw_batch_carries_no_mood_tags():
    # sfw -> all LOW -> nothing mood-eligible -> no mood tags anywhere.
    char = _character(occupation="nurse")
    controls = BatchControls(sfw_only=True, max_nudity=NudityLevel.HIGH, base_seed=7)
    out = _planned(char, 12, controls)
    assert all(not (s.mood_kinks or s.mood_personality) for s in out)


# ---------------------------------------------------------------------------
# WS-B / Phase B2: trait-profile bias in the planner
# ---------------------------------------------------------------------------
import random as _random  # noqa: E402
from models.enums import DemeanorType, WardrobeStyleType  # noqa: E402
from services.story_planner import (  # noqa: E402
    _weighted_pick, _prefer_wardrobe, _allowed_outfit_pool,
    _OUTFIT_PHRASE_MAP, _POSE_PHRASE_MAP, DEMEANOR_POSE_FAVOR, _DEMEANOR_EXPRESSION_FAVOR,
)
from services.outfit_vocab import outfits_for_styles, OUTFIT_STYLE_TAGS  # noqa: E402


def test_weighted_pick_favored_is_about_3x():
    # A favored candidate (weight 3.0) is picked ~3x as often as a non-favored one (1.0).
    pool = [OutfitType.COCKTAIL_DRESS, OutfitType.BUSINESS_SUIT]
    favored = {OutfitType.COCKTAIL_DRESS}
    counts = {o: 0 for o in pool}
    rng = _random.Random(0)
    for _ in range(6000):
        counts[_weighted_pick(pool, rng, set(), set(), {}, favored=favored)] += 1
    ratio = counts[OutfitType.COCKTAIL_DRESS] / counts[OutfitType.BUSINESS_SUIT]
    assert 2.5 < ratio < 3.6, f"favored ratio {ratio:.2f} not ~3x"


def test_weighted_pick_favored_weight_two_for_poses():
    pool = [PoseType.LYING_BACK, PoseType.STANDING_LEANING]
    favored = {PoseType.LYING_BACK}
    counts = {p: 0 for p in pool}
    rng = _random.Random(0)
    for _ in range(6000):
        counts[_weighted_pick(pool, rng, set(), set(), {}, favored=favored, favored_weight=2.0)] += 1
    ratio = counts[PoseType.LYING_BACK] / counts[PoseType.STANDING_LEANING]
    assert 1.6 < ratio < 2.4, f"pose favored ratio {ratio:.2f} not ~2x"


def test_like_and_favored_are_maxed_not_multiplied():
    # A candidate that is BOTH like-matched AND favored is weighted 3.0, not 9.0.
    pool = [OutfitType.RED_EVENING_GOWN, OutfitType.BUSINESS_SUIT]
    counts = {o: 0 for o in pool}
    rng = _random.Random(0)
    for _ in range(6000):
        # RED_EVENING_GOWN is both liked ("gown") and favored -> still 3.0 vs 1.0.
        counts[_weighted_pick(pool, rng, {"gown"}, set(), _OUTFIT_PHRASE_MAP,
                              favored={OutfitType.RED_EVENING_GOWN})] += 1
    ratio = counts[OutfitType.RED_EVENING_GOWN] / counts[OutfitType.BUSINESS_SUIT]
    assert 2.5 < ratio < 3.6, f"like+favored ratio {ratio:.2f} should be ~3x (maxed), not ~9x"


def test_like_gown_boosts_evening_gown_via_phrase_map():
    # The phrase map makes a free-text like ("gown") match RED_EVENING_GOWN's garment words.
    pool = [OutfitType.RED_EVENING_GOWN, OutfitType.BUSINESS_SUIT]
    counts = {o: 0 for o in pool}
    rng = _random.Random(1)
    for _ in range(6000):
        counts[_weighted_pick(pool, rng, {"gown"}, set(), _OUTFIT_PHRASE_MAP)] += 1
    assert counts[OutfitType.RED_EVENING_GOWN] > 2 * counts[OutfitType.BUSINESS_SUIT]


def test_dislike_never_empties_the_pool():
    # A dislike that matches the ONLY candidate must not empty the pool (fallback to it).
    rng = _random.Random(0)
    res = _weighted_pick([OutfitType.RED_EVENING_GOWN], rng, set(), {"gown"}, _OUTFIT_PHRASE_MAP)
    assert res == OutfitType.RED_EVENING_GOWN


def test_prefer_wardrobe_intersect_fallback_and_uniform_bypass():
    pool = [OutfitType.COCKTAIL_DRESS, OutfitType.RED_EVENING_GOWN, OutfitType.GYM_SET]
    # >=2 in wardrobe -> use the soft subset.
    c2 = BatchControls(wardrobe_outfits=[OutfitType.COCKTAIL_DRESS, OutfitType.RED_EVENING_GOWN])
    assert _prefer_wardrobe(pool, c2, min_keep=2) == [OutfitType.COCKTAIL_DRESS, OutfitType.RED_EVENING_GOWN]
    # only 1 in wardrobe -> fallback to the full pool (never a 1-option choke).
    c1 = BatchControls(wardrobe_outfits=[OutfitType.COCKTAIL_DRESS])
    assert _prefer_wardrobe(pool, c1, min_keep=2) == pool
    # a UNIFORM is always retained even when not in the wardrobe set.
    pool_u = [OutfitType.COCKTAIL_DRESS, OutfitType.NURSE_UNIFORM]
    assert _prefer_wardrobe(pool_u, c1, min_keep=2) == pool_u
    # no wardrobe_outfits -> no-op (byte-identical, the regression-safe path).
    assert _prefer_wardrobe(pool, BatchControls(), min_keep=2) == pool


def test_allowed_outfit_pool_inherits_wardrobe_bias():
    from types import SimpleNamespace
    tmpl = SimpleNamespace(outfit_pool=(
        OutfitType.COCKTAIL_DRESS, OutfitType.RED_EVENING_GOWN, OutfitType.GYM_SET,
    ))
    c = BatchControls(wardrobe_outfits=[OutfitType.COCKTAIL_DRESS, OutfitType.RED_EVENING_GOWN])
    assert set(_allowed_outfit_pool(tmpl, c)) == {OutfitType.COCKTAIL_DRESS, OutfitType.RED_EVENING_GOWN}


def test_wardrobe_bias_never_breaks_cap_or_ceiling_and_cap_beats_wardrobe():
    # A sporty wardrobe is ALL MEDIUM-capped; on a HIGH batch the exposure pass must still
    # reach HIGH via a non-wardrobe HIGH-capable garment (cap compliance beats wardrobe),
    # and no item may ever exceed its outfit cap or location ceiling.
    from services.outfit_vocab import outfit_exposure_cap
    char = _character(occupation="model")
    controls = BatchControls(
        max_nudity=NudityLevel.HIGH, escalation="building", base_seed=5,
        wardrobe_outfits=sorted(outfits_for_styles([WardrobeStyleType.SPORTY,
                                                    WardrobeStyleType.STREETWEAR]),
                                key=lambda o: o.value),
    )
    out = _planned(char, 20, controls)
    for s in out:
        if s.outfit is not None:
            assert _nudity_index(s.nudityLevel) <= _nudity_index(outfit_exposure_cap(s.outfit))
        assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location))
    highs = [s for s in out if s.nudityLevel == NudityLevel.HIGH]
    assert highs, "a HIGH building batch should reach HIGH"
    for s in highs:
        assert s.outfit is not None and outfit_exposure_cap(s.outfit) == NudityLevel.HIGH


def test_demeanor_pose_favor_biases_pose_pick():
    fav = DEMEANOR_POSE_FAVOR[DemeanorType.SULTRY]           # {lying_back, bending_over, kneeling}
    assert PoseType.STANDING_LEANING not in fav
    pool = [PoseType.LYING_BACK, PoseType.STANDING_LEANING]
    counts = {p: 0 for p in pool}
    rng = _random.Random(0)
    for _ in range(6000):
        counts[_weighted_pick(pool, rng, set(), set(), _POSE_PHRASE_MAP,
                              favored=fav, favored_weight=2.0)] += 1
    assert counts[PoseType.LYING_BACK] > counts[PoseType.STANDING_LEANING]


# --- culture favored_poses (Stage 3): favored_strong at 3.0 ---
def test_weighted_pick_favored_strong_none_is_byte_identical():
    # favored_strong defaulting/explicit-None must leave the seeded draw unchanged.
    pool = [OutfitType.COCKTAIL_DRESS, OutfitType.BUSINESS_SUIT, OutfitType.GYM_SET]
    for seed in range(60):
        a = _weighted_pick(
            pool, _random.Random(seed), {"gown"}, set(), _OUTFIT_PHRASE_MAP,
            favored={OutfitType.COCKTAIL_DRESS})
        b = _weighted_pick(
            pool, _random.Random(seed), {"gown"}, set(), _OUTFIT_PHRASE_MAP,
            favored={OutfitType.COCKTAIL_DRESS}, favored_strong=None)
        assert a == b, seed


def test_favored_strong_alone_is_about_3x():
    pool = [OutfitType.COCKTAIL_DRESS, OutfitType.BUSINESS_SUIT]
    counts = {o: 0 for o in pool}
    rng = _random.Random(0)
    for _ in range(6000):
        counts[_weighted_pick(pool, rng, set(), set(), {},
                              favored_strong={OutfitType.COCKTAIL_DRESS})] += 1
    ratio = counts[OutfitType.COCKTAIL_DRESS] / counts[OutfitType.BUSINESS_SUIT]
    assert 2.5 < ratio < 3.6, f"favored_strong ratio {ratio:.2f} not ~3x"


def test_like_favored_and_strong_are_maxed_not_compounded():
    # A candidate that is liked AND favored AND strong-favored is 3.0, never compounded.
    pool = [OutfitType.RED_EVENING_GOWN, OutfitType.BUSINESS_SUIT]
    counts = {o: 0 for o in pool}
    rng = _random.Random(0)
    for _ in range(6000):
        counts[_weighted_pick(
            pool, rng, {"gown"}, set(), _OUTFIT_PHRASE_MAP,
            favored={OutfitType.RED_EVENING_GOWN},
            favored_strong={OutfitType.RED_EVENING_GOWN},
        )] += 1
    ratio = counts[OutfitType.RED_EVENING_GOWN] / counts[OutfitType.BUSINESS_SUIT]
    assert 2.5 < ratio < 3.6, f"like+favored+strong ratio {ratio:.2f} should be ~3x (maxed)"


def test_favored_poses_bias_pick_pose_within_beat_pool():
    # controls.favored_poses (culture-derived) biases _pick_pose ~3x, but the candidate pool
    # stays the beat's authored pose pool — a favored pose is only ever re-weighted, and a
    # non-authored favored pose is never introduced.
    planner = DeterministicScenePlanner()
    pool = [PoseType.LYING_BACK, PoseType.STANDING_LEANING]  # neither is athletic
    tmpl = SimpleNamespace(pose_pool=list(pool))
    controls = BatchControls(base_seed=1, favored_poses=[PoseType.LYING_BACK])
    counts = {p: 0 for p in pool}
    rng = _random.Random(0)
    for _ in range(6000):
        p = planner._pick_pose(tmpl, rng, set(), set(), controls)
        assert p in pool  # never outside the beat's authored pool
        counts[p] += 1
    ratio = counts[PoseType.LYING_BACK] / counts[PoseType.STANDING_LEANING]
    assert 2.5 < ratio < 3.6, f"favored-pose ratio {ratio:.2f} not ~3x"


def test_favored_pose_outside_beat_pool_is_never_introduced():
    planner = DeterministicScenePlanner()
    pool = [PoseType.LYING_BACK, PoseType.STANDING_LEANING]
    tmpl = SimpleNamespace(pose_pool=list(pool))
    # KNEELING is a valid pose but NOT in this beat's pool — culture must never add it.
    controls = BatchControls(base_seed=1, favored_poses=[PoseType.KNEELING])
    rng = _random.Random(0)
    for _ in range(500):
        assert planner._pick_pose(tmpl, rng, set(), set(), controls) in pool


def test_plan_with_culture_merged_controls_passes_invariants():
    # Merge a culture (no profile) into controls, then run the real batch path and assert
    # count guarantee + nudity ceiling + no NAKED + seeded reproducibility hold.
    from services import trait_profile_merge as tpm
    base = _character(occupation="model")
    c0 = BatchControls(max_nudity=NudityLevel.MEDIUM, escalation="building", base_seed=7)
    controls, likes, dislikes = tpm.apply_trait_profile(c0, [], [], None, "model", culture="sporty_gym")
    assert controls.favored_poses  # culture actually populated the pose bias
    char = Character(persona=base.persona, likes=likes, dislikes=dislikes)
    scenes = _planned(char, 24, controls)
    assert len(scenes) == 24
    for s in scenes:
        assert s.outfit != OutfitType.NAKED
        assert _nudity_index(s.nudityLevel) <= _nudity_index(NudityLevel.MEDIUM)
        assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location))
    scenes_b = _planned(char, 24, controls)
    assert [s.pose for s in scenes] == [s.pose for s in scenes_b]


def test_every_demeanor_has_pose_and_expression_favor():
    for d in DemeanorType:
        assert DEMEANOR_POSE_FAVOR.get(d), f"no pose favor for {d}"
        assert all(isinstance(p, PoseType) for p in DEMEANOR_POSE_FAVOR[d])
        favor = _DEMEANOR_EXPRESSION_FAVOR.get(d)
        assert favor, f"no expression favor for {d}"
        # every favored expression is a real batch-pool string
        assert favor <= set(sp._BATCH_EXPRESSION_POOL), f"{d} favors a non-pool expression"
        # >=2 from EACH register so both can be biased without starving.
        assert len(favor & set(sp._BATCH_EXPRESSIONS_CAMERA_AWARE)) >= 2
        assert len(favor & set(sp._BATCH_EXPRESSIONS_CANDID)) >= 2


def test_demeanor_biases_batch_expressions_toward_consistent_states():
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, base_seed=4, demeanor=[DemeanorType.SHY])
    out = _planned(char, 16, controls)
    favor = _DEMEANOR_EXPRESSION_FAVOR[DemeanorType.SHY]
    hits = sum(1 for s in out if s.expression in favor)
    assert hits >= 12, f"only {hits}/16 expressions were demeanor-consistent"
    # invariants preserved: non-null + no adjacent duplicates.
    assert all(s.expression for s in out)
    assert all(out[i].expression != out[i - 1].expression for i in range(1, len(out)))


def test_no_profile_fields_byte_identical_regression_lock():
    # THE regression lock: with none of the new profile-derived fields set, the plan is
    # byte-identical to the pre-B2 behavior under the same seed. A plain controls and one
    # with every new field EXPLICITLY None must produce identical plans (no likes/dislikes,
    # so the newly-wired phrase maps are inert too).
    char = _character(occupation="nurse")
    plain = BatchControls(max_nudity=NudityLevel.MEDIUM, escalation="building", base_seed=42)
    explicit_none = BatchControls(
        max_nudity=NudityLevel.MEDIUM, escalation="building", base_seed=42,
        wardrobe_outfits=None, favored_outfits=None, favored_locations=None,
        demeanor=None, interior_style=None, color_palette=None,
    )
    a = _planned(char, 24, plain)
    b = _planned(char, 24, explicit_none)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]


def test_profile_fields_actually_change_the_plan():
    # The companion to the regression lock: proving the machinery is wired, a wardrobe +
    # favored + demeanor bias DOES change the plan for the same seed (at minimum via the
    # demeanor-biased expressions; wardrobe/favored outfit shifts are proven separately in
    # the unit tests above and the trait_batch integration test).
    char = _character(occupation="student")
    base = BatchControls(max_nudity=NudityLevel.MEDIUM, escalation="building", base_seed=42)
    biased = base.model_copy(update={
        "wardrobe_outfits": sorted(outfits_for_styles([WardrobeStyleType.SPORTY,
                                                        WardrobeStyleType.STREETWEAR]),
                                   key=lambda o: o.value),
        "favored_outfits": [OutfitType.GYM_SET],
        "demeanor": [DemeanorType.ENERGETIC],
    })
    a = _planned(char, 24, base)
    b = _planned(char, 24, biased)
    assert [s.model_dump() for s in a] != [s.model_dump() for s in b]
    # And the demeanor's fingerprint is visible in the expressions specifically.
    favor = _DEMEANOR_EXPRESSION_FAVOR[DemeanorType.ENERGETIC]
    assert sum(1 for s in b if s.expression in favor) >= 12


# ---------------------------------------------------------------------------
# WS-P: pose <-> outfit (and pose <-> location) compatibility
# ---------------------------------------------------------------------------
from services import story_templates as _st  # noqa: E402
from services.outfit_vocab import outfit_exposure_cap as _exposure_cap  # noqa: E402

# Dress/gown-class outfits — the garments an ATHLETIC pose must never pair with.
_DRESS_CLASS = {
    OutfitType.RED_EVENING_GOWN, OutfitType.LITTLE_BLACK_DRESS, OutfitType.WHITE_SUMMER_DRESS,
    OutfitType.FLORAL_MAXI_DRESS, OutfitType.COCKTAIL_DRESS, OutfitType.BODYCON_DRESS,
    OutfitType.VELVET_DRESS, OutfitType.SATIN_SLIP_DRESS, OutfitType.POLKA_DOT_DRESS_50S,
    OutfitType.SEQUIN_TOP_SKIRT, OutfitType.RED_EVENING_GOWN,
}
_FORMAL_WARDROBE = [
    OutfitType.VELVET_DRESS, OutfitType.FLORAL_MAXI_DRESS, OutfitType.COCKTAIL_DRESS,
    OutfitType.RED_EVENING_GOWN, OutfitType.LITTLE_BLACK_DRESS, OutfitType.SATIN_SLIP_DRESS,
]


def _planned_without_ws_p(char, n, controls):
    """A full plan with EVERY WS-P effect disabled (athletic-pose drop + the pose-compat pass +
    the compat check the adjacency pass gained), by monkeypatching the module functions. Manual
    save/restore (no pytest fixture) so the file still runs under the __main__ runner."""
    saved = (sp._enforce_pose_compat, sp._athletic_poses_allowed, sp._pose_outfit_ok)
    sp._enforce_pose_compat = lambda scenes, slots, controls: scenes
    sp._athletic_poses_allowed = lambda controls: True
    sp._pose_outfit_ok = lambda pose, outfit: True
    try:
        return _planned(char, n, controls)
    finally:
        sp._enforce_pose_compat, sp._athletic_poses_allowed, sp._pose_outfit_ok = saved


def test_ws_p_athletic_pose_set_and_compat_map():
    # The athletic set is exactly jogging + squatting; POSE_OUTFIT_COMPAT is keyed by those
    # values and every athletic pose requires the {sporty, streetwear, casual_minimal} styles.
    assert sp.ATHLETIC_POSES == frozenset({PoseType.JOGGING, PoseType.SQUATTING})
    wanted = {WardrobeStyleType.SPORTY, WardrobeStyleType.STREETWEAR, WardrobeStyleType.CASUAL_MINIMAL}
    assert set(sp.POSE_OUTFIT_COMPAT) == {p.value for p in sp.ATHLETIC_POSES}
    for required in sp.POSE_OUTFIT_COMPAT.values():
        assert set(required) == wanted


def test_ws_p_pose_outfit_ok_semantics():
    # Athletic pose blocked on a dress; allowed on activewear/streetwear/casual; uniforms and a
    # None outfit are exempt; a non-athletic pose is unconstrained.
    assert not sp._pose_outfit_ok(PoseType.JOGGING, OutfitType.VELVET_DRESS)
    assert not sp._pose_outfit_ok(PoseType.SQUATTING, OutfitType.RED_EVENING_GOWN)
    assert sp._pose_outfit_ok(PoseType.JOGGING, OutfitType.GYM_SET)          # sporty
    assert sp._pose_outfit_ok(PoseType.JOGGING, OutfitType.DENIM_JACKET_JEANS)  # casual_minimal/streetwear
    assert sp._pose_outfit_ok(PoseType.JOGGING, OutfitType.OVERSIZED_STREETWEAR)  # streetwear
    assert sp._pose_outfit_ok(PoseType.JOGGING, OutfitType.NURSE_UNIFORM)    # uniform exempt
    assert sp._pose_outfit_ok(PoseType.JOGGING, None)                        # no garment -> nothing to conflict
    assert sp._pose_outfit_ok(PoseType.SITTING, OutfitType.VELVET_DRESS)     # non-athletic pose unconstrained
    # _outfit_is_athletic: dresses/gowns/uniforms are not athletic; activewear/streetwear/casual are.
    assert not sp._outfit_is_athletic(OutfitType.VELVET_DRESS)
    assert not sp._outfit_is_athletic(OutfitType.NURSE_UNIFORM)
    assert sp._outfit_is_athletic(OutfitType.RUNNING_GEAR)
    assert sp._outfit_is_athletic(OutfitType.CROP_TOP_CARGO)


def test_ws_p_athletic_compatible_outfit_set_matches_style_intersection():
    # The athletic-compatible outfits are exactly those whose OUTFIT_STYLE_TAGS intersect
    # {sporty, streetwear, casual_minimal} — activewear/streetwear/casual IN, dresses/gowns OUT.
    compat = {o for o in OutfitType if sp._outfit_is_athletic(o)}
    for o in (OutfitType.YOGA_OUTFIT, OutfitType.RUNNING_GEAR, OutfitType.GYM_SET,
              OutfitType.DENIM_JACKET_JEANS, OutfitType.GRAPHIC_TEE_SHORTS,
              OutfitType.HOODIE_JOGGERS, OutfitType.OVERSIZED_STREETWEAR):
        assert o in compat, o
    for o in _DRESS_CLASS | sp._UNIFORM_OUTFITS:
        assert o not in compat, o


def test_formal_wardrobe_drops_athletic_poses_entirely_any_seed():
    # THE evidence case: a dress/gown-only wardrobe (velvet/maxi/...) owns no athletic-compatible
    # outfit, so athletic poses are removed from the batch's pose pools UP FRONT — under every
    # seed, occupation and period length, no athletic pose appears at all (and, a fortiori, never
    # on a dress).
    assert not sp._athletic_poses_allowed(BatchControls(wardrobe_outfits=_FORMAL_WARDROBE))
    for occ in ("model", "nurse", "student", "singer_musician"):
        char = _character(occupation=occ)
        for seed in range(1, 13):
            for pd in (1, 3):
                controls = BatchControls(
                    max_nudity=NudityLevel.HIGH, escalation="building", period_days=pd,
                    base_seed=seed, wardrobe_outfits=_FORMAL_WARDROBE,
                )
                out = _planned(char, 24, controls)
                assert not any(s.pose in sp.ATHLETIC_POSES for s in out), (occ, seed, pd)
                assert not any(
                    s.pose in sp.ATHLETIC_POSES and s.outfit in _DRESS_CLASS for s in out
                ), (occ, seed, pd)


def test_athletic_poses_survive_sporty_wardrobe_only_on_compatible_outfits():
    # With a sporty/streetwear wardrobe, athletic poses may appear — but ONLY on an
    # athletic-compatible (or uniform/None) outfit, never a dress.
    sporty = sorted(outfits_for_styles([WardrobeStyleType.SPORTY, WardrobeStyleType.STREETWEAR]),
                    key=lambda o: o.value)
    assert sp._athletic_poses_allowed(BatchControls(wardrobe_outfits=sporty))
    seen_athletic = False
    for seed in range(1, 20):
        controls = BatchControls(
            max_nudity=NudityLevel.MEDIUM, escalation="building", period_days=2,
            base_seed=seed, wardrobe_outfits=sporty,
        )
        out = _planned(_character(occupation="fitness_coach"), 16, controls)
        for s in out:
            if s.pose in sp.ATHLETIC_POSES:
                seen_athletic = True
                assert sp._pose_outfit_ok(s.pose, s.outfit), (seed, s.pose, s.outfit)
                assert s.outfit not in _DRESS_CLASS, (seed, s.pose, s.outfit)
    assert seen_athletic, "a sporty wardrobe should still produce some athletic poses"


def test_jogging_only_in_outdoor_or_gym_locations_any_seed():
    # Folds in the "jogging @ cafe" chip: jogging renders only on a runnable outdoor path or a
    # gym — never a cafe/garden/poolside/rooftop. And every scene stays pose<->location and
    # pose<->outfit coherent.
    jog_ok = sp._POSE_LOCATION_GUARD[PoseType.JOGGING.value]
    assert LocationType.CAFE.value not in jog_ok
    for occ in ("student", "model", "yoga_instructor", "teacher", "nurse"):
        char = _character(occupation=occ)
        for seed in range(1, 26):
            controls = BatchControls(max_nudity=NudityLevel.MEDIUM, escalation="building",
                                     period_days=2, base_seed=seed)
            out = _planned(char, 16, controls)
            for s in out:
                if s.pose == PoseType.JOGGING:
                    assert s.location.value in jog_ok, (occ, seed, s.location.value)
                assert sp._pose_ok_at(s.pose, s.location), (occ, seed, s.pose, s.location)
                assert sp._pose_outfit_ok(s.pose, s.outfit), (occ, seed, s.pose, s.outfit)


def test_pose_location_guard_never_breaks_authored_beats_except_jogging_cafe():
    # The guard is a coherence-correct SUPERSET of every hand-authored (pose, location) pairing
    # the planner can produce — the SOLE deliberate exclusion is jogging @ cafe (the fix). If a
    # future template authors a new pairing outside the guard, this test flags it (the compat
    # pass would otherwise silently "repair" a coherent beat).
    arcs = {}
    for lst in _st.ARC_TEMPLATES.values():
        for a in lst:
            arcs[a.arc_id] = a
    for a in _st.GENERIC_ARCS:
        arcs[a.arc_id] = a
    for d in range(0, 6):
        for a in _st.leisure_arcs_for_day(d):
            arcs[a.arc_id] = a
    rejected = set()
    for a in arcs.values():
        for beat in a.beats:
            for pose in beat.pose_pool:
                for loc in beat.location_pool:
                    if not sp._pose_ok_at(pose, loc):
                        rejected.add((pose.value, loc.value))
    assert rejected == {(PoseType.JOGGING.value, LocationType.CAFE.value)}, rejected


def test_ws_p_preserves_all_invariants_on_24_item_multiday_plan():
    # Combined-invariant lock on a 24-item, multi-day plan that DOES need pose-compat repair.
    char = _character(occupation="model")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=4)
    out = _planned(char, 24, controls)
    off = _planned_without_ws_p(char, 24, controls)
    # It is a meaningful case: WS-P actually moved poses.
    assert [s.pose for s in out] != [s.pose for s in off]

    # (1) WS-P touched ONLY pose/pose_detail — so the nudity ramp, outfit, location, time and the
    #     A2 expression assignment are all preserved EXACTLY (swaps never perturb them).
    for a, b in zip(out, off):
        da, db = a.model_dump(), b.model_dump()
        changed = {k for k in da if da[k] != db.get(k)}
        assert changed <= {"pose", "pose_detail"}, changed

    # (2) pose <-> location AND pose <-> outfit compatible everywhere (the WS-P goal).
    for s in out:
        assert sp._pose_ok_at(s.pose, s.location), (s.pose, s.location)
        assert sp._pose_outfit_ok(s.pose, s.outfit), (s.pose, s.outfit)

    # (3) shipped invariants still hold: exposure cap, location ceiling, pose usage cap, and
    #     pose + expression adjacency (all non-null expressions).
    pose_cap = max(2, math.ceil(24 / 8))
    pose_counts: dict = {}
    for s in out:
        if s.pose is not None:
            pose_counts[s.pose.value] = pose_counts.get(s.pose.value, 0) + 1
        if s.outfit is not None:
            assert _nudity_index(s.nudityLevel) <= _nudity_index(_exposure_cap(s.outfit))
        assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location))
    assert max(pose_counts.values()) <= pose_cap, pose_counts
    for i in range(1, len(out)):
        if out[i].pose is not None and out[i - 1].pose is not None:
            assert out[i].pose != out[i - 1].pose, ("pose adjacency", i)
        assert out[i].expression and out[i].expression != out[i - 1].expression, ("expr adjacency", i)
    assert all(s.expression for s in out)

    # (4) the nudity sequence (the guided ramp, post-ceiling/exposure) is byte-identical with WS-P
    #     off — an explicit proof that the pose-only repair preserves the ramp.
    assert [s.nudityLevel for s in out] == [s.nudityLevel for s in off]


def test_ws_p_is_seeded_reproducible():
    # The whole pipeline including the WS-P repair reproduces byte-for-byte under a fixed seed.
    char = _character(occupation="student")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=2, base_seed=9)
    a = _planned(char, 24, controls)
    b = _planned(char, 24, controls)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]


def test_all_compatible_batch_is_byte_identical_without_ws_p():
    # Regression lock: a batch whose pools are already all-compatible (WS-P has nothing to drop,
    # swap or re-pick) plans BYTE-IDENTICALLY whether or not the WS-P layer runs — proven by
    # disabling every WS-P effect and comparing full model dumps.
    char = _character(occupation="nurse")
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, escalation="building", base_seed=1)
    after = _planned(char, 24, controls)
    before = _planned_without_ws_p(char, 24, controls)
    assert [s.model_dump() for s in before] == [s.model_dump() for s in after]
    # (and it really is all-compatible: WS-P found nothing to fix)
    for s in after:
        assert sp._pose_ok_at(s.pose, s.location) and sp._pose_outfit_ok(s.pose, s.outfit)


# ---------------------------------------------------------------------------
# PLANNER COHERENCE: caption reconciliation + mood-payload cap
# ---------------------------------------------------------------------------
from services.story_planner import (  # noqa: E402
    _reconcile_captions, _LOCATION_CAPTION_TOKENS, _caption_names_location,
    _caption_foreign_location,
)


def _scene(beat_description, location, pose=None, activity=None, nudity=NudityLevel.LOW):
    return SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0,
        beat_description=beat_description, pose=pose, activity=activity,
        location=location, nudityLevel=nudity,
    )


def _character_with_kinks(kinks):
    persona = PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation="nurse", personality="temptress", relationship="girlfriend", kinks=kinks,
    )
    return Character(persona=persona, likes=[], dislikes=[])


def test_location_caption_tokens_cover_every_location():
    # Every LocationType value must have a non-empty tuple of caption tokens.
    for loc in LocationType:
        toks = _LOCATION_CAPTION_TOKENS.get(loc.value)
        assert toks, f"no caption tokens for location {loc.value}"
        assert all(isinstance(t, str) and t for t in toks), f"bad token in {loc.value}: {toks}"


def test_reconcile_rewrites_caption_when_location_moved():
    # The live bug: caption "at a cafe" on an item whose FINAL location is photo_studio.
    s = _scene("A relaxed moment at a cafe", LocationType.PHOTO_STUDIO,
               pose=PoseType.STANDING_LEANING)
    original = s.beat_description
    _reconcile_captions([s])
    low = s.beat_description.lower()
    assert s.beat_description != original, "contradicting caption should have been rewritten"
    assert not any(t in low for t in _LOCATION_CAPTION_TOKENS["cafe"]), \
        f"cafe token survived: {s.beat_description!r}"
    assert "studio" in low, f"studio phrase missing from rewrite: {s.beat_description!r}"
    assert len(s.beat_description) <= 280


def test_reconcile_rewrites_studio_caption_at_home():
    # The other live case: "posing under studio lights" on a home_living_room item.
    s = _scene("Posing under studio lights", LocationType.HOME_LIVING_ROOM, pose=PoseType.SOFA)
    _reconcile_captions([s])
    low = s.beat_description.lower()
    assert "studio" not in low, f"studio survived at living room: {s.beat_description!r}"
    assert _caption_names_location(low, _LOCATION_CAPTION_TOKENS["home_living_room"]), \
        f"rewrite does not name the final location: {s.beat_description!r}"


def test_reconcile_uses_activity_as_lead_when_present():
    # activity (identity-free action) is preferred over the pose-derived fallback.
    s = _scene("Sipping espresso at a cozy cafe", LocationType.GARDEN,
               pose=PoseType.SITTING, activity="reading a paperback")
    _reconcile_captions([s])
    low = s.beat_description.lower()
    assert "reading a paperback" in low, f"activity not used as lead: {s.beat_description!r}"
    assert "garden" in low and "cafe" not in low, s.beat_description


def test_reconcile_leaves_coherent_caption_byte_identical():
    # A caption already naming its final location is untouched; so is one that names NO
    # location at all. Byte-identical is the contract for non-contradicting captions.
    coherent = _scene("A quiet morning in the bedroom", LocationType.HOME_BEDROOM,
                      pose=PoseType.SITTING)
    before = coherent.beat_description
    tokenfree = _scene("Waking up slow, wrapped in a robe", LocationType.PHOTO_STUDIO,
                       pose=PoseType.LYING_STOMACH)
    before_tf = tokenfree.beat_description
    _reconcile_captions([coherent, tokenfree])
    assert coherent.beat_description == before
    assert tokenfree.beat_description == before_tf


def test_validate_and_repair_captions_are_location_coherent():
    # End-to-end through validate_and_repair (the real batch path): after every repair
    # settles, no caption may name a location the item does not finally occupy.
    char = _character(occupation="model")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=5)
    out = _planned(char, 24, controls)
    for s in out:
        low = (s.beat_description or "").lower()
        fv = s.location.value
        if _caption_names_location(low, _LOCATION_CAPTION_TOKENS.get(fv, ())):
            continue
        assert not _caption_foreign_location(low, fv), \
            f"caption names a foreign location: loc={fv} cap={s.beat_description!r}"


def test_reconcile_is_reproducible_through_validate_and_repair():
    # Same seed -> identical captions (the rewrite is a pure function of final fields).
    char = _character(occupation="model")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=5)
    a = _planned(char, 24, controls)
    b = _planned(char, 24, controls)
    assert [s.beat_description for s in a] == [s.beat_description for s in b]


def test_mood_items_carry_at_most_one_kink():
    # Mood payload capped to one kink; the seeded ~1/3 which-items gating is unchanged.
    char = _character_with_kinks(["bondage", "spanking", "edging"])
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    out = _planned(char, 24, controls)
    moody = [s for s in out if s.mood_kinks]
    assert moody, "expected some moody items on a HIGH batch with kinks"
    for s in moody:
        assert len(s.mood_kinks) <= 1, f"item carries multiple kinks: {s.mood_kinks}"


def test_mood_cap_is_seeded_reproducible():
    char = _character_with_kinks(["bondage", "spanking", "edging"])
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=3, base_seed=7)
    a = _planned(char, 24, controls)
    b = _planned(char, 24, controls)
    assert [(s.mood_kinks, s.mood_personality) for s in a] == \
        [(s.mood_kinks, s.mood_personality) for s in b]


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
