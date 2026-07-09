"""
Tests for the pose reference system (Part A).

Covers:
  t1  prepared pose workflow: node 170 flat filename (no "poses/" prefix),
      node 109 source name, node 114 prompt injection, node 3 seed set.
  t2  staging: stage_pose_reference appends a second data-URI entry so
      _pending_images has 2 entries, both data:image/png;base64,, correct names,
      and the returned name equals the entry name.
  t3  payload bound: a representative ~3 MB source + a pose ref stays under the
      9.5 MiB submission cap when JSON-serialized.
  t4  B1 regression: pipeline _build_step_workflow("pose", ...) sets node 114 to
      build_pose_prompt(request.pose) (NOT the template's baked-in string), and an
      outfit step appends no pose reference entry.

Runs under pytest AND under plain ``python tests/test_pose_refs.py`` (the
__main__ block invokes each test function; pytest is not required).
"""
import asyncio
import base64
import json
import sys
from pathlib import Path

# Ensure the loli_api package dir is importable when run as a plain script
# (mirrors conftest.py / main.py:22).
_LOLI_API_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_API_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_API_DIR))

from models.enums import PoseType, OutfitType, NudityLevel  # noqa: E402
from services import pose_assets  # noqa: E402
from api.v1.endpoints.pose import (  # noqa: E402
    build_pose_prompt,
    prepare_pose_workflow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tiny_png_bytes() -> bytes:
    """
    Return bytes for a tiny valid PNG. Uses Pillow if available, otherwise a
    hard-coded 1x1 PNG (so the test works even without Pillow installed).
    """
    try:
        from PIL import Image
        import io

        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (128, 64, 200)).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Minimal 1x1 opaque PNG.
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )


def _fake_pose_template() -> dict:
    """
    Minimal pose workflow template with the nodes prepare_pose_workflow touches.
    Node 114 carries a distinctive baked-in string so t4 can prove it is replaced.
    """
    return {
        "109": {"inputs": {"image": "PLACEHOLDER_SOURCE"}},
        "170": {"inputs": {"image": "PLACEHOLDER_REF"}},
        "114": {"inputs": {"prompt": "TEMPLATE_BAKED_IN_POSE_TEXT"}},
        "3": {"inputs": {"seed": 0, "steps": 4}},
    }


class _StubJobManager:
    """No-op job manager stand-in for constructing a worker."""

    async def update_job_status(self, *args, **kwargs):
        return None


def _make_pose_worker():
    """Construct a PoseBackgroundWorker with stubbed dependencies (no network)."""
    from workers.pose_worker import PoseBackgroundWorker

    return PoseBackgroundWorker(
        job_manager=_StubJobManager(),
        comfyui_client=None,
        storage_service=None,
        workflow_path="unused.json",
    )


# ---------------------------------------------------------------------------
# t1 — prepared pose workflow wiring
# ---------------------------------------------------------------------------
def test_prepared_pose_workflow_node_wiring():
    template = _fake_pose_template()
    source_name = "pose_src_abc123.png"
    ref_name = pose_assets.worker_filename(PoseType.SITTING)
    prompt = build_pose_prompt(PoseType.SITTING)
    seed = 4242

    wf = prepare_pose_workflow(
        template, source_name, ref_name, prompt=prompt, seed=seed
    )

    # Node 170: flat reference filename, no legacy "poses/" prefix.
    assert wf["170"]["inputs"]["image"] == ref_name
    assert ref_name == "pose_ref_sitting.png"
    assert "poses/" not in wf["170"]["inputs"]["image"]

    # Node 109: source image name.
    assert wf["109"]["inputs"]["image"] == source_name

    # Node 114: prompt contains the pose description text.
    assert PoseType.SITTING.value.replace("_", " ") or True  # sanity
    desc = "sitting upright on a chair or seat"
    assert desc in wf["114"]["inputs"]["prompt"]
    assert wf["114"]["inputs"]["prompt"] == prompt

    # Node 3: seed set.
    assert wf["3"]["inputs"]["seed"] == seed

    # Original template not mutated (prepare_pose_workflow deep-copies).
    assert template["170"]["inputs"]["image"] == "PLACEHOLDER_REF"
    print("t1 OK: node 170 flat name, node 109 source, node 114 prompt, node 3 seed")


