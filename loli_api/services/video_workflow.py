"""
Workflow-prep helpers for image-to-video (reel) generation.

This module owns the pure, network-free helpers that turn a motion preset (or a
custom motion text) + a source still into a mutated WAN 2.2 i2v ComfyUI graph.
They were moved here out of ``api/v1/endpoints/video.py`` so both the single-clip
route and the per-character video-batch subsystem can share them without a route
import; ``video.py`` re-exports the original names for back-compat (route +
tests keep importing them from there).

New in the batch era:
    * ``build_catalog_prompt``            — catalog preset text + identity clause.
    * ``select_video_template``           — pick lightning vs baseline per mode/tier.
    * ``prepare_lightning_video_workflow``— baseline anchor writes PLUS runtime
                                            insertion of 0-2 preset-LoRA nodes into
                                            the WAN high-noise (and, for H+L pairs,
                                            low-noise) chain + an interpolate toggle.
    * ``resolve_item_loras``              — snapshot a preset's LoRAs to plain dicts.
"""
import copy
import logging
from typing import Any, Dict, List, Optional

from models.enums import MotionType
from services import prompt_constants as pc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Motion presets — text descriptions injected into the WAN positive prompt.
# (Moved verbatim from api/v1/endpoints/video.py; the video-batch action catalog
# reuses these same 24 texts for the first 24 catalog presets.)
# ---------------------------------------------------------------------------
MOTION_DESCRIPTIONS: Dict[MotionType, str] = {
    MotionType.SUBTLE_IDLE: "subtle idle motion, gentle breathing and micro head movements, then settling into a soft smile toward the camera, static camera",
    MotionType.SLOW_TURN: "slowly turning head and shoulders to face the camera, then holding the gaze with a soft smile",
    MotionType.HAIR_IN_WIND: "hair flowing gently in the wind, soft fabric movement, then tucking a strand behind the ear and smiling at the camera",
    MotionType.HAIR_FLIP: "playfully flipping hair back over the shoulder, then looking to the camera with a warm smile",
    MotionType.BLOW_KISS: "smiling warmly, leaning slightly toward the camera and blowing a kiss",
    MotionType.WAVE: "waving a hand at the camera, then a warm friendly smile",
    MotionType.WALK_TOWARD: "walking slowly toward the camera, then stopping close, leaning in slightly, blinking softly and smiling at the camera",
    MotionType.LOOK_OVER_SHOULDER: "glancing back over the shoulder, then turning to face the camera with a soft smile",
    MotionType.WINK: "looking at the camera, smiling and giving a playful wink",
    MotionType.LIP_BITE: "a soft sultry gaze at the camera, gently biting the lower lip, then a faint smile",
    MotionType.BEND_TO_CAMERA: "leaning and bending toward the camera, then looking up through the lashes and smiling",
    MotionType.HEAD_TILT: "tilting the head with curiosity, then a soft smile toward the camera",
    MotionType.ADJUST_HAIR: "running fingers through the hair, then settling and smiling at the camera",
    MotionType.GLANCE_UP_THROUGH_LASHES: "looking down, then slowly glancing up at the camera through the lashes with a soft smile",
    MotionType.GENTLE_LAUGH: "a genuine, gentle laugh, then looking at the camera with a bright smile",
    MotionType.SHOULDER_SWAY: "swaying the shoulders playfully to a rhythm, ending facing the camera with a smile",
    MotionType.COME_HITHER: "beckoning toward the camera with a curling finger and a playful smile",
    MotionType.TWIRL: "turning in a gentle twirl, hair and fabric flaring, then facing the camera with a smile",
    MotionType.PEACE_SIGN: "raising a playful peace sign near the face, then a wink and a smile at the camera",
    MotionType.TOUCH_LIPS: "softly touching the lips with a fingertip, gaze to the camera, then a faint smile",
    MotionType.SLOW_STRETCH: "a slow graceful stretch, relaxing the shoulders, then a soft smile toward the camera",
    MotionType.LEAN_ON_HAND: "leaning forward toward the camera, resting the chin lightly on a hand, then smiling",
    MotionType.GAZE_AND_SMILE: "a slow, intimate gaze into the camera that softens into a warm smile",
    MotionType.NOD_AND_SMILE: "a gentle nod of acknowledgement toward the camera, then a warm smile",
}

