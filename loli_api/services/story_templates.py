"""
Hand-authored narrative arc templates for the deterministic story planner.

An ArcTemplate is a sequence of BeatTemplates; each beat offers *pools* of poses /
outfits / locations / times / lighting from which the deterministic planner samples
(seeded, weighted by likes, filtered by dislikes + controls). Shared arcs (morning /
evening / out-and-about) are reused across professions so we don't author N*M content;
only the profession-specific "work" arc differs.

These templates describe ONLY scene attributes — never persona identity.
"""
from dataclasses import dataclass
from typing import Dict, Tuple

from models.enums import (
    PoseType as P,
    OutfitType as O,
    LocationType as L,
    TimeOfDayType as T,
    LightingType as Li,
)


@dataclass(frozen=True)
class BeatTemplate:
    beat_description: str
    pose_pool: Tuple[P, ...]
    outfit_pool: Tuple[O, ...]
    location_pool: Tuple[L, ...]
    time_pool: Tuple[T, ...]
    lighting_pool: Tuple[Li, ...]
    nudity_bias: str  # "low" | "medium" | "escalate"


@dataclass(frozen=True)
class ArcTemplate:
    arc_id: str
    arc_title: str
    beats: Tuple[BeatTemplate, ...]


# --- Shared arcs -------------------------------------------------------------
MORNING_HOME_ARC = ArcTemplate(
    arc_id="morning_home",
    arc_title="A slow morning at home",
    beats=(
        BeatTemplate(
            "Waking up slow, wrapped in a robe",
            (P.STANDING_LEANING, P.SITTING, P.LYING_STOMACH),
            (O.SATIN_ROBE, O.SILK_PAJAMAS, O.OVERSIZED_STREETWEAR),
            (L.HOME_BEDROOM,),
            (T.EARLY_MORNING, T.MORNING),
            (Li.NATURAL_SOFT, Li.OVERCAST),
            "low",
        ),
        BeatTemplate(
            "Morning coffee in the kitchen, unhurried",
            (P.STANDING_LEANING, P.COOKING, P.OPENING_FRIDGE),
            (O.SILK_PAJAMAS, O.GRAPHIC_TEE_SHORTS, O.HOODIE_JOGGERS),
            (L.HOME_KITCHEN,),
            (T.MORNING,),
            (Li.NATURAL_SOFT, Li.BRIGHT_DAYLIGHT),
            "low",
        ),
        BeatTemplate(
            "Curled on the sofa, watching the day begin",
            (P.SOFA, P.SITTING, P.HANDS_BEHIND_HEAD),
            (O.OVERSIZED_STREETWEAR, O.SILK_PAJAMAS, O.SATIN_SLIP_DRESS),
            (L.HOME_LIVING_ROOM, L.HOME_BALCONY),
            (T.MORNING, T.DAYTIME),
            (Li.NATURAL_SOFT,),
            "low",
        ),
    ),
)

OUT_AND_ABOUT_ARC = ArcTemplate(
    arc_id="out_and_about",
    arc_title="Out and about",
    beats=(
        BeatTemplate(
            "Strolling out for the day",
            (P.STANDING_LEANING, P.JOGGING),
            (O.WHITE_SUMMER_DRESS, O.DENIM_JACKET_JEANS, O.FLORAL_MAXI_DRESS),
            (L.CITY_STREET, L.PARK, L.CAFE),
            (T.DAYTIME, T.MORNING),
            (Li.BRIGHT_DAYLIGHT, Li.NATURAL_SOFT),
            "low",
        ),
        BeatTemplate(
            "A relaxed moment at a cafe",
            (P.SITTING, P.EATING),
            (O.CROP_TOP_CARGO, O.WHITE_SUMMER_DRESS, O.BODYCON_DRESS),
            (L.CAFE, L.RESTAURANT, L.GARDEN),
            (T.DAYTIME, T.GOLDEN_HOUR),
            (Li.NATURAL_SOFT, Li.GOLDEN_WARM),
            "low",
        ),
        BeatTemplate(
            "Golden-hour glow outdoors",
            (P.STANDING_LEANING, P.HANDS_BEHIND_HEAD),
            (O.BIKINI, O.WHITE_SUMMER_DRESS, O.SATIN_SLIP_DRESS),
            (L.BEACH, L.POOLSIDE, L.ROOFTOP),
            (T.GOLDEN_HOUR, T.SUNSET),
            (Li.GOLDEN_WARM, Li.BACKLIT_RIM),
            "medium",
        ),
    ),
)

