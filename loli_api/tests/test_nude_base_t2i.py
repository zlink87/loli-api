"""
Tests for WS-N: the text-to-image nude base + ReActor face lock.

Covers the NEW default path (settings.NUDE_BASE_T2I=True):
  * stable_nude_base_seed — deterministic zlib.crc32 per character (NOT hash()).
  * build_nude_base_prompt — the assembled base prompt carries the full locked
    identity block + the NAKED clause + the neutral standing pose + the plain
    studio backdrop + the char-gen quality tail + the anti-gloss feature clause,
    and contains NO glamour/gloss tokens.
  * build_t2i_workflow — ALWAYS the natural photo-style wrapper (ignores any
    character/controls photo_style), resolution left untouched (no downscale),
    hires refine pass on per GENERATION_HIRES_DEFAULT.
  * build_faceswap_workflow — ReActor sources the ORIGINAL hero face onto the
    GENERATED base, with the gentle restore params mirrored from pose node 200,
    a settings-driven restore model (NUDE_BASE_FACE_RESTORE_MODEL), and an
    optional ReActorFaceBoost pass (NUDE_BASE_FACE_BOOST).
  * NudeBaseWorker._process_job — settings.NUDE_BASE_FACE_SWAP gates the ReActor
    step entirely: OFF (default) submits ONLY the t2i workflow and persists its
    output verbatim; True submits the t2i workflow THEN the faceswap workflow
    (GPEN/FaceBoost params intact) and persists the swapped output.
  * POST /nude-base builds a `nude_base` job carrying the persona + hero URL +
    deterministic seed (flag True), and the LEGACY pipeline_edit job (flag False).

Runs under pytest or directly: python loli_api/tests/test_nude_base_t2i.py
"""
import asyncio
import base64
import json
import zlib
from pathlib import Path
from types import SimpleNamespace

# Endpoint + legacy request build SSRF-validate source_image; these tests exercise
# feature logic, not the allowlist, so make the validator a passthrough.
import models.requests as _mr
_mr.validate_source_image = lambda u: u  # type: ignore

from config import settings
from models.enums import JobStatus, NudityLevel, OutfitType, PhotoStyleType
from models.requests import PersonaOptions, NudeBaseGenerateRequest
from services import prompt_constants as pc
from services.job_manager import JobManager
from services.prompt_generator import locked_tokens
import workers.nude_base_worker as nbw
from workers.nude_base_worker import (
    NudeBaseWorker,
    stable_nude_base_seed,
    build_nude_base_prompt,
    build_t2i_workflow,
    build_faceswap_workflow,
    NEUTRAL_POSE_TEXT,
    PLAIN_BACKDROP_TEXT,
    ANTI_GLOSS_POSITIVE,
    NEUTRAL_BASE_OUTFIT_CLAUSE,
    BODY_AESTHETIC_CLAUSES,
    REACTOR_CODEFORMER_WEIGHT,
    REACTOR_FACE_RESTORE_VISIBILITY,
    REACTOR_FACE_RESTORE_MODEL,
)
from api.v1.endpoints import nude_base as ep
from api.v1.endpoints import pipeline as pipeline_ep

_T2I_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "workflows" / "amazing-z-photo_API_Create_CHAR.json"
)

_GLAMOUR_BANNED = ("glamour", "editorial", "retouched", "glossy", "airbrushed", "soft focus")


def _persona():
    return PersonaOptions(
        ethnicity="japanese", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Stella",
        occupation="nurse",
    )


# ---------------------------------------------------------------------------
# Deterministic seed
# ---------------------------------------------------------------------------
def test_seed_is_deterministic_crc32_per_character():
    assert stable_nude_base_seed("c1") == stable_nude_base_seed("c1")   # stable
    assert stable_nude_base_seed("c1") == zlib.crc32(b"c1")             # crc32, not hash()
    assert stable_nude_base_seed("c1") != stable_nude_base_seed("c2")   # per-character
    assert isinstance(stable_nude_base_seed("abc"), int)


