"""
Nude-base worker (WS-N) — text-to-image base (+ optional ReActor face lock).

Replaces the old edit-based undressing (outfit step in "nude_base" prompt mode +
background step on the clothed hero) with a deterministic, pose-independent,
mask-free path. One ``nude_base`` job runs a TEXT-TO-IMAGE BASE step and an
OPTIONAL second chained GPU step:

  1. TEXT-TO-IMAGE BASE — generated exactly like char-gen (Z-Image Turbo,
     ``COMFYUI_WORKFLOW_PATH``, ``assemble_generation_prompt``) from the
     character's locked identity block, a FORCED ``OutfitType.NAKED`` clause, a
     constant neutral standing full-body pose, a constant plain studio backdrop,
     and the NATURAL photo style — at a deterministic per-character seed
     (``zlib.crc32`` of the character id). This produces the SAME body geometry
     every time with the correct skin tone from the persona, so an unusual hero
     crop (kneeling in a kitchen, a tight portrait, …) can no longer make the
     model paint a whole second person into a mask — the root cause of the old
     two-headed composite.

  2. FACE LOCK (optional, OFF by default — ``settings.NUDE_BASE_FACE_SWAP``) — a
     single ReActor face pass swaps the ORIGINAL hero photo's face onto that
     generated base (source = the hero URL, NEVER a generated or intermediate
     image; node params mirror the pose graphs' node 200 exactly). Product
     decision: the base's own face never reaches a published photo — every batch
     photo's face is stamped from the HERO at the pose step — so locking the
     base's face is wasted GPU work and a confusing hero-vs-base identity
     mismatch in admin. With the flag off, the t2i output from step 1 IS the
     final base image and this step is skipped entirely (no hero download, no
     second workflow submit). The flag stays for rollback to the old
     face-locked bases.

The job finalizes exactly like every other worker (sets ``job.preview_url`` +
``job.image_hash`` on success) regardless of which branch produced the final
bytes, so the nude-base store / status reconcile-on-read flow in
``api/v1/endpoints/nude_base.py`` is unchanged. The legacy edit-based path stays
intact behind ``settings.NUDE_BASE_T2I=False``.
"""
import asyncio
import base64
import logging
import traceback
import uuid
import zlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests as http_requests

from config import settings
from services.job_manager import JobManager, Job
from services.comfyui_client import ComfyUIClient
from services.runpod_client import RunPodServerlessClient
from services import runpod_runner
from services import attribute_phrases as ap
from services.prompt_generator import assemble_generation_prompt
from services.outfit_vocab import generation_outfit_clause
from services.storage_service import StorageService
from services.supabase_storage_service import SupabaseStorageService
from services.notification_service import NotificationService
from models.enums import JobStatus, NudityLevel, OutfitType, PhotoStyleType, ShotFramingType
from models.requests import ShotOptions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constant framing for the base render (deterministic — no pools, no variety).
# ---------------------------------------------------------------------------
# A calm, camera-facing, whole-body standing reference so the base has clean,
# unambiguous anatomy every batch scene can dress additively over. Passed as the
# verbatim body-position phrase (``pose_text``) into assemble_generation_prompt.
NEUTRAL_POSE_TEXT = (
    "standing straight facing the camera, arms relaxed at her sides, "
    "full body visible head to toe"
)
# A plain, seamless studio backdrop so the internal asset carries no location,
# props, or passersby into scenes built from it. Passed as the verbatim scene
# clause (``free_text``) into assemble_generation_prompt.
PLAIN_BACKDROP_TEXT = (
    "plain seamless light grey studio backdrop, soft even studio lighting, "
    "empty background with no furniture, props, or other people"
)
# Explicit anti-gloss / max-feature clause appended to the POSITIVE (WS-N quality
# bar: "save as much features as possible — no glossing, no blurring"). Kept free
# of the banned finish words (glamour/editorial/retouched/glossy/airbrushed/soft
# focus) so it reinforces real matte skin without smuggling a glamour token into
# the assembled prompt; the suppression wording lives in the negative below.
ANTI_GLOSS_POSITIVE = (
    "matte natural skin with visible pores and fine skin texture, "
    "sharp focus across the whole body, no shine"
)
# Suppression tokens for the NEGATIVE (belt-and-suspenders — inert at cfg=1 on the
# gen graph, kept for provenance/parity). These DO name the gloss words on purpose;
# they never appear in the positive, so the "no glamour in the assembled prompt"
# contract holds.
ANTI_GLOSS_NEGATIVE = (
    "airbrushed skin, retouched, glossy plastic skin, oily shine, "
    "soft focus, blurry, waxy doll skin"
)
# Neutral reference-body clause. The shared NAKED/HIGH outfit clause is arousal-styled
# ("hard nipples, swollen aroused pussy lips…") — wrong for a CALM base that every
# downstream batch scene later dresses over. build_nude_base_prompt swaps that clause
# out for this one AFTER assembly, so outfit_vocab / prompt_generator are left untouched
# (the swap is local to the base render). Keep it free of arousal tokens.
NEUTRAL_BASE_OUTFIT_CLAUSE = (
    "completely nude, bare natural relaxed body, neutral reference posture, no arousal"
)
# Body-aesthetic clause (nude base v2), keyed by BodyType enum VALUES
# (models/enums.py). A graceful, model-like framing of the persona's OWN body
# type — never a slimming rewrite of it: curvy/bbw deliberately carry NO
# slimming vocabulary (that would fight the admin's explicit body-type choice),
# and none of the five carry gloss vocabulary (matte doctrine — see
# ANTI_GLOSS_POSITIVE/NEGATIVE above). build_nude_base_prompt looks a persona's
# body type up here and appends whatever comes back (empty string for an
# unknown/missing body type is a clean skip, never a stray comma).
BODY_AESTHETIC_CLAUSES: Dict[str, str] = {
    "skinny": "gracefully slim with elegant model-like proportions and poised posture",
    "athletic": "gracefully toned, athletic model-like physique with poised posture",
    "average": "naturally balanced proportions with a graceful model-like posture",
    "curvy": "gracefully curvy hourglass proportions carried with model-like poise",
    "bbw": "confidently full-figured with soft, graceful proportions and poised posture",
}

