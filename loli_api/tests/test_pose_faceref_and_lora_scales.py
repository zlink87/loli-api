"""
WS-F (hero face as a render conditioning input) + WS-N2 (style-scaled LoRA strengths
+ anti-HDR text) — behavior + worker-integration coverage.

WS-F: on the faceref pose graph the hero face donor (node 210) is wired into the prompt
ENCODERS as a third conditioning image (image3), so the diffusion itself locks facial
structure to the real hero instead of deriving it from the random-faced nude base.
``build_pose_prompt(face_ref_conditioning=True)`` adds the one matching sentence, and
``pipeline_worker`` flips that flag ONLY when the loaded template exposes the image3
encoder input (``pose_template_has_face_ref_conditioning``).

WS-N2: natural/candid_phone batches otherwise render editorial/contrasty because the pose
graph's LoRA stack (304 URP / 305 NSFW / 306 skin) applies its baked strengths to every
style. ``prepare_pose_workflow(lora_scales=...)`` dials them down for those styles only,
and the natural photo-style suffix / EDIT_SKIN_NEGATIVE carry explicit anti-HDR wording.

Graph-structure lint for the new faceref JSON lives in test_dark_asset_graphs.py (that
file owns the dark-asset graph linting); this file owns the prompt/scale/text behavior
and the pipeline_worker wiring. Fully offline — no GPU / RunPod / network.
"""
import asyncio
import json
from pathlib import Path

import models.requests as _mr

# These tests exercise prompt/scale logic, not the SSRF allowlist (mirrors
# test_single_pass_pipeline.py's stand-in so a bare source_image validates).
_mr.validate_source_image = lambda u: u  # type: ignore

from config import settings
from models.enums import PoseType, PhotoStyleType
from models.requests import PipelineEditRequest
from services import prompt_constants as pc
from api.v1.endpoints.pose import (
    build_pose_prompt,
    prepare_pose_workflow,
    pose_template_has_face_ref_conditioning,
)
from workers.pipeline_worker import (
    PipelineBackgroundWorker,
    _natural_lora_scales,
    _extract_applied_lora_scales,
)

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"
_FACEREF = "pose_2511_skinlora_faceref_API.json"
_SKINLORA = "pose_2511_skinlora_API.json"
_RAPID = "edit_pose_action.json"

_FACE_CLAUSE = (
    "Her face, facial structure, and hairline are exactly those of the person "
    "in image 3; render that same face."
)


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ===========================================================================
# WS-F — build_pose_prompt(face_ref_conditioning=...)
# ===========================================================================
def test_face_ref_clause_present_exactly_once_when_flag_true():
    p = build_pose_prompt(PoseType.SITTING, face_ref_conditioning=True)
    assert p.count(_FACE_CLAUSE) == 1


def test_face_ref_clause_absent_when_flag_false_or_default():
    # Explicit False and the default (omitted) both leave the prompt without the clause.
    assert _FACE_CLAUSE not in build_pose_prompt(PoseType.SITTING, face_ref_conditioning=False)
    assert _FACE_CLAUSE not in build_pose_prompt(PoseType.SITTING)


def test_face_ref_clause_sits_right_after_the_target_pose_sentence():
    p = build_pose_prompt(PoseType.SITTING, face_ref_conditioning=True)
    # Directly after "The target pose is: {desc}." and before the identity/new-pose text.
    assert p.index("The target pose is:") < p.index(_FACE_CLAUSE) < p.index("The new pose should match")


def test_face_ref_clause_composes_with_other_pose_options():
    # The clause must not disturb the rest of the builder (scene/outfit/solo still land).
    p = build_pose_prompt(
        PoseType.SITTING,
        outfit_text="a charcoal business suit",
        scene_text="a cozy sunlit loft",
        dress_mode=True,
        face_ref_conditioning=True,
    )
    assert p.count(_FACE_CLAUSE) == 1
    assert "Place her in: a cozy sunlit loft." in p
    assert "Dress her in: a charcoal business suit" in p


# ===========================================================================
# WS-N2 — _natural_lora_scales decision
# ===========================================================================
def test_natural_lora_scales_for_natural_and_candid():
    expected = {
        "304": settings.NATURAL_LORA_URP,
        "305": settings.NATURAL_LORA_NSFW,
        "306": settings.NATURAL_LORA_SKIN,
    }
    assert _natural_lora_scales("natural") == expected
    assert _natural_lora_scales("candid_phone") == expected
    # Accepts a PhotoStyleType enum (its .value) as well as the raw string.
    assert _natural_lora_scales(PhotoStyleType.NATURAL) == expected