# ---------------------------------------------------------------------------
# Base prompt assembly
# ---------------------------------------------------------------------------
def test_base_prompt_carries_identity_naked_pose_backdrop_natural_no_glamour():
    persona = _persona()
    positive, negative, locked = build_nude_base_prompt(persona)
    low = positive.lower()

    # Full locked identity block — EVERY persona feature (age bucket, ethnicity/skin
    # phrase, hair style+color, eye color, body type, breast size) reaches the base.
    for tok in locked_tokens(persona):
        assert tok.lower() in low, f"identity token missing from base prompt: {tok!r}"
    assert locked and locked.lower() in low

    # Neutral reference-body clause REPLACES the arousal-styled NAKED/HIGH tier prose
    # (the WS-N base is a calm reference every scene later dresses over, not an arousal
    # scene): 'nude' + neutral wording present, HIGH-tier arousal tokens ABSENT.
    assert "completely nude" in low
    assert NEUTRAL_BASE_OUTFIT_CLAUSE in positive
    assert "neutral reference posture" in low
    for tok in ("aroused", "hard nipples", "swollen"):
        assert tok not in low, f"arousal token leaked into base prompt: {tok!r}"

    # Neutral standing full-body pose + plain studio backdrop constants, verbatim.
    assert NEUTRAL_POSE_TEXT in positive
    assert PLAIN_BACKDROP_TEXT in positive

    # Char-gen quality tail + the WS-N anti-gloss / max-feature clause.
    assert "highly detailed, natural skin texture" in positive
    assert ANTI_GLOSS_POSITIVE in positive
    assert "matte natural skin" in low and "visible pores" in low and "sharp focus" in low

    # Body-aesthetic clause (nude base v2): _persona() is bodyType="curvy", so her
    # own graceful/model-like framing clause reaches the base, inserted between the
    # quality tail and the anti-gloss clause.
    assert BODY_AESTHETIC_CLAUSES["curvy"] in positive

    # NO glamour/gloss tokens anywhere in the assembled POSITIVE.
    for banned in _GLAMOUR_BANNED:
        assert banned not in low, f"banned glamour/gloss token in base prompt: {banned!r}"

    # Extend the banned-vocab check to EVERY BODY_AESTHETIC_CLAUSES entry (not just
    # the one this persona happens to draw) so a future edit to any of the 5 clauses
    # can't quietly reintroduce a glamour/gloss token. curvy/bbw additionally must
    # never carry slimming vocabulary — that would fight the admin's explicit
    # body-type choice instead of gracefully framing it.
    for body_type, clause in BODY_AESTHETIC_CLAUSES.items():
        clause_low = clause.lower()
        for banned in _GLAMOUR_BANNED:
            assert banned not in clause_low, (
                f"banned glamour/gloss token in {body_type!r} body clause: {banned!r}"
            )
        if body_type in ("curvy", "bbw"):
            for slim_word in ("slim", "slender", "petite", "skinny"):
                assert slim_word not in clause_low, (
                    f"slimming vocab leaked into {body_type!r} body clause: {slim_word!r}"
                )

    # The gloss-suppression wording lives in the NEGATIVE instead (never the positive).
    neg_low = negative.lower()
    assert "airbrushed" in neg_low and "retouched" in neg_low


def test_base_prompt_is_deterministic():
    a = build_nude_base_prompt(_persona())
    b = build_nude_base_prompt(_persona())
    assert a == b  # no variety seed, no pool draw -> byte-identical every call


# ---------------------------------------------------------------------------
# Body-aesthetic clause (nude base v2) — keyed by BodyType enum value, appended
# right before ANTI_GLOSS_POSITIVE. Covers a slim and a curvy persona explicitly
# (opposite ends of the pool) plus the clean-skip path for an unrecognized value.
# ---------------------------------------------------------------------------
def _persona_with_body(body_type) -> PersonaOptions:
    """A persona whose bodyType is forced post-construction — Pydantic only
    validates BodyType membership at construction time (validate_assignment is
    not enabled on PersonaOptions), so this is the standard way to exercise an
    unrecognized value without fighting the enum field."""
    persona = _persona()
    persona.bodyType = body_type
    return persona


