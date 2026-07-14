"""
DARK ASSETS workstream (07-14): four new ComfyUI graphs + one new
``prepare_pose_workflow`` kwarg. Everything here ships DARK — zero runtime
behavior change until ops uploads the model files to the RunPod volume and an
operator flips an env var (see docs/RUNPOD_SETUP.md "Dark quality assets").

New graphs covered:
  * workflows/pose_2511_skinlora_API.json                    (A: skin LoRA, pose)
  * workflows/outfit_cropstitch_2511full_skinlora_API.json    (A: skin LoRA, outfit)
  * workflows/pose_2511_faceboost_API.json                    (B: GPEN ReActorFaceBoost)
  * workflows/pose_2511_skinlora_faceboost_API.json           (A+B combined, pose)

Covers:
  * all four parse as JSON with no dangling node-id references;
  * the skin-LoRA graphs wire node 306 (LoraLoaderModelOnly, qwen-edit-skin.safetensors
    @ strength_model 1.0) onto node 305's output, node 305 stays softened to 0.65, and
    the node immediately downstream of the LoRA chain is repointed at ["306", 0];
  * all three pose variants (skinlora + faceboost + the skinlora+faceboost combo)
    inherit the CURRENT base pose graph's node 301 (UNETLoader, 2511 marker) and node
    200 baked ReActor values (codeformer_weight 0.7 / face_restore_visibility 0.65)
    untouched, and still trip ``_is_pose_2511_template``;
  * the faceboost graph wires node 215 (ReActorFaceBoost) into node 200's optional
    face_boost input;
  * the combined graph (pose_2511_skinlora_faceboost_API.json) carries BOTH halves at
    once: it is the skinlora graph (node 306 @ 1.0, node 305 softened to 0.65, sampler
    reading ["306", 0]) PLUS node 215 exactly as authored on the faceboost graph, wired
    into node 200's face_boost input — neither half clobbers the other;
  * ``prepare_pose_workflow(face_restore_model=...)`` writes node 200's
    face_restore_model field when truthy, and is a true no-op (byte-identical) when
    omitted/None/empty or when node 200 is absent.

Kept in its OWN file (not test_pose_2511_workflow.py / test_pose_output_megapixels.py)
per this workstream's ownership boundary — other agents own those files concurrently.
Fully offline — reads local JSON only, no GPU / RunPod needed.

Runs under pytest or directly: python loli_api/tests/test_dark_asset_graphs.py
"""
import json
from pathlib import Path

from api.v1.endpoints.pose import prepare_pose_workflow, _is_pose_2511_template

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"

_NEW_GRAPHS = (
    "pose_2511_skinlora_API.json",
    "outfit_cropstitch_2511full_skinlora_API.json",
    "pose_2511_faceboost_API.json",
    "pose_2511_skinlora_faceboost_API.json",
)
_POSE_VARIANT_GRAPHS = (
    "pose_2511_skinlora_API.json",
    "pose_2511_faceboost_API.json",
    "pose_2511_skinlora_faceboost_API.json",
)
_COMBINED_GRAPH = "pose_2511_skinlora_faceboost_API.json"


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _dangling_refs(g: dict):
    """Same checker used by test_pose_2511_workflow.py: every ['id', idx] input
    reference must point at a node id that actually exists in the graph."""
    ids = set(g)
    return [
        f"{nid}.{k} -> {v[0]}"
        for nid, n in g.items()
        for k, v in n.get("inputs", {}).items()
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in ids
    ]


# ---------------------------------------------------------------------------
# All four new graphs: valid JSON, no dangling node refs
# ---------------------------------------------------------------------------
def test_new_graphs_parse_as_valid_json():
    for name in _NEW_GRAPHS:
        g = _load(name)
        assert isinstance(g, dict) and g, name


def test_new_graphs_have_no_dangling_references():
    for name in _NEW_GRAPHS:
        g = _load(name)
        assert _dangling_refs(g) == [], f"{name}: {_dangling_refs(g)}"


