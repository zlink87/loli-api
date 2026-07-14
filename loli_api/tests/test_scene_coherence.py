"""
WS1 — real-world-coherence guards for the batch planner.

Every planned photo must make real-world human sense. This covers the three guards and
the zero-violation meta-test that is the CI enforcement of that mandate:

  1a  time <-> location   — LOCATION_TIME_COMPAT covers every location; a night venue is
                            never at midday, a beach never at deep night; the repair pass
                            moves TIME (never the location) onto the nearest allowed value.
  1b  expression <-> situation — every pool expression is tagged; athletic poses drop
                            soft/sultry faces, HIGH/naked scenes drop bright grins, and a
                            public venue at SUGGESTIVE+ drops the most intimate state; both
                            the pick-time filter and the repair pass enforce it, adjacency
                            and candid share preserved.
  1c  provocative-pose propriety — the spread/all-fours poses (PRIVATE_ONLY_POSES) never
                            land in a public venue after planning.
  1d  ZERO-violation meta-test — ~10 seeded 24-item plans across nudity ramps assert NO
                            violation of: time<->location, expression compat, private-only
                            poses in public, staging class-coherence, caption<->location,
                            exposure caps, location nudity ceilings.

Runs under pytest or directly: python loli_api/tests/test_scene_coherence.py
"""
import math

from models.enums import (
    NudityLevel, OutfitType, LocationType, TimeOfDayType, PoseType,
)
from models.requests import PersonaOptions
from models.batch import BatchControls
from models.scene import SceneSpec
from services import scene_vocab as sv
from services import story_planner as sp
from services.outfit_vocab import outfit_exposure_cap
from services.story_planner import (
    Character, DeterministicScenePlanner, validate_and_repair,
    LOCATION_TIME_COMPAT, PRIVATE_ONLY_POSES, _location_ceiling, _nudity_index,
)


def _character(occupation="nurse", likes=None, dislikes=None, personality="temptress"):
    persona = PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation=occupation, personality=personality, relationship="girlfriend",
    )
    return Character(persona=persona, likes=likes or [], dislikes=dislikes or [])


def _planned(char, n, controls):
    scenes = DeterministicScenePlanner().plan_scenes_sync(char, n, controls)
    return validate_and_repair(scenes, char, n, controls)


# ---------------------------------------------------------------------------
# 1a  time <-> location
# ---------------------------------------------------------------------------
def test_location_time_compat_covers_every_location():
    for loc in LocationType:
        assert loc.value in LOCATION_TIME_COMPAT, f"no time-compat entry for {loc.value}"
        allowed = LOCATION_TIME_COMPAT[loc.value]
        assert allowed, f"empty time-compat set for {loc.value}"
        assert all(isinstance(t, TimeOfDayType) for t in allowed)


def test_time_compat_spot_rules():
    T, L = TimeOfDayType, LocationType
    # nightlife: evening/night only.
    assert sp._time_ok_at(T.NIGHT, L.NIGHTCLUB) and sp._time_ok_at(T.EVENING, L.BAR)
    assert not sp._time_ok_at(T.DAYTIME, L.NIGHTCLUB)
    assert not sp._time_ok_at(T.MORNING, L.BAR)
    # indoor public / business: no night.
    for loc in (L.OFFICE, L.CLASSROOM, L.LIBRARY, L.LAB, L.HOSPITAL_WARD):
        assert not sp._time_ok_at(T.NIGHT, loc), loc
        assert sp._time_ok_at(T.DAYTIME, loc) and sp._time_ok_at(T.EVENING, loc)
    # outdoors: daylight + golden/sunset, no deep night/evening.
    for loc in (L.BEACH, L.PARK, L.POOLSIDE, L.FOREST_TRAIL, L.GARDEN, L.CITY_STREET):
        assert sp._time_ok_at(T.DAYTIME, loc) and sp._time_ok_at(T.SUNSET, loc)
        assert not sp._time_ok_at(T.NIGHT, loc), loc
    # homes/hotel/studio/lounge/car/rooftop/stage: anything.
    for loc in (L.HOME_BEDROOM, L.HOTEL_ROOM, L.PHOTO_STUDIO, L.LUXURY_LOUNGE,
                L.CAR_INTERIOR, L.ROOFTOP, L.STAGE):
        for t in TimeOfDayType:
            assert sp._time_ok_at(t, loc), (t, loc)


