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

from models.enums import InteriorStyleType, PaletteType
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


# ---------------------------------------------------------------------------
# Home scenery consistency (WS-B trait profiles) — a character's OWN styled rooms.
# ---------------------------------------------------------------------------
# A TraitProfile carries an interior_style; for her HOME (and hotel) scenes the styled
# room description below REPLACES the generic LOCATION_PHRASES entry, so the same
# character's bedroom looks the same every batch AND matches her taste, while two
# differently-styled characters get visibly different homes. Curated visual text only —
# NEVER free LLM prose and NEVER identity (see build_scene_background_text). The keys are
# exactly the "home-ish" locations (every home_* LocationType + hotel_room); non-home
# locations are intentionally absent, so a styled lookup there returns None and the
# generic phrase stands. Coverage-tested: every InteriorStyleType x every home room.
_HOME_LIKE_LOCATIONS = frozenset({
    "home_bedroom", "home_living_room", "home_kitchen",
    "home_bathroom", "home_balcony", "home_office", "hotel_room",
})

INTERIOR_ROOM_PHRASES = {
    InteriorStyleType.COZY_BOHEMIAN: {
        "home_bedroom": "a cozy bohemian bedroom with layered textiles, hanging plants, warm string lights and a low wooden bed",
        "home_living_room": "a bohemian living room with a rattan sofa, macrame wall hangings, floor cushions and trailing plants",
        "home_kitchen": "a warm eclectic kitchen with open wooden shelves, hanging herbs, patterned tiles and terracotta pots",
        "home_bathroom": "a boho bathroom with a hanging fern, woven baskets, warm wood accents and a clawfoot tub",
        "home_balcony": "a snug plant-filled balcony with fairy lights, a rattan chair and draped textiles",
        "home_office": "a cozy bohemian study with a wooden desk, stacked books, a woven rug and hanging plants",
        "hotel_room": "a warm boho-styled hotel room with layered throws, woven textures and soft lamp light",
    },
    InteriorStyleType.MODERN_MINIMAL: {
        "home_bedroom": "a minimalist bedroom with clean lines, a low platform bed, neutral bedding and uncluttered surfaces",
        "home_living_room": "a modern minimalist living room with a low grey sofa, bare walls and a single statement plant",
        "home_kitchen": "a sleek minimalist kitchen with handleless matte cabinets, clear counters and a stone island",
        "home_bathroom": "a minimalist bathroom with a floating vanity, matte fixtures and a large frameless mirror",
        "home_balcony": "a clean modern balcony with a slim rail, a single lounge chair and unobstructed views",
        "home_office": "a minimalist home office with a slim desk, a single monitor and clean empty walls",
        "hotel_room": "a modern minimalist hotel room with a low bed, neutral tones and uncluttered surfaces",
    },
    InteriorStyleType.LUXURY_GLAM: {
        "home_bedroom": "a luxurious glam bedroom with a tufted velvet headboard, satin bedding, mirrored nightstands and a crystal chandelier",
        "home_living_room": "an opulent living room with plush velvet sofas, gold accents, marble tables and a crystal chandelier",
        "home_kitchen": "a glamorous kitchen with marble counters, gold hardware, mirrored splashback and polished surfaces",
        "home_bathroom": "a lavish marble bathroom with gold fixtures, a freestanding tub and a backlit mirror",
        "home_balcony": "an elegant balcony with marble flooring, plush seating, gold planters and city views",
        "home_office": "a plush glam study with a lacquered desk, velvet chair, gold lamp and mirrored shelves",
        "hotel_room": "a lavish upscale hotel suite with a tufted headboard, satin bedding and gilded accents",
    },
    InteriorStyleType.RUSTIC_WARM: {
        "home_bedroom": "a rustic bedroom with a reclaimed-wood bed, exposed beams, wool throws and a warm lamp",
        "home_living_room": "a warm rustic living room with a stone fireplace, worn leather sofa, wooden beams and knit blankets",
        "home_kitchen": "a farmhouse kitchen with butcher-block counters, open wood shelving, cast-iron pans and a ceramic sink",
        "home_bathroom": "a rustic bathroom with reclaimed-wood panelling, a stone basin and a vintage tub",
        "home_balcony": "a wooden balcony with a weathered bench, potted greenery and a woollen throw",
        "home_office": "a warm wood-panelled study with a heavy oak desk, brass lamp and shelves of old books",
        "hotel_room": "a warm rustic lodge-style room with a timber bed frame, wool blankets and a stone accent wall",
    },
    InteriorStyleType.SCANDINAVIAN_LIGHT: {
        "home_bedroom": "a bright Scandinavian bedroom with pale wood, white bedding, soft grey textiles and a leafy plant",
        "home_living_room": "an airy Scandinavian living room with a light-grey sofa, pale wood floor, white walls and greenery",
        "home_kitchen": "a bright Nordic kitchen with white cabinets, pale wood counters, clean lines and potted herbs",
        "home_bathroom": "a light Scandinavian bathroom with white tiles, pale wood accents and simple fixtures",
        "home_balcony": "a bright airy balcony with pale wood decking, a simple chair and a few green plants",
        "home_office": "a bright Nordic workspace with a pale wood desk, white walls, a simple chair and a small plant",
        "hotel_room": "a bright Scandinavian-style hotel room with pale wood, crisp white linens and soft daylight",
    },
    InteriorStyleType.INDUSTRIAL_LOFT: {
        "home_bedroom": "an industrial loft bedroom with exposed brick, a black metal bed frame, concrete floor and Edison bulbs",
        "home_living_room": "an industrial loft living room with exposed brick, a leather sofa, black steel shelving and pendant bulbs",
        "home_kitchen": "an industrial kitchen with stainless steel counters, black metal shelving, concrete and exposed pipes",
        "home_bathroom": "an industrial bathroom with concrete walls, black metal fixtures and an exposed-bulb mirror",
        "home_balcony": "a concrete loft balcony with black steel railings, a metal stool and city rooftops beyond",
        "home_office": "an industrial workspace with a reclaimed-wood-and-steel desk, exposed brick and a metal task lamp",
        "hotel_room": "an industrial-style hotel room with exposed brick, black metal fittings and Edison-bulb lighting",
    },
    InteriorStyleType.GIRLY_PASTEL: {
        "home_bedroom": "a soft girly bedroom with blush-pink bedding, fairy lights, plush cushions and pastel decor",
        "home_living_room": "a pastel living room with a blush velvet sofa, soft throw pillows, fairy lights and cute decor",
        "home_kitchen": "a pastel kitchen with mint cabinets, pink accessories, soft light and dainty crockery",
        "home_bathroom": "a girly pastel bathroom with pink tiles, soft towels, a round mirror and dainty bottles",
        "home_balcony": "a sweet pastel balcony with a blush chair, potted flowers and string fairy lights",
        "home_office": "a girly pastel desk nook with a white desk, pink accessories, fairy lights and cute stationery",
        "hotel_room": "a soft pastel-toned hotel room with blush linens, plush cushions and warm fairy lights",
    },
    InteriorStyleType.ARTSY_ECLECTIC: {
        "home_bedroom": "an eclectic artsy bedroom with a gallery wall, mismatched patterned textiles and a vintage headboard",
        "home_living_room": "an artsy eclectic living room with a gallery wall, a bold patterned rug, mixed vintage furniture and sculptures",
        "home_kitchen": "an eclectic kitchen with mismatched tiles, colorful crockery, quirky art and open shelving",
        "home_bathroom": "an artsy bathroom with patterned tiles, framed prints and a bold vintage mirror",
        "home_balcony": "a quirky balcony with mismatched chairs, colorful pots, string lights and hanging art",
        "home_office": "an eclectic studio-office with a paint-flecked desk, a gallery wall, sculptures and a patterned rug",
        "hotel_room": "an artsy boutique hotel room with a gallery wall, bold patterns and mixed vintage furnishings",
    },
}

