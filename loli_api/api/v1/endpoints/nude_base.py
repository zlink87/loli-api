"""
Nude-base generation endpoints — ADMIN ONLY.

WS-N (default, settings.NUDE_BASE_T2I=True): the nude base is now GENERATED from
scratch (text-to-image, like char-gen) from the character's locked identity + a
forced NAKED clause + a neutral standing full-body pose + a plain studio backdrop
+ the NATURAL photo style, at a deterministic per-character seed; an OPTIONAL ReActor
face pass (settings.NUDE_BASE_FACE_SWAP, default OFF) can then swap the ORIGINAL hero
face onto it, but by default the t2i output IS the base — see workers/nude_base_worker.py
(_submit_t2i_nude_base below). This is pose-independent and mask-free, so an unusual
hero crop can no longer make the model paint a second person into a mask (the old
two-headed composite that poisoned every downstream batch photo). The LEGACY
edit-based path below is preserved verbatim behind the flag (NUDE_BASE_T2I=False).

LEGACY path (flag False): a nude base is generated from the clothed hero photo via
the pipeline edit machinery: an outfit step (outfit=NAKED,
prompt mode "nude_base" — a NEUTRAL anatomical reference body, not the arousal-
styled NAKED scene tier — pushed hard, see _NUDE_BASE_OUTFIT_DENOISE /
_NUDE_BASE_OUTFIT_PROMPT_MODE below) chained with a background step that clears the
scene to a plain neutral SOLO backdrop (denoise + solo-subject person-mask knobs,
_NUDE_BASE_BACKGROUND_DENOISE / soloSubject below, so the hero's original crowd/
props don't survive). The head/face stays byte-locked exactly as on every other
edit (server YuNet head mask + crop-stitch composite-back — nothing new here).

WHY THE PIPELINE PATH (not the plain outfit-edit endpoint): a nude conversion needs
to fully REMOVE the source garment, not blend a new one over it — the standard
"change the outfit to X" phrasing at the engine's default denoise tends to let the
source clothing ghost through (the same failure mode that made batch outfit swaps
unreliable — see outfit_denoise/outfit_prompt_mode on BatchControls). The plain
/v1/edit/outfit path has no way to ask for that extra strength, so this endpoint
goes through /v1/edit's PipelineEditRequest instead, which already carries
outfitDenoise/outfitPromptMode end to end, and additionally gets a background step
in the SAME job by setting `prompt` (a plain-backdrop instruction) alongside outfit.

KNOWN LIMITATION: HEAD accessories (glasses, earrings, hat, sunglasses) cannot be
removed here — they sit on the identity-locked head region (YuNet head mask), which
every edit step deliberately never touches. A character wearing glasses in her hero
photo will keep them in her nude base. This is the same, deliberate identity-lock
tradeoff documented for batches (see docs/ADMIN_STORY_BATCHES_V2_WORKORDER.md §7).

Once a character has a nude base, story batches automatically start each scene's edit
chain from it instead of the clothed hero, so dressing is ADDITIVE (clothes onto bare
skin) rather than subtractive (swap one outfit for another, which lets the hero's
original garment ghost through the new outfit). It is an explicit, per-character admin
action — NEVER auto-generated; batches simply USE it when present and fall back to the
hero photo when absent (zero behavior change for characters without one).

Routes (all require_admin, character-scoped):
    POST /v1/characters/{character_id}/nude-base   -> start generation (returns a job_id)
    GET  /v1/characters/{character_id}/nude-base   -> status; finalizes on the job's success

REROLL (t2i path only, 2026-07-14): POST accepts an optional `variant` query param
(0..99, default 0). The base render's sampler seed is otherwise pinned per-character
(stable_nude_base_seed, workers/nude_base_worker.py), so without this knob every
regeneration reproduced the byte-identical body. `variant=0`/omitted keeps that exact
canonical seed; `variant=1, 2, ...` each draw a different, still fully deterministic
body from the same locked identity/pose/backdrop — POST again with an incremented
variant until the rendered body looks right. Out-of-range values 422. No effect on the
LEGACY edit-based path (flag off) — that path has no seed-reroll concept.

MODERATION / CONSENT: this deliberately creates and stores an explicit nude asset per
character. Only run it for characters where that is intended and permitted.

The async contract matches every other edit endpoint: POST returns a job_id (202); poll
GET /v1/jobs/{jobId} as usual. GET here additionally finalizes the base into permanent
storage the moment that job has succeeded (reconcile-on-read — no background task).
Calling POST again after a `failed` (or to regenerate after `succeeded`) status is a
normal retry — it is only short-circuited while a job is still genuinely in flight.
"""
import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.admin import require_admin
from api.v1.endpoints.pipeline import submit_pipeline_edit_job
from config import settings
from models.enums import JobStatus, NudityLevel, OutfitType
from models.nude_base import NudeBaseRead, NudeBaseStatusResponse
from models.requests import PipelineEditRequest, NudeBaseGenerateRequest
from workers.nude_base_worker import stable_nude_base_seed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/characters", tags=["Nude Base"])