_MAX_LABEL_LEN = 40


def motion_label(motion: MotionType) -> str:
    """Short human caption for the chat quick-action button."""
    text = motion.value.replace("_", " ").title()
    return text[:_MAX_LABEL_LEN]


def build_video_prompt(motion: MotionType, extra: Optional[str] = None) -> str:
    """Compose the WAN positive prompt from a motion preset + identity clause.

    When ``extra`` (custom motion text, already LLM-polished by the request path)
    is supplied it REPLACES the preset entirely; otherwise the ``motion`` preset
    description is used. The identity-lock ``VIDEO_CONSISTENCY_CLAUSE`` is always
    appended in either path.
    """
    if extra and extra.strip():
        return f"{extra.strip()}. {pc.VIDEO_CONSISTENCY_CLAUSE}."
    desc = MOTION_DESCRIPTIONS.get(motion, "subtle natural motion, static camera")
    return f"{desc}. {pc.VIDEO_CONSISTENCY_CLAUSE}."


def prepare_video_workflow(
    template: dict,
    source_image: str,
    prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    length: Optional[int] = None,
    fps: Optional[int] = None,
) -> dict:
    """
    Prepare the WAN 2.2 i2v workflow (workflows/wan_i2v.json) by mutating the
    pinned anchor node IDs. Mirrors prepare_pose_workflow (deep-copy + guarded
    writes).

    Anchor nodes:
        52  LoadImage        -> inputs.image  (start frame)
        6   CLIPTextEncode   -> inputs.text   (positive / motion prompt)
        7   CLIPTextEncode   -> inputs.text   (negative)
        50  WanImageToVideo  -> inputs.width/height/length
        57  KSamplerAdvanced -> inputs.noise_seed  (high-noise expert)
        58  KSamplerAdvanced -> inputs.noise_seed  (low-noise expert)
        60  VideoImagesBridge -> inputs.frame_rate
    """
    wf = copy.deepcopy(template)

    if "52" in wf:
        wf["52"]["inputs"]["image"] = source_image

    if prompt is not None and "6" in wf:
        wf["6"]["inputs"]["text"] = prompt

    if negative_prompt is not None and "7" in wf:
        wf["7"]["inputs"]["text"] = negative_prompt

    if "50" in wf:
        if width is not None:
            wf["50"]["inputs"]["width"] = width
        if height is not None:
            wf["50"]["inputs"]["height"] = height
        if length is not None:
            wf["50"]["inputs"]["length"] = length

    # Seed both experts (high-noise then low-noise) so the clip is reproducible.
    if seed is not None:
        for nid in ("57", "58"):
            if nid in wf:
                wf[nid]["inputs"]["noise_seed"] = seed

    if fps is not None and "60" in wf:
        wf["60"]["inputs"]["frame_rate"] = fps

        # When the interpolation variant of the workflow is in use, the clip is
        # generated at `fps` but has multiplier x more frames after FrameInterpolate;
        # scale the output frame_rate so playback stays real-time (16fps gen x2 = 32).
        for node in wf.values():
            if node.get("class_type") == "FrameInterpolate":
                multiplier = node.get("inputs", {}).get("multiplier", 1)
                wf["60"]["inputs"]["frame_rate"] = fps * multiplier
                break

    return wf


def prepare_flf2v_workflow(
    template: dict,
    source_image: str,
    end_image: str,
    prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    length: Optional[int] = None,
    fps: Optional[int] = None,
) -> dict:
    """
    Prepare the WAN 2.2 first-last-frame workflow (workflows/wan_i2v_flf2v.json).

    Identical to prepare_video_workflow but for the extra END-frame anchor: this
    graph's node 50 is a ``WanFirstLastFrameToVideo`` (not ``WanImageToVideo``)
    that takes both a start_image (node 52) and an end_image (node 53). All the
    other anchors (prompt/negative/seed/dims/fps) are shared, so we delegate to
    prepare_video_workflow and only add the node-53 end-image write here.

    Anchor nodes (in addition to prepare_video_workflow's):
        53  LoadImage  -> inputs.image  (end frame)
    """
    wf = prepare_video_workflow(
        template,
        source_image,
        prompt=prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        width=width,
        height=height,
        length=length,
        fps=fps,
    )

    if "53" in wf:
        wf["53"]["inputs"]["image"] = end_image

    return wf


