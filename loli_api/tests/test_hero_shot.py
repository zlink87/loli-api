"""
Tests for consistent, polished hero-shot generation: camera vocabulary, shot-block
assembly, framing survival gate, output whitelist, and workflow injection.

Runs under pytest or directly: python loli_api/tests/test_hero_shot.py
"""
import copy
import json
from pathlib import Path

from models.enums import (
    ShotFramingType,
    CameraAngleType,
    ExpressionType,
    PhotoStyleType,
    PersonalityType,
)
from models.requests import PersonaOptions, ShotOptions, OutputOptions
from services import camera_vocab as cv
from services import output_presets as op
from services import prompt_constants as pc
from services.prompt_generator import assemble_generation_prompt, verify_locked
from services.comfyui_client import ComfyUIClient

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "workflows" / "amazing-z-photo_API_Create_CHAR.json"


def _persona(**kw):
    base = dict(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
    )
    base.update(kw)
    return PersonaOptions(**base)


def _workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


# --- h1: vocabulary + template coverage ---
def test_vocab_coverage():
    for e in ShotFramingType:
        assert cv.FRAMING_PHRASES.get(e.value), f"missing framing phrase: {e.value}"
    for e in CameraAngleType:
        assert cv.CAMERA_ANGLE_PHRASES.get(e.value), f"missing angle phrase: {e.value}"
    for e in ExpressionType:
        assert cv.EXPRESSION_PHRASES.get(e.value), f"missing expression phrase: {e.value}"
    for e in PhotoStyleType:
        t = pc.PHOTO_STYLE_TEMPLATES.get(e.value)
        assert t, f"missing photo style template: {e.value}"
        assert "{$@}" in t, f"template '{e.value}' missing {{$@}} substitution token"


def test_vocab_has_no_ageon_language():
    all_phrases = (
        list(cv.FRAMING_PHRASES.values())
        + list(cv.CAMERA_ANGLE_PHRASES.values())
        + list(cv.EXPRESSION_PHRASES.values())
    )
    for text in all_phrases:
        assert "youthful" not in text.lower(), f"age-down language in: {text}"


# --- h2: scaffold composition ---
def test_default_shot_is_waist_up_eye_level():
    positive, _neg, _locked = assemble_generation_prompt(_persona())
    assert "waist-up portrait" in positive
    assert "shot at eye level" in positive
    assert "full-body" not in positive


def test_full_body_framing_restores_legacy_crop():
    shot = ShotOptions(framing=ShotFramingType.FULL_BODY)
    positive, _neg, _locked = assemble_generation_prompt(_persona(), shot=shot)
    assert "full-body shot, whole figure in frame" in positive


def test_locked_identity_block_unchanged():
    positive, _neg, locked = assemble_generation_prompt(_persona())
    assert "28 years old" in locked
    assert "a Caucasian woman with fair skin" in locked
    assert locked in positive  # identity block appears verbatim


def test_locked_identity_block_carries_new_ethnicity_phrase():
    # A NEW regional ethnicity value flows into the locked identity block via
    # ETHNICITY_PHRASES with no other wiring (purely additive expansion).
    positive, _neg, locked = assemble_generation_prompt(_persona(ethnicity="slavic"))
    assert "a Slavic woman with fair skin, high cheekbones and gently rounded features" in locked
    assert locked in positive
    # and the legacy phrase is NOT emitted for this character
    assert "a Caucasian woman with fair skin" not in locked


# --- h3: expression resolution ---
def test_explicit_expression_suppresses_personality():
    persona = _persona(personality=PersonalityType.SHY)  # -> "a shy, bashful expression"
    shot = ShotOptions(expression=ExpressionType.CONFIDENT)
    positive, _neg, _locked = assemble_generation_prompt(persona, shot=shot)
    assert "a confident self-assured expression" in positive
    assert "a shy, bashful expression" not in positive


def test_personality_expression_stands_without_override():
    persona = _persona(personality=PersonalityType.SHY)
    positive, _neg, _locked = assemble_generation_prompt(persona)
    assert "a shy, bashful expression" in positive
    assert "a soft pleasant smile" not in positive


