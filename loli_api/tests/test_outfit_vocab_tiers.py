"""
Tests for OUTFIT_DESCRIPTIONS / _GENERATION_DEFAULT_CLOTHING tier completeness
against the 5-level NudityLevel ladder (LOW < SUGGESTIVE < MEDIUM < REVEALING <
HIGH).

Regression guard: build_prompt() (api/v1/endpoints/outfit.py) and
generation_outfit_clause() (services/outfit_vocab.py) both do a bare/`.get()`
dict lookup keyed by NudityLevel and fall back to LOW's text when a key is
missing. Before this suite, OUTFIT_DESCRIPTIONS only had LOW/MEDIUM/HIGH per
outfit, so a request for SUGGESTIVE or REVEALING would silently render as LOW
(fully clothed) instead of the intended escalation. These tests fail loudly if
that gap reopens — e.g. a new OutfitType added without all 5 tiers.

Runs under pytest or directly: python tests/test_outfit_vocab_tiers.py
"""
from models.enums import OutfitType, NudityLevel
from services.outfit_vocab import OUTFIT_DESCRIPTIONS, _GENERATION_DEFAULT_CLOTHING

_ALL_LEVELS = set(NudityLevel)
_MIN_LEN = 20


# ---------------------------------------------------------------------------
# OUTFIT_DESCRIPTIONS completeness — every OutfitType x every NudityLevel
# ---------------------------------------------------------------------------
def test_every_outfit_type_is_present_in_outfit_descriptions():
    missing = [o.value for o in OutfitType if o not in OUTFIT_DESCRIPTIONS]
    assert not missing, f"OutfitType(s) missing from OUTFIT_DESCRIPTIONS: {missing}"


def test_every_outfit_has_all_five_nudity_levels():
    incomplete = {}
    for outfit in OutfitType:
        keys = set(OUTFIT_DESCRIPTIONS.get(outfit, {}).keys())
        if keys != _ALL_LEVELS:
            incomplete[outfit.value] = sorted(l.value for l in (_ALL_LEVELS - keys))
    assert not incomplete, f"outfits missing tier keys: {incomplete}"


def test_no_outfit_type_dict_has_extra_unexpected_keys():
    # Guards against typos (e.g. a stray string key) that `set(...) != levels`
    # in the check above would also catch, but this pins the failure mode.
    for outfit in OutfitType:
        keys = set(OUTFIT_DESCRIPTIONS[outfit].keys())
        extra = keys - _ALL_LEVELS
        assert not extra, f"{outfit.value} has unexpected keys: {extra}"


# ---------------------------------------------------------------------------
# String sanity — every one of the 47 * 5 = 235 description strings
# ---------------------------------------------------------------------------
def test_every_description_string_is_non_empty_and_reasonably_long():
    too_short = []
    for outfit in OutfitType:
        for level, text in OUTFIT_DESCRIPTIONS[outfit].items():
            if not isinstance(text, str) or len(text.strip()) < _MIN_LEN:
                too_short.append((outfit.value, level.value, text))
    assert not too_short, f"suspiciously short/empty description(s): {too_short}"


def test_no_tier_literally_duplicates_another_tier_for_the_same_outfit():
    dupes = []
    for outfit in OutfitType:
        levels = OUTFIT_DESCRIPTIONS[outfit]
        seen = {}
        for level, text in levels.items():
            if text in seen:
                dupes.append((outfit.value, seen[text].value, level.value))
            else:
                seen[text] = level
    assert not dupes, f"duplicate tier text within an outfit: {dupes}"


def test_new_tier_count_is_exactly_94():
    # 47 OutfitType entries x 2 new tiers (SUGGESTIVE, REVEALING) authored by
    # this suite's companion content change. A regression here means either an
    # outfit was added/removed without updating both new tiers, or one of the
    # two new tiers silently collapsed back onto an old key.
    new_levels = {NudityLevel.SUGGESTIVE, NudityLevel.REVEALING}
    count = sum(
        1
        for outfit in OutfitType
        for level in OUTFIT_DESCRIPTIONS[outfit]
        if level in new_levels
    )
    assert count == 94, f"expected 94 new-tier strings, found {count}"


# ---------------------------------------------------------------------------
# Escalation sanity spot-checks — SUGGESTIVE stays clean (no HIGH-register
# anatomical/explicit terms), REVEALING is more exposed than MEDIUM but a
# notch short of that same outfit's HIGH-only explicit vocabulary. Light
# heuristic on a handful of representative outfits, not exhaustive.
# ---------------------------------------------------------------------------
_EXPLICIT_TERMS = ("pussy", "labia", "clit", "dripping", "folds", "pubic hair", "cum")

