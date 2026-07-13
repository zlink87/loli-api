"""
Tests for the expanded ethnicity vocabulary (WS-2).

Guards the invariants that make the 25-value EthnicityType safe:
  * COVERAGE: every EthnicityType member has BOTH an ETHNICITY_PHRASES entry
    (locked-identity block) and a SKIN_TONE_PHRASES entry (edit skin anchor).
  * NO HAIR/EYE COLOR: neither map's phrases may name a hair or eye color —
    those are separate persona fields (HairColorType/EyeColorType) and a heritage
    phrase that fixed them would fight the admin's explicit choice.
  * LEGACY BYTE-IDENTICAL: the 5 original values keep their exact phrases so
    existing characters render unchanged.

Runs under pytest or directly: python loli_api/tests/test_ethnicity_vocab.py
"""
import re

from models.enums import EthnicityType
from services import attribute_phrases as ap
from services.attribute_phrases import ETHNICITY_PHRASES, SKIN_TONE_PHRASES, skin_tone_phrase


# --- coverage ---------------------------------------------------------------
def test_every_ethnicity_has_an_ethnicity_phrase():
    for e in EthnicityType:
        assert ETHNICITY_PHRASES.get(e.value), f"missing ETHNICITY_PHRASES entry: {e.value}"


def test_every_ethnicity_has_a_skin_tone_phrase():
    for e in EthnicityType:
        assert SKIN_TONE_PHRASES.get(e.value), f"missing SKIN_TONE_PHRASES entry: {e.value}"


def test_no_orphan_phrase_keys():
    # Both maps key ONLY real enum values (no typo/stale keys that silently miss).
    valid = {e.value for e in EthnicityType}
    assert set(ETHNICITY_PHRASES).issubset(valid), set(ETHNICITY_PHRASES) - valid
    assert set(SKIN_TONE_PHRASES).issubset(valid), set(SKIN_TONE_PHRASES) - valid


def test_expansion_is_the_expected_25_values():
    # Exactly the 5 legacy + 20 regional values, no more/less.
    assert len(EthnicityType) == 25
    assert len(ETHNICITY_PHRASES) == 25
    assert len(SKIN_TONE_PHRASES) == 25


# --- regression guard: no hair/eye color words ------------------------------
# Substring bans would false-positive on legitimate skin words — "brown"/"black"
# are valid skin tones (and are deliberately NOT banned), "Caucasian" contains
# "asian", etc. So the guard is word-boundary anchored. It bans ONLY words that
# are unambiguously hair/eye descriptors, plus the nouns "hair"/"eyes"/"eyed".
_BANNED_PATTERNS = [
    r"\bblonde?\b",     # blond / blonde
    r"\bbrunette\b",
    r"\bredhead",       # redhead / redheaded
    r"\bhair",          # hair / haired / hairstyle
    r"\beyes?\b",       # eye / eyes
    r"\beyed\b",        # blue-eyed / almond-eyed
    r"\bhazel\b",
    r"\bblue\b",
    r"\bgreen\b",
]


def _violations(text: str):
    low = text.lower()
    return [p for p in _BANNED_PATTERNS if re.search(p, low)]


def test_ethnicity_phrases_name_no_hair_or_eye_color():
    for value, text in ETHNICITY_PHRASES.items():
        hits = _violations(text)
        assert not hits, f"ETHNICITY_PHRASES['{value}'] mentions hair/eye color {hits}: {text!r}"


def test_skin_tone_phrases_name_no_hair_or_eye_color():
    for value, text in SKIN_TONE_PHRASES.items():
        hits = _violations(text)
        assert not hits, f"SKIN_TONE_PHRASES['{value}'] mentions hair/eye color {hits}: {text!r}"


def test_ban_list_has_no_false_positive_on_legit_skin_words():
    # Guard the guard: brown/black/olive/ebony/bronze skin words (and "Caucasian")
    # must NOT be flagged — otherwise a legitimate phrase would fail the guard.
    for legit in ("warm dark-brown skin", "a Black woman with warm dark-brown skin",
                  "deep rich ebony skin", "sun-kissed bronze skin", "warm olive skin",
                  "a Caucasian woman with fair skin"):
        assert not _violations(legit), f"false positive on legit skin phrase: {legit!r}"

    # And the guard genuinely fires on real hair/eye phrasing (proves it works).
    for bad in ("long blonde hair", "bright green eyes", "hazel eyes", "blue-eyed"):
        assert _violations(bad), f"ban list failed to catch: {bad!r}"


# --- legacy byte-identical ---------------------------------------------------
_LEGACY_ETHNICITY = {
    "caucasian": "a Caucasian woman with fair skin",
    "asian": "an East Asian woman with light skin",
    "black_afro": "a Black woman with warm dark-brown skin",
    "latina": "a Latina woman with warm tan skin",
    "arab": "a Middle Eastern woman with olive skin",
}
_LEGACY_SKIN_TONE = {
    "caucasian": "fair skin",
    "asian": "light skin",
    "black_afro": "warm dark-brown skin",
    "latina": "warm tan skin",
    "arab": "olive skin",
}


def test_legacy_ethnicity_phrases_are_byte_identical():
    for value, expected in _LEGACY_ETHNICITY.items():
        assert ETHNICITY_PHRASES[value] == expected


def test_legacy_skin_tone_phrases_are_byte_identical():
    for value, expected in _LEGACY_SKIN_TONE.items():
        assert SKIN_TONE_PHRASES[value] == expected


# --- new values resolve through the public helpers --------------------------
def test_skin_tone_phrase_resolves_for_new_values():
    # The edit-anchor helper (case/underscore tolerant) resolves new values.
    assert skin_tone_phrase("west_african") == "deep rich ebony skin"
    assert skin_tone_phrase(EthnicityType.BALTIC) == "very fair cool-toned skin"
    assert skin_tone_phrase("SLAVIC") == "fair skin"


def test_ethnicity_phrase_lookup_for_new_value_leads_with_heritage_and_skin():
    text = ap.phrase(ETHNICITY_PHRASES, EthnicityType.WEST_AFRICAN)
    assert text.startswith("a West African woman with deep rich ebony skin")


def test_unknown_ethnicity_degrades_safely():
    # The additive-expansion contract: unknown values -> "" / None, never raise.
    assert ap.phrase(ETHNICITY_PHRASES, "klingon") == ""
    assert skin_tone_phrase("klingon") is None


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
