#!/usr/bin/env python3
"""
One-time generator for the 16 pose reference images.

Drives the live API's ``POST /v1/generate/image`` endpoint (NOT the raw ComfyUI
workflow) with a fixed neutral adult persona (age 30) plus each pose's
``POSE_DESCRIPTIONS`` text and a full-body framing suffix. It polls the job to
completion, downloads the preview, downscales it to <=1024px on the longest side,
re-encodes it as a PNG <=500 KB, and writes it to
``assets/poses/pose_ref_<value>.png``.

The pose workflow blacks out the reference's face at runtime
(FaceBoundingBox -> RectFill), so any generated person in the correct pose works
as a reference — identity never leaks from these images.

Usage examples
--------------
    # Generate every missing pose reference against a local API:
    python scripts/generate_pose_refs.py \
        --api-base http://localhost:8000 --token "$JWT"

    # Regenerate two specific poses, overwriting existing files:
    python scripts/generate_pose_refs.py --token "$JWT" \
        --pose sitting --pose spread_legs --overwrite

    # Preview what would run without calling the API:
    python scripts/generate_pose_refs.py --dry-run

Exit code is non-zero if any requested pose fails to generate/download/save.
"""
import argparse
import io
import sys
import time
from pathlib import Path
from typing import List, Optional

# Make the loli_api package importable when this script is run directly, so we
# can single-source POSE_DESCRIPTIONS and the pose asset naming/paths.
_LOLI_API_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_API_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_API_DIR))

from models.enums import PoseType  # noqa: E402
from api.v1.endpoints.pose import POSE_DESCRIPTIONS  # noqa: E402
from services import pose_assets  # noqa: E402

# Full-body framing appended to every generation request so the reference shows
# the whole pose against a clean background.
FRAMING_SUFFIX = (
    "full body visible head to toe, single person alone, "
    "plain neutral studio background"
)

# Fixed neutral adult persona (age 30) reused for every pose reference.
BASE_PERSONA = {
    "style": "realistic",
    "ethnicity": "caucasian",
    "age": 30,
    "hairStyle": "straight",
    "hairColor": "brunette",
    "eyeColor": "brown",
    "bodyType": "average",
    "breastSize": "medium",
    "name": "PoseReference",
}

# Downscale / encode targets for the saved reference PNGs.
MAX_LONGEST_SIDE = 1024
MAX_FILE_BYTES = 500 * 1024  # 500 KB

# Job polling.
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 360


def parse_poses(values: Optional[List[str]]) -> List[PoseType]:
    """Resolve --pose values (or all poses if none given) to PoseType members."""
    if not values:
        return list(PoseType)
    resolved: List[PoseType] = []
    valid = {p.value: p for p in PoseType}
    for v in values:
        if v not in valid:
            raise SystemExit(
                f"Unknown pose '{v}'. Valid poses: {', '.join(sorted(valid))}"
            )
        resolved.append(valid[v])
    return resolved


def build_context(pose: PoseType) -> str:
    """Compose the free-text ``context`` field for a pose generation request."""
    desc = POSE_DESCRIPTIONS.get(pose, "natural pose")
    return f"{desc}. {FRAMING_SUFFIX}"


def _require_requests():
    try:
        import requests  # noqa: F401
    except ImportError:
        raise SystemExit(
            "The 'requests' package is required to run this generator. "
            "Install it with: pip install requests"
        )
    return sys.modules["requests"]


def submit_generation(session, api_base: str, token: str, pose: PoseType) -> str:
    """POST /v1/generate/image; return the created jobId."""
    payload = {
        "persona": BASE_PERSONA,
        "context": build_context(pose),
        "isEnhance": True,
    }
    resp = session.post(
        f"{api_base}/v1/generate/image",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    job_id = data.get("jobId")
    if not job_id:
        raise RuntimeError(f"No jobId in generate response: {data}")
    return job_id


def poll_job(session, api_base: str, token: str, job_id: str) -> str:
    """Poll GET /v1/jobs/{jobId} until succeeded; return the preview URL."""
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(f"Job {job_id} timed out after {POLL_TIMEOUT_SECONDS}s")
        resp = session.get(
            f"{api_base}/v1/jobs/{job_id}", headers=headers, timeout=30
        )
        resp.raise_for_status()
        doc = resp.json()
        status = doc.get("status")
        if status == "succeeded":
            results = doc.get("results") or []
            if not results or not results[0].get("previewUrl"):
                raise RuntimeError(f"Job {job_id} succeeded but has no previewUrl")
            return results[0]["previewUrl"]
        if status == "failed":
            err = doc.get("error") or {}
            raise RuntimeError(
                f"Job {job_id} failed: "
                f"{err.get('code', 'UNKNOWN')}: {err.get('message', '')}"
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def download_and_process(session, preview_url: str) -> bytes:
    """
    Download the preview image, downscale to <=1024px on the longest side, and
    re-encode as a PNG <=500 KB. Returns the PNG bytes.
    """
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "The 'Pillow' package is required to downscale/encode references. "
            "Install it with: pip install Pillow"
        )

    resp = session.get(preview_url, timeout=60)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content))
    img = img.convert("RGB")

    # Downscale so the longest side is at most MAX_LONGEST_SIDE.
    w, h = img.size
    longest = max(w, h)
    if longest > MAX_LONGEST_SIDE:
        scale = MAX_LONGEST_SIDE / float(longest)
        img = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS
        )

    # Encode PNG; if over budget, progressively shrink until it fits.
    for attempt in range(8):
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_FILE_BYTES:
            return data
        # Shrink 15% and retry.
        w, h = img.size
        img = img.resize(
            (max(1, int(w * 0.85)), max(1, int(h * 0.85))), Image.LANCZOS
        )
    # Return the last (smallest) attempt even if still slightly over budget.
    return data


