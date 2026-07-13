"""
Tests for D3 — the Tier-A pose graph (pose_2511_API.json): re-pose the source on
the full (non-distilled) Qwen-Image-Edit-2511 stack + realism/NSFW LoRAs at 20
steps / cfg 2.5 with a LIVE negative, instead of the distilled Rapid v1 graph
(edit_pose_action.json: 4 steps, cfg 1, inert ConditioningZeroOut negative).

Covers:
  * the graph is well-formed and keeps the SAME node-id contract the shared
    prepare_pose_workflow injects into (source/pose-ref LoadImage, prompt node,
    KSampler 3, ReActor 200, SaveImage 164, VAEDecode 8) so ONE preparer drives
    both templates;
  * the model core (2511 UNET + URP/NSFW LoRA chain), two-image conditioning, and
    a real (non-zeroed) negative wired into the sampler at cfg 2.5;
  * prepare_pose_workflow is template-aware: it injects the live negative into node
    115 ONLY on the 2511 graph and stays byte-identical to pre-D3 behavior on v1;
  * pipeline_worker reports tier "pose_2511" so batch A/Bs are identifiable.

This graph ships DEFAULT-OFF (COMFYUI_POSE_WORKFLOW_PATH_2511 empty) — these are
static/offline guards, no GPU / RunPod needed.

Runs under pytest or directly: python tests/test_pose_2511_workflow.py
"""
import asyncio
import json
from pathlib import Path

from models.enums import NudityLevel, PoseType
from api.v1.endpoints.pose import prepare_pose_workflow, _is_pose_2511_template
from services import prompt_constants as pc

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _template() -> dict:
    return _load("pose_2511_API.json")


# ---------------------------------------------------------------------------
# Graph shape: contract node ids + 2511 model core
# ---------------------------------------------------------------------------
def test_pose_2511_parses_and_keeps_the_injection_contract():
    g = _template()
    # Contract node ids prepare_pose_workflow injects into (must match v1 for a single
    # preparer to drive both templates).
    assert g["109"]["class_type"] == "LoadImage"        # source (image1)
    assert g["170"]["class_type"] == "LoadImage"        # pose reference (image2)
    assert g["114"]["class_type"] == "TextEncodeQwenImageEditPlus"  # positive prompt
    assert g["3"]["class_type"] == "KSampler"           # seed / denoise
    assert g["8"]["class_type"] == "VAEDecode"          # pre-ReActor frame (debug hook)
    assert g["200"]["class_type"] == "ReActorFaceSwap"  # face lock
    assert g["164"]["class_type"] == "SaveImage"        # post-ReActor final output


def test_pose_2511_model_core_is_full_2511_with_lora_chain():
    g = _template()
    assert g["301"]["class_type"] == "UNETLoader"
    assert g["301"]["inputs"]["unet_name"] == "qwen_image_edit_2511_fp8mixed.safetensors"
    assert g["302"]["class_type"] == "CLIPLoader" and g["302"]["inputs"]["type"] == "qwen_image"
    assert g["303"]["class_type"] == "VAELoader"
    # model chain: UNet -> realism LoRA (URP_20 @0.8) -> NSFW LoRA (@0.9) -> KSampler.
    # No DifferentialDiffusion (that node is inpaint-specific; the pose step is a full
    # re-diffusion with no mask).
    assert g["304"]["inputs"]["lora_name"] == "URP_20.safetensors"
    assert g["304"]["inputs"]["strength_model"] == 0.8
    assert g["304"]["inputs"]["model"] == ["301", 0]
    assert g["305"]["inputs"]["lora_name"] == "qwen-image-edit-plus-nsfw-lora.safetensors"
    assert g["305"]["inputs"]["strength_model"] == 0.9
    assert g["305"]["inputs"]["model"] == ["304", 0]
    assert g["3"]["inputs"]["model"] == ["305", 0]
    assert "DifferentialDiffusion" not in {n["class_type"] for n in g.values()}


def test_pose_2511_sampler_is_cfg25_20steps_euler_full_denoise():
    s = _template()["3"]["inputs"]
    assert s["steps"] == 20
    assert s["cfg"] == 2.5
    assert s["sampler_name"] == "euler"
    assert s["denoise"] == 1.0  # full re-pose is the point


def test_pose_2511_two_image_conditioning_and_live_negative():
    g = _template()
    # Both encoders take the SOURCE as image1 and the POSE REFERENCE as image2 (the
    # two-image usage the repo's v1 pose graph already evidences), sharing CLIP/VAE.
    for nid in ("114", "115"):
        inp = g[nid]["inputs"]
        assert inp["image1"] == ["109", 0]
        assert inp["image2"] == ["170", 0]
        assert inp["clip"] == ["302", 0]
        assert inp["vae"] == ["303", 0]
        assert g[nid]["class_type"] == "TextEncodeQwenImageEditPlus"
    # Negative is a REAL conditioning wired into the sampler (live at cfg 2.5), NOT the
    # v1 ConditioningZeroOut inert branch.
    assert "ConditioningZeroOut" not in {n["class_type"] for n in g.values()}
    assert g["3"]["inputs"]["positive"] == ["134", 0]
    assert g["3"]["inputs"]["negative"] == ["135", 0]
    assert g["134"]["inputs"]["conditioning"] == ["114", 0]
    assert g["135"]["inputs"]["conditioning"] == ["115", 0]