# Palette -> a short color/light clause folded into the LIGHTING section of the scene
# background (see build_scene_background_text). One entry per PaletteType (coverage-tested).
PALETTE_PHRASES = {
    PaletteType.WARM_NEUTRALS: "a warm neutral palette of beige, cream and soft tan tones",
    PaletteType.SOFT_PASTELS: "soft pastel colors in blush, mint and powder-blue tones",
    PaletteType.BOLD_DARK: "a bold dark palette of deep charcoal and moody tones",
    PaletteType.EARTHY_GREEN: "earthy green and terracotta tones with natural wood",
    PaletteType.CRISP_WHITE: "a crisp bright palette of clean whites and cool light",
    PaletteType.JEWEL_TONES: "rich jewel tones of emerald, sapphire and ruby",
}


def _coerce_interior_style(v) -> Optional[InteriorStyleType]:
    if v is None:
        return None
    if isinstance(v, InteriorStyleType):
        return v
    try:
        return InteriorStyleType(getattr(v, "value", v))
    except (ValueError, TypeError):
        return None


def _coerce_palette(v) -> Optional[PaletteType]:
    if v is None:
        return None
    if isinstance(v, PaletteType):
        return v
    try:
        return PaletteType(getattr(v, "value", v))
    except (ValueError, TypeError):
        return None