# ---------------------------------------------------------------------------
# A: skin-LoRA chain (node 306) on both skinlora graphs
# ---------------------------------------------------------------------------
def test_pose_skinlora_node_306_wired_and_305_softened():
    g = _load("pose_2511_skinlora_API.json")
    assert g["306"]["class_type"] == "LoraLoaderModelOnly"
    assert g["306"]["inputs"]["lora_name"] == "qwen-edit-skin.safetensors"
    assert g["306"]["inputs"]["strength_model"] == 1.0
    assert g["306"]["inputs"]["model"] == ["305", 0]
    assert g["305"]["inputs"]["strength_model"] == 0.65
    # Pose graph: the LoRA chain feeds the KSampler (node 3) directly (no inpaint
    # mask node in between, unlike the outfit crop-and-stitch graph below).
    assert g["3"]["class_type"] == "KSampler"
    assert g["3"]["inputs"]["model"] == ["306", 0]
    # Node 305 must have exactly ONE consumer (node 3, rewired to 306) — confirms
    # nothing else still reads the pre-skin-LoRA model output.
    consumers_of_305 = [
        f"{nid}.{k}"
        for nid, n in g.items()
        for k, v in n.get("inputs", {}).items()
        if v == ["305", 0]
    ]
    assert consumers_of_305 == ["306.model"]


def test_outfit_skinlora_node_306_wired_and_305_softened():
    g = _load("outfit_cropstitch_2511full_skinlora_API.json")
    assert g["306"]["class_type"] == "LoraLoaderModelOnly"
    assert g["306"]["inputs"]["lora_name"] == "qwen-edit-skin.safetensors"
    assert g["306"]["inputs"]["strength_model"] == 1.0
    assert g["306"]["inputs"]["model"] == ["305", 0]
    assert g["305"]["inputs"]["strength_model"] == 0.65
    # Outfit crop-and-stitch graph: node 305's ORIGINAL sole consumer is node 237
    # (DifferentialDiffusion, the soft-edge-denoise wrapper) — NOT the KSampler (106)
    # directly, since 237 sits between the LoRA chain and the sampler. 306 is spliced
    # in there; 237 must now read node 306 instead of 305.
    assert g["237"]["class_type"] == "DifferentialDiffusion"
    assert g["237"]["inputs"]["model"] == ["306", 0]
    # Node 305 must have exactly ONE consumer (node 237, rewired to 306).
    consumers_of_305 = [
        f"{nid}.{k}"
        for nid, n in g.items()
        for k, v in n.get("inputs", {}).items()
        if v == ["305", 0]
    ]
    assert consumers_of_305 == ["306.model"]
    # End-to-end chain integrity: the KSampler (106) still reads node 237's output
    # (unchanged), so the skin LoRA transitively reaches the sampler:
    # 301 -> 304 -> 305 -> 306 -> 237 -> 106.
    assert g["106"]["class_type"] == "KSampler"
    assert g["106"]["inputs"]["model"] == ["237", 0]


def test_skinlora_graphs_leave_realism_lora_and_unet_untouched():
    # Node 304 (URP_20 realism LoRA @ 0.8) and node 301 (UNETLoader) are the SAME on
    # both skinlora graphs as their non-skinlora base — only 305's strength and the
    # new 306 splice changed.
    for name in (
        "pose_2511_skinlora_API.json",
        "outfit_cropstitch_2511full_skinlora_API.json",
    ):
        g = _load(name)
        assert g["304"]["inputs"]["lora_name"] == "URP_20.safetensors"
        assert g["304"]["inputs"]["strength_model"] == 0.8
        assert g["304"]["inputs"]["model"] == ["301", 0]
        assert g["301"]["class_type"] == "UNETLoader"
        assert g["301"]["inputs"]["unet_name"] == "qwen_image_edit_2511_fp8mixed.safetensors"


# ---------------------------------------------------------------------------
# All pose variants (skinlora, faceboost, and the skinlora+faceboost combo) inherit
# the CURRENT base graph's node 301 marker + node 200 baked ReActor values
# (codeformer_weight 0.7 / face_restore_visibility 0.65) — these were JUST updated
# on pose_2511_API.json by a separate, already-finished workstream, so the clones
# must carry the NEW values, not stale ones.
# ---------------------------------------------------------------------------
def test_pose_variants_keep_the_2511_template_marker():
    for name in _POSE_VARIANT_GRAPHS:
        g = _load(name)
        assert _is_pose_2511_template(g) is True, name
        assert g["301"]["class_type"] == "UNETLoader", name