# Nudity target for the base render: fully undressed so scenes dress additively.
_NUDE_BASE_NUDITY = NudityLevel.HIGH
# Pushed well above the batch default (0.85) — this needs a full strip, not a
# garment swap, so it errs toward maximum removal strength. Bounded at 0.95 by
# PipelineEditRequest.outfitDenoise; identity is unaffected regardless of this
# value (the head sits outside the edit mask on every tier).
_NUDE_BASE_OUTFIT_DENOISE = 0.92
# "nude_base" = the neutral-anatomical-base prompt mode (build_prompt, outfit.py):
# on the NAKED outfit it swaps the scene-tier arousal prose ("hard nipples, swollen
# aroused pussy lips…", wrong for a neutral reference asset) for a calm reference-
# body description AND hardens the removal lead so no stray bra/strap/underwear
# survives. Supersedes the old "replace" mode here, which reused that arousal prose.
_NUDE_BASE_OUTFIT_PROMPT_MODE = "nude_base"
# Pushed high (max 1.0 on backgroundDenoise) so the busy hero scene is actually
# cleared: the V1 background graph samples at cfg 1.0 with denoise baked at 0.8, so
# a clean backdrop needs the extra removal strength from the denoise knob, not the
# (mathematically inert) negatives.
_NUDE_BASE_BACKGROUND_DENOISE = 0.95
# Clears the hero's original scene to a plain, neutral backdrop — an internal asset
# shouldn't carry a specific location/prop (or a passerby out of the hero's street
# crowd) into every scene built from it. The "only person in the frame" tail pairs
# with soloSubject=True on the request: the background step's person detector then
# drops low-confidence background people out of the protected mask so they get
# painted over instead of composited back byte-exact.
_NUDE_BASE_BACKGROUND_PROMPT = (
    "a plain seamless light grey studio backdrop, soft even lighting, "
    "no furniture, props, or distracting objects, she is the only person in the "
    "frame, no other people anywhere, empty backdrop"
)
# Reroll bound for POST's `variant` query param (t2i path only — see
# _submit_t2i_nude_base / stable_nude_base_seed). Enforced with a manual check in
# generate_nude_base rather than relying solely on the Query(ge=/le=) annotation
# below, because this endpoint is also called directly (bypassing FastAPI's own
# request parsing) throughout tests/test_nude_base_t2i.py and tests/test_nude_base.py.
_NUDE_BASE_VARIANT_MAX = 99

# ---------------------------------------------------------------------------
# Global service instances (set from main.py via router.configure_services)
# ---------------------------------------------------------------------------
_job_manager = None
_character_store = None
_nude_base_store = None


def set_job_manager(job_manager) -> None:
    global _job_manager
    _job_manager = job_manager


def set_character_store(store) -> None:
    global _character_store
    _character_store = store


def set_nude_base_store(store) -> None:
    global _nude_base_store
    _nude_base_store = store


def get_job_manager():
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def _require_stores():
    if _character_store is None or _nude_base_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nude base requires the Supabase DB (stores not configured)",
        )
    return _character_store, _nude_base_store


def _status_response(nb: NudeBaseRead) -> NudeBaseStatusResponse:
    return NudeBaseStatusResponse(
        characterId=nb.character_id,
        status=nb.status,
        jobId=nb.job_id,
        imageUrl=nb.image_url,
        error=nb.error,
        createdAt=nb.created_at,
        updatedAt=nb.updated_at,
    )