# ---------------------------------------------------------------------------
# Video-batch additions.
# ---------------------------------------------------------------------------
def build_catalog_prompt(text: str) -> str:
    """Compose the WAN positive prompt from a catalog preset text + identity clause.

    Same shape as build_video_prompt's custom path: the preset motion text plus
    the identity-lock VIDEO_CONSISTENCY_CLAUSE. Kept separate from
    build_video_prompt (which is keyed on a MotionType) so the catalog registry
    is not coupled to the old enum.
    """
    return f"{(text or '').strip()}. {pc.VIDEO_CONSISTENCY_CLAUSE}."


def select_video_template(
    quality_mode: Any,
    tier: Any,
    *,
    lightning: Optional[dict],
    baseline: Optional[dict],
):
    """Pick the workflow template for an item and report the resolved quality mode.

    Rules:
        * ``max``      -> baseline (undistilled two-expert graph).
        * ``fast``     -> lightning (distilled low-noise expert, ~4-step).
        * explicit tier ALWAYS forces lightning (NSFW motion LoRAs are wired into
          the lightning graph's runtime insertion contract), overriding ``max``.

    ``quality_mode``/``tier`` accept either the str-Enum members or their string
    values (str-Enum equality with the raw string holds both ways), so callers can
    pass an enum or a persisted text column interchangeably. ``tier`` is None for
    custom (hand-written) items.

    Returns ``(template, resolved_mode)`` where ``resolved_mode`` is the "fast" /
    "max" string actually used. When the fast (lightning) template is unavailable
    for a non-explicit item, degrades to the baseline template; an explicit item
    with no lightning template is rejected upstream at launch (the orchestrator
    gates it), so here it simply returns the (possibly None) lightning template so
    the caller can surface the misconfiguration rather than silently baselining an
    NSFW item.
    """
    is_explicit = tier == "explicit"
    is_max = quality_mode == "max"

    if is_explicit:
        if is_max:
            logger.info(
                "[VIDEO_BATCH] explicit tier forces the lightning path; "
                "overriding requested quality_mode=max"
            )
        return lightning, "fast"

    if is_max:
        return baseline, "max"

    # fast (default): lightning when available, else degrade to baseline.
    if lightning is None:
        return baseline, "max"
    return lightning, "fast"


def resolve_item_loras(preset: Any) -> List[Dict[str, Any]]:
    """Snapshot a catalog preset's LoRAs to plain dicts for the item JSONB column.

    Duck-typed on ``preset.loras`` (a tuple of LoraRef); returns
    ``[{"name", "strength_high", "strength_low"}, ...]`` — an empty list for
    presets that carry no LoRAs (every non-explicit tier).
    """
    return [
        {
            "name": ref.name,
            "strength_high": ref.strength_high,
            "strength_low": ref.strength_low,
        }
        for ref in getattr(preset, "loras", ()) or ()
    ]


def _lora_triples(loras) -> List[tuple]:
    """Normalize preset LoRAs (LoraRef objects OR plain dicts) to (name, high, low)."""
    out: List[tuple] = []
    for ref in loras or ():
        if isinstance(ref, dict):
            name = ref.get("name")
            high = ref.get("strength_high", 0.0)
            low = ref.get("strength_low", 0.0)
        else:
            name = getattr(ref, "name", None)
            high = getattr(ref, "strength_high", 0.0)
            low = getattr(ref, "strength_low", 0.0)
        if name:
            out.append((name, float(high), float(low)))
    return out


# Runtime preset-LoRA node ids (master plan A4(d)): up to 2 on the HIGH chain
# (37 -> 82 -> 83 -> 54) and up to 2 on the LOW chain (81 -> 84 -> 85 -> 55).
_HIGH_LORA_NODE_IDS = ("82", "83")
_LOW_LORA_NODE_IDS = ("84", "85")