def test_nearest_allowed_time_moves_to_boundary():
    T, L = TimeOfDayType, LocationType
    # midday at a nightclub -> the nearest nightlife time (evening).
    assert sp._nearest_allowed_time(T.DAYTIME, L.NIGHTCLUB) == T.EVENING
    # night at a beach -> the nearest outdoor time (sunset).
    assert sp._nearest_allowed_time(T.NIGHT, L.BEACH) == T.SUNSET
    # night at the office -> evening.
    assert sp._nearest_allowed_time(T.NIGHT, L.OFFICE) == T.EVENING
    # already allowed -> unchanged.
    assert sp._nearest_allowed_time(T.NIGHT, L.HOME_BEDROOM) == T.NIGHT


def test_time_repair_moves_time_never_location():
    char = _character()
    scenes = [
        SceneSpec(arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
                  location=LocationType.NIGHTCLUB, time_of_day=TimeOfDayType.DAYTIME),
        SceneSpec(arc_id="a", arc_title="A", beat_index=1, global_index=1, beat_description="b",
                  location=LocationType.BEACH, time_of_day=TimeOfDayType.NIGHT),
    ]
    sp._enforce_time_location_compat(scenes, BatchControls(base_seed=1))
    assert scenes[0].location == LocationType.NIGHTCLUB       # never relocated
    assert scenes[0].time_of_day == TimeOfDayType.EVENING     # time snapped instead
    assert scenes[1].location == LocationType.BEACH
    assert scenes[1].time_of_day == TimeOfDayType.SUNSET


def test_deterministic_pick_time_is_location_coherent_any_seed():
    # The deterministic planner's OWN pick (pre-repair) is already time<->location coherent.
    for seed in range(1, 7):  # base_seed must be >= 1
        for occ in ("bartender", "boss_ceo", "model", "nurse"):
            scenes = DeterministicScenePlanner().plan_scenes_sync(
                _character(occupation=occ), 16, BatchControls(base_seed=seed, escalation="building")
            )
            for s in scenes:
                assert sp._time_ok_at(s.time_of_day, s.location), (occ, seed, s.time_of_day, s.location)


# ---------------------------------------------------------------------------
# 1b  expression <-> situation
# ---------------------------------------------------------------------------
def test_every_pool_expression_is_tagged():
    for e in sp._BATCH_EXPRESSION_POOL:
        assert e in sp._EXPRESSION_TAGS, f"untagged expression {e!r}"
        assert sp._EXPRESSION_TAGS[e] in {
            sp._EXPR_CHEERFUL, sp._EXPR_SOFT, sp._EXPR_SULTRY, sp._EXPR_CANDID, sp._EXPR_NEUTRAL,
        }


