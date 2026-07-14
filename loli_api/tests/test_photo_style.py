"""
Tests for the edit-pipeline photo-style clause: the pure helper in
prompt_constants and its wiring through PipelineBackgroundWorker's
_build_step_workflow (which serves both interactive /v1/edit and batches).

Runs under pytest or directly: python loli_api/tests/test_photo_style.py
"""
import asyncio
from pathlib import Path

import models.requests as _mr

# The mapper builds a PipelineEditRequest whose source_image is SSRF-validated.
# These tests exercise prompt wiring, not the allowlist.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import PoseType, OutfitType, PhotoStyleType
from models.requests import PipelineEditRequest
from services.prompt_constants import (
    EDIT_PHOTO_STYLE_SUFFIXES,
    EDIT_PHOTO_STYLE_TAIL_ECHOES,
    PHOTO_STYLE_TEMPLATES,
    apply_edit_photo_style,
)
from workers.pipeline_worker import PipelineBackgroundWorker

_LOLI_API_DIR = Path(__file__).resolve().parent.parent
_POSE_WF = str(_LOLI_API_DIR / "workflows" / "edit_pose_action.json")
_OUTFIT_WF = str(_LOLI_API_DIR / "workflows" / "test_final_API.json")


# --- pure helper -----------------------------------------------------------

def test_suffix_keys_match_photo_style_enum():
    # Every selectable style must have an (possibly empty) edit clause, and the
    # keys must stay aligned with the generation-side templates.
    values = {s.value for s in PhotoStyleType}
    assert set(EDIT_PHOTO_STYLE_SUFFIXES) == values
    assert set(PHOTO_STYLE_TEMPLATES) == values


def test_apply_none_and_unknown_are_noops():
    assert apply_edit_photo_style("Change the outfit", None) == "Change the outfit"
    assert apply_edit_photo_style("Change the outfit", "nope") == "Change the outfit"


def test_apply_candid_phone_is_legacy_noop():
    prompt = "Change the person's clothing to: red evening gown"
    assert apply_edit_photo_style(prompt, PhotoStyleType.CANDID_PHONE) == prompt
    assert apply_edit_photo_style(prompt, "candid_phone") == prompt


def test_apply_polished_leads_with_clause():
    # WS-S: the style clause now LEADS the positive (strongest binding), with a short
    # tail echo — it used to trail (weakest binding) where it lost the fidelity fight.
    prompt = "Change the person's clothing to: red evening gown"
    out = apply_edit_photo_style(prompt, PhotoStyleType.POLISHED)
    assert out.startswith(EDIT_PHOTO_STYLE_SUFFIXES["polished"])  # clause LEADS
    assert prompt in out                                         # body preserved
    # sentence-terminated body before the echo
    assert f"{prompt}. " in out
    # short tail echo re-states the finish at the end
    assert out.endswith(EDIT_PHOTO_STYLE_TAIL_ECHOES["polished"])


def test_apply_polished_scene_lighting_drops_key_light():
    # Scene-lit pose step: when the item carries its own lighting/time-of-day (which already
    # re-light the frame via build_pose_prompt), the polished wrapper's generic "soft
    # flattering key light" fights that scene light — so scene_lighting=True drops JUST that
    # fragment from the polished lead. Only the pose call site passes it.
    prompt = "Change the person's clothing to: red evening gown"
    lit = apply_edit_photo_style(prompt, PhotoStyleType.POLISHED, scene_lighting=True)
    assert "soft flattering key light" not in lit
    assert prompt in lit                                     # body still preserved
    assert lit.startswith("Give this a professional photographic retouch")  # still leads polished
    # The remaining lead reads cleanly (the comma-joined fragment was removed whole).
    assert "true-to-life color, and a softly blurred" in lit

    # Default (scene_lighting False / omitted) keeps the key light, byte-identical.
    assert (
        apply_edit_photo_style(prompt, PhotoStyleType.POLISHED, scene_lighting=False)
        == apply_edit_photo_style(prompt, PhotoStyleType.POLISHED)
    )
    assert "a soft flattering key light," in apply_edit_photo_style(prompt, PhotoStyleType.POLISHED)

    # scene_lighting on a non-polished style is a no-op (only polished carries the fragment).
    assert (
        apply_edit_photo_style(prompt, PhotoStyleType.NATURAL, scene_lighting=True)
        == apply_edit_photo_style(prompt, PhotoStyleType.NATURAL)
    )


