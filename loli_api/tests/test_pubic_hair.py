"""
Tests for the pubic-hair grooming attribute (PubicHairType) + genital-area realism.

Covers the whole feature surface:
  * PUBIC_HAIR_PHRASES hygiene — every enum value mapped, no orphan keys, matte
    doctrine (no gloss/shine vocabulary), and pubic_hair_phrase()'s None/unknown ->
    SHAVED default + case/underscore tolerance.
  * Nude base (workers.nude_base_worker.build_nude_base_prompt) — ALWAYS carries the
    grooming clause (persona value, or the SHAVED default when unset) exactly once,
    positioned after the body-aesthetic clause and before ANTI_GLOSS_POSITIVE, plus
    the anatomy-realism POSITIVE clause and the anatomy-realism NEGATIVE terms.
  * Generation t2i (services.prompt_generator.assemble_generation_prompt) — the
    grooming clause enters ONLY for a NAKED outfit at HIGH nudity, adjacent to the
    clothing clause and NEVER in the locked identity block; dressed or sub-HIGH
    prompts must NOT carry it (the critical negative case).
  * Batch naked tier (services.scene_mapper + the outfit/pose builders) — the mapper
    threads pubicHair ONLY for a NAKED-class outfit at HIGH nudity; build_prompt and
    outfit_continuity_text append the grooming to the NAKED prose (and the NAKED
    state-of-undress lead survives for build_pose_prompt); dressed items never carry it.
  * edit_negative tiers — the anatomy-realism negative is appended ONLY at the HIGH
    tier, never the sub-HIGH tiers used on dressed edits.
  * Migration 0007 exists with the expected additive column DDL.
  * CharacterStore mapping — pubic_hair round-trips, and a row missing the column (or a
    garbage value) reads back as None (which resolves to the SHAVED default).

Runs under pytest or directly: python loli_api/tests/test_pubic_hair.py
"""
from pathlib import Path
from types import SimpleNamespace

import models.requests as _mr

# The mapper / requests SSRF-validate source_image; these tests exercise feature
# logic, not the allowlist, so make the validator a passthrough.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import (
    PubicHairType, OutfitType, NudityLevel, LocationType, PoseType,
)
from models.requests import PersonaOptions
from models.batch import BatchControls
from models.scene import SceneSpec
from services import attribute_phrases as ap
from services import prompt_constants as pc
from services.prompt_generator import assemble_generation_prompt, locked_tokens
from services.story_planner import Character
from services import scene_mapper as sm
from services.character_store import (
    _persona_to_columns, _row_to_persona, _valid_pubic_hair,
)
from api.v1.endpoints.outfit import build_prompt, outfit_continuity_text
from api.v1.endpoints.pose import build_pose_prompt
from workers.nude_base_worker import (
    build_nude_base_prompt,
    ANATOMY_REALISM_POSITIVE,
    ANTI_GLOSS_POSITIVE,
    BODY_AESTHETIC_POSTURE_TAIL,
)

# Matte doctrine: grooming phrases describe grooming/hair only, never a wet/oily/
# glossy finish. Same discipline as the nude-base anti-gloss ban.
_GLOSS_BANNED = (
    "glossy", "gloss", "shiny", "shine", "oily", "oiled", "wet-look",
    "glisten", "sheen", "airbrushed", "polished", "greasy",
)

_SHAVED = ap.PUBIC_HAIR_PHRASES["shaved"]
_FULL = ap.PUBIC_HAIR_PHRASES["full"]


def _persona(**overrides) -> PersonaOptions:
    fields = dict(
        ethnicity="japanese", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Stella",
    )
    fields.update(overrides)
    return PersonaOptions(**fields)


def _character(**persona_overrides) -> Character:
    char = Character(
        persona=_persona(**persona_overrides),
        hero_photo_url="https://x.supabase.co/hero.png",
    )
    char.nude_base_url = "https://x.supabase.co/nude.png"
    return char


def _scene(**kw) -> SceneSpec:
    base = dict(
        arc_id="a", arc_title="A", beat_index=0, global_index=0,
        beat_description="beat", location=LocationType.HOME_BEDROOM,
    )
    base.update(kw)
    return SceneSpec(**base)


