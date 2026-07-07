"""
Pydantic models for Story Batches — a batch of 20-50 images generated for one
Character by editing its hero photo across a planned sequence of scenes.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from .enums import NudityLevel, OutfitType, PoseType, LocationType, PhotoStyleType


class SeedStrategy(str, Enum):
    """How per-item seeds are derived for a batch."""
    FIXED = "fixed"        # one seed for every item (maximum visual consistency)
    PER_ITEM = "per_item"  # deterministic seed = base_seed + scene_index (reproducible variety)
    RANDOM = "random"      # each item random (worker picks; reported back for reproducibility)


class BatchControls(BaseModel):
    """Admin-facing knobs the planner + orchestrator honor for a batch."""

    max_nudity: NudityLevel = Field(
        default=NudityLevel.MEDIUM,
        description="Hard ceiling; planner output is clamped so nudity never exceeds this",
    )
    sfw_only: bool = Field(default=False, description="Force nudity=LOW and drop the 'naked' outfit")
    content_rating: str = Field(
        default="nsfw",
        description="'sfw' | 'nsfw' — gates the Claude planner out of NSFW batches",
    )
    escalation: str = Field(
        default="building",
        description="'flat' (roughly constant) | 'building' (nudity rises across the batch)",
    )
    allowed_outfits: Optional[List[OutfitType]] = Field(
        default=None, description="Allowlist; None = all outfits permitted"
    )
    blocked_outfits: List[OutfitType] = Field(
        default_factory=lambda: [OutfitType.NAKED],
        description="Blocklist (wins over allowlist); defaults to blocking 'naked'",
    )
    blocked_poses: List[PoseType] = Field(default_factory=list)
    allowed_locations: Optional[List[LocationType]] = None
    blocked_locations: List[LocationType] = Field(default_factory=list)
    seed_strategy: SeedStrategy = SeedStrategy.PER_ITEM
    base_seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
        description="Base seed; used by FIXED/PER_ITEM strategies (auto-filled if omitted)",
    )
    arc_count: Optional[int] = Field(
        default=None, ge=1, le=8, description="Number of narrative arcs; None = auto from count"
    )
    pipeline_order: Optional[List[str]] = Field(
        default=None, description="Override pipeline step order forwarded to each item"
    )
    photo_style: PhotoStyleType = Field(
        default=PhotoStyleType.POLISHED,
        description=(
            "Photographic finish applied to every edit step of every item: "
            "polished (retouched editorial), studio, or candid_phone (legacy raw look)"
        ),
    )


class BatchCreate(BaseModel):
    """Request body for POST /v1/characters/{id}/batches."""

    count: int = Field(..., ge=1, le=50, description="Number of images to generate (1-50)")
    controls: BatchControls = Field(default_factory=BatchControls)
    likes: List[str] = Field(
        default_factory=list,
        description="Free-text likes; bias planned scenes toward these (generation-only, not stored on the character)",
    )
    dislikes: List[str] = Field(
        default_factory=list,
        description="Free-text dislikes; soft-excluded from planned scenes",
    )
    dry_run: bool = Field(
        default=False,
        description="Plan + map + persist items and return the estimate, but do NOT enqueue GPU jobs",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "count": 24,
                "controls": {
                    "max_nudity": "medium",
                    "content_rating": "nsfw",
                    "escalation": "building",
                    "arc_count": 4,
                    "seed_strategy": "per_item",
                    "base_seed": 42,
                    "photo_style": "polished",
                },
                "likes": ["coffee", "rainy days", "silk"],
                "dislikes": ["gyms", "neon clubs"],
                "dry_run": False,
            }
        }


class BatchItemRead(BaseModel):
    """One item (one planned scene / one child job) of a batch."""

    id: str
    scene_index: int
    status: str
    scene_spec: dict
    job_id: Optional[str] = None
    preview_url: Optional[str] = None
    image_url: Optional[str] = None
    image_hash: Optional[str] = None
    seed: Optional[int] = None
    arc: Optional[str] = None
    beat: Optional[int] = None
    attempts: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    character_image_id: Optional[str] = Field(
        default=None,
        description="character_images row created for this item once it succeeded",
    )


class BatchRead(BaseModel):
    """Aggregate view of a batch."""

    id: str
    character_id: str
    count: int
    controls: BatchControls
    likes: List[str] = Field(default_factory=list)
    dislikes: List[str] = Field(default_factory=list)
    status: str
    progress: float = 0.0
    items_total: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class BatchDetailRead(BatchRead):
    """Batch aggregate plus its items."""

    items: List[BatchItemRead] = Field(default_factory=list)


class BatchEstimate(BaseModel):
    """Cost/time preview returned immediately when a batch is launched."""

    items_total: int
    est_runpod_jobs: int = Field(..., description="Sum of active pipeline steps across all items")
    est_seconds_min: int
    est_seconds_max: int
    est_cost_usd: Optional[float] = None


class BatchLaunchResponse(BaseModel):
    """Response for POST /v1/characters/{id}/batches."""

    batch: BatchRead
    estimate: BatchEstimate
    provider: Optional[str] = Field(default=None, description="Planner provider used")
