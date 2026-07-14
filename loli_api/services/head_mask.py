"""
Server-side head-protection mask for outfit edits.

WHY THIS EXISTS: the outfit edit region is the PERSON (the only mask that both
dresses a nude hero and swaps clothes on a dressed one), but the head must never
be editable. On-worker face detection is unreliable for our heroes:
GroundingDINO phrase-grounding misses small and stylized faces, and insightface
(ReActor) fails on stylized/anime-ish renders — both failure modes were observed
in production. OpenCV **YuNet**, however, detects these stylized faces reliably
(verified 16/16 on the equally-stylized pose reference assets), so the
head-protect mask is computed HERE on the server and shipped to the workflow as
a per-request image input (LoadImage -> ImageToMask -> MaskComposite subtract).
No on-worker face detection required.

Mask semantics: WHITE = protected head region (face box, padded generously and
extended upward to cover the hair/scalp, feathered), BLACK = editable. When no
face is found we FAIL CLOSED: a conservative top-center fallback box protects the
head region anyway. The old all-black behavior was wrong — with the real masked
inpaint (noise_mask=true), an unprotected head lands inside the editable region
and the face is destroyed (observed in production). Over-protecting a little
background is harmless; leaving the face editable is not.
"""
import io
import logging
import threading
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parent.parent / "assets" / "models" / "face_detection_yunet_2023mar.onnx"

# Face-box padding fractions (of the detected box size).
_PAD_X = 0.45        # sideways: ears + hair sides
_PAD_TOP = 1.50      # upward: full scalp + voluminous hair (clears the silhouette top)
_PAD_BOTTOM = 0.35   # downward: chin + jawline
_FEATHER = 31        # Gaussian kernel for soft mask edges (odd)

# Fail-closed fallback box (fractions of W/H), used when YuNet finds no face.
# Heroes are portrait / waist-up, so the head is reliably top-center. Protecting
# this region is far safer than an all-black mask that leaves the face editable.
_FALLBACK_X0 = 0.20
_FALLBACK_X1 = 0.80
_FALLBACK_Y1 = 0.30

_lock = threading.Lock()
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        if not _MODEL_PATH.exists():
            raise FileNotFoundError(f"YuNet model missing: {_MODEL_PATH}")
        _detector = cv2.FaceDetectorYN.create(str(_MODEL_PATH), "", (320, 320), 0.6, 0.3, 5000)
    return _detector


def _detect_face_box(img) -> Optional[Tuple[int, int, int, int]]:
    """Highest-confidence face box (x, y, w, h) via the shared YuNet detector, or None
    when no face is found. Thread-safe (the detector instance is not, hence the lock).
    Extracted so both build_head_mask and crop_face_donor share ONE detection path."""
    h, w = img.shape[:2]
    with _lock:  # YuNet detector instances are not thread-safe
        det = _get_detector()
        det.setInputSize((w, h))
        _ok, faces = det.detect(img)
    if faces is None or not len(faces):
        return None
    best = max(faces, key=lambda f: f[-1])
    x, y, fw, fh = (int(v) for v in best[:4])
    return (x, y, fw, fh)


# Face-donor crop (FACE_REF_CROP): margin expansion + a minimum-size guard. The detected
# face box is grown this many multiples of its OWN size on each side (keeping hair/neck/a
# little context while dropping the surrounding scene); a resulting crop smaller than the
# min on either side, or one that removes no scenery, falls back to the full image.
_CROP_EXPAND = 1.6
_CROP_MIN = 256


def crop_face_donor(image_bytes: bytes) -> Tuple[bytes, bool]:
    """
    Crop a hero photo down to the primary face/head region so it can serve as the pose
    graph's ReActor / image3 conditioning donor (node 210) WITHOUT dragging the hero's own
    scenery into the reference latents. Reuses the same YuNet detector as build_head_mask.

    The detected face box is expanded ``_CROP_EXPAND`` x its own size on each side, squared
    up by growing the short side, and clamped to the image bounds; the region is re-encoded
    as PNG.

    Returns ``(png_bytes, cropped)``:
      * ``(cropped_png, True)``  — a real face-region crop (strictly smaller than the source
        on at least one axis).
      * ``(image_bytes, False)`` — FALLBACK to the UNCHANGED full image (same bytes object)
        when no face is detected, the crop would be smaller than ``_CROP_MIN`` px on an axis,
        or it removes no scenery. ReActor face-detects the donor itself, so a full-image
        fallback is always swap-safe.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("crop_face_donor: could not decode source image")
    h, w = img.shape[:2]

    box = _detect_face_box(img)
    if box is None:
        return image_bytes, False  # detector miss -> stage the full hero unchanged

    x, y, fw, fh = box
    x0 = x - fw * _CROP_EXPAND
    x1 = x + fw + fw * _CROP_EXPAND
    y0 = y - fh * _CROP_EXPAND
    y1 = y + fh + fh * _CROP_EXPAND

    # Square-ish: grow the SHORT side symmetrically toward the long side.
    cw, ch = x1 - x0, y1 - y0
    if cw < ch:
        pad = (ch - cw) / 2.0
        x0, x1 = x0 - pad, x1 + pad
    elif ch < cw:
        pad = (cw - ch) / 2.0
        y0, y1 = y0 - pad, y1 + pad

    # Clamp to image bounds.
    x0, y0 = max(0, int(round(x0))), max(0, int(round(y0)))
    x1, y1 = min(w, int(round(x1))), min(h, int(round(y1)))

    cw, ch = x1 - x0, y1 - y0
    if cw < _CROP_MIN or ch < _CROP_MIN:
        return image_bytes, False  # crop too small to be a useful donor -> full image
    if cw >= w and ch >= h:
        return image_bytes, False  # nothing actually cropped away -> full image

    crop = img[y0:y1, x0:x1]
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("crop_face_donor: PNG encode failed")
    return buf.tobytes(), True


def build_head_mask(image_bytes: bytes) -> Tuple[bytes, bool]:
    """
    Build the head-protection mask PNG for a source image.

    Returns (png_bytes, face_found). The PNG has the SAME dimensions as the
    source; white (feathered) over the padded head region, black elsewhere.
    All-black when no face is detected.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("head_mask: could not decode source image")
    h, w = img.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    box = _detect_face_box(img)

    found = box is not None
    if found:
        x, y, fw, fh = box
        x0 = max(0, int(x - fw * _PAD_X))
        x1 = min(w, int(x + fw * (1 + _PAD_X)))
        y0 = max(0, int(y - fh * _PAD_TOP))
        y1 = min(h, int(y + fh * (1 + _PAD_BOTTOM)))
    else:
        # FAIL CLOSED: detection missed, so protect a conservative top-center
        # region rather than returning an all-black (fully-editable) mask that
        # would let the inpaint destroy the face.
        x0, x1 = int(w * _FALLBACK_X0), int(w * _FALLBACK_X1)
        y0, y1 = 0, int(h * _FALLBACK_Y1)

    mask[y0:y1, x0:x1] = 255
    mask = cv2.GaussianBlur(mask, (_FEATHER, _FEATHER), 0)

    ok, buf = cv2.imencode(".png", mask)
    if not ok:
        raise ValueError("head_mask: PNG encode failed")
    return buf.tobytes(), found
