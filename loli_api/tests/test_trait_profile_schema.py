"""
Tests for TraitProfile schema (WS-B): tolerant coerce (difflib repair + drop
unknowns), per-field caps, NAKED-strip everywhere, never_wears-beats-favorites
overlap, de-dupe, and display-text clamping.

Runs under pytest or directly: python loli_api/tests/test_trait_profile_schema.py
"""
from models.enums import (
    DemeanorType,
    InteriorStyleType,
    OutfitType,
    WardrobeStyleType,
    ZodiacType,
)
from models.trait_profile import (
    MAX_AVOIDED_LOCATIONS,
    MAX_DEMEANOR,
    MAX_DISLIKES,
    MAX_DISPLAY_HOBBIES,
    MAX_DISPLAY_OCCUPATION_CHARS,
    MAX_DISPLAY_PERSONALITY,
    MAX_FAVORITE_LOCATIONS,
    MAX_FAVORITE_OUTFITS,
    MAX_LIKES,
    MAX_NEVER_WEARS,
    MAX_QUIRKS,
    MAX_SHORT_DESCRIPTION_CHARS,
    MAX_WARDROBE_STYLES,
    TraitProfile,
)


# --- clean round-trip ---
def test_coerce_clean_values():
    tp = TraitProfile.coerce({
        "wardrobe_styles": ["elegant", "glamorous"],
        "demeanor": ["sultry"],
        "interior_style": "luxury_glam",
        "color_palette": "jewel_tones",
        "zodiac": "leo",
        "likes": ["champagne", "spa days"],
    })
    assert tp.wardrobe_styles == [WardrobeStyleType.ELEGANT, WardrobeStyleType.GLAMOROUS]
    assert tp.demeanor == [DemeanorType.SULTRY]
    assert tp.interior_style == InteriorStyleType.LUXURY_GLAM
    assert tp.zodiac == ZodiacType.LEO
    assert tp.likes == ["champagne", "spa days"]


# --- caps on every list field ---
def test_coerce_caps_every_list_field():
    tp = TraitProfile.coerce({
        "wardrobe_styles": [w.value for w in WardrobeStyleType],           # 11 -> 3
        "favorite_outfits": ["red_evening_gown", "little_black_dress", "cocktail_dress",
                              "bodycon_dress", "velvet_dress", "satin_slip_dress"],  # 6 -> 5
        # 12 outfits, chosen NOT to overlap the favorites above (overlap has its own test).
        "never_wears": ["hoodie_joggers", "flannel_shirt", "crop_top_cargo", "yoga_outfit",
                        "tennis_outfit", "running_gear", "gym_set", "one_piece_swimsuit",
                        "leather_jacket", "trench_coat", "puffer_jacket", "fur_coat"],  # 12 -> 8
        "favorite_locations": ["beach", "park", "cafe", "bar", "nightclub", "rooftop"],  # 6 -> 5
        "avoided_locations": ["office", "hospital_ward", "classroom", "gym", "lab",
                               "library", "salon", "stage", "bar", "cafe"],  # 10 -> 8
        "demeanor": ["shy", "confident", "playful"],                      # 3 -> 2
        "likes": [f"like{i}" for i in range(20)],                         # 20 -> 12
        "dislikes": [f"dis{i}" for i in range(20)],                       # 20 -> 12
        "quirks": [f"quirk{i}" for i in range(10)],                       # 10 -> 6
    })
    assert len(tp.wardrobe_styles) == MAX_WARDROBE_STYLES
    assert len(tp.favorite_outfits) == MAX_FAVORITE_OUTFITS
    assert len(tp.never_wears) == MAX_NEVER_WEARS
    assert len(tp.favorite_locations) == MAX_FAVORITE_LOCATIONS
    assert len(tp.avoided_locations) == MAX_AVOIDED_LOCATIONS
    assert len(tp.demeanor) == MAX_DEMEANOR
    assert len(tp.likes) == MAX_LIKES
    assert len(tp.dislikes) == MAX_DISLIKES
    assert len(tp.quirks) == MAX_QUIRKS


# --- NAKED stripped everywhere ---
def test_naked_stripped_from_favorites_and_never_wears():
    tp = TraitProfile.coerce({
        "favorite_outfits": ["naked", "bikini"],
        "never_wears": ["naked", "fur_coat"],
    })
    assert OutfitType.NAKED not in tp.favorite_outfits
    assert OutfitType.NAKED not in tp.never_wears
    assert OutfitType.BIKINI in tp.favorite_outfits
    assert OutfitType.FUR_COAT in tp.never_wears


