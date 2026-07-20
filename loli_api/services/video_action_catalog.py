"""
Video action catalog — the tiered registry of selectable reel actions.

A data-driven registry (frozen dataclasses), NOT a 40-member enum. Each preset is
a motion prompt in one of five ascending tiers; explicit-tier presets carry 1-2
NSFW motion ``LoraRef``s that the workflow preparer inserts into the WAN graph at
runtime (master plan A4(d)).

The first 24 entries reuse the existing ``MotionType`` ids + ``MOTION_DESCRIPTIONS``
texts verbatim (a back-compat-proven register) so every single-clip motion is also
a batch action; the remaining entries fill out glamour / tease / explicit. The old
``MotionType`` enum + single-clip route are untouched by this module.

Explicit-tier LoRA sourcing (licensing diligence, 2026-07-17): the community WAN 2.2
NSFW LoRAs on Civitai/mirrors are license-encumbered for off-platform commercial use
(e.g. CubeyAI's General NSFW is RentCivit-only), so the ONLY third-party LoRA wired
here is NSFW-API's openrail-m LoRA extraction (author-owned, commercial use allowed):
  huggingface.co/NSFW-API/NSFW_Wan_14b -> nsfw_lora_wan_14b_e15.safetensors
staged on the volume as loras/nsfw/nsfw_wan14b_e15.safetensors. It is 2.1-T2V-based,
so it runs on the HIGH-noise expert only (strength_low=0) at moderate strength; the
prompts alone carry the motion on base WAN 2.2 if the LoRA is ever dropped. Roadmap:
replace with in-house trained WAN 2.2 I2V motion LoRAs.
"""
from dataclasses import dataclass
from typing import List, Optional

from models.enums import MotionType
from models.video_batch import VideoActionTier
from services.video_workflow import MOTION_DESCRIPTIONS, motion_label


@dataclass(frozen=True)
class LoraRef:
    """A preset NSFW motion LoRA: file on the volume + per-expert strengths."""

    name: str
    strength_high: float
    strength_low: float


@dataclass(frozen=True)
class VideoActionPreset:
    """One selectable action: an id, a caption, its tier, the motion prompt, LoRAs."""

    id: str
    label: str
    tier: VideoActionTier
    prompt: str
    loras: tuple[LoraRef, ...] = ()


# Human-readable tier headings for the grouped admin picker.
TIER_LABELS: dict[VideoActionTier, str] = {
    VideoActionTier.CHARM_IDLE: "Charm & Idle",
    VideoActionTier.PLAYFUL: "Playful",
    VideoActionTier.GLAMOUR: "Glamour",
    VideoActionTier.TEASE: "Tease",
    VideoActionTier.EXPLICIT: "Explicit",
}


def _reused(motion: MotionType, tier: VideoActionTier) -> VideoActionPreset:
    """Build a catalog preset from an existing MotionType + its MOTION_DESCRIPTIONS text."""
    return VideoActionPreset(
        id=motion.value,
        label=motion_label(motion),
        tier=tier,
        prompt=MOTION_DESCRIPTIONS[motion],
    )


