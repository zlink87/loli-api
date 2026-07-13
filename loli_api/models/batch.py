"""
Pydantic models for Story Batches — a batch of 20-50 images generated for one
Character by editing its hero photo across a planned sequence of scenes.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from .enums import (
    NudityLevel, OutfitType, PoseType, LocationType, PhotoStyleType,
    DemeanorType, InteriorStyleType, PaletteType,
)


class SeedStrategy(str, Enum):
    """How per-item seeds are derived for a batch."""
    FIXED = "fixed"        # one seed for every item (maximum visual consistency)
    PER_ITEM = "per_item"  # deterministic seed = base_seed + scene_index (reproducible variety)
    RANDOM = "random"      # each item random (worker picks; reported back for reproducibility)


class BatchControls(BaseModel):
    """Admin-facing knobs the planner + orchestrator honor for a batch."""

    max_nudity: NudityLevel = Field(
        default=NudityLevel.LOW,
        description=(
            "Hard ceiling; planner output is clamped so nudity never exceeds this, "
            "and the finish level of the nudity arc. "
            "Dressed-by-default: explicit batches are opt-in via medium/high."
        ),
    )
    start_nudity: Optional[NudityLevel] = Field(
        default=None,
        description=(
            "Nudity of photo 1; ramps up to max_nudity (the finish + ceiling). "
            "None = derive from escalation: building -> low, flat -> max_nudity."
        ),
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
    outfit_denoise: Optional[float] = Field(
        default=None,
        ge=0.5,
        le=0.95,
        description=(
            "Outfit-step denoise for the crop-stitch edit (0.5-0.95); None = engine default (~0.80). "
            "Higher = the new garment overrides the source clothing more strongly."
        ),
    )
    outfit_prompt_mode: str = Field(
        default="replace",
        description=(
            "'replace' (DEFAULT for batches: explicitly remove the current clothing first, "
            "then describe the new outfit) | 'standard' (append the outfit description only). "
            "Batch source avatars are dressed-by-default, so removal must be explicit or the "
            "swap tends to reconstruct the original garment. The admin UI should align its "
            "default to 'replace' (or omit the field so this backend default applies). "
            "NOTE: when the character has an active nude base, the mapper automatically "
            "overrides this to 'dress' (additive dress-onto-bare-body) for garment scenes — "
            "'replace' on a nude source is incoherent (there is no current clothing to remove)."
        ),
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
    period_days: int = Field(
        default=1, ge=1, le=7,
        description=("Days the story spans. 1 = a single wake->sleep day; N = N day-cycles "
                     "with varied activities. time_of_day is curated across the whole span."),
    )
    pipeline_order: Optional[List[str]] = Field(
        default=None, description="Override pipeline step order forwarded to each item"
    )
    photo_style: PhotoStyleType = Field(
        default=PhotoStyleType.POLISHED,
        description=(
            "Photographic finish applied once (final edit step) to every item: "
            "polished (retouched, default — matches the generated hero), natural "
            "(realistic/unstaged), studio, or candid_phone (legacy raw look)"
        ),
    )
    story_mode: bool = Field(
        default=False,
        description=(
            "RETIRED from the admin flow. Batches always run variety mode now: the "
            "deterministic planner (or opt-in Venice per-beat garnish) picks coherent, "
            "correctly-ramped scenes from the batch controls alone, with no narrative arc. "
            "This field is still accepted for API/back-compat with old admin payloads, but "
            "it is IGNORED — BatchLaunchService forces story_mode=False before planning, so a "
            "stale payload can never re-enable the old story-director path. Default is False."
        ),
    )
    reactor_restore_visibility: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Pose-step ReActor face-restore knob (node 200 face_restore_visibility, "
            "0.0-1.0). None = template default (~0.8). Pose-step ReActor face-restore "
            "knobs — lower codeformer weight = less 'beautification' drift between items."
        ),
    )
    reactor_codeformer_weight: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Pose-step ReActor face-restore knob (node 200 codeformer_weight, "
            "0.0-1.0). None = template default (~0.25). Pose-step ReActor face-restore "
            "knobs — lower codeformer weight = less 'beautification' drift between items."
        ),
    )

    # --- Character trait-profile bias (WS-B Phase B2) ---------------------------
    # These are a SOFT bias, normally profile-DERIVED at launch by
    # services.trait_profile_merge.apply_trait_profile (from the character's saved
    # TraitProfile) — the admin rarely sets them by hand. When the admin DOES set one
    # explicitly, the explicit value WINS (the merge is fill-only for these). None means
    # "no bias" and keeps the planner byte-identical to its pre-trait-profile behavior.
    wardrobe_outfits: Optional[List[OutfitType]] = Field(
        default=None,
        description=(
            "Soft wardrobe bias: outfits that fit the character's style. The planner "
            "intersects each beat's pool with this set (keeping uniforms), using the "
            "subset only when >=2 survive so variety is preserved (never a hard filter). "
            "Normally profile-derived at launch; explicit admin values win."
        ),
    )
    favored_outfits: Optional[List[OutfitType]] = Field(
        default=None,
        description=(
            "Soft favourite-outfit bias (her favorite_outfits minus blocks): weighted up "
            "(~3x) in outfit picks. Profile-derived at launch; explicit admin values win."
        ),
    )
    favored_locations: Optional[List[LocationType]] = Field(
        default=None,
        description=(
            "Soft favourite-location bias: weighted up (~3x) in location picks. "
            "Profile-derived at launch; explicit admin values win."
        ),
    )
    demeanor: Optional[List[DemeanorType]] = Field(
        default=None,
        description=(
            "The character's default demeanor(s): biases per-item expression toward "
            "demeanor-consistent states and favours matching poses. Profile-derived at "
            "launch; explicit admin values win."
        ),
    )
    interior_style: Optional[InteriorStyleType] = Field(
        default=None,
        description=(
            "Home interior style: gives the character a consistent, styled room for "
            "home/hotel scenes. Profile-derived at launch; explicit admin value wins."
        ),
    )
    color_palette: Optional[PaletteType] = Field(
        default=None,
        description=(
            "Color palette: a short color/light clause folded into scene backgrounds. "
            "Profile-derived at launch; explicit admin value wins."
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
    use_trait_profile: bool = Field(
        default=True,
        description=(
            "When True (default) and the character has a saved trait profile, the "
            "orchestrator folds that profile's wardrobe/demeanor/home-scenery/likes bias "
            "into the batch controls at launch (best-effort; explicit admin values win, "
            "nudity controls are never touched). Set False to launch a batch that ignores "
            "the character's trait profile entirely."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "count": 24,
                "controls": {
                    "max_nudity": "medium",
                    "start_nudity": "low",
                    "content_rating": "nsfw",
                    "escalation": "building",
                    "arc_count": 4,
                    "period_days": 1,
                    "seed_strategy": "per_item",
                    "base_seed": 42,
                    "photo_style": "polished",
                },
                "likes": ["coffee", "rainy days", "silk"],
                "dislikes": ["gyms", "neon clubs"],
                "dry_run": False,
            }
        }


class BatchItemEdit(BaseModel):
    """
    PATCH body for a single batch item's scene (Phase 3).

    All fields are optional; only the keys actually present in the request payload
    are applied onto the stored ``scene_spec`` (use ``model_dump(exclude_unset=True)``
    to read them). Enum fields are accepted as raw strings and coerced through the
    SAME ``_coerce_enum`` + controls filters the planner uses (story_planner.
    apply_item_scene_edit), so near-miss values are repaired and an edit can never
    bypass the batch's allow/block lists, ``sfw_only``, or the ``max_nudity`` ceiling.
    Free-text detail fields get the planner's identity scrub, companion strip, and
    length caps. Passing ``null`` for the nullable steps (``outfit``/``pose``) clears
    that step.
    """

    outfit: Optional[str] = Field(default=None, description="Outfit enum; null clears the outfit step")
    location: Optional[str] = None
    pose: Optional[str] = Field(default=None, description="Pose enum; null clears the pose step")
    nudity_level: Optional[str] = Field(default=None, description="Nudity level (capped at the batch max_nudity)")
    time_of_day: Optional[str] = None
    lighting: Optional[str] = None
    setting: Optional[str] = None
    activity: Optional[str] = None
    pose_detail: Optional[str] = None
    outfit_detail: Optional[str] = None
    expression: Optional[str] = None


class BatchItemRerun(BaseModel):
    """POST body for re-running one succeeded/failed batch item (Phase 3)."""

    new_seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
        description="Explicit seed for the rerun. Ignored when reseed=True.",
    )
    reseed: bool = Field(
        default=False,
        description=(
            "Derive a fresh random seed for the rerun (overrides new_seed). "
            "Default False keeps the item's stored deterministic seed."
        ),
    )


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
    planner_provider: Optional[str] = Field(
        default=None,
        description=(
            "Which planner actually produced this batch's scenes ('deterministic' | "
            "'venice' | ...), read back from controls._planner_provider (set once at "
            "launch by BatchStore.set_planner_provider). Surfaced as a top-level field "
            "rather than through BatchControls because pydantic's extra='ignore' would "
            "silently drop the underscore-prefixed key when BatchControls is "
            "reconstructed from the row. None for batches launched before this field "
            "existed."
        ),
    )


# ---------------------------------------------------------------------------
# Story view (Feature 2) — derived at read time from the items' scene_spec jsonb.
# No new storage: story_title + per-beat narrative already ride in scene_spec.
# ---------------------------------------------------------------------------
class StoryBeat(BaseModel):
    scene_index: int
    narrative: Optional[str] = None
    beat_description: Optional[str] = None
    image_url: Optional[str] = None


class StoryChapter(BaseModel):
    arc_id: str
    arc_title: str
    beats: List[StoryBeat] = Field(default_factory=list)


class BatchStory(BaseModel):
    title: Optional[str] = None
    chapters: List[StoryChapter] = Field(default_factory=list)


def assemble_story(items: List[BatchItemRead]) -> Optional["BatchStory"]:
    """Reconstruct the story from items' scene_spec. Returns None for non-story batches."""
    if not items:
        return None
    ordered = sorted(items, key=lambda it: it.scene_index)
    if not any(
        (it.scene_spec or {}).get("narrative") or (it.scene_spec or {}).get("story_title")
        for it in ordered
    ):
        return None

    title: Optional[str] = None
    chapters: List[StoryChapter] = []
    current: Optional[StoryChapter] = None
    for it in ordered:
        spec = it.scene_spec or {}
        if title is None and spec.get("story_title"):
            title = spec.get("story_title")
        arc_id = str(spec.get("arc_id") or "arc")
        arc_title = str(spec.get("arc_title") or "Chapter")
        if current is None or current.arc_id != arc_id:
            current = StoryChapter(arc_id=arc_id, arc_title=arc_title, beats=[])
            chapters.append(current)
        current.beats.append(
            StoryBeat(
                scene_index=it.scene_index,
                narrative=spec.get("narrative"),
                beat_description=spec.get("beat_description"),
                image_url=it.image_url,
            )
        )
    return BatchStory(title=title, chapters=chapters)


class BatchDetailRead(BatchRead):
    """Batch aggregate plus its items (and, in story mode, the derived story)."""

    items: List[BatchItemRead] = Field(default_factory=list)
    story: Optional[BatchStory] = None


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