def test_default_soft_smile_when_no_personality():
    positive, _neg, _locked = assemble_generation_prompt(_persona())
    assert "a soft pleasant smile" in positive


# --- h4: framing survival gate ---
def test_framing_tokens_verification():
    shot = ShotOptions()
    tokens = cv.framing_tokens(shot)
    assert tokens  # non-empty for defaults
    with_framing = "waist-up portrait, shot at eye level, facing the camera, centered composition, blonde"
    without_framing = "a stunning blonde woman in golden light"
    assert verify_locked(with_framing, tokens) is True
    assert verify_locked(without_framing, tokens) is False


# --- h5: whitelist ---
def test_whitelist_dims_are_multiples_of_16():
    for ratio, (w, h) in op.ASPECT_RATIO_DIMS.items():
        assert w % 16 == 0 and h % 16 == 0, f"{ratio}: {w}x{h} not /16"


def test_default_aspect_matches_legacy_dims():
    assert op.ASPECT_RATIO_DIMS["2:3"] == (1088, 1600)


def test_bad_aspect_ratio_rejected():
    raised = False
    try:
        OutputOptions(aspectRatio="7:5")
    except ValueError:
        raised = True
    assert raised


def test_resolution_whitelist():
    assert OutputOptions(resolution="1088x1600").resolution == "1088x1600"
    raised = False
    try:
        OutputOptions(resolution="944x1408")  # old fake default, never real — now rejected
    except ValueError:
        raised = True
    assert raised


def test_dims_for_precedence():
    assert op.dims_for(aspect_ratio="1:1", resolution="1088x1600") == (1088, 1600)  # resolution wins
    assert op.dims_for(aspect_ratio="1:1") == (1328, 1328)
    assert op.dims_for() == (1088, 1600)  # default


# --- h6: workflow injection ---
def test_photo_style_rewrites_node_125():
    wf = _workflow()
    out = ComfyUIClient.prepare_character_workflow(wf, "prompt", photo_style="polished")
    # photo_style_template() is the source of truth for node 125 (it applies the
    # tunable color-grade clause on top of the raw PHOTO_STYLE_TEMPLATES entry --
    # see test_color_grade_* below), so compare against the function, not the dict.
    assert out["125"]["inputs"]["value"] == pc.photo_style_template("polished")
    # None leaves the baked-in text
    out2 = ComfyUIClient.prepare_character_workflow(wf, "prompt", photo_style=None)
    assert out2["125"]["inputs"]["value"] == wf["125"]["inputs"]["value"]


def test_hires_rewires_output_switch():
    wf = _workflow()
    out = ComfyUIClient.prepare_character_workflow(wf, "prompt", seed=42, hires=True)
    assert out["207"]["inputs"]["any_01"] == ["300", 0]
    assert out["181"]["inputs"]["noise_seed"] == 42
    off = ComfyUIClient.prepare_character_workflow(wf, "prompt", seed=42, hires=False)
    assert off["207"]["inputs"]["any_01"] == ["284", 0]


def test_aspect_ratio_writes_dims():
    wf = _workflow()
    out = ComfyUIClient.prepare_character_workflow(wf, "prompt", aspect_ratio="1:1")
    assert out["243"]["inputs"]["value"] == 1328
    assert out["248"]["inputs"]["value"] == 1328


def test_template_not_mutated():
    wf = _workflow()
    snapshot = copy.deepcopy(wf)
    ComfyUIClient.prepare_character_workflow(wf, "prompt", seed=1, photo_style="studio", hires=True)
    assert wf == snapshot  # deepcopy regression guard


# --- h7: static workflow JSON guard ---
def test_workflow_json_invariants():
    wf = _workflow()
    assert wf["300"]["class_type"] == "VAEDecode"
    assert wf["300"]["inputs"]["samples"] == ["181", 0]
    assert wf["300"]["inputs"]["vae"] == ["287", 0]
    assert "{$@}" in wf["125"]["inputs"]["value"]
    assert wf["9"]["inputs"]["images"] == ["207", 0]
    assert wf["207"]["inputs"]["any_01"] == ["284", 0]  # dormant by default


