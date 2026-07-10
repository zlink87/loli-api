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


def test_source_is_hero_photo_when_no_nude_base():
    char = _character()  # nude_base_url defaults to None
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SITTING), BatchControls())
    assert req.source_image == char.hero_photo_url


def test_source_prefers_nude_base_when_present():
    # W2 prep: when a nude/undressed base is populated, it becomes the swap source so a new
    # garment renders onto a clean body instead of fighting the hero's existing clothes.
    char = _character()
    char.nude_base_url = "https://x.supabase.co/nude.png"
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SITTING), BatchControls())
    assert req.source_image == "https://x.supabase.co/nude.png"


def test_photo_style_threaded_from_controls():
    char = _character()
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SITTING), BatchControls())
    assert req.photoStyle == PhotoStyleType.POLISHED  # batch default now matches the generated hero's retouched finish
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


# ---------------------------------------------------------------------------
# WS2 routing: activity is dual-channel (background text vs the pose step)
# ---------------------------------------------------------------------------
def test_activity_excluded_from_background_when_pose_present():
    char = _character()
    scene = _scene(
        pose=PoseType.SITTING,
        activity="pouring her first coffee",
        setting="a sunlit small kitchen",
    )
    req = scene_to_pipeline_request(char, scene, BatchControls())
    assert "pouring her first coffee" not in (req.prompt or "")
    assert req.activity == "pouring her first coffee"  # rides the pose step instead


def test_activity_included_in_background_when_pose_absent():
    char = _character()
    scene = _scene(
        pose=None,
        activity="pouring her first coffee",
        setting="a sunlit small kitchen",
    )
    req = scene_to_pipeline_request(char, scene, BatchControls())
    assert "pouring her first coffee" in req.prompt
    assert req.activity is None  # no pose step to consume it


def test_activity_rides_background_when_pose_is_blocked():
    # A pose the batch controls block behaves like "no pose" for routing purposes —
    # activity must still land somewhere (the background text), never vanish.
    char = _character()
    controls = BatchControls(blocked_poses=[PoseType.SITTING])
    scene = _scene(pose=PoseType.SITTING, activity="stretching after a nap")
    req = scene_to_pipeline_request(char, scene, controls)
    assert req.pose is None
    assert "stretching after a nap" in req.prompt
    assert req.activity is None  # pose step won't run, so nothing to route it to


# ---------------------------------------------------------------------------
# WS2 routing: outfit_detail / expression pass straight through to the request
# ---------------------------------------------------------------------------
def test_outfit_detail_and_expression_mapped_onto_request():
    char = _character()
    scene = _scene(
        outfit=OutfitType.BUSINESS_SUIT,
        outfit_detail="charcoal wool pantsuit, fitted blazer",
        expression="confident subtle smirk",
    )
    req = scene_to_pipeline_request(char, scene, BatchControls())
    assert req.outfitDetail == "charcoal wool pantsuit, fitted blazer"
    assert req.expression == "confident subtle smirk"


def test_outfit_detail_and_expression_none_when_scene_omits_them():
    char = _character()
    req = scene_to_pipeline_request(char, _scene(pose=PoseType.SITTING), BatchControls())
    assert req.outfitDetail is None
    assert req.expression is None


# ---------------------------------------------------------------------------
# WS2 firewall: narrative (gallery-only prose) must never reach a request field
# ---------------------------------------------------------------------------
def test_narrative_never_reaches_any_request_text_field():
    char = _character()
    marker = "NARRATIVE_ONLY_MARKER_do_not_leak_9f3a"
    scene = _scene(
        pose=PoseType.SITTING,
        outfit=OutfitType.BUSINESS_SUIT,
        outfit_detail="a tailored charcoal suit",
        expression="soft smile",
        activity="reviewing paperwork",
        setting="a quiet office",
        narrative=marker,
    )
    req = scene_to_pipeline_request(char, scene, BatchControls())
    for field in (req.prompt, req.outfitDetail, req.expression, req.activity, req.negativePrompt):
        assert field is None or marker not in field, f"narrative leaked into: {field}"


# ---------------------------------------------------------------------------
# WS3.2: outfit_denoise / outfit_prompt_mode threading
# ---------------------------------------------------------------------------
def test_outfit_denoise_set_for_non_naked_outfit():
    char = _character()
    controls = BatchControls(outfit_denoise=0.85)
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.BUSINESS_SUIT), controls)
    assert req.outfitDenoise == 0.85


