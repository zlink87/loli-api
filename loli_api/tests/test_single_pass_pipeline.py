"""
Single-pass batch pipeline (CORE FLOW).

An eligible batch item (nude-base source + a pose + an outfit) collapses to ONE
pose-graph job that dresses + re-scenes from the nude base in a single full-frame
re-diffusion, instead of the legacy outfit -> background -> pose chain.

Covers:
  * PipelineBackgroundWorker._determine_active_steps -> ["pose"] when singlePassEdit
    is set (and a pose exists); the legacy ordered list otherwise;
  * the single-pass pose positive (built directly AND via _build_step_workflow) uses
    "Dress her in:" (additive) + "Place her in:" (scene from scratch), and drops the
    "Keep the same background…" clause and the "keep her state of dress… wearing"
    continuity contradiction that would fight a nude-base source;
  * the NAKED tier keeps the state-of-dress wording (literally true vs a nude base);
  * the single-pass scene text is scenery-only — no mood phrases, no time/lighting
    duplication (those ride the pose tail via the request's lighting/timeOfDay);
  * compute_estimate / _active_steps_for_scene count 1 job for a single-pass-eligible
    scene and the legacy 3 otherwise.

Runs under pytest or directly: python loli_api/tests/test_single_pass_pipeline.py
"""
import json
from pathlib import Path
from types import SimpleNamespace

import models.requests as _mr

# These tests exercise mapping/prompt/step logic, not the SSRF allowlist.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import (
    PoseType, OutfitType, NudityLevel, LocationType, TimeOfDayType, LightingType,
    KinkType, PersonalityType,
)
from models.requests import PersonaOptions, PipelineEditRequest
from models.batch import BatchControls
from models.scene import SceneSpec
from services import scene_vocab as sv
from services.scene_mapper import scene_to_pipeline_request
from services.story_planner import Character
from services.batch_orchestrator import compute_estimate, _active_steps_for_scene
from api.v1.endpoints.pose import build_pose_prompt
from api.v1.endpoints.outfit import outfit_continuity_text
from workers.pipeline_worker import PipelineBackgroundWorker

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"

_KEEP_BG = "Keep the same background, location and environment as image 1"
_WEARING_CONTRADICTION = "keep her state of dress and every garment exactly as in image 1"


def _character(nude=True):
    p = PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation="nurse", relationship="girlfriend",
    )
    c = Character(persona=p, hero_photo_url="https://x.supabase.co/hero.png")
    if nude:
        c.nude_base_url = "https://x.supabase.co/nude.png"
    return c


def _scene(**kw):
    base = dict(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
        location=LocationType.HOME_BEDROOM, time_of_day=TimeOfDayType.NIGHT,
        lighting=LightingType.CANDLELIT,
    )
    base.update(kw)
    return SceneSpec(**base)


def _worker():
    # _determine_active_steps / _build_step_workflow need no live services; templates are
    # only loaded lazily by _load_workflows (called explicitly where a graph is needed).
    return PipelineBackgroundWorker(
        job_manager=None, comfyui_client=None, storage_service=None,
        pose_workflow_path=str(_WF_DIR / "edit_pose_action.json"),
        outfit_workflow_path=str(_WF_DIR / "test_final_API.json"),
        background_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )


def _req(**kw):
    base = dict(source_image="https://x.supabase.co/s.png")
    base.update(kw)
    return PipelineEditRequest(**base)


# ---------------------------------------------------------------------------
# _determine_active_steps
# ---------------------------------------------------------------------------
def test_determine_active_steps_collapses_to_pose_when_single_pass():
    w = _worker()
    req = _req(
        pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT,
        prompt="a sunlit loft", singlePassEdit=True,
    )
    # All three steps would be active in legacy mode, but single-pass collapses to pose.
    assert w._determine_active_steps(req) == ["pose"]


