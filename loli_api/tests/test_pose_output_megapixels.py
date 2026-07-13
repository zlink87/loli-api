"""
Pose output-resolution knob: prepare_pose_workflow(output_megapixels=…) writes node
93 (ImageScaleToTotalPixels.megapixels) so the single-pass batch path can render the
full re-diffusion at a higher resolution.

Covers (both real pose graphs):
  * a value > 0 overrides node 93's megapixels on v1 AND the 2511 tier;
  * None (default) and 0.0 leave node 93 byte-identical to the template;
  * a template missing node 93 degrades to a no-op instead of crashing.

Kept in its OWN file (not test_pose_2511_workflow.py) to avoid colliding with the
concurrent node-200 baked-value edits there. Fully offline — reads local JSON only.

Runs under pytest or directly: python loli_api/tests/test_pose_output_megapixels.py
"""
import json
from pathlib import Path

from api.v1.endpoints.pose import prepare_pose_workflow

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"
_POSE_GRAPHS = ("edit_pose_action.json", "pose_2511_API.json")


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def test_output_megapixels_written_on_both_pose_graphs():
    for name in _POSE_GRAPHS:
        g = _load(name)
        assert "93" in g and g["93"]["class_type"] == "ImageScaleToTotalPixels", name
        wf = prepare_pose_workflow(g, "src.png", "ref.png", output_megapixels=1.74)
        assert wf["93"]["inputs"]["megapixels"] == 1.74, name


def test_output_megapixels_none_leaves_node_93_untouched():
    for name in _POSE_GRAPHS:
        g = _load(name)
        baked = g["93"]["inputs"]["megapixels"]
        # Omitted entirely.
        wf = prepare_pose_workflow(g, "src.png", "ref.png")
        assert wf["93"]["inputs"]["megapixels"] == baked, name
        # Explicit None -> same no-op.
        wf_none = prepare_pose_workflow(g, "src.png", "ref.png", output_megapixels=None)
        assert wf_none["93"]["inputs"]["megapixels"] == baked, name


def test_output_megapixels_zero_is_a_noop_not_a_zero_write():
    # 0.0 means "keep the baked size" (it's the settings default sentinel), NOT
    # "scale to zero megapixels" — so node 93 must stay untouched.
    for name in _POSE_GRAPHS:
        g = _load(name)
        baked = g["93"]["inputs"]["megapixels"]
        wf = prepare_pose_workflow(g, "src.png", "ref.png", output_megapixels=0.0)
        assert wf["93"]["inputs"]["megapixels"] == baked, name


def test_output_megapixels_missing_node_93_is_a_noop():
    # A synthetic template with no node 93 must not raise.
    template = {
        "200": {
            "inputs": {"face_restore_visibility": 0.65, "codeformer_weight": 0.7},
            "class_type": "ReActorFaceSwap",
        }
    }
    wf = prepare_pose_workflow(template, "src.png", "ref.png", output_megapixels=1.74)
    assert "93" not in wf


def test_output_megapixels_coerced_to_float():
    g = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(g, "src.png", "ref.png", output_megapixels=2)  # int in
    assert wf["93"]["inputs"]["megapixels"] == 2.0
    assert isinstance(wf["93"]["inputs"]["megapixels"], float)


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
