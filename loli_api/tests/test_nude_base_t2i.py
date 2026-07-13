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
    GENERATED base, with the gentle restore params mirrored from pose node 200.
  * POST /nude-base builds a `nude_base` job carrying the persona + hero URL +
    deterministic seed (flag True), and the LEGACY pipeline_edit job (flag False).

Runs under pytest or directly: python loli_api/tests/test_nude_base_t2i.py
"""
import asyncio
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
from services.prompt_generator import locked_tokens
from workers.nude_base_worker import (
    stable_nude_base_seed,
    build_nude_base_prompt,
    build_t2i_workflow,
    build_faceswap_workflow,
    NEUTRAL_POSE_TEXT,
    PLAIN_BACKDROP_TEXT,
    ANTI_GLOSS_POSITIVE,
    NEUTRAL_BASE_OUTFIT_CLAUSE,
    REACTOR_CODEFORMER_WEIGHT,
    REACTOR_FACE_RESTORE_VISIBILITY,
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

    # NO glamour/gloss tokens anywhere in the assembled POSITIVE.
    for banned in _GLAMOUR_BANNED:
        assert banned not in low, f"banned glamour/gloss token in base prompt: {banned!r}"

    # The gloss-suppression wording lives in the NEGATIVE instead (never the positive).
    neg_low = negative.lower()
    assert "airbrushed" in neg_low and "retouched" in neg_low


def test_base_prompt_is_deterministic():
    a = build_nude_base_prompt(_persona())
    b = build_nude_base_prompt(_persona())
    assert a == b  # no variety seed, no pool draw -> byte-identical every call


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

    # Gentle restore params mirror the pose graphs' node 200 exactly.
    assert r["codeformer_weight"] == REACTOR_CODEFORMER_WEIGHT == 0.25
    assert r["face_restore_visibility"] == REACTOR_FACE_RESTORE_VISIBILITY == 0.8
    assert r["swap_model"] == "inswapper_128.onnx"
    assert r["facedetection"] == "retinaface_resnet50"
    assert r["face_restore_model"] == "codeformer-v0.1.0.pth"
    assert r["enabled"] is True

    # Exactly one SaveImage, consuming the ReActor output (no extra restore/upscale).
    save_items = [n for n in wf.values() if n["class_type"] == "SaveImage"]
    assert len(save_items) == 1
    assert save_items[0]["inputs"]["images"][0] == reactor_id


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