def test_pose_2511_output_size_derives_from_reference_like_v1():
    g = _template()
    # Mirrors edit_pose_action.json: the output latent is shaped by scaling the pose
    # reference (node 170) to 1MP and VAE-encoding it (denoise 1.0 replaces the
    # content, so this only sets the canvas). VAE comes from the 2511 VAELoader (303).
    assert g["93"]["class_type"] == "ImageScaleToTotalPixels"
    assert g["93"]["inputs"]["image"] == ["170", 0]
    assert g["93"]["inputs"]["megapixels"] == 1
    assert g["88"]["class_type"] == "VAEEncode"
    assert g["88"]["inputs"]["pixels"] == ["93", 0]
    assert g["88"]["inputs"]["vae"] == ["303", 0]
    assert g["3"]["inputs"]["latent_image"] == ["88", 0]


def test_pose_2511_reactor_tail_matches_v1_values():
    g = _template()
    r = g["200"]["inputs"]
    # Copied verbatim from edit_pose_action.json's node 200.
    assert r["input_image"] == ["8", 0]        # ReActor consumes the raw pose regen
    assert r["source_image"] == ["109", 0]     # hero face from the source
    assert r["face_restore_visibility"] == 0.8
    assert r["codeformer_weight"] == 0.25
    assert g["164"]["inputs"]["images"] == ["200", 0]  # save the face-locked frame
    assert g["164"]["inputs"]["filename_prefix"] == "pose_edit"


def test_pose_2511_has_no_dangling_references():
    g = _template()
    ids = set(g)
    dangling = [
        f"{nid}.{k} -> {v[0]}"
        for nid, n in g.items()
        for k, v in n.get("inputs", {}).items()
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in ids
    ]
    assert dangling == [], f"dangling refs: {dangling}"


# ---------------------------------------------------------------------------
# prepare_pose_workflow: template-aware negative injection on the 2511 tier
# ---------------------------------------------------------------------------
def test_prepare_injects_live_negative_on_2511_tier():
    g = _template()
    assert _is_pose_2511_template(g) is True
    wf = prepare_pose_workflow(
        g, "src.png", "ref.png", prompt="do the pose", seed=123,
        negative_prompt="mittens", nudity_level=NudityLevel.MEDIUM,
    )
    neg = wf["115"]["inputs"]["prompt"]
    # The distinctive EDIT_SKIN_NEGATIVE fragment must be present (proves pc.edit_negative
    # produced this string), plus the request extra and the MEDIUM nudity block.
    assert "airbrushed skin" in neg
    assert "mittens" in neg
    assert neg == pc.edit_negative("mittens", nudity_level=NudityLevel.MEDIUM)
    # Contract injections still land.
    assert wf["109"]["inputs"]["image"] == "src.png"
    assert wf["170"]["inputs"]["image"] == "ref.png"
    assert wf["114"]["inputs"]["prompt"] == "do the pose"
    assert wf["3"]["inputs"]["seed"] == 123
    # 20 baked steps survive the v1 "bump to >= 8" nudge (no-op here).
    assert wf["3"]["inputs"]["steps"] == 20


def test_prepare_negative_defaults_to_standard_edit_negative_on_2511():
    # No negative_prompt / nudity_level -> the full standard edit negative at 'low'.
    wf = prepare_pose_workflow(_template(), "src.png", "ref.png")
    assert wf["115"]["inputs"]["prompt"] == pc.edit_negative(None, nudity_level=None)
    assert "airbrushed skin" in wf["115"]["inputs"]["prompt"]


def test_prepare_reactor_knobs_and_debug_hook_work_on_2511():
    g = _template()
    wf = prepare_pose_workflow(
        g, "src.png", "ref.png", seed=7,
        debug_save_pre_reactor=True,
        reactor_restore_visibility=0.6, reactor_codeformer_weight=0.5,
    )
    # Debug SaveImage reads the pre-ReActor VAEDecode (node 8) — same contract as v1.
    assert wf["300"]["class_type"] == "SaveImage"
    assert wf["300"]["inputs"]["images"] == ["8", 0]
    assert wf["300"]["inputs"]["filename_prefix"] == "pose_preface"
    # ReActor overrides land on node 200.
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.6
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.5


