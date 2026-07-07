"""
Pose reference assets — single source of truth for the 16 pose reference images.

The pose edit workflow (``edit_pose_action.json``) is structurally dependent on a
reference image: node 170 (LoadImage) loads it, its face is blacked out
(FaceBoundingBox -> RectFill) so it cannot leak identity, and it feeds the
Qwen edit conditioning (node 114 image2) plus the KSampler latent.

Rather than requiring the references to pre-exist on the RunPod worker's network
volume, we ship each reference as a base64 ``input.images[]`` entry alongside the
source image (same mechanism as source images). Node 170 then references the flat
filename that worker-comfyui writes into the worker's ComfyUI input dir.

The reference PNGs live in-repo at ``loli_api/assets/poses/pose_ref_<value>.png``
(flat names, all PNG, pre-downscaled). They are generated once via
``scripts/generate_pose_refs.py``.
"""
import base64
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models.enums import PoseType

logger = logging.getLogger(__name__)

# Directory holding the pose reference PNGs, relative to this module:
#   loli_api/services/pose_assets.py -> loli_api/assets/poses/
POSE_ASSETS_DIR: Path = Path(__file__).parent.parent / "assets" / "poses"

# Data URI prefix used for the base64 ``input.images[]`` entry sent to the worker.
_DATA_URI_PREFIX = "data:image/png;base64,"

# Module-level cache: pose value -> (filename, data_uri). Populated lazily by
# load_pose_reference_b64 and eagerly by preload().
_cache: Dict[str, Tuple[str, str]] = {}


def worker_filename(pose: PoseType) -> str:
    """
    Flat filename the worker's LoadImage node (170) references for this pose.

    e.g. PoseType.SITTING -> ``pose_ref_sitting.png``
    """
    return f"pose_ref_{pose.value}.png"


def asset_path(pose: PoseType) -> Path:
    """Absolute path to the pose reference PNG in this repo."""
    return POSE_ASSETS_DIR / worker_filename(pose)


def missing_pose_assets() -> List[PoseType]:
    """Return the list of PoseType members whose reference PNG is not installed."""
    return [pose for pose in PoseType if not asset_path(pose).exists()]


def load_pose_reference_b64(pose: PoseType) -> Tuple[str, str]:
    """
    Load a pose reference image and return ``(filename, data_uri)``.

    ``filename`` is the flat name node 170 should reference; ``data_uri`` is the
    ``data:image/png;base64,...`` payload for the ``input.images[]`` entry.

    Results are cached in-process. Raises FileNotFoundError with a clear,
    actionable message if the asset is not installed.
    """
    key = pose.value
    cached = _cache.get(key)
    if cached is not None:
        return cached

    filename = worker_filename(pose)
    path = asset_path(pose)
    if not path.exists():
        raise FileNotFoundError(
            f"Pose reference not installed for pose '{pose.value}': "
            f"expected file at {path}. "
            f"Generate the 16 pose references with scripts/generate_pose_refs.py."
        )

    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    data_uri = f"{_DATA_URI_PREFIX}{b64}"

    result = (filename, data_uri)
    _cache[key] = result
    return result


def preload() -> int:
    """
    Eagerly load all installed pose references into the in-process cache.

    Returns the number of references successfully loaded. Never raises on missing
    assets — callers (e.g. startup) log a warning about the gap and continue so
    non-pose endpoints are unaffected.
    """
    loaded = 0
    for pose in PoseType:
        try:
            load_pose_reference_b64(pose)
            loaded += 1
        except FileNotFoundError:
            # Missing asset is expected until the generator has been run; skip.
            continue
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Failed to preload pose reference '{pose.value}': {exc}")
    return loaded


def clear_cache() -> None:
    """Clear the in-process reference cache (used by tests)."""
    _cache.clear()