def test_natural_lora_scales_none_for_other_styles():
    assert _natural_lora_scales("polished") is None
    assert _natural_lora_scales("studio") is None
    assert _natural_lora_scales(None) is None
    assert _natural_lora_scales(PhotoStyleType.POLISHED) is None


def test_natural_lora_scales_minus_one_sentinel_skips_that_node(monkeypatch):
    # -1.0 on a node's setting means "leave that node's baked strength alone" — it drops
    # out of the override dict entirely (the other two still scale).
    monkeypatch.setattr(settings, "NATURAL_LORA_NSFW", -1.0)
    scales = _natural_lora_scales("natural")
    assert scales == {"304": settings.NATURAL_LORA_URP, "306": settings.NATURAL_LORA_SKIN}
    assert "305" not in scales


def test_natural_lora_scales_all_sentinel_is_none(monkeypatch):
    for attr in ("NATURAL_LORA_URP", "NATURAL_LORA_NSFW", "NATURAL_LORA_SKIN"):
        monkeypatch.setattr(settings, attr, -1.0)
    assert _natural_lora_scales("natural") is None


# ===========================================================================
# WS-N2 — prepare_pose_workflow(lora_scales=...)
# ===========================================================================
def test_prepare_writes_natural_scales_on_skinlora_nodes():
    g = _load(_SKINLORA)
    wf = prepare_pose_workflow(
        g, "s.png", "r.png", lora_scales={"304": 0.6, "305": 0.5, "306": 0.7}
    )
    assert wf["304"]["inputs"]["strength_model"] == 0.6
    assert wf["305"]["inputs"]["strength_model"] == 0.5
    assert wf["306"]["inputs"]["strength_model"] == 0.7


def test_prepare_none_leaves_baked_strengths_untouched():
    # polished/studio/None pass lora_scales=None -> the baked stack survives verbatim.
    g = _load(_SKINLORA)
    wf = prepare_pose_workflow(g, "s.png", "r.png", lora_scales=None)
    assert wf["304"]["inputs"]["strength_model"] == 0.8
    assert wf["305"]["inputs"]["strength_model"] == 0.65
    assert wf["306"]["inputs"]["strength_model"] == 1.0


def test_prepare_partial_dict_skips_absent_node():
    # A dict missing node 305 (the -1.0-sentinel case) leaves 305 baked, scales 304/306.
    g = _load(_SKINLORA)
    wf = prepare_pose_workflow(g, "s.png", "r.png", lora_scales={"304": 0.6, "306": 0.7})
    assert wf["304"]["inputs"]["strength_model"] == 0.6
    assert wf["305"]["inputs"]["strength_model"] == 0.65  # baked, untouched
    assert wf["306"]["inputs"]["strength_model"] == 0.7


def test_prepare_lora_scales_is_noop_on_rapid_graph():
    # The v1 Rapid pose graph carries none of nodes 304/305/306 — a scales dict is a true
    # no-op there (never raises, never invents a node).
    g = _load(_RAPID)
    wf = prepare_pose_workflow(
        g, "s.png", "r.png", lora_scales={"304": 0.6, "305": 0.5, "306": 0.7}
    )
    assert not any(nid in wf for nid in ("304", "305", "306"))


def test_prepare_lora_scales_omitted_is_byte_identical():
    # Backward compat: omitting the kwarg vs. passing None yields an identical workflow.
    g = _load(_SKINLORA)
    without = prepare_pose_workflow(g, "s.png", "r.png", prompt="P", seed=1)
    with_none = prepare_pose_workflow(g, "s.png", "r.png", prompt="P", seed=1, lora_scales=None)
    assert json.dumps(without, sort_keys=True) == json.dumps(with_none, sort_keys=True)


# ===========================================================================
# WS-N2 — _extract_applied_lora_scales (feeds the step _debug meta)
# ===========================================================================
def test_extract_applied_scales_reads_back_from_built_skinlora_workflow():
    g = _load(_SKINLORA)
    wf = prepare_pose_workflow(g, "s.png", "r.png", lora_scales=_natural_lora_scales("natural"))
    applied = _extract_applied_lora_scales(wf, "natural")
    assert applied == {
        "304": settings.NATURAL_LORA_URP,
        "305": settings.NATURAL_LORA_NSFW,
        "306": settings.NATURAL_LORA_SKIN,
    }


def test_extract_applied_scales_none_on_rapid_and_non_natural():
    rapid = prepare_pose_workflow(_load(_RAPID), "s.png", "r.png",
                                  lora_scales=_natural_lora_scales("natural"))
    assert _extract_applied_lora_scales(rapid, "natural") is None  # no LoRA nodes on v1
    skin = prepare_pose_workflow(_load(_SKINLORA), "s.png", "r.png", lora_scales=None)
    assert _extract_applied_lora_scales(skin, "polished") is None  # non-natural style


