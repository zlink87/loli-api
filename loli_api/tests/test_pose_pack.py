"""
POSE PACK (07-14) — 11 new poses (active/lifestyle + camera-aware provocative).

Covers:
  p1  completeness: every PoseType has a POSE_DESCRIPTIONS entry AND a scene_vocab
      _POSE_CLASS entry; the 11 new poses exist with the exact snake_case values and
      the exact instructive descriptions from the work order.
  p2  classes: the MOTION class covers walking/walking_away/dancing/stretching/
      over_shoulder_look; running is ATHLETIC; the provocative poses reuse KNEELING/
      LYING/OTHER; MOTION + the self-staging OTHER poses are unstaged (staging_options()
      == () everywhere).
  p3  expression compat: MOTION is unrestricted EXCEPT the generic HIGH-nudity/exposed
      rule (it is NOT athletic-gated) — the "verify expression-compat treats a non-athletic
      class permissively" check.
  p4  ref latch: all 11 new poses ship REFLESS; the planner pool builders
      (_controls_pose_vocab, _allowed_pose_pool) exclude every refless pose so the
      effective pose vocabulary is byte-identical to the pre-pack 16; monkeypatching the
      latch predicate to "installed" makes the new poses reachable again (they light up
      with no code change once their PNG lands).
  p5  endpoint 422: POST /v1/edit/pose naming a refless pose fails fast with a clear 422;
      an installed pose passes the latch gate.
  p6  running mirrors jogging: same ATHLETIC wardrobe compat (POSE_OUTFIT_COMPAT) and the
      same {park, city_street, beach, forest_trail, gym} location guard; a dress is barred,
      a cafe is barred, activewear/uniform/None pass — identically to jogging.
  p7  propriety: the three explicit poses are private-only (barred at every public venue,
      allowed in private); bent_over_from_behind is public-legal but barred at the formal
      workplaces (office/classroom/library/hospital_ward).
  p8  determinism: seeded plans reproduce and NEVER contain a refless pose (so a batch
      today is byte-identical to the pre-pack baseline).

Runs under pytest or directly: python loli_api/tests/test_pose_pack.py
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

_LOLI_API_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_API_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_API_DIR))

# These tests exercise planner/endpoint logic, not the SSRF allowlist (mirrors
# test_scene_staging.py) — patch BEFORE any PoseEditRequest is constructed.
import models.requests as _mr  # noqa: E402
_mr.validate_source_image = lambda u: u  # type: ignore

from fastapi import HTTPException  # noqa: E402

from models.enums import PoseType, OutfitType, NudityLevel, LocationType  # noqa: E402
from models.requests import PoseEditRequest  # noqa: E402
from models.batch import BatchControls  # noqa: E402
from services import pose_assets  # noqa: E402
from services import scene_vocab as sv  # noqa: E402
from services import story_planner as sp  # noqa: E402
from services.story_planner import Character, DeterministicScenePlanner, validate_and_repair  # noqa: E402
from api.v1.endpoints import pose as pose_ep  # noqa: E402
from models.requests import PersonaOptions  # noqa: E402


# The 11 POSE PACK values, and their EXACT descriptions from the work order.
_NEW_DESCRIPTIONS = {
    PoseType.WALKING: "walking toward the camera with a relaxed natural stride",
    PoseType.WALKING_AWAY: "walking away from the camera, glancing back over her shoulder",
    PoseType.RUNNING: "running mid-stride, athletic dynamic motion",
    PoseType.DANCING: "dancing freely, body in relaxed motion",
    PoseType.STRETCHING: "stretching with arms raised overhead, elongated posture",
    PoseType.ALL_FOURS_FROM_BEHIND:
        "on all fours facing away, photographed from behind, looking back over her shoulder at the camera",
    PoseType.BENT_OVER_FROM_BEHIND:
        "bending forward at the waist, photographed from behind, glancing back at the camera",
    PoseType.KNEELING_ARCHED_BACK:
        "kneeling upright with her back arched, chest lifted, hands resting on her thighs",
    PoseType.LYING_ON_SIDE:
        "lying on her side, propped on one elbow, hip curve emphasized, facing the camera",
    PoseType.OVER_SHOULDER_LOOK:
        "standing with her back to the camera, looking back over her shoulder",
    PoseType.STRADDLING_CHAIR:
        "straddling a chair backwards, arms folded on the chairback, facing the camera",
}
NEW_POSES = frozenset(_NEW_DESCRIPTIONS)
_MOTION_POSES = {
    PoseType.WALKING, PoseType.WALKING_AWAY, PoseType.DANCING, PoseType.STRETCHING,
    PoseType.OVER_SHOULDER_LOOK,
}


def _character(occupation="model"):
    persona = PersonaOptions(
        name="Pack", style="realistic", ethnicity="caucasian", age=27,
        eyeColor="green", hairStyle="straight", hairColor="blonde",
        bodyType="curvy", breastSize="medium", personality="lover",
        occupation=occupation, relationship="girlfriend",
    )
    return Character(persona=persona, hero_photo_url="https://x.supabase.co/hero.png")


def _planned(seed=1234, count=24, occupation="model", **ctrl):
    controls = BatchControls(base_seed=seed, max_nudity=NudityLevel.HIGH, **ctrl)
    char = _character(occupation)
    return validate_and_repair(
        DeterministicScenePlanner().plan_scenes_sync(char, count, controls), char, count, controls
    )


# ---------------------------------------------------------------------------
# p1 — completeness
# ---------------------------------------------------------------------------
def test_every_pose_has_description_and_class():
    for p in PoseType:
        assert p in pose_assets.POSE_DESCRIPTIONS, f"{p.name} missing a description"
        desc = pose_assets.POSE_DESCRIPTIONS[p]
        assert isinstance(desc, str) and desc.strip(), f"{p.name} blank description"
        assert not desc.endswith("."), f"{p.name} description must be a bare phrase"
        assert p.value in sv._POSE_CLASS, f"{p.name} missing a staging class"
    # The 11 new members exist with the exact work-order values + descriptions.
    for p, desc in _NEW_DESCRIPTIONS.items():
        assert pose_assets.POSE_DESCRIPTIONS[p] == desc, p.name
    # Appended last (nothing reordered) so the ref latch keeps the installed prefix intact.
    assert list(PoseType)[:16] == [p for p in PoseType if p not in NEW_POSES]
    print("p1 OK: every pose has a description + class; 11 new values/descriptions exact; appended last")


# ---------------------------------------------------------------------------
# p2 — classes + staging
# ---------------------------------------------------------------------------
def test_new_pose_classes_and_staging():
    for p in _MOTION_POSES:
        assert sv.pose_class(p) == sv.POSE_CLASS_MOTION, p.name
    assert sv.pose_class(PoseType.RUNNING) == sv.POSE_CLASS_ATHLETIC
    assert sv.pose_class(PoseType.ALL_FOURS_FROM_BEHIND) == sv.POSE_CLASS_KNEELING
    assert sv.pose_class(PoseType.KNEELING_ARCHED_BACK) == sv.POSE_CLASS_KNEELING
    assert sv.pose_class(PoseType.LYING_ON_SIDE) == sv.POSE_CLASS_LYING
    assert sv.pose_class(PoseType.BENT_OVER_FROM_BEHIND) == sv.POSE_CLASS_OTHER
    assert sv.pose_class(PoseType.STRADDLING_CHAIR) == sv.POSE_CLASS_OTHER

    # MOTION + the self-staging OTHER poses draw NO staging anchor anywhere (the phrase /
    # description carries the stance/surface itself).
    for p in _MOTION_POSES | {PoseType.BENT_OVER_FROM_BEHIND, PoseType.STRADDLING_CHAIR}:
        for loc in LocationType:
            assert sv.staging_options(loc, p) == (), (p.name, loc.value)
    # The reused reclining/kneel classes DO pull their class pool where one exists (wiring proof).
    assert sv.staging_options(LocationType.HOME_BEDROOM, PoseType.LYING_ON_SIDE) == \
        sv.STAGING_PHRASES["home_bedroom"][sv.POSE_CLASS_LYING]
    assert sv.staging_options(LocationType.HOME_BEDROOM, PoseType.ALL_FOURS_FROM_BEHIND) == \
        sv.STAGING_PHRASES["home_bedroom"][sv.POSE_CLASS_KNEELING]
    print("p2 OK: MOTION/ATHLETIC/KNEELING/LYING/OTHER classes wired; motion + self-staging unstaged")


# ---------------------------------------------------------------------------
# p3 — MOTION expression compat is permissive (not athletic-gated)
# ---------------------------------------------------------------------------
def test_motion_expressions_unrestricted_except_high_nudity():
    L, N = LocationType, NudityLevel
    # A soft/sultry face reads WRONG mid-jog (ATHLETIC) but is FINE while walking/dancing (MOTION).
    assert not sp._expression_allowed("calm, lids lowered", PoseType.RUNNING, N.LOW, L.PARK)
    assert sp._expression_allowed("calm, lids lowered", PoseType.WALKING, N.LOW, L.PARK)
    assert sp._expression_allowed("soft smile at the camera", PoseType.DANCING, N.LOW, L.NIGHTCLUB)
    assert sp._expression_allowed("bright, open smile", PoseType.STRETCHING, N.LOW, L.HOME_BEDROOM)
    # …but the generic HIGH-nudity/exposed rule still applies to MOTION (no bright grin exposed).
    assert not sp._expression_allowed("bright, open smile", PoseType.WALKING, N.HIGH, L.HOME_BEDROOM)
    assert sp._expression_allowed("calm, lids lowered", PoseType.WALKING, N.HIGH, L.HOME_BEDROOM)
    print("p3 OK: MOTION expressions unrestricted except the HIGH-nudity/exposed rule")


# ---------------------------------------------------------------------------
# p4 — ref latch
# ---------------------------------------------------------------------------
def test_original_poses_installed_and_missing_set_is_consistent():
    # State-independent: new-pose refs are generated over time, so the only
    # hard invariants are (a) the 16 original poses always ship installed and
    # (b) missing_pose_assets() is exactly the set of poses without a PNG.
    for p in PoseType:
        if p not in NEW_POSES:
            assert pose_assets.has_pose_ref(p), f"{p.name} is missing its ref PNG"
    refless = {p for p in PoseType if not pose_assets.has_pose_ref(p)}
    assert set(pose_assets.missing_pose_assets()) == refless
    assert refless <= set(NEW_POSES), "an original pose lost its ref PNG"
    print("p4a OK: originals installed; missing set consistent with disk state")


def test_latch_excludes_refless_from_planner_pools_and_lights_up_when_present():
    controls = BatchControls(base_seed=1)
    # Pin the "only originals installed" world so the assertions hold no matter
    # how many new-pose PNGs have been generated on this checkout.
    orig = sp.has_pose_ref
    try:
        sp.has_pose_ref = lambda p: p not in NEW_POSES
        vocab = sp._controls_pose_vocab(controls)
        # No refless pose is ever a fallback candidate…
        for p in NEW_POSES:
            assert p not in vocab
        # …and the vocab is EXACTLY the installed originals in enum order
        # (byte-identical to pre-pack: default controls carry an
        # athletic-capable fill pool, so jogging/squatting stay in).
        assert vocab == [p for p in PoseType if p not in NEW_POSES]
    finally:
        sp.has_pose_ref = orig

    # An authored beat pool never contains a refless pose either (all authored poses installed).
    from services import story_templates as st
    for arc_list in st.ARC_TEMPLATES.values():
        for arc in arc_list:
            for beat in arc.beats:
                for p in sp._allowed_pose_pool(beat, controls):
                    assert pose_assets.has_pose_ref(p), (arc.arc_id, p.value)

    # Latch is load-bearing: pretend every ref is installed -> the new poses become reachable.
    orig = sp.has_pose_ref
    try:
        sp.has_pose_ref = lambda p: True
        lit = sp._controls_pose_vocab(controls)
        for p in NEW_POSES:
            assert p in lit, f"{p.name} should light up once its ref exists"
    finally:
        sp.has_pose_ref = orig
    print("p4b OK: refless poses excluded from both pool builders; monkeypatched-installed -> reachable")


# ---------------------------------------------------------------------------
# p5 — endpoint 422 on a refless pose
# ---------------------------------------------------------------------------
class _StubJM:
    def is_queue_full(self, job_type=None):
        return False

    async def create_job(self, request, user_id, job_type=None):
        return SimpleNamespace(job_id="job_pack_1")


def test_endpoint_422s_a_refless_pose_and_passes_an_installed_one():
    orig = pose_ep._job_manager
    pose_ep.set_job_manager(_StubJM())
    # The endpoint calls pose_assets.has_pose_ref (module-qualified) -- patch there.
    orig_ref = pose_assets.has_pose_ref
    pose_assets.has_pose_ref = lambda p: p != PoseType.DANCING  # pin DANCING refless
    try:
        refless = PoseEditRequest(source_image="https://x.supabase.co/s.png", pose=PoseType.DANCING)
        try:
            asyncio.run(pose_ep.edit_pose(refless, {"sub": "u"}))
            assert False, "expected a 422 for a refless pose"
        except HTTPException as e:
            assert e.status_code == 422
            assert "dancing" in str(e.detail) and "generate_pose_refs" in str(e.detail)

        # An installed pose clears the latch gate (reaches job creation -> 202-shaped response).
        installed = PoseEditRequest(source_image="https://x.supabase.co/s.png", pose=PoseType.SITTING)
        resp = asyncio.run(pose_ep.edit_pose(installed, {"sub": "u"}))
        assert resp.jobId == "job_pack_1"
    finally:
        pose_ep.set_job_manager(orig)
        pose_assets.has_pose_ref = orig_ref
    print("p5 OK: refless pose -> 422 with a clear message; installed pose passes the gate")


# ---------------------------------------------------------------------------
# p6 — running mirrors jogging
# ---------------------------------------------------------------------------
def test_running_mirrors_jogging_wardrobe_and_location_rules():
    assert PoseType.RUNNING in sp.ATHLETIC_POSES
    # Identical wardrobe compat + identical location guard.
    assert sp.POSE_OUTFIT_COMPAT[PoseType.RUNNING.value] == sp.POSE_OUTFIT_COMPAT[PoseType.JOGGING.value]
    assert sp._POSE_LOCATION_GUARD[PoseType.RUNNING.value] == sp._POSE_LOCATION_GUARD[PoseType.JOGGING.value]
    assert sp._POSE_LOCATION_GUARD[PoseType.RUNNING.value] == {
        LocationType.PARK.value, LocationType.CITY_STREET.value, LocationType.BEACH.value,
        LocationType.FOREST_TRAIL.value, LocationType.GYM.value,
    }
    # Same outfit verdicts as jogging across the representative cases.
    for outfit in (OutfitType.VELVET_DRESS, OutfitType.RED_EVENING_GOWN, OutfitType.GYM_SET,
                   OutfitType.RUNNING_GEAR, OutfitType.OVERSIZED_STREETWEAR,
                   OutfitType.NURSE_UNIFORM, None):
        assert sp._pose_outfit_ok(PoseType.RUNNING, outfit) == sp._pose_outfit_ok(PoseType.JOGGING, outfit), outfit
    # Same location verdicts as jogging at every location (cafe barred, park/gym allowed).
    for loc in LocationType:
        assert sp._pose_ok_at(PoseType.RUNNING, loc) == sp._pose_ok_at(PoseType.JOGGING, loc), loc.value
    assert not sp._pose_ok_at(PoseType.RUNNING, LocationType.CAFE)
    assert sp._pose_ok_at(PoseType.RUNNING, LocationType.PARK)
    print("p6 OK: running inherits jogging's ATHLETIC wardrobe compat + outdoor/gym location guard")


# ---------------------------------------------------------------------------
# p7 — propriety
# ---------------------------------------------------------------------------
def test_new_explicit_poses_are_private_only_and_bent_over_is_public_legal():
    for p in (PoseType.ALL_FOURS_FROM_BEHIND, PoseType.KNEELING_ARCHED_BACK, PoseType.STRADDLING_CHAIR):
        assert p in sp.PRIVATE_ONLY_POSES, p.name
        # No guard allowlist entry -> barred at EVERY public venue, allowed in private.
        assert sp._POSE_LOCATION_GUARD.get(p.value) is None, p.name
        assert not sp._pose_ok_at(p, LocationType.NIGHTCLUB), p.name
        assert not sp._pose_ok_at(p, LocationType.BEACH), p.name
        assert sp._pose_ok_at(p, LocationType.HOME_BEDROOM), p.name
        assert sp._pose_ok_at(p, LocationType.HOTEL_ROOM), p.name

    # bent_over_from_behind: public-legal, but never in a formal professional venue.
    bent = PoseType.BENT_OVER_FROM_BEHIND
    assert bent not in sp.PRIVATE_ONLY_POSES
    for loc in (LocationType.OFFICE, LocationType.CLASSROOM, LocationType.LIBRARY,
                LocationType.HOSPITAL_WARD):
        assert not sp._pose_ok_at(bent, loc), loc.value
    for loc in (LocationType.NIGHTCLUB, LocationType.BEACH, LocationType.HOME_BEDROOM,
                LocationType.BAR, LocationType.POOLSIDE):
        assert sp._pose_ok_at(bent, loc), loc.value
    print("p7 OK: 3 explicit poses private-only; bent_over_from_behind public-legal minus formal workplaces")


# ---------------------------------------------------------------------------
# p8 — determinism / no refless pose in a real plan
# ---------------------------------------------------------------------------
def test_plans_are_reproducible_and_never_use_a_refless_pose():
    # Pin the "only originals installed" world (new-pose PNGs may exist on
    # this checkout) so both the byte-reproducibility and the no-refless
    # assertions stay meaningful regardless of generated assets.
    orig = sp.has_pose_ref
    try:
        sp.has_pose_ref = lambda p: p not in NEW_POSES
        for occ in ("model", "nurse", "fitness_coach", "student"):
            for seed in (1, 7, 21):
                a = _planned(seed=seed, occupation=occ, escalation="building")
                b = _planned(seed=seed, occupation=occ, escalation="building")
                assert [s.model_dump() for s in a] == [s.model_dump() for s in b], (occ, seed)
                for s in a:
                    assert s.pose is None or s.pose not in NEW_POSES, (occ, seed, s.pose)
    finally:
        sp.has_pose_ref = orig
    print("p8 OK: seeded plans reproduce byte-for-byte and never contain a refless (new) pose")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
