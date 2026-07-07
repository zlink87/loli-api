"""
Character management endpoints (batch generation). Admin-only.

POST/GET/PATCH/DELETE /v1/characters — real rows in the product `characters`
table (created as status='draft'), reusable across batches.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.admin import require_admin
from models.character import CharacterCreate, CharacterUpdate, CharacterRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/characters", tags=["Characters"])

_character_store = None


def set_character_store(store) -> None:
    global _character_store
    _character_store = store


def get_character_store():
    if _character_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Character store not configured (Supabase DB required)",
        )
    return _character_store


@router.post("", response_model=CharacterRead, status_code=status.HTTP_201_CREATED)
async def create_character(
    body: CharacterCreate,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_store()
    return await store.create(body)


@router.get("", response_model=List[CharacterRead])
async def list_characters(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_store()
    return await store.list(limit=limit, offset=offset)


@router.get("/{character_id}", response_model=CharacterRead)
async def get_character(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_store()
    character = await store.get(character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return character


@router.patch("/{character_id}", response_model=CharacterRead)
async def update_character(
    character_id: str,
    body: CharacterUpdate,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_store()
    character = await store.update(character_id, body)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return character


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_store()
    ok = await store.delete(character_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return None
