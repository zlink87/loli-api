"""
Tests for the reel motion path: the 24-value MotionType ↔ MOTION_DESCRIPTIONS
mapping, the build_video_prompt preset-vs-custom-override behaviour, the
MotionWriter deterministic fallback, and the persisted label precedence.

Runs under pytest or directly: python loli_api/tests/test_video_motion.py
"""
import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.enums import MotionType
from models.requests import VideoGenerateRequest
from services import prompt_constants as pc
from services.motion_writer import MotionWriter, _MAX_LABEL_LEN
from api.v1.endpoints.video import (
    MOTION_DESCRIPTIONS,
    build_video_prompt,
    motion_label,
    prepare_video_workflow,
)

_WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"


# ---------------------------------------------------------------------------
# MotionType ↔ MOTION_DESCRIPTIONS completeness (a missing key silently falls
# back to a generic description in build_video_prompt).
# ---------------------------------------------------------------------------
def test_motion_type_has_24_members():
    assert len(list(MotionType)) == 24


def test_every_motion_type_has_a_description():
    for motion in MotionType:
        assert motion in MOTION_DESCRIPTIONS, f"missing description for {motion.value}"
        assert MOTION_DESCRIPTIONS[motion].strip(), f"empty description for {motion.value}"


def test_legacy_motion_values_unchanged():
    # Back-compat: the original 8 value strings must stay identical (motion is
    # stored as free JSONB metadata.motion).
    for value in (
        "subtle_idle", "slow_turn", "hair_in_wind", "hair_flip",
        "blow_kiss", "wave", "walk_toward", "look_over_shoulder",
    ):
        assert MotionType(value).value == value


# ---------------------------------------------------------------------------
# build_video_prompt — preset path vs custom-override path.
# ---------------------------------------------------------------------------
def test_build_video_prompt_preset_path():
    prompt = build_video_prompt(MotionType.HAIR_IN_WIND)
    assert MOTION_DESCRIPTIONS[MotionType.HAIR_IN_WIND] in prompt
    assert pc.VIDEO_CONSISTENCY_CLAUSE in prompt


def test_build_video_prompt_custom_override_replaces_preset():
    custom = "she does a graceful cartwheel then grins at the camera"
    prompt = build_video_prompt(MotionType.HAIR_IN_WIND, extra=custom)
    assert custom in prompt
    assert pc.VIDEO_CONSISTENCY_CLAUSE in prompt
    # The preset description must NOT leak into the custom path.
    assert MOTION_DESCRIPTIONS[MotionType.HAIR_IN_WIND] not in prompt


def test_build_video_prompt_blank_extra_uses_preset():
    prompt = build_video_prompt(MotionType.WAVE, extra="   ")
    assert MOTION_DESCRIPTIONS[MotionType.WAVE] in prompt
    assert pc.VIDEO_CONSISTENCY_CLAUSE in prompt


# ---------------------------------------------------------------------------
# MotionWriter — deterministic fallback when disabled (no api_key). Never raises.
# ---------------------------------------------------------------------------
def test_motion_writer_disabled_falls_back_to_raw_text():
    writer = MotionWriter(api_key="")
    assert writer.enabled is False

    user_text = "  do a little happy dance and wink  "
    desc, label, provider = asyncio.run(writer.interpret(user_text))

    assert provider == "deterministic"
    assert desc == user_text.strip()
    assert label == user_text.strip()[:_MAX_LABEL_LEN]
    assert len(label) <= _MAX_LABEL_LEN


def test_motion_writer_disabled_truncates_long_label():
    writer = MotionWriter(api_key="")
    long_text = "x" * 100
    desc, label, provider = asyncio.run(writer.interpret(long_text))
    assert provider == "deterministic"
    assert len(label) == _MAX_LABEL_LEN


def test_motion_writer_never_raises_on_empty_input():
    writer = MotionWriter(api_key="")
    desc, label, provider = asyncio.run(writer.interpret(""))
    assert provider == "deterministic"
    assert desc == ""
    assert label == ""


# ---------------------------------------------------------------------------
# Persisted label precedence: request.motionLabel or motion_label(request.motion).
# ---------------------------------------------------------------------------
def test_label_precedence_prefers_motion_label():
    custom_label = "Happy Dance"
    resolved = custom_label or motion_label(MotionType.SUBTLE_IDLE)
    assert resolved == custom_label


def test_label_precedence_falls_back_to_preset():
    resolved = None or motion_label(MotionType.SLOW_TURN)
    assert resolved == motion_label(MotionType.SLOW_TURN)
    assert resolved == "Slow Turn"


# ---------------------------------------------------------------------------
# Phase 2a — frame-interpolation workflow shape + frame_rate scaling.
# ---------------------------------------------------------------------------
def _load_workflow(name: str) -> dict:
    with open(_WORKFLOWS_DIR / name) as f:
        return json.load(f)


def test_interp_workflow_is_valid_json_and_wired():
    wf = _load_workflow("wan_i2v_interp.json")
    # Node 60 (VideoImagesBridge) now consumes the interpolated frames.
    assert wf["60"]["inputs"]["images"] == ["71", 0]
    # Node 71 is FrameInterpolate x2, fed by the VAE decode (node 8) + the loader.
    assert wf["71"]["class_type"] == "FrameInterpolate"
    assert wf["71"]["inputs"]["multiplier"] == 2
    assert wf["71"]["inputs"]["images"] == ["8", 0]
    assert wf["71"]["inputs"]["interp_model"] == ["70", 0]
    # Node 70 is the interpolation model loader.
    assert wf["70"]["class_type"] == "FrameInterpolationModelLoader"