def test_expression_allowed_matrix():
    L, N = LocationType, NudityLevel
    # ATHLETIC pose: cheerful/candid/neutral only.
    assert not sp._expression_allowed("calm, lids lowered", PoseType.JOGGING, N.LOW, L.PARK)
    assert not sp._expression_allowed("soft smile at the camera", PoseType.JOGGING, N.LOW, L.PARK)
    assert sp._expression_allowed("playful grin", PoseType.JOGGING, N.LOW, L.PARK)
    assert sp._expression_allowed("focused on what she's doing", PoseType.JOGGING, N.LOW, L.PARK)
    # HIGH nudity / naked: soft/sultry/neutral only (no bright grin).
    assert not sp._expression_allowed("bright, open smile", PoseType.LYING_BACK, N.HIGH, L.HOME_BEDROOM)
    assert not sp._expression_allowed("cheerful laugh", PoseType.SITTING, N.MEDIUM, L.HOTEL_ROOM,
                                      OutfitType.NAKED)
    assert sp._expression_allowed("calm, lids lowered", PoseType.LYING_BACK, N.HIGH, L.HOME_BEDROOM)
    assert sp._expression_allowed("soft smile at the camera", PoseType.LYING_BACK, N.HIGH, L.HOME_BEDROOM)
    # PUBLIC venue at SUGGESTIVE+: the most intimate state is excluded.
    assert not sp._expression_allowed("calm, lids lowered", PoseType.SITTING, N.SUGGESTIVE, L.CAFE)
    assert sp._expression_allowed("calm, lids lowered", PoseType.SITTING, N.LOW, L.CAFE)  # low -> fine
    assert sp._expression_allowed("calm, lids lowered", PoseType.SITTING, N.HIGH, L.HOME_BEDROOM)  # private
    # A NEUTRAL expression is allowed under every rule (so a compatible option always exists).
    for pose, nud, loc in (
        (PoseType.JOGGING, N.LOW, L.PARK),
        (PoseType.LYING_BACK, N.HIGH, L.HOME_BEDROOM),
        (PoseType.SITTING, N.SUGGESTIVE, L.CAFE),
    ):
        assert sp._expression_allowed("amused half-smile", pose, nud, loc)


def test_planned_expressions_are_situation_coherent_any_seed():
    for seed in (1, 5, 9):
        for occ in ("fitness_coach", "model", "nurse"):
            controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                                     base_seed=seed)
            for s in _planned(_character(occupation=occ), 24, controls):
                assert sp._expression_allowed(
                    s.expression, s.pose, s.nudityLevel, s.location, s.outfit
                ), (occ, seed, s.expression, s.pose, s.nudityLevel.value, s.location.value)


def test_expression_compat_preserves_adjacency_and_non_null():
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=2, base_seed=7)
    out = _planned(_character(occupation="fitness_coach"), 24, controls)
    assert all(s.expression for s in out)
    for i in range(1, len(out)):
        assert out[i].expression != out[i - 1].expression, ("adjacent expr dup", i)


# ---------------------------------------------------------------------------
# 1c  provocative-pose propriety
# ---------------------------------------------------------------------------
def test_private_only_poses_never_in_public_venue_after_planning():
    # Occupations whose authored beats pair a spread/all-fours pose with a PUBLIC venue
    # (gym/office) — the repair must move the POSE off a public venue UNLESS an explicit
    # _POSE_LOCATION_GUARD entry allows the exact pair (all_fours @ gym/yoga_studio), which
    # WINS over the private-only rule.
    for occ in ("fitness_coach", "yoga_instructor", "boss_ceo", "secretary", "professional_athlete"):
        for seed in (2, 6, 11):
            controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                                     base_seed=seed)
            for s in _planned(_character(occupation=occ), 24, controls):
                if s.pose in PRIVATE_ONLY_POSES and sv.is_public_venue(s.location):
                    guard = sp._POSE_LOCATION_GUARD.get(s.pose.value)
                    assert guard is not None and s.location.value in guard, \
                        (occ, seed, s.pose, s.location)


def test_private_only_pose_set_is_the_spread_all_fours_class():
    assert PRIVATE_ONLY_POSES == frozenset({
        PoseType.SPREAD_LEGS, PoseType.SITTING_LEGS_WIDE_OPEN, PoseType.ALL_FOURS,
    })


