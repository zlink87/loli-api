"""
Whitelisted output dimensions for character generation (Z-Image Turbo).

All dims are multiples of 16 with areas of ~1.4-1.9 MP, bracketing the
known-good production default 1088x1600 (1.74 MP) — no OOM regression surface.
Kept in a tiny standalone module so both models/requests.py (validators) and
services/comfyui_client.py (workflow injection) can import it without cycles.
"""

# aspect ratio -> (width, height)
ASPECT_RATIO_DIMS = {
    "2:3": (1088, 1600),   # default; byte-identical to today's template dims
    "3:4": (1152, 1536),
    "1:1": (1328, 1328),
    "9:16": (1008, 1792),
    "16:9": (1792, 1008),
    "3:2": (1600, 1088),
    "4:3": (1536, 1152),
}

ALLOWED_RESOLUTIONS = {f"{w}x{h}" for (w, h) in ASPECT_RATIO_DIMS.values()}

DEFAULT_ASPECT_RATIO = "2:3"


def dims_for(aspect_ratio: str | None = None, resolution: str | None = None) -> tuple[int, int]:
    """
    Resolve (width, height) from an explicit whitelisted resolution (wins) or an
    aspect-ratio preset. Falls back to the default 2:3 dims.
    """
    if resolution and resolution in ALLOWED_RESOLUTIONS:
        w, h = resolution.lower().split("x")
        return int(w), int(h)
    if aspect_ratio and aspect_ratio in ASPECT_RATIO_DIMS:
        return ASPECT_RATIO_DIMS[aspect_ratio]
    return ASPECT_RATIO_DIMS[DEFAULT_ASPECT_RATIO]
