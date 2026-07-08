"""
Tests for the edit-pipeline photo-style clause: the pure helper in
prompt_constants and its wiring through PipelineBackgroundWorker's
_build_step_workflow (which serves both interactive /v1/edit and batches).

Runs under pytest or directly: python loli_api/tests/test_photo_style.py
"""
import asyncio
from pathlib import Path

import models.requests as _mr

# The mapper builds a PipelineEditRequest whose source_image is SSRF-validated.
# These tests exercise prompt wiring, not the allowlist.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import PoseType, OutfitType, PhotoStyleType
from models.requests import PipelineEditRequest
from services.prompt_constants import (
    EDIT_PHOTO_STYLE_SUFFIXES,
    PHOTO_STYLE_TEMPLATES,
    apply_edit_photo_style,
)
from workers.pipeline_worker import PipelineBackgroundWorker

_LOLI_API_DIR = Path(__file__).resolve().parent.parent
_POSE_WF = str(_LOLI_API_DIR / "workflows" / "edit_pose_action.json")
_OUTFIT_WF = str(_LOLI_API_DIR / "workflows" / "test_final_API.json")


# --- pure helper -----------------------------------------------------------

def test_suffix_keys_match_photo_style_enum():
    # Every selectable style must have an (possibly empty) edit clause, and the
    # keys must stay aligned with the generation-side templates.
    values = {s.value for s in PhotoStyleType}
    assert set(EDIT_PHOTO_STYLE_SUFFIXES) == values
    assert set(PHOTO_STYLE_TEMPLATES) == values


def test_apply_none_and_unknown_are_noops():
    assert apply_edit_photo_style("Change the outfit", None) == "Change the outfit"
    assert apply_edit_photo_style("Change the outfit", "nope") == "Change the outfit"


def test_apply_candid_phone_is_legacy_noop():
    prompt = "Change the person's clothing to: red evening gown"
    assert apply_edit_photo_style(prompt, PhotoStyleType.CANDID_PHONE) == prompt
    assert apply_edit_photo_style(prompt, "candid_phone") == prompt


def test_apply_polished_appends_clause():
    prompt = "Change the person's clothing to: red evening gown"
    out = apply_edit_photo_style(prompt, PhotoStyleType.POLISHED)
    assert out.startswith(prompt)
    assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] in out
    # sentence-terminated join
    assert f"{prompt}. " in out


def test_suffixes_never_touch_identity():
    for suffix in EDIT_PHOTO_STYLE_SUFFIXES.values():
        for banned in ("face", "hair", "eye", "identity", "features"):
            assert banned not in suffix.lower(), f"'{banned}' in style clause: {suffix}"


# --- worker wiring ---------------------------------------------------------

def _worker():
    w = PipelineBackgroundWorker(
        job_manager=None,
        comfyui_client=None,
        storage_service=None,
        pose_workflow_path=_POSE_WF,
        outfit_workflow_path=_OUTFIT_WF,
    )
    asyncio.run(w._load_workflows())
    return w


def _request(**kw):
    base = dict(
        source_image="https://x.supabase.co/img.png",
        pose=PoseType.SITTING,
        outfit=OutfitType.BIKINI,
        prompt="on a beach at sunset",
    )
    base.update(kw)
    return PipelineEditRequest(**base)


def _positive_prompt(workflow: dict, step: str) -> str:
    if step == "pose":
        return workflow["114"]["inputs"]["prompt"]
    return workflow["16"]["inputs"]["positive"]


def test_build_step_workflow_wraps_all_steps_when_polished():
    w = _worker()
    req = _request(photoStyle=PhotoStyleType.POLISHED)
    for step in ("pose", "outfit", "background"):
        wf = w._build_step_workflow(step, req, "src.png", 42, "job-1", pose_ref_name="ref.png")
        prompt = _positive_prompt(wf, step)
        assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] in prompt, f"{step} missing polished clause"


def test_pipeline_defaults_to_polished():
    # The unified /v1/edit pipeline now DEFAULTS to POLISHED (was None) so a pipeline
    # edit matches the generated hero's retouched finish across all steps.
    assert _request().photoStyle == PhotoStyleType.POLISHED
    w = _worker()
    req = _request()  # unset -> POLISHED default
    for step in ("pose", "outfit", "background"):
        wf = w._build_step_workflow(step, req, "src.png", 42, "job-1", pose_ref_name="ref.png")
        assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] in _positive_prompt(wf, step)


def test_build_step_workflow_explicit_none_or_candid_is_legacy_no_style():
    # Legacy "no style clause" is still reachable by explicitly opting out.
    w = _worker()
    none_style = _request(photoStyle=None)
    candid = _request(photoStyle=PhotoStyleType.CANDID_PHONE)
    for step in ("pose", "outfit", "background"):
        wf_none = w._build_step_workflow(step, none_style, "src.png", 42, "job-1", pose_ref_name="ref.png")
        wf_candid = w._build_step_workflow(step, candid, "src.png", 42, "job-1", pose_ref_name="ref.png")
        assert _positive_prompt(wf_none, step) == _positive_prompt(wf_candid, step)
        for suffix in (EDIT_PHOTO_STYLE_SUFFIXES["polished"], EDIT_PHOTO_STYLE_SUFFIXES["studio"]):
            assert suffix not in _positive_prompt(wf_none, step)


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