EVENING_UNWIND_ARC = ArcTemplate(
    arc_id="evening_unwind",
    arc_title="Evening back home",
    beats=(
        BeatTemplate(
            "Golden-hour on the balcony with a drink",
            (P.STANDING_LEANING, P.SITTING),
            (O.SATIN_SLIP_DRESS, O.COCKTAIL_DRESS, O.VELVET_DRESS),
            (L.HOME_BALCONY, L.LUXURY_LOUNGE),
            (T.GOLDEN_HOUR, T.EVENING),
            (Li.GOLDEN_WARM, Li.MOODY_DIM),
            "low",
        ),
        BeatTemplate(
            "Unwinding on the sofa as night falls",
            (P.SOFA, P.LYING_BACK, P.SITTING_LEGS_WIDE_OPEN),
            (O.LACE_BODYSUIT, O.SATIN_SLIP_DRESS, O.SILK_PAJAMAS),
            (L.HOME_LIVING_ROOM, L.HOME_BEDROOM),
            (T.EVENING, T.NIGHT),
            (Li.MOODY_DIM, Li.CANDLELIT),
            "escalate",
        ),
        BeatTemplate(
            "Candlelit and intimate in the bedroom",
            (P.LYING_BACK, P.KNEELING, P.ALL_FOURS, P.SPREAD_LEGS),
            (O.LACE_BODYSUIT, O.SATIN_ROBE, O.NAKED),
            (L.HOME_BEDROOM, L.HOTEL_ROOM),
            (T.NIGHT,),
            (Li.CANDLELIT, Li.MOODY_DIM),
            "escalate",
        ),
    ),
)


# --- Profession "work" arcs --------------------------------------------------
HOSPITAL_SHIFT_ARC = ArcTemplate(
    arc_id="on_the_ward",
    arc_title="On the ward",
    beats=(
        BeatTemplate(
            "Confident on rounds",
            (P.STANDING_LEANING, P.HANDS_BEHIND_HEAD),
            (O.NURSE_UNIFORM,),
            (L.HOSPITAL_WARD,),
            (T.DAYTIME, T.MORNING),
            (Li.BRIGHT_DAYLIGHT,),
            "low",
        ),
        BeatTemplate(
            "A teasing glance at the nurses' station",
            (P.SITTING, P.BENDING_OVER),
            (O.NURSE_UNIFORM,),
            (L.HOSPITAL_WARD,),
            (T.DAYTIME,),
            (Li.BRIGHT_DAYLIGHT, Li.NATURAL_SOFT),
            "medium",
        ),
    ),
)

CLASSROOM_ARC = ArcTemplate(
    arc_id="in_the_classroom",
    arc_title="In the classroom",
    beats=(
        BeatTemplate(
            "Teaching at the board",
            (P.STANDING_LEANING,),
            (O.PENCIL_SKIRT_SET, O.BUSINESS_SUIT, O.BLAZER_TROUSERS),
            (L.CLASSROOM,),
            (T.DAYTIME, T.MORNING),
            (Li.BRIGHT_DAYLIGHT,),
            "low",
        ),
        BeatTemplate(
            "A quiet moment after class",
            (P.SITTING, P.BENDING_OVER),
            (O.PENCIL_SKIRT_SET, O.BODYCON_DRESS),
            (L.CLASSROOM, L.LIBRARY),
            (T.DAYTIME, T.EVENING),
            (Li.NATURAL_SOFT, Li.MOODY_DIM),
            "medium",
        ),
    ),
)