# ---------------------------------------------------------------------------
# 1. Phrase-map hygiene + helper behavior
# ---------------------------------------------------------------------------
def test_every_pubic_hair_value_has_a_nonempty_phrase_and_no_orphans():
    enum_vals = {m.value for m in PubicHairType}
    map_keys = set(ap.PUBIC_HAIR_PHRASES)
    assert map_keys == enum_vals, "PUBIC_HAIR_PHRASES keys must be exactly the enum values"
    for m in PubicHairType:
        assert ap.PUBIC_HAIR_PHRASES[m.value].strip(), f"empty phrase for {m.value!r}"


def test_pubic_hair_phrases_carry_no_gloss_vocabulary():
    for value, phrase in ap.PUBIC_HAIR_PHRASES.items():
        low = phrase.lower()
        for banned in _GLOSS_BANNED:
            assert banned not in low, f"gloss token {banned!r} leaked into {value!r} phrase"


def test_pubic_hair_phrase_resolves_none_and_unknown_to_shaved():
    assert ap.pubic_hair_phrase(None) == _SHAVED
    assert ap.pubic_hair_phrase("not_a_value") == _SHAVED
    assert ap.pubic_hair_phrase("") == _SHAVED


def test_pubic_hair_phrase_maps_each_member_and_is_tolerant():
    for m in PubicHairType:
        assert ap.pubic_hair_phrase(m) == ap.PUBIC_HAIR_PHRASES[m.value]
        assert ap.pubic_hair_phrase(m.value) == ap.pubic_hair_phrase(m)
        # case- and separator-tolerant (mirrors skin_tone_phrase)
        assert ap.pubic_hair_phrase(m.value.upper()) == ap.pubic_hair_phrase(m)
    assert ap.pubic_hair_phrase("landing-strip") == ap.PUBIC_HAIR_PHRASES["landing_strip"]


# ---------------------------------------------------------------------------
# 2. Nude base — ALWAYS carries grooming (persona value or the SHAVED default),
#    plus the anatomy-realism positive clause and negative terms.
# ---------------------------------------------------------------------------
def test_nude_base_carries_persona_grooming_anatomy_and_negatives_once():
    positive, negative, locked = build_nude_base_prompt(_persona(pubicHair=PubicHairType.FULL))
    # grooming present exactly once (no double-add from the assembler's inline copy)
    assert positive.count(_FULL) == 1
    # anatomy-realism positive clause + shared anatomy negative terms
    assert ANATOMY_REALISM_POSITIVE in positive
    assert pc.ANATOMY_REALISM_NEGATIVE in negative
    # positioned AFTER the body-aesthetic clause and BEFORE the anti-gloss clause
    assert positive.index(BODY_AESTHETIC_POSTURE_TAIL) < positive.index(_FULL)
    assert positive.index(_FULL) < positive.index(ANATOMY_REALISM_POSITIVE)
    assert positive.index(ANATOMY_REALISM_POSITIVE) < positive.index(ANTI_GLOSS_POSITIVE)
    # grooming never leaks into the locked identity block
    assert _FULL not in locked


def test_nude_base_absent_pubic_hair_defaults_to_shaved():
    # A persona that predates the field (pubicHair unset) still gets a definite
    # groomed state — the SHAVED default — rather than leaving the base to improvise.
    positive, _neg, _lk = build_nude_base_prompt(_persona())
    assert positive.count(_SHAVED) == 1
    assert ANATOMY_REALISM_POSITIVE in positive


def test_nude_base_grooming_and_anatomy_carry_no_gloss_vocabulary():
    positive, _neg, _lk = build_nude_base_prompt(_persona(pubicHair=PubicHairType.NATURAL))
    for banned in _GLOSS_BANNED:
        # the anatomy positive clause and grooming phrase must not smuggle gloss in
        assert banned not in ANATOMY_REALISM_POSITIVE.lower()
    assert ap.PUBIC_HAIR_PHRASES["natural"] in positive


# ---------------------------------------------------------------------------
# 3. Generation t2i gating — the CRITICAL negative case.
# ---------------------------------------------------------------------------
def test_generation_naked_high_carries_grooming_adjacent_not_in_locked():
    persona = _persona(pubicHair=PubicHairType.FULL)
    positive, _neg, locked = assemble_generation_prompt(
        persona, outfit=OutfitType.NAKED, nudity_level=NudityLevel.HIGH
    )
    assert _FULL in positive
    assert _FULL not in locked  # never in the always-on identity block