def test_base_prompt_carries_body_clause_for_skinny_persona():
    positive, _negative, _locked = build_nude_base_prompt(_persona_with_body("skinny"))
    assert BODY_AESTHETIC_CLAUSES["skinny"] in positive
    # Sits between the quality tail and the anti-gloss clause, as assembled.
    assert positive.index(BODY_AESTHETIC_CLAUSES["skinny"]) < positive.index(ANTI_GLOSS_POSITIVE)
    # No other body type's clause leaks in.
    for body_type, clause in BODY_AESTHETIC_CLAUSES.items():
        if body_type != "skinny":
            assert clause not in positive, f"unexpected {body_type!r} clause in skinny prompt"


def test_base_prompt_carries_body_clause_for_curvy_persona():
    positive, _negative, _locked = build_nude_base_prompt(_persona_with_body("curvy"))
    assert BODY_AESTHETIC_CLAUSES["curvy"] in positive
    assert positive.index(BODY_AESTHETIC_CLAUSES["curvy"]) < positive.index(ANTI_GLOSS_POSITIVE)
    for body_type, clause in BODY_AESTHETIC_CLAUSES.items():
        if body_type != "curvy":
            assert clause not in positive, f"unexpected {body_type!r} clause in curvy prompt"


def test_base_prompt_skips_body_clause_cleanly_for_unknown_body_type():
    persona = _persona_with_body("not_a_real_body_type")
    positive, _negative, _locked = build_nude_base_prompt(persona)
    # None of the known clauses appear ...
    for body_type, clause in BODY_AESTHETIC_CLAUSES.items():
        assert clause not in positive, f"unexpected {body_type!r} clause for an unknown body type"
    # ... and the skip left no dangling separator artifact.
    assert ", ," not in positive
    assert ANTI_GLOSS_POSITIVE in positive  # the rest of the assembly is unaffected


# ---------------------------------------------------------------------------
# t2i workflow build
# ---------------------------------------------------------------------------
def test_t2i_workflow_natural_style_untouched_resolution_hires():
    template = json.loads(_T2I_TEMPLATE_PATH.read_text())
    seed = 424242
    wf = build_t2i_workflow(template, _persona(), seed)

    # Node 110 carries the assembled base positive verbatim.
    positive, _neg, _lk = build_nude_base_prompt(_persona())
    assert wf["110"]["inputs"]["value"] == positive

    # Node 125 is the NATURAL wrapper regardless of any character/controls photo_style
    # (the base render is ALWAYS natural) — never the polished/studio glamour wrappers.
    assert wf["125"]["inputs"]["value"] == pc.photo_style_template(PhotoStyleType.NATURAL.value, None)
    assert wf["125"]["inputs"]["value"] != pc.photo_style_template("polished", None)
    assert wf["125"]["inputs"]["value"] != pc.photo_style_template("studio", None)

    # Resolution left UNTOUCHED (no downscale) — dims match the template exactly.
    assert wf["243"]["inputs"]["value"] == template["243"]["inputs"]["value"]
    assert wf["248"]["inputs"]["value"] == template["248"]["inputs"]["value"]

    # Deterministic sampler seed.
    assert wf["67"]["inputs"]["noise_seed"] == seed

    # Hires refine pass follows GENERATION_HIRES_DEFAULT (texture detail).
    if settings.GENERATION_HIRES_DEFAULT:
        assert wf["207"]["inputs"]["any_01"] == ["300", 0]


