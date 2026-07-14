"""
Tests for WS4.1 (pose-step pre-ReActor instrumentation) and WS4.2 (ReActor
tuning knobs) plumbing:

  g1  prepare_pose_workflow(debug_save_pre_reactor=True) injects node "300"
      (SaveImage, images=["8",0], filename_prefix="pose_preface") reading the
      PRE-ReActor VAEDecode frame; False (default) injects nothing; a
      template missing node "8" degrades to a no-op instead of crashing.
  g2  prepare_pose_workflow's ReActor overrides (reactor_restore_visibility /
      reactor_codeformer_weight) write node 200's face_restore_visibility /
      codeformer_weight ONLY when >= 0 (0.0 is a valid override, distinct
      from the -1.0 "no override" sentinel); a template missing node "200"
      degrades to a no-op instead of crashing.
  g2b faceboost mirror: on graphs where node 215 (ReActorFaceBoost) OWNS the
      restore (enabled=True, restore_with_main_after=False — the shipped
      faceboost graphs), upstream skips node 200's main restore
      ("if self.restore or not self.face_boost_enabled"), so the same three
      dials MUST also land on node 215 (boost_model/visibility/
      codeformer_weight) or they are inert — the 07-14 "dials do nothing"
      root cause. Boost disabled / main-after=True -> node 215 untouched;
      graphs without node 215 behave exactly as before.
  g3  _select_primary_output (workers.pipeline_worker) picks the
      "pose_edit"-prefixed entry over "pose_preface" regardless of list
      order, falls back to outputs[0] when nothing matches the prefix, and
      returns None (not a crash) on an empty list. Fixtures mirror the exact
      shape RunPodServerlessClient.parse_output returns (filename/type/url/
      data/kind/content_type).
  g4  Back-compat guard: calling prepare_pose_workflow with the new WS4
      params left at their defaults (or omitted entirely) is byte-identical
      to the pre-WS4 behavior — no node 300, node 200 untouched vs. the
      template's baked 0.65 restore-visibility / 0.7 codeformer-weight.

Loads the REAL edit_pose_action.json from loli_api/workflows/ for the
injection tests (mirrors tests/test_identity_workflows.py and
tests/test_outfit_strength.py).

Runs under pytest or directly: python tests/test_pose_debug.py
"""
import json
from pathlib import Path

from api.v1.endpoints.pose import prepare_pose_workflow
from workers.pipeline_worker import _select_primary_output

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# g1 — WS4.1 debug SaveImage (node 300) injection
# ---------------------------------------------------------------------------
def test_debug_flag_injects_node_300_reading_pre_reactor_frame():
    template = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png", debug_save_pre_reactor=True,
    )
    assert wf["300"]["class_type"] == "SaveImage"
    assert wf["300"]["inputs"]["images"] == ["8", 0]
    assert wf["300"]["inputs"]["filename_prefix"] == "pose_preface"
    # The real post-ReActor save (node 164) is untouched.
    assert wf["164"]["class_type"] == "SaveImage"
    assert wf["164"]["inputs"]["images"] == ["200", 0]
    assert wf["164"]["inputs"]["filename_prefix"] == "pose_edit"


def test_debug_flag_false_injects_nothing():
    template = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png", debug_save_pre_reactor=False,
    )
    assert "300" not in wf
    assert set(wf.keys()) == set(template.keys())


def test_debug_flag_default_injects_nothing():
    # Same as above but relying on the parameter's default (not passed at all).
    template = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(template, "src.png", "ref.png")
    assert "300" not in wf


def test_debug_flag_missing_node_8_does_not_crash():
    # Synthetic template with no node "8" (e.g. an unexpected/future graph
    # shape) — the injection must guard on "8" in wf and degrade to a no-op
    # rather than raising.
    template = {
        "200": {
            "inputs": {"face_restore_visibility": 0.8, "codeformer_weight": 0.25},
            "class_type": "ReActorFaceSwap",
        }
    }
    wf = prepare_pose_workflow(template, "src.png", "ref.png", debug_save_pre_reactor=True)
    assert "300" not in wf
    assert "8" not in wf


def test_debug_flag_empty_template_does_not_crash():
    wf = prepare_pose_workflow({}, "src.png", "ref.png", debug_save_pre_reactor=True)
    assert wf == {}


# ---------------------------------------------------------------------------
# g2 — WS4.2 ReActor tuning knobs (node 200)
# ---------------------------------------------------------------------------
def test_reactor_overrides_applied_when_gte_zero():
    template = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=0.6, reactor_codeformer_weight=0.5,
    )
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.6
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.5


def test_reactor_overrides_zero_is_a_valid_override_not_the_sentinel():
    template = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=0.0, reactor_codeformer_weight=0.0,
    )
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.0
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.0


