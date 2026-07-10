"""
Pydantic request models for the Character Image Generation API.
Based on BE-AI-Tasks.docx PersonaOptions specification.
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List

from services.url_guard import validate_source_image, SourceImageError

from services.output_presets import ASPECT_RATIO_DIMS, ALLOWED_RESOLUTIONS

from .enums import (
    StyleType,
    EthnicityType,
    HairStyleType,
    HairColorType,
    EyeColorType,
    BodyType,
    BreastSize,
    PersonalityType,
    RelationshipType,
    OccupationType,
    KinkType,
    OutfitType,
    AccessoryType,
    NudityLevel,
    PoseType,
    MotionType,
    ShotFramingType,
    CameraAngleType,
    ExpressionType,
    PhotoStyleType,
    TimeOfDayType,
    LightingType,
)


class PersonaOptions(BaseModel):
    """
    Character persona configuration for prompt generation.
    All fields based on BE-AI-Tasks.docx specification.
    """

    # Required fields
    style: StyleType = Field(
        default=StyleType.REALISTIC,
        description="Visual style: realistic or anime"
    )
    ethnicity: EthnicityType = Field(
        ...,
        description="Character ethnicity"
    )
    age: int = Field(
        ...,
        ge=18,
        le=99,
        description="Character age (18-99)"
    )
    hairStyle: HairStyleType = Field(
        ...,
        description="Hair style"
    )
    hairColor: HairColorType = Field(
        ...,
        description="Hair color"
    )
    eyeColor: EyeColorType = Field(
        ...,
        description="Eye/iris color"
    )
    bodyType: BodyType = Field(
        default=BodyType.AVERAGE,
        description="Body type"
    )
    breastSize: BreastSize = Field(
        default=BreastSize.MEDIUM,
        description="Breast size"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Character name"
    )

    # Optional fields
    personality: Optional[PersonalityType] = Field(
        default=None,
        description="Character personality type"
    )
    relationship: Optional[RelationshipType] = Field(
        default=None,
        description="Relationship context"
    )
    occupation: Optional[OccupationType] = Field(
        default=None,
        description="Character occupation"
    )
    kinks: Optional[List[KinkType]] = Field(
        default=None,
        max_length=3,
        description="Special attributes (max 3)"
    )
    voice: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Voice identifier (e.g., voice_4)"
    )

    @field_validator("kinks")
    @classmethod
    def validate_kinks_max_length(cls, v):
        """Ensure max 3 kinks are selected."""
        if v and len(v) > 3:
            raise ValueError("Maximum 3 kinks allowed")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "style": "realistic",
                "ethnicity": "asian",
                "age": 25,
                "hairStyle": "ponytail",
                "hairColor": "black",
                "eyeColor": "brown",
                "bodyType": "average",
                "breastSize": "medium",
                "name": "Sakura",
                "personality": "shy",
                "relationship": "stranger",
                "occupation": "student",
                "kinks": ["shy_flirting", "cuddling"],
                "voice": "voice_1"
            }
        }


class OutputOptions(BaseModel):
    """Output configuration for image generation."""

    aspectRatio: Optional[str] = Field(
        default="2:3",
        description=f"Aspect ratio preset. Allowed: {', '.join(sorted(ASPECT_RATIO_DIMS))}"
    )
    resolution: Optional[str] = Field(
        default=None,
        description=(
            "Explicit whitelisted resolution (wins over aspectRatio). "
            f"Allowed: {', '.join(sorted(ALLOWED_RESOLUTIONS))}"
        )
    )
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed for reproducibility"
    )
    n: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Number of images (accepted for compatibility but currently clamped to 1)"
    )
    hires: Optional[bool] = Field(
        default=None,
        description=(
            "Run a second detail-refine pass (upscale-model round trip + refine steps). "
            "Output resolution is unchanged; adds roughly 50-100% GPU time. "
            "None = server default (GENERATION_HIRES_DEFAULT)."
        )
    )

    @field_validator("aspectRatio")
    @classmethod
    def validate_aspect_ratio(cls, v):
        if v is not None and v not in ASPECT_RATIO_DIMS:
            raise ValueError(
                f"Unsupported aspectRatio '{v}'. Allowed: {', '.join(sorted(ASPECT_RATIO_DIMS))}"
            )
        return v

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, v):
        if v is not None and v not in ALLOWED_RESOLUTIONS:
            raise ValueError(
                f"Unsupported resolution '{v}'. Allowed: {', '.join(sorted(ALLOWED_RESOLUTIONS))}"
            )
        return v


class ShotOptions(BaseModel):
    """
    Camera/framing configuration for the hero shot. All fields optional with
    hero defaults (waist-up, eye level, polished finish) so persona-only
    requests produce consistent Candy.ai-style character cards.
    """

    framing: ShotFramingType = Field(
        default=ShotFramingType.WAIST_UP,
        description="How much of the subject is in frame"
    )
    angle: CameraAngleType = Field(
        default=CameraAngleType.EYE_LEVEL,
        description="Camera position relative to the subject"
    )
    expression: Optional[ExpressionType] = Field(
        default=None,
        description="Explicit expression override. None = derive from persona.personality, "
                    "or a soft smile when no personality is set"
    )
    photoStyle: PhotoStyleType = Field(
        default=PhotoStyleType.POLISHED,
        description="Photographic finish: polished (retouched editorial), studio, or candid_phone (legacy raw look)"
    )
    timeOfDay: Optional[TimeOfDayType] = Field(
        default=None,
        description=(
            "Time of day for the scene (early_morning/morning/daytime/golden_hour/"
            "sunset/evening/night). Enforced: the phrase becomes a verified prompt "
            "token AND the photo-style wrapper adapts its lighting/grade to match "
            "(night stays polished low-key instead of fighting the daylight grade). "
            "None = the default bright editorial look."
        ),
    )
    lighting: Optional[LightingType] = Field(
        default=None,
        description=(
            "Optional lighting flavor (e.g. neon, candlelit, moody_dim, "
            "studio_softbox); appended to the shot block"
        ),
    )


class ProviderHints(BaseModel):
    """Optional hints for provider/model selection."""

    model: Optional[str] = Field(
        default=None,
        description="Specific model to use"
    )
    provider: Optional[str] = Field(
        default=None,
        description="Specific provider to use"
    )


class GenerateImageRequest(BaseModel):
    """
    Request body for POST /v1/generate/image.
    Creates a character image from PersonaOptions.

    Only `persona` is required. The workflow uses default settings
    for dimensions, steps, etc.
    """

    id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional client-provided ID for tracking purposes"
    )
    persona: PersonaOptions = Field(
        ...,
        description="Character persona configuration (REQUIRED)"
    )
    context: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional scene hint (e.g., 'After a long shift, relaxing at home'), "
                    "used verbatim in the assembled prompt."
    )
    outfit: Optional[OutfitType] = Field(
        default=None,
        description="Outfit to generate the character in. None -> a neutral outfit "
                    "at the chosen nudityLevel (clothed by default)."
    )
    nudityLevel: NudityLevel = Field(
        default=NudityLevel.LOW,
        description="Nudity level for generation: low (fully clothed), medium "
                    "(partial exposure), high (nude). Drives both the clothing "
                    "clause and the nudity-suppression negative."
    )
    accessories: Optional[List[AccessoryType]] = Field(
        default=None,
        max_length=5,
        description="List of accessories to add (max 5)"
    )
    output: Optional[OutputOptions] = Field(
        default=None,
        description="Output configuration (aspect ratio / resolution / seed / hires)"
    )
    shot: Optional[ShotOptions] = Field(
        default=None,
        description="Camera/framing configuration. None = hero defaults "
                    "(waist-up, eye level, polished finish)"
    )
    providerHints: Optional[ProviderHints] = Field(
        default=None,
        description="Optional provider/model hints"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "client-request-001",
                "persona": {
                    "style": "realistic",
                    "ethnicity": "asian",
                    "age": 28,
                    "hairStyle": "ponytail",
                    "hairColor": "black",
                    "eyeColor": "green",
                    "bodyType": "average",
                    "breastSize": "medium",
                    "name": "Estella",
                    "personality": "shy",
                    "occupation": "nurse"
                },
                "context": "After a long shift, relaxing at home",
                "shot": {
                    "framing": "waist_up",
                    "angle": "eye_level",
                    "photoStyle": "polished"
                },
                "output": {"aspectRatio": "2:3", "hires": True}
            }
        }


class BatchGenerateRequest(BaseModel):
    """
    Request body for POST /v1/generate/batch (Batch Character Creation, admin-only).

    A list of independent character photos to dispatch, where each item is the exact
    `GenerateImageRequest` the single `POST /v1/generate/image` form already builds
    (reused verbatim — no new item fields). There is NO maximum item count; concurrency
    is bounded server-side by a dedicated worker pool on an isolated queue. If ANY item
    fails Pydantic validation the whole request returns 422 and nothing is enqueued.
    """

    items: List[GenerateImageRequest] = Field(
        ...,
        description="Character photos to dispatch; each is a full GenerateImageRequest.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "items": [
                    {
                        "id": "draft-a1",
                        "persona": {
                            "ethnicity": "asian", "age": 26, "hairStyle": "ponytail",
                            "hairColor": "black", "eyeColor": "brown", "name": "Sakura",
                        },
                        "context": "after a long shift, relaxing at home",
                    }
                ]
            }
        }


class SceneRandomizeRequest(BaseModel):
    """
    Request body for POST /v1/scenes/randomize (Batch Character Creation, admin-only).

    Both inputs optional. `persona` themes the generated scene to her occupation /
    personality / relationship; `hint` is a free-text seed. Stateless — nothing stored.
    """

    persona: Optional[PersonaOptions] = Field(
        default=None,
        description="Optional persona to theme the scene (occupation/personality/relationship).",
    )
    hint: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional free-text scene seed (e.g. 'somewhere cosy at night').",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "persona": {
                    "ethnicity": "caucasian", "age": 28, "hairStyle": "straight",
                    "hairColor": "blonde", "eyeColor": "green", "name": "Estella",
                    "occupation": "nurse", "personality": "shy",
                },
                "hint": "somewhere cosy at night",
            }
        }


class OutfitEditRequest(BaseModel):
    """Request body for POST /v1/edit/outfit."""

    source_image: str = Field(
        ...,
        description="Supabase URL of the source image to edit"
    )
    outfit: OutfitType = Field(
        ...,
        description="Type of outfit to apply"
    )
    nudityLevel: NudityLevel = Field(
        default=NudityLevel.LOW,
        description="Nudity level: low (suggestive/clothed), medium (partial nudity), high (nude)"
    )
    accessories: Optional[List[AccessoryType]] = Field(
        default=None,
        max_length=5,
        description="List of accessories to add (max 5)"
    )
    negativePrompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Extra negative prompt terms for the outfit edit"
    )
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed for reproducibility"
    )
    sourceDressed: bool = Field(
        default=False,
        description=(
            "Set true when the SOURCE image already shows clothing. Enables the tight "
            "GARMENT mask (edit only the existing clothing) for supported outfit types, "
            "which keeps far more fine detail (sequins, lace) and avoids re-diffusing "
            "the body/anatomy. Leave false for a nude/unclothed source — a garment mask "
            "would find nothing to segment, so the whole-body mask is used instead."
        )
    )

    @field_validator("source_image")
    @classmethod
    def validate_source_image_url(cls, v):
        try:
            return validate_source_image(v)
        except SourceImageError as e:
            raise ValueError(str(e))

    class Config:
        json_schema_extra = {
            "example": {
                "source_image": "https://xxx.supabase.co/storage/v1/object/public/images/test.png",
                "outfit": "red_evening_gown",
                "nudityLevel": "low",
                "accessories": ["necklace", "earrings"],
                "seed": 12345
            }
        }


class PoseEditRequest(BaseModel):
    """Request body for POST /v1/edit/pose."""

    source_image: str = Field(
        ...,
        description="Supabase URL of the source character image"
    )
    pose: PoseType = Field(
        ...,
        description="Target pose to apply"
    )
    negativePrompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description=(
            "Accepted for request-shape parity with the other edit endpoints but "
            "IGNORED: the pose workflow runs at cfg=1 with a zeroed negative "
            "conditioning branch (ConditioningZeroOut), so negative text is "
            "mathematically inert. See pose.py."
        )
    )
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed for reproducibility"
    )

    @field_validator("source_image")
    @classmethod
    def validate_source_image_url(cls, v):
        try:
            return validate_source_image(v)
        except SourceImageError as e:
            raise ValueError(str(e))

    class Config:
        json_schema_extra = {
            "example": {
                "source_image": "https://xxx.supabase.co/storage/v1/object/public/images/test.png",
                "pose": "sitting_casual",
                "seed": 12345
            }
        }


# Whitelisted frame counts for WAN i2v (must be 4n+1). 81 ≈ 5s @ 16fps.
VIDEO_ALLOWED_LENGTHS = {49, 81}
# Whitelisted (width, height) portrait resolutions a caller may opt into.
# 720x1280 is the WAN 2.2 14B native tier; it can become the default once the
# RunPod worker GPU tier is confirmed to not OOM (video worker has max_oom_attempts=1).
VIDEO_ALLOWED_RESOLUTIONS = {(480, 832), (576, 1024), (720, 1280)}
# Vertical reel defaults (portrait 9:16-ish); WAN is trained at 16fps.
# NOTE: 480x832 kept as the shipped default (safe for the current RunPod tier).
# Bump to 720x1280 (native 14B tier, sharper push-in) only after confirming the
# worker GPU tier tolerates it without OOM.
VIDEO_DEFAULT_WIDTH = 480
VIDEO_DEFAULT_HEIGHT = 832
VIDEO_DEFAULT_LENGTH = 81
VIDEO_DEFAULT_FPS = 16


class VideoGenerateRequest(BaseModel):
    """
    Request body for POST /v1/characters/{character_id}/videos (admin).

    The client sends ``source_image_id`` (a character_images.id) + a motion
    preset. The endpoint resolves the still to a URL and fills ``character_id``
    (from the path) and ``source_image`` (the resolved URL) server-side before
    the job is enqueued; those two are not part of the client contract.
    """

    source_image_id: str = Field(
        ...,
        description="character_images.id of the still to animate (must belong to the character)",
    )
    motion: MotionType = Field(
        ...,
        description="Motion preset for the clip",
    )
    motionPrompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional free-text motion. When set, it is interpreted by the LLM and replaces the preset.",
    )
    useFlf2v: bool = Field(
        default=False,
        description=(
            "Opt in to the first-last-frame (FLF2V) path: the clip resolves on a "
            "controlled, in-focus end frame. Only takes effect when the server also "
            "has COMFYUI_VIDEO_FLF2V_WORKFLOW_PATH configured; otherwise the normal "
            "i2v path is used. OFF by default."
        ),
    )
    negativePrompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Extra negative prompt terms",
    )
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed for reproducibility",
    )
    length: Optional[int] = Field(
        default=None,
        description=f"Frame count. Allowed: {sorted(VIDEO_ALLOWED_LENGTHS)}. None = server default (81).",
    )
    fps: Optional[int] = Field(
        default=None,
        ge=8,
        le=30,
        description="Frames per second. None = server default (16).",
    )
    width: Optional[int] = Field(
        default=None,
        description=f"Clip width. Allowed pairs: {sorted(VIDEO_ALLOWED_RESOLUTIONS)}. None = server default (480).",
    )
    height: Optional[int] = Field(
        default=None,
        description=f"Clip height. Allowed pairs: {sorted(VIDEO_ALLOWED_RESOLUTIONS)}. None = server default (832).",
    )

    # Filled server-side (from the path + source resolution); not client-supplied.
    character_id: Optional[str] = Field(default=None, description="Set server-side from the URL path")
    source_image: Optional[str] = Field(default=None, description="Resolved still URL, set server-side")
    motionLabel: Optional[str] = Field(
        default=None,
        description="Set server-side from the LLM interpretation of a custom motionPrompt",
    )

    @field_validator("length")
    @classmethod
    def validate_length(cls, v):
        if v is not None and v not in VIDEO_ALLOWED_LENGTHS:
            raise ValueError(
                f"Unsupported length '{v}'. Allowed: {sorted(VIDEO_ALLOWED_LENGTHS)}"
            )
        return v

    @model_validator(mode="after")
    def validate_resolution(self):
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

    class Config:
        json_schema_extra = {
            "example": {
                "source_image_id": "9c1e2a4f-0000-0000-0000-000000000000",
                "motion": "hair_in_wind",
                "seed": 12345,
            }
        }


class BackgroundEditRequest(BaseModel):
    """Request body for POST /v1/edit/background."""

    source_image: str = Field(
        ...,
        description="Supabase URL of the source image to edit"
    )
    prompt: str = Field(
        ...,
        max_length=2000,
        description="Background/scene description to apply"
    )
    negativePrompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Negative prompt for background generation"
    )
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed for reproducibility"
    )

    @field_validator("source_image")
    @classmethod
    def validate_source_image_url(cls, v):
        try:
            return validate_source_image(v)
        except SourceImageError as e:
            raise ValueError(str(e))

    class Config:
        json_schema_extra = {
            "example": {
                "source_image": "https://xxx.supabase.co/storage/v1/object/public/images/test.png",
                "prompt": "tropical beach at sunset, warm golden light",
                "seed": 12345
            }
        }


VALID_PIPELINE_STEPS = {"pose", "outfit", "background"}


class PipelineEditRequest(BaseModel):
    """
    Unified request body for POST /v1/edit.
    Runs requested editing steps in a configurable pipeline order
    (default: pose → outfit → background), chaining outputs between steps.
    """

    source_image: str = Field(
        ...,
        description="Supabase URL of the source image to edit"
    )
    pose: Optional[PoseType] = Field(
        default=None,
        description="Target pose to apply. If set, pose step runs."
    )
    outfit: Optional[OutfitType] = Field(
        default=None,
        description="Outfit type to apply. If set, outfit step runs."
    )
    outfitDetail: Optional[str] = Field(
        default=None,
        max_length=160,
        description=(
            "Optional identity-free concrete garment description (colors/fabric/fit; "
            "e.g. from SceneSpec.outfit_detail) appended after the outfit's tier prose "
            "to sharpen it. Clothing ONLY. None = tier prose only (unchanged behavior)."
        ),
    )
    outfitDenoise: Optional[float] = Field(
        default=None,
        ge=0.5,
        le=0.95,
        description=(
            "Optional outfit-step denoise override for the crop-and-stitch graph "
            "(node 106). Higher = the new garment overrides the source clothing more "
            "strongly. None = engine default (~0.80). No effect on the legacy V1 "
            "whole-frame graph."
        ),
    )
    outfitPromptMode: Optional[str] = Field(
        default=None,
        description=(
            "'standard' (default behavior: append outfit/outfitDetail) | 'replace' "
            "(explicit remove-then-replace lead-in — use when a dressed source keeps "
            "reconstructing its original garment) | 'nude_base' (INTERNAL — set by "
            "the nude-base endpoint, not admin UIs: on the NAKED outfit it swaps the "
            "arousal-styled tier prose for a neutral anatomical reference body and "
            "hardens the removal so no stray bra/strap/underwear survives). None "
            "behaves like 'standard'."
        ),
    )
    outfitDetailDominant: bool = Field(
        default=False,
        description=(
            "When True the outfit step's garment description is the freeform outfitDetail "
            "ALONE; the enum's tier prose is skipped (the enum only gates the step + carries "
            "the nudity ramp, which is re-expressed as a garment-neutral exposure clause). "
            "Set by the planner when a director caption had no confident enum mapping or "
            "conflicted with the enum. No effect on the NAKED outfit or when outfitDetail is "
            "empty. Defaults False (unchanged tier-prose behavior)."
        ),
    )
    nudityLevel: NudityLevel = Field(
        default=NudityLevel.LOW,
        description="Nudity level for outfit step: low, medium, high"
    )
    accessories: Optional[List[AccessoryType]] = Field(
        default=None,
        max_length=5,
        description="List of accessories to add during outfit step (max 5)"
    )
    activity: Optional[str] = Field(
        default=None,
        max_length=200,
        description=(
            "Optional identity-free action phrase (e.g. from SceneSpec.activity) "
            "routed to the pose step as ', while {activity}'. Only has an effect when "
            "a pose step is active; ignored otherwise."
        ),
    )
    expression: Optional[str] = Field(
        default=None,
        max_length=80,
        description=(
            "Optional facial expression/mood (e.g. from SceneSpec.expression) routed "
            "to the pose step as ', {expression} expression'. Expression/mood ONLY — "
            "never facial features. Only has an effect when a pose step is active "
            "(non-posed items keep the hero's face byte-locked)."
        ),
    )
    lighting: Optional[str] = Field(
        default=None,
        max_length=60,
        description=(
            "Optional identity-free lighting descriptor (e.g. from SceneSpec.lighting, an "
            "enum value like 'candlelit'/'neon'/'moody_dim'). Phrase-ified (via "
            "services.scene_vocab) and appended to the pose step's prompt — the primary "
            "lighting fix, since pose is the only step that fully re-diffuses the frame — "
            "and, as a secondary/cheap signal, to the outfit step's prompt. Unrecognized "
            "values or None leave both prompts unchanged."
        ),
    )
    timeOfDay: Optional[str] = Field(
        default=None,
        max_length=40,
        description=(
            "Optional time-of-day descriptor (e.g. from SceneSpec.time_of_day, an enum "
            "value like 'golden_hour'/'night'). Phrase-ified (via services.scene_vocab) and "
            "appended to the pose step's prompt only. Unrecognized values or None leave the "
            "prompt unchanged."
        ),
    )
    location: Optional[str] = Field(
        default=None,
        max_length=60,
        description=(
            "Optional scene-location descriptor (e.g. from SceneSpec.location, an enum "
            "value like 'home_bedroom'/'beach'/'cafe'). Phrase-ified (via services.scene_vocab) "
            "and appended to the pose step's prompt as the scene the reposed frame must keep — "
            "the pose step is the only step that re-diffuses the whole frame, so it is the one "
            "place the location can be re-anchored. Unrecognized values or None leave the "
            "prompt unchanged."
        ),
    )
    prompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Background/scene prompt. If set, background step runs."
    )
    negativePrompt: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Negative prompt for background step"
    )
    backgroundDenoise: Optional[float] = Field(
        default=None,
        ge=0.5,
        le=1.0,
        description=(
            "Optional background-step denoise override for the V1 whole-frame graph "
            "(node 106). Higher = the new backdrop overrides the source scene more "
            "strongly — e.g. the nude base clears the hero's original location to a "
            "plain studio backdrop. None = the template's baked value (~0.80)."
        ),
    )
    soloSubject: bool = Field(
        default=False,
        description=(
            "Nude-base / internal. When the server's SOLO_BG_PERSON_THRESHOLD env "
            "is set (>0), the background step raises its GroundingDINO person-"
            "detector confidence threshold so low-confidence background passersby "
            "fall OUT of the protected mask and get painted over by the new "
            "backdrop. FAIL-OPEN risk: if the MAIN subject also scored below the "
            "threshold the whole frame becomes editable — acceptable only for "
            "admin-reviewed assets like the nude base, never the interactive edit "
            "paths (which leave this false)."
        ),
    )
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed shared across all pipeline steps"
    )
    pipeline_order: Optional[List[str]] = Field(
        default=None,
        description="Override default pipeline order. Must contain only 'pose', 'outfit', 'background'."
    )
    photoStyle: Optional[PhotoStyleType] = Field(
        default=PhotoStyleType.POLISHED,
        description=(
            "Photographic finish appended to the final step's edit instruction so a "
            "pipeline edit matches the generated hero's retouched look: polished "
            "(retouched, default), natural, studio, or candid_phone (legacy raw, "
            "no style clause)."
        )
    )
    sourceDressed: bool = Field(
        default=False,
        description=(
            "Set true when the SOURCE already shows clothing, so the outfit step can use "
            "the tight GARMENT mask (edit only the existing clothing) for supported outfit "
            "types — keeps fine detail and avoids re-diffusing the body. Leave false for a "
            "nude source. Note: in a pose->outfit pipeline the person is still clothed when "
            "the outfit step runs, so this reflects the ORIGINAL source's dressed state."
        )
    )

    @field_validator("source_image")
    @classmethod
    def validate_source_image_url(cls, v):
        try:
            return validate_source_image(v)
        except SourceImageError as e:
            raise ValueError(str(e))

    @field_validator("pipeline_order")
    @classmethod
    def validate_pipeline_order(cls, v):
        if v is not None:
            for step in v:
                if step not in VALID_PIPELINE_STEPS:
                    raise ValueError(
                        f"Invalid pipeline step '{step}'. "
                        f"Must be one of: {', '.join(sorted(VALID_PIPELINE_STEPS))}"
                    )
        return v

    @model_validator(mode="after")
    def validate_at_least_one_step(self):
        if self.pose is None and self.outfit is None and self.prompt is None:
            raise ValueError(
                "At least one pipeline step must be specified "
                "(pose, outfit, or prompt for background)"
            )
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "source_image": "https://xxx.supabase.co/storage/v1/object/public/images/test.png",
                "pose": "sitting_casual",
                "outfit": "red_evening_gown",
                "nudityLevel": "high",
                "prompt": "beach background, sunset",
                "seed": 12345
            }
        }