# ---------------------------------------------------------------------------
# Face-swap workflow wiring
# ---------------------------------------------------------------------------
def test_faceswap_sources_hero_onto_generated_base():
    # Pin the settings this test asserts against explicitly, rather than relying
    # on ambient defaults, so it can't flake if another test's override leaks.
    # build_faceswap_workflow() itself is unconditional (NUDE_BASE_FACE_SWAP only
    # gates whether NudeBaseWorker._process_job calls it — see the run-flow tests
    # below); pinning it True here just documents that this test describes the
    # graph the "swap enabled" path submits.
    prev_swap = settings.NUDE_BASE_FACE_SWAP
    prev_model = settings.NUDE_BASE_FACE_RESTORE_MODEL
    settings.NUDE_BASE_FACE_SWAP = True
    settings.NUDE_BASE_FACE_RESTORE_MODEL = "GPEN-BFR-512.onnx"
    try:
        wf = build_faceswap_workflow("BASE_generated.png", "HERO_original.png")

        reactor_items = [(nid, n) for nid, n in wf.items() if n["class_type"] == "ReActorFaceSwap"]
        assert len(reactor_items) == 1
        reactor_id, reactor = reactor_items[0]
        r = reactor["inputs"]

        # input_image = the GENERATED base (the body the face is stamped ONTO).
        base_node = r["input_image"][0]
        assert wf[base_node]["class_type"] == "LoadImage"
        assert wf[base_node]["inputs"]["image"] == "BASE_generated.png"

        # source_image = the ORIGINAL hero (the face DONOR / identity source) — never a
        # generated or intermediate image.
        hero_node = r["source_image"][0]
        assert wf[hero_node]["class_type"] == "LoadImage"
        assert wf[hero_node]["inputs"]["image"] == "HERO_original.png"
        assert base_node != hero_node

        # Fidelity-favoring restore params mirror the pose graphs' node 200 exactly
        # (FACE-DIAL fix: HIGH codeformer_weight keeps the swapped face's real texture,
        # moderate visibility keeps raw-swap detail in the blend).
        assert r["codeformer_weight"] == REACTOR_CODEFORMER_WEIGHT == 0.7
        assert r["face_restore_visibility"] == REACTOR_FACE_RESTORE_VISIBILITY == 0.65
        assert r["swap_model"] == "inswapper_128.onnx"
        assert r["facedetection"] == "retinaface_resnet50"
        # DELIBERATE CHANGE: face_restore_model is now settings-driven
        # (NUDE_BASE_FACE_RESTORE_MODEL) instead of the baked codeformer constant —
        # this used to assert the literal "codeformer-v0.1.0.pth". The baked
        # REACTOR_FACE_RESTORE_MODEL constant is now only the empty-string fallback;
        # see the dedicated restore-model / boost tests below for that coverage.
        assert r["face_restore_model"] == "GPEN-BFR-512.onnx"
        assert r["enabled"] is True

        # Exactly one SaveImage, consuming the ReActor output (no extra restore/upscale
        # BESIDES the optional FaceBoost pass, which is covered separately below).
        save_items = [n for n in wf.values() if n["class_type"] == "SaveImage"]
        assert len(save_items) == 1
        assert save_items[0]["inputs"]["images"][0] == reactor_id
    finally:
        settings.NUDE_BASE_FACE_SWAP = prev_swap
        settings.NUDE_BASE_FACE_RESTORE_MODEL = prev_model


# ---------------------------------------------------------------------------
# Face restore model — settings-driven (NUDE_BASE_FACE_RESTORE_MODEL), applied to
# BOTH the main ReActorFaceSwap node and (when enabled) the ReActorFaceBoost node.
# ---------------------------------------------------------------------------
def test_faceswap_restore_model_empty_setting_keeps_baked_codeformer_fallback():
    prev_swap = settings.NUDE_BASE_FACE_SWAP
    prev = settings.NUDE_BASE_FACE_RESTORE_MODEL
    settings.NUDE_BASE_FACE_SWAP = True  # documents the "swap enabled" scenario
    settings.NUDE_BASE_FACE_RESTORE_MODEL = ""
    try:
        wf = build_faceswap_workflow("BASE_generated.png", "HERO_original.png")
        assert wf["12"]["inputs"]["face_restore_model"] == REACTOR_FACE_RESTORE_MODEL
        assert REACTOR_FACE_RESTORE_MODEL == "codeformer-v0.1.0.pth"
    finally:
        settings.NUDE_BASE_FACE_SWAP = prev_swap
        settings.NUDE_BASE_FACE_RESTORE_MODEL = prev