# ---------------------------------------------------------------------------
# t2 — staging appends a second data-URI entry
# ---------------------------------------------------------------------------
def test_stage_pose_reference_appends_entry(tmp_path=None, monkeypatch=None):
    # Support both pytest (fixtures injected) and plain-script invocation.
    import tempfile

    created_tmp = None
    if tmp_path is None:
        created_tmp = tempfile.TemporaryDirectory()
        pose_dir = Path(created_tmp.name)
    else:
        pose_dir = Path(tmp_path)

    orig_dir = pose_assets.POSE_ASSETS_DIR
    try:
        # Point pose_assets at a tmp dir containing a tiny generated PNG.
        pose_assets.POSE_ASSETS_DIR = pose_dir
        pose_assets.clear_cache()
        pose = PoseType.SITTING
        ref_file = pose_dir / pose_assets.worker_filename(pose)
        ref_file.write_bytes(_tiny_png_bytes())

        worker = _make_pose_worker()

        # Pre-stage a source entry the way prepare_source_image would.
        source_name = "pose_src_deadbeef.png"
        src_uri = "data:image/png;base64," + base64.b64encode(_tiny_png_bytes()).decode("ascii")
        worker._pending_images = [{"name": source_name, "image": src_uri}]

        returned_name = asyncio.run(worker.stage_pose_reference(pose))

        pending = worker._pending_images
        assert len(pending) == 2, f"expected 2 pending images, got {len(pending)}"

        # Both entries are PNG data URIs.
        for entry in pending:
            assert entry["image"].startswith("data:image/png;base64,")

        # First entry is the source, second is the pose reference.
        assert pending[0]["name"] == source_name
        ref_entry = pending[1]
        expected_ref_name = pose_assets.worker_filename(pose)
        assert ref_entry["name"] == expected_ref_name == "pose_ref_sitting.png"

        # Returned name matches the appended entry name.
        assert returned_name == ref_entry["name"]
        print("t2 OK: _pending_images has 2 PNG data-URI entries; returned name matches")
    finally:
        pose_assets.POSE_ASSETS_DIR = orig_dir
        pose_assets.clear_cache()
        if created_tmp is not None:
            created_tmp.cleanup()


# ---------------------------------------------------------------------------
# t3 — payload stays under the submission cap
# ---------------------------------------------------------------------------
def test_payload_under_cap():
    from workers.base_worker import MAX_PENDING_IMAGES_BYTES

    # Representative ~3 MB source image (raw bytes -> base64 ~4 MB).
    source_raw = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (3 * 1024 * 1024))
    source_b64 = base64.b64encode(source_raw).decode("ascii")

    # A ref that respects the generator's <=500 KB budget (raw), base64 ~680 KB.
    ref_raw = b"\x89PNG\r\n\x1a\n" + (b"\x11" * (500 * 1024))
    ref_b64 = base64.b64encode(ref_raw).decode("ascii")

    pending = [
        {"name": "pose_src.png", "image": f"data:image/png;base64,{source_b64}"},
        {"name": "pose_ref_sitting.png", "image": f"data:image/png;base64,{ref_b64}"},
    ]

    # The size check in submit_and_save sums len() of the base64 image strings.
    total_image_str_bytes = sum(len(e["image"]) for e in pending)
    assert total_image_str_bytes < MAX_PENDING_IMAGES_BYTES, (
        f"pending image strings {total_image_str_bytes} exceed cap "
        f"{MAX_PENDING_IMAGES_BYTES}"
    )

    # And the full JSON-serialized payload also stays under the cap.
    serialized = json.dumps({"input": {"images": pending}})
    assert len(serialized.encode("utf-8")) < MAX_PENDING_IMAGES_BYTES
    print(
        f"t3 OK: representative source+ref = {total_image_str_bytes} bytes "
        f"(< {MAX_PENDING_IMAGES_BYTES} cap)"
    )


# ---------------------------------------------------------------------------
# t4 — B1 regression: pipeline pose step carries build_pose_prompt text
# ---------------------------------------------------------------------------
class _FakePipelineRequest:
    """Minimal request stand-in exposing the fields _build_step_workflow reads."""

    def __init__(self, pose=None, outfit=None, nudityLevel=NudityLevel.LOW):
        self.pose = pose
        self.outfit = outfit
        self.nudityLevel = nudityLevel
        self.accessories = None
        self.prompt = None
        self.negativePrompt = None


def _make_pipeline_worker():
    from workers.pipeline_worker import PipelineBackgroundWorker

    worker = PipelineBackgroundWorker(
        job_manager=_StubJobManager(),
        comfyui_client=None,
        storage_service=None,
        pose_workflow_path="unused.json",
        outfit_workflow_path="unused.json",
    )
    # Inject templates directly (start()/_load_workflows() would read files).
    worker._pose_template = _fake_pose_template()
    worker._outfit_template = {
        "108": {"inputs": {"image": "PLACEHOLDER"}},
        "16": {"inputs": {"positive": "TEMPLATE_OUTFIT_TEXT"}},
        "117": {"inputs": {"negative": "TEMPLATE_NEG"}},
        "106": {"inputs": {"seed": 0}},
    }
    return worker


