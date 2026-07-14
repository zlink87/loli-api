"""CFG experiment knob + anatomy-LoRA injection slot (07-14).

Covers the two render knobs added alongside the turbo-finish work:
  * cfg_scale — overrides node 3's cfg on the 2511 tier ONLY (the distilled v1
    Rapid graph samples at cfg 1 by design and must never be overridden);
  * anatomy_lora_name/strength — splices LoraLoaderModelOnly node 307 after the
    skin LoRA (306) and repoints every ["306", 0] consumer to ["307", 0].
    Injection (not baking) keeps graphs valid while the LoRA file is unstaged;
    the batch path passes a name only for explicit-tier items (pubicHair gate).
"""
import copy
import json
import sys
from pathlib import Path

_LOLI_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_DIR))

from api.v1.endpoints.pose import prepare_pose_workflow  # noqa: E402

_WF_DIR = _LOLI_DIR / "workflows"


def _load(name: str) -> dict:
    return json.loads((_WF_DIR / name).read_text())


def _prep(template: dict, **kwargs) -> dict:
    return prepare_pose_workflow(
        copy.deepcopy(template), "src.png", "ref.png", **kwargs
    )


def test_cfg_override_writes_node_3_on_2511_tier():
    wf = _prep(_load("pose_2511_skinlora_API.json"), cfg_scale=2.1)
    assert wf["3"]["inputs"]["cfg"] == 2.1


def test_cfg_sentinel_and_none_leave_baked_cfg():
    template = _load("pose_2511_skinlora_API.json")
    baked = template["3"]["inputs"]["cfg"]
    assert _prep(template, cfg_scale=None)["3"]["inputs"]["cfg"] == baked
    assert _prep(template, cfg_scale=-1.0)["3"]["inputs"]["cfg"] == baked


def test_cfg_override_never_touches_v1_rapid_graph():
    template = _load("edit_pose_action.json")
    baked = template["3"]["inputs"]["cfg"]
    wf = _prep(template, cfg_scale=2.1)
    assert wf["3"]["inputs"]["cfg"] == baked  # cfg 1 by design, distilled


def test_anatomy_lora_injected_and_chain_repointed():
    wf = _prep(
        _load("pose_2511_skinlora_API.json"),
        anatomy_lora_name="anatomy-test.safetensors",
        anatomy_lora_strength=0.75,
    )
    assert wf["307"]["class_type"] == "LoraLoaderModelOnly"
    assert wf["307"]["inputs"]["lora_name"] == "anatomy-test.safetensors"
    assert wf["307"]["inputs"]["strength_model"] == 0.75
    assert wf["307"]["inputs"]["model"] == ["306", 0]
    # Every prior consumer of the skin LoRA output now reads 307 (the sampler).
    assert wf["3"]["inputs"]["model"] == ["307", 0]
    # No other node still consumes ["306", 0] except the injected 307 itself.
    consumers = [
        nid
        for nid, node in wf.items()
        if nid != "307"
        and isinstance(node.get("inputs"), dict)
        and any(v == ["306", 0] for v in node["inputs"].values())
    ]
    assert consumers == []


def test_anatomy_lora_absent_without_name():
    wf = _prep(_load("pose_2511_skinlora_API.json"), anatomy_lora_name=None)
    assert "307" not in wf
    assert wf["3"]["inputs"]["model"] == ["306", 0]


def test_anatomy_lora_noop_on_graph_without_skin_lora():
    template = _load("edit_pose_action.json")  # no 306 stack
    wf = _prep(template, anatomy_lora_name="anatomy-test.safetensors")
    assert "307" not in wf


def test_anatomy_lora_composes_with_style_scales_and_turbofinish():
    wf = _prep(
        _load("pose_2511_skinlora_faceref_turbofinish_API.json"),
        anatomy_lora_name="anatomy-test.safetensors",
        anatomy_lora_strength=0.8,
        lora_scales={"304": 0.6, "305": 0.5, "306": 0.7},
        cfg_scale=2.2,
    )
    assert wf["304"]["inputs"]["strength_model"] == 0.6
    assert wf["306"]["inputs"]["strength_model"] == 0.7
    assert wf["307"]["inputs"]["lora_name"] == "anatomy-test.safetensors"
    assert wf["3"]["inputs"]["model"] == ["307", 0]
    assert wf["3"]["inputs"]["cfg"] == 2.2
    # Turbo chain untouched by the splice (its model input is the turbo UNet).
    assert wf["409"]["inputs"]["model"] == ["401", 0]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"OK   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if failures else 0)
