"""
Pose reference assets — single source of truth for the pose reference images
(one per PoseType).

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


# ---------------------------------------------------------------------------
# Pose text descriptions — SINGLE SOURCE OF TRUTH for the per-pose prose injected
# into the pose workflow prompt (node 114) and used by scripts/generate_pose_refs.py
# to render each reference image. This lives here (a service) rather than in
# api/v1/endpoints/pose.py so services and scripts never import from api/; the
# endpoint re-exports it (``from services.pose_assets import POSE_DESCRIPTIONS``)
# for back-compat. Keep in lockstep with PoseType (one entry per member).
# ---------------------------------------------------------------------------
POSE_DESCRIPTIONS: Dict[PoseType, str] = {
    PoseType.STANDING_LEANING: "standing and leaning against a wall or surface, relaxed casual pose",
    PoseType.SITTING: "sitting upright on a chair or seat, legs together, relaxed posture",
    PoseType.SITTING_LEGS_WIDE_OPEN: "sitting with legs spread wide open, provocative seated pose",
    PoseType.SOFA: "sitting comfortably on a sofa, relaxed, leaning back slightly",
    PoseType.LYING_BACK: "lying on her back on a bed or soft surface, relaxed, looking up",
    PoseType.LYING_STOMACH: "lying face down on her stomach, head turned to one side",
    PoseType.KNEELING: "kneeling on the ground or bed, upright torso, knees apart",
    PoseType.BENDING_OVER: "bending over at the waist, looking back over shoulder",
    PoseType.HANDS_BEHIND_HEAD: "standing with hands behind head, chest out, confident pose",
    PoseType.SQUATTING: "squatting down low, knees bent wide, balanced posture",
    PoseType.ALL_FOURS: "on all fours, hands and knees on the ground or bed",
    PoseType.SPREAD_LEGS: "lying back or sitting with legs spread wide apart",
    PoseType.EATING: "sitting at a table eating, casual everyday pose",
    PoseType.JOGGING: "jogging or running, dynamic motion pose",
    PoseType.OPENING_FRIDGE: "standing and reaching into an open refrigerator",
    PoseType.COOKING: "standing in a kitchen cooking, hands busy with food preparation",
    # --- POSE PACK (07-14): active/lifestyle ---
    PoseType.WALKING: "walking toward the camera with a relaxed natural stride",
    PoseType.WALKING_AWAY: "walking away from the camera, glancing back over her shoulder",
    PoseType.RUNNING: "running mid-stride, athletic dynamic motion",
    PoseType.DANCING: "dancing freely, body in relaxed motion",
    PoseType.STRETCHING: "stretching with arms raised overhead, elongated posture",
    # --- POSE PACK (07-14): camera-aware provocative (the phrase carries the camera direction) ---
    PoseType.ALL_FOURS_FROM_BEHIND: "on all fours facing away, photographed from behind, looking back over her shoulder at the camera",
    PoseType.BENT_OVER_FROM_BEHIND: "bending forward at the waist, photographed from behind, glancing back at the camera",
    PoseType.KNEELING_ARCHED_BACK: "kneeling upright with her back arched, chest lifted, hands resting on her thighs",
    PoseType.LYING_ON_SIDE: "lying on her side, propped on one elbow, hip curve emphasized, facing the camera",
    PoseType.OVER_SHOULDER_LOOK: "standing with her back to the camera, looking back over her shoulder",
    PoseType.STRADDLING_CHAIR: "straddling a chair backwards, arms folded on the chairback, facing the camera",
}


def worker_filename(pose: PoseType) -> str:
    """
    Flat filename the worker's LoadImage node (170) references for this pose.

    e.g. PoseType.SITTING -> ``pose_ref_sitting.png``
    """
    return f"pose_ref_{pose.value}.png"


def asset_path(pose: PoseType) -> Path:
    """Absolute path to the pose reference PNG in this repo."""
    return POSE_ASSETS_DIR / worker_filename(pose)


def has_pose_ref(pose: PoseType) -> bool:
    """
    True iff this pose's reference PNG is installed on disk
    (``loli_api/assets/poses/pose_ref_<value>.png``).

    This is the POSE PACK "ref latch" predicate, the single safety piece that lets new
    poses ship in the enum + descriptions before their reference images exist:

      * the story planner filters its pose pools through it (services.story_planner.
        _allowed_pose_pool / _controls_pose_vocab), so a batch NEVER picks a pose whose
        reference is missing (``load_pose_reference_b64`` would raise) — a refless pose is
        simply invisible to planning, which also keeps the effective pose vocabulary
        byte-identical to before the pose was added (determinism preserved);
      * the /v1/edit/pose endpoint calls it to 422 an interactive request naming a
        not-yet-generated pose.

    A pose stays "dark" (present in the enum, never rendered) until its PNG is generated +
    committed via scripts/generate_pose_refs.py, at which point it lights up with no code
    change. No caching: a bare stat is cheap, and existence flips exactly once (when the
    PNG lands) so a cache would only add staleness risk (some tests point POSE_ASSETS_DIR
    at a tmp dir).
    """
    return asset_path(pose).exists()


def missing_pose_assets() -> List[PoseType]:
    """Return the list of PoseType members whose reference PNG is not installed."""
    return [pose for pose in PoseType if not has_pose_ref(pose)]


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
            f"Generate the pose references with scripts/generate_pose_refs.py."
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