def _insert_preset_loras(wf: dict, loras) -> None:
    """Insert 0-2 preset-LoRA ``LoraLoaderModelOnly`` nodes into the WAN chains.

    Contract (master plan A4(d)):
        * HIGH chain: for each preset LoRA, chain a LoraLoaderModelOnly node into
          the high-noise path 37 -> 82 (-> 83) -> 54 with strength_model =
          strength_high. Node 54's ``model`` input is rewired to the last inserted
          node; with 0 LoRAs the chain is byte-identical (54.model stays ["37",0]).
        * LOW chain: when a LoRA's strength_low > 0, ALSO chain the SAME lora_name
          on the low-noise side between the Lightning node (81) and node 55 as
          nodes 84 (-> 85) with strength_model = strength_low.

    Defensive: reads the CURRENT ``model`` input of the tail node (54 / 55) rather
    than hardcoding the upstream id, so the wiring is correct whether or not the
    template baked the Lightning LoRA at node 81 (or wired the high chain
    differently). Mutates ``wf`` in place.
    """
    triples = _lora_triples(loras)
    if not triples:
        return

    # --- HIGH chain: 37 -> 82 (-> 83) -> 54 ---
    if "54" in wf:
        prev = wf["54"]["inputs"].get("model")  # e.g. ["37", 0]
        for i, (name, high, _low) in enumerate(triples[: len(_HIGH_LORA_NODE_IDS)]):
            nid = _HIGH_LORA_NODE_IDS[i]
            wf[nid] = {
                "inputs": {
                    "lora_name": name,
                    "strength_model": high,
                    "model": prev,
                },
                "class_type": "LoraLoaderModelOnly",
                "_meta": {"title": f"Preset LoRA (high) [{name}]"},
            }
            prev = [nid, 0]
        wf["54"]["inputs"]["model"] = prev

    # --- LOW chain: 81 -> 84 (-> 85) -> 55, only for LoRAs with strength_low > 0 ---
    low_triples = [t for t in triples if t[2] > 0]
    if low_triples and "55" in wf:
        prev = wf["55"]["inputs"].get("model")  # e.g. ["81", 0] in the lightning template
        for i, (name, _high, low) in enumerate(low_triples[: len(_LOW_LORA_NODE_IDS)]):
            nid = _LOW_LORA_NODE_IDS[i]
            wf[nid] = {
                "inputs": {
                    "lora_name": name,
                    "strength_model": low,
                    "model": prev,
                },
                "class_type": "LoraLoaderModelOnly",
                "_meta": {"title": f"Preset LoRA (low) [{name}]"},
            }
            prev = [nid, 0]
        wf["55"]["inputs"]["model"] = prev


def prepare_lightning_video_workflow(
    template: dict,
    source_image: str,
    prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    length: Optional[int] = None,
    fps: Optional[int] = None,
    loras=None,
    interpolate: bool = False,
) -> dict:
    """Prepare the WAN 2.2 Lightning i2v workflow (workflows/wan_i2v_lightning.json).

    The lightning template = wan_i2v_interp.json + a baked Lightning low-noise
    LoRA at node 81 (low chain 56 -> 81 -> 55; high chain 37 -> 54 untouched) +
    a mixed sampler schedule. This preparer writes the same anchors as
    prepare_video_workflow (source / positive / negative / dims / both-expert seed
    / frame_rate) and then:

    * Sets the FrameInterpolate node's multiplier to 2 (interpolate=True) or 1
      (interpolate=False). The node is found by class_type scan (not a hardcoded
      id) so an id shuffle in the exported graph can't silently disable it. The
      frame_rate on node 60 is scaled by that multiplier by the shared anchor
      logic (16fps gen x2 = 32fps playback; x1 = identity).
    * Inserts 0-2 runtime preset-LoRA nodes per the A4(d) contract (see
      ``_insert_preset_loras``).
    """
    wf = copy.deepcopy(template)

    # Set the interpolate multiplier FIRST so the shared frame_rate scaling in
    # prepare_video_workflow reads the intended value. Defensive class_type scan.
    multiplier = 2 if interpolate else 1
    for node in wf.values():
        if node.get("class_type") == "FrameInterpolate":
            node.setdefault("inputs", {})["multiplier"] = multiplier
            break

    # Shared anchor writes (source/pos/neg/dims/seed/frame_rate). prepare_video_workflow
    # deep-copies again — harmless (graphs are tiny) and keeps the anchor logic DRY.
    wf = prepare_video_workflow(
        wf,
        source_image,
        prompt=prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        width=width,
        height=height,
        length=length,
        fps=fps,
    )

    # Runtime preset-LoRA insertion into the high (and, for H+L pairs, low) chain.
    _insert_preset_loras(wf, loras)

    return wf