def test_generation_dressed_or_sub_high_never_carries_grooming():
    persona = _persona(pubicHair=PubicHairType.FULL)
    # dressed at MEDIUM
    p1, _, _ = assemble_generation_prompt(
        persona, outfit=OutfitType.RED_EVENING_GOWN, nudity_level=NudityLevel.MEDIUM
    )
    # NAKED but sub-HIGH
    p2, _, _ = assemble_generation_prompt(
        persona, outfit=OutfitType.NAKED, nudity_level=NudityLevel.MEDIUM
    )
    # dressed at HIGH
    p3, _, _ = assemble_generation_prompt(
        persona, outfit=OutfitType.RED_EVENING_GOWN, nudity_level=NudityLevel.HIGH
    )
    # no explicit outfit (the neutral nude fallback is NOT NAKED-class) at HIGH
    p4, _, _ = assemble_generation_prompt(
        persona, outfit=None, nudity_level=NudityLevel.HIGH
    )
    for prompt in (p1, p2, p3, p4):
        for phrase in ap.PUBIC_HAIR_PHRASES.values():
            assert phrase not in prompt, f"grooming leaked into a non-exposed prompt: {phrase!r}"


def test_generation_grooming_defaults_to_shaved_when_unset():
    positive, _neg, _lk = assemble_generation_prompt(
        _persona(), outfit=OutfitType.NAKED, nudity_level=NudityLevel.HIGH
    )
    assert _SHAVED in positive


# ---------------------------------------------------------------------------
# 4. Batch naked tier — scene_mapper threading + the outfit/pose builders.
# ---------------------------------------------------------------------------
_NAKED_OK = BatchControls(max_nudity=NudityLevel.HIGH, blocked_outfits=[])


def test_scene_mapper_threads_pubic_hair_only_for_naked_high():
    char = _character(pubicHair=PubicHairType.FULL)
    # NAKED + HIGH -> the persona's grooming value
    req = sm.scene_to_pipeline_request(
        char, _scene(pose=PoseType.SITTING, outfit=OutfitType.NAKED, nudityLevel=NudityLevel.HIGH),
        _NAKED_OK,
    )
    assert req.pubicHair == "full"
    # NAKED + sub-HIGH -> None
    req = sm.scene_to_pipeline_request(
        char, _scene(pose=PoseType.SITTING, outfit=OutfitType.NAKED, nudityLevel=NudityLevel.MEDIUM),
        _NAKED_OK,
    )
    assert req.pubicHair is None
    # dressed + HIGH -> None
    req = sm.scene_to_pipeline_request(
        char, _scene(pose=PoseType.SITTING, outfit=OutfitType.RED_EVENING_GOWN, nudityLevel=NudityLevel.HIGH),
        _NAKED_OK,
    )
    assert req.pubicHair is None


def test_scene_mapper_naked_high_unset_persona_defaults_to_shaved():
    char = _character()  # no pubicHair on the persona
    req = sm.scene_to_pipeline_request(
        char, _scene(pose=PoseType.SITTING, outfit=OutfitType.NAKED, nudityLevel=NudityLevel.HIGH),
        _NAKED_OK,
    )
    assert req.pubicHair == "shaved"


def test_scene_mapper_clamp_below_high_drops_grooming():
    # A NAKED item whose nudity is clamped below HIGH by the batch envelope is no
    # longer fully exposed, so grooming must NOT thread.
    char = _character(pubicHair=PubicHairType.FULL)
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM, blocked_outfits=[])
    req = sm.scene_to_pipeline_request(
        char, _scene(pose=PoseType.SITTING, outfit=OutfitType.NAKED, nudityLevel=NudityLevel.HIGH),
        controls,
    )
    assert req.pubicHair is None


def test_build_prompt_naked_appends_grooming_dressed_ignores():
    naked = build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH, grooming=_FULL)
    assert _FULL in naked
    dressed = build_prompt(OutfitType.RED_EVENING_GOWN, None, NudityLevel.HIGH, grooming=_FULL)
    assert _FULL not in dressed  # grooming is only ever paired with NAKED
    # None grooming is byte-identical to omitting it
    assert build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH) == \
        build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH, grooming=None)


