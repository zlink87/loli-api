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

    # --- render-safe story channel (identity-free; DOES reach the image prompt) ---
    # Unlike `narrative` (gallery-only, below), `setting` and `activity` are folded
    # into the background prompt by scene_mapper so the AI-authored day actually drives
    # what each photo shows. They are scrubbed of identity tokens by the planner and
    # gated by has_banned_style_words in the mapper, so they describe place/action only.
    setting: Optional[str] = Field(
        default=None,
        max_length=400,
        description="Identity-free one-sentence environment description; folded into the background prompt",
    )
    activity: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Identity-free short action phrase (what she is doing); folded into the background prompt",
    )
    pose_detail: Optional[str] = Field(
        default=None,
        max_length=200,
        description=(
            "Identity-free body-position/action sentence (e.g. 'curled up on the sofa, mug "
            "in both hands, knees tucked'); REPLACES the pose enum's canned description in "
            "the pose step's target-pose text. The `pose` enum still selects the reference "
            "image. Body position ONLY — no other people, never facial features. Defaults "
            "None (legacy jsonb without this key parses back to enum-description prose)."
        ),
    )
    staging: Optional[str] = Field(
        default=None,
        max_length=160,
        description=(
            "Scenery-anchored staging fragment naming the concrete surface/furniture the "
            "pose sits/stands/lies on for THIS (location, pose-class) — e.g. 'perched on a "
            "bar stool at the counter' for a sitting pose at a nightclub. Assigned "
            "deterministically by the planner (validate_and_repair) AFTER pose/location "
            "repairs settle, from scene_vocab.STAGING_PHRASES, so the full-frame pose "
            "re-diffusion never improvises an absurd seat. Scenery ONLY — never identity/"
            "clothing/nudity. Folded into the background scene text (after the location "
            "phrase) and the pose step's target-pose sentence. Defaults None (legacy jsonb "
            "without this key parses back to no staging; a pose-class with no phrase pool "
            "at its location stays None — a clean skip)."
        ),
    )
    outfit_detail: Optional[str] = Field(
        default=None,
        max_length=160,
        description=(
            "Identity-free concrete garment description (colors/fabric/fit) matching outfit + "
            "nudityLevel; sharpens the outfit step. Clothing ONLY — never facial features."
        ),
    )
    outfit_detail_dominant: bool = Field(
        default=False,
        description=(
            "When True the outfit step renders `outfit_detail` ALONE — the `outfit` enum's "
            "tier prose is skipped, and the enum only gates the step + carries the nudity ramp. "
            "Set by the planner when a director caption had no confident enum mapping or "
            "conflicted with the enum, so the gallery card caption and the render agree. "
            "Defaults False (legacy jsonb without this key parses back to enum-driven prose)."
        ),
    )
    expression: Optional[str] = Field(
        default=None,
        max_length=80,
        description=(
            "Facial expression/mood for this photo (e.g. 'soft sleepy smile'), routed to the pose "
            "step. Expression/mood ONLY — never facial features (eyes, lips, face shape)."
        ),
    )
    scene_direction: Optional[str] = Field(
        default=None,
        max_length=340,
        description=(
            "Venice-authored photographic staging for THIS photo (1-3 sentences): the concrete "
            "furniture/objects, where in the space she is, and the camera feel — HOW IT LOOKS, "
            "on top of the deterministically-decided WHAT (outfit/pose/location/nudity/time). "
            "Populated AFTER validate_and_repair from the FINAL scene facts (services."
            "scene_direction.apply_scene_directions), hard-validated to carry NO identity/"
            "appearance, no clothing outside the item's outfit, no foreign-location tokens, no "
            "interacting people (anonymous background only at public venues), and no narrative. "
            "When present the scene mapper uses it INSTEAD of the bare `staging` phrase in the "
            "composed scene text. None (deterministic provider / a per-item validation fallback / "
            "legacy jsonb without this key) -> the mapper falls back to `staging` unchanged."
        ),
    )
    direction_source: Optional[str] = Field(
        default=None,
        description=(
            "Provenance of scene_direction: 'venice' (LLM wrote + passed validation), 'fallback' "
            "(Venice was attempted but this item failed validation or the whole call errored/timed "
            "out -> kept its staging phrase), or None (the deterministic provider skipped Venice "
            "entirely / legacy jsonb). Denormalized for after-the-fact visibility, like the batch's "
            "planner_provider."
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

    # --- story narrative (Feature 2) ---
    # Additive, purely for surfacing (gallery/chat). NEVER fed into the image prompt —
    # scene_mapper reads only beat_description + the render-safe setting/activity above,
    # never this free prose — so it cannot leak identity/style into a render or bloat tokens.
    narrative: Optional[str] = Field(
        default=None,
        max_length=700,
        description="Per-beat story prose for this photo; excluded from the render prompt",
    )
    story_title: Optional[str] = Field(
        default=None,
        max_length=160,
        description="Batch-level story title, denormalized onto every beat",
    )

    model_config = {"use_enum_values": False}