def process_pose(
    session, api_base: str, token: str, pose: PoseType, out_dir: Path,
    overwrite: bool,
) -> str:
    """
    Full pipeline for a single pose. Returns a status string:
    'saved', 'skipped', or raises on failure.
    """
    out_path = out_dir / pose_assets.worker_filename(pose)
    if out_path.exists() and not overwrite:
        print(f"  [skip]  {pose.value}: {out_path.name} already exists (use --overwrite)")
        return "skipped"

    print(f"  [gen]   {pose.value}: submitting generation...")
    job_id = submit_generation(session, api_base, token, pose)
    print(f"  [poll]  {pose.value}: job {job_id}, polling...")
    preview_url = poll_job(session, api_base, token, job_id)
    print(f"  [dl]    {pose.value}: downloading + downscaling...")
    png_bytes = download_and_process(session, preview_url)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_bytes)
    print(f"  [saved] {pose.value}: {out_path} ({len(png_bytes)} bytes)")
    return "saved"


def print_review_checklist(saved: List[PoseType], out_dir: Path) -> None:
    """Print a manual-review checklist for the generated references."""
    if not saved:
        return
    print()
    print("=" * 70)
    print("MANUAL REVIEW CHECKLIST")
    print("=" * 70)
    print(f"Generated {len(saved)} reference(s) in {out_dir}")
    print("Review each image and confirm:")
    print("  [ ] The pose clearly matches the intended pose type")
    print("  [ ] The full body is visible (head to toe)")
    print("  [ ] Exactly one person is shown, alone")
    print("  [ ] The background is plain/neutral (not distracting)")
    print("  [ ] The subject reads as an adult (30)")
    print("Re-run rejected poses with: --pose <value> --overwrite")
    print("Files to review:")
    for pose in saved:
        print(f"  - {pose.value}: {out_dir / pose_assets.worker_filename(pose)}")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the 16 pose reference images via POST /v1/generate/image."
    )
    parser.add_argument(
        "--pose",
        action="append",
        dest="poses",
        metavar="POSE",
        help="Pose value to (re)generate. Repeatable. Default: all 16 poses.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing reference files.",
    )
    parser.add_argument(
        "--api-base",
        default="http://localhost:8000",
        help="Base URL of the running loli-api (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="JWT bearer token for the API (required unless --dry-run).",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help=(
            "Directory to write references into "
            f"(default: {pose_assets.POSE_ASSETS_DIR})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be generated without calling the API.",
    )
    args = parser.parse_args()

    poses = parse_poses(args.poses)
    out_dir = Path(args.out_dir) if args.out_dir else pose_assets.POSE_ASSETS_DIR
    api_base = args.api_base.rstrip("/")

    if args.dry_run:
        print(f"[dry-run] API base: {api_base}")
        print(f"[dry-run] Output dir: {out_dir}")
        print(f"[dry-run] Overwrite: {args.overwrite}")
        print(f"[dry-run] {len(poses)} pose(s) would be generated:")
        for pose in poses:
            out_path = out_dir / pose_assets.worker_filename(pose)
            marker = "exists" if out_path.exists() else "missing"
            print(f"  - {pose.value} -> {out_path.name} [{marker}]")
            print(f"      context: {build_context(pose)}")
        return 0

    if not args.token:
        raise SystemExit("--token is required (unless --dry-run). Provide a JWT bearer token.")

    requests = _require_requests()
    session = requests.Session()

    print(f"Generating {len(poses)} pose reference(s) against {api_base}")
    saved: List[PoseType] = []
    failures: List[str] = []
    for pose in poses:
        try:
            result = process_pose(
                session, api_base, args.token, pose, out_dir, args.overwrite
            )
            if result == "saved":
                saved.append(pose)
        except Exception as exc:
            print(f"  [FAIL]  {pose.value}: {exc}")
            failures.append(pose.value)

    print_review_checklist(saved, out_dir)

    print()
    print(f"Done: {len(saved)} saved, {len(failures)} failed.")
    if failures:
        print(f"Failed poses: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