def test_outfit_continuity_appends_grooming_preserving_state_of_undress_lead():
    text = outfit_continuity_text(OutfitType.NAKED, NudityLevel.HIGH, None, grooming=_FULL)
    # APPENDED (not prepended): the NAKED tier keeps its leading state-of-undress word.
    assert text.startswith("completely naked")
    assert text.endswith(_FULL)
    # None grooming is byte-identical to omitting it (parity)
    assert outfit_continuity_text(OutfitType.NAKED, NudityLevel.HIGH, None) == \
        outfit_continuity_text(OutfitType.NAKED, NudityLevel.HIGH, None, grooming=None)


def test_pose_prompt_naked_continuity_keeps_state_of_dress_phrasing_with_grooming():
    # The single-pass path: build_pose_prompt must phrase the naked-plus-grooming
    # continuity as "she is completely naked …", never "Dress her in: {grooming}".
    text = outfit_continuity_text(OutfitType.NAKED, NudityLevel.HIGH, None, grooming=_FULL)
    prompt = build_pose_prompt(
        PoseType.SITTING, outfit_text=text, scene_text="a dim bedroom", dress_mode=True,
    )
    assert "she is completely naked" in prompt
    assert _FULL in prompt
    assert "Dress her in:" not in prompt


# ---------------------------------------------------------------------------
# 5. edit_negative tiers — anatomy negative at HIGH only.
# ---------------------------------------------------------------------------
def test_edit_negative_anatomy_terms_only_at_high_tier():
    assert pc.ANATOMY_REALISM_NEGATIVE in pc.edit_negative(nudity_level=NudityLevel.HIGH)
    for level in (NudityLevel.LOW, NudityLevel.SUGGESTIVE, NudityLevel.MEDIUM, NudityLevel.REVEALING):
        assert pc.ANATOMY_REALISM_NEGATIVE not in pc.edit_negative(nudity_level=level)
    # default (None -> 'low') also excludes it
    assert pc.ANATOMY_REALISM_NEGATIVE not in pc.edit_negative()


# ---------------------------------------------------------------------------
# 6. Migration file exists with the additive column DDL.
# ---------------------------------------------------------------------------
def test_migration_0007_exists_with_additive_not_null_default_column():
    path = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "0007_character_pubic_hair.sql"
    )
    assert path.exists(), "migration 0007_character_pubic_hair.sql must exist"
    sql = path.read_text().lower()
    assert "add column if not exists pubic_hair" in sql
    assert "not null default 'shaved'" in sql
    assert "alter table public.characters" in sql


# ---------------------------------------------------------------------------
# 7. CharacterStore mapping — write + tolerant read.
# ---------------------------------------------------------------------------
_CHAR_ROW = {
    "id": "c1", "name": "Stella", "style": "realistic", "ethnicity": "caucasian",
    "age": 28, "hair_style": "straight", "hair_color": "blonde", "eye_color": "green",
    "body_type": "curvy", "breast_size": "medium", "created_at": "t", "updated_at": "t",
}


def test_persona_to_columns_emits_pubic_hair_value_or_shaved_default():
    assert _persona_to_columns(_persona(pubicHair=PubicHairType.FULL))["pubic_hair"] == "full"
    # unset -> the explicit 'shaved' default (never NULL — the column is NOT NULL)
    assert _persona_to_columns(_persona())["pubic_hair"] == "shaved"


def test_character_row_round_trips_pubic_hair():
    persona = _row_to_persona(dict(_CHAR_ROW, pubic_hair="full"))
    assert persona.pubicHair is not None and persona.pubicHair.value == "full"


def test_character_row_missing_pubic_hair_key_reads_none():
    # A pre-migration row simply has no pubic_hair key -> None (resolves to shaved
    # at phrase time), never raises.
    assert "pubic_hair" not in _CHAR_ROW
    assert _row_to_persona(_CHAR_ROW).pubicHair is None


def test_character_row_garbage_pubic_hair_degrades_to_none():
    for bad in ("not_a_value", "FULL!!", 123, ""):
        assert _row_to_persona(dict(_CHAR_ROW, pubic_hair=bad)).pubicHair is None


def test_valid_pubic_hair_helper():
    assert _valid_pubic_hair("shaved") == "shaved"
    assert _valid_pubic_hair(PubicHairType.FULL) == "full"
    assert _valid_pubic_hair(None) is None
    assert _valid_pubic_hair("garbage") is None


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