def test_reactor_overrides_negative_sentinel_leaves_template_untouched():
    template = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=-1.0, reactor_codeformer_weight=-1.0,
    )
    # Baked values (the graph now bakes 0.65 / 0.7 after the ReActor-dial semantics fix).
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.65
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.7


def test_reactor_overrides_are_independent_of_each_other():
    template = _load("edit_pose_action.json")

    visibility_only = prepare_pose_workflow(
        template, "src.png", "ref.png", reactor_restore_visibility=1.0,
    )
    assert visibility_only["200"]["inputs"]["face_restore_visibility"] == 1.0
    assert visibility_only["200"]["inputs"]["codeformer_weight"] == 0.7  # untouched (baked)

    weight_only = prepare_pose_workflow(
        template, "src.png", "ref.png", reactor_codeformer_weight=0.5,
    )
    assert weight_only["200"]["inputs"]["face_restore_visibility"] == 0.65  # untouched (baked)
    assert weight_only["200"]["inputs"]["codeformer_weight"] == 0.5


def test_reactor_overrides_guard_when_node_200_absent():
    template = {"8": {"inputs": {"samples": ["3", 0], "vae": ["163", 2]}, "class_type": "VAEDecode"}}
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=0.6, reactor_codeformer_weight=0.5,
    )
    assert "200" not in wf


def test_debug_and_reactor_overrides_combine():
    template = _load("edit_pose_action.json")
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        debug_save_pre_reactor=True,
        reactor_restore_visibility=1.0, reactor_codeformer_weight=0.5,
    )
    assert wf["300"]["inputs"]["images"] == ["8", 0]
    assert wf["200"]["inputs"]["face_restore_visibility"] == 1.0
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.5


# ---------------------------------------------------------------------------
# g2b — faceboost mirror (node 215). When the boost stage OWNS the restore
# (enabled=True, restore_with_main_after=False), upstream ReActor skips node
# 200's main restore ("if self.restore or not self.face_boost_enabled"), so
# the WS4.2 dials must ALSO be written to node 215 — otherwise they are inert,
# which is exactly what happened on the live faceboost graph (07-14).
# ---------------------------------------------------------------------------
# The LIVE production batch pose graph — ships node 215 enabled + main-after=False.
_FACEBOOST_TEMPLATE = "pose_2511_skinlora_faceboost_API.json"


def test_faceboost_mirror_writes_both_node_200_and_node_215():
    template = _load(_FACEBOOST_TEMPLATE)
    # Sanity: the real graph ships the boost owning the restore (the exact
    # config under which node 200's restore is skipped upstream).
    assert template["215"]["class_type"] == "ReActorFaceBoost"
    assert template["215"]["inputs"]["enabled"] is True
    assert template["215"]["inputs"]["restore_with_main_after"] is False

    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=0.7, reactor_codeformer_weight=0.4,
        face_restore_model="codeformer-v0.1.0.pth",
    )
    # Node 200 keeps the existing writes — dead-but-harmless while the boost
    # owns the restore, live again if ops flips restore_with_main_after.
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.7
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.4
    assert wf["200"]["inputs"]["face_restore_model"] == "codeformer-v0.1.0.pth"
    # Node 215 — the inputs the runtime actually reads in this config —
    # mirrors all three dials onto the boost's own input names.
    assert wf["215"]["inputs"]["visibility"] == 0.7
    assert wf["215"]["inputs"]["codeformer_weight"] == 0.4
    assert wf["215"]["inputs"]["boost_model"] == "codeformer-v0.1.0.pth"
    # Non-dial boost inputs untouched.
    assert wf["215"]["inputs"]["enabled"] is True
    assert wf["215"]["inputs"]["restore_with_main_after"] is False
    assert wf["215"]["inputs"]["interpolation"] == "Bicubic"


def test_faceboost_mirror_skipped_when_main_restore_runs_after():
    # restore_with_main_after=True -> self.restore is truthy upstream -> node
    # 200's main restore DOES run -> its dials are live and the boost's
    # restore inputs must stay exactly as baked.
    template = _load(_FACEBOOST_TEMPLATE)
    template["215"]["inputs"]["restore_with_main_after"] = True
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=0.7, reactor_codeformer_weight=0.4,
        face_restore_model="codeformer-v0.1.0.pth",
    )
    assert wf["215"]["inputs"] == template["215"]["inputs"]  # untouched
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.7  # node 200 as before


def test_faceboost_mirror_skipped_when_boost_disabled():
    # enabled=False -> "not self.face_boost_enabled" -> main restore runs and
    # the boost stage is inert; writing it would be dead config churn.
    template = _load(_FACEBOOST_TEMPLATE)
    template["215"]["inputs"]["enabled"] = False
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=0.7, reactor_codeformer_weight=0.4,
        face_restore_model="codeformer-v0.1.0.pth",
    )
    assert wf["215"]["inputs"] == template["215"]["inputs"]  # untouched
    assert wf["200"]["inputs"]["face_restore_model"] == "codeformer-v0.1.0.pth"