STUDIO_ARC = ArcTemplate(
    arc_id="in_the_studio",
    arc_title="In the studio",
    beats=(
        BeatTemplate(
            "Posing under studio lights",
            (P.STANDING_LEANING, P.HANDS_BEHIND_HEAD),
            (O.BODYCON_DRESS, O.SEQUIN_TOP_SKIRT, O.LACE_BODYSUIT),
            (L.PHOTO_STUDIO, L.STAGE),
            (T.DAYTIME,),
            (Li.STUDIO_SOFTBOX, Li.BACKLIT_RIM),
            "medium",
        ),
        BeatTemplate(
            "A bolder set as the shoot heats up",
            (P.LYING_BACK, P.KNEELING, P.ALL_FOURS),
            (O.LACE_BODYSUIT, O.BIKINI, O.NAKED),
            (L.PHOTO_STUDIO,),
            (T.DAYTIME,),
            (Li.STUDIO_SOFTBOX, Li.MOODY_DIM),
            "escalate",
        ),
    ),
)

GYM_ARC = ArcTemplate(
    arc_id="at_the_gym",
    arc_title="At the gym",
    beats=(
        BeatTemplate(
            "Warming up",
            (P.STANDING_LEANING, P.SQUATTING),
            (O.GYM_SET, O.YOGA_OUTFIT, O.RUNNING_GEAR),
            (L.GYM, L.YOGA_STUDIO),
            (T.MORNING, T.DAYTIME),
            (Li.BRIGHT_DAYLIGHT, Li.NATURAL_SOFT),
            "low",
        ),
        BeatTemplate(
            "Stretching, glistening after a session",
            (P.ALL_FOURS, P.BENDING_OVER, P.SPREAD_LEGS),
            (O.GYM_SET, O.YOGA_OUTFIT),
            (L.YOGA_STUDIO, L.GYM),
            (T.DAYTIME,),
            (Li.NATURAL_SOFT,),
            "medium",
        ),
    ),
)

OFFICE_ARC = ArcTemplate(
    arc_id="at_the_office",
    arc_title="At the office",
    beats=(
        BeatTemplate(
            "Commanding the room",
            (P.STANDING_LEANING, P.SITTING),
            (O.BUSINESS_SUIT, O.POWER_SUIT_80S, O.PENCIL_SKIRT_SET),
            (L.OFFICE,),
            (T.DAYTIME, T.MORNING),
            (Li.BRIGHT_DAYLIGHT,),
            "low",
        ),
        BeatTemplate(
            "Late at the office, tie loosened",
            (P.BENDING_OVER, P.SITTING_LEGS_WIDE_OPEN),
            (O.PENCIL_SKIRT_SET, O.BODYCON_DRESS),
            (L.OFFICE,),
            (T.EVENING, T.NIGHT),
            (Li.MOODY_DIM, Li.NEON),
            "escalate",
        ),
    ),
)

NIGHT_OUT_ARC = ArcTemplate(
    arc_id="night_out",
    arc_title="A night out",
    beats=(
        BeatTemplate(
            "Getting ready to go out",
            (P.STANDING_LEANING, P.HANDS_BEHIND_HEAD),
            (O.COCKTAIL_DRESS, O.SEQUIN_TOP_SKIRT, O.LITTLE_BLACK_DRESS),
            (L.HOME_BEDROOM, L.HOTEL_ROOM),
            (T.EVENING,),
            (Li.MOODY_DIM, Li.GOLDEN_WARM),
            "low",
        ),
        BeatTemplate(
            "Owning the club",
            (P.STANDING_LEANING, P.SITTING),
            (O.BODYCON_DRESS, O.SEQUIN_TOP_SKIRT),
            (L.NIGHTCLUB, L.BAR, L.LUXURY_LOUNGE),
            (T.NIGHT,),
            (Li.NEON, Li.MOODY_DIM),
            "medium",
        ),
    ),
)