def test_faceswap_restore_model_gpen_applied_to_main_and_boost_nodes():
    prev_swap = settings.NUDE_BASE_FACE_SWAP
    prev_model = settings.NUDE_BASE_FACE_RESTORE_MODEL
    prev_boost = settings.NUDE_BASE_FACE_BOOST
    settings.NUDE_BASE_FACE_SWAP = True  # documents the "swap enabled" scenario
    settings.NUDE_BASE_FACE_RESTORE_MODEL = "GPEN-BFR-512.onnx"
    settings.NUDE_BASE_FACE_BOOST = True
    try:
        wf = build_faceswap_workflow("BASE_generated.png", "HERO_original.png")
        assert wf["12"]["inputs"]["face_restore_model"] == "GPEN-BFR-512.onnx"
        boost_items = [n for n in wf.values() if n["class_type"] == "ReActorFaceBoost"]
        assert len(boost_items) == 1
        assert boost_items[0]["inputs"]["boost_model"] == "GPEN-BFR-512.onnx"
    finally:
        settings.NUDE_BASE_FACE_SWAP = prev_swap
        settings.NUDE_BASE_FACE_RESTORE_MODEL = prev_model
        settings.NUDE_BASE_FACE_BOOST = prev_boost


# ---------------------------------------------------------------------------
# ReActorFaceBoost — settings-gated (NUDE_BASE_FACE_BOOST), restores + upscales the
# swapped face BEFORE it is pasted back onto the base.
# ---------------------------------------------------------------------------
def test_faceswap_boost_on_by_default_node_present_with_exact_params_and_wired():
    prev_swap = settings.NUDE_BASE_FACE_SWAP
    prev_boost = settings.NUDE_BASE_FACE_BOOST
    prev_model = settings.NUDE_BASE_FACE_RESTORE_MODEL
    settings.NUDE_BASE_FACE_SWAP = True  # documents the "swap enabled" scenario
    settings.NUDE_BASE_FACE_BOOST = True
    settings.NUDE_BASE_FACE_RESTORE_MODEL = "GPEN-BFR-512.onnx"
    try:
        wf = build_faceswap_workflow("BASE_generated.png", "HERO_original.png")

        boost_node_items = [(nid, n) for nid, n in wf.items() if n["class_type"] == "ReActorFaceBoost"]
        assert len(boost_node_items) == 1
        boost_id, boost_node = boost_node_items[0]

        # Exact params, per spec: enabled, boost_model mirrors the main node's
        # restore model, Bicubic interpolation, visibility 1.0, codeformer_weight
        # 0.5, restore_with_main_after False (the boost's own restore is final).
        assert boost_node["inputs"] == {
            "enabled": True,
            "boost_model": "GPEN-BFR-512.onnx",
            "interpolation": "Bicubic",
            "visibility": 1.0,
            "codeformer_weight": 0.5,
            "restore_with_main_after": False,
        }

        # Wired into the main ReActorFaceSwap node's face_boost input.
        assert wf["12"]["class_type"] == "ReActorFaceSwap"
        assert wf["12"]["inputs"]["face_boost"] == [boost_id, 0]
    finally:
        settings.NUDE_BASE_FACE_SWAP = prev_swap
        settings.NUDE_BASE_FACE_BOOST = prev_boost
        settings.NUDE_BASE_FACE_RESTORE_MODEL = prev_model


def test_faceswap_boost_disabled_omits_node_graph_otherwise_unchanged():
    prev_swap = settings.NUDE_BASE_FACE_SWAP
    prev_boost = settings.NUDE_BASE_FACE_BOOST
    settings.NUDE_BASE_FACE_SWAP = True  # documents the "swap enabled" scenario
    settings.NUDE_BASE_FACE_BOOST = False
    try:
        wf = build_faceswap_workflow("BASE_generated.png", "HERO_original.png")

        # No boost node, no face_boost key on the main node.
        assert not any(n["class_type"] == "ReActorFaceBoost" for n in wf.values())
        assert "face_boost" not in wf["12"]["inputs"]

        # Graph is byte-identical (aside from the restore-model setting) to the
        # pre-boost shape: exactly the original 4 node ids, nothing extra.
        assert set(wf.keys()) == {"10", "11", "12", "13"}
    finally:
        settings.NUDE_BASE_FACE_SWAP = prev_swap
        settings.NUDE_BASE_FACE_BOOST = prev_boost