# ---------------------------------------------------------------------------
# ReActor face-swap parameters — mirrored EXACTLY from the pose graphs' node 200
# (edit_pose_action.json / pose_2511_API.json).
#
# CodeFormer semantics (verified against the node's actual behavior — the
# intuitive-sounding reading is INVERTED): ``codeformer_weight`` LOW = MORE
# hallucinated/smoothed restoration (the plastic, doll-skin look); HIGH = MORE
# faithful to the swapped input, i.e. it keeps the real skin texture inswapper
# produced. ``face_restore_visibility`` blends that restored face back over the
# raw swap (LOWER = more of the raw swap's own texture shows through the
# blend). The old baked values (0.25 weight / 0.8 visibility) were deep in the
# plastic zone: a LOW weight (heavy hallucinated smoothing) blended at HIGH
# visibility (mostly the smoothed result) — this is what was flushing every
# face to plastic. The current values raise the weight to stay faithful to the
# swapped face's texture and pull visibility down so more raw-swap detail
# survives the blend.
#
# REACTOR_FACE_RESTORE_MODEL below is now only the BAKED FALLBACK: the live
# default is ``settings.NUDE_BASE_FACE_RESTORE_MODEL`` (GPEN-BFR-512.onnx —
# see config.py), applied to the main node whenever that setting is non-empty.
# inswapper_128 synthesizes identity at only 128px, so CodeFormer's own
# restore (itself low-res) was leaving faces soft; GPEN-BFR-512 restores at
# 512px instead. When ``settings.NUDE_BASE_FACE_BOOST`` is True (default),
# ``build_faceswap_workflow`` additionally wires a ReActorFaceBoost node into
# the main swap's ``face_boost`` input — it restores AND upscales the swapped
# face BEFORE it is pasted back onto the base, which is the actual fix for a
# 128px swap landing on a close-up face (the main node's own restore only
# acts on the face at the base image's resolution).
# ---------------------------------------------------------------------------
REACTOR_SWAP_MODEL = "inswapper_128.onnx"
REACTOR_FACE_DETECTION = "retinaface_resnet50"
REACTOR_FACE_RESTORE_MODEL = "codeformer-v0.1.0.pth"
REACTOR_FACE_RESTORE_VISIBILITY = 0.65
REACTOR_CODEFORMER_WEIGHT = 0.7


