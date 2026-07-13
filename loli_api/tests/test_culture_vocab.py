"""
Coverage + hygiene tests for the culture/subculture vocabulary (services.culture_vocab).

Guards the invariants that keep CultureType safe and consistent:
  * COVERAGE: every CultureType has exactly one CULTURE_SPECS entry and vice versa
    (no orphan keys), and each spec's fields are non-empty / well-formed.
  * REFERENTIAL INTEGRITY: every biased enum a spec points at is a real member, and
    the outfit/interior/palette references resolve in the maps that own them
    (outfit_vocab.OUTFIT_STYLE_TAGS, scene_vocab.INTERIOR_ROOM_PHRASES /
    PALETTE_PHRASES); favored_outfits never include NAKED.
  * PHRASE HYGIENE: render phrases describe makeup/styling only — never hair color/
    texture, eye color, skin tone, age-down words, or banned glamour filler
    (prompt_constants.has_banned_style_words) or concrete garment nouns.
  * DEGRADE-SAFE ACCESSORS: unknown / None inputs degrade to ""/None, and string /
    enum / case-insensitive lookups agree.

Runs under pytest or directly: python loli_api/tests/test_culture_vocab.py
"""
import re

from models.enums import (
    CultureType,
    WardrobeStyleType,
    OutfitType,
    LocationType,
    PoseType,
    InteriorStyleType,
    PaletteType,
    DemeanorType,
)
from services import culture_vocab as cv
from services.culture_vocab import CULTURE_SPECS, CultureSpec
from services import outfit_vocab, scene_vocab, prompt_constants


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------
def test_every_culture_has_exactly_one_spec_and_no_orphans():
    assert set(CULTURE_SPECS) == set(CultureType)
    assert len(CULTURE_SPECS) == len(CultureType) == 16
    for c, spec in CULTURE_SPECS.items():
        assert isinstance(spec, CultureSpec), c


def test_spec_text_fields_are_non_empty():
    for c, spec in CULTURE_SPECS.items():
        assert spec.label and spec.label.strip(), f"{c.value} has no label"
        assert spec.render_phrase and spec.render_phrase.strip(), f"{c.value} has no render_phrase"
        assert spec.persona_hint and spec.persona_hint.strip(), f"{c.value} has no persona_hint"
        assert spec.likes and all(l.strip() for l in spec.likes), f"{c.value} has empty likes"


# ---------------------------------------------------------------------------
# referential integrity
# ---------------------------------------------------------------------------
def test_wardrobe_styles_are_1_to_3_valid_members():
    valid = set(WardrobeStyleType)
    for c, spec in CULTURE_SPECS.items():
        assert isinstance(spec.wardrobe_styles, frozenset)
        assert 1 <= len(spec.wardrobe_styles) <= 3, f"{c.value} wardrobe_styles count"
        assert spec.wardrobe_styles <= valid, f"{c.value} has non-WardrobeStyleType: {spec.wardrobe_styles - valid}"


def test_favored_outfits_are_valid_never_naked_and_tagged():
    valid = set(OutfitType)
    for c, spec in CULTURE_SPECS.items():
        assert spec.favored_outfits, f"{c.value} has no favored_outfits"
        assert spec.favored_outfits <= valid, f"{c.value} has non-OutfitType(s)"
        assert OutfitType.NAKED not in spec.favored_outfits, f"{c.value} favors NAKED"
        # every favored outfit is a real garment carried in the style-tag map
        for o in spec.favored_outfits:
            assert o in outfit_vocab.OUTFIT_STYLE_TAGS, f"{c.value}: {o.value} not in OUTFIT_STYLE_TAGS"


def test_favored_locations_are_valid_members():
    valid = set(LocationType)
    for c, spec in CULTURE_SPECS.items():
        assert spec.favored_locations, f"{c.value} has no favored_locations"
        assert spec.favored_locations <= valid, f"{c.value} has non-LocationType(s)"


def test_favored_poses_are_valid_members():
    valid = set(PoseType)
    for c, spec in CULTURE_SPECS.items():
        assert isinstance(spec.favored_poses, frozenset)
        assert spec.favored_poses <= valid, f"{c.value} has non-PoseType(s)"


