"""
Black-box the face in every pose reference asset (one-time preprocessing).

WHY: the pose workflow feeds a reference photo (image2) to Qwen-Image-Edit to copy
the POSE from. The original workflow anonymized the reference on the worker
(FaceAnalysis FaceBoundingBox -> RectFill black, padding 20%) so the model could
never copy the reference person's identity — the hero (image1) stayed the only
identity source. That node chain was removed from the worker image (dlib build
issues), so the anonymization now happens HERE, offline, on the static assets.

Detection: OpenCV YuNet (downloaded on first run) with Haar-cascade fallback.
Any asset with no detected face is reported at the end for manual fixing.

Usage (from repo root):
    .venv/bin/python loli_api/scripts/blackbox_pose_refs.py [--dry-run]

Originals are backed up next to the assets as <name>.orig.png (git-ignored is
fine; they are also recoverable from git history).
"""
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "poses"
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_PATH = Path(__file__).resolve().parent / "face_detection_yunet_2023mar.onnx"
PADDING = 0.20  # matches the original FaceBoundingBox padding_percent 0.2


def _yunet():
    if not YUNET_PATH.exists():
        print(f"downloading YuNet model -> {YUNET_PATH.name}")
        urllib.request.urlretrieve(YUNET_URL, YUNET_PATH)
    return cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (320, 320), 0.6, 0.3, 5000)


def detect_face(img) -> tuple | None:
    """Return (x, y, w, h) of the most confident face, or None."""
    h, w = img.shape[:2]
    det = _DETECTOR
    det.setInputSize((w, h))
    ok, faces = det.detect(img)
    if faces is not None and len(faces):
        best = max(faces, key=lambda f: f[-1])
        x, y, fw, fh = best[:4]
        return int(x), int(y), int(fw), int(fh)
    # Haar fallback (frontal, then profile both directions)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for casc_name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        casc = cv2.CascadeClassifier(cv2.data.haarcascades + casc_name)
        for frame in (gray, cv2.flip(gray, 1)):
            found = casc.detectMultiScale(frame, 1.1, 5, minSize=(int(w * 0.05), int(h * 0.05)))
            if len(found):
                x, y, fw, fh = max(found, key=lambda r: r[2] * r[3])
                if frame is not gray:  # un-mirror
                    x = w - x - fw
                return int(x), int(y), int(fw), int(fh)
    return None


def blackbox(path: Path, dry: bool) -> bool:
    img = cv2.imread(str(path))
    if img is None:
        print(f"  !! unreadable: {path.name}")
        return False
    box = detect_face(img)
    if box is None:
        return False
    x, y, w, h = box
    pad_w, pad_h = int(w * PADDING), int(h * PADDING)
    x0, y0 = max(0, x - pad_w), max(0, y - pad_h)
    x1, y1 = min(img.shape[1], x + w + pad_w), min(img.shape[0], y + h + pad_h)
    if dry:
        print(f"  {path.name}: face at ({x0},{y0})-({x1},{y1})")
        return True
    backup = path.with_suffix(".orig.png")
    if not backup.exists():
        cv2.imwrite(str(backup), img)
    img[y0:y1, x0:x1] = 0
    cv2.imwrite(str(path), img)
    print(f"  {path.name}: blacked ({x0},{y0})-({x1},{y1})")
    return True


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    _DETECTOR = _yunet()
    pngs = sorted(p for p in ASSETS.glob("pose_ref_*.png") if ".orig" not in p.name)
    print(f"{len(pngs)} pose refs in {ASSETS}{' (dry run)' if dry else ''}")
    missed = [p.name for p in pngs if not blackbox(p, dry)]
    if missed:
        print(f"\nNO FACE FOUND (fix manually): {missed}")
        sys.exit(1)
    print("\nall faces blacked" if not dry else "\nall faces detected")
