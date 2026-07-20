"""
Pydantic models for per-character admin Video Batches.

An admin picks a character, picks N of its gallery stills, assigns each an action
(a preset from the tiered video action catalog, or a hand-written prompt), and
launches a batch. Each item animates one still into a short WAN 2.2 i2v clip.

Mirrors the shape of ``models/batch.py`` (Story Batches): a Create request with
per-item specs + batch defaults, Read/DetailRead aggregate views, an Estimate,
and a LaunchResponse. The per-item seed strategy reuses ``SeedStrategy`` from
``models/batch.py`` (imported, not redefined).
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .batch import SeedStrategy
from .requests import (
    VIDEO_ALLOWED_LENGTHS,
    VIDEO_ALLOWED_RESOLUTIONS,
)


class VideoQualityMode(str, Enum):
    """Render path for a batch / item."""
    FAST = "fast"   # lightning-distilled low-noise expert (~4-step, ~1.5-3 min/clip)
    MAX = "max"     # baseline undistilled two-expert graph (slower, max fidelity)


class VideoActionTier(str, Enum):
    """The five action-catalog tiers, ascending in intensity."""
    CHARM_IDLE = "charm_idle"
    PLAYFUL = "playful"
    GLAMOUR = "glamour"
    TEASE = "tease"
    EXPLICIT = "explicit"


# ---------------------------------------------------------------------------
# Batch defaults + per-item create specs.
# ---------------------------------------------------------------------------
class VideoBatchDefaults(BaseModel):
    """Batch-wide render defaults; each item may override a subset."""

    width: Optional[int] = Field(
        default=None,
        description=f"Clip width. Allowed pairs: {sorted(VIDEO_ALLOWED_RESOLUTIONS)}. None = server default.",
    )
    height: Optional[int] = Field(
        default=None,
        description=f"Clip height. Allowed pairs: {sorted(VIDEO_ALLOWED_RESOLUTIONS)}. None = server default.",
    )
    length: Optional[int] = Field(
        default=None,
        description=f"Frame count. Allowed: {sorted(VIDEO_ALLOWED_LENGTHS)}. None = server default.",
    )
    fps: Optional[int] = Field(
        default=None,
        ge=8,
        le=30,
        description="Frames per second. None = server default (16).",
    )
    seed_strategy: SeedStrategy = Field(
        default=SeedStrategy.PER_ITEM,
        description="How per-item seeds are derived (fixed / per_item / random).",
    )
    base_seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
        description="Base seed for fixed / per_item strategies (auto-filled if omitted).",
    )
    interpolate: bool = Field(
        default=False,
        description="Enable RIFE frame interpolation (2x frames, smoother playback).",
    )
    negative_prompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Extra negative-prompt terms folded into every item.",
    )

    @field_validator("length")
    @classmethod
    def _validate_length(cls, v):
        if v is not None and v not in VIDEO_ALLOWED_LENGTHS:
            raise ValueError(
                f"Unsupported length '{v}'. Allowed: {sorted(VIDEO_ALLOWED_LENGTHS)}"
            )
        return v

    @model_validator(mode="after")
    def _validate_resolution(self):
        # None/None -> server default. Otherwise both must be set and the
        # (width, height) pair must be one of the allowlisted resolutions.
        if self.width is None and self.height is None:
            return self
        pair = (self.width, self.height)
        if pair not in VIDEO_ALLOWED_RESOLUTIONS:
            raise ValueError(
                f"Unsupported resolution {pair}. Allowed: {sorted(VIDEO_ALLOWED_RESOLUTIONS)}"
            )
        return self


class VideoBatchItemCreate(BaseModel):
    """One item of a video batch: a still + exactly one action (preset XOR custom)."""

    source_image_id: str = Field(
        ...,
        description="character_images.id of the still to animate (must belong to the character).",
    )
    preset_id: Optional[str] = Field(
        default=None,
        description="Action-catalog preset id. Provide EITHER this or custom_prompt (not both).",
    )
    custom_prompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Hand-written motion, interpreted by the LLM at launch. XOR with preset_id.",
    )
    # Per-item overrides (None -> inherit the batch defaults).
    seed: Optional[int] = Field(default=None, ge=1, le=1_000_000_000)
    length: Optional[int] = Field(default=None)
    fps: Optional[int] = Field(default=None, ge=8, le=30)
    quality_mode: Optional[VideoQualityMode] = Field(
        default=None,
        description="Override the batch quality_mode for this item (fast / max).",
    )

    @field_validator("length")
    @classmethod
    def _validate_length(cls, v):
        if v is not None and v not in VIDEO_ALLOWED_LENGTHS:
            raise ValueError(
                f"Unsupported length '{v}'. Allowed: {sorted(VIDEO_ALLOWED_LENGTHS)}"
            )
        return v

    @model_validator(mode="after")
    def _exactly_one_action(self):
        has_preset = bool(self.preset_id and self.preset_id.strip())
        has_custom = bool(self.custom_prompt and self.custom_prompt.strip())
        if has_preset == has_custom:
            raise ValueError("provide exactly one of preset_id or custom_prompt")
        return self


class VideoBatchCreate(BaseModel):
    """Request body for POST /v1/characters/{id}/video-batches."""

    quality_mode: VideoQualityMode = Field(
        default=VideoQualityMode.FAST,
        description="Batch-wide render path; explicit-tier items always force fast (lightning).",
    )
    defaults: VideoBatchDefaults = Field(default_factory=VideoBatchDefaults)
    items: List[VideoBatchItemCreate] = Field(
        ..., min_length=1, max_length=50, description="1-50 items (one clip each)."
    )
    dry_run: bool = Field(
        default=False,
        description="Plan + resolve + persist items and return the estimate, but do NOT enqueue GPU jobs.",
    )


# ---------------------------------------------------------------------------
# Read views.
# ---------------------------------------------------------------------------
class VideoBatchItemRead(BaseModel):
    """One item (one still + one action + one child clip) of a video batch."""

    id: str
    item_index: int
    status: str
    source_image_id: str
    source_image_url: Optional[str] = None
    action_kind: str
    preset_id: Optional[str] = None
    custom_prompt: Optional[str] = None
    tier: Optional[str] = None
    motion_text: Optional[str] = None
    motion_label: Optional[str] = None
    quality_mode: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    length: Optional[int] = None
    fps: Optional[int] = None
    seed: Optional[int] = None
    attempts: int = 0
    runpod_status: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    video_url: Optional[str] = None
    preview_url: Optional[str] = None
    character_image_id: Optional[str] = Field(
        default=None,
        description="character_images row created for this item once it succeeded (publish guard).",
    )
    action_id: Optional[str] = Field(
        default=None,
        description="chat_persona_actions draft row created for this item (publish guard).",
    )


class VideoBatchRead(BaseModel):
    """Aggregate view of a video batch."""

    id: str
    character_id: str
    quality_mode: str
    defaults: dict = Field(default_factory=dict)
    status: str
    progress: float = 0.0
    items_total: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class VideoBatchDetailRead(VideoBatchRead):
    """Batch aggregate plus its items."""

    items: List[VideoBatchItemRead] = Field(default_factory=list)


class VideoBatchEstimate(BaseModel):
    """Cost/time preview returned when a batch is launched (one GPU job per item)."""

    items_total: int
    est_seconds_min: int
    est_seconds_max: int
    est_cost_usd: Optional[float] = None


class VideoBatchLaunchResponse(BaseModel):
    """Response for POST /v1/characters/{id}/video-batches."""

    batch: VideoBatchRead
    estimate: VideoBatchEstimate


class VideoBatchItemRerun(BaseModel):
    """POST body for re-running one item (optionally with a new action / seed)."""

    new_seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
        description="Explicit seed for the rerun. Ignored when reseed=True.",
    )
    reseed: bool = Field(
        default=False,
        description="Derive a fresh random seed for the rerun (overrides new_seed).",
    )
    preset_id: Optional[str] = Field(
        default=None,
        description="Change the action to this preset on rerun. XOR with custom_prompt; both None keeps the item's action.",
    )
    custom_prompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Change the action to this hand-written motion on rerun. XOR with preset_id.",
    )

    @model_validator(mode="after")
    def _at_most_one_action(self):
        has_preset = bool(self.preset_id and self.preset_id.strip())
        has_custom = bool(self.custom_prompt and self.custom_prompt.strip())
        if has_preset and has_custom:
            raise ValueError("provide at most one of preset_id or custom_prompt")
        return self


# ---------------------------------------------------------------------------
# Action-catalog response models (the admin action picker).
# ---------------------------------------------------------------------------
class VideoActionPresetRead(BaseModel):
    """One selectable action in the catalog."""

    id: str
    label: str
    tier: str


class VideoActionTierGroup(BaseModel):
    """A tier and its presets (for the grouped picker UI)."""

    tier: str
    label: str
    presets: List[VideoActionPresetRead] = Field(default_factory=list)


class VideoActionCatalogRead(BaseModel):
    """The full action catalog, grouped by tier."""

    tiers: List[VideoActionTierGroup] = Field(default_factory=list)