def test_outfit_denoise_none_when_no_outfit_step():
    char = _character()
    controls = BatchControls(outfit_denoise=0.85)
    req = scene_to_pipeline_request(char, _scene(outfit=None), controls)
    assert req.outfit is None
    assert req.outfitDenoise is None


def test_outfit_denoise_none_for_naked_outfit():
    char = _character()
    # blocked_outfits defaults to [NAKED]; clear it so NAKED survives to the request.
    controls = BatchControls(outfit_denoise=0.85, blocked_outfits=[])
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.NAKED), controls)
    assert req.outfit == OutfitType.NAKED
    assert req.outfitDenoise is None


def test_outfit_denoise_defaults_to_085_for_outfit_step():
    # BatchControls.outfit_denoise defaults to None, but the mapper now applies a stronger
    # 0.85 default when a real (non-NAKED) outfit is present so the dressed-by-default avatar
    # garment is actually removed (was: passed None through -> engine ~0.80).
    char = _character()
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.BUSINESS_SUIT), BatchControls())
    assert req.outfitDenoise == 0.85


def test_outfit_prompt_mode_threaded_from_controls():
    char = _character()
    controls = BatchControls(outfit_prompt_mode="replace")
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.BUSINESS_SUIT), controls)
    assert req.outfitPromptMode == "replace"


def test_outfit_prompt_mode_defaults_to_replace():
    # Batch default flipped standard -> replace: dressed-by-default avatars need an explicit
    # remove-then-replace lead-in or the swap reconstructs the original garment.
    char = _character()
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.BUSINESS_SUIT), BatchControls())
    assert req.outfitPromptMode == "replace"


# ---------------------------------------------------------------------------
# B2: additive dressing on a nude base overrides the (incoherent) replace mode
# ---------------------------------------------------------------------------
def test_nude_base_source_forces_dress_mode_for_garment():
    # A populated nude_base_url makes the swap SOURCE a bare body, where "replace"
    # ("remove the current outfit…") is incoherent — the mapper forces "dress".
    char = _character()
    char.nude_base_url = "https://x.supabase.co/nude.png"
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.BUSINESS_SUIT), BatchControls())
    assert req.source_image == "https://x.supabase.co/nude.png"
    assert req.outfitPromptMode == "dress"  # overrides controls' "replace"


def test_no_nude_base_keeps_controls_prompt_mode():
    # Without a nude base (hero-photo source) the controls value passes straight through.
    char = _character()  # nude_base_url defaults to None
    req = scene_to_pipeline_request(
        char, _scene(outfit=OutfitType.BUSINESS_SUIT),
        BatchControls(outfit_prompt_mode="standard"),
    )
    assert req.outfitPromptMode == "standard"


def test_nude_base_naked_outfit_is_not_dressed():
    # NAKED never gets "dress" (nothing to additively add) even on a nude source —
    # the controls value is kept. blocked_outfits cleared so NAKED reaches the request.
    char = _character()
    char.nude_base_url = "https://x.supabase.co/nude.png"
    controls = BatchControls(blocked_outfits=[], outfit_prompt_mode="replace")
    req = scene_to_pipeline_request(char, _scene(outfit=OutfitType.NAKED), controls)
    assert req.outfit == OutfitType.NAKED
    assert req.outfitPromptMode == "replace"  # NOT "dress"


# ---------------------------------------------------------------------------
# B1: location (raw enum value) is threaded onto the request for the pose step
# ---------------------------------------------------------------------------
def test_location_threaded_onto_request():
    char = _character()
    scene = _scene(pose=PoseType.SITTING, location=LocationType.BEACH)
    req = scene_to_pipeline_request(char, scene, BatchControls())
    assert req.location == "beach"  # raw enum-value string, phrase-ified at the pose step


# ---------------------------------------------------------------------------
# W3 prep: lighting / timeOfDay flow from the scene onto the request (additive)
# ---------------------------------------------------------------------------
def test_lighting_and_time_of_day_mapped_from_scene():
    char = _character()
    scene = _scene(
        pose=PoseType.SITTING,
        time_of_day=TimeOfDayType.GOLDEN_HOUR, lighting=LightingType.CANDLELIT,
    )
    req = scene_to_pipeline_request(char, scene, BatchControls())
    assert req.lighting == "candlelit"      # enum-value string, ready for the W3 pose step
    assert req.timeOfDay == "golden_hour"


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
