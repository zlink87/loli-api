"""
Tests for scene_mapper.scene_to_pipeline_request (pure mapping logic).

Runs under pytest or directly: python loli_api/tests/test_scene_mapper.py
"""
import models.requests as _mr

# The mapper builds a PipelineEditRequest whose source_image is SSRF-validated.
# These tests exercise mapping logic, not the allowlist, so make the validator a
# passthrough.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import (
    PoseType, OutfitType, NudityLevel, LocationType, TimeOfDayType, LightingType,
    PhotoStyleType,
)
from models.requests import PersonaOptions
from models.batch import BatchControls, SeedStrategy
from models.scene import SceneSpec
from services.scene_mapper import scene_to_pipeline_request, resolve_seed
# Use the REAL planner dataclass (not a stand-in) so the mapper<->orchestrator
# attribute contract (hero_photo_url) is exercised exactly as at runtime.
from services.story_planner import Character


def _character():
    persona = PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation="nurse", relationship="girlfriend",
    )
    return Character(persona=persona, hero_photo_url="https://x.supabase.co/img.png")


def _scene(**kw):
    base = dict(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="beat",
        location=LocationType.HOME_BEDROOM, time_of_day=TimeOfDayType.NIGHT,
        lighting=LightingType.CANDLELIT,
    )
    base.update(kw)
    return SceneSpec(**base)


def test_source_is_always_hero_photo():
    char = _character()
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SITTING), BatchControls())
    assert req.source_image == char.hero_photo_url


def test_photo_style_threaded_from_controls():
    char = _character()
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SITTING), BatchControls())
    assert req.photoStyle == PhotoStyleType.NATURAL  # batch default (dressed-by-default, no glamour suffix)
    controls = BatchControls(photo_style=PhotoStyleType.CANDID_PHONE)
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SITTING), controls)
    assert req.photoStyle == PhotoStyleType.CANDID_PHONE


def test_nudity_is_clamped_to_max():
    char = _character()
    controls = BatchControls(max_nudity=NudityLevel.LOW)
    req = scene_to_pipeline_request(char, _scene(nudityLevel=NudityLevel.HIGH), controls)
    assert req.nudityLevel == NudityLevel.LOW


def test_sfw_forces_low_and_drops_naked():
    char = _character()
    controls = BatchControls(sfw_only=True)
    req = scene_to_pipeline_request(
        char, _scene(outfit=OutfitType.NAKED, nudityLevel=NudityLevel.HIGH), controls
    )
    assert req.nudityLevel == NudityLevel.LOW
    assert req.outfit is None


def test_blocked_outfit_is_dropped():
    char = _character()
    controls = BatchControls(blocked_outfits=[OutfitType.BIKINI])
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.BIKINI), controls)
    assert req.outfit is None


def test_allowed_outfits_filters_out_others():
    char = _character()
    controls = BatchControls(allowed_outfits=[OutfitType.BUSINESS_SUIT])
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.BIKINI), controls)
    assert req.outfit is None


def test_blocked_pose_is_dropped():
    char = _character()
    controls = BatchControls(blocked_poses=[PoseType.SPREAD_LEGS])
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SPREAD_LEGS), controls)
    assert req.pose is None


def test_at_least_one_step_when_everything_filtered():
    # No pose, no outfit, but a background is always composed from location -> valid request.
    char = _character()
    controls = BatchControls()
    req = scene_to_pipeline_request(char, _scene(pose=None, outfit=None), controls)
    assert req.prompt and req.prompt.strip()  # background step present


def test_background_text_composed_from_location():
    char = _character()
    req = scene_to_pipeline_request(char, _scene(pose=None, outfit=None), BatchControls())
    assert "bedroom" in req.prompt.lower()


def test_seed_strategy_fixed():
    controls = BatchControls(seed_strategy=SeedStrategy.FIXED, base_seed=42)
    assert resolve_seed(controls, 0) == 42
    assert resolve_seed(controls, 5) == 42


def test_seed_strategy_per_item_is_deterministic_and_distinct():
    controls = BatchControls(seed_strategy=SeedStrategy.PER_ITEM, base_seed=42)
    s0, s1 = resolve_seed(controls, 0), resolve_seed(controls, 1)
    assert s0 != s1
    assert resolve_seed(controls, 1) == s1  # reproducible


def test_seed_strategy_random_is_none():
    controls = BatchControls(seed_strategy=SeedStrategy.RANDOM, base_seed=42)
    assert resolve_seed(controls, 0) is None


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
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