_SPOT_CHECK_OUTFITS = (
    OutfitType.LITTLE_BLACK_DRESS,
    OutfitType.BIKINI,
    OutfitType.SATIN_ROBE,
    OutfitType.SCHOOL_UNIFORM,
)


def test_suggestive_tier_has_no_explicit_anatomical_terms():
    for outfit in _SPOT_CHECK_OUTFITS:
        text = OUTFIT_DESCRIPTIONS[outfit][NudityLevel.SUGGESTIVE].lower()
        hits = [t for t in _EXPLICIT_TERMS if t in text]
        assert not hits, f"{outfit.value} SUGGESTIVE contains explicit term(s) {hits}: {text!r}"
        assert "nipple" not in text, f"{outfit.value} SUGGESTIVE exposes nipples: {text!r}"


def test_revealing_tier_stops_short_of_high_only_explicit_terms():
    for outfit in _SPOT_CHECK_OUTFITS:
        high_text = OUTFIT_DESCRIPTIONS[outfit][NudityLevel.HIGH].lower()
        revealing_text = OUTFIT_DESCRIPTIONS[outfit][NudityLevel.REVEALING].lower()
        high_only_terms = [t for t in _EXPLICIT_TERMS if t in high_text]
        leaked = [t for t in high_only_terms if t in revealing_text]
        assert not leaked, (
            f"{outfit.value} REVEALING reuses HIGH-only explicit term(s) {leaked}: "
            f"{revealing_text!r}"
        )


def test_revealing_tier_is_longer_or_equal_signal_than_medium():
    # Not a strict word-count assertion (voice varies), just guards against a
    # REVEALING entry that's a near-empty stub shorter than its own MEDIUM.
    for outfit in OutfitType:
        levels = OUTFIT_DESCRIPTIONS[outfit]
        assert len(levels[NudityLevel.REVEALING]) >= _MIN_LEN
        assert levels[NudityLevel.REVEALING] != levels[NudityLevel.MEDIUM]


# ---------------------------------------------------------------------------
# _GENERATION_DEFAULT_CLOTHING completeness (the no-outfit-selected fallback)
# ---------------------------------------------------------------------------
def test_generation_default_clothing_has_all_five_levels():
    missing = _ALL_LEVELS - set(_GENERATION_DEFAULT_CLOTHING.keys())
    assert not missing, f"_GENERATION_DEFAULT_CLOTHING missing levels: {missing}"


def test_generation_default_clothing_strings_are_reasonably_long():
    for level, text in _GENERATION_DEFAULT_CLOTHING.items():
        assert isinstance(text, str) and len(text.strip()) >= _MIN_LEN, (
            f"_GENERATION_DEFAULT_CLOTHING[{level.value}] too short: {text!r}"
        )


def test_generation_default_clothing_has_no_duplicate_tiers():
    seen = {}
    for level, text in _GENERATION_DEFAULT_CLOTHING.items():
        assert text not in seen, (
            f"_GENERATION_DEFAULT_CLOTHING[{level.value}] duplicates "
            f"[{seen.get(text)}]: {text!r}"
        )
        seen[text] = level.value


# ---------------------------------------------------------------------------
# End-to-end: generation_outfit_clause() actually resolves the new levels
# instead of silently falling back to LOW (the exact bug this suite guards).
# ---------------------------------------------------------------------------
def test_generation_outfit_clause_resolves_suggestive_and_revealing_distinctly():
    from services.outfit_vocab import generation_outfit_clause

    outfit = OutfitType.BIKINI
    low = generation_outfit_clause(outfit, NudityLevel.LOW)
    suggestive = generation_outfit_clause(outfit, NudityLevel.SUGGESTIVE)
    medium = generation_outfit_clause(outfit, NudityLevel.MEDIUM)
    revealing = generation_outfit_clause(outfit, NudityLevel.REVEALING)
    high = generation_outfit_clause(outfit, NudityLevel.HIGH)

    # All five must be distinct strings — if SUGGESTIVE/REVEALING fell back to
    # LOW's text (the pre-fix bug), these equality checks would fail.
    assert len({low, suggestive, medium, revealing, high}) == 5


def test_generation_outfit_clause_naked_resolves_all_five_levels_distinctly():
    from services.outfit_vocab import generation_outfit_clause

    outfit = OutfitType.NAKED
    clauses = {level: generation_outfit_clause(outfit, level) for level in NudityLevel}
    assert len(set(clauses.values())) == 5
    # NAKED's clause is self-contained (no bare "wearing" prefix injected).
    for text in clauses.values():
        assert not text.startswith("wearing wearing")


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
