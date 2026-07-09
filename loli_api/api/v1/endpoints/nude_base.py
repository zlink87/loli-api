"""
Nude-base generation endpoints — ADMIN ONLY.

A nude base is ONE identity-locked nude/underwear render per character, generated
from the clothed hero photo via the EXISTING outfit-edit machinery (outfit=NAKED at
high nudity). The head/face stays byte-locked exactly as on every other outfit edit
(server YuNet head mask + crop-stitch composite-back — nothing new is invented here).

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
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.admin import require_admin
from api.v1.endpoints.outfit import submit_outfit_edit_job
from models.enums import JobStatus, NudityLevel, OutfitType
from models.nude_base import NudeBaseRead, NudeBaseStatusResponse
from models.requests import OutfitEditRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/characters", tags=["Nude Base"])

# Nudity target for the base render: fully undressed so scenes dress additively.
_NUDE_BASE_NUDITY = NudityLevel.HIGH

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
    Reconcile-on-read: if the base is still 'pending', poll its outfit_edit job and
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

    # Reuse the EXACT outfit-edit path: outfit=NAKED at high nudity. Identity lock is
    # automatic (the outfit worker always stages the YuNet head mask + composite-back);
    # sourceDressed=True truthfully flags the clothed hero (inert for NAKED, which uses
    # the whole-body mask regardless, but accurate).
    request = OutfitEditRequest(
        source_image=character.hero_image_url,
        outfit=OutfitType.NAKED,
        nudityLevel=_NUDE_BASE_NUDITY,
        sourceDressed=True,
    )
    job = await submit_outfit_edit_job(request, user_id)

    nb = await nude_base_store.create(
        character_id, job_id=job.job_id, source_image_url=character.hero_image_url
    )
    logger.info(
        f"[NUDE-BASE] character {character_id} -> job {job.job_id} (outfit=naked, nudity=high)"
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