# --- Leisure / day-off arcs (multi-day stories) ------------------------------
# Drawn on days 2+ of a period_days>1 batch (see leisure_arcs_for_day). Day 1 stays
# built around her occupation (ARC_TEMPLATES); these are the OTHER real days — a day
# off, errands, a night out with friends — so a multi-day story doesn't just repeat
# the same workday. Same structural shape/conventions as the shared arcs above.
LAZY_DAY_HOME_ARC = ArcTemplate(
    arc_id="lazy_day_home",
    arc_title="A lazy day off at home",
    beats=(
        BeatTemplate(
            "Sleeping in, tangled in soft sheets",
            (P.LYING_STOMACH, P.LYING_BACK, P.SITTING),
            (O.SILK_PAJAMAS, O.SATIN_ROBE, O.OVERSIZED_STREETWEAR),
            (L.HOME_BEDROOM,),
            (T.EARLY_MORNING, T.MORNING),
            (Li.NATURAL_SOFT, Li.OVERCAST),
            "low",
        ),
        BeatTemplate(
            "A slow brunch, still in comfies",
            (P.EATING, P.STANDING_LEANING, P.SITTING),
            (O.GRAPHIC_TEE_SHORTS, O.HOODIE_JOGGERS, O.SILK_PAJAMAS),
            (L.HOME_KITCHEN, L.HOME_LIVING_ROOM),
            (T.MORNING, T.DAYTIME),
            (Li.NATURAL_SOFT, Li.BRIGHT_DAYLIGHT),
            "low",
        ),
        BeatTemplate(
            "Lazing on the sofa with a book",
            (P.SOFA, P.LYING_BACK, P.HANDS_BEHIND_HEAD),
            (O.OVERSIZED_STREETWEAR, O.GRAPHIC_TEE_SHORTS, O.SATIN_SLIP_DRESS),
            (L.HOME_LIVING_ROOM, L.HOME_BALCONY),
            (T.DAYTIME, T.GOLDEN_HOUR),
            (Li.NATURAL_SOFT, Li.GOLDEN_WARM),
            "low",
        ),
        BeatTemplate(
            "A long soak as the day winds down",
            (P.SITTING, P.LYING_BACK, P.KNEELING),
            (O.SATIN_ROBE, O.LACE_BODYSUIT, O.SILK_PAJAMAS),
            (L.HOME_BATHROOM, L.HOME_BEDROOM),
            (T.EVENING, T.NIGHT),
            (Li.CANDLELIT, Li.MOODY_DIM),
            "escalate",
        ),
    ),
)

ERRANDS_CAFE_ARC = ArcTemplate(
    arc_id="errands_and_cafe",
    arc_title="Errands and a cafe afternoon",
    beats=(
        BeatTemplate(
            "Heading out to run errands",
            (P.STANDING_LEANING, P.JOGGING),
            (O.DENIM_JACKET_JEANS, O.CROP_TOP_CARGO, O.WHITE_SUMMER_DRESS),
            (L.CITY_STREET, L.PARK),
            (T.MORNING, T.DAYTIME),
            (Li.BRIGHT_DAYLIGHT, Li.NATURAL_SOFT),
            "low",
        ),
        BeatTemplate(
            "Coffee and people-watching at a cafe",
            (P.SITTING, P.EATING, P.STANDING_LEANING),
            (O.WHITE_SUMMER_DRESS, O.CROP_TOP_CARGO, O.FLORAL_MAXI_DRESS),
            (L.CAFE, L.RESTAURANT),
            (T.DAYTIME, T.GOLDEN_HOUR),
            (Li.NATURAL_SOFT, Li.GOLDEN_WARM),
            "low",
        ),
        BeatTemplate(
            "A wander through the park as the light turns gold",
            (P.STANDING_LEANING, P.HANDS_BEHIND_HEAD, P.SITTING),
            (O.FLORAL_MAXI_DRESS, O.SATIN_SLIP_DRESS, O.DENIM_JACKET_JEANS),
            (L.PARK, L.GARDEN, L.ROOFTOP),
            (T.GOLDEN_HOUR, T.SUNSET),
            (Li.GOLDEN_WARM, Li.BACKLIT_RIM),
            "medium",
        ),
    ),
)