def stable_nude_base_seed(character_id: str) -> int:
    """
    Deterministic per-character sampling seed for the base render.

    ``zlib.crc32`` (NOT the built-in ``hash()``, which is salted per-process and
    would give a different base every restart) over the character id, so the same
    character always regenerates the byte-identical base geometry. Range is
    0..2**32-1, matching the sampler seed range char-gen already uses.
    """
    return zlib.crc32(character_id.encode("utf-8"))


def build_nude_base_prompt(persona) -> tuple:
    """
    Assemble the text-to-image base prompt for ``persona``.

    Reuses ``services.prompt_generator.assemble_generation_prompt`` UNMODIFIED
    (READ-ONLY dependency) so the base carries the SAME locked identity block as a
    hero generation — every available persona feature: age bucket, ethnicity/skin
    phrase, hair (style + color), eye color, body type, breast size. Forced:
    ``OutfitType.NAKED`` at ``NudityLevel.HIGH`` (fully nude base), the neutral
    standing full-body pose, the plain studio backdrop, a full-body natural shot,
    and NO variety seed (deterministic — a fixed pool draw would defeat the point).

    The char-gen quality tail ("highly detailed, natural skin texture") comes for
    free from the assembler; the WS-N anti-gloss clause is appended after it, and
    the gloss-suppression tokens are added to the negative. The arousal-styled
    NAKED/HIGH outfit clause the assembler injects is swapped for the CALM
    ``NEUTRAL_BASE_OUTFIT_CLAUSE`` (the base is a neutral reference, not a scene) —
    everything else (identity block, pose, backdrop, quality tail) is untouched.
    Right after that swap, the persona's own ``BODY_AESTHETIC_CLAUSES`` phrase
    (nude base v2) is appended — a graceful, model-like framing of whatever body
    type she already has, never a slimming rewrite of it — and skipped cleanly
    for an unknown/missing body type. Returns ``(positive, negative, locked_block)``.
    """
    # Full-body NATURAL shot: an explicit shot suppresses the seeded shot rotation
    # (deterministic) and pins natural finish + full-body framing. photoStyle here
    # drives the workflow-side wrapper (node 125), not the assembled text.
    shot = ShotOptions(
        framing=ShotFramingType.FULL_BODY,
        photoStyle=PhotoStyleType.NATURAL,
    )
    positive, negative, locked = assemble_generation_prompt(
        persona,
        free_text=PLAIN_BACKDROP_TEXT,
        shot=shot,
        outfit=OutfitType.NAKED,
        nudity_level=NudityLevel.HIGH,
        accessories=None,
        variety_seed=None,       # deterministic: no pool variety on the base
        pose_text=NEUTRAL_POSE_TEXT,
    )
    # Swap the arousal-styled NAKED/HIGH clause for the calm neutral reference clause.
    # The clause the assembler injected is EXACTLY generation_outfit_clause(NAKED, HIGH)
    # (no accessories / no variety seed here), so recomputing it gives the precise
    # replace target without touching outfit_vocab / prompt_generator. Bounded replace
    # (count=1) — the clause is a unique comma-joined part of the positive.
    naked_clause = generation_outfit_clause(OutfitType.NAKED, NudityLevel.HIGH)
    positive = positive.replace(naked_clause, NEUTRAL_BASE_OUTFIT_CLAUSE, 1)
    # Body-aesthetic clause (nude base v2): same enum-or-str value extraction the
    # rest of the codebase uses for persona fields (ap.phrase() -> ap._val()), so
    # a raw string ("curvy") or a BodyType member both resolve. Unknown/missing
    # body type -> "" -> ap.phrase's own default, so the comma-join below skips
    # cleanly with no dangling ", ".
    body_clause = ap.phrase(BODY_AESTHETIC_CLAUSES, getattr(persona, "bodyType", None))
    if body_clause:
        positive = f"{positive}, {body_clause}"
    positive = f"{positive}, {ANTI_GLOSS_POSITIVE}"
    negative = f"{negative}, {ANTI_GLOSS_NEGATIVE}"
    return positive, negative, locked