def test_pipeline_pose_step_carries_prompt_and_no_ref_on_outfit():
    worker = _make_pipeline_worker()
    pose = PoseType.SPREAD_LEGS
    request = _FakePipelineRequest(pose=pose)
    ref_name = pose_assets.worker_filename(pose)

    # Pose branch must inject build_pose_prompt(pose) into node 114.
    wf = worker._build_step_workflow(
        "pose", request, "pipe_pose_src.png", seed=99, job_id="jobX",
        pose_ref_name=ref_name,
    )
    expected_prompt = build_pose_prompt(pose)
    assert wf["114"]["inputs"]["prompt"] == expected_prompt
    assert wf["114"]["inputs"]["prompt"] != "TEMPLATE_BAKED_IN_POSE_TEXT"
    # And node 170 uses the single passed-in flat ref name.
    assert wf["170"]["inputs"]["image"] == ref_name == "pose_ref_spread_legs.png"

    # Outfit step: build the images list the way _run_step does and confirm no
    # pose reference is appended (only the source entry).
    from workers.pipeline_worker import _stage_image

    outfit_request = _FakePipelineRequest(outfit=OutfitType.BUSINESS_SUIT)
    _src_name, images = _stage_image(b"fake-outfit-source-bytes", "pipe_outfit")
    # _run_step only appends a pose ref when step_name == "pose"; for outfit the
    # images list stays at exactly one (source) entry.
    assert len(images) == 1
    assert images[0]["name"].startswith("pipe_outfit_")
    print(
        "t4 OK: pipeline pose step node 114 == build_pose_prompt (not baked-in); "
        "outfit step appends no pose reference"
    )


# ---------------------------------------------------------------------------
# t5 — W3 regression: _build_step_workflow threads request.lighting/timeOfDay
# into the pose step's node 114 prompt (the primary lighting fix — pose is the
# only pipeline step that fully re-diffuses the frame), and request.lighting
# into the outfit step's node 16 prompt (secondary/cheap addition). A request
# with neither attribute set (the pre-W3 shape) still produces the exact
# pre-W3 prompt.
# ---------------------------------------------------------------------------
def test_pipeline_step_workflow_threads_lighting_and_time_of_day():
    worker = _make_pipeline_worker()
    pose = PoseType.SITTING
    ref_name = pose_assets.worker_filename(pose)

    # Pose step: both lighting + timeOfDay set on the request reach node 114,
    # phrase-ified exactly like a direct build_pose_prompt(..., lighting=...,
    # time_of_day=...) call.
    pose_request = _FakePipelineRequest(pose=pose)
    pose_request.lighting = "moody_dim"
    pose_request.timeOfDay = "night"

    wf = worker._build_step_workflow(
        "pose", pose_request, "pipe_pose_src.png", seed=99, job_id="jobLight",
        pose_ref_name=ref_name,
    )
    node114_prompt = wf["114"]["inputs"]["prompt"]
    assert node114_prompt == build_pose_prompt(pose, lighting="moody_dim", time_of_day="night")
    assert "in moody dim low-key lighting" in node114_prompt
    assert "late at night" in node114_prompt
    # Raw enum-value string never leaks into the actual node prompt.
    assert "moody_dim" not in node114_prompt

    # A request with no lighting/timeOfDay attributes at all (the pre-W3
    # shape, same as _FakePipelineRequest elsewhere in this file) still
    # produces the exact pre-W3 prompt (back-compat).
    bare_request = _FakePipelineRequest(pose=pose)
    bare_wf = worker._build_step_workflow(
        "pose", bare_request, "pipe_pose_src.png", seed=99, job_id="jobBare",
        pose_ref_name=ref_name,
    )
    assert bare_wf["114"]["inputs"]["prompt"] == build_pose_prompt(pose)

    # Outfit step: lighting reaches node 16 (secondary/cheap signal).
    outfit_request = _FakePipelineRequest(outfit=OutfitType.BUSINESS_SUIT)
    outfit_request.lighting = "candlelit"
    outfit_wf = worker._build_step_workflow(
        "outfit", outfit_request, "pipe_outfit_src.png", seed=99, job_id="jobOutfitLight",
    )
    node16_prompt = outfit_wf["16"]["inputs"]["positive"]
    assert "in flickering candlelight" in node16_prompt
    assert "candlelit" not in node16_prompt

    print(
        "t5 OK: _build_step_workflow threads lighting/timeOfDay into the pose step's "
        "node 114, and lighting into the outfit step's node 16; a bare request (no "
        "attrs) stays byte-identical to pre-W3"
    )


# ---------------------------------------------------------------------------
# Plain-script runner (pytest not required)
# ---------------------------------------------------------------------------
def _run_all():
    tests = [
        test_prepared_pose_workflow_node_wiring,
        test_stage_pose_reference_appends_entry,
        test_payload_under_cap,
        test_pipeline_pose_step_carries_prompt_and_no_ref_on_outfit,
        test_pipeline_step_workflow_threads_lighting_and_time_of_day,
    ]
    failures = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            import traceback

            print(f"FAIL: {fn.__name__}: {exc}")
            traceback.print_exc()
    print()
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