def test_pose_variants_inherit_current_reactor_baked_values():
    for name in _POSE_VARIANT_GRAPHS:
        g = _load(name)
        r = g["200"]["inputs"]
        assert g["200"]["class_type"] == "ReActorFaceSwap", name
        assert r["codeformer_weight"] == 0.7, name
        assert r["face_restore_visibility"] == 0.65, name


# ---------------------------------------------------------------------------
# B: faceboost graph — node 215 (ReActorFaceBoost) wired into node 200
# ---------------------------------------------------------------------------
def test_faceboost_node_215_exists_with_expected_inputs():
    g = _load("pose_2511_faceboost_API.json")
    n = g["215"]
    assert n["class_type"] == "ReActorFaceBoost"
    i = n["inputs"]
    assert i["enabled"] is True
    assert i["boost_model"] == "GPEN-BFR-512.onnx"
    assert i["interpolation"] == "Bicubic"
    assert i["visibility"] == 1.0
    assert i["codeformer_weight"] == 0.5
    assert i["restore_with_main_after"] is False


def test_faceboost_node_200_face_boost_wired_to_215():
    g = _load("pose_2511_faceboost_API.json")
    assert g["200"]["inputs"]["face_boost"] == ["215", 0]
    # Everything else on node 200 is untouched vs. the base graph.
    r = g["200"]["inputs"]
    assert r["source_image"] == ["210", 0]
    assert r["input_image"] == ["8", 0]


def test_faceboost_graph_has_no_node_306_skin_lora_splice():
    # The faceboost graph is a SEPARATE variant off the same base as the skinlora
    # graph, not a combined graph — it must NOT carry the skin-LoRA chain.
    g = _load("pose_2511_faceboost_API.json")
    assert "306" not in g
    assert g["305"]["inputs"]["strength_model"] == 0.9  # base value, not softened
    assert g["3"]["inputs"]["model"] == ["305", 0]


# ---------------------------------------------------------------------------
# A+B combined: pose_2511_skinlora_faceboost_API.json = the skinlora graph (node
# 306 @ 1.0, node 305 softened to 0.65, sampler on ["306", 0]) PLUS node 215
# (ReActorFaceBoost, copied verbatim from the faceboost graph) wired into node
# 200's face_boost input — both halves present at once, neither clobbering the
# other.
# ---------------------------------------------------------------------------
def test_combined_graph_has_skinlora_half_wired_same_as_skinlora_graph():
    g = _load(_COMBINED_GRAPH)
    assert g["306"]["class_type"] == "LoraLoaderModelOnly"
    assert g["306"]["inputs"]["lora_name"] == "qwen-edit-skin.safetensors"
    assert g["306"]["inputs"]["strength_model"] == 1.0
    assert g["306"]["inputs"]["model"] == ["305", 0]
    assert g["305"]["inputs"]["strength_model"] == 0.65
    assert g["3"]["class_type"] == "KSampler"
    assert g["3"]["inputs"]["model"] == ["306", 0]
    # Node 305 must have exactly ONE consumer (node 306) — same invariant as the
    # standalone skinlora graph; the face-boost splice must not add a second reader.
    consumers_of_305 = [
        f"{nid}.{k}"
        for nid, n in g.items()
        for k, v in n.get("inputs", {}).items()
        if v == ["305", 0]
    ]
    assert consumers_of_305 == ["306.model"]


def test_combined_graph_has_faceboost_half_wired_same_as_faceboost_graph():
    g = _load(_COMBINED_GRAPH)
    n = g["215"]
    assert n["class_type"] == "ReActorFaceBoost"
    i = n["inputs"]
    assert i["enabled"] is True
    assert i["boost_model"] == "GPEN-BFR-512.onnx"
    assert i["interpolation"] == "Bicubic"
    assert i["visibility"] == 1.0
    assert i["codeformer_weight"] == 0.5
    assert i["restore_with_main_after"] is False
    assert g["200"]["inputs"]["face_boost"] == ["215", 0]
    # Everything else on node 200 is untouched vs. the skinlora base graph.
    r = g["200"]["inputs"]
    assert r["source_image"] == ["210", 0]
    assert r["input_image"] == ["8", 0]
    assert r["codeformer_weight"] == 0.7
    assert r["face_restore_visibility"] == 0.65


