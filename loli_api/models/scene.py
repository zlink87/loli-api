"""
SceneSpec — the contract between the story planner and the batch orchestrator.

A SceneSpec describes ONE planned image (one beat in a narrative arc). The planner
produces N of them; the orchestrator maps each onto a PipelineEditRequest that edits
the character's hero photo (pose -> outfit -> background).

HARD RULE: a SceneSpec describes ONLY scene attributes (pose/outfit/nudity/
background/mood). It carries NO persona identity fields (age/ethnicity/hair/eyes/
body/breasts). Identity is preserved by the edit pipeline's identity clauses and
negatives, never by this object.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from .enums import (
    PoseType,
    OutfitType,
    NudityLevel,
    AccessoryType,
    KinkType,
    PersonalityType,
    LocationType,
    TimeOfDayType,
    LightingType,
)


class SceneSpec(BaseModel):
    """One planned scene = one image job."""

    # --- narrative placement ---
    arc_id: str = Field(..., description="Stable id of the arc this beat belongs to, e.g. 'day_in_life'")
    arc_title: str = Field(..., description="Human-readable arc name, e.g. 'A day off at home'")
    beat_index: int = Field(..., ge=0, description="0-based index of this beat within its arc")
    global_index: int = Field(..., ge=0, description="0-based index across the whole batch (ordering)")
    beat_description: str = Field(
        ...,
        max_length=280,
        description="Short human-readable narrative caption for this scene",
    )

    # --- pipeline-driving scene attributes (all map to PipelineEditRequest) ---
    pose: Optional[PoseType] = Field(default=None, description="Pose step; None = skip pose step")
    outfit: Optional[OutfitType] = Field(default=None, description="Outfit step; None = skip outfit step")
    nudityLevel: NudityLevel = Field(default=NudityLevel.LOW, description="Nudity level for the outfit step")
    accessories: Optional[List[AccessoryType]] = Field(default=None, max_length=5)

    # --- structured background (composed into background free-text) ---
    location: LocationType = Field(..., description="Where the scene takes place")
    time_of_day: TimeOfDayType = Field(default=TimeOfDayType.DAYTIME)
    lighting: LightingType = Field(default=LightingType.NATURAL_SOFT)
    background_text: Optional[str] = Field(
        default=None,
        max_length=600,
        description=(
            "Fully-composed background free-text. If None, the orchestrator composes it "
            "from location/time_of_day/lighting via build_scene_background_text()."
        ),
    )

    # --- optional per-scene mood overrides (do NOT change identity) ---
    mood_kinks: Optional[List[KinkType]] = Field(
        default=None,
        max_length=3,
        description="Per-scene mood/atmosphere override, folded into background_text as mood phrases only",
    )
    mood_personality: Optional[PersonalityType] = Field(
        default=None,
        description="Per-scene expression override (e.g. a normally-shy character being playful once)",
    )

    # --- reproducibility / provenance ---
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
        description="Per-scene seed; set by the planner/orchestrator when a base seed is supplied",
    )

    model_config = {"use_enum_values": False}
