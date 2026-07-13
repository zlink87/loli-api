"""
Tests for the WS-B home-scenery vocab in services.scene_vocab:
  * INTERIOR_ROOM_PHRASES — full (style x home-room) coverage matrix;
  * PALETTE_PHRASES        — one clause per PaletteType;
  * build_scene_background_text — styled room REPLACES the generic phrase for home-ish
    locations, leaves non-home locations on the generic phrase, and folds the palette
    clause into the lighting section; both params default None -> unchanged output.

Runs under pytest or directly: python loli_api/tests/test_scene_vocab_home.py
"""
from models.enums import (
    LocationType, InteriorStyleType, PaletteType, TimeOfDayType, LightingType,
)
from services import scene_vocab as sv


# The home-ish rooms every interior style must describe (every home_* + hotel_room).
_HOME_ROOMS = [
    LocationType.HOME_BEDROOM, LocationType.HOME_LIVING_ROOM, LocationType.HOME_KITCHEN,
    LocationType.HOME_BATHROOM, LocationType.HOME_BALCONY, LocationType.HOME_OFFICE,
    LocationType.HOTEL_ROOM,
]
_NON_HOME = [
    LocationType.OFFICE, LocationType.CAFE, LocationType.BEACH, LocationType.GYM,
    LocationType.NIGHTCLUB, LocationType.CITY_STREET,
]


# ---------------------------------------------------------------------------
# Coverage matrices
# ---------------------------------------------------------------------------
def test_interior_room_phrases_cover_full_style_x_room_matrix():
    for style in InteriorStyleType:
        rooms = sv.INTERIOR_ROOM_PHRASES.get(style)
        assert rooms is not None, f"no room map for interior style {style.value}"
        for room in _HOME_ROOMS:
            text = rooms.get(room.value)
            assert text and len(text.strip()) >= 20, (
                f"{style.value} x {room.value} has a missing/short room phrase: {text!r}"
            )


def test_interior_room_phrases_have_no_non_home_keys():
    home_vals = {r.value for r in _HOME_ROOMS}
    for style, rooms in sv.INTERIOR_ROOM_PHRASES.items():
        extra = set(rooms) - home_vals
        assert not extra, f"{style.value} has non-home room keys: {extra}"


def test_palette_phrases_cover_every_palette():
    for pal in PaletteType:
        text = sv.PALETTE_PHRASES.get(pal)
        assert text and len(text.strip()) >= 10, f"missing/short palette clause for {pal.value}"


def test_home_bedroom_text_differs_across_styles():
    # Two differently-styled characters must get visibly different bedrooms.
    beds = {sv.styled_room_phrase(s, LocationType.HOME_BEDROOM) for s in InteriorStyleType}
    assert len(beds) == len(list(InteriorStyleType)), "some interior styles share a bedroom phrase"


# ---------------------------------------------------------------------------
# styled_room_phrase helper
# ---------------------------------------------------------------------------
def test_styled_room_phrase_home_vs_non_home():
    # Home-ish location -> a styled phrase; non-home -> None (generic phrase stands).
    assert sv.styled_room_phrase(InteriorStyleType.LUXURY_GLAM, LocationType.HOME_BEDROOM)
    assert sv.styled_room_phrase(InteriorStyleType.LUXURY_GLAM, LocationType.HOTEL_ROOM)
    assert sv.styled_room_phrase(InteriorStyleType.LUXURY_GLAM, LocationType.CAFE) is None
    assert sv.styled_room_phrase(None, LocationType.HOME_BEDROOM) is None
    # tolerant of raw string values
    assert sv.styled_room_phrase("luxury_glam", "home_bedroom")


# ---------------------------------------------------------------------------
# build_scene_background_text — the styled-room replacement + palette clause
# ---------------------------------------------------------------------------
def test_styled_room_replaces_generic_for_home_location():
    styled = sv.build_scene_background_text(
        location=LocationType.HOME_BEDROOM,
        interior_style=InteriorStyleType.LUXURY_GLAM,
    )
    assert sv.styled_room_phrase(InteriorStyleType.LUXURY_GLAM, LocationType.HOME_BEDROOM) in styled
    # The generic bedroom phrase is REPLACED, not appended.
    assert sv.LOCATION_PHRASES["home_bedroom"] not in styled


def test_generic_phrase_stands_for_non_home_location():
    styled = sv.build_scene_background_text(
        location=LocationType.CAFE,
        interior_style=InteriorStyleType.LUXURY_GLAM,
    )
    # A non-home location ignores interior_style and keeps its generic phrase.
    assert sv.LOCATION_PHRASES["cafe"] in styled


def test_palette_clause_present_and_after_lighting():
    styled = sv.build_scene_background_text(
        location=LocationType.HOME_LIVING_ROOM,
        lighting=LightingType.CANDLELIT,
        interior_style=InteriorStyleType.COZY_BOHEMIAN,
        color_palette=PaletteType.WARM_NEUTRALS,
    )
    pal = sv.PALETTE_PHRASES[PaletteType.WARM_NEUTRALS]
    light = sv.LIGHTING_PHRASES["candlelit"]
    assert pal in styled and light in styled
    assert styled.index(light) < styled.index(pal), "palette clause should follow the lighting phrase"


def test_none_style_and_palette_are_byte_identical_to_legacy():
    kw = dict(location=LocationType.HOME_BEDROOM, time_of_day=TimeOfDayType.NIGHT,
              lighting=LightingType.CANDLELIT, free_text="a tail")
    legacy = sv.build_scene_background_text(**kw)
    with_none = sv.build_scene_background_text(**kw, interior_style=None, color_palette=None)
    assert legacy == with_none
    # And the legacy output still leads with the generic home phrase.
    assert legacy.startswith(sv.LOCATION_PHRASES["home_bedroom"])


# ---------------------------------------------------------------------------
# scene_mood_phrase — mood garnish capped to ONE phrase (PLANNER COHERENCE)
# ---------------------------------------------------------------------------
def test_scene_mood_phrase_returns_at_most_one_phrase():
    # Was: 1 personality + up to 3 kink phrases joined ("...expression, tense restrained
    # mood, playful power-play mood") — too much garnish, polluted the background step.
    # Now: exactly ONE phrase from the maps (or "").
    all_phrases = set(sv.PERSONALITY_PHRASES.values()) | set(sv.KINK_PHRASES.values())
    out = sv.scene_mood_phrase(kinks=["bondage", "spanking", "edging"], personality="nympho")
    assert out in all_phrases, f"expected a single mood phrase, got {out!r}"
    # No kink phrase may have been appended after the personality phrase.
    assert sv.KINK_PHRASES["bondage"] not in out
    assert sv.KINK_PHRASES["spanking"] not in out


def test_scene_mood_phrase_personality_wins_over_kinks():
    out = sv.scene_mood_phrase(kinks=["bondage", "spanking"], personality="nympho")
    assert out == sv.PERSONALITY_PHRASES["nympho"]


def test_scene_mood_phrase_first_kink_when_no_personality():
    # personality None -> the FIRST kink that maps to a phrase (order-sensitive).
    assert sv.scene_mood_phrase(kinks=["bondage", "spanking"], personality=None) \
        == sv.KINK_PHRASES["bondage"]
    assert sv.scene_mood_phrase(kinks=["spanking", "bondage"], personality=None) \
        == sv.KINK_PHRASES["spanking"]


def test_scene_mood_phrase_empty_when_nothing():
    assert sv.scene_mood_phrase(None, None) == ""
    assert sv.scene_mood_phrase([], None) == ""


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
