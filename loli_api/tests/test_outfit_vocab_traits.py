"""
Coverage tests for the WS-B trait-profile outfit vocabulary in services.outfit_vocab:
  * OUTFIT_STYLE_TAGS      — every garment (except NAKED) tagged with >=1 style;
  * outfits_for_styles     — the style -> garment-set helper;
  * OUTFIT_KEYWORD_PHRASES — a like/dislike phrase for EVERY OutfitType value, with no
                             bare generic color/fit adjective standing alone;
  * _GENERATION_POOL_STYLE_TAGS — index-aligned with _GENERATION_DEFAULT_CLOTHING_POOL.

Runs under pytest or directly: python loli_api/tests/test_outfit_vocab_traits.py
"""
import re

from models.enums import OutfitType, WardrobeStyleType
from services import outfit_vocab as ov


# ---------------------------------------------------------------------------
# OUTFIT_STYLE_TAGS
# ---------------------------------------------------------------------------
def test_every_non_naked_outfit_has_at_least_one_style_tag():
    missing = [o.value for o in OutfitType if o != OutfitType.NAKED and o not in ov.OUTFIT_STYLE_TAGS]
    assert not missing, f"OutfitType(s) missing a style tag: {missing}"
    for o, tags in ov.OUTFIT_STYLE_TAGS.items():
        assert isinstance(tags, frozenset) and len(tags) >= 1, f"{o.value} has no style tag"


def test_naked_is_absent_from_style_tags():
    assert OutfitType.NAKED not in ov.OUTFIT_STYLE_TAGS


def test_all_style_tag_values_are_valid_wardrobe_styles():
    valid = set(WardrobeStyleType)
    for o, tags in ov.OUTFIT_STYLE_TAGS.items():
        bad = tags - valid
        assert not bad, f"{o.value} has non-WardrobeStyleType tag(s): {bad}"


def test_every_wardrobe_style_tags_at_least_one_outfit():
    covered = set().union(*ov.OUTFIT_STYLE_TAGS.values())
    missing = set(WardrobeStyleType) - covered
    assert not missing, f"WardrobeStyleType(s) with no tagged outfit: {missing}"


def test_the_four_uniforms_are_tagged_professional():
    for u in (OutfitType.NURSE_UNIFORM, OutfitType.SCHOOL_UNIFORM,
              OutfitType.MILITARY_UNIFORM, OutfitType.CHEF_UNIFORM):
        assert WardrobeStyleType.PROFESSIONAL in ov.OUTFIT_STYLE_TAGS[u]


# ---------------------------------------------------------------------------
# outfits_for_styles
# ---------------------------------------------------------------------------
def test_outfits_for_styles_returns_tag_intersection():
    sporty = ov.outfits_for_styles([WardrobeStyleType.SPORTY])
    assert OutfitType.GYM_SET in sporty and OutfitType.YOGA_OUTFIT in sporty
    assert OutfitType.RED_EVENING_GOWN not in sporty
    # NAKED is never returned (absent from the tag map).
    assert OutfitType.NAKED not in ov.outfits_for_styles(list(WardrobeStyleType))


def test_outfits_for_styles_empty_and_string_tolerant():
    assert ov.outfits_for_styles([]) == set()
    assert ov.outfits_for_styles(None) == set()
    # raw string values coerce; unknown values are skipped, not raised.
    assert ov.outfits_for_styles(["elegant", "not-a-style"]) == ov.outfits_for_styles([WardrobeStyleType.ELEGANT])


def test_outfits_for_styles_union_over_multiple_styles():
    a = ov.outfits_for_styles([WardrobeStyleType.SPORTY])
    b = ov.outfits_for_styles([WardrobeStyleType.ELEGANT])
    assert ov.outfits_for_styles([WardrobeStyleType.SPORTY, WardrobeStyleType.ELEGANT]) == a | b


# ---------------------------------------------------------------------------
# OUTFIT_KEYWORD_PHRASES
# ---------------------------------------------------------------------------
def test_every_outfit_value_has_a_non_empty_keyword_phrase():
    for o in OutfitType:
        phrase = ov.OUTFIT_KEYWORD_PHRASES.get(o.value)
        assert phrase and phrase.strip(), f"no keyword phrase for {o.value}"


def test_keyword_phrases_have_no_extraneous_keys():
    valid = {o.value for o in OutfitType}
    extra = set(ov.OUTFIT_KEYWORD_PHRASES) - valid
    assert not extra, f"OUTFIT_KEYWORD_PHRASES has unknown keys: {extra}"


def test_keyword_phrases_avoid_bare_generic_color_fit_adjectives():
    # The canonical failure the plan guards: a dislike like "black coffee" must not be able
    # to nuke a garment via a generic adjective in its PHRASE. (The enum NAME may still
    # contain e.g. "black"; this only pins the hand-curated phrase.)
    banned = {"black", "white", "red", "blue", "grey", "gray", "tight", "fitted", "short", "long"}
    offenders = {}
    for value, phrase in ov.OUTFIT_KEYWORD_PHRASES.items():
        toks = set(re.split(r"[^a-z0-9]+", phrase.lower()))
        hit = toks & banned
        if hit:
            offenders[value] = hit
    assert not offenders, f"phrases contain bare generic color/fit adjectives: {offenders}"


def test_keyword_phrase_makes_gown_like_match_the_evening_gown():
    # "gown" must select RED_EVENING_GOWN's keyword set (via the phrase map), and NOT the
    # little_black_dress (no "gown" in its keywords) — the mechanism the planner leans on.
    from services.story_planner import _enum_keywords, _OUTFIT_PHRASE_MAP
    gown_kw = _enum_keywords(OutfitType.RED_EVENING_GOWN, _OUTFIT_PHRASE_MAP)
    lbd_kw = _enum_keywords(OutfitType.LITTLE_BLACK_DRESS, _OUTFIT_PHRASE_MAP)
    assert "gown" in gown_kw and "gown" not in lbd_kw


# ---------------------------------------------------------------------------
# _GENERATION_POOL_STYLE_TAGS alignment
# ---------------------------------------------------------------------------
def test_generation_pool_style_tags_index_aligned():
    pool = ov._GENERATION_DEFAULT_CLOTHING_POOL
    tags = ov._GENERATION_POOL_STYLE_TAGS
    assert set(pool.keys()) == set(tags.keys()), "level keys differ"
    for level in pool:
        assert len(pool[level]) == len(tags[level]), (
            f"{level.value}: pool has {len(pool[level])} entries but tags has {len(tags[level])}"
        )
    # Every tag entry is a frozenset of valid WardrobeStyleType (empty allowed for the nude entry).
    valid = set(WardrobeStyleType)
    for level, entries in tags.items():
        for i, fs in enumerate(entries):
            assert isinstance(fs, frozenset), f"{level.value}[{i}] is not a frozenset"
            assert fs <= valid, f"{level.value}[{i}] has invalid style(s): {fs - valid}"


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
