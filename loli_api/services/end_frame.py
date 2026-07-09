"""
FLF2V end-frame generation (Phase 3).

The first-last-frame WAN path (WanFirstLastFrameToVideo) conditions generation on
BOTH a start frame (the source still) and a controlled END frame, so the clip
always resolves on an in-focus, camera-facing beat and identity drift drops (the
model synthesises coherent mid-frames instead of free-drifting to a soft,
out-of-focus tail).

This module produces that end frame from the source still. Two tiers were
considered:

  * Tier 1 (NOT shipped): a "soft smile, camera-facing, slightly closer crop"
    identity-preserving variant generated through the existing edit pipeline.
    The edit pipeline (outfit/pose/background) is entirely async + queue-based
    (worker -> RunPod -> persist); there is no synchronous "one still in, one
    edited still out" helper. Reusing it from inside the video worker would mean
    enqueuing a nested edit job, polling for completion and downloading the
    result — a second RunPod cold round-trip and substantial new orchestration
    that cannot be verified locally. That is out of scope for a safe, OFF-by-
    default change. See ``TODO(tier1)`` below for the hook.

  * Tier 2 (SHIPPED): a deterministic PIL centre-crop-zoom of the source still
    toward the upper-centre (face). This is identity-perfect (it is literally a
    crop of the source), always succeeds, needs no network, and gives WAN a
    stable "arrived closer" endpoint. It is the guaranteed fallback the FLF2V
    path is built on.
"""
import io
import logging

from PIL import Image

logger = logging.getLogger(__name__)

# Zoom factor toward the face for the deterministic end frame. A mild push-in
# (~1.18x) reads as "settled a little closer" without a jarring interpolation.
_DEFAULT_ZOOM = 1.18
_MIN_ZOOM = 1.05
_MAX_ZOOM = 1.40
# Vertical crop bias: 0.0 = crop from the very top, 0.5 = centred. Portrait stills
# put the face in the upper third, so bias the crop upward to keep the face framed.
_DEFAULT_VERTICAL_BIAS = 0.35


def crop_zoom_end_frame(
    image_bytes: bytes,
    zoom: float = _DEFAULT_ZOOM,
    vertical_bias: float = _DEFAULT_VERTICAL_BIAS,
) -> bytes:
    """
    Tier 2 end frame: a deterministic centre-crop-zoom of ``image_bytes`` toward
    the upper-centre, re-encoded as PNG at the SAME dimensions as the source.

    Identity-perfect (a straight crop of the source), always succeeds, no network.
    ``zoom`` is clamped to [1.05, 1.40]; ``vertical_bias`` to [0.0, 1.0].
    Raises only on genuinely undecodable input (the caller falls back to i2v).
    """
    zoom = max(_MIN_ZOOM, min(_MAX_ZOOM, zoom))
    vertical_bias = max(0.0, min(1.0, vertical_bias))

    with Image.open(io.BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        width, height = img.size

        crop_w = max(1, int(round(width / zoom)))
        crop_h = max(1, int(round(height / zoom)))
        left = (width - crop_w) // 2
        top = int(round((height - crop_h) * vertical_bias))
        box = (left, top, left + crop_w, top + crop_h)

        cropped = img.crop(box).resize((width, height), Image.LANCZOS)

    out = io.BytesIO()
    cropped.save(out, format="PNG")
    return out.getvalue()


def resolve_end_frame_bytes(source_bytes: bytes) -> bytes:
    """
    Produce the FLF2V end-frame image bytes from the source still bytes.

    Currently always Tier 2 (deterministic crop-zoom). This is the single seam a
    future Tier 1 would slot into.

    TODO(tier1): when a synchronous, identity-preserving "source still -> soft
    smile / camera-facing / slightly closer" edit path exists, try it here first
    and fall back to ``crop_zoom_end_frame`` on any failure. Keep the transform
    MILD so the interpolated motion stays plausible.
    """
    return crop_zoom_end_frame(source_bytes)
