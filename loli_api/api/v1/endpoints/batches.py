"""
Character batch endpoints. Admin-only.

POST /v1/characters/{id}/batches — plan + persist + (async) launch a batch.
GET  /v1/characters/{id}/batches — list a character's batches.
GET  /v1/batches/{id}            — aggregate status + items.
GET  /v1/batches/{id}/results    — succeeded items (with stable image URLs).
POST /v1/batches/{id}/launch     — promote a dry-run ('planned') batch.
POST /v1/batches/{id}/retry      — re-enqueue failed items.
DELETE /v1/batches/{id}          — cancel a batch.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.admin import require_admin
from models.batch import (
    BatchCreate,
    BatchRead,
    BatchDetailRead,
    BatchItemRead,
    BatchLaunchResponse,
)
from services.batch_orchestrator import CharacterNotFound

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Character Batches"])

_batch_store = None
_orchestrator = None


def set_batch_store(store) -> None:
    global _batch_store
    _batch_store = store


def set_orchestrator(orchestrator) -> None:
    global _orchestrator
    _orchestrator = orchestrator


def _require_services():
    if _batch_store is None or _orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Batch services not configured (Supabase DB required)",
        )
    return _batch_store, _orchestrator


@router.post(
    "/characters/{character_id}/batches",
    response_model=BatchLaunchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_batch(
    character_id: str,
    body: BatchCreate,
    user: Dict[str, Any] = Depends(require_admin),
):
    _, orchestrator = _require_services()
    try:
        batch, estimate = await orchestrator.launch_batch(character_id, body)
    except CharacterNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return BatchLaunchResponse(batch=batch, estimate=estimate)


@router.get("/characters/{character_id}/batches", response_model=List[BatchRead])
async def list_character_batches(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store, _ = _require_services()
    return await store.list_batches(character_id=character_id)


@router.get("/batches/{batch_id}", response_model=BatchDetailRead)
async def get_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store, _ = _require_services()
    detail = await store.get_batch_detail(batch_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return detail


@router.get("/batches/{batch_id}/results", response_model=List[BatchItemRead])
async def get_batch_results(
    batch_id: str,
    ready_only: bool = Query(True, description="Return only succeeded items with an image URL"),
    user: Dict[str, Any] = Depends(require_admin),
):
    store, _ = _require_services()
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    statuses = ["succeeded"] if ready_only else None
    return await store.list_items(batch_id, statuses=statuses)


@router.post("/batches/{batch_id}/launch", response_model=BatchRead, status_code=status.HTTP_202_ACCEPTED)
async def launch_planned_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Promote a dry-run ('planned') batch to a real run using its exact previewed plan."""
    store, orchestrator = _require_services()
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    if batch.status != "planned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a 'planned' (dry-run) batch can be launched; this batch is '{batch.status}'",
        )
    return await orchestrator.confirm_batch(batch_id) or batch


@router.post("/batches/{batch_id}/retry", response_model=BatchRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store, orchestrator = _require_services()
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    if batch.items_failed == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No failed items to retry")
    result = await orchestrator.retry_failed(batch_id)
    return result or batch


@router.delete("/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_batch(
    batch_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    _, orchestrator = _require_services()
    ok = await orchestrator.cancel_batch(batch_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return None