# ---------------------------------------------------------------------------
# Worker run-flow — settings.NUDE_BASE_FACE_SWAP gates whether
# NudeBaseWorker._process_job submits the second (ReActor) workflow at all.
# OFF (default): exactly one workflow (the t2i base) is submitted, and its own
# output is what gets persisted — no hero download, no second submit_and_poll.
# ON: the legacy two-workflow chain runs, and the FACE-SWAPPED output (not the
# raw t2i base) is what gets persisted. Drives the real JobManager (mirrors
# test_video_endpoint_routing.py's convention) through the same
# create_job -> get_next_nude_base_job -> get_job sequence _worker_loop uses,
# then calls _process_job directly so status/queue bookkeeping (mark_nude_base_done
# via task_done()) is exercised exactly like production.
# ---------------------------------------------------------------------------
class _FakeRunPodClient:
    """
    Records every submitted workflow (+ its staged images) and completes each
    immediately with a distinct, ORDERED fake payload, so a test can tell which
    submission's output ended up persisted. Mirrors RunPodServerlessClient's
    async submit()/status() contract closely enough for runpod_runner.run_workflow
    to drive to completion on the first poll (no real HTTP, no real sleep).
    """

    def __init__(self, outputs):
        self.submitted = []  # [{"workflow": dict, "images": list|None}, ...], submit order
        self._outputs = list(outputs)

    async def submit(self, workflow, images=None, webhook_url=None,
                      execution_timeout_ms=None, ttl_ms=None):
        self.submitted.append({"workflow": workflow, "images": images})
        return f"rp_{len(self.submitted)}"

    async def status(self, runpod_id: str) -> dict:
        idx = int(runpod_id.rsplit("_", 1)[1]) - 1
        b64 = base64.b64encode(self._outputs[idx]).decode("ascii")
        return {
            "status": "COMPLETED",
            "output": {"images": [{"filename": "out.png", "type": "base64", "data": b64}]},
        }


class _FakeStorage:
    """
    Mirrors StorageService.save_image / generate_signed_url (the non-Supabase
    persist branch _process_job takes when supabase_storage_service=None) just
    enough to record which bytes were persisted, without touching the filesystem
    or requiring real PNG bytes (StorageService.save_image round-trips through PIL).
    """

    def __init__(self):
        self.saved = []  # [(image_bytes, job_id), ...]

    def save_image(self, image_data, job_id, format="PNG"):
        self.saved.append((image_data, job_id))
        return f"nude_bases/{job_id}.png", f"hash-{job_id}"

    def generate_signed_url(self, relative_path, expiry_minutes=None):
        return f"https://example.local/{relative_path}", None


def _nude_base_request(character_id="c1"):
    return NudeBaseGenerateRequest(
        persona=_persona(),
        hero_image_url="https://x.supabase.co/hero.png",
        character_id=character_id,
        seed=stable_nude_base_seed(character_id),
    )


async def _run_nude_base_job(runpod_client, storage):
    """
    Build a real JobManager + NudeBaseWorker, enqueue one nude_base job exactly
    as the endpoint does (create_job), pop it exactly as _worker_loop does
    (get_next_nude_base_job -> get_job), then run _process_job directly. Returns
    the job's final state.
    """
    job_manager = JobManager()
    worker = NudeBaseWorker(
        job_manager=job_manager,
        comfyui_client=None,
        storage_service=storage,
        workflow_path=str(_T2I_TEMPLATE_PATH),
        supabase_storage_service=None,
        runpod_client=runpod_client,
    )
    worker._t2i_template = json.loads(_T2I_TEMPLATE_PATH.read_text())

    created = await job_manager.create_job(_nude_base_request(), user_id="admin-1", job_type="nude_base")
    job_id = await job_manager.get_next_nude_base_job()
    assert job_id == created.job_id
    job = await job_manager.get_job(job_id)

    await worker._process_job(job)

    return await job_manager.get_job(job_id)


