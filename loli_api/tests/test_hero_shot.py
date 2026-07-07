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
    assert out["125"]["inputs"]["value"] == pc.PHOTO_STYLE_TEMPLATES["polished"]
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