def test_suffixes_never_touch_identity():
    # "face" is intentionally allowed ONLY inside the "skin tone even and
    # consistent with the face" clause (natural/polished/studio) — it anchors
    # body-skin tone to the (separately identity-locked) face rather than altering
    # it. Strip that one known-safe occurrence before the sweep so the guard still
    # catches any OTHER accidental identity language.
    safe_clause = "skin tone even and consistent with the face"
    for suffix in EDIT_PHOTO_STYLE_SUFFIXES.values():
        text = suffix.lower().replace(safe_clause, "")
        for banned in ("face", "hair", "eye", "identity", "features"):
            assert banned not in text, f"'{banned}' in style clause: {suffix}"


def test_style_clauses_preserve_texture_and_ban_gloss_blur_vocab():
    # WS-S skin-texture doctrine: every non-empty style clause in BOTH maps (edit
    # suffixes + generation templates) explicitly preserves real skin texture and
    # carries NONE of the gloss/blur/airbrush vocabulary. candid_phone's EDIT suffix
    # is "" (the raw opt-out — no retouch clause, so it can't smooth skin), skipped.
    banned = (
        "flawless skin", "porcelain", "silky smooth", "airbrush",
        "soft focus", "dreamy glow", "glamour skin",
        "lightly retouched skin", "retouched photograph",
    )
    for label, m in (("edit", EDIT_PHOTO_STYLE_SUFFIXES), ("generation", PHOTO_STYLE_TEMPLATES)):
        for style, clause in m.items():
            if not clause:
                continue
            low = clause.lower()
            assert "texture" in low, f"{label}/{style} missing texture-preservation wording"
            for b in banned:
                assert b not in low, f"{label}/{style} contains banned gloss/blur vocab: {b!r}"


def test_polished_studio_carry_explicit_no_skin_smoothing_sentence():
    # PROMPT DE-GLOSS doctrine: photography styles may only retouch light/exposure/
    # contrast/color + background depth of field -- NEVER smooth, blur, or gloss
    # skin/features. polished/studio (the two "retouched" finishes, in both the
    # edit-pipeline suffixes and the generation-side templates) must say so
    # explicitly rather than relying on the now-removed "lightly retouched skin"
    # framing to imply it.
    doctrine = "do not smooth, blur, or retouch the skin itself"
    for label, m in (("edit", EDIT_PHOTO_STYLE_SUFFIXES), ("generation", PHOTO_STYLE_TEMPLATES)):
        for style in ("polished", "studio"):
            assert doctrine in m[style].lower(), f"{label}/{style} missing the no-skin-smoothing sentence"


def test_polished_studio_distinct_from_natural_via_light_identity():
    # polished/studio express their finish via LIGHT identity words and must differ
    # from the natural (as-shot) baseline.
    assert "key light" in EDIT_PHOTO_STYLE_SUFFIXES["polished"].lower()
    assert "softbox" in EDIT_PHOTO_STYLE_SUFFIXES["studio"].lower()
    for style in ("polished", "studio"):
        assert EDIT_PHOTO_STYLE_SUFFIXES[style] != EDIT_PHOTO_STYLE_SUFFIXES["natural"]


# --- PROMPT DE-GLOSS: natural counters the base model's heavy-makeup prior --

