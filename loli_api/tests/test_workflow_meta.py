"""
Tests for services.workflow_meta.describe_template — tier detection (2511full /
rapid_cropstitch / v1 / unknown) and sampler-value extraction off a LOADED
ComfyUI workflow template, plus the pipeline_worker wiring that populates
PipelineBackgroundWorker.workflow_meta at load time.

Runs under pytest or directly: python loli_api/tests/test_workflow_meta.py
"""
import asyncio
import json
from pathlib import Path

from services.workflow_meta import (
    describe_template,
    TIER_2511FULL,
    TIER_RAPID_CROPSTITCH,
    TIER_POSE_2511,
    TIER_V1,
    TIER_UNKNOWN,
)

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tier detection on the three real outfit-step templates
# ---------------------------------------------------------------------------
def test_2511full_tier_on_real_template():
    wf = _load("outfit_cropstitch_2511full_API.json")
    meta = describe_template(wf)
    assert meta["tier"] == TIER_2511FULL == "2511full"
    # Full (non-distilled) 2511 sampler: >20 steps, cfg 2.5, denoise 0.9 (see
    # test_full2511_workflow.py for why these specific values matter).
    assert meta["sampler"] == {"steps": 20, "cfg": 2.5, "denoise": 0.9}


def test_rapid_cropstitch_tier_on_real_template():
    wf = _load("outfit_cropstitch_API.json")
    meta = describe_template(wf)
    assert meta["tier"] == TIER_RAPID_CROPSTITCH == "rapid_cropstitch"
    # Distilled Rapid sampler: 8 steps, cfg 1.0 (negatives are inert at cfg=1).
    assert meta["sampler"] == {"steps": 8, "cfg": 1.0, "denoise": 0.9}


def test_v1_tier_on_real_template():
    wf = _load("test_final_API.json")
    meta = describe_template(wf)
    assert meta["tier"] == TIER_V1 == "v1"
    assert meta["sampler"] == {"steps": 8, "cfg": 1.0, "denoise": 0.8}


def test_maskpreview_variant_is_also_rapid_cropstitch():
    # outfit_cropstitch_maskpreview_API.json is a debug variant of the same V2
    # graph (has node 235/InpaintCropImproved, no node 301) — same tier.
    wf = _load("outfit_cropstitch_maskpreview_API.json")
    assert describe_template(wf)["tier"] == TIER_RAPID_CROPSTITCH


# ---------------------------------------------------------------------------
# Pose graphs: no node "106" -> sampler falls back to node "3", and the pose
# step is classified on its OWN axis (v1 Rapid graph vs. Tier-A 2511 graph).
# ---------------------------------------------------------------------------
def test_pose_graph_sampler_falls_back_to_node_3():
    wf = _load("edit_pose_action.json")
    meta = describe_template(wf)
    # The v1 Rapid pose graph has a ReActorFaceSwap at node 200 (so it's detected as
    # a pose graph) but NOT the native 2511 UNETLoader at node 301, so it reports the
    # catch-all "v1" tier — unchanged from before pose_2511 existed.
    assert meta["tier"] == TIER_V1
    assert "106" not in wf
    assert meta["sampler"] == {"steps": 4, "cfg": 1, "denoise": 1}


def test_pose_2511_tier_on_real_template():
    wf = _load("pose_2511_API.json")
    meta = describe_template(wf)
    # The Tier-A pose graph is a pose graph (ReActorFaceSwap at 200) AND carries the
    # native 2511 UNETLoader (node 301), so it reports its own "pose_2511" tier — even
    # though it reuses the outfit 2511 loader block. This is what makes batch A/Bs
    # identifiable in character_images.metadata -> workflow_meta -> steps[].tier.
    assert meta["tier"] == TIER_POSE_2511 == "pose_2511"
    assert "106" not in wf
    # Full re-pose sampler: 20 steps, cfg 2.5, denoise 1.0 (read off node 3).
    assert meta["sampler"] == {"steps": 20, "cfg": 2.5, "denoise": 1.0}


def test_pose_2511_does_not_leak_into_outfit_2511_tier():
    # Guard the ordering in describe_template: the 2511 pose graph reuses node 301, so
    # if the pose check didn't run FIRST it would misreport as the outfit "2511full".
    assert describe_template(_load("pose_2511_API.json"))["tier"] != TIER_2511FULL
    # ...and conversely the outfit 2511 graph (SAMModelLoader at 200, not ReActor) must
    # stay "2511full", never "pose_2511".
    assert describe_template(_load("outfit_cropstitch_2511full_API.json"))["tier"] == TIER_2511FULL