async def _finalize_if_ready(nb: NudeBaseRead) -> NudeBaseRead:
    """
    Reconcile-on-read: if the base is still 'pending', poll its pipeline_edit job and
    persist the result — succeeded -> store the stable URL + flip to succeeded;
    failed -> record the error; a vanished job (in-memory registry cleaned after
    ~24h) -> mark failed so the admin can regenerate rather than being stuck pending.
    Terminal rows are returned unchanged.
    """
    if nb.status != "pending" or not nb.job_id:
        return nb

    _, nude_base_store = _require_stores()
    job = await get_job_manager().get_job(nb.job_id)

    if job is None:
        updated = await nude_base_store.update_status(
            nb.id, "failed",
            error="Generation job no longer available (expired); please regenerate.",
        )
        return updated or nb

    if job.status == JobStatus.SUCCEEDED:
        # In production (Supabase storage) preview_url is the stable public URL
        # (no expiry) the worker uploaded — persist it as the nude base.
        updated = await nude_base_store.update_status(
            nb.id, "succeeded",
            image_url=job.preview_url,
            image_hash=job.image_hash,
        )
        logger.info(f"[NUDE-BASE] finalized {nb.id} for character {nb.character_id}")
        return updated or nb

    if job.status == JobStatus.FAILED:
        updated = await nude_base_store.update_status(
            nb.id, "failed",
            error=job.error_message or "Nude base generation failed",
        )
        return updated or nb

    return nb  # queued / running — still pending


async def _submit_t2i_nude_base(
    character, character_id: str, nude_base_store, user_id: str, variant: int = 0
):
    """
    NEW default path (settings.NUDE_BASE_T2I=True): a deterministic text-to-image
    base render, run as ONE `nude_base` job (workers/nude_base_worker.py). The ReActor
    face lock from the ORIGINAL hero is OPTIONAL and OFF by default
    (settings.NUDE_BASE_FACE_SWAP=False), so by default the t2i output IS the base — the
    published batch faces always come from the hero via the pose-step ReActor anyway. The
    seed is a stable zlib.crc32 of the character id offset by `variant` (the REROLL
    index — see generate_nude_base below), so `variant=0` (default) reproduces the exact
    same base body geometry every call and `variant=1..99` each draw a distinct but
    still deterministic reroll. Records a `pending` base row against the created job.
    """
    if get_job_manager().is_queue_full(job_type="nude_base"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Nude base generation queue is full. Please try again later.",
        )
    seed = stable_nude_base_seed(character_id, variant)
    request = NudeBaseGenerateRequest(
        persona=character.persona,
        hero_image_url=character.hero_image_url,
        character_id=character_id,
        seed=seed,
        variant=variant,
    )
    job = await get_job_manager().create_job(request, user_id, job_type="nude_base")
    nb = await nude_base_store.create(
        character_id, job_id=job.job_id, source_image_url=character.hero_image_url
    )
    logger.info(
        f"[NUDE-BASE] character {character_id} -> job {job.job_id} "
        f"(t2i base; face lock optional via NUDE_BASE_FACE_SWAP, default off, "
        f"seed={seed}, variant={variant})"
    )
    return nb


async def submit_nude_base_for_new_character(character, user_id: str):
    """
    Part 3 — best-effort auto nude-base submission on character creation.

    Reuses the EXACT text-to-image submit path as POST /characters/{id}/nude-base
    (``_submit_t2i_nude_base``): the same ``nude_base`` job, the same deterministic
    per-character seed, the same pending-row bookkeeping — no duplicated logic.

    Returns the pending ``NudeBaseRead`` on submit, or None when the feature is not
    applicable: ``settings.NUDE_BASE_T2I`` is off (only the t2i path auto-runs; the
    legacy edit path is never auto-triggered), the nude-base job manager / store are
    not configured, or the character has no hero image. Submission errors (e.g. a full
    queue -> 429) PROPAGATE to the caller; the character-create flow runs this
    best-effort and swallows them so creation never fails.
    """
    if not settings.NUDE_BASE_T2I:
        return None
    if _job_manager is None or _nude_base_store is None:
        return None
    if not getattr(character, "hero_image_url", None):
        return None
    return await _submit_t2i_nude_base(character, character.id, _nude_base_store, user_id)