def build_t2i_workflow(t2i_template: dict, persona, seed: int) -> dict:
    """
    Build the ready-to-run text-to-image base workflow from the char-gen template.

    The photo style is ALWAYS ``natural`` here — the base render deliberately
    ignores any character/controls photo_style so it can never inherit a polished/
    studio glamour finish. ``hires`` follows ``GENERATION_HIRES_DEFAULT`` (texture-
    detail refine pass) and the resolution is left untouched (no downscale — the
    template's native char-gen resolution stands).
    """
    positive, negative, _locked = build_nude_base_prompt(persona)
    return ComfyUIClient.prepare_character_workflow(
        workflow_template=t2i_template,
        character_prompt=positive,
        seed=seed,
        filename_prefix=f"NUDEBASE_{seed}",
        resolution=None,
        aspect_ratio=None,       # keep the template's native resolution (no downscale)
        batch_size=1,
        negative_prompt=negative,
        photo_style=PhotoStyleType.NATURAL.value,   # ALWAYS natural
        hires=settings.GENERATION_HIRES_DEFAULT,     # refine pass for texture detail
        time_of_day=None,
    )


def build_faceswap_workflow(base_image_name: str, hero_image_name: str) -> dict:
    """
    Minimal ReActor face-swap graph, authored in code (no new workflow JSON).
    Only invoked by ``_process_job`` when ``settings.NUDE_BASE_FACE_SWAP`` is True
    (OFF by default — see config.py); the function itself is unconditional so the
    graph shape can still be unit-tested with the flag ignored:

        LoadImage(base)  --input_image-->  ReActorFaceSwap  --> SaveImage
        LoadImage(hero)  --source_image--/
                                  ^
                    ReActorFaceBoost --face_boost-/  (settings.NUDE_BASE_FACE_BOOST)

    ``base_image_name`` is the generated t2i base (the body the face is stamped
    ONTO). ``hero_image_name`` is the ORIGINAL hero photo (the face DONOR / identity
    source) — never a generated or intermediate image. Node params mirror the pose
    graphs' node 200 exactly (fidelity-favoring restore — see the REACTOR_* constants
    above), except the restore model and the optional FaceBoost pass are settings-
    driven (``NUDE_BASE_FACE_RESTORE_MODEL`` / ``NUDE_BASE_FACE_BOOST`` — see
    config.py), so a sharper restorer can be rolled out or rolled back without a code
    change. Both images are shipped alongside as base64 ``input.images[]`` entries
    under these flat names.
    """
    face_restore_model = settings.NUDE_BASE_FACE_RESTORE_MODEL or REACTOR_FACE_RESTORE_MODEL

    workflow = {
        "10": {
            "class_type": "LoadImage",
            "inputs": {"image": base_image_name},
        },
        "11": {
            "class_type": "LoadImage",
            "inputs": {"image": hero_image_name},
        },
        "12": {
            "class_type": "ReActorFaceSwap",
            "inputs": {
                "enabled": True,
                "input_image": ["10", 0],       # the generated base body
                "source_image": ["11", 0],      # the ORIGINAL hero face
                "swap_model": REACTOR_SWAP_MODEL,
                "facedetection": REACTOR_FACE_DETECTION,
                "face_restore_model": face_restore_model,
                "face_restore_visibility": REACTOR_FACE_RESTORE_VISIBILITY,
                "codeformer_weight": REACTOR_CODEFORMER_WEIGHT,
                "detect_gender_input": "no",
                "detect_gender_source": "no",
                "input_faces_index": "0",
                "source_faces_index": "0",
                "console_log_level": 1,
            },
        },
        "13": {
            "class_type": "SaveImage",
            "inputs": {"images": ["12", 0], "filename_prefix": "nude_base"},
        },
    }

    if settings.NUDE_BASE_FACE_BOOST:
        # Restores + upscales the swapped face BEFORE it is pasted back onto the
        # base (vs. the main node's own restore, which only ever sees the face at
        # the base image's resolution) — the real fix for inswapper's 128px swap
        # landing on a close-up face. "5" is unused elsewhere in this graph.
        workflow["5"] = {
            "class_type": "ReActorFaceBoost",
            "inputs": {
                "enabled": True,
                "boost_model": face_restore_model,
                "interpolation": "Bicubic",
                "visibility": 1.0,
                "codeformer_weight": 0.5,
                "restore_with_main_after": False,
            },
        }
        workflow["12"]["inputs"]["face_boost"] = ["5", 0]

    return workflow


def _download_image(url: str, timeout: int = 30) -> bytes:
    """Download image bytes from a URL. Raises RuntimeError on failure."""
    try:
        response = http_requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.content
    except http_requests.RequestException as e:
        raise RuntimeError(f"Failed to download image: {e}")


