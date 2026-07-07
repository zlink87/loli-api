"""
Structured scene vocabulary for Story Batches.

Location / time-of-day / lighting enums are mapped to descriptive phrases and
composed into the free-text background string consumed by the existing background
edit step (background.build_background_prompt). This lives in its own module (rather
than appended to attribute_phrases.py) so the scene vocabulary is self-contained.

These phrases describe ONLY the environment — never the person — so they compose
cleanly with the identity-preserving background edit.
"""
from typing import List, Optional

from services.attribute_phrases import phrase, KINK_PHRASES, PERSONALITY_PHRASES


# One entry for EVERY LocationType / TimeOfDayType / LightingType value
# (coverage is enforced by tests).
LOCATION_PHRASES = {
    # home
    "home_bedroom": "a cozy sunlit bedroom with soft bedding and warm decor",
    "home_living_room": "a comfortable living room with a sofa and warm lamps",
    "home_kitchen": "a bright modern home kitchen with clean counters",
    "home_bathroom": "a bright modern bathroom with a large mirror",
    "home_balcony": "a private balcony overlooking the city",
    "home_office": "a tidy home office with a desk and shelves",
    # workplace
    "office": "a sleek modern corporate office with glass walls",
    "hospital_ward": "a clean bright hospital ward with medical equipment",
    "classroom": "a tidy classroom with a chalkboard and desks",
    "photo_studio": "a professional photo studio with a seamless backdrop",
    "gym": "a well-equipped modern gym with weights and mirrors",
    "yoga_studio": "a serene yoga studio with wooden floors and soft light",
    "restaurant_kitchen": "a busy professional restaurant kitchen with steel counters",
    "library": "a quiet library with tall bookshelves",
    "salon": "a stylish beauty salon with mirrors and chairs",
    "stage": "a dramatic stage with spotlights",
    "lab": "a clean modern laboratory with equipment",
    # outdoors
    "beach": "a sunlit tropical beach with turquoise water and pale sand",
    "park": "a green city park with trees and open lawns",
    "city_street": "a lively city street with storefronts and passersby",
    "forest_trail": "a peaceful forest trail among tall trees",
    "rooftop": "a rooftop terrace overlooking a city skyline",
    "poolside": "the edge of a luxury swimming pool",
    "garden": "a lush blooming garden",
    # social venues
    "cafe": "a warm rustic cafe with wooden tables",
    "restaurant": "an elegant restaurant with candlelit tables",
    "bar": "a stylish dimly lit cocktail bar",
    "nightclub": "a vibrant nightclub with colored lights and a crowd",
    "hotel_room": "an elegant upscale hotel room with a large bed",
    "luxury_lounge": "a plush luxury lounge with velvet seating",
    "car_interior": "the interior of a parked luxury car",
}

TIME_OF_DAY_PHRASES = {
    "early_morning": "in the quiet early morning",
    "morning": "in the fresh morning light",
    "daytime": "in the middle of the day",
    "golden_hour": "during golden hour",
    "sunset": "at sunset",
    "evening": "in the early evening",
    "night": "late at night",
}

LIGHTING_PHRASES = {
    "natural_soft": "soft natural lighting",
    "bright_daylight": "bright even daylight",
    "golden_warm": "warm golden light",
    "moody_dim": "moody dim low-key lighting",
    "neon": "vivid neon lighting",
    "candlelit": "flickering candlelight",
    "studio_softbox": "clean studio softbox lighting",
    "backlit_rim": "dramatic backlit rim lighting",
    "overcast": "soft diffuse overcast light",
}


def location_phrase(location) -> str:
    """Descriptive phrase for a LocationType (or its value)."""
    return phrase(LOCATION_PHRASES, location)


def scene_mood_phrase(kinks=None, personality=None) -> str:
    """
    Tasteful mood-only phrases from per-scene kink/personality overrides.
    Reuses KINK_PHRASES + PERSONALITY_PHRASES (mood/expression only — never identity).
    """
    parts: List[str] = []
    if personality:
        p = phrase(PERSONALITY_PHRASES, personality)
        if p:
            parts.append(p)
    if kinks:
        for k in list(kinks)[:3]:
            kp = phrase(KINK_PHRASES, k)
            if kp:
                parts.append(kp)
    return ", ".join(parts)


def build_scene_background_text(
    location,
    time_of_day=None,
    lighting=None,
    mood_kinks=None,
    mood_personality=None,
    free_text: Optional[str] = None,
) -> str:
    """
    Compose location + time + lighting (+ optional mood + free text) into the
    scene free-text consumed by background.build_background_prompt(). Contains NO
    persona identity language.
    """
    parts: List[str] = []
    loc = location_phrase(location)
    if loc:
        parts.append(loc)
    t = phrase(TIME_OF_DAY_PHRASES, time_of_day)
    if t:
        parts.append(t)
    li = phrase(LIGHTING_PHRASES, lighting)
    if li:
        parts.append(li)
    mood = scene_mood_phrase(mood_kinks, mood_personality)
    if mood:
        parts.append(mood)
    if free_text and free_text.strip():
        parts.append(free_text.strip())
    return ", ".join(parts)