async def _submit_legacy_nude_base(character, character_id: str, nude_base_store, user_id: str):
    """
    LEGACY path (settings.NUDE_BASE_T2I=False): edit-based undressing on the hero —
    outfit=NAKED at high nudity, pushed hard (denoise + "nude_base" prompt mode) so
    the source garment is actually removed rather than blended over, PLUS a background
    step (via `prompt`) in the same job so the base isn't stuck in the hero's original
    scene. Identity lock is automatic (the pipeline worker always stages the YuNet head
    mask + composite-back on both steps). sourceDressed is left at its default (False):
    NAKED is never a GARMENT_MODE_OUTFITS target, so it always uses the whole-body mask.

    Preserved byte-for-byte behind the flag as a rollback fallback for the t2i path.
    """
    request = PipelineEditRequest(
        source_image=character.hero_image_url,
        outfit=OutfitType.NAKED,
        nudityLevel=_NUDE_BASE_NUDITY,
        outfitDenoise=_NUDE_BASE_OUTFIT_DENOISE,
        outfitPromptMode=_NUDE_BASE_OUTFIT_PROMPT_MODE,
        prompt=_NUDE_BASE_BACKGROUND_PROMPT,
        backgroundDenoise=_NUDE_BASE_BACKGROUND_DENOISE,
        soloSubject=True,
    )
    job = await submit_pipeline_edit_job(request, user_id)

    nb = await nude_base_store.create(
        character_id, job_id=job.job_id, source_image_url=character.hero_image_url
    )
    logger.info(
        f"[NUDE-BASE] character {character_id} -> job {job.job_id} "
        f"(LEGACY edit-based: outfit=naked, nudity=high, denoise={_NUDE_BASE_OUTFIT_DENOISE}, "
        f"mode={_NUDE_BASE_OUTFIT_PROMPT_MODE}, background=plain solo "
        f"denoise={_NUDE_BASE_BACKGROUND_DENOISE})"
    )
    return nb


@router.post(
    "/{character_id}/nude-base",
    response_model=NudeBaseStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate the character's identity-locked nude base (admin)",
)
async def generate_nude_base(
    character_id: str,
    variant: Annotated[
        int,
        Query(
            ge=0,
            le=_NUDE_BASE_VARIANT_MAX,
            description=(
                "Reroll index (0..99). 0/omitted reproduces the canonical "
                "deterministic base byte-for-byte; POST again with an incremented "
                "value to draw a different, still deterministic body from the same "
                "identity (t2i path only — see stable_nude_base_seed)."
            ),
        ),
    ] = 0,
    user: Dict[str, Any] = Depends(require_admin),
):
    # Belt-and-suspenders: Query(ge=/le=) already 422s this over real HTTP, but this
    # endpoint is also called directly (bypassing FastAPI's request parsing) all
    # through tests/test_nude_base_t2i.py and tests/test_nude_base.py, where the
    # annotation's bounds are never evaluated.
    if not (0 <= variant <= _NUDE_BASE_VARIANT_MAX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"variant must be between 0 and {_NUDE_BASE_VARIANT_MAX}",
        )

    character_store, nude_base_store = _require_stores()
    user_id = user.get("sub", "admin")

    character = await character_store.get(character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if not character.hero_image_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Character has no hero image to derive a nude base from",
        )

    # Idempotency: if a base is already generating (pending + its job still live),
    # return that instead of spawning a duplicate render on a double-submit.
    existing = await nude_base_store.get_latest(character_id)
    if existing is not None and existing.status == "pending" and existing.job_id:
        job = await get_job_manager().get_job(existing.job_id)
        if job is not None and job.status not in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            return _status_response(existing)

    # Two generation paths, selected by settings.NUDE_BASE_T2I:
    #   * NEW (default): a text-to-image base render (with an OPTIONAL ReActor face lock,
    #     NUDE_BASE_FACE_SWAP, default OFF), run as ONE `nude_base` job
    #     (workers/nude_base_worker.py). Pose-independent and mask-free, so an unusual hero
    #     crop can no longer produce the old two-headed edit-based composite that poisoned
    #     every downstream batch photo.
    #   * LEGACY (flag False): the edit-based undressing on the hero (outfit step in
    #     "nude_base" prompt mode + background step, via the pipeline engine) — UNCHANGED.
    # Both record a `pending` base row against the created job; GET reconciles it on read.
    # `variant` (the reroll index) only means anything on the t2i path's seed math —
    # the legacy path has no seed-reroll concept, so it's simply not threaded there.
    if settings.NUDE_BASE_T2I:
        nb = await _submit_t2i_nude_base(character, character_id, nude_base_store, user_id, variant)
    else:
        nb = await _submit_legacy_nude_base(character, character_id, nude_base_store, user_id)
    return _status_response(nb)


@router.get(
    "/{character_id}/nude-base",
    response_model=NudeBaseStatusResponse,
    summary="Get the character's nude-base status; finalizes it on the job's success (admin)",
)
async def get_nude_base(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    _, nude_base_store = _require_stores()
    nb = await nude_base_store.get_latest(character_id)
    if nb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No nude base for this character (generate one first)",
        )
    nb = await _finalize_if_ready(nb)
    return _status_response(nb)
