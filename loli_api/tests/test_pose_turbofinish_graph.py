"""
TURBO FINISHING PASS workstream (07-14): one new ComfyUI graph + one new
``prepare_pose_workflow`` kwarg + one config knob. Ships DARK — zero runtime change
until ops stages the Z-Image-Turbo model files on the RunPod volume and flips
``COMFYUI_POSE_WORKFLOW_PATH_2511`` to the turbofinish graph (see
docs/RUNPOD_SETUP.md §5c/§5d).

New graph:
  * workflows/pose_2511_skinlora_faceref_turbofinish_API.json

What it is: a clone of pose_2511_skinlora_faceref_API.json with a LOW-denoise
Z-Image-Turbo img2img refine (nodes 401-410) inserted between the Qwen VAEDecode
(node 8) and the ReActor swap (node 200). Qwen still owns composition (pose/outfit/
scene from refs); Turbo only re-skins the frame with its natural prior; ReActor then
stamps the hero face onto the refined frame. All in one graph/job.

Covers:
  * parses as JSON with no dangling node-id references;
  * BOTH model stacks' loaders are present and correct — the Qwen edit stack
    (301 UNET / 302 CLIP / 303 VAE) untouched, PLUS the turbo stack (401 UNET
    z_image_turbo_nvfp4 / 402 CLIP qwen_3_4b_fp4_mixed lumina2 / 403 VAE ae);
  * node 200's input_image is repointed to the turbo VAEDecode (node 410), not the
    Qwen decode (node 8) — the ReActor swap runs on the refined frame;
  * node 301 still trips ``_is_pose_2511_template`` (the marker is untouched);
  * the LoRA chain is intact (304 -> 305 -> 306 -> KSampler 3) and the Qwen encoders
    (114 positive / 115 negative) keep their image3 (hero face-ref) wire;
  * the inserted turbo chain is wired exactly (404 positive CLIPTextEncode -> 405
    ConditioningZeroOut -> 409 SamplerCustom @ cfg 1, with 406 VAEEncode off node 8,
    407 BasicScheduler carrying denoise 0.32, 408 KSamplerSelect, 410 VAEDecode);
  * ``prepare_pose_workflow`` mirrors the pose positive prompt into node 404 (turbo
    positive) on THIS template and touches no other template's node 404;
  * ``turbo_finish_denoise`` writes node 407's denoise only when >= 0 AND node 407
    exists — the None/-1.0 sentinel leaves the baked 0.32, and a non-turbofinish
    template is a byte-identical no-op;
  * ``pose_template_has_turbo_finish`` is True here and False on the plain faceref base.

Kept in its OWN file (not test_dark_asset_graphs.py / test_pose_2511_workflow.py /
test_pose_output_megapixels.py) per this workstream's ownership boundary — other
agents own those files concurrently. Fully offline — reads local JSON only.

Runs under pytest or directly: python loli_api/tests/test_pose_turbofinish_graph.py
"""
import json
from pathlib import Path

from api.v1.endpoints.pose import (
    prepare_pose_workflow,
    _is_pose_2511_template,
    pose_template_has_turbo_finish,
    pose_template_has_face_ref_conditioning,
)

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"

_TURBOFINISH_GRAPH = "pose_2511_skinlora_faceref_turbofinish_API.json"
_FACEREF_BASE_GRAPH = "pose_2511_skinlora_faceref_API.json"


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _dangling_refs(g: dict):
    """Every ['id', idx] input reference must point at a node id that exists."""
    ids = set(g)
    return [
        f"{nid}.{k} -> {v[0]}"
        for nid, n in g.items()
        for k, v in n.get("inputs", {}).items()
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in ids
    ]


# ---------------------------------------------------------------------------
# Graph lint: valid JSON, no dangling refs
# ---------------------------------------------------------------------------
def test_turbofinish_graph_parses_and_has_no_dangling_refs():
    g = _load(_TURBOFINISH_GRAPH)
    assert isinstance(g, dict) and g
    assert _dangling_refs(g) == [], _dangling_refs(g)


# ---------------------------------------------------------------------------
# Both model stacks' loaders present
# ---------------------------------------------------------------------------
def test_qwen_edit_stack_untouched():
    g = _load(_TURBOFINISH_GRAPH)
    # Qwen edit stack: 301 UNET (2511 marker) / 302 CLIP / 303 VAE — identical to base.
    assert g["301"]["class_type"] == "UNETLoader"
    assert g["301"]["inputs"]["unet_name"] == "qwen_image_edit_2511_fp8mixed.safetensors"
    assert g["302"]["class_type"] == "CLIPLoader"
    assert g["302"]["inputs"]["clip_name"] == "qwen_2.5_vl_7b_fp8_scaled.safetensors"
    assert g["302"]["inputs"]["type"] == "qwen_image"
    assert g["303"]["class_type"] == "VAELoader"
    assert g["303"]["inputs"]["vae_name"] == "qwen_image_vae.safetensors"