# ---------------------------------------------------------------------------
# The catalog — grouped by tier (ascending intensity). Every prompt ends on a
# camera-facing beat, matching the register of MOTION_DESCRIPTIONS.
# ---------------------------------------------------------------------------
VIDEO_ACTION_CATALOG: List[VideoActionPreset] = [
    # --- charm_idle (8, all reused) ---
    _reused(MotionType.SUBTLE_IDLE, VideoActionTier.CHARM_IDLE),
    _reused(MotionType.GAZE_AND_SMILE, VideoActionTier.CHARM_IDLE),
    _reused(MotionType.NOD_AND_SMILE, VideoActionTier.CHARM_IDLE),
    _reused(MotionType.HEAD_TILT, VideoActionTier.CHARM_IDLE),
    _reused(MotionType.SLOW_TURN, VideoActionTier.CHARM_IDLE),
    _reused(MotionType.GLANCE_UP_THROUGH_LASHES, VideoActionTier.CHARM_IDLE),
    _reused(MotionType.HAIR_IN_WIND, VideoActionTier.CHARM_IDLE),
    _reused(MotionType.GENTLE_LAUGH, VideoActionTier.CHARM_IDLE),
    # --- playful (10, all reused) ---
    _reused(MotionType.WAVE, VideoActionTier.PLAYFUL),
    _reused(MotionType.WINK, VideoActionTier.PLAYFUL),
    _reused(MotionType.BLOW_KISS, VideoActionTier.PLAYFUL),
    _reused(MotionType.HAIR_FLIP, VideoActionTier.PLAYFUL),
    _reused(MotionType.PEACE_SIGN, VideoActionTier.PLAYFUL),
    _reused(MotionType.SHOULDER_SWAY, VideoActionTier.PLAYFUL),
    _reused(MotionType.TWIRL, VideoActionTier.PLAYFUL),
    _reused(MotionType.COME_HITHER, VideoActionTier.PLAYFUL),
    _reused(MotionType.ADJUST_HAIR, VideoActionTier.PLAYFUL),
    _reused(MotionType.WALK_TOWARD, VideoActionTier.PLAYFUL),
    # --- glamour (3 reused + 3 new) ---
    _reused(MotionType.SLOW_STRETCH, VideoActionTier.GLAMOUR),
    _reused(MotionType.LEAN_ON_HAND, VideoActionTier.GLAMOUR),
    _reused(MotionType.LOOK_OVER_SHOULDER, VideoActionTier.GLAMOUR),
    VideoActionPreset(
        id="hair_sweep_glam",
        label="Hair Sweep",
        tier=VideoActionTier.GLAMOUR,
        prompt="sweeping the hair to one side to bare the neck and shoulder, chin lifting, then a slow smoldering look to the camera",
    ),
    VideoActionPreset(
        id="slow_spin_reveal",
        label="Slow Spin Reveal",
        tier=VideoActionTier.GLAMOUR,
        prompt="a slow full turn that shows off the outfit, then arriving front-on with a confident look straight to the camera",
    ),
    VideoActionPreset(
        id="chin_lift_smoulder",
        label="Chin Lift",
        tier=VideoActionTier.GLAMOUR,
        prompt="lowering the chin, then lifting it slowly into a half-lidded, smoldering gaze right at the camera",
    ),
    # --- tease (3 reused + 4 new) ---
    _reused(MotionType.LIP_BITE, VideoActionTier.TEASE),
    _reused(MotionType.TOUCH_LIPS, VideoActionTier.TEASE),
    _reused(MotionType.BEND_TO_CAMERA, VideoActionTier.TEASE),
    VideoActionPreset(
        id="strap_slip_tease",
        label="Strap Slip",
        tier=VideoActionTier.TEASE,
        prompt="slowly slipping a thin strap down over one shoulder, eyes flicking up to the camera with a coy smile",
    ),
    VideoActionPreset(
        id="unbutton_tease",
        label="Unbutton",
        tier=VideoActionTier.TEASE,
        prompt="slowly undoing the top button, glancing down and then back up to the camera with a slow smile",
    ),
    VideoActionPreset(
        id="hip_sway_tease",
        label="Hip Sway",
        tier=VideoActionTier.TEASE,
        prompt="a slow hip sway with hands gliding down the waist, ending on a sultry look to the camera",
    ),
    VideoActionPreset(
        id="over_shoulder_strap",
        label="Over-Shoulder Strap",
        tier=VideoActionTier.TEASE,
        prompt="looking back over a bare shoulder while easing a strap down, then a smoldering glance to the camera",
    ),
    # --- explicit (5; single clean-licensed enhancer LoRA, high-chain only) ---
    VideoActionPreset(
        id="undress_reveal",
        label="Undress Reveal",
        tier=VideoActionTier.EXPLICIT,
        prompt="slowly drawing the top down to reveal the body, then a heated, inviting gaze to the camera",
        loras=(LoraRef("nsfw/nsfw_wan14b_e15.safetensors", 0.7, 0.0),),
    ),
    VideoActionPreset(
        id="body_run_hands",
        label="Hands Over Body",
        tier=VideoActionTier.EXPLICIT,
        prompt="gliding both hands slowly up the body, arching gently, ending on a heated look to the camera",
        loras=(LoraRef("nsfw/nsfw_wan14b_e15.safetensors", 0.6, 0.0),),
    ),
    VideoActionPreset(
        id="arch_and_gaze",
        label="Arch & Gaze",
        tier=VideoActionTier.EXPLICIT,
        prompt="arching the back slowly, chest forward, ending with a half-lidded gaze at the camera",
        loras=(LoraRef("nsfw/nsfw_wan14b_e15.safetensors", 0.55, 0.0),),
    ),
    VideoActionPreset(
        id="bend_over_look_back",
        label="Bend & Look Back",
        tier=VideoActionTier.EXPLICIT,
        prompt="bending forward and looking back over the shoulder at the camera with a sultry expression",
        loras=(LoraRef("nsfw/nsfw_wan14b_e15.safetensors", 0.6, 0.0),),
    ),
    VideoActionPreset(
        id="bounce_idle",
        label="Bounce Idle",
        tier=VideoActionTier.EXPLICIT,
        prompt="a slow relaxed shift of weight with natural body movement, settling into a sultry look to the camera",
        loras=(LoraRef("nsfw/nsfw_wan14b_e15.safetensors", 0.65, 0.0),),
    ),
]

# id -> preset lookup (ids are unique by construction; enforced by tests).
CATALOG_BY_ID: dict[str, VideoActionPreset] = {p.id: p for p in VIDEO_ACTION_CATALOG}

# Tier display order for the grouped picker.
_TIER_ORDER: tuple[VideoActionTier, ...] = (
    VideoActionTier.CHARM_IDLE,
    VideoActionTier.PLAYFUL,
    VideoActionTier.GLAMOUR,
    VideoActionTier.TEASE,
    VideoActionTier.EXPLICIT,
)


def get_preset(preset_id: str) -> Optional[VideoActionPreset]:
    """Look up a preset by id, or None if unknown."""
    return CATALOG_BY_ID.get(preset_id)


def catalog_grouped_by_tier() -> list[dict]:
    """The catalog grouped by tier for the admin picker.

    Returns ``[{"tier", "label", "presets": [{"id", "label", "tier"}, ...]}, ...]``
    in ascending-intensity tier order — the exact shape models.video_batch.
    ``VideoActionCatalogRead`` consumes.
    """
    groups: list[dict] = []
    for tier in _TIER_ORDER:
        presets = [
            {"id": p.id, "label": p.label, "tier": p.tier.value}
            for p in VIDEO_ACTION_CATALOG
            if p.tier == tier
        ]
        groups.append(
            {"tier": tier.value, "label": TIER_LABELS[tier], "presets": presets}
        )
    return groups
