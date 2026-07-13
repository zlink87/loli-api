"""
Tests for services.trait_profile_merge.apply_trait_profile — the pure function that
folds a character's saved TraitProfile into a batch's controls/likes/dislikes.

Covers the plan's B2.2 contract: admin-wins matrix (allowlists / explicit fields skip
the profile), the nudity-envelope byte-identity invariant, work-location protection,
and the None-profile (flag-off) no-op.

Runs under pytest or directly: python loli_api/tests/test_trait_profile_merge.py
"""
from models.batch import BatchControls
from models.enums import (
    OutfitType as O, LocationType as L, DemeanorType, InteriorStyleType, PaletteType,
    WardrobeStyleType as W,
)
from models.trait_profile import TraitProfile
from services.trait_profile_merge import apply_trait_profile
from services import outfit_vocab as ov


# Fields that make up the nudity envelope — apply_trait_profile must NEVER touch them.
_NUDITY_ENVELOPE = ("max_nudity", "start_nudity", "sfw_only", "content_rating", "escalation")


def _envelope(c: BatchControls):
    return tuple(getattr(c, f) for f in _NUDITY_ENVELOPE)


def _profile(**kw) -> TraitProfile:
    base = dict(
        wardrobe_styles=["elegant", "glamorous"],
        favorite_outfits=["red_evening_gown", "little_black_dress"],
        never_wears=["bikini"],
        favorite_locations=["luxury_lounge", "rooftop"],
        avoided_locations=["gym"],
        demeanor=["elegant"],
        interior_style="luxury_glam",
        color_palette="jewel_tones",
        likes=["silk", "champagne"],
        dislikes=["neon clubs"],
    )
    base.update(kw)
    return TraitProfile.coerce(base)


# ---------------------------------------------------------------------------
# None profile / flag-off no-op
# ---------------------------------------------------------------------------
def test_none_profile_is_a_noop_echo():
    c0 = BatchControls(max_nudity="medium", base_seed=3)
    c1, likes, dislikes = apply_trait_profile(c0, ["a"], ["b"], None, "nurse")
    assert c1 is c0                      # controls object echoed unchanged
    assert likes == ["a"] and dislikes == ["b"]


# ---------------------------------------------------------------------------
# Nudity envelope byte-identity (the hard contract)
# ---------------------------------------------------------------------------
def test_nudity_envelope_is_byte_identical():
    for kw in (
        dict(max_nudity="high", escalation="building"),
        dict(max_nudity="low", sfw_only=True),
        dict(max_nudity="medium", start_nudity="low", content_rating="nsfw"),
    ):
        c0 = BatchControls(base_seed=1, **kw)
        before = _envelope(c0)
        c1, _, _ = apply_trait_profile(c0, [], [], _profile(), "nurse")
        assert _envelope(c1) == before, f"nudity envelope changed for {kw}"


# ---------------------------------------------------------------------------
# Default path — profile drives the outfit/location/taste bias fields
# ---------------------------------------------------------------------------
def test_default_path_populates_bias_fields():
    c0 = BatchControls(max_nudity="medium", base_seed=1)
    c1, likes, dislikes = apply_trait_profile(c0, [], [], _profile(), "boss_ceo")
    # blocked_outfits ∪= never_wears (default [NAKED] retained).
    assert O.BIKINI in c1.blocked_outfits and O.NAKED in c1.blocked_outfits
    # wardrobe_outfits = style-mapped ∪ favorites − blocked − NAKED.
    assert c1.wardrobe_outfits and O.BIKINI not in c1.wardrobe_outfits
    assert O.NAKED not in c1.wardrobe_outfits
    assert O.RED_EVENING_GOWN in c1.wardrobe_outfits  # a favorite survives
    # favored_outfits = favorites − blocked.
    assert set(c1.favored_outfits) == {O.RED_EVENING_GOWN, O.LITTLE_BLACK_DRESS}
    # location bias.
    assert L.GYM in c1.blocked_locations            # avoided, not a boss_ceo workplace
    assert set(c1.favored_locations) == {L.LUXURY_LOUNGE, L.ROOFTOP}
    # taste fields fill-only.
    assert c1.demeanor == [DemeanorType.ELEGANT]
    assert c1.interior_style == InteriorStyleType.LUXURY_GLAM
    assert c1.color_palette == PaletteType.JEWEL_TONES
    # likes/dislikes filled wholesale from an empty batch list.
    assert likes == ["silk", "champagne"] and dislikes == ["neon clubs"]