def test_turbo_stack_loaders_present_and_correct():
    g = _load(_TURBOFINISH_GRAPH)
    # Turbo stack: 401 UNET / 402 CLIP (lumina2) / 403 VAE (ae). FP4 variants chosen so
    # the turbo stack co-resides with the resident Qwen stack inside 48GB without thrash
    # (see docs/RUNPOD_SETUP.md §5c/§5d for the VRAM arithmetic).
    assert g["401"]["class_type"] == "UNETLoader"
    assert g["401"]["inputs"]["unet_name"] == "z_image_turbo_nvfp4.safetensors"
    assert g["402"]["class_type"] == "CLIPLoader"
    assert g["402"]["inputs"]["clip_name"] == "qwen_3_4b_fp4_mixed.safetensors"
    assert g["402"]["inputs"]["type"] == "lumina2"
    assert g["403"]["class_type"] == "VAELoader"
    assert g["403"]["inputs"]["vae_name"] == "ae.safetensors"


# ---------------------------------------------------------------------------
# ReActor runs on the turbo-refined frame; 2511 marker intact
# ---------------------------------------------------------------------------
def test_reactor_input_repointed_to_turbo_decode():
    g = _load(_TURBOFINISH_GRAPH)
    # node 200.input_image must read the turbo VAEDecode (410), NOT the Qwen decode (8).
    assert g["200"]["class_type"] == "ReActorFaceSwap"
    assert g["200"]["inputs"]["input_image"] == ["410", 0]
    # ReActor still stamps the hero donor (node 210) at the baked strengths.
    assert g["200"]["inputs"]["source_image"] == ["210", 0]
    assert g["200"]["inputs"]["codeformer_weight"] == 0.7
    assert g["200"]["inputs"]["face_restore_visibility"] == 0.65
    # SaveImage still reads the face-locked ReActor output.
    assert g["164"]["inputs"]["images"] == ["200", 0]


def test_turbofinish_graph_keeps_2511_marker():
    g = _load(_TURBOFINISH_GRAPH)
    assert _is_pose_2511_template(g) is True


# ---------------------------------------------------------------------------
# LoRA chain intact; Qwen encoders keep image3 (face-ref)
# ---------------------------------------------------------------------------
def test_lora_chain_and_ksampler_intact():
    g = _load(_TURBOFINISH_GRAPH)
    assert g["304"]["inputs"]["lora_name"] == "URP_20.safetensors"
    assert g["304"]["inputs"]["model"] == ["301", 0]
    assert g["305"]["inputs"]["lora_name"] == "qwen-image-edit-plus-nsfw-lora.safetensors"
    assert g["305"]["inputs"]["model"] == ["304", 0]
    assert g["305"]["inputs"]["strength_model"] == 0.65
    assert g["306"]["inputs"]["lora_name"] == "qwen-edit-skin.safetensors"
    assert g["306"]["inputs"]["model"] == ["305", 0]
    assert g["306"]["inputs"]["strength_model"] == 1.0
    # The Qwen KSampler (node 3) still reads the tail of the LoRA chain (node 306).
    assert g["3"]["class_type"] == "KSampler"
    assert g["3"]["inputs"]["model"] == ["306", 0]


def test_qwen_encoders_keep_image3_face_ref():
    g = _load(_TURBOFINISH_GRAPH)
    assert g["114"]["inputs"]["image3"] == ["210", 0]
    assert g["115"]["inputs"]["image3"] == ["210", 0]
    assert pose_template_has_face_ref_conditioning(g) is True