def test_faceboost_mirror_noop_on_graphs_without_node_215():
    # Existing graphs (no boost stage): behavior byte-identical to before the
    # mirror existed — no node 215 materialized, node 200 written as always.
    template = _load("edit_pose_action.json")
    assert "215" not in template
    wf = prepare_pose_workflow(
        template, "src.png", "ref.png",
        reactor_restore_visibility=0.7, reactor_codeformer_weight=0.4,
        face_restore_model="codeformer-v0.1.0.pth",
    )
    assert "215" not in wf
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.7
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.4
    assert wf["200"]["inputs"]["face_restore_model"] == "codeformer-v0.1.0.pth"


def test_faceboost_mirror_defaults_leave_node_215_untouched():
    # Sentinels (-1.0 / -1.0 / None) mean "no override" on the boost node too:
    # the live faceboost template's baked 215 survives byte-identical.
    template = _load(_FACEBOOST_TEMPLATE)
    wf = prepare_pose_workflow(template, "src.png", "ref.png")
    assert wf["215"] == template["215"]


# ---------------------------------------------------------------------------
# g3 — _select_primary_output (pipeline_worker), fixtures matching the real
# RunPodServerlessClient.parse_output shape:
#   {"filename", "type", "url"|None, "data"|None, "kind", "content_type"}
# ---------------------------------------------------------------------------
def _output_entry(filename, url=None, data=None):
    return {
        "filename": filename,
        "type": "s3_url" if url else "base64",
        "url": url,
        "data": data,
        "kind": "image",
        "content_type": "image/png",
    }


def test_select_primary_output_picks_pose_edit_regardless_of_order():
    pose_edit = _output_entry("pose_edit_00001_.png", url="https://example.com/pose_edit.png")
    pose_preface = _output_entry("pose_preface_00001_.png", url="https://example.com/pose_preface.png")

    # RunPod does not guarantee output list ordering — must work both ways.
    assert _select_primary_output([pose_edit, pose_preface]) is pose_edit
    assert _select_primary_output([pose_preface, pose_edit]) is pose_edit


def test_select_primary_output_falls_back_to_first_when_nothing_matches():
    a = _output_entry("edit_out_00001_.png", url="https://example.com/a.png")
    b = _output_entry("edit_out_00002_.png", url="https://example.com/b.png")
    # Neither entry starts with the default "pose_edit" prefix (outfit/background
    # steps use "edit_out") -> falls back to the first entry, same as legacy
    # outputs[0] behavior.
    assert _select_primary_output([a, b]) is a


def test_select_primary_output_single_entry_no_debug_flag():
    only = _output_entry("pose_edit_00001_.png", data="ZmFrZQ==")
    assert _select_primary_output([only]) is only


def test_select_primary_output_empty_list_returns_none_not_a_crash():
    assert _select_primary_output([]) is None


def test_select_primary_output_respects_custom_prefix():
    a = _output_entry("edit_out_00001_.png")
    b = _output_entry("other_00001_.png")
    assert _select_primary_output([a, b], primary_prefix="other") is b


# ---------------------------------------------------------------------------
# g4 — back-compat: WS4 params at defaults are byte-identical to pre-WS4
# ---------------------------------------------------------------------------
def test_defaults_are_byte_identical_to_pre_ws4_behavior():
    template = _load("edit_pose_action.json")

    wf = prepare_pose_workflow(template, "src.png", "ref.png", prompt="hello", seed=42)

    # No debug node, no new keys at all vs. the template.
    assert "300" not in wf
    assert set(wf.keys()) == set(template.keys())
    # Node 200 (ReActor) completely untouched vs. the template's baked values (the graph
    # now bakes 0.65 / 0.7 after the ReActor-dial semantics fix).
    assert wf["200"]["inputs"]["face_restore_visibility"] == 0.65
    assert wf["200"]["inputs"]["codeformer_weight"] == 0.7
    assert wf["200"] == template["200"]

    # Explicitly passing the new params AT their defaults must produce the
    # EXACT same serialized workflow as omitting them — proves the defaults
    # are true no-ops, not merely coincidentally equal.
    wf_explicit_defaults = prepare_pose_workflow(
        template, "src.png", "ref.png", prompt="hello", seed=42,
        debug_save_pre_reactor=False,
        reactor_restore_visibility=-1.0,
        reactor_codeformer_weight=-1.0,
    )
    assert json.dumps(wf, sort_keys=True) == json.dumps(wf_explicit_defaults, sort_keys=True)


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
