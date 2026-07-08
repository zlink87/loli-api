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
from typing import Tuple

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

    box = None
    with _lock:  # YuNet detector instances are not thread-safe
        det = _get_detector()
        det.setInputSize((w, h))
        ok, faces = det.detect(img)
        if faces is not None and len(faces):
            best = max(faces, key=lambda f: f[-1])
            x, y, fw, fh = (int(v) for v in best[:4])
            box = (x, y, fw, fh)

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
