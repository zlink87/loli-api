"""
Character batch endpoints. Admin-only.

POST /v1/characters/{id}/batches — plan + persist + (async) launch a batch.
GET  /v1/characters/{id}/batches — list a character's batches.
GET  /v1/batches/{id}            — aggregate status + items.
GET  /v1/batches/{id}/results    — succeeded items (with stable image URLs).
POST /v1/batches/{id}/launch     — promote a dry-run ('planned') batch.
POST /v1/batches/{id}/retry      — re-enqueue failed items.
DELETE /v1/batches/{id}          — cancel a batch.
PATCH  /v1/batches/{id}/items/{item_id}        — edit one item's scene_spec.
POST   /v1/batches/{id}/items/{item_id}/rerun  — re-run one succeeded/failed item.
"""
import logging
import random
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.admin import require_admin
from models.batch import (
    BatchCreate,
    BatchRead,
    BatchDetailRead,
    BatchItemRead,
    BatchItemEdit,
    BatchItemRerun,
    BatchLaunchResponse,
)
from services import story_planner
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


_EDITABLE_ITEM_STATUSES = ("succeeded", "failed")


async def _load_item_for_mutation(store, batch_id: str, item_id: str, verb: str):
    """Shared 404/409 guard for the item edit + rerun endpoints.

    Returns (batch, item) for a succeeded/failed item, else raises the right HTTP
    error. ``verb`` is the action word used in the 409 message ('edited'/'rerun')."""
    batch = await store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    item = await store.get_item(item_id, batch_id=batch_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch item not found")
    if item.status not in _EDITABLE_ITEM_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only a 'succeeded' or 'failed' item can be {verb}; "
                f"this item is '{item.status}'"
            ),
        )
    return batch, item


@router.patch("/batches/{batch_id}/items/{item_id}", response_model=BatchItemRead)
async def edit_batch_item(
    batch_id: str,
    item_id: str,
    body: BatchItemEdit,
    user: Dict[str, Any] = Depends(require_admin),
):
    """
    Edit a subset of one item's scene_spec (outfit/location/pose/nudity/time/lighting
    + the free-text detail fields), validated through the SAME enum-coercion + controls
    filters the planner uses so an edit can't bypass allow/block, sfw_only, or max_nudity.
    Only 'succeeded' or 'failed' items are editable.
    """
    store, _ = _require_services()
    batch, item = await _load_item_for_mutation(store, batch_id, item_id, "edited")

    edit = body.model_dump(exclude_unset=True)
    if not edit:
        return item
    try:
        updated = story_planner.apply_item_scene_edit(item.scene_spec, edit, batch.controls)
    except story_planner.SceneEditError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    await store.update_item_scene_spec(item_id, updated.model_dump(mode="json"))
    return await store.get_item(item_id, batch_id=batch_id)


@router.post(
    "/batches/{batch_id}/items/{item_id}/rerun",
    response_model=BatchItemRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rerun_batch_item(
    batch_id: str,
    item_id: str,
    body: BatchItemRerun = BatchItemRerun(),
    user: Dict[str, Any] = Depends(require_admin),
):
    """
    Re-run a single succeeded/failed item. Resets it to 'pending' (clearing its old
    image + error fields), keeps the stored seed unless ``reseed`` (fresh random) or
    ``new_seed`` is given, and flips a settled batch back to 'running' so the reconciler
    re-enqueues it. The previously published gallery image is superseded on rerun.
    """
    store, orchestrator = _require_services()
    await _load_item_for_mutation(store, batch_id, item_id, "rerun")

    seed = None
    if body.reseed:
        seed = random.randint(1, 1_000_000_000)
    elif body.new_seed is not None:
        seed = body.new_seed

    await orchestrator.rerun_item(batch_id, item_id, seed=seed)
    return await store.get_item(item_id, batch_id=batch_id)


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