def test_natural_edit_suffix_counters_glamour_makeup_prior():
    # A "natural" batch was still reading as a styled photoshoot because nothing pushed
    # back on the base model's heavy-makeup prior; the edit suffix now says so explicitly.
    natural = EDIT_PHOTO_STYLE_SUFFIXES["natural"]
    assert "light everyday makeup, not a styled photoshoot" in natural
    # Natural-only: polished/studio/candid_phone (recently rewritten) are untouched.
    for style in ("polished", "studio", "candid_phone"):
        assert "everyday makeup" not in EDIT_PHOTO_STYLE_SUFFIXES[style]


def test_natural_generation_template_counters_glamour_makeup_prior():
    natural = PHOTO_STYLE_TEMPLATES["natural"]
    makeup_line = "Your subjects wear light everyday makeup, never heavy glamour makeup."
    assert makeup_line in natural
    # The line belongs to YOUR CONTEXT, so it must land BEFORE the "---" divider that
    # separates context from the substituted YOUR PHOTO prompt.
    assert natural.index(makeup_line) < natural.index("---")
    for style in ("polished", "studio", "candid_phone"):
        assert "everyday makeup" not in PHOTO_STYLE_TEMPLATES[style]


def test_apply_natural_leads_with_makeup_clause():
    # End-to-end: the new clause actually reaches the assembled edit prompt (not just the
    # constant), leading the body the same way the rest of the natural clause does.
    prompt = "Change the person's clothing to: red evening gown"
    out = apply_edit_photo_style(prompt, PhotoStyleType.NATURAL)
    assert out.startswith(EDIT_PHOTO_STYLE_SUFFIXES["natural"])
    assert "light everyday makeup, not a styled photoshoot" in out


# --- worker wiring ---------------------------------------------------------

def _worker():
    w = PipelineBackgroundWorker(
        job_manager=None,
        comfyui_client=None,
        storage_service=None,
        pose_workflow_path=_POSE_WF,
        outfit_workflow_path=_OUTFIT_WF,
    )
    asyncio.run(w._load_workflows())
    return w


def _request(**kw):
    base = dict(
        source_image="https://x.supabase.co/img.png",
        pose=PoseType.SITTING,
        outfit=OutfitType.BIKINI,
        prompt="on a beach at sunset",
    )
    base.update(kw)
    return PipelineEditRequest(**base)


def _positive_prompt(workflow: dict, step: str) -> str:
    if step == "pose":
        return workflow["114"]["inputs"]["prompt"]
    return workflow["16"]["inputs"]["positive"]


def test_build_step_workflow_wraps_person_rendering_steps_when_polished():
    # Pose and outfit ALWAYS get the photo-style clause — they're the
    # steps that actually re-diffuse the person's body, so this holds even on
    # a full request (pose + outfit + background all active).
    w = _worker()
    req = _request(photoStyle=PhotoStyleType.POLISHED)
    for step in ("pose", "outfit"):
        wf = w._build_step_workflow(step, req, "src.png", 42, "job-1", pose_ref_name="ref.png")
        prompt = _positive_prompt(wf, step)
        assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] in prompt, f"{step} missing polished clause"


def test_build_step_workflow_wraps_background_only_when_sole_step():
    # Background is masked out and composited back untouched whenever a
    # pose/outfit step is also active, so wrapping it there would only dress up
    # discarded pixels -> no clause. A background-only edit (no outfit/pose on
    # the request) has no mask/composite to skip, so it keeps the legacy
    # behavior of receiving the clause.
    w = _worker()

    full_req = _request(photoStyle=PhotoStyleType.POLISHED)  # outfit + pose also set
    wf_full = w._build_step_workflow(
        "background", full_req, "src.png", 42, "job-1", pose_ref_name="ref.png"
    )
    assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] not in _positive_prompt(wf_full, "background")

    bg_only_req = _request(photoStyle=PhotoStyleType.POLISHED, outfit=None, pose=None)
    wf_bg_only = w._build_step_workflow("background", bg_only_req, "src.png", 42, "job-1")
    assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] in _positive_prompt(wf_bg_only, "background")


