"""
Pydantic request models for the Character Image Generation API.
Based on BE-AI-Tasks.docx PersonaOptions specification.
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List

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
        description="Aspect ratio (e.g., 1:1, 16:9, 2:3)"
    )
    resolution: Optional[str] = Field(
        default="944x1408",
        description="Resolution (e.g., 1024x1024, 1920x1080)"
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
        description="Number of images to generate (1-4)"
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
        description="Optional context for the scene (e.g., 'After a long shift, relaxing at home')"
    )
    isEnhance: bool = Field(
        default=True,
        description="If True, use xAI Grok to enhance the prompt. If False, send context directly to ComfyUI."
    )
    output: Optional[OutputOptions] = Field(
        default=None,
        description="Output configuration (optional - seed only used)"
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
                "isEnhance": True
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
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed for reproducibility"
    )

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
    seed: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000000000,
        description="Random seed for reproducibility"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "source_image": "https://xxx.supabase.co/storage/v1/object/public/images/test.png",
                "pose": "sitting_casual",
                "seed": 12345
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
    nudityLevel: NudityLevel = Field(
        default=NudityLevel.LOW,
        description="Nudity level for outfit step: low, medium, high"
    )
    accessories: Optional[List[AccessoryType]] = Field(
        default=None,
        max_length=5,
        description="List of accessories to add during outfit step (max 5)"
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
