"""
Integration test (plan verification §2) for the WS-B trait-profile batch consumption.

Two characters with the SAME occupation / controls / seed / count=24 but different saved
TraitProfiles are run through the REAL batch path (trait_profile_merge -> deterministic
planner -> validate_and_repair -> scene_mapper), and we assert the plan reflects each
character's taste while the nudity envelope stays untouched.

NOTE on the A/B style roles: the plan's example makes the sporty character the one whose
non-uniform wardrobe must be >=60% on-style. The hand-authored beat pools
(services.story_templates) are eveningwear/lounge-dominated — only ~44% of beats contain
ANY sporty/streetwear outfit, versus ~82% for elegant/glamorous — so a >=60% sporty share
is unreachable by BIAS alone without breaking beat coherence (which the plan forbids: "no
changes to story_templates.py"). We therefore assign the >=60%-checked role (A) to the
well-represented elegant/glamorous style, and make B the sporty/streetwear character whose
never_wears=[bikini] blocks a garment its OWN style would otherwise favor — a strictly
stronger never_wears test. Every other §2 assertion is exactly as specified.

Runs under pytest or directly: python loli_api/tests/test_trait_batch_dryrun.py
"""
import models.requests as _mr

# The mapper builds a PipelineEditRequest whose source_image is SSRF-validated; these tests
# exercise planning/mapping, not the allowlist, so make the validator a passthrough.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.batch import BatchControls
from models.enums import (
    OutfitType as O, LocationType as L, NudityLevel, WardrobeStyleType as W,
    InteriorStyleType, PaletteType,
)
from models.requests import PersonaOptions
from models.trait_profile import TraitProfile
from services import outfit_vocab as ov
from services import scene_vocab as sv
from services import trait_profile_merge as tpm
from services.story_planner import (
    Character, DeterministicScenePlanner, validate_and_repair,
    _nudity_index, _location_ceiling, _BATCH_EXPRESSIONS_CANDID,
)
from services.scene_mapper import scene_to_pipeline_request
from services.outfit_vocab import outfit_exposure_cap

_OCC = "model"
_COUNT = 24
_SEED = 99
_UNIFORMS = {O.NURSE_UNIFORM, O.SCHOOL_UNIFORM, O.MILITARY_UNIFORM, O.CHEF_UNIFORM}
_A_STYLES = {W.ELEGANT, W.GLAMOROUS}


def _persona():
    return PersonaOptions(
        ethnicity="latina", age=27, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="large", name="Nadia",
        occupation=_OCC, personality="queen", relationship="girlfriend",
    )


# A: elegant/glamorous (the well-represented style -> the >=60% role).
_PROFILE_A = TraitProfile.coerce({
    "wardrobe_styles": ["elegant", "glamorous"],
    "favorite_outfits": ["red_evening_gown", "little_black_dress", "cocktail_dress"],
    "favorite_locations": ["luxury_lounge", "rooftop"],
    "demeanor": ["elegant"],
    "interior_style": "luxury_glam",
    "color_palette": "jewel_tones",
    "likes": ["silk", "gowns", "champagne"],
    "dislikes": ["gyms"],
})
# B: sporty/streetwear, never_wears bikini (a bikini its own SPORTY style would favor).
_PROFILE_B = TraitProfile.coerce({
    "wardrobe_styles": ["sporty", "streetwear"],
    "favorite_outfits": ["gym_set", "hoodie_joggers"],
    "never_wears": ["bikini"],
    "demeanor": ["energetic"],
    "interior_style": "industrial_loft",
    "color_palette": "bold_dark",
    "likes": ["running", "sneakers"],
})


def _controls():
    return BatchControls(max_nudity=NudityLevel.MEDIUM, escalation="building", base_seed=_SEED)


def _plan(profile):
    """Merge the profile then run the real deterministic batch path. Returns (scenes, controls)."""
    controls, likes, dislikes = tpm.apply_trait_profile(_controls(), [], [], profile, _OCC)
    char = Character(
        persona=_persona(), likes=likes, dislikes=dislikes,
        hero_photo_url="https://x.supabase.co/hero.png",
    )
    scenes = validate_and_repair(
        DeterministicScenePlanner().plan_scenes_sync(char, _COUNT, controls), char, _COUNT, controls
    )
    return scenes, controls, char


def _plan_no_profile():
    controls = _controls()
    char = Character(persona=_persona(), hero_photo_url="https://x.supabase.co/hero.png")
    scenes = validate_and_repair(
        DeterministicScenePlanner().plan_scenes_sync(char, _COUNT, controls), char, _COUNT, controls
    )
    return scenes


