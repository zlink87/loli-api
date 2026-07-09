"""
Nude-base generation endpoints — ADMIN ONLY.

A nude base is ONE identity-locked nude render per character, generated from the
clothed hero photo via the pipeline edit machinery: an outfit step (outfit=NAKED
at high nudity, pushed hard — see _NUDE_BASE_OUTFIT_DENOISE/_NUDE_BASE_PROMPT_MODE
below) chained with a background step that clears the scene to a plain neutral
backdrop. The head/face stays byte-locked exactly as on every other edit (server
YuNet head mask + crop-stitch composite-back — nothing new is invented here).

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

MODERATION / CONSENT: this deliberately creates and stores an explicit nude asset per
character. Only run it for characters where that is intended and permitted.

The async contract matches every other edit endpoint: POST returns a job_id (202); poll
GET /v1/jobs/{jobId} as usual. GET here additionally finalizes the base into permanent
storage the moment that job has succeeded (reconcile-on-read — no background task).
Calling POST again after a `failed` (or to regenerate after `succeeded`) status is a
normal retry — it is only short-circuited while a job is still genuinely in flight.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.admin import require_admin
from api.v1.endpoints.pipeline import submit_pipeline_edit_job
from models.enums import JobStatus, NudityLevel, OutfitType
from models.nude_base import NudeBaseRead, NudeBaseStatusResponse
from models.requests import PipelineEditRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/characters", tags=["Nude Base"])

# Nudity target for the base render: fully undressed so scenes dress additively.
_NUDE_BASE_NUDITY = NudityLevel.HIGH
# Pushed well above the batch default (0.85) — this needs a full strip, not a
# garment swap, so it errs toward maximum removal strength. Bounded at 0.95 by
# PipelineEditRequest.outfitDenoise; identity is unaffected regardless of this
# value (the head sits outside the edit mask on every tier).
_NUDE_BASE_OUTFIT_DENOISE = 0.92
# "replace" = explicit remove-then-apply lead-in, instead of the default
# "change the outfit to X" phrasing that lets the source garment ghost through.
_NUDE_BASE_OUTFIT_PROMPT_MODE = "replace"
# Clears the hero's original scene to a plain, neutral backdrop — an internal
# asset shouldn't carry a specific location/prop into every scene built from it.
_NUDE_BASE_BACKGROUND_PROMPT = (
    "a plain seamless light grey studio backdrop, soft even lighting, "
    "no furniture, props, or distracting objects"
)

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


@router.post(
    "/{character_id}/nude-base",
    response_model=NudeBaseStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate the character's identity-locked nude base (admin)",
)
async def generate_nude_base(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
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

    # Pipeline job: outfit=NAKED at high nudity, pushed hard (denoise + replace-mode)
    # so the source garment is actually removed rather than blended over, PLUS a
    # background step (via `prompt`) in the same job so the base isn't stuck in the
    # hero's original scene. Identity lock is automatic (the pipeline worker always
    # stages the YuNet head mask + composite-back on both steps) — nothing here can
    # touch the head/face regardless of denoise. sourceDressed is left at its default
    # (False): NAKED is never a GARMENT_MODE_OUTFITS target, so it always uses the
    # whole-body mask either way — sourceDressed=True would be a no-op here, not a
    # correctness issue, but leaving it unset keeps the request's meaning honest.
    request = PipelineEditRequest(
        source_image=character.hero_image_url,
        outfit=OutfitType.NAKED,
        nudityLevel=_NUDE_BASE_NUDITY,
        outfitDenoise=_NUDE_BASE_OUTFIT_DENOISE,
        outfitPromptMode=_NUDE_BASE_OUTFIT_PROMPT_MODE,
        prompt=_NUDE_BASE_BACKGROUND_PROMPT,
    )
    job = await submit_pipeline_edit_job(request, user_id)

    nb = await nude_base_store.create(
        character_id, job_id=job.job_id, source_image_url=character.hero_image_url
    )
    logger.info(
        f"[NUDE-BASE] character {character_id} -> job {job.job_id} "
        f"(outfit=naked, nudity=high, denoise={_NUDE_BASE_OUTFIT_DENOISE}, "
        f"mode={_NUDE_BASE_OUTFIT_PROMPT_MODE}, background=plain)"
    )
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