def test_pipeline_defaults_to_polished():
    # The unified /v1/edit pipeline now DEFAULTS to POLISHED (was None) so a pipeline
    # edit matches the generated hero's retouched finish on the person-rendering
    # steps. The default request has outfit+pose set, so background stays
    # unwrapped (see test_build_step_workflow_wraps_background_only_when_sole_step).
    assert _request().photoStyle == PhotoStyleType.POLISHED
    w = _worker()
    req = _request()  # unset -> POLISHED default
    for step in ("pose", "outfit"):
        wf = w._build_step_workflow(step, req, "src.png", 42, "job-1", pose_ref_name="ref.png")
        assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] in _positive_prompt(wf, step)
    wf_bg = w._build_step_workflow("background", req, "src.png", 42, "job-1", pose_ref_name="ref.png")
    assert EDIT_PHOTO_STYLE_SUFFIXES["polished"] not in _positive_prompt(wf_bg, "background")


def test_build_step_workflow_explicit_none_or_candid_is_legacy_no_style():
    # Legacy "no style clause" is still reachable by explicitly opting out.
    w = _worker()
    none_style = _request(photoStyle=None)
    candid = _request(photoStyle=PhotoStyleType.CANDID_PHONE)
    for step in ("pose", "outfit", "background"):
        wf_none = w._build_step_workflow(step, none_style, "src.png", 42, "job-1", pose_ref_name="ref.png")
        wf_candid = w._build_step_workflow(step, candid, "src.png", 42, "job-1", pose_ref_name="ref.png")
        assert _positive_prompt(wf_none, step) == _positive_prompt(wf_candid, step)
        for suffix in (EDIT_PHOTO_STYLE_SUFFIXES["polished"], EDIT_PHOTO_STYLE_SUFFIXES["studio"]):
            assert suffix not in _positive_prompt(wf_none, step)


# --- Phase 5 observability: _extract_step_prompts reads back the EXACT prompt
# text a step's workflow was built with, off the injected node ids -----------

def test_extract_step_prompts_outfit_positive_carries_caption_marker_and_has_negative():
    from workers.pipeline_worker import _extract_step_prompts

    w = _worker()
    req = _request(outfitDetail="a cropped emerald silk camisole")
    wf = w._build_step_workflow("outfit", req, "src.png", 42, "job-1")
    prompts = _extract_step_prompts("outfit", wf)

    # Positive carries the concrete caption (known marker) the planner asked for.
    assert prompts["positive"]
    assert "a cropped emerald silk camisole" in prompts["positive"]
    assert prompts["positive"] == wf["16"]["inputs"]["positive"]
    # The V1 outfit graph always wires SOME text onto node 117 (inert at cfg 1,
    # but the text itself is real, not empty) -- present, not None.
    assert prompts["negative"]
    assert prompts["negative"] == wf["117"]["inputs"]["negative"]


def test_extract_step_prompts_unknown_step_or_missing_nodes_are_none():
    from workers.pipeline_worker import _extract_step_prompts

    assert _extract_step_prompts("bogus_step", {"16": {"inputs": {"positive": "x"}}}) == {
        "positive": None,
        "negative": None,
    }
    assert _extract_step_prompts("outfit", {}) == {"positive": None, "negative": None}


def test_extract_step_prompts_truncates_long_text():
    from workers.pipeline_worker import _extract_step_prompts, _DEBUG_PROMPT_TRUNC_CHARS

    long_text = "x" * (_DEBUG_PROMPT_TRUNC_CHARS + 500)
    wf = {
        "16": {"inputs": {"positive": long_text}},
        "117": {"inputs": {"negative": long_text}},
    }
    prompts = _extract_step_prompts("outfit", wf)
    assert len(prompts["positive"]) == _DEBUG_PROMPT_TRUNC_CHARS
    assert len(prompts["negative"]) == _DEBUG_PROMPT_TRUNC_CHARS


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