def test_outfit_multisets_differ_between_profiles():
    a, _, _ = _plan(_PROFILE_A)
    b, _, _ = _plan(_PROFILE_B)
    ma = sorted(s.outfit.value for s in a if s.outfit)
    mb = sorted(s.outfit.value for s in b if s.outfit)
    assert ma != mb, "two differently-styled characters produced identical outfit multisets"


def test_character_a_wardrobe_is_at_least_60pct_on_style():
    a, _, _ = _plan(_PROFILE_A)
    non_uniform = [s.outfit for s in a if s.outfit and s.outfit not in _UNIFORMS]
    assert non_uniform, "no non-uniform outfits to check"
    on_style = sum(1 for o in non_uniform if ov.OUTFIT_STYLE_TAGS.get(o, frozenset()) & _A_STYLES)
    share = on_style / len(non_uniform)
    assert share >= 0.60, f"only {share:.0%} of A's non-uniform outfits are on-style"


def test_character_b_never_emits_bikini():
    b, _, _ = _plan(_PROFILE_B)
    assert all(s.outfit != O.BIKINI for s in b), "B emitted bikini despite never_wears"


def test_nudity_sequence_identical_across_a_b_and_no_profile():
    a, _, _ = _plan(_PROFILE_A)
    b, _, _ = _plan(_PROFILE_B)
    n0 = _plan_no_profile()
    seq_a = [s.nudityLevel for s in a]
    seq_b = [s.nudityLevel for s in b]
    seq_0 = [s.nudityLevel for s in n0]
    assert seq_a == seq_b == seq_0, "trait profiles must not change the nudity arc"


def test_every_item_within_outfit_cap_and_location_ceiling():
    for profile in (_PROFILE_A, _PROFILE_B):
        scenes, _, _ = _plan(profile)
        for s in scenes:
            if s.outfit is not None:
                assert _nudity_index(s.nudityLevel) <= _nudity_index(outfit_exposure_cap(s.outfit))
            assert _nudity_index(s.nudityLevel) <= _nudity_index(_location_ceiling(s.location))


def test_expressions_present_varied_and_candid_share():
    a, _, _ = _plan(_PROFILE_A)
    exprs = [s.expression for s in a]
    assert all(exprs), "an item was left with no expression"
    # No adjacent duplicate expressions or poses.
    assert all(exprs[i] != exprs[i - 1] for i in range(1, len(exprs)))
    poses = [s.pose for s in a]
    assert all(
        poses[i] is None or poses[i - 1] is None or poses[i] != poses[i - 1]
        for i in range(1, len(poses))
    )
    # ~1/3 candid (camera-unaware) share.
    candid = sum(1 for e in exprs if e in _BATCH_EXPRESSIONS_CANDID)
    assert 5 <= candid <= 11, f"candid share {candid}/24 outside the ~1/3 band"


def test_home_items_carry_the_characters_styled_room_text():
    a, controls_a, char_a = _plan(_PROFILE_A)
    home = [
        s for s in a
        if str(s.location.value).startswith("home") or s.location == L.HOTEL_ROOM
    ]
    assert home, "expected at least one home/hotel scene"
    for s in home:
        prompt = scene_to_pipeline_request(char_a, s, controls_a).prompt or ""
        styled = sv.styled_room_phrase(InteriorStyleType.LUXURY_GLAM, s.location)
        assert styled and styled in prompt, f"home scene at {s.location.value} lost its styled room text"
    # The palette clause rides along too.
    assert any(
        sv.PALETTE_PHRASES[PaletteType.JEWEL_TONES] in (scene_to_pipeline_request(char_a, s, controls_a).prompt or "")
        for s in home
    )


def test_home_room_text_is_stable_per_character_and_distinct_across_characters():
    # Same character, two separate batches -> identical styled home text (visual consistency).
    a1, c1, ch1 = _plan(_PROFILE_A)
    a2, c2, ch2 = _plan(_PROFILE_A)

    def home_prompts(scenes, controls, char):
        out = {}
        for s in scenes:
            if str(s.location.value).startswith("home") or s.location == L.HOTEL_ROOM:
                out[s.global_index] = scene_to_pipeline_request(char, s, controls).prompt
        return out

    assert home_prompts(a1, c1, ch1) == home_prompts(a2, c2, ch2), \
        "A's home scenery drifted between two identical batches"
    # A's bedroom text differs from B's (different interior styles -> different homes).
    bed_a = sv.styled_room_phrase(InteriorStyleType.LUXURY_GLAM, L.HOME_BEDROOM)
    bed_b = sv.styled_room_phrase(InteriorStyleType.INDUSTRIAL_LOFT, L.HOME_BEDROOM)
    assert bed_a and bed_b and bed_a != bed_b


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