def test_combined_graph_leaves_realism_lora_and_unet_untouched():
    g = _load(_COMBINED_GRAPH)
    assert g["304"]["inputs"]["lora_name"] == "URP_20.safetensors"
    assert g["304"]["inputs"]["strength_model"] == 0.8
    assert g["304"]["inputs"]["model"] == ["301", 0]
    assert g["301"]["class_type"] == "UNETLoader"
    assert g["301"]["inputs"]["unet_name"] == "qwen_image_edit_2511_fp8mixed.safetensors"


def test_combined_graph_both_halves_coexist_without_clobbering():
    # Sanity check that combining the two variants didn't silently drop either
    # half: the skin-LoRA chain still reaches the sampler AND the face-boost node
    # still feeds node 200, at the same time, on the SAME graph.
    g = _load(_COMBINED_GRAPH)
    assert "306" in g and "215" in g
    assert g["3"]["inputs"]["model"] == ["306", 0]
    assert g["200"]["inputs"]["face_boost"] == ["215", 0]


# ---------------------------------------------------------------------------
# prepare_pose_workflow(face_restore_model=...)
# ---------------------------------------------------------------------------
def test_face_restore_model_written_when_truthy():
    for name in ("edit_pose_action.json", "pose_2511_API.json"):
        g = _load(name)
        wf = prepare_pose_workflow(
            g, "src.png", "ref.png", face_restore_model="GPEN-BFR-512.onnx"
        )
        assert wf["200"]["inputs"]["face_restore_model"] == "GPEN-BFR-512.onnx", name


def test_face_restore_model_none_leaves_node_200_untouched():
    for name in ("edit_pose_action.json", "pose_2511_API.json"):
        g = _load(name)
        baked = g["200"]["inputs"]["face_restore_model"]
        # Omitted entirely.
        wf = prepare_pose_workflow(g, "src.png", "ref.png")
        assert wf["200"]["inputs"]["face_restore_model"] == baked, name
        # Explicit None -> same no-op.
        wf_none = prepare_pose_workflow(
            g, "src.png", "ref.png", face_restore_model=None
        )
        assert wf_none["200"]["inputs"]["face_restore_model"] == baked, name


def test_face_restore_model_empty_string_is_a_noop():
    g = _load("pose_2511_API.json")
    baked = g["200"]["inputs"]["face_restore_model"]
    wf = prepare_pose_workflow(g, "src.png", "ref.png", face_restore_model="")
    assert wf["200"]["inputs"]["face_restore_model"] == baked


def test_face_restore_model_omitted_is_byte_identical_to_before_param_existed():
    g = _load("pose_2511_API.json")
    without = prepare_pose_workflow(g, "src.png", "ref.png", prompt="P", seed=1)
    with_none = prepare_pose_workflow(
        g, "src.png", "ref.png", prompt="P", seed=1, face_restore_model=None
    )
    assert json.dumps(without, sort_keys=True) == json.dumps(with_none, sort_keys=True)


def test_face_restore_model_missing_node_200_is_a_noop():
    # A synthetic template with no node 200 must not raise.
    template = {
        "93": {
            "inputs": {"megapixels": 1},
            "class_type": "ImageScaleToTotalPixels",
        }
    }
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png", face_restore_model="GPEN-BFR-512.onnx"
    )
    assert "200" not in wf


def test_face_restore_model_works_on_new_pose_variant_graphs():
    # Sanity: the new graphs are real, loadable prepare_pose_workflow inputs too.
    for name in _POSE_VARIANT_GRAPHS:
        g = _load(name)
        wf = prepare_pose_workflow(
            g, "src.png", "ref.png", face_restore_model="GPEN-BFR-512.onnx"
        )
        assert wf["200"]["inputs"]["face_restore_model"] == "GPEN-BFR-512.onnx", name


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