# ---------------------------------------------------------------------------
# The inserted turbo refine chain is wired exactly
# ---------------------------------------------------------------------------
def test_turbo_refine_chain_wiring():
    g = _load(_TURBOFINISH_GRAPH)
    # 404 turbo positive CLIPTextEncode off the turbo CLIP (402).
    assert g["404"]["class_type"] == "CLIPTextEncode"
    assert g["404"]["inputs"]["clip"] == ["402", 0]
    # 405 negative = ConditioningZeroOut of the positive (turbo runs cfg 1).
    assert g["405"]["class_type"] == "ConditioningZeroOut"
    assert g["405"]["inputs"]["conditioning"] == ["404", 0]
    # 406 VAEEncode: the Qwen decode (node 8) into the turbo VAE (403).
    assert g["406"]["class_type"] == "VAEEncode"
    assert g["406"]["inputs"]["pixels"] == ["8", 0]
    assert g["406"]["inputs"]["vae"] == ["403", 0]
    # 407 BasicScheduler carries the refine strength (denoise) off the turbo model.
    assert g["407"]["class_type"] == "BasicScheduler"
    assert g["407"]["inputs"]["model"] == ["401", 0]
    assert g["407"]["inputs"]["denoise"] == 0.32
    # 408 sampler select.
    assert g["408"]["class_type"] == "KSamplerSelect"
    # 409 SamplerCustom @ cfg 1, low-denoise img2img on the turbo model.
    assert g["409"]["class_type"] == "SamplerCustom"
    assert g["409"]["inputs"]["cfg"] == 1
    assert g["409"]["inputs"]["model"] == ["401", 0]
    assert g["409"]["inputs"]["positive"] == ["404", 0]
    assert g["409"]["inputs"]["negative"] == ["405", 0]
    assert g["409"]["inputs"]["sampler"] == ["408", 0]
    assert g["409"]["inputs"]["sigmas"] == ["407", 0]
    assert g["409"]["inputs"]["latent_image"] == ["406", 0]
    # 410 VAEDecode: refined latent back to pixels via the turbo VAE, feeding ReActor.
    assert g["410"]["class_type"] == "VAEDecode"
    assert g["410"]["inputs"]["samples"] == ["409", 0]
    assert g["410"]["inputs"]["vae"] == ["403", 0]


# ---------------------------------------------------------------------------
# Predicate: pose_template_has_turbo_finish
# ---------------------------------------------------------------------------
def test_has_turbo_finish_true_here_false_on_base():
    assert pose_template_has_turbo_finish(_load(_TURBOFINISH_GRAPH)) is True
    assert pose_template_has_turbo_finish(_load(_FACEREF_BASE_GRAPH)) is False
    assert pose_template_has_turbo_finish({}) is False


# ---------------------------------------------------------------------------
# Preparer: mirrors the pose positive prompt into node 404 on THIS template
# ---------------------------------------------------------------------------
def test_preparer_mirrors_prompt_into_turbo_positive():
    g = _load(_TURBOFINISH_GRAPH)
    out = prepare_pose_workflow(g, "src.png", "ref.png", prompt="A woman on a sunny beach")
    # Node 114 (Qwen positive) AND node 404 (turbo positive) both carry the same text.
    assert out["114"]["inputs"]["prompt"] == "A woman on a sunny beach"
    assert out["404"]["inputs"]["text"] == "A woman on a sunny beach"


def test_preparer_does_not_touch_node_404_on_non_turbofinish_template():
    base = _load(_FACEREF_BASE_GRAPH)
    assert "404" not in base
    out = prepare_pose_workflow(base, "src.png", "ref.png", prompt="X")
    # No node 404 gets invented on a template that never had one.
    assert "404" not in out


# ---------------------------------------------------------------------------
# Preparer: turbo_finish_denoise writes node 407 only when >= 0 AND node present
# ---------------------------------------------------------------------------
def test_denoise_override_writes_when_positive():
    g = _load(_TURBOFINISH_GRAPH)
    out = prepare_pose_workflow(g, "s", "r", prompt="p", turbo_finish_denoise=0.45)
    assert out["407"]["inputs"]["denoise"] == 0.45


def test_denoise_sentinel_and_none_leave_baked():
    g = _load(_TURBOFINISH_GRAPH)
    baked = g["407"]["inputs"]["denoise"]
    out_sentinel = prepare_pose_workflow(g, "s", "r", prompt="p", turbo_finish_denoise=-1.0)
    assert out_sentinel["407"]["inputs"]["denoise"] == baked
    out_none = prepare_pose_workflow(g, "s", "r", prompt="p", turbo_finish_denoise=None)
    assert out_none["407"]["inputs"]["denoise"] == baked
    # Default (kwarg omitted) also leaves the baked 0.32.
    out_default = prepare_pose_workflow(g, "s", "r", prompt="p")
    assert out_default["407"]["inputs"]["denoise"] == baked


def test_denoise_zero_is_a_valid_override():
    # 0.0 is a real denoise value (not the no-override marker) — it must be written.
    g = _load(_TURBOFINISH_GRAPH)
    out = prepare_pose_workflow(g, "s", "r", prompt="p", turbo_finish_denoise=0.0)
    assert out["407"]["inputs"]["denoise"] == 0.0


def test_denoise_override_no_op_on_non_turbofinish_template():
    base = _load(_FACEREF_BASE_GRAPH)
    assert "407" not in base
    out = prepare_pose_workflow(base, "s", "r", prompt="p", turbo_finish_denoise=0.5)
    # No node 407 gets invented; the base graph is unaffected by the knob.
    assert "407" not in out


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
    sys.exit(0)