def test_favored_poses_are_sparse_only_where_specified():
    # Exactly the three cultures the plan calls out carry poses; all others are empty.
    posed = {c.value for c, spec in CULTURE_SPECS.items() if spec.favored_poses}
    assert posed == {"sporty_gym", "cottagecore", "pinup_rockabilly"}
    assert CULTURE_SPECS[CultureType.SPORTY_GYM].favored_poses == frozenset({PoseType.JOGGING, PoseType.SQUATTING})
    assert CULTURE_SPECS[CultureType.COTTAGECORE].favored_poses == frozenset(
        {PoseType.SITTING, PoseType.EATING, PoseType.COOKING}
    )
    assert CULTURE_SPECS[CultureType.PINUP_ROCKABILLY].favored_poses == frozenset(
        {PoseType.STANDING_LEANING, PoseType.KNEELING}
    )


def test_interior_style_is_a_key_of_interior_room_phrases():
    for c, spec in CULTURE_SPECS.items():
        assert isinstance(spec.interior_style, InteriorStyleType)
        assert spec.interior_style in scene_vocab.INTERIOR_ROOM_PHRASES, (
            f"{c.value}: {spec.interior_style} missing from INTERIOR_ROOM_PHRASES"
        )


def test_color_palette_is_a_key_of_palette_phrases():
    for c, spec in CULTURE_SPECS.items():
        assert isinstance(spec.color_palette, PaletteType)
        assert spec.color_palette in scene_vocab.PALETTE_PHRASES, (
            f"{c.value}: {spec.color_palette} missing from PALETTE_PHRASES"
        )


def test_demeanor_is_1_to_2_valid_members():
    valid = set(DemeanorType)
    for c, spec in CULTURE_SPECS.items():
        assert isinstance(spec.demeanor, tuple)
        assert 1 <= len(spec.demeanor) <= 2, f"{c.value} demeanor count"
        assert set(spec.demeanor) <= valid, f"{c.value} has non-DemeanorType(s)"


# ---------------------------------------------------------------------------
# render-phrase hygiene
# ---------------------------------------------------------------------------
# Word-boundary anchored so legitimate makeup words survive (a culture phrase may
# say "brown eyeshadow"/"black eyeliner"/"pink lips" — makeup colors — but must
# never name the person's actual hair color/texture, eye color, skin tone, or an
# age-down word, and must carry no garment noun; clothing is owned by the outfit
# clause). Deliberately NOT banned: bare "black"/"brown"/"pink"/"red" (makeup
# colors), "skin"/"complexion" (finish, not a tone), or bare "girl" ("e-girl"/
# "gyaru" are culture names, not age-down words).
_BANNED_PATTERNS = [
    # hair color / texture / noun
    r"\bblonde?\b", r"\bbrunette\b", r"\bredhead", r"\bauburn\b", r"\bginger\b",
    r"\bcurly\b", r"\bwavy\b", r"\bcoily\b", r"\bbraided\b", r"\bdreadlock",
    r"\bhair\b", r"\bhaired\b", r"\bhairstyle\b",
    # eye color
    r"\beyes?\b", r"\beyed\b", r"\bhazel\b", r"\bblue\b", r"\bgreen\b",
    # skin tone
    r"\bpale\b", r"\bfair\b", r"\btanned?\b", r"\bolive\b", r"\bebony\b",
    r"\bbronzed?\b", r"\bporcelain\b", r"\balabaster\b", r"\bsallow\b",
    r"\bdark skin\b", r"\blight skin\b",
    # age-down
    r"\bteen", r"\bteenage", r"\badolescent\b", r"\bchildlike\b", r"\bgirlish\b",
    r"\bpetite\b", r"\byouthful\b", r"\byoung\b", r"\bschoolgirl\b",
    # concrete garment nouns (clothing is owned by the outfit clause)
    r"\bdress\b", r"\bgown\b", r"\bskirt\b", r"\bjacket\b", r"\bcoat\b",
    r"\bcorset\b", r"\bfishnet", r"\blingerie\b", r"\bbodysuit\b", r"\bbikini\b",
    r"\bjeans\b", r"\btrousers\b", r"\bblouse\b", r"\bhoodie\b", r"\bleggings\b",
    r"\bstockings\b", r"\bsweater\b", r"\bcardigan\b",
]


