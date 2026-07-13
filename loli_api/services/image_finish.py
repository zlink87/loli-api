"""
Output finishing: a subtle film-grain + local-contrast pass for final,
user-facing edit outputs.

WHY THIS EXISTS: AI-generated skin reads as "plastic" in large part because
diffusion output lacks the high-frequency texture a real camera sensor
captures — grain/noise, plus the micro local-contrast a lens+sensor chain
adds on top of it. Reintroducing a small, luminance-correlated monochrome
grain field (the kind that reads as "photographic" rather than "noisy"),
followed by a very gentle unsharp mask, is a cheap and well-known mitigation
for this look. This module is the single place that implements the recipe;
callers (SupabaseStorageService.upload_image) stay oblivious to the details.

Typical strength: 0.02-0.04 (see config.OUTPUT_FILM_GRAIN_STRENGTH). Below
that range the effect is imperceptible; much above ~0.06 it starts reading as
visible sensor noise rather than film grain.

Determinism: the noise field is seeded from a CRC32 of the INPUT png bytes, so
the same input always produces byte-identical output for a given strength.
This matters both for tests and for idempotent re-uploads/re-processing of the
same source image, which must not silently drift on every call.
"""
import logging
import zlib
from io import BytesIO

import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Storage folders that receive the finishing pass -- i.e. the FINAL,
# user-facing edit outputs a subscriber actually looks at, not intermediate,
# source, or debug artifacts. Verified against the real upload_image call
# sites (folder= kwarg / STORAGE_FOLDER constant), not guessed:
#   - workers/batch_pipeline_worker.py   STORAGE_FOLDER = "batch_edits"
#   - workers/pipeline_worker.py         folder="pipeline_edits"
#   - workers/outfit_worker.py           submit_and_save(..., "outfit_edits")
#     -> workers/base_worker.py save_output_image(folder=folder)
#   - workers/pose_worker.py             submit_and_save(..., "pose_edits")
#     -> workers/base_worker.py save_output_image(folder=folder)
#   - workers/background_edit_worker.py  submit_and_save(..., "background_edits")
#     -> workers/base_worker.py save_output_image(folder=folder)
#
# Deliberately EXCLUDED:
#   - "nude_bases" (workers/nude_base_worker.py): an edit SOURCE, not an
#     output -- it feeds back into outfit/pose/background re-diffusion, so
#     grain baked in here would compound across every downstream edit instead
#     of appearing exactly once on what the user actually sees.
#   - "character_creation" (workers/background_worker.py, the default
#     `folder` on upload_image): the character-generation hero look users
#     already respond well to -- left untouched on purpose, not an oversight.
#   - "debug_frames" (workers/pipeline_worker.py POSE_DEBUG_SAVE_PRE_REACTOR)
#     and any other debug/diagnostic folder: operator-only frames, never
#     shown to a user, no reason to spend the CPU or risk altering them.
FINISH_FOLDERS = frozenset({
    "batch_edits",
    "pipeline_edits",
    "outfit_edits",
    "pose_edits",
    "background_edits",
})

# Gentle local-contrast pass applied after grain (PIL's ImageFilter.UnsharpMask
# signature: radius, percent, threshold). Small percent/threshold keeps this a
# subtle "clarity" pass rather than a halo-inducing sharpen.
_UNSHARP_RADIUS = 2
_UNSHARP_PERCENT = 12
_UNSHARP_THRESHOLD = 2

# The independent per-channel chroma-noise component rides at this fraction of
# the main (monochrome, luminance-correlated) grain amplitude -- just a faint
# hint of color grain, the way real film stock has slight chromatic grain
# variance, without actually tinting the image.
_CHROMA_FRACTION = 0.25


def _highlight_taper(luma_norm: np.ndarray) -> np.ndarray:
    """
    Per-pixel grain-amplitude weight curve over normalized luma (0=black,
    1=white): ~1.0 in shadows/mids, tapering to ~0.4 in bright highlights.

    Real photographic grain reads strongest in shadows/midtones; blown
    highlights carry comparatively little visible grain. This is a simple
    linear taper standing in for that intuition -- not a physical sensor
    model.
    """
    return 0.4 + 0.6 * (1.0 - luma_norm)