# --- h8: n clamp surface ---
def test_output_options_defaults():
    o = OutputOptions()
    assert o.n == 1
    assert o.hires is None
    assert o.aspectRatio == "2:3"
    assert o.resolution is None




# --- time-of-day / lighting option ---
def test_time_vocab_coverage():
    from models.enums import TimeOfDayType, LightingType
    for t in TimeOfDayType:
        assert cv.TIME_OF_DAY_PHRASES.get(t.value), f"missing time phrase: {t.value}"
    for li in LightingType:
        assert cv.LIGHTING_PHRASES.get(li.value), f"missing lighting phrase: {li.value}"


def test_time_of_day_is_a_verified_token():
    """timeOfDay joins framing_tokens -> the polish gate enforces its survival."""
    from models.enums import TimeOfDayType
    shot = ShotOptions(timeOfDay=TimeOfDayType.NIGHT)
    tokens = cv.framing_tokens(shot)
    assert any("night" in t for t in tokens)
    # And it lands in the assembled prompt.
    persona = _persona()
    positive, _, _ = assemble_generation_prompt(persona, shot=shot)
    assert "night" in positive.lower()
    # Unset -> no time language injected by the shot block.
    assert not any("scene set" in t for t in cv.framing_tokens(ShotOptions()))


def test_lighting_joins_shot_block():
    from models.enums import LightingType
    shot = ShotOptions(lighting=LightingType.NEON)
    assert "neon" in cv.compose_shot_block(shot).lower()


def test_polished_wrapper_adapts_to_night(monkeypatch):
    """polished@night swaps the daylight grade for a low-key night grade.

    Isolated from the (separate) color-grade clause via monkeypatch so this
    test stays focused on the time-of-day swap mechanic; see
    test_color_grade_default_generation_color_grade_* for that clause.
    """
    monkeypatch.setattr(pc.settings, "GENERATION_COLOR_GRADE", "")
    day = pc.photo_style_template("polished")
    night = pc.photo_style_template("polished", "night")
    assert day == pc.PHOTO_STYLE_TEMPLATES["polished"]      # default byte-identical
    assert night != day
    assert "{$@}" in night                                   # substitution token intact
    assert "night" in night.lower()
    assert "warm color grade" not in night                   # daylight line replaced
    # studio/candid ignore time; unknown style -> "".
    assert pc.photo_style_template("studio", "night") == pc.PHOTO_STYLE_TEMPLATES["studio"]
    assert pc.photo_style_template("candid_phone", "night") == pc.PHOTO_STYLE_TEMPLATES["candid_phone"]
    assert pc.photo_style_template(None, "night") == ""


def test_night_wrapper_reaches_node_125():
    from models.enums import TimeOfDayType
    wf = json.loads(WORKFLOW_PATH.read_text())
    out = ComfyUIClient.prepare_character_workflow(
        wf, "prompt", photo_style="polished", time_of_day="night"
    )
    assert "night" in out["125"]["inputs"]["value"].lower()


# --- color grade (GENERATION styles only; node 125) ---
def test_color_grade_default_present_in_generation_styles():
    """Default settings.GENERATION_COLOR_GRADE clause lands in every GENERATION
    style's wrapper text -- natural/polished/studio get it verbatim, candid_phone
    gets the deliberately milder companion clause."""
    grade = pc.settings.GENERATION_COLOR_GRADE
    assert grade  # the shipped default is non-empty
    for style in ("natural", "polished", "studio"):
        assert grade in pc.photo_style_template(style), f"{style} missing color-grade clause"
    assert pc._CANDID_COLOR_GRADE_MILD in pc.photo_style_template("candid_phone")
    assert grade not in pc.photo_style_template("candid_phone")  # gets the mild variant, not verbatim