def _stage_image(image_bytes: bytes, prefix: str) -> tuple:
    """Encode bytes as a RunPod input.images[] entry. Returns (name, images_list)."""
    name = f"{prefix}_{uuid.uuid4().hex[:12]}.png"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return name, [{"name": name, "image": f"data:image/png;base64,{b64}"}]


def _bytes_from_output(first: dict, step: str) -> bytes:
    """Resolve output image bytes from a parsed RunPod output entry (url or data)."""
    if first.get("url"):
        return _download_image(first["url"])
    data = first.get("data")
    if not data:
        raise RuntimeError(f"No image data from {step} step")
    return base64.b64decode(data)


class NudeBaseWorker:
    """
    Async worker that processes ``nude_base`` jobs: t2i base render -> optional
    ReActor face pass (``settings.NUDE_BASE_FACE_SWAP``, OFF by default), chained
    in one job. Mirrors the BackgroundWorker/PipelineBackgroundWorker lifecycle
    (start/stop, template load on start, single worker loop).
    """

    def __init__(
        self,
        job_manager: JobManager,
        comfyui_client: ComfyUIClient,
        storage_service: StorageService,
        workflow_path: str,
        notification_service: Optional[NotificationService] = None,
        supabase_storage_service: Optional[SupabaseStorageService] = None,
        runpod_client: Optional[RunPodServerlessClient] = None,
    ):
        self.job_manager = job_manager
        self.comfyui = comfyui_client
        self.runpod_client = runpod_client
        self.storage = storage_service
        self.supabase_storage = supabase_storage_service
        # The char-gen text-to-image template (COMFYUI_WORKFLOW_PATH) — same graph
        # the hero is generated from, so the base matches its resolution/quality.
        self.workflow_path = workflow_path
        self.notification = notification_service
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._t2i_template: Optional[dict] = None

    async def start(self) -> None:
        self._running = True
        await self._load_workflow()
        self._task = asyncio.create_task(self._worker_loop())
        logger.info("Nude-base worker started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Nude-base worker stopped")

    async def _load_workflow(self) -> None:
        workflow_file = Path(self.workflow_path)
        if not workflow_file.exists():
            raise FileNotFoundError(f"Nude-base t2i workflow not found: {self.workflow_path}")
        import json
        with open(workflow_file, "r", encoding="utf-8") as f:
            self._t2i_template = json.load(f)
        logger.info(f"Loaded nude-base t2i workflow template: {self.workflow_path}")

    async def _worker_loop(self) -> None:
        logger.info("Nude-base worker loop started, waiting for jobs...")
        while self._running:
            try:
                job_id = await self.job_manager.get_next_nude_base_job()
                job = await self.job_manager.get_job(job_id)

                if not job:
                    logger.warning(f"Nude-base job {job_id} not found in registry")
                    self.job_manager.mark_nude_base_done()
                    continue

                if job.status == JobStatus.FAILED:
                    logger.info(f"Skipping cancelled nude-base job {job_id}")
                    self.job_manager.mark_nude_base_done()
                    continue

                logger.info(f"Processing nude-base job {job_id} for user {job.user_id}")
                await self._process_job(job)

            except asyncio.CancelledError:
                logger.info("Nude-base worker loop cancelled")
                break
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error in nude-base worker loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    async def _process_job(self, job: Job) -> None:
        """Run the t2i base render, then the optional ReActor face pass, then persist."""
        start_time = datetime.utcnow()
        request = job.request

        try:
            if self.runpod_client is None:
                raise RuntimeError("RunPod client not configured")

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.0, seed_used=request.seed
            )
            logger.info(
                f"[NUDE-BASE] {job.job_id} | RUNNING | character={request.character_id} "
                f"seed={request.seed}"
            )

            # --- Step 1: text-to-image base (no input images — pure generation) ---
            t2i_workflow = build_t2i_workflow(self._t2i_template, request.persona, request.seed)
            base_prompt = t2i_workflow.get("110", {}).get("inputs", {}).get("value", "")
            logger.info(f"[NUDE-BASE] {job.job_id} | t2i prompt: {base_prompt[:120]}...")
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.15, prompt_used=base_prompt
            )

            base_outputs = await runpod_runner.run_workflow(
                self.runpod_client, self.job_manager, job.job_id, t2i_workflow,
                images=None, progress_start=0.15, progress_end=0.55,
            )
            if not base_outputs:
                raise RuntimeError("No image returned from t2i base step")
            base_bytes = await asyncio.to_thread(_bytes_from_output, base_outputs[0], "t2i base")
            logger.info(f"[NUDE-BASE] {job.job_id} | base rendered ({len(base_bytes)} bytes)")

            # --- Step 2: optional ReActor face pass — hero face onto the generated
            # base. OFF by default (settings.NUDE_BASE_FACE_SWAP=False): the base's
            # own face never reaches a published photo (every batch photo's face is
            # stamped from the HERO at the pose step), so swapping it here is wasted
            # GPU work and a false identity signal in admin. When off, the t2i output
            # from step 1 IS the final base image — same upload/status flow below,
            # just without the second workflow round-trip (no hero download, no
            # second submit_and_poll).
            if settings.NUDE_BASE_FACE_SWAP:
                await self.job_manager.update_job_status(
                    job.job_id, JobStatus.RUNNING, progress=0.6
                )
                hero_bytes = await asyncio.to_thread(_download_image, request.hero_image_url)
                base_name, images = _stage_image(base_bytes, "nudebase_base")
                hero_name, hero_images = _stage_image(hero_bytes, "nudebase_hero")
                images.extend(hero_images)

                face_workflow = build_faceswap_workflow(base_name, hero_name)
                face_outputs = await runpod_runner.run_workflow(
                    self.runpod_client, self.job_manager, job.job_id, face_workflow,
                    images=images, progress_start=0.6, progress_end=0.9,
                )
                if not face_outputs:
                    raise RuntimeError("No image returned from face-swap step")
                final_bytes = await asyncio.to_thread(_bytes_from_output, face_outputs[0], "face-swap")
                logger.info(
                    f"[NUDE-BASE] {job.job_id} | face locked from hero ({len(final_bytes)} bytes)"
                )
            else:
                final_bytes = base_bytes
                await self.job_manager.update_job_status(
                    job.job_id, JobStatus.RUNNING, progress=0.9
                )
                logger.info(
                    f"[NUDE-BASE] {job.job_id} | face swap OFF (NUDE_BASE_FACE_SWAP=False) — "
                    f"t2i base is the final image ({len(final_bytes)} bytes)"
                )

            # --- Persist final output (identical finalize contract to other workers) ---
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.RUNNING, progress=0.92,
                image_generated_at=datetime.utcnow(),
            )
            if self.supabase_storage:
                preview_url, image_hash = await asyncio.to_thread(
                    self.supabase_storage.upload_image,
                    image=final_bytes,
                    image_id=job.job_id,
                    folder="nude_bases",
                )
                expires_at = None
                relative_path = f"nude_bases/{job.job_id}.png"
            else:
                relative_path, image_hash = self.storage.save_image(final_bytes, job.job_id)
                preview_url, expires_at = self.storage.generate_signed_url(relative_path)

            completed_at = datetime.utcnow()
            await self.job_manager.update_job_status(
                job.job_id, JobStatus.SUCCEEDED, progress=1.0,
                result_path=relative_path,
                preview_url=preview_url,
                preview_expires_at=expires_at,
                image_hash=image_hash,
                completed_at=completed_at,
            )
            total = (completed_at - start_time).total_seconds()
            logger.info(
                f"[NUDE-BASE] {job.job_id} | SUCCEEDED | {total:.2f}s | URL: {preview_url}"
            )

        except Exception as e:  # noqa: BLE001
            error_msg = str(e)
            total = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"[NUDE-BASE] {job.job_id} | FAILED | {error_msg} | {total:.2f}s")
            traceback.print_exc()

            error_code = "NUDE_BASE_ERROR"
            lower = error_msg.lower()
            if "out of memory" in lower or "outofmemoryerror" in lower:
                error_code = "GPU_OOM_ERROR"
            elif "download" in lower:
                error_code = "DOWNLOAD_ERROR"
            elif "no image" in lower:
                error_code = "NO_OUTPUT_ERROR"

            await self.job_manager.update_job_status(
                job.job_id, JobStatus.FAILED,
                error_message=error_msg, error_code=error_code,
            )
            if self.notification:
                await self.notification.send_job_failed(
                    job_id=job.job_id, user_id=job.user_id,
                    error_message=error_msg, error_code=error_code,
                    total_duration=total,
                )
        finally:
            self.job_manager.mark_nude_base_done()