def test_process_job_face_swap_off_by_default_submits_only_t2i_workflow():
    prev = settings.NUDE_BASE_FACE_SWAP
    settings.NUDE_BASE_FACE_SWAP = False
    try:
        t2i_bytes = b"T2I_BASE_BYTES"
        runpod = _FakeRunPodClient(outputs=[t2i_bytes])
        storage = _FakeStorage()

        job = asyncio.run(_run_nude_base_job(runpod, storage))

        # Exactly ONE workflow submitted (the t2i base) — no faceswap round-trip.
        assert len(runpod.submitted) == 1
        wf = runpod.submitted[0]["workflow"]
        assert runpod.submitted[0]["images"] is None      # pure t2i: no input images staged
        assert not any(n.get("class_type") == "ReActorFaceSwap" for n in wf.values())
        assert "110" in wf and "125" in wf                # t2i graph node ids present

        # The t2i output IS the persisted final image — no second, swapped bytes.
        assert len(storage.saved) == 1
        saved_bytes, saved_job_id = storage.saved[0]
        assert saved_bytes == t2i_bytes
        assert saved_job_id == job.job_id

        assert job.status == JobStatus.SUCCEEDED
        assert job.preview_url == f"https://example.local/nude_bases/{job.job_id}.png"
        assert job.image_hash == f"hash-{job.job_id}"
    finally:
        settings.NUDE_BASE_FACE_SWAP = prev


def test_process_job_face_swap_on_submits_t2i_then_faceswap_workflow():
    prev_swap = settings.NUDE_BASE_FACE_SWAP
    prev_model = settings.NUDE_BASE_FACE_RESTORE_MODEL
    prev_boost = settings.NUDE_BASE_FACE_BOOST
    settings.NUDE_BASE_FACE_SWAP = True
    settings.NUDE_BASE_FACE_RESTORE_MODEL = "GPEN-BFR-512.onnx"
    settings.NUDE_BASE_FACE_BOOST = True
    # _process_job downloads the hero photo unconditionally in this branch; stub
    # the module-level helper so the test makes no real network call (mirrors how
    # the other tests in this file pin settings.* directly rather than using a
    # pytest fixture — this file's tests run standalone via __main__ too).
    prev_download = nbw._download_image
    nbw._download_image = lambda url, timeout=30: b"HERO_BYTES"
    try:
        t2i_bytes = b"T2I_BASE_BYTES"
        swapped_bytes = b"FACESWAPPED_BYTES"
        runpod = _FakeRunPodClient(outputs=[t2i_bytes, swapped_bytes])
        storage = _FakeStorage()

        job = asyncio.run(_run_nude_base_job(runpod, storage))

        # TWO workflows submitted, in order: the t2i base, then the ReActor face-swap.
        assert len(runpod.submitted) == 2
        t2i_wf = runpod.submitted[0]["workflow"]
        assert runpod.submitted[0]["images"] is None
        assert not any(n.get("class_type") == "ReActorFaceSwap" for n in t2i_wf.values())

        swap_wf = runpod.submitted[1]["workflow"]
        reactor_nodes = [n for n in swap_wf.values() if n.get("class_type") == "ReActorFaceSwap"]
        assert len(reactor_nodes) == 1
        reactor = reactor_nodes[0]["inputs"]
        # Exact GPEN/FaceBoost params — same contract test_faceswap_* assert above.
        assert reactor["face_restore_model"] == "GPEN-BFR-512.onnx"
        assert reactor["codeformer_weight"] == REACTOR_CODEFORMER_WEIGHT == 0.7
        assert reactor["face_restore_visibility"] == REACTOR_FACE_RESTORE_VISIBILITY == 0.65
        assert any(n.get("class_type") == "ReActorFaceBoost" for n in swap_wf.values())
        # Two staged input images (base + hero) shipped alongside the swap submit.
        staged_names = {img["name"] for img in runpod.submitted[1]["images"]}
        assert len(staged_names) == 2

        # The FACE-SWAPPED bytes (not the raw t2i base) are what gets persisted.
        assert len(storage.saved) == 1
        saved_bytes, saved_job_id = storage.saved[0]
        assert saved_bytes == swapped_bytes
        assert saved_job_id == job.job_id

        assert job.status == JobStatus.SUCCEEDED
    finally:
        settings.NUDE_BASE_FACE_SWAP = prev_swap
        settings.NUDE_BASE_FACE_RESTORE_MODEL = prev_model
        settings.NUDE_BASE_FACE_BOOST = prev_boost
        nbw._download_image = prev_download


