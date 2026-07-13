"""
Options endpoint. Admin-only, stateless.

GET /v1/options — enumerates every selectable enum (persona/generation/scene/video)
as {value,label} pairs, plus the numeric constraints (age range, kinks cap, name
length), so an admin UI can build its dropdowns/forms from one source of truth
instead of hardcoding values that can drift from the backend's enums.

Modeled on the stateless GET-style pattern of scenes.py, minus the service layer
(this endpoint only reads static enums/constants — nothing to inject).
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends

from auth.admin import require_admin
from models.enums import (
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
    NudityLevel,
    OutfitType,
    PoseType,
    AccessoryType,
    PhotoStyleType,
    LocationType,
    TimeOfDayType,
    LightingType,
    ShotFramingType,
    CameraAngleType,
    ExpressionType,
    MotionType,
    WardrobeStyleType,
    DemeanorType,
    ZodiacType,
    InteriorStyleType,
    PaletteType,
)
from models.requests import VIDEO_ALLOWED_LENGTHS, VIDEO_ALLOWED_RESOLUTIONS
from services.output_presets import ASPECT_RATIO_DIMS, ALLOWED_RESOLUTIONS

router = APIRouter(tags=["Options"])


def _opts(enum_cls):
    return [{"value": m.value, "label": m.value.replace("_", " ").title()} for m in enum_cls]


@router.get(
    "/options",
    summary="Enumerate all selectable options (admin UI dropdowns)",
    description=(
        "Admin-only, stateless. Returns every enum's {value,label} pairs grouped "
        "by persona/generation/scene/video, plus the numeric constraints (age "
        "range, kinks cap, name length) so a UI never hardcodes them."
    ),
)
async def get_options(user: Dict[str, Any] = Depends(require_admin)):
    return {
        "persona": {
            "style": _opts(StyleType),
            "ethnicity": _opts(EthnicityType),
            "hair_style": _opts(HairStyleType),
            "hair_color": _opts(HairColorType),
            "eye_color": _opts(EyeColorType),
            "body_type": _opts(BodyType),
            "breast_size": _opts(BreastSize),
            "personality": _opts(PersonalityType),
            "relationship": _opts(RelationshipType),
            "occupation": _opts(OccupationType),
            "kinks": _opts(KinkType),
            "constraints": {
                # Mirrors PersonaOptions.age bounds (models/requests.py).
                "age": {"min": 18, "max": 50},
                "kinks_max": 3,
                "name_max_length": 50,
            },
        },
        "generation": {
            "nudity_level": _opts(NudityLevel),
            "outfit": _opts(OutfitType),
            "pose": _opts(PoseType),
            "accessory": _opts(AccessoryType),
            "photo_style": _opts(PhotoStyleType),
            "aspect_ratios": list(ASPECT_RATIO_DIMS.keys()),
            "resolutions": sorted(ALLOWED_RESOLUTIONS),
        },
        "scene": {
            "location": _opts(LocationType),
            "time_of_day": _opts(TimeOfDayType),
            "lighting": _opts(LightingType),
            "shot_framing": _opts(ShotFramingType),
            "camera_angle": _opts(CameraAngleType),
            "expression": _opts(ExpressionType),
        },
        "video": {
            "motion": _opts(MotionType),
            # Both are sets in models/requests.py; sorted() gives stable JSON output.
            "lengths": sorted(VIDEO_ALLOWED_LENGTHS),
            "resolutions": sorted(VIDEO_ALLOWED_RESOLUTIONS),
        },
        "trait_profile": {
            "wardrobe_style": _opts(WardrobeStyleType),
            "demeanor": _opts(DemeanorType),
            "zodiac": _opts(ZodiacType),
            "interior_style": _opts(InteriorStyleType),
            "color_palette": _opts(PaletteType),
        },
    }