FRIENDS_DATE_NIGHT_ARC = ArcTemplate(
    arc_id="friends_and_date",
    arc_title="Friends, then a date night",
    beats=(
        BeatTemplate(
            "Getting ready for the evening",
            (P.STANDING_LEANING, P.HANDS_BEHIND_HEAD, P.SITTING),
            (O.SATIN_SLIP_DRESS, O.LITTLE_BLACK_DRESS, O.COCKTAIL_DRESS),
            (L.HOME_BEDROOM, L.HOTEL_ROOM),
            (T.EVENING,),
            (Li.MOODY_DIM, Li.GOLDEN_WARM),
            "low",
        ),
        BeatTemplate(
            "Drinks and laughter with friends",
            (P.SITTING, P.STANDING_LEANING),
            (O.COCKTAIL_DRESS, O.SEQUIN_TOP_SKIRT, O.LITTLE_BLACK_DRESS),
            (L.BAR, L.LUXURY_LOUNGE, L.RESTAURANT),
            (T.EVENING, T.NIGHT),
            (Li.MOODY_DIM, Li.NEON),
            "low",
        ),
        BeatTemplate(
            "An intimate dinner for two",
            (P.SITTING, P.EATING, P.STANDING_LEANING),
            (O.VELVET_DRESS, O.BODYCON_DRESS, O.SATIN_SLIP_DRESS),
            (L.RESTAURANT,),
            (T.NIGHT,),
            (Li.CANDLELIT, Li.MOODY_DIM),
            "medium",
        ),
        BeatTemplate(
            "Back home, the night turns private",
            (P.LYING_BACK, P.KNEELING, P.SITTING_LEGS_WIDE_OPEN),
            (O.LACE_BODYSUIT, O.SATIN_ROBE, O.SATIN_SLIP_DRESS),
            (L.HOME_BEDROOM, L.HOTEL_ROOM),
            (T.NIGHT,),
            (Li.CANDLELIT, Li.MOODY_DIM),
            "escalate",
        ),
    ),
)


GENERIC_ARCS: Tuple[ArcTemplate, ...] = (
    MORNING_HOME_ARC,
    OUT_AND_ABOUT_ARC,
    EVENING_UNWIND_ARC,
)

# Keyed by OccupationType.value. Professions not listed fall back to GENERIC_ARCS.
# The middle arc is the profession-specific "work" arc; morning/evening bookend it.
ARC_TEMPLATES: Dict[str, Tuple[ArcTemplate, ...]] = {
    "nurse": (MORNING_HOME_ARC, HOSPITAL_SHIFT_ARC, EVENING_UNWIND_ARC),
    "doctor": (MORNING_HOME_ARC, HOSPITAL_SHIFT_ARC, EVENING_UNWIND_ARC),
    "gynecologist": (MORNING_HOME_ARC, HOSPITAL_SHIFT_ARC, EVENING_UNWIND_ARC),
    "teacher": (MORNING_HOME_ARC, CLASSROOM_ARC, EVENING_UNWIND_ARC),
    "librarian": (MORNING_HOME_ARC, CLASSROOM_ARC, EVENING_UNWIND_ARC),
    "student": (MORNING_HOME_ARC, CLASSROOM_ARC, NIGHT_OUT_ARC),
    "writer": (MORNING_HOME_ARC, CLASSROOM_ARC, EVENING_UNWIND_ARC),
    "model": (STUDIO_ARC, OUT_AND_ABOUT_ARC, EVENING_UNWIND_ARC),
    "photographer": (STUDIO_ARC, OUT_AND_ABOUT_ARC, EVENING_UNWIND_ARC),
    "movie_star_actress": (STUDIO_ARC, NIGHT_OUT_ARC, EVENING_UNWIND_ARC),
    "dancer": (STUDIO_ARC, NIGHT_OUT_ARC, EVENING_UNWIND_ARC),
    "stripper": (STUDIO_ARC, NIGHT_OUT_ARC, EVENING_UNWIND_ARC),
    "singer_musician": (STUDIO_ARC, NIGHT_OUT_ARC, EVENING_UNWIND_ARC),
    "yoga_instructor": (MORNING_HOME_ARC, GYM_ARC, EVENING_UNWIND_ARC),
    "fitness_coach": (MORNING_HOME_ARC, GYM_ARC, EVENING_UNWIND_ARC),
    "professional_athlete": (MORNING_HOME_ARC, GYM_ARC, EVENING_UNWIND_ARC),
    "lifeguard": (OUT_AND_ABOUT_ARC, GYM_ARC, EVENING_UNWIND_ARC),
    "boss_ceo": (MORNING_HOME_ARC, OFFICE_ARC, EVENING_UNWIND_ARC),
    "secretary": (MORNING_HOME_ARC, OFFICE_ARC, EVENING_UNWIND_ARC),
    "lawyer": (MORNING_HOME_ARC, OFFICE_ARC, EVENING_UNWIND_ARC),
    "tech_engineer": (MORNING_HOME_ARC, OFFICE_ARC, NIGHT_OUT_ARC),
    "bartender": (MORNING_HOME_ARC, NIGHT_OUT_ARC, EVENING_UNWIND_ARC),
    "cam_girl": (MORNING_HOME_ARC, STUDIO_ARC, EVENING_UNWIND_ARC),
    "streamer": (MORNING_HOME_ARC, STUDIO_ARC, NIGHT_OUT_ARC),
    "pornstar": (STUDIO_ARC, NIGHT_OUT_ARC, EVENING_UNWIND_ARC),
    "maid": (MORNING_HOME_ARC, OUT_AND_ABOUT_ARC, EVENING_UNWIND_ARC),
    "flight_attendant": (OUT_AND_ABOUT_ARC, NIGHT_OUT_ARC, EVENING_UNWIND_ARC),
}