# ---------------------------------------------------------------------------
# v1 graph is completely untouched by the D3 params (no negative injection)
# ---------------------------------------------------------------------------
def test_prepare_on_v1_ignores_negative_params_byte_identical():
    v1 = _load("edit_pose_action.json")
    assert _is_pose_2511_template(v1) is False
    with_neg = prepare_pose_workflow(
        v1, "src.png", "ref.png", prompt="P", seed=1,
        negative_prompt="SHOULD_BE_IGNORED", nudity_level=NudityLevel.HIGH,
    )
    without = prepare_pose_workflow(v1, "src.png", "ref.png", prompt="P", seed=1)
    # No node 115 on v1; the inert ConditioningZeroOut negative stays.
    assert "115" not in with_neg
    assert with_neg["116"]["class_type"] == "ConditioningZeroOut"
    # Passing the new params must be a true no-op vs. omitting them.
    assert json.dumps(with_neg, sort_keys=True) == json.dumps(without, sort_keys=True)
    # And "SHOULD_BE_IGNORED" appears nowhere in the serialized v1 workflow.
    assert "SHOULD_BE_IGNORED" not in json.dumps(with_neg)


# ---------------------------------------------------------------------------
# pipeline_worker wiring: pointing the pose step at pose_2511 reports tier
# "pose_2511" (fully offline — _load_workflows only reads local JSON).
# ---------------------------------------------------------------------------
def test_pipeline_worker_reports_pose_2511_tier():
    from workers.pipeline_worker import PipelineBackgroundWorker

    w = PipelineBackgroundWorker(
        job_manager=None,
        comfyui_client=None,
        storage_service=None,
        pose_workflow_path=str(_WF_DIR / "pose_2511_API.json"),
        outfit_workflow_path=str(_WF_DIR / "outfit_cropstitch_2511full_API.json"),
        background_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )
    asyncio.run(w._load_workflows())
    assert w.workflow_meta["pose"]["tier"] == "pose_2511"
    assert w.workflow_meta["pose"]["sampler"] == {"steps": 20, "cfg": 2.5, "denoise": 1.0}
    # The outfit 2511 graph (also has node 301) must NOT be confused for a pose graph.
    assert w.workflow_meta["outfit"]["tier"] == "2511full"


# ---------------------------------------------------------------------------
# Phase 5 observability: _extract_step_prompts reads back the EXACT composed
# positive/negative off a just-built pose step workflow. Negative is LIVE on
# the 2511 tier (node 115) and absent (no node 115 at all) on v1.
# ---------------------------------------------------------------------------
class _FakePoseRequest:
    """Minimal request stand-in exposing the fields _build_step_workflow reads."""

    def __init__(self, pose, nudity_level=NudityLevel.MEDIUM):
        self.pose = pose
        self.outfit = None
        self.nudityLevel = nudity_level
        self.accessories = None
        self.negativePrompt = None


def test_extract_step_prompts_pose_2511_positive_marker_and_live_negative():
    from workers.pipeline_worker import PipelineBackgroundWorker, _extract_step_prompts

    w = PipelineBackgroundWorker(
        job_manager=None, comfyui_client=None, storage_service=None,
        pose_workflow_path=str(_WF_DIR / "pose_2511_API.json"),
        outfit_workflow_path=str(_WF_DIR / "outfit_cropstitch_2511full_API.json"),
        background_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )
    asyncio.run(w._load_workflows())

    req = _FakePoseRequest(pose=PoseType.SITTING)
    wf = w._build_step_workflow(
        "pose", req, "src.png", seed=42, job_id="job-debug", pose_ref_name="ref.png",
    )
    prompts = _extract_step_prompts("pose", wf)

    # Known marker: the pose's own canned description leads the positive prompt.
    assert prompts["positive"]
    assert "sitting upright on a chair or seat" in prompts["positive"]
    assert prompts["positive"] == wf["114"]["inputs"]["prompt"]
    # Negative is LIVE on the 2511 tier -- non-empty, carries the standard
    # edit-negative fragment other tests in this file already key off.
    assert prompts["negative"]
    assert "airbrushed skin" in prompts["negative"]
    assert prompts["negative"] == wf["115"]["inputs"]["prompt"]


def test_extract_step_prompts_pose_v1_negative_is_none_inert_tier():
    from workers.pipeline_worker import PipelineBackgroundWorker, _extract_step_prompts

    w = PipelineBackgroundWorker(
        job_manager=None, comfyui_client=None, storage_service=None,
        pose_workflow_path=str(_WF_DIR / "edit_pose_action.json"),
        outfit_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )
    asyncio.run(w._load_workflows())

    req = _FakePoseRequest(pose=PoseType.SITTING)
    wf = w._build_step_workflow(
        "pose", req, "src.png", seed=42, job_id="job-debug-v1", pose_ref_name="ref.png",
    )
    prompts = _extract_step_prompts("pose", wf)

    assert prompts["positive"]
    assert "115" not in wf  # v1 graph has no live-negative node at all
    assert prompts["negative"] is None


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