# ---------------------------------------------------------------------------
# Unknown / missing / malformed input
# ---------------------------------------------------------------------------
def test_none_template_is_unknown():
    meta = describe_template(None)
    assert meta["tier"] == TIER_UNKNOWN == "unknown"
    assert meta["sampler"] == {"steps": None, "cfg": None, "denoise": None}


def test_empty_dict_template_is_unknown():
    meta = describe_template({})
    assert meta["tier"] == TIER_UNKNOWN
    assert meta["sampler"] == {"steps": None, "cfg": None, "denoise": None}


def test_template_with_neither_sampler_node_yields_none_sampler_values():
    # A template that matches a tier (v1 catch-all) but carries no KSampler at
    # all (e.g. a stub/partial graph) must not raise — sampler values are None.
    meta = describe_template({"1": {"class_type": "LoadImage", "inputs": {}}})
    assert meta["tier"] == TIER_V1
    assert meta["sampler"] == {"steps": None, "cfg": None, "denoise": None}


def test_2511_marker_takes_precedence_over_cropstitch_marker():
    # Synthetic template with both markers present: 2511full wins (matches the
    # real outfit_cropstitch_2511full_API.json, which has both node 301 AND a
    # node 235 InpaintCropImproved).
    wf = {
        "301": {"class_type": "UNETLoader", "inputs": {}},
        "235": {"class_type": "InpaintCropImproved", "inputs": {}},
    }
    assert describe_template(wf)["tier"] == TIER_2511FULL


def test_cropstitch_node_235_wrong_class_type_does_not_match():
    wf = {"235": {"class_type": "SomethingElse", "inputs": {}}}
    assert describe_template(wf)["tier"] == TIER_V1


# ---------------------------------------------------------------------------
# Cross-check: local reimplementation must agree with the endpoint's
# _is_cropstitch_template on every real template (guards against drift between
# the two copies — see workflow_meta.py's module docstring for why it's a
# separate reimplementation rather than an import).
# ---------------------------------------------------------------------------
def test_cropstitch_detection_matches_endpoint_implementation_on_real_templates():
    from api.v1.endpoints.outfit import _is_cropstitch_template as endpoint_check
    from services.workflow_meta import _is_cropstitch_template as meta_check

    for name in (
        "outfit_cropstitch_2511full_API.json",
        "outfit_cropstitch_API.json",
        "outfit_cropstitch_maskpreview_API.json",
        "test_final_API.json",
        "edit_pose_action.json",
    ):
        wf = _load(name)
        assert meta_check(wf) == endpoint_check(wf), f"mismatch on {name}"


# ---------------------------------------------------------------------------
# pipeline_worker wiring: _load_workflows() populates self.workflow_meta.
# Fully offline — _load_workflows only reads local JSON files, no network/RunPod
# call, mirroring the instantiation pattern used by test_photo_style.py.
# ---------------------------------------------------------------------------
def test_pipeline_worker_load_workflows_populates_workflow_meta():
    from workers.pipeline_worker import PipelineBackgroundWorker

    w = PipelineBackgroundWorker(
        job_manager=None,
        comfyui_client=None,
        storage_service=None,
        pose_workflow_path=str(_WF_DIR / "edit_pose_action.json"),
        outfit_workflow_path=str(_WF_DIR / "outfit_cropstitch_API.json"),
        background_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )
    asyncio.run(w._load_workflows())

    assert set(w.workflow_meta.keys()) == {"pose", "outfit", "background"}

    outfit_meta = w.workflow_meta["outfit"]
    assert outfit_meta["tier"] == "rapid_cropstitch"
    assert outfit_meta["sampler"]["steps"] == 8
    assert Path(outfit_meta["path"]).name == "outfit_cropstitch_API.json"
    assert Path(outfit_meta["path"]).is_absolute()  # resolved, not the raw input string

    assert w.workflow_meta["background"]["tier"] == "v1"
    assert w.workflow_meta["pose"]["sampler"] == {"steps": 4, "cfg": 1, "denoise": 1}


def test_pipeline_worker_workflow_meta_empty_before_load():
    from workers.pipeline_worker import PipelineBackgroundWorker

    w = PipelineBackgroundWorker(
        job_manager=None,
        comfyui_client=None,
        storage_service=None,
        pose_workflow_path=str(_WF_DIR / "edit_pose_action.json"),
        outfit_workflow_path=str(_WF_DIR / "outfit_cropstitch_API.json"),
    )
    assert w.workflow_meta == {}


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