# Leisure/day-off pool for the non-first days of a multi-day story. Day 1 stays on
# the occupation arcs (ARC_TEMPLATES); days 2+ rotate through THESE so each day feels
# like a different real day (see leisure_arcs_for_day / story_planner._plan_arcs).
LEISURE_ARCS: Tuple[ArcTemplate, ...] = (
    LAZY_DAY_HOME_ARC,
    ERRANDS_CAFE_ARC,
    FRIENDS_DATE_NIGHT_ARC,
)


def leisure_arcs_for_day(day_index: int) -> Tuple[ArcTemplate, ...]:
    """
    The leisure/day-off arc pool for a non-first day, rotated so consecutive days
    LEAD with a different theme (a lazy day, then errands, then a night out...) —
    a multi-day batch reads as different real days, not the same day off repeated.

    ``day_index`` is 0-based over the whole story where day 0 is her occupation day
    (handled by the caller); this is only called for day_index >= 1. Rotation is a
    pure function of the index (offset = (day_index-1) mod len), so a batch replans
    identically. Empty pool would fall back to GENERIC_ARCS (defensive).
    """
    if not LEISURE_ARCS:
        return GENERIC_ARCS
    offset = (day_index - 1) % len(LEISURE_ARCS)
    return LEISURE_ARCS[offset:] + LEISURE_ARCS[:offset]