# ===========================================================================
# WS-N2 — prompt_constants anti-HDR text
# ===========================================================================
def test_natural_suffix_carries_anti_hdr_wording_and_keeps_flow():
    natural = pc.EDIT_PHOTO_STYLE_SUFFIXES["natural"]
    assert "soft balanced contrast, unboosted true-to-life colors, no HDR look" in natural
    # The prior makeup wording (asserted elsewhere) survives, and texture doctrine holds.
    assert "light everyday makeup, not a styled photoshoot" in natural
    assert "texture" in natural.lower()
    # Single terminal period — the fragment flows into the last sentence, not appended raw.
    assert natural.rstrip().endswith("no HDR look.")


def test_skin_negative_carries_anti_hdr_terms_and_keeps_existing():
    neg = pc.EDIT_SKIN_NEGATIVE
    assert "oversaturated colors, HDR, crushed blacks, harsh high contrast" in neg
    assert "airbrushed skin" in neg  # existing distinctive fragment survives
    # It flows through edit_negative() (the live pose/edit negative) too.
    assert "HDR" in pc.edit_negative()


def test_natural_anti_hdr_words_do_not_trip_gloss_blur_banned_vocab():
    # Guard: the words WS-N2 added to the natural suffix must not collide with the
    # gloss/blur/airbrush ban that test_photo_style enforces on every non-empty clause.
    banned = (
        "flawless skin", "porcelain", "silky smooth", "airbrush",
        "soft focus", "dreamy glow", "glamour skin",
        "lightly retouched skin", "retouched photograph",
    )
    low = pc.EDIT_PHOTO_STYLE_SUFFIXES["natural"].lower()
    for b in banned:
        assert b not in low, f"natural suffix now trips banned gloss/blur vocab: {b!r}"


# ===========================================================================
# Integration — pipeline_worker threads both flags through _build_step_workflow
# ===========================================================================
def _worker(pose_path: str) -> PipelineBackgroundWorker:
    return PipelineBackgroundWorker(
        job_manager=None, comfyui_client=None, storage_service=None,
        pose_workflow_path=str(_WF_DIR / pose_path),
        outfit_workflow_path=str(_WF_DIR / "test_final_API.json"),
        background_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )


def _pose_wf(pose_path: str, photo_style, face_ref_name=None) -> dict:
    w = _worker(pose_path)
    asyncio.run(w._load_workflows())
    req = PipelineEditRequest(
        source_image="https://x.supabase.co/s.png",
        pose=PoseType.SITTING,
        photoStyle=photo_style,
    )
    return w._build_step_workflow(
        "pose", req, "src.png", 7, "job",
        pose_ref_name="ref.png", face_ref_name=face_ref_name,
    )


def test_worker_faceref_natural_adds_clause_and_scales_loras():
    # Task D: faceref template WITH a staged hero donor -> face clause in node 114; natural
    # style -> LoRA stack dialed down. The staged donor (face_ref_name) is what gives the
    # "image 3" clause a real conditioning image to bind to (see the both-conditions guard).
    wf = _pose_wf(_FACEREF, PhotoStyleType.NATURAL, face_ref_name="donor.png")
    assert _FACE_CLAUSE in wf["114"]["inputs"]["prompt"]
    assert wf["210"]["inputs"]["image"] == "donor.png"  # donor actually wired to node 210
    assert wf["304"]["inputs"]["strength_model"] == settings.NATURAL_LORA_URP
    assert wf["305"]["inputs"]["strength_model"] == settings.NATURAL_LORA_NSFW
    assert wf["306"]["inputs"]["strength_model"] == settings.NATURAL_LORA_SKIN
    # The read-back that feeds the step _debug meta sees the same applied scales.
    assert _extract_applied_lora_scales(wf, "natural") == {
        "304": settings.NATURAL_LORA_URP,
        "305": settings.NATURAL_LORA_NSFW,
        "306": settings.NATURAL_LORA_SKIN,
    }


def test_worker_faceref_without_staged_face_omits_clause_but_still_scales_loras():
    # GUARD (both-conditions): even on the faceref graph, with NO dedicated hero donor staged
    # (face_ref_name None) there is no image3 to bind, so the "render that same face" clause
    # must be ABSENT — node 210 falls back to the step source for the ReActor stamp only.
    # LoRA scaling is independent of the donor and still fires for the natural style.
    wf = _pose_wf(_FACEREF, PhotoStyleType.NATURAL)  # no face_ref_name
    assert _FACE_CLAUSE not in wf["114"]["inputs"]["prompt"]
    assert wf["210"]["inputs"]["image"] == "src.png"  # fallback donor == step source
    assert wf["304"]["inputs"]["strength_model"] == settings.NATURAL_LORA_URP
    assert wf["305"]["inputs"]["strength_model"] == settings.NATURAL_LORA_NSFW
    assert wf["306"]["inputs"]["strength_model"] == settings.NATURAL_LORA_SKIN