def test_color_grade_empty_env_is_byte_identical_to_legacy(monkeypatch):
    """Empty GENERATION_COLOR_GRADE disables the clause entirely -- every style's
    wrapper (including the polished@night time-swapped variant) reverts to
    exactly the pre-feature text."""
    monkeypatch.setattr(pc.settings, "GENERATION_COLOR_GRADE", "")
    for style in ("natural", "polished", "studio", "candid_phone"):
        assert pc.photo_style_template(style) == pc.PHOTO_STYLE_TEMPLATES[style]
    night = pc.photo_style_template("polished", "night")
    assert night == pc.PHOTO_STYLE_TEMPLATES["polished"].replace(
        pc._POLISHED_DAY_LINE, pc._POLISHED_TIME_LINES["night"]
    )


def test_color_grade_candid_phone_is_milder_than_standard():
    """candid_phone's clause deliberately drops the 'more produced' language
    (balanced contrast) so the raw/candid look isn't pushed toward a graded,
    finished aesthetic -- while still addressing the washed-out/faded complaint
    that motivated this feature. (The old 'polished final finish' gloss vocab was
    removed from the standard default entirely, so it no longer differentiates.)"""
    standard = pc.settings.GENERATION_COLOR_GRADE
    mild = pc._CANDID_COLOR_GRADE_MILD
    assert "balanced contrast" in standard
    assert "balanced contrast" not in mild
    assert "no washed-out or faded tones" in standard
    assert "no washed-out or faded tones" in mild  # core fix kept in both


def test_color_grade_avoids_oversaturation_trigger_words():
    """Explicit guard against wording that flips the subtle grade into an
    Instagram-filter look."""
    banned = ("vibrant", "hdr", "oversaturat")  # covers oversaturated/oversaturation
    for clause in (pc.settings.GENERATION_COLOR_GRADE, pc._CANDID_COLOR_GRADE_MILD):
        low = clause.lower()
        for word in banned:
            assert word not in low, f"'{word}' in color-grade clause: {clause}"


def test_color_grade_is_tunable_via_settings(monkeypatch):
    """Changing settings.GENERATION_COLOR_GRADE (i.e. the env var) changes the
    wording with no code change -- proves the env-tunability requirement."""
    marker = "a distinctive marker color-grade phrase for this test"
    monkeypatch.setattr(pc.settings, "GENERATION_COLOR_GRADE", marker)
    for style in ("natural", "polished", "studio"):
        assert marker in pc.photo_style_template(style)


def test_color_grade_never_touches_edit_suffixes(monkeypatch):
    """The GENERATION color-grade knob is fully independent of the EDIT-pipeline
    suffixes (qwen edit steps) -- changing one must never leak into the other."""
    marker = "a distinctive marker color-grade phrase for this test"
    monkeypatch.setattr(pc.settings, "GENERATION_COLOR_GRADE", marker)
    for suffix in pc.EDIT_PHOTO_STYLE_SUFFIXES.values():
        assert marker not in suffix
    prompt = "Change the person's clothing to: red evening gown"
    out = pc.apply_edit_photo_style(prompt, "polished")
    assert marker not in out
    # WS-S: the style clause LEADS the body, with a short tail echo re-stating it.
    assert out == (
        f"{pc.EDIT_PHOTO_STYLE_SUFFIXES['polished']} {prompt}. "
        f"{pc.EDIT_PHOTO_STYLE_TAIL_ECHOES['polished']}"
    )
    # Disabling the generation knob must not affect the edit suffix either.
    monkeypatch.setattr(pc.settings, "GENERATION_COLOR_GRADE", "")
    assert pc.apply_edit_photo_style(prompt, "polished") == out


def test_kink_moods_capped_at_two():
    """3-4 stacked mood clauses muddy the aesthetic -> cap at 2 (order kept)."""
    from services import attribute_phrases as ap
    from models.enums import KinkType
    kinks = list(KinkType)[:4]
    joined = ap.kinks_phrase(kinks)
    expected = [ap.phrase(ap.KINK_PHRASES, k) for k in kinks[:2]]
    assert joined == ", ".join(e for e in expected if e)


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