def test_determine_active_steps_legacy_list_when_not_single_pass():
    w = _worker()
    req = _req(
        pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT,
        prompt="a sunlit loft", singlePassEdit=False,
    )
    # Default order outfit -> background -> pose, all three enabled.
    assert w._determine_active_steps(req) == ["outfit", "background", "pose"]


def test_determine_active_steps_single_pass_without_pose_stays_legacy():
    # singlePassEdit only collapses when a pose is present (the pose graph is what runs).
    w = _worker()
    req = _req(outfit=OutfitType.BUSINESS_SUIT, prompt="a loft", singlePassEdit=True)
    assert w._determine_active_steps(req) == ["outfit", "background"]


# ---------------------------------------------------------------------------
# single-pass pose positive: dress + scene from scratch, no continuity contradiction
# ---------------------------------------------------------------------------
def test_single_pass_pose_prompt_dresses_and_scenes_from_scratch():
    p = build_pose_prompt(
        PoseType.SITTING,
        outfit_text="a charcoal business suit",
        location="home_bedroom",
        scene_text="a cozy sunlit loft with warm decor",
        dress_mode=True,
    )
    assert "Place her in: a cozy sunlit loft with warm decor." in p
    assert "Dress her in: a charcoal business suit" in p
    assert _KEEP_BG not in p                     # no background to "keep"
    assert "The scene is" not in p               # scene_text subsumes the location anchor
    assert _WEARING_CONTRADICTION not in p       # additive dress, not continuity


def test_single_pass_naked_tier_keeps_state_of_dress_wording():
    # NAKED-tier prose ("completely naked, …") is literally true against a nude base, so it
    # keeps the continuity phrasing even in dress_mode — never "Dress her in: naked".
    naked_text = outfit_continuity_text(OutfitType.NAKED, NudityLevel.HIGH, None)
    p = build_pose_prompt(
        PoseType.SITTING, outfit_text=naked_text,
        scene_text="a dim bedroom", dress_mode=True,
    )
    assert "keep her state of dress exactly as" in p
    assert "Dress her in:" not in p
    assert _KEEP_BG not in p


def test_legacy_pose_prompt_unchanged_when_flags_off():
    # Defaults (scene_text=None, dress_mode=False) keep the keep-background + continuity path.
    p = build_pose_prompt(
        PoseType.SITTING, outfit_text="a charcoal business suit", location="home_bedroom",
    )
    assert _KEEP_BG in p
    assert "In image 1 she is wearing a charcoal business suit" in p
    assert "Place her in:" not in p and "Dress her in:" not in p


def test_build_step_workflow_threads_single_pass_into_node_114():
    # Integration: the worker reads singlePassEdit off the request and threads dress_mode +
    # scene_text (request.prompt) into build_pose_prompt, landing in node 114.
    import asyncio

    w = _worker()
    asyncio.run(w._load_workflows())
    req = _req(
        pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT,
        nudityLevel=NudityLevel.LOW, prompt="a cozy sunlit loft", singlePassEdit=True,
    )
    wf = w._build_step_workflow("pose", req, "src.png", 7, "job", pose_ref_name="ref.png")
    node114 = wf["114"]["inputs"]["prompt"]
    assert "Place her in: a cozy sunlit loft." in node114
    assert "Dress her in:" in node114
    assert _KEEP_BG not in node114


# ---------------------------------------------------------------------------
# single-pass scene text is scenery-only (mood-free, no time/lighting duplication)
# ---------------------------------------------------------------------------
def test_single_pass_scene_text_has_no_mood_or_time_lighting():
    char = _character()
    mk = [list(KinkType)[0]]
    mp = list(PersonalityType)[0]
    scene = _scene(
        pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT,
        mood_kinks=mk, mood_personality=mp,
        time_of_day=TimeOfDayType.NIGHT, lighting=LightingType.CANDLELIT,
    )
    req = scene_to_pipeline_request(char, scene, BatchControls(), single_pass=True)
    assert req.singlePassEdit is True

    mood_phrase = sv.scene_mood_phrase(mk, mp)
    assert mood_phrase and mood_phrase not in (req.prompt or "")
    # Time/lighting must NOT be duplicated in the scene text — they ride the pose tail.
    assert sv.time_of_day_phrase("night") not in (req.prompt or "")
    assert sv.lighting_phrase("candlelit") not in (req.prompt or "")
    # …but the request still carries them so the pose step can re-light/re-time the frame.
    assert req.lighting == "candlelit" and req.timeOfDay == "night"