def apply_film_grain(png_bytes: bytes, strength: float, *, sharpen: bool = True) -> bytes:
    """
    Add deterministic, luminance-correlated film grain (plus an optional
    gentle unsharp mask) to a PNG image.

    Args:
        png_bytes: source image, PNG-encoded.
        strength: grain amplitude as a fraction of the 0-255 luma range
            (typical 0.02-0.04). <= 0 disables the pass entirely and returns
            the input unchanged.
        sharpen: apply a gentle ImageFilter.UnsharpMask after grain (default
            True) -- a small local-contrast boost that reads as "clarity"
            rather than a hard sharpen.

    Returns:
        PNG-encoded bytes. Identical (same object) to `png_bytes` when
        strength <= 0.
    """
    if strength <= 0:
        return png_bytes

    img = Image.open(BytesIO(png_bytes))
    original_mode = img.mode

    # Alpha-less RGB is the common case (every photographic output on this
    # pipeline) -- keep it simple. For anything else, convert to RGB to run
    # the same math, then restore alpha / the original mode afterward so this
    # pass never silently drops transparency or changes the stored mode.
    alpha = None
    if original_mode == "RGB":
        rgb_img = img
    elif original_mode == "RGBA":
        alpha = img.getchannel("A")
        rgb_img = img.convert("RGB")
    else:
        logger.debug(
            "apply_film_grain: converting %s -> RGB for processing", original_mode
        )
        rgb_img = img.convert("RGB")

    rgb = np.asarray(rgb_img, dtype=np.float32)  # (H, W, 3), 0..255
    height, width = rgb.shape[:2]

    # Deterministic seed from the INPUT bytes -- the same source image always
    # produces the same underlying noise field, independent of strength (so
    # re-running at a different strength on the same source scales the same
    # pattern rather than drawing a fresh one).
    seed = zlib.crc32(png_bytes)
    rng = np.random.default_rng(seed)

    # Luma (ITU-R BT.601 weights -- matches PIL's own "L" conversion) drives
    # the per-pixel grain amplitude via _highlight_taper.
    luma = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    luma_norm = luma / 255.0
    amplitude = strength * 255.0 * _highlight_taper(luma_norm)  # (H, W)

    # Monochrome component: ONE noise field added identically to all three
    # channels. This cross-channel correlation is what makes the grain read as
    # photographic (real film/sensor grain is predominantly luminance noise)
    # instead of as colored digital static.
    mono_noise = rng.standard_normal((height, width)).astype(np.float32) * amplitude
    finished = rgb + mono_noise[:, :, None]

    # Chroma component: a much smaller INDEPENDENT noise draw per channel, so
    # there's a faint hint of color grain riding on top of the shared
    # monochrome field (subtle -- not a color cast).
    chroma_noise = (
        rng.standard_normal((height, width, 3)).astype(np.float32)
        * (amplitude[:, :, None] * _CHROMA_FRACTION)
    )
    finished = finished + chroma_noise

    finished = np.clip(finished, 0, 255).astype(np.uint8)
    finished_img = Image.fromarray(finished, mode="RGB")

    if sharpen:
        finished_img = finished_img.filter(
            ImageFilter.UnsharpMask(
                radius=_UNSHARP_RADIUS,
                percent=_UNSHARP_PERCENT,
                threshold=_UNSHARP_THRESHOLD,
            )
        )

    # Restore alpha / the original mode so this pass never changes anything
    # about the stored image beyond the pixels it's meant to touch.
    if alpha is not None:
        finished_img = finished_img.convert("RGBA")
        finished_img.putalpha(alpha)
    elif original_mode != "RGB":
        finished_img = finished_img.convert(original_mode)

    buffer = BytesIO()
    finished_img.save(buffer, format="PNG")
    return buffer.getvalue()
