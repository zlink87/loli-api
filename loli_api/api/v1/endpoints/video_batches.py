"""
Per-character video-batch endpoints. Admin-only.

An admin picks a character, picks N of its gallery stills, assigns each an action
(a preset from the tiered video action catalog, or a hand-written prompt), and
launches a batch; each item animates one still into a short WAN 2.2 i2v clip that
lands as a DRAFT chat action.

Routes (all require_admin):
  POST   /v1/characters/{id}/video-batches        — plan + persist + (async) launch.
  GET    /v1/characters/{id}/video-batches         — list a character's video batches.
  GET    /v1/video-batches/action-catalog          — tiers -> presets (the admin picker).
  GET    /v1/video-batches/{id}                     — aggregate status + items.
  GET    /v1/video-batches/{id}/results             — succeeded items (with clip URLs).
  POST   /v1/video-batches/{id}/launch              — promote a dry-run ('planned') batch.
  POST   /v1/video-batches/{id}/retry               — re-enqueue failed items.
  POST   /v1/video-batches/{id}/publish             — bulk-flip succeeded items' actions active.
  DELETE /v1/video-batches/{id}                      — cancel a batch.
  POST   /v1/video-batches/{id}/items/{item_id}/rerun — re-run one succeeded/failed item.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.admin import require_admin
from models.video_batch import (
    VideoBatchCreate,
    VideoBatchRead,
    VideoBatchDetailRead,
    VideoBatchItemRead,
    VideoBatchItemRerun,
    VideoBatchLaunchResponse,
    VideoActionCatalogRead,
)
from services.video_action_catalog import catalog_grouped_by_tier
from services.video_batch_orchestrator import (
    CharacterNotFound,
    VideoBatchValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Video Batches"])

_video_batch_store = None
_orchestrator = None


def set_video_batch_store(store) -> None:
    global _video_batch_store
    _video_batch_store = store


def set_video_batch_orchestrator(orchestrator) -> None:
    global _orchestrator
    _orchestrator = orchestrator


def _require_services():
    if _video_batch_store is None or _orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Video-batch services not configured "
                "(requires Supabase DB, RUNPOD_VIDEO_ENDPOINT_ID, and "
                "COMFYUI_VIDEO_LIGHTNING_WORKFLOW_PATH)"
            ),
        )
    return _video_batch_store, _orchestrator


# ---------------------------------------------------------------------------
# Create + list (character-scoped)
# ---------------------------------------------------------------------------
@router.post(
    "/characters/{character_id}/video-batches",
    response_model=VideoBatchLaunchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_video_batch(
    character_id: str,
    body: VideoBatchCreate,
    user: Dict[str, Any] = Depends(require_admin),
):
    _, orchestrator = _require_services()
    try:
        batch, estimate = await orchestrator.launch_batch(character_id, body)
    except CharacterNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    except VideoBatchValidationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return VideoBatchLaunchResponse(batch=batch, estimate=estimate)


@router.get(
    "/characters/{character_id}/video-batches", response_model=List[VideoBatchRead]
)
async def list_character_video_batches(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store, _ = _require_services()
    return await store.list_batches(character_id=character_id)


# ---------------------------------------------------------------------------
# Action catalog (declared BEFORE /video-batches/{batch_id} so the static path wins)
# ---------------------------------------------------------------------------
@router.get("/video-batches/action-catalog", response_model=VideoActionCatalogRead)
async def get_action_catalog(
    user: Dict[str, Any] = Depends(require_admin),
):
    """The tiered action catalog for the admin picker (does not require the DB)."""
    return VideoActionCatalogRead(tiers=catalog_grouped_by_tier())


# ---------------------------------------------------------------------------
# Batch read + lifecycle
# ---------------------------------------------------------------------------
@router.get("/video-batches/{batch_id}", response_model=VideoBatchDetailRead)
async def get_video_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store, _ = _require_services()
    detail = await store.get_batch_detail(batch_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch not found")
    return detail


@router.get(
    "/video-batches/{batch_id}/results", response_model=List[VideoBatchItemRead]
)
async def get_video_batch_results(
    batch_id: str,
    ready_only: bool = Query(True, description="Return only succeeded items with a clip URL"),
    user: Dict[str, Any] = Depends(require_admin),
):
    store, _ = _require_services()
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch not found")
    statuses = ["succeeded"] if ready_only else None
    return await store.list_items(batch_id, statuses=statuses)


@router.post(
    "/video-batches/{batch_id}/launch",
    response_model=VideoBatchRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def launch_planned_video_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Promote a dry-run ('planned') batch to a real run using its exact previewed plan."""
    store, orchestrator = _require_services()
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch not found")
    if batch.status != "planned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a 'planned' (dry-run) batch can be launched; this batch is '{batch.status}'",
        )
    return await orchestrator.confirm_batch(batch_id) or batch


@router.post(
    "/video-batches/{batch_id}/retry",
    response_model=VideoBatchRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_video_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store, orchestrator = _require_services()
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch not found")
    if batch.items_failed == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No failed items to retry")
    result = await orchestrator.retry_failed(batch_id)
    return result or batch


@router.post("/video-batches/{batch_id}/publish")
async def publish_video_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Bulk-flip every succeeded item's draft action to active (publish the whole batch)."""
    _, orchestrator = _require_services()
    published = await orchestrator.publish_batch(batch_id)
    if published is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch not found")
    return {"batchId": batch_id, "published": published}


@router.delete("/video-batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_video_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    _, orchestrator = _require_services()
    ok = await orchestrator.cancel_batch(batch_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch not found")
    return None


# ---------------------------------------------------------------------------
# Item rerun
# ---------------------------------------------------------------------------
_RERUNNABLE_ITEM_STATUSES = ("succeeded", "failed")


@router.post(
    "/video-batches/{batch_id}/items/{item_id}/rerun",
    response_model=VideoBatchItemRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rerun_video_batch_item(
    batch_id: str,
    item_id: str,
    body: VideoBatchItemRerun = VideoBatchItemRerun(),
    user: Dict[str, Any] = Depends(require_admin),
):
    """
    Re-run a single succeeded/failed item, optionally with a new action (preset XOR
    custom) and/or a new seed. Resets it to 'pending' (clearing its clip + publish
    guards), and flips a settled batch back to 'running' so the reconciler re-enqueues it.
    The previously published gallery clip is superseded on rerun.
    """
    store, orchestrator = _require_services()
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch not found")
    item = await store.get_item(item_id, batch_id=batch_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video batch item not found")
    if item.status not in _RERUNNABLE_ITEM_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a 'succeeded' or 'failed' item can be rerun; this item is '{item.status}'",
        )
    try:
        await orchestrator.rerun_item(batch_id, item_id, body)
    except VideoBatchValidationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return await store.get_item(item_id, batch_id=batch_id)