def styled_room_phrase(interior_style, location) -> Optional[str]:
    """
    The character's styled room description for `location` under `interior_style`, or
    None when the style is unknown or the location is not a home-ish room (so the caller
    falls back to the generic LOCATION_PHRASES entry). interior_style/location accept an
    enum or its raw value.
    """
    style = _coerce_interior_style(interior_style)
    if style is None:
        return None
    loc_val = getattr(location, "value", location)
    rooms = INTERIOR_ROOM_PHRASES.get(style)
    if not rooms:
        return None
    return rooms.get(loc_val)


def palette_phrase(color_palette) -> str:
    """Short color/light clause for a PaletteType (or value); '' when unknown/None."""
    pal = _coerce_palette(color_palette)
    return PALETTE_PHRASES.get(pal, "") if pal is not None else ""


# The home-ish locations that carry a character's styled room + color palette,
# DERIVED from INTERIOR_ROOM_PHRASES (single source of truth: exactly the rooms every
# interior style defines) so a home room added there is covered here automatically.
# The styled-room replacement is already self-gating (styled_room_phrase returns None
# off-home), but the PALETTE clause is not — build_scene_background_text appends it
# unconditionally — so scene_mapper gates BOTH on this set to stop a character's
# "bold dark palette" being stamped over a midday cafe/street (WS-S palette scope).
HOME_LIKE_LOCATIONS = frozenset().union(
    *(set(rooms) for rooms in INTERIOR_ROOM_PHRASES.values())
) if INTERIOR_ROOM_PHRASES else frozenset()


def is_home_like_location(location) -> bool:
    """True if `location` (enum or raw value) is a home-ish room that carries a
    character's styled-room + color-palette text; False for every other location so
    callers keep the generic phrase AND drop the palette clause."""
    return getattr(location, "value", location) in HOME_LIKE_LOCATIONS


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
    lead_text: Optional[str] = None,
    interior_style=None,
    color_palette=None,
) -> str:
    """
    Compose location + time + lighting (+ optional mood + free text) into the
    scene free-text consumed by background.build_background_prompt(). Contains NO
    persona identity language.

    ``lead_text`` (opt-in, C3 setting-led scenery): an AI-authored scene sentence —
    the story director's ``setting`` — placed FIRST, so the authored description
    LEADS the composition and the location enum phrase follows as an anchor, then
    time/lighting/mood as before. Only scene_mapper passes it (story batches);
    every other caller omits it and gets the location-first composition unchanged.

    ``interior_style`` / ``color_palette`` (opt-in, WS-B home scenery): the character's
    saved taste. For a HOME/HOTEL location the styled INTERIOR_ROOM_PHRASES text REPLACES
    the generic location phrase (so her home stays visually consistent AND personal); for
    any other location the generic phrase stands. The palette clause (if any) joins the
    LIGHTING section. Both default None -> byte-identical to the pre-trait-profile output,
    so every non-batch caller is unaffected.
    """
    parts: List[str] = []
    if lead_text and lead_text.strip():
        parts.append(lead_text.strip())
    # Styled home room REPLACES the generic location phrase for home-ish locations;
    # elsewhere (styled_room_phrase returns None) the generic phrase stands.
    loc = styled_room_phrase(interior_style, location) if interior_style is not None else None
    if not loc:
        loc = location_phrase(location)
    if loc:
        parts.append(loc)
    t = phrase(TIME_OF_DAY_PHRASES, time_of_day)
    if t:
        parts.append(t)
    li = phrase(LIGHTING_PHRASES, lighting)
    if li:
        parts.append(li)
    # Palette clause joins the lighting section (right after the lighting phrase).
    pal = palette_phrase(color_palette) if color_palette is not None else ""
    if pal:
        parts.append(pal)
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