def test_worker_skinlora_polished_no_clause_and_baked_loras():
    # Non-faceref template -> no face clause; polished style -> baked strengths survive.
    wf = _pose_wf(_SKINLORA, PhotoStyleType.POLISHED)
    assert _FACE_CLAUSE not in wf["114"]["inputs"]["prompt"]
    assert wf["304"]["inputs"]["strength_model"] == 0.8
    assert wf["305"]["inputs"]["strength_model"] == 0.65
    assert wf["306"]["inputs"]["strength_model"] == 1.0
    assert _extract_applied_lora_scales(wf, "polished") is None


def test_worker_rapid_natural_is_a_noop_for_both_features():
    # v1 Rapid pose graph has no image3 encoder input and no LoRA nodes -> both features
    # no-op: no face clause, no injected LoRA nodes, no error.
    wf = _pose_wf(_RAPID, PhotoStyleType.NATURAL)
    assert _FACE_CLAUSE not in wf["114"]["inputs"]["prompt"]
    assert not any(nid in wf for nid in ("304", "305", "306"))


# ===========================================================================
# WS-FRC — face-ref donor crop (drop the hero's own scenery before it reaches
# node 210's image3 conditioning). Crop helper reuses head_mask's YuNet detector;
# pipeline_worker._maybe_crop_face_donor gates it on settings.FACE_REF_CROP.
# ===========================================================================
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from services import head_mask  # noqa: E402
from workers.pipeline_worker import _maybe_crop_face_donor  # noqa: E402


def _png(h: int, w: int, val: int = 90) -> bytes:
    return cv2.imencode(".png", np.full((h, w, 3), val, np.uint8))[1].tobytes()


def _crop_with_box(image_bytes, box):
    """Run crop_face_donor with the YuNet detector swapped for a fixed bbox (manual save/
    restore so it runs under this file's __main__ runner too, not just pytest)."""
    saved = head_mask._detect_face_box
    head_mask._detect_face_box = lambda img: box
    try:
        return head_mask.crop_face_donor(image_bytes)
    finally:
        head_mask._detect_face_box = saved


def _maybe_with(image_bytes, flag, box=None):
    saved_flag = settings.FACE_REF_CROP
    saved_det = head_mask._detect_face_box
    settings.FACE_REF_CROP = flag
    if box is not None:
        head_mask._detect_face_box = lambda img: box
    try:
        return _maybe_crop_face_donor(image_bytes, "job")
    finally:
        settings.FACE_REF_CROP = saved_flag
        head_mask._detect_face_box = saved_det


def test_crop_face_donor_crops_to_detected_region():
    # A known face box in a large frame -> the donor shrinks (its scenery mass is dropped).
    src = _png(1024, 1024)
    out, cropped = _crop_with_box(src, (400, 300, 200, 240))
    assert cropped and out != src
    dec = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    assert dec.shape[0] < 1024 and dec.shape[1] < 1024   # dimensions shrank


def test_crop_face_donor_detector_miss_returns_full_image_byte_identical():
    # A blank synthetic frame has no detectable face -> fall back to the full image, unchanged.
    blank = _png(240, 180, 128)
    out, cropped = head_mask.crop_face_donor(blank)
    assert not cropped and out == blank


def test_maybe_crop_flag_off_is_byte_identical_even_with_a_face():
    # FACE_REF_CROP off stages the FULL hero verbatim (legacy behavior), face or not.
    src = _png(1024, 1024)
    assert _maybe_with(src, False, box=(400, 300, 200, 240)) == src


def test_maybe_crop_flag_on_applies_crop():
    src = _png(1024, 1024)
    out = _maybe_with(src, True, box=(400, 300, 200, 240))
    assert out != src
    dec = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    assert dec.shape[0] < 1024 and dec.shape[1] < 1024


def test_maybe_crop_flag_on_detector_miss_falls_back_to_full_image():
    blank = _png(240, 180, 128)          # real detector runs, finds no face
    assert _maybe_with(blank, True) == blank


def test_face_ref_crop_defaults_on():
    # The scenery-dilution fix ships ENABLED (the whole point of WS-FRC).
    assert type(settings).model_fields["FACE_REF_CROP"].default is True


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn() if fn.__code__.co_argcount == 0 else None
            if fn.__code__.co_argcount == 0:
                print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\ndone ({failures} failures; monkeypatch tests skipped in direct mode)")
    sys.exit(1 if failures else 0)