# ---------------------------------------------------------------------------
# Endpoint fakes
# ---------------------------------------------------------------------------
def _character(hero="https://x.supabase.co/hero.png"):
    return SimpleNamespace(id="c1", persona=_persona(), hero_image_url=hero)


class _FakeJobManager:
    def __init__(self, job=None):
        self.created = []
        self._job = job

    def is_queue_full(self, job_type="text_to_image"):
        return False

    async def create_job(self, request, user_id, job_type="text_to_image"):
        job = SimpleNamespace(job_id=f"{job_type}_new", request=request, user_id=user_id)
        self.created.append((request, user_id, job_type))
        return job

    async def get_job(self, job_id):
        return self._job


class _FakeCharStore:
    def __init__(self, character):
        self.character = character

    async def get(self, cid):
        return self.character


class _FakeNudeStore:
    def __init__(self, latest=None):
        self._latest = latest
        self.created = []

    async def get_latest(self, character_id):
        return self._latest

    async def create(self, character_id, *, job_id, source_image_url=None):
        self.created.append(
            {"character_id": character_id, "job_id": job_id, "source_image_url": source_image_url}
        )
        now = "2026-07-13T00:00:00Z"
        from models.nude_base import NudeBaseRead
        return NudeBaseRead(
            id="nb1", character_id=character_id, source_image_url=source_image_url,
            image_url=None, image_hash=None, job_id=job_id, status="pending",
            error=None, created_at=now, updated_at=now,
        )


def _wire(job_manager, char_store, nude_store):
    ep.set_job_manager(job_manager)
    ep.set_character_store(char_store)
    ep.set_nude_base_store(nude_store)


# ---------------------------------------------------------------------------
# POST /nude-base — NEW t2i path (flag True) and LEGACY path (flag False)
# ---------------------------------------------------------------------------
def test_post_t2i_builds_nude_base_job_with_persona_hero_and_seed():
    prev = settings.NUDE_BASE_T2I
    settings.NUDE_BASE_T2I = True
    try:
        jm = _FakeJobManager()
        nude = _FakeNudeStore(latest=None)  # nothing pending -> fresh generation
        _wire(jm, _FakeCharStore(_character()), nude)

        resp = asyncio.run(ep.generate_nude_base("c1", user={"sub": "admin-1"}))

        assert len(jm.created) == 1
        request, user_id, job_type = jm.created[0]
        assert job_type == "nude_base"
        assert isinstance(request, NudeBaseGenerateRequest)
        # The ReActor source is the ORIGINAL hero URL; the base carries the persona;
        # the seed is the deterministic per-character crc32.
        assert request.hero_image_url == "https://x.supabase.co/hero.png"
        assert request.character_id == "c1"
        assert request.seed == zlib.crc32(b"c1")
        assert request.persona.name == "Stella"

        # A pending base row was recorded against that job.
        assert nude.created == [{
            "character_id": "c1", "job_id": "nude_base_new",
            "source_image_url": "https://x.supabase.co/hero.png",
        }]
        assert resp.status == "pending"
        assert resp.jobId == "nude_base_new"
        assert resp.imageUrl is None
    finally:
        settings.NUDE_BASE_T2I = prev


def test_post_legacy_builds_pipeline_edit_job_when_flag_false():
    prev = settings.NUDE_BASE_T2I
    settings.NUDE_BASE_T2I = False
    try:
        jm = _FakeJobManager()
        nude = _FakeNudeStore(latest=None)
        pipeline_ep.set_job_manager(jm)
        pipeline_ep.set_notification_service(None)
        _wire(jm, _FakeCharStore(_character()), nude)

        resp = asyncio.run(ep.generate_nude_base("c1", user={"sub": "admin-1"}))

        assert len(jm.created) == 1
        request, user_id, job_type = jm.created[0]
        assert job_type == "pipeline_edit"          # unchanged legacy edit-based path
        assert request.outfit == OutfitType.NAKED
        assert request.nudityLevel == NudityLevel.HIGH
        assert request.outfitPromptMode == "nude_base"
        assert request.source_image == "https://x.supabase.co/hero.png"
        assert resp.status == "pending"
    finally:
        settings.NUDE_BASE_T2I = prev


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