def _violations(text: str):
    low = text.lower()
    return [p for p in _BANNED_PATTERNS if re.search(p, low)]


def test_render_phrases_name_no_identity_or_garment_words():
    for c, spec in CULTURE_SPECS.items():
        hits = _violations(spec.render_phrase)
        assert not hits, f"CULTURE_SPECS[{c.value}].render_phrase trips {hits}: {spec.render_phrase!r}"


def test_render_phrases_have_no_banned_glamour_filler():
    for c, spec in CULTURE_SPECS.items():
        assert not prompt_constants.has_banned_style_words(spec.render_phrase), (
            f"CULTURE_SPECS[{c.value}].render_phrase has banned style filler: {spec.render_phrase!r}"
        )


def test_render_phrases_open_with_styling_clause():
    for c, spec in CULTURE_SPECS.items():
        assert "styling," in spec.render_phrase.lower(), f"{c.value} render_phrase missing styling opener"


def test_hygiene_guard_fires_and_has_no_false_positive_on_legit_makeup_words():
    # Guard the guard: the ban list catches real hair/eye/skin/age/garment phrasing ...
    for bad in ("long blonde hair", "bright green eyes", "pale olive skin",
                "youthful teen look", "a fitted black dress", "curly waves"):
        assert _violations(bad), f"ban list failed to catch: {bad!r}"
    # ... but NOT the legitimate makeup/jewelry vocabulary the phrases rely on.
    for legit in ("glossy pink lips", "soft brown eyeshadow", "black winged eyeliner",
                  "matte red lips", "e-girl styling", "gold hoop earrings",
                  "silver jewelry", "matte complexion makeup", "beaded necklaces"):
        assert not _violations(legit), f"false positive on legit makeup phrase: {legit!r}"


# ---------------------------------------------------------------------------
# degrade-safe accessors
# ---------------------------------------------------------------------------
def test_render_phrase_degrades_on_unknown_and_none():
    assert cv.culture_render_phrase(None) == ""
    assert cv.culture_render_phrase("not_a_culture") == ""
    assert cv.culture_render_phrase("") == ""


def test_spec_for_degrades_and_agrees_across_enum_string_and_case():
    assert cv.spec_for(None) is None
    assert cv.spec_for("klingon") is None
    # enum, exact value, upper-case, and hyphen-for-underscore all resolve to the same spec
    ref = cv.spec_for(CultureType.E_GIRL)
    assert ref is not None
    assert cv.spec_for("e_girl") is ref
    assert cv.spec_for("E_GIRL") is ref
    assert cv.spec_for(" e-girl ") is ref


def test_accessors_agree_for_string_enum_and_case():
    for c in CultureType:
        assert cv.culture_render_phrase(c) == cv.culture_render_phrase(c.value)
        assert cv.culture_render_phrase(c.value.upper()) == cv.culture_render_phrase(c)
        assert cv.culture_wardrobe_styles(c) == cv.culture_wardrobe_styles(c.value)
        assert cv.culture_favored_outfits(c) == cv.culture_favored_outfits(c.value)
        assert cv.culture_favored_locations(c) == cv.culture_favored_locations(c.value)
        assert cv.culture_favored_poses(c) == cv.culture_favored_poses(c.value)
        assert cv.culture_interior_style(c) == cv.culture_interior_style(c.value)
        assert cv.culture_color_palette(c) == cv.culture_color_palette(c.value)
        assert cv.culture_demeanor(c) == cv.culture_demeanor(c.value)


def test_typed_accessors_degrade_to_empty_or_none():
    assert cv.culture_wardrobe_styles(None) == set()
    assert cv.culture_favored_outfits("nope") == set()
    assert cv.culture_favored_locations(None) == set()
    assert cv.culture_favored_poses("nope") == set()
    assert cv.culture_interior_style(None) is None
    assert cv.culture_color_palette("nope") is None
    assert cv.culture_demeanor(None) == []
    assert cv.culture_hint(None) == ""
    assert cv.culture_label("nope") == ""


def test_culture_hint_is_label_dash_persona_hint():
    spec = CULTURE_SPECS[CultureType.GOTH]
    assert cv.culture_hint(CultureType.GOTH) == f"{spec.label} — {spec.persona_hint}"
    assert cv.culture_hint("goth").startswith("Goth — ")


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