# ---------------------------------------------------------------------------
# 1d  ZERO-violation meta-test — the CI enforcement of "makes real-world sense".
# ---------------------------------------------------------------------------
def _violations(scene) -> list:
    """Every real-world-coherence rule this scene must satisfy; returns the failures."""
    v = []
    low = (scene.beat_description or "").lower()
    final = scene.location.value
    # time <-> location
    if not sp._time_ok_at(scene.time_of_day, scene.location):
        v.append(("time_location", scene.time_of_day.value, final))
    # expression compat
    if not sp._expression_allowed(scene.expression, scene.pose, scene.nudityLevel,
                                  scene.location, scene.outfit):
        v.append(("expression", scene.expression, scene.pose and scene.pose.value))
    # private-only pose in public venue — UNLESS an explicit _POSE_LOCATION_GUARD entry allows
    # this exact (pose, location) pair (all_fours as a post-workout stretch at gym/yoga_studio),
    # which WINS over the private-only rule (mirrors _pose_ok_at's precedence).
    if scene.pose in PRIVATE_ONLY_POSES and sv.is_public_venue(scene.location):
        guard = sp._POSE_LOCATION_GUARD.get(scene.pose.value)
        if not (guard is not None and final in guard):
            v.append(("private_pose_public", scene.pose.value, final))
    # staging class-coherence: a set staging must belong to THIS (location, pose-class) pool
    if scene.staging is not None and scene.staging not in sv.staging_options(scene.location, scene.pose):
        v.append(("staging_incoherent", scene.staging, final))
    # caption <-> location: a caption naming a FOREIGN place must also name the final one
    if (sp._caption_foreign_location(low, final)
            and not sp._caption_names_location(low, sp._LOCATION_CAPTION_TOKENS.get(final, ()))):
        v.append(("caption_foreign_location", scene.beat_description, final))
    # exposure cap
    if scene.outfit is not None and _nudity_index(scene.nudityLevel) > _nudity_index(
            outfit_exposure_cap(scene.outfit)):
        v.append(("exposure_cap", scene.nudityLevel.value, scene.outfit.value))
    # location nudity ceiling
    if _nudity_index(scene.nudityLevel) > _nudity_index(_location_ceiling(scene.location)):
        v.append(("location_ceiling", scene.nudityLevel.value, final))
    return v


def test_zero_coherence_violations_across_seeded_24_item_plans():
    # ~10 seeded 24-item plans spanning occupations, nudity ceilings and escalation styles.
    # EVERY item must satisfy EVERY real-world-sense rule — this is the mandate's CI gate.
    configs = [
        ("nurse", NudityLevel.HIGH, "building", 1, 1),
        ("model", NudityLevel.HIGH, "building", 2, 3),
        ("fitness_coach", NudityLevel.REVEALING, "building", 3, 5),
        ("boss_ceo", NudityLevel.MEDIUM, "flat", 1, 7),
        ("bartender", NudityLevel.HIGH, "building", 1, 9),
        ("yoga_instructor", NudityLevel.REVEALING, "building", 2, 11),
        ("student", NudityLevel.SUGGESTIVE, "building", 1, 13),
        ("photographer", NudityLevel.HIGH, "building", 3, 4),
        ("lifeguard", NudityLevel.MEDIUM, "building", 1, 8),
        ("secretary", NudityLevel.HIGH, "flat", 1, 6),
    ]
    total = 0
    for occ, max_nud, esc, days, seed in configs:
        controls = BatchControls(max_nudity=max_nud, escalation=esc, period_days=days, base_seed=seed)
        scenes = _planned(_character(occupation=occ), 24, controls)
        assert len(scenes) == 24
        total += len(scenes)
        for s in scenes:
            bad = _violations(s)
            assert not bad, f"{occ}/{max_nud.value}/{esc}/d{days}/seed{seed} item {s.global_index}: {bad}"
    assert total == 240


def test_meta_plans_are_seeded_reproducible():
    # The whole guarded pipeline reproduces byte-for-byte (determinism preserved).
    char = _character(occupation="fitness_coach")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building",
                             period_days=2, base_seed=5)
    a = _planned(char, 24, controls)
    b = _planned(char, 24, controls)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