# ---------------------------------------------------------------------------
# Occupation -> workplace locations (story director "DAY SHAPE" block)
# ---------------------------------------------------------------------------
# Where THIS occupation actually works, so the director can anchor the one "work
# chapter" of her day in a coherent place. Keyed by OccupationType.value; every
# value is a REAL LocationType member (models/enums.py). Occupations without a
# natural workplace fall back to (OFFICE, CITY_STREET).
OCCUPATION_WORK_LOCATIONS: Dict[str, Tuple[L, ...]] = {
    "student": (L.CLASSROOM, L.LIBRARY),
    "dancer": (L.STAGE, L.PHOTO_STUDIO),
    "model": (L.PHOTO_STUDIO, L.STAGE),
    "stripper": (L.STAGE, L.NIGHTCLUB),
    "maid": (L.HOTEL_ROOM, L.HOME_LIVING_ROOM),
    "cam_girl": (L.PHOTO_STUDIO, L.HOME_OFFICE),
    "boss_ceo": (L.OFFICE,),
    "babysitter_au_pair": (L.HOME_LIVING_ROOM, L.PARK),
    "pornstar": (L.PHOTO_STUDIO, L.HOTEL_ROOM),
    "streamer": (L.HOME_OFFICE, L.PHOTO_STUDIO),
    "bartender": (L.BAR, L.NIGHTCLUB),
    "tech_engineer": (L.OFFICE, L.HOME_OFFICE),
    "lifeguard": (L.BEACH, L.POOLSIDE),
    "cashier": (L.CAFE, L.CITY_STREET),
    "massage_therapist": (L.SALON, L.HOTEL_ROOM),
    "nurse": (L.HOSPITAL_WARD,),
    "secretary": (L.OFFICE,),
    "yoga_instructor": (L.YOGA_STUDIO, L.GYM),
    "fitness_coach": (L.GYM, L.YOGA_STUDIO),
    "cook": (L.RESTAURANT_KITCHEN, L.HOME_KITCHEN),
    "artist": (L.PHOTO_STUDIO, L.HOME_OFFICE),
    "movie_star_actress": (L.STAGE, L.PHOTO_STUDIO),
    "doctor": (L.HOSPITAL_WARD, L.LAB),
    "librarian": (L.LIBRARY, L.CLASSROOM),
    "spy": (L.CITY_STREET, L.HOTEL_ROOM),
    "police_officer": (L.CITY_STREET, L.OFFICE),
    "soldier": (L.FOREST_TRAIL, L.CITY_STREET),
    "lawyer": (L.OFFICE, L.LIBRARY),
    "hairdresser": (L.SALON,),
    "dentist": (L.HOSPITAL_WARD, L.LAB),
    "singer_musician": (L.STAGE, L.NIGHTCLUB),
    "gynecologist": (L.HOSPITAL_WARD, L.LAB),
    "writer": (L.HOME_OFFICE, L.CAFE),
    "flight_attendant": (L.HOTEL_ROOM, L.CITY_STREET),
    "professional_athlete": (L.GYM, L.PARK),
    "scientist": (L.LAB,),
    "florist": (L.GARDEN, L.SALON),
    "makeup_artist": (L.SALON, L.PHOTO_STUDIO),
    "photographer": (L.PHOTO_STUDIO, L.CITY_STREET),
    "social_worker": (L.OFFICE, L.HOME_LIVING_ROOM),
    "designer": (L.HOME_OFFICE, L.OFFICE),
    "pharmacist": (L.LAB, L.HOSPITAL_WARD),
    "nutritionist": (L.OFFICE, L.GYM),
}

# Fallback for occupations not in the map above (or None).
_DEFAULT_WORK_LOCATIONS: Tuple[L, ...] = (L.OFFICE, L.CITY_STREET)


def work_locations_for(occupation) -> Tuple[L, ...]:
    """Workplace LocationTypes for an occupation (enum or value); default is
    (OFFICE, CITY_STREET) for occupations with no natural workplace."""
    key = occupation.value if hasattr(occupation, "value") else occupation
    return OCCUPATION_WORK_LOCATIONS.get(key, _DEFAULT_WORK_LOCATIONS)


# ---------------------------------------------------------------------------
# Deterministic story helpers (Feature 2)
# ---------------------------------------------------------------------------
# Used when Venice is unavailable so a story_mode batch still gets a title + one
# narrative sentence per photo. Prose is THIRD-PERSON, PRESENT-TENSE and identity-free
# (built only from the scene-only beat_description + a mood phrase; the character's
# name is a safe proper noun).
_STORY_OPENERS: Tuple[str, ...] = (
    "{name} lets the moment linger — {desc}.",
    "{name} settles into it: {desc}.",
    "Right now, {name} is caught up in it — {desc}.",
    "{name} takes her time here — {desc}.",
)


def deterministic_story_title(name: str, occupation: str = "") -> str:
    who = (occupation or "").replace("_", " ").strip()
    title = f"A Day with {name} the {who}" if who else f"A Day with {name}"
    return title[:160]


def deterministic_beat_narrative(
    name: str, beat_description: str, mood_phrase: str = "", index: int = 0
) -> str:
    desc = (beat_description or "").strip().rstrip(".").lower()
    text = _STORY_OPENERS[index % len(_STORY_OPENERS)].format(name=name, desc=desc)
    if mood_phrase:
        text += f" The mood: {mood_phrase}."
    return text[:700]