def test_wardrobe_outfits_reflect_style_expansion():
    c0 = BatchControls(base_seed=1)
    c1, _, _ = apply_trait_profile(c0, [], [], _profile(favorite_outfits=[], never_wears=[]), "model")
    # No favorites/never_wears -> wardrobe is exactly the style-mapped set (minus NAKED default block).
    expected = {o for o in ov.outfits_for_styles([W.ELEGANT, W.GLAMOROUS]) if o != O.NAKED}
    assert set(c1.wardrobe_outfits or []) == expected


# ---------------------------------------------------------------------------
# Admin-wins matrix
# ---------------------------------------------------------------------------
def test_admin_allowed_outfits_skips_all_profile_outfit_fields():
    c0 = BatchControls(base_seed=1, allowed_outfits=[O.COCKTAIL_DRESS, O.SATIN_SLIP_DRESS])
    c1, _, _ = apply_trait_profile(c0, [], [], _profile(), "model")
    # allowlist untouched; NO wardrobe/favored derived; never_wears NOT unioned into blocked.
    assert c1.allowed_outfits == [O.COCKTAIL_DRESS, O.SATIN_SLIP_DRESS]
    assert c1.wardrobe_outfits is None
    assert c1.favored_outfits is None
    assert O.BIKINI not in c1.blocked_outfits          # never_wears skipped entirely
    # Location + taste fields are independent and STILL applied.
    assert L.GYM in c1.blocked_locations
    assert c1.interior_style == InteriorStyleType.LUXURY_GLAM


def test_admin_allowed_locations_skips_all_profile_location_fields():
    c0 = BatchControls(base_seed=1, allowed_locations=[L.OFFICE, L.HOME_OFFICE])
    c1, _, _ = apply_trait_profile(c0, [], [], _profile(), "model")
    assert c1.allowed_locations == [L.OFFICE, L.HOME_OFFICE]
    assert c1.favored_locations is None
    assert L.GYM not in c1.blocked_locations           # avoided skipped entirely
    # Outfit + taste fields still applied.
    assert c1.wardrobe_outfits and O.BIKINI in c1.blocked_outfits


def test_explicit_demeanor_interior_palette_win_over_profile():
    c0 = BatchControls(
        base_seed=1,
        demeanor=[DemeanorType.SULTRY],
        interior_style=InteriorStyleType.INDUSTRIAL_LOFT,
        color_palette=PaletteType.BOLD_DARK,
    )
    c1, _, _ = apply_trait_profile(c0, [], [], _profile(), "model")
    assert c1.demeanor == [DemeanorType.SULTRY]                 # admin value kept
    assert c1.interior_style == InteriorStyleType.INDUSTRIAL_LOFT
    assert c1.color_palette == PaletteType.BOLD_DARK


def test_batch_likes_dislikes_win_wholesale():
    c0 = BatchControls(base_seed=1)
    c1, likes, dislikes = apply_trait_profile(c0, ["coffee"], ["rain"], _profile(), "model")
    # A non-empty batch list is kept verbatim; the profile's likes/dislikes are NOT merged in.
    assert likes == ["coffee"] and dislikes == ["rain"]


# ---------------------------------------------------------------------------
# Work-location protection: an avoided place she WORKS at is not blocked
# ---------------------------------------------------------------------------
def test_avoided_work_location_is_not_blocked():
    # A nurse who "avoids" the hospital off the clock must still be shown at the ward for
    # her work chapter — work_locations_for(nurse) == (HOSPITAL_WARD,) protects it.
    prof = _profile(avoided_locations=["hospital_ward", "gym"])
    c0 = BatchControls(base_seed=1)
    c1, _, _ = apply_trait_profile(c0, [], [], prof, "nurse")
    assert L.HOSPITAL_WARD not in c1.blocked_locations   # protected (a nurse workplace)
    assert L.GYM in c1.blocked_locations                 # not a workplace -> blocked


def test_purity_inputs_not_mutated():
    c0 = BatchControls(base_seed=1)
    blocked_before = list(c0.blocked_outfits)
    likes_in, dislikes_in = ["x"], ["y"]
    apply_trait_profile(c0, likes_in, dislikes_in, _profile(), "model")
    # The caller's controls + lists are untouched (a fresh object/list is returned).
    assert c0.blocked_outfits == blocked_before
    assert c0.wardrobe_outfits is None
    assert likes_in == ["x"] and dislikes_in == ["y"]


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