def test_naked_stripped_on_direct_construction():
    # Not just coerce — the field validators strip NAKED on plain construction too.
    tp = TraitProfile(favorite_outfits=[OutfitType.NAKED, OutfitType.BIKINI])
    assert tp.favorite_outfits == [OutfitType.BIKINI]


# --- never_wears beats favorites ---
def test_never_wears_beats_favorites():
    tp = TraitProfile.coerce({
        "favorite_outfits": ["bikini", "red_evening_gown"],
        "never_wears": ["bikini"],
    })
    assert OutfitType.BIKINI not in tp.favorite_outfits
    assert OutfitType.RED_EVENING_GOWN in tp.favorite_outfits
    assert OutfitType.BIKINI in tp.never_wears


# --- de-dupe ---
def test_dedupe_enum_and_str_lists():
    tp = TraitProfile.coerce({
        "wardrobe_styles": ["elegant", "elegant", "glamorous"],
        "likes": ["Coffee", "coffee", "tea"],  # case-insensitive de-dupe
    })
    assert tp.wardrobe_styles == [WardrobeStyleType.ELEGANT, WardrobeStyleType.GLAMOROUS]
    assert tp.likes == ["Coffee", "tea"]


# --- difflib repair + drop unknowns ---
def test_coerce_repairs_near_miss_and_drops_unknown():
    tp = TraitProfile.coerce({
        "zodiac": "leoo",                       # near-miss -> leo
        "interior_style": "not-a-real-style",   # unknown -> None
        "wardrobe_styles": ["elegant", "xyzzy"],  # elegant -> elegant; xyzzy dropped
    })
    assert tp.zodiac == ZodiacType.LEO
    assert tp.interior_style is None
    assert tp.wardrobe_styles == [WardrobeStyleType.ELEGANT]


# --- text clamp ---
def test_backstory_and_home_description_clamped():
    tp = TraitProfile.coerce({
        "backstory": "x" * 2000,
        "home_description": "y" * 2000,
    })
    assert len(tp.backstory) == 800
    assert len(tp.home_description) == 400


# --- tolerant of garbage input ---
def test_coerce_tolerates_non_dict_and_none():
    for bad in (None, [], "garbage", 42):
        tp = TraitProfile.coerce(bad)
        assert tp.wardrobe_styles == []
        assert tp.interior_style is None
        assert tp.likes == []


def test_coerce_scalar_into_list_field():
    # A single string where a list is expected is wrapped, not dropped.
    tp = TraitProfile.coerce({"wardrobe_styles": "elegant", "likes": "coffee"})
    assert tp.wardrobe_styles == [WardrobeStyleType.ELEGANT]
    assert tp.likes == ["coffee"]


# --- public profile card ---
def test_card_text_fields_clamped():
    tp = TraitProfile.coerce({
        "short_description": "x" * 500,     # -> 220
        "display_occupation": "y" * 100,    # -> 40
    })
    assert len(tp.short_description) == MAX_SHORT_DESCRIPTION_CHARS
    assert len(tp.display_occupation) == MAX_DISPLAY_OCCUPATION_CHARS


def test_card_display_lists_capped_and_item_clamped():
    tp = TraitProfile.coerce({
        "display_personality": ["a" * 40, "Spoiled", "Charming", "Bold", "Witty"],  # 5 -> 4, item -> 24
        "display_hobbies": ["b" * 60, "Shopping", "Parties", "Travel", "Wine", "Art"],  # 6 -> 5, item -> 32
    })
    assert len(tp.display_personality) == MAX_DISPLAY_PERSONALITY
    assert all(len(x) <= 24 for x in tp.display_personality)
    assert len(tp.display_hobbies) == MAX_DISPLAY_HOBBIES
    assert all(len(x) <= 32 for x in tp.display_hobbies)


def test_card_language_defaults_to_english():
    assert TraitProfile.coerce({}).language == "English"
    assert TraitProfile.coerce({"language": ""}).language == "English"
    assert TraitProfile.coerce({"language": None}).language == "English"
    assert TraitProfile.coerce({"language": "Spanish"}).language == "Spanish"
    # direct construction with a None language also defaults (mode=before validator)
    assert TraitProfile(language=None).language == "English"


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
