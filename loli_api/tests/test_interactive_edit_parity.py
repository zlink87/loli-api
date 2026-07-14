"""
PARITY: the interactive single-edit endpoints must carry the SAME render-quality
improvements as the batch/pipeline path.

Covers:
  * Standalone pose worker (``PoseBackgroundWorker._build_edit_workflow``) threads the
    settings-driven knobs into ``prepare_pose_workflow`` — ReActor node-200 tuning
    (restore-visibility / codeformer-weight / face-restore-model), node-93 output
    megapixels, and the natural/candid LoRA stack (nodes 304/305/306) — exactly like
    ``pipeline_worker``'s pose branch, and gates the faceref "render that same face"
    clause on BOTH template capability AND a staged hero donor.
  * Outfit preparer (``prepare_outfit_workflow(lora_scales=...)``) writes strength_model
    only for LoRA nodes present on the loaded graph (2511/skinlora crop-stitch), and is a
    true no-op on the legacy V1 / plain crop-stitch graphs.

Fully offline — reads local workflow JSON only; no GPU / RunPod / network. Runs under
pytest or directly (``python loli_api/tests/test_interactive_edit_parity.py``); the
monkeypatch-based tests are skipped in direct mode.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import models.requests as _mr

# These tests exercise prompt/scale/threading logic, not the SSRF allowlist — mirror the
# existing pose/pipeline test stand-in so a bare source_image validates.
_mr.validate_source_image = lambda u: u  # type: ignore

from config import settings
from models.enums import PoseType, OutfitType, NudityLevel, PhotoStyleType
from models.requests import PoseEditRequest
from api.v1.endpoints.outfit import prepare_outfit_workflow
from workers.pose_worker import PoseBackgroundWorker

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"

_SKINLORA = "pose_2511_skinlora_API.json"
_FACEREF = "pose_2511_skinlora_faceref_API.json"
_RAPID = "edit_pose_action.json"

_OUTFIT_SKINLORA = "outfit_cropstitch_2511full_skinlora_API.json"   # LoRA 304/305/306
_OUTFIT_2511FULL = "outfit_cropstitch_2511full_API.json"            # LoRA 304/305 only
_OUTFIT_PLAIN = "outfit_cropstitch_API.json"                         # crop-stitch, no LoRA
_OUTFIT_LEGACY = "test_final_API.json"                               # V1 whole-frame, no LoRA

_FACE_CLAUSE = (
    "Her face, facial structure, and hairline are exactly those of the person "
    "in image 3; render that same face."
)


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _pose_worker(graph_name: str) -> PoseBackgroundWorker:
    w = PoseBackgroundWorker(
        job_manager=None, comfyui_client=None, storage_service=None,
        workflow_path=str(_WF_DIR / graph_name),
    )
    # Set the template directly (skip the async file-load; the path above is only for the
    # constructor's contract). This is the same dict _load_workflow would produce.
    w._workflow_template = _load(graph_name)
    return w


def _pose_req(**overrides) -> PoseEditRequest:
    base = dict(source_image="https://x.supabase.co/s.png", pose=PoseType.SITTING)
    base.update(overrides)
    return PoseEditRequest(**base)


# ===========================================================================
# Standalone pose worker — settings-driven ReActor / output-MP threading
# ===========================================================================
def test_pose_worker_threads_reactor_output_and_face_restore(monkeypatch):
    # The interactive pose edit must pick up the SAME server-wide ReActor / resolution /
    # face-restore settings the batch path does (they used to default to the -1.0/empty
    # sentinels regardless of the env).
    monkeypatch.setattr(settings, "POSE_REACTOR_RESTORE_VISIBILITY", 0.4)
    monkeypatch.setattr(settings, "POSE_REACTOR_CODEFORMER_WEIGHT", 0.9)
    monkeypatch.setattr(settings, "POSE_REACTOR_FACE_RESTORE_MODEL", "GPEN-BFR-512.onnx")
    monkeypatch.setattr(settings, "POSE_OUTPUT_MEGAPIXELS", 1.74)

    w = _pose_worker(_SKINLORA)
    _prompt, wf = w._build_edit_workflow(_pose_req(), "src.png", "ref.png", 7)

    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.4
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.9
    assert wf["200"]["inputs"]["face_restore_model"] == "GPEN-BFR-512.onnx"
    assert wf["93"]["inputs"]["megapixels"] == 1.74


def test_pose_worker_reactor_sentinels_leave_baked_values(monkeypatch):
    # Default sentinels (-1.0 / empty / 0.0) leave the graph's baked node-200 / node-93
    # values byte-identical — no accidental override on the interactive path.
    monkeypatch.setattr(settings, "POSE_REACTOR_RESTORE_VISIBILITY", -1.0)
    monkeypatch.setattr(settings, "POSE_REACTOR_CODEFORMER_WEIGHT", -1.0)
    monkeypatch.setattr(settings, "POSE_REACTOR_FACE_RESTORE_MODEL", "")
    monkeypatch.setattr(settings, "POSE_OUTPUT_MEGAPIXELS", 0.0)

    template = _load(_SKINLORA)
    baked_vis = template["200"]["inputs"]["face_restore_visibility"]
    baked_wt = template["200"]["inputs"]["codeformer_weight"]
    baked_model = template["200"]["inputs"]["face_restore_model"]
    baked_mp = template["93"]["inputs"]["megapixels"]

    w = _pose_worker(_SKINLORA)
    _prompt, wf = w._build_edit_workflow(_pose_req(), "src.png", "ref.png", 7)

    assert wf["200"]["inputs"]["face_restore_visibility"] == baked_vis
    assert wf["200"]["inputs"]["codeformer_weight"] == baked_wt
    assert wf["200"]["inputs"]["face_restore_model"] == baked_model
    assert wf["93"]["inputs"]["megapixels"] == baked_mp


# ===========================================================================
# Standalone pose worker — natural/candid LoRA scaling (nodes 304/305/306)
# ===========================================================================
def test_pose_worker_natural_style_scales_lora_stack():
    # A natural/candid style on the request dials the URP/NSFW/skin stack down — the same
    # parity the batch path gives. PoseEditRequest has no photoStyle field today, so a light
    # stand-in supplies it; _build_edit_workflow reads it via getattr(request, "photoStyle").
    req = SimpleNamespace(
        pose=PoseType.SITTING, identityAnchors=None, negativePrompt=None,
        photoStyle=PhotoStyleType.NATURAL,
    )
    w = _pose_worker(_SKINLORA)
    _prompt, wf = w._build_edit_workflow(req, "src.png", "ref.png", 7)

    assert wf["304"]["inputs"]["strength_model"] == settings.NATURAL_LORA_URP
    assert wf["305"]["inputs"]["strength_model"] == settings.NATURAL_LORA_NSFW
    assert wf["306"]["inputs"]["strength_model"] == settings.NATURAL_LORA_SKIN


def test_pose_worker_no_photostyle_leaves_lora_baked():
    # A real PoseEditRequest (no photoStyle) -> _natural_lora_scales(None) -> None -> the
    # baked LoRA strengths survive verbatim (polished-equivalent behavior).
    template = _load(_SKINLORA)
    baked = [template[n]["inputs"]["strength_model"] for n in ("304", "305", "306")]

    w = _pose_worker(_SKINLORA)
    _prompt, wf = w._build_edit_workflow(_pose_req(), "src.png", "ref.png", 7)

    assert [wf[n]["inputs"]["strength_model"] for n in ("304", "305", "306")] == baked


def test_pose_worker_lora_scaling_noop_on_rapid_graph():
    # The v1 Rapid pose graph carries none of nodes 304/305/306 — a natural style is a true
    # no-op there (never raises, never invents a node).
    req = SimpleNamespace(
        pose=PoseType.SITTING, identityAnchors=None, negativePrompt=None,
        photoStyle=PhotoStyleType.NATURAL,
    )
    w = _pose_worker(_RAPID)
    _prompt, wf = w._build_edit_workflow(req, "src.png", "ref.png", 7)
    assert not any(nid in wf for nid in ("304", "305", "306"))


# ===========================================================================
# Standalone pose worker — faceref both-conditions guard
# ===========================================================================
def test_pose_worker_faceref_clause_absent_without_staged_face():
    # GUARD: even on the faceref graph, the interactive path stages no dedicated hero donor
    # (face_ref_name None) -> no image3 to bind -> the "render that same face" clause is
    # ABSENT, and node 210 falls back to the source for the ReActor stamp only.
    w = _pose_worker(_FACEREF)
    prompt, wf = w._build_edit_workflow(_pose_req(), "src.png", "ref.png", 7, face_ref_name=None)
    assert _FACE_CLAUSE not in prompt
    assert wf["210"]["inputs"]["image"] == "src.png"


def test_pose_worker_faceref_clause_present_with_staged_face():
    # When a dedicated donor IS staged, the clause appears and node 210 is wired to it — the
    # guard's positive side (matches the pipeline's behavior).
    w = _pose_worker(_FACEREF)
    prompt, wf = w._build_edit_workflow(
        _pose_req(), "src.png", "ref.png", 7, face_ref_name="donor.png"
    )
    assert _FACE_CLAUSE in prompt
    assert wf["210"]["inputs"]["image"] == "donor.png"


def test_pose_worker_non_faceref_graph_never_adds_clause_even_with_donor():
    # A staged donor on a NON-faceref graph (no image3 encoder input) still yields no clause
    # — the template-capability half of the guard holds.
    w = _pose_worker(_SKINLORA)
    prompt, _wf = w._build_edit_workflow(
        _pose_req(), "src.png", "ref.png", 7, face_ref_name="donor.png"
    )
    assert _FACE_CLAUSE not in prompt


def test_pose_worker_negative_prompt_threaded_on_2511_graph():
    # D3 parity: the live 2511 negative is wired on the skinlora (2511) graph. Node 115 is a
    # real negative encoder there; the request's extra negative term must reach it.
    w = _pose_worker(_SKINLORA)
    _prompt, wf = w._build_edit_workflow(
        _pose_req(negativePrompt="extra_neg_marker"), "src.png", "ref.png", 7
    )
    assert "115" in wf
    assert "extra_neg_marker" in wf["115"]["inputs"]["prompt"]


# ===========================================================================
# Outfit preparer — lora_scales writes / no-op (task B)
# ===========================================================================
def test_outfit_prepare_writes_lora_scales_on_skinlora_cropstitch():
    g = _load(_OUTFIT_SKINLORA)
    wf = prepare_outfit_workflow(
        g, "s.png", "P", seed=1, lora_scales={"304": 0.6, "305": 0.5, "306": 0.7}
    )
    assert wf["304"]["inputs"]["strength_model"] == 0.6
    assert wf["305"]["inputs"]["strength_model"] == 0.5
    assert wf["306"]["inputs"]["strength_model"] == 0.7


def test_outfit_prepare_partial_dict_writes_present_nodes_only():
    # outfit_cropstitch_2511full (softlora) carries 304/305 but NOT 306 — a full dict writes
    # only the two present nodes and never invents 306.
    g = _load(_OUTFIT_2511FULL)
    assert "306" not in g
    wf = prepare_outfit_workflow(
        g, "s.png", "P", seed=1, lora_scales={"304": 0.6, "305": 0.5, "306": 0.7}
    )
    assert wf["304"]["inputs"]["strength_model"] == 0.6
    assert wf["305"]["inputs"]["strength_model"] == 0.5
    assert "306" not in wf


def test_outfit_prepare_none_leaves_baked_strengths():
    g = _load(_OUTFIT_SKINLORA)
    baked = [g[n]["inputs"]["strength_model"] for n in ("304", "305", "306")]
    wf = prepare_outfit_workflow(g, "s.png", "P", seed=1, lora_scales=None)
    assert [wf[n]["inputs"]["strength_model"] for n in ("304", "305", "306")] == baked


def test_outfit_prepare_lora_scales_noop_on_plain_cropstitch_and_legacy():
    # Plain crop-stitch (V2, no LoRA) and the legacy V1 whole-frame graph both carry none of
    # 304/305/306 — a scales dict is a true no-op (never raises, never invents a node).
    for name in (_OUTFIT_PLAIN, _OUTFIT_LEGACY):
        g = _load(name)
        wf = prepare_outfit_workflow(
            g, "s.png", "P", seed=1, lora_scales={"304": 0.6, "305": 0.5, "306": 0.7}
        )
        assert not any(nid in wf for nid in ("304", "305", "306")), name


def test_outfit_prepare_lora_omitted_is_byte_identical():
    # Backward compat: omitting the kwarg vs. passing None yields an identical workflow.
    g = _load(_OUTFIT_SKINLORA)
    without = prepare_outfit_workflow(g, "s.png", "P", seed=1)
    with_none = prepare_outfit_workflow(g, "s.png", "P", seed=1, lora_scales=None)
    assert json.dumps(without, sort_keys=True) == json.dumps(with_none, sort_keys=True)


def test_outfit_prepare_lora_scales_applies_natural_map_end_to_end():
    # The same _natural_lora_scales map that drives the pose graph drives the outfit graph
    # (identical node ids + LoRA files), so a natural style dials both down uniformly.
    from api.v1.endpoints.pose import _natural_lora_scales
    g = _load(_OUTFIT_SKINLORA)
    wf = prepare_outfit_workflow(g, "s.png", "P", seed=1, lora_scales=_natural_lora_scales("natural"))
    assert wf["304"]["inputs"]["strength_model"] == settings.NATURAL_LORA_URP
    assert wf["305"]["inputs"]["strength_model"] == settings.NATURAL_LORA_NSFW
    assert wf["306"]["inputs"]["strength_model"] == settings.NATURAL_LORA_SKIN


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        if fn.__code__.co_argcount != 0:  # skip monkeypatch tests in direct mode
            continue
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\ndone ({failures} failures; monkeypatch tests skipped in direct mode)")
    sys.exit(1 if failures else 0)