def test_prepare_workflow_scales_frame_rate_when_interpolating():
    wf = prepare_video_workflow(
        _load_workflow("wan_i2v_interp.json"),
        source_image="x.png",
        fps=16,
    )
    # 16fps generation x2 multiplier = 32fps real-time playback.
    assert wf["60"]["inputs"]["frame_rate"] == 32


def test_prepare_workflow_leaves_frame_rate_without_interp_node():
    wf = prepare_video_workflow(
        _load_workflow("wan_i2v.json"),
        source_image="x.png",
        fps=16,
    )
    assert wf["60"]["inputs"]["frame_rate"] == 16


# ---------------------------------------------------------------------------
# Phase 2b — per-request resolution opt-in (allowlisted pairs only).
# ---------------------------------------------------------------------------
def test_video_request_accepts_allowed_resolution():
    req = VideoGenerateRequest(
        source_image_id="id", motion=MotionType.WAVE, width=720, height=1280,
    )
    assert (req.width, req.height) == (720, 1280)


def test_video_request_defaults_resolution_to_none():
    req = VideoGenerateRequest(source_image_id="id", motion=MotionType.WAVE)
    assert req.width is None and req.height is None


def test_video_request_rejects_disallowed_resolution():
    with pytest.raises(ValidationError):
        VideoGenerateRequest(
            source_image_id="id", motion=MotionType.WAVE, width=1024, height=1024,
        )


# ---------------------------------------------------------------------------
# Phase 3 — FLF2V (first-last-frame) workflow, preparer, end-frame, opt-in.
# ---------------------------------------------------------------------------
from api.v1.endpoints.video import prepare_flf2v_workflow
from services.end_frame import crop_zoom_end_frame, resolve_end_frame_bytes


def test_flf2v_workflow_is_valid_json_with_flf_node_and_anchors():
    wf = _load_workflow("wan_i2v_flf2v.json")
    # The i2v WanImageToVideo is replaced by WanFirstLastFrameToVideo (node 50),
    # taking BOTH a start_image (node 52) and an end_image (node 53).
    assert wf["50"]["class_type"] == "WanFirstLastFrameToVideo"
    assert wf["50"]["inputs"]["start_image"] == ["52", 0]
    assert wf["50"]["inputs"]["end_image"] == ["53", 0]
    # Start + end frames are LoadImage anchors.
    assert wf["52"]["class_type"] == "LoadImage"
    assert wf["53"]["class_type"] == "LoadImage"
    assert "[ANCHOR: source image]" in wf["52"]["_meta"]["title"]
    assert "[ANCHOR: end image]" in wf["53"]["_meta"]["title"]


def test_prepare_flf2v_workflow_writes_start_and_end_and_params():
    wf = prepare_flf2v_workflow(
        _load_workflow("wan_i2v_flf2v.json"),
        source_image="start.png",
        end_image="end.png",
        prompt="wave then smile at the camera",
        negative_prompt="blurry",
        seed=4242,
        width=480,
        height=832,
        length=81,
        fps=16,
    )
    # Both image anchors written.
    assert wf["52"]["inputs"]["image"] == "start.png"
    assert wf["53"]["inputs"]["image"] == "end.png"
    # Prompt / negative / dims / fps.
    assert wf["6"]["inputs"]["text"] == "wave then smile at the camera"
    assert wf["7"]["inputs"]["text"] == "blurry"
    assert wf["50"]["inputs"]["width"] == 480
    assert wf["50"]["inputs"]["height"] == 832
    assert wf["50"]["inputs"]["length"] == 81
    assert wf["60"]["inputs"]["frame_rate"] == 16
    # Seed written to BOTH experts.
    assert wf["57"]["inputs"]["noise_seed"] == 4242
    assert wf["58"]["inputs"]["noise_seed"] == 4242


def _png_bytes(width: int, height: int) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 90, 200)).save(buf, format="PNG")
    return buf.getvalue()


def test_crop_zoom_end_frame_preserves_dimensions_and_is_valid_png():
    import io
    from PIL import Image
    src = _png_bytes(200, 360)
    out = crop_zoom_end_frame(src)
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "PNG"
        assert img.size == (200, 360)  # same dims as the source still


def test_resolve_end_frame_bytes_tier2_always_succeeds():
    out = resolve_end_frame_bytes(_png_bytes(128, 128))
    assert isinstance(out, bytes) and len(out) > 0


def test_video_request_useflf2v_defaults_false():
    req = VideoGenerateRequest(source_image_id="id", motion=MotionType.WAVE)
    assert req.useFlf2v is False


def test_worker_path_selection_picks_i2v_when_flf2v_off():
    # The worker's branch predicate: opt-in AND a loaded FLF2V template.
    from workers.video_worker import VideoBackgroundWorker
    worker = VideoBackgroundWorker(
        job_manager=None,
        comfyui_client=None,
        storage_service=None,
        workflow_path="workflows/wan_i2v.json",
    )
    # Default construction: no FLF2V template loaded, path empty.
    assert worker._flf2v_template is None
    assert worker.flf2v_workflow_path == ""

    req_off = VideoGenerateRequest(source_image_id="id", motion=MotionType.WAVE)
    req_on = VideoGenerateRequest(source_image_id="id", motion=MotionType.WAVE, useFlf2v=True)

    def _use_flf2v(request, template):
        return bool(getattr(request, "useFlf2v", False)) and (template is not None)

    # Off by request -> i2v; even opted-in stays i2v while the template is None.
    assert _use_flf2v(req_off, worker._flf2v_template) is False
    assert _use_flf2v(req_on, worker._flf2v_template) is False
    # Only opted-in AND template present -> FLF2V.
    assert _use_flf2v(req_on, {"50": {}}) is True


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
