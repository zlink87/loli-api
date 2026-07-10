"""
Structured scene vocabulary for Story Batches.

Location / time-of-day / lighting enums are mapped to descriptive phrases and
composed into the free-text background string consumed by the existing background
edit step (background.build_background_prompt). This lives in its own module (rather
than appended to attribute_phrases.py) so the scene vocabulary is self-contained.

These phrases describe ONLY the environment — never the person — so they compose
cleanly with the identity-preserving background edit.
"""
import re
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


def time_of_day_phrase(time_of_day) -> str:
    """
    Descriptive phrase for a TimeOfDayType (or its raw enum-value string, e.g.
    the ``timeOfDay`` string that rides PipelineEditRequest). Same lookup used
    by build_scene_background_text, exposed standalone so other prompt
    builders (e.g. api.v1.endpoints.pose.build_pose_prompt) can phrase-ify a
    time-of-day value with the exact same tone. Unknown/None -> "" (caller
    skips the clause rather than injecting a raw enum string).
    """
    return phrase(TIME_OF_DAY_PHRASES, time_of_day)


def lighting_phrase(lighting) -> str:
    """
    Descriptive phrase for a LightingType (or its raw enum-value string, e.g.
    the ``lighting`` string that rides PipelineEditRequest). Same lookup used
    by build_scene_background_text, exposed standalone so other prompt
    builders (e.g. api.v1.endpoints.pose.build_pose_prompt /
    api.v1.endpoints.outfit.build_prompt) can phrase-ify a lighting value with
    the exact same tone. Unknown/None -> "" (caller skips the clause rather
    than injecting a raw enum string).
    """
    return phrase(LIGHTING_PHRASES, lighting)


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


# ---------------------------------------------------------------------------
# Companion / crowd scrubber for identity-free ACTION text (pose step)
#
# The pose step is the only pipeline step that fully re-diffuses the frame, so a
# planned activity like "practicing a new dance with a partner" literally paints
# the extra person into the shot. This is a DEFENSIVE, purely-textual scrub applied
# right before the activity phrase is folded into build_pose_prompt — it removes
# multi-person phrasing so a solo character stays solo. It is a backstop, not the
# primary guard: build_pose_prompt always also appends an explicit "exactly one
# person" sentence, and a planner-side scrub lands in a following PR.
# ---------------------------------------------------------------------------

# A "with <someone>" companion tail — everything from here to the end of the string
# is dropped (truncation), because the rest of the phrase describes the interaction
# with that person and no longer makes sense once they are removed.
_COMPANION_TAIL_RE = re.compile(
    r"\bwith\s+"
    r"(?:a\s+|an\s+|her\s+|his\s+|their\s+|the\s+|some\s+|another\s+)?"
    r"(?:partners?|friends?|another\s+person|others|someone|a\s+group|groups?|"
    r"guests?|colleagues?|companions?|a\s+man|a\s+woman|a\s+couple|couples?|"
    r"people|strangers?)\b",
    re.IGNORECASE,
)

# A bare crowd noun, optionally preceded by a quantifier phrase ("full of",
# "lots of", "a crowd of" …) and/or an article/quantifier ("a", "the", "some" …).
# Removed in place (not truncated) — crowd nouns typically sit at the tail, and the
# dangling-connector trim below cleans up whatever preposition introduced them.
_CROWD_RE = re.compile(
    r"(?:\b(?:full|lots|plenty|tons|crowds?|throngs?|groups?|swarms?)\s+of\s+)?"
    r"(?:\b(?:a|an|the|some|other|another|many|several|few)\s+)*"
    r"\b(?:passers-?by|crowds?|bystanders?|onlookers?|pedestrians?|spectators?|"
    r"other\s+people)\b",
    re.IGNORECASE,
)

# Trailing function-words / spatial connectors that dangle once a companion or crowd
# has been cut, e.g. "a busy plaza with" -> "a busy plaza", "surrounded by" -> "".
_TRAILING_CONNECTORS = {
    "with", "of", "and", "or", "but", "in", "on", "at", "to", "for", "from",
    "into", "a", "an", "the", "her", "his", "their", "its", "our", "your",
    "among", "amongst", "amid", "amidst", "around", "surrounded", "by", "beside",
    "near", "next", "alongside", "between", "toward", "towards", "past", "through",
}


def _trim_dangling(text: str) -> str:
    """Collapse whitespace, strip edge punctuation, and drop trailing connector
    words left dangling by a companion/crowd removal. Returns '' if nothing but
    connectors/punctuation remains."""
    cleaned = re.sub(r"\s+", " ", text).strip(" ,;.&-—\t")
    tokens = cleaned.split(" ") if cleaned else []
    while tokens and tokens[-1].lower().strip(",;.&-") in _TRAILING_CONNECTORS:
        tokens.pop()
    return " ".join(tokens).strip(" ,;.&-—\t")


def strip_companions(text: Optional[str]) -> Optional[str]:
    """
    Defensively remove multi-person phrasing from identity-free scene/action text
    so a solo character is never given company by a stray phrase. Case-insensitive.

    Two independent removals, then a dangling-connector cleanup:
      1. A ``with <someone>`` companion tail (partner/friend/another person/a group/
         a couple/strangers/…) truncates the text at that phrase — everything after
         ``with`` describes the removed person, so it goes too.
      2. Bare crowd nouns (passersby/crowd/bystanders/onlookers/other people),
         together with any quantifier ("full of …", "a crowd of …") or leading
         article/adjective-quantifier, are removed in place.
      3. Any connector word left dangling at the end (a bare "with", "of",
         "surrounded by", …) plus stray separators/whitespace are trimmed.

    Returns None if nothing meaningful survives (e.g. the whole phrase was the
    companion/crowd), so callers can simply skip the clause.

    Examples:
        "practicing a new dance with a partner" -> "practicing a new dance"
        "dancing with a partner"                -> "dancing"
        "a lively street full of passersby"     -> "a lively street"
            (NOT "a lively street full of" — the trailing "full of" is trimmed)
        "a busy plaza with onlookers"           -> "a busy plaza"
        "with a group of friends"               -> None
        "pouring her first coffee"              -> "pouring her first coffee"  (clean passthrough)
    """
    if text is None:
        return None

    cleaned = text
    m = _COMPANION_TAIL_RE.search(cleaned)
    if m:
        cleaned = cleaned[: m.start()]
    cleaned = _CROWD_RE.sub(" ", cleaned)
    cleaned = _trim_dangling(cleaned)
    return cleaned or None
