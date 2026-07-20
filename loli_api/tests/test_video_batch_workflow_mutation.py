"""
Tests for the WAN 2.2 Lightning i2v workflow mutation (services/video_workflow.py),
exercised against the REAL loli_api/workflows/wan_i2v_lightning.json template.

Covers:
  * anchor writes (source image / positive / negative / dims / both-expert seed / fps);
  * the runtime preset-LoRA insertion contract (A4(d)) for 0 / 1 / 2 LoRAs on the
    high chain, and the H+L low-chain insertion when strength_low > 0;
  * the shared template is never mutated across calls (deep-copy discipline);
  * the interpolate toggle (multiplier 1 vs 2, frame_rate scaling);
  * select_video_template routing (fast -> lightning, max -> baseline, explicit
    forces lightning even for max, fast degrades to baseline when lightning is None).

Runs under pytest or directly: python loli_api/tests/test_video_batch_workflow_mutation.py
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from services.video_workflow import (
    prepare_lightning_video_workflow,
    prepare_video_workflow,
    select_video_template,
)

# loli_api/tests/ -> loli_api/workflows/wan_i2v_lightning.json (resolved off this
# file so the test is CWD-independent).
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "workflows" / "wan_i2v_lightning.json"


def _template() -> dict:
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_frame_interpolate(wf: dict) -> dict:
    for node in wf.values():
        if node.get("class_type") == "FrameInterpolate":
            return node
    raise AssertionError("no FrameInterpolate node found in workflow")


def _lora_obj(name, high, low):
    """A synthetic LoraRef-shaped object (duck-typed on name/strength_*)."""
    return SimpleNamespace(name=name, strength_high=high, strength_low=low)


# ---------------------------------------------------------------------------
# Anchor writes
# ---------------------------------------------------------------------------
def test_anchor_writes():
    wf = prepare_lightning_video_workflow(
        _template(),
        "still_source.png",
        prompt="a slow wink. keep identity.",
        negative_prompt="blurry, warping",
        seed=4242,
        width=720,
        height=1280,
        length=49,
        fps=16,
        loras=None,
        interpolate=False,  # multiplier 1 -> frame_rate stays == fps
    )
    assert wf["52"]["inputs"]["image"] == "still_source.png"      # start frame
    assert wf["6"]["inputs"]["text"] == "a slow wink. keep identity."  # positive
    assert wf["7"]["inputs"]["text"] == "blurry, warping"         # negative
    assert wf["50"]["inputs"]["width"] == 720
    assert wf["50"]["inputs"]["height"] == 1280
    assert wf["50"]["inputs"]["length"] == 49
    # Seed written on BOTH experts (high 57 + low 58) for reproducibility.
    assert wf["57"]["inputs"]["noise_seed"] == 4242
    assert wf["58"]["inputs"]["noise_seed"] == 4242
    # fps on the VideoImagesBridge (node 60); multiplier 1 -> unscaled.
    assert wf["60"]["inputs"]["frame_rate"] == 16


# ---------------------------------------------------------------------------
# Runtime preset-LoRA insertion (A4(d))
# ---------------------------------------------------------------------------
def test_zero_loras_leaves_high_chain_byte_identical():
    wf = prepare_lightning_video_workflow(
        _template(), "s.png", prompt="p", negative_prompt="n", loras=[]
    )
    # No preset-LoRA nodes inserted; node 54 still reads straight from node 37.
    assert wf["54"]["inputs"]["model"] == ["37", 0]
    assert "82" not in wf
    assert "83" not in wf
    # Low chain untouched too (Lightning LoRA at 81 -> 55).
    assert wf["55"]["inputs"]["model"] == ["81", 0]
    assert "84" not in wf


def test_one_lora_low_zero_inserts_high_only():
    lora = {"name": "nsfw/enhancer.safetensors", "strength_high": 0.7, "strength_low": 0.0}
    wf = prepare_lightning_video_workflow(
        _template(), "s.png", prompt="p", negative_prompt="n", loras=[lora]
    )
    # High chain: 37 -> 82 -> 54.
    assert "82" in wf
    assert wf["82"]["inputs"]["model"] == ["37", 0]
    assert wf["82"]["inputs"]["lora_name"] == "nsfw/enhancer.safetensors"
    assert wf["82"]["inputs"]["strength_model"] == 0.7
    assert wf["82"]["class_type"] == "LoraLoaderModelOnly"
    assert wf["54"]["inputs"]["model"] == ["82", 0]
    assert "83" not in wf
    # strength_low == 0 -> NO low-chain insertion; low side stays 81 -> 55.
    assert "84" not in wf
    assert wf["55"]["inputs"]["model"] == ["81", 0]


def test_two_loras_chain_high_side_37_82_83_54():
    loras = [
        {"name": "A.safetensors", "strength_high": 0.6, "strength_low": 0.0},
        {"name": "B.safetensors", "strength_high": 0.5, "strength_low": 0.0},
    ]
    wf = prepare_lightning_video_workflow(
        _template(), "s.png", prompt="p", negative_prompt="n", loras=loras
    )
    # Chain 37 -> 82 -> 83 -> 54.
    assert wf["82"]["inputs"]["model"] == ["37", 0]
    assert wf["82"]["inputs"]["lora_name"] == "A.safetensors"
    assert wf["83"]["inputs"]["model"] == ["82", 0]
    assert wf["83"]["inputs"]["lora_name"] == "B.safetensors"
    assert wf["54"]["inputs"]["model"] == ["83", 0]
    # Neither carried a low strength -> low chain untouched.
    assert "84" not in wf
    assert wf["55"]["inputs"]["model"] == ["81", 0]


def test_lora_with_low_strength_also_inserts_low_side():
    # Accepts a LoraRef-shaped OBJECT too (duck-typed), not only a dict.
    lora = _lora_obj("HL.safetensors", 0.7, 0.4)
    wf = prepare_lightning_video_workflow(
        _template(), "s.png", prompt="p", negative_prompt="n", loras=[lora]
    )
    # High side: 37 -> 82 -> 54 at strength_high.
    assert wf["82"]["inputs"]["model"] == ["37", 0]
    assert wf["82"]["inputs"]["strength_model"] == 0.7
    assert wf["54"]["inputs"]["model"] == ["82", 0]
    # Low side: 81 -> 84 -> 55 at strength_low.
    assert "84" in wf
    assert wf["84"]["inputs"]["model"] == ["81", 0]
    assert wf["84"]["inputs"]["lora_name"] == "HL.safetensors"
    assert wf["84"]["inputs"]["strength_model"] == 0.4
    assert wf["84"]["class_type"] == "LoraLoaderModelOnly"
    assert wf["55"]["inputs"]["model"] == ["84", 0]


def test_template_deep_copy_not_mutated_across_calls():
    template = _template()
    snapshot = copy.deepcopy(template)

    prepare_lightning_video_workflow(
        template, "s.png", prompt="p", negative_prompt="n",
        seed=1, width=576, height=1024, length=81, fps=16,
        loras=[{"name": "X.safetensors", "strength_high": 0.6, "strength_low": 0.5}],
        interpolate=True,
    )
    prepare_video_workflow(template, "s2.png", prompt="q", seed=9)

    assert template == snapshot, "the shared template dict was mutated by a prepare call"


# ---------------------------------------------------------------------------
# Interpolate toggle
# ---------------------------------------------------------------------------
def test_interpolate_false_multiplier_1_framerate_unscaled():
    wf = prepare_lightning_video_workflow(
        _template(), "s.png", prompt="p", negative_prompt="n", fps=16, interpolate=False
    )
    assert _find_frame_interpolate(wf)["inputs"]["multiplier"] == 1
    assert wf["60"]["inputs"]["frame_rate"] == 16  # 16 * 1


def test_interpolate_true_multiplier_2_framerate_doubled():
    wf = prepare_lightning_video_workflow(
        _template(), "s.png", prompt="p", negative_prompt="n", fps=16, interpolate=True
    )
    assert _find_frame_interpolate(wf)["inputs"]["multiplier"] == 2
    assert wf["60"]["inputs"]["frame_rate"] == 32  # 16 * 2 -> real-time playback


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------
def test_select_template_fast_returns_lightning():
    L, B = {"kind": "lightning"}, {"kind": "baseline"}
    template, mode = select_video_template("fast", None, lightning=L, baseline=B)
    assert template is L
    assert mode == "fast"


def test_select_template_max_returns_baseline():
    L, B = {"kind": "lightning"}, {"kind": "baseline"}
    template, mode = select_video_template("max", None, lightning=L, baseline=B)
    assert template is B
    assert mode == "max"


def test_select_template_explicit_forces_lightning_even_for_max():
    L, B = {"kind": "lightning"}, {"kind": "baseline"}
    template, mode = select_video_template("max", "explicit", lightning=L, baseline=B)
    assert template is L
    assert mode == "fast"


def test_select_template_fast_degrades_to_baseline_when_lightning_missing():
    B = {"kind": "baseline"}
    template, mode = select_video_template("fast", None, lightning=None, baseline=B)
    assert template is B
    assert mode == "max"


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