# ---------------------------------------------------------------------------
# estimate: single-pass-eligible scene counts as 1 job, legacy 3
# ---------------------------------------------------------------------------
_EST_SETTINGS = SimpleNamespace(
    RUNPOD_AVG_STEP_SECONDS=60, BATCH_WORKER_POOL_SIZE=1,
    RUNPOD_GPU_USD_PER_SECOND=0.0, BATCH_SINGLE_PASS_EDIT=True,
)


def test_active_steps_single_pass_eligible_is_one_job():
    scene = _scene(pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT)
    # eligible: single-pass on + a nude base -> 1
    assert _active_steps_for_scene(
        scene, BatchControls(), single_pass=True, has_nude_base=True
    ) == 1
    # no nude base -> legacy 3 (background + pose + outfit)
    assert _active_steps_for_scene(
        scene, BatchControls(), single_pass=True, has_nude_base=False
    ) == 3
    # flag off -> legacy 3
    assert _active_steps_for_scene(
        scene, BatchControls(), single_pass=False, has_nude_base=True
    ) == 3
    # defaults (both off) reproduce the legacy count
    assert _active_steps_for_scene(scene, BatchControls()) == 3


def test_active_steps_single_pass_needs_both_pose_and_outfit():
    pose_only = _scene(pose=PoseType.SITTING)
    outfit_only = _scene(outfit=OutfitType.BUSINESS_SUIT)
    # Missing outfit -> not eligible (pose+background = 2); missing pose -> not eligible
    # (background+outfit = 2). Neither collapses to 1.
    assert _active_steps_for_scene(
        pose_only, BatchControls(), single_pass=True, has_nude_base=True
    ) == 2
    assert _active_steps_for_scene(
        outfit_only, BatchControls(), single_pass=True, has_nude_base=True
    ) == 2


def test_compute_estimate_reflects_single_pass_collapse():
    scenes = [
        _scene(pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT, global_index=i)
        for i in range(4)
    ]
    with_base = compute_estimate(scenes, BatchControls(), _EST_SETTINGS, has_nude_base=True)
    without_base = compute_estimate(scenes, BatchControls(), _EST_SETTINGS, has_nude_base=False)
    assert with_base.est_runpod_jobs == 4            # 4 items x 1 pose job
    assert without_base.est_runpod_jobs == 12         # 4 items x 3 steps
    assert with_base.items_total == without_base.items_total == 4


def test_compute_estimate_flag_off_is_legacy_even_with_base():
    off_settings = SimpleNamespace(
        RUNPOD_AVG_STEP_SECONDS=60, BATCH_WORKER_POOL_SIZE=1,
        RUNPOD_GPU_USD_PER_SECOND=0.0, BATCH_SINGLE_PASS_EDIT=False,
    )
    scenes = [_scene(pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT)]
    est = compute_estimate(scenes, BatchControls(), off_settings, has_nude_base=True)
    assert est.est_runpod_jobs == 3


def test_compute_estimate_missing_flag_defaults_to_legacy():
    # A settings stub without BATCH_SINGLE_PASS_EDIT must not raise -> legacy count.
    bare = SimpleNamespace(
        RUNPOD_AVG_STEP_SECONDS=60, BATCH_WORKER_POOL_SIZE=1, RUNPOD_GPU_USD_PER_SECOND=0.0,
    )
    scenes = [_scene(pose=PoseType.SITTING, outfit=OutfitType.BUSINESS_SUIT)]
    est = compute_estimate(scenes, BatchControls(), bare, has_nude_base=True)
    assert est.est_runpod_jobs == 3


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
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
