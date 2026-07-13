"""
Character trait-profile endpoints. Admin-only.

GET  /v1/characters/{id}/trait-profile          — the character's current trait sheet.
POST /v1/characters/{id}/trait-profile/generate — generate + persist (per-field; fields
                                                   default ALL; dry_run returns only).
PUT  /v1/characters/{id}/trait-profile          — manual per-field edit (provider="manual").
POST /v1/trait-profiles/preview                 — stateless suggestions (no character row).
POST /v1/trait-profiles/backfill                — generate profiles for characters lacking one.

Venice authors a structured trait sheet from the character's persona enums + bio;
everything runs through TraitProfile.coerce and is persisted (never-clobber) into
the character_trait_profiles.profile jsonb. Generation NEVER touches nudity controls
and NEVER emits render free text.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth.admin import require_admin
from models.trait_profile import (
    TraitProfile,
    TraitProfileGenerateRequest,
    TraitProfileGenerateResponse,
    TraitProfilePreviewRequest,
    TraitProfilePreviewResponse,
    TraitProfileRead,
    TraitProfileUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Trait Profile"])

_trait_profile_writer = None
_character_store = None
_trait_profile_store = None


def set_trait_profile_writer(writer) -> None:
    global _trait_profile_writer
    _trait_profile_writer = writer


def set_character_store(store) -> None:
    global _character_store
    _character_store = store


def set_trait_profile_store(store) -> None:
    global _trait_profile_store
    _trait_profile_store = store


def _require_writer():
    if _trait_profile_writer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trait profile writer not configured",
        )
    return _trait_profile_writer


def _require_persist_services():
    if _character_store is None or _trait_profile_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trait profile persistence not configured (Supabase DB required)",
        )
    return _character_store, _trait_profile_store


def _s(v):
    return None if v is None else str(v)


def _read(row: dict) -> TraitProfileRead:
    return TraitProfileRead(
        character_id=str(row["character_id"]),
        profile=TraitProfile.coerce(row.get("profile") or {}),
        provider=row.get("provider"),
        created_at=_s(row.get("created_at")),
        updated_at=_s(row.get("updated_at")),
    )


# ---------------------------------------------------------------------------
# Backfill response models
# ---------------------------------------------------------------------------
class TraitBackfillItem(BaseModel):
    character_id: str
    provider: Optional[str] = None
    error: Optional[str] = None


class TraitBackfillResponse(BaseModel):
    results: List[TraitBackfillItem] = Field(default_factory=list)


@router.get("/characters/{character_id}/trait-profile", response_model=TraitProfileRead)
async def get_trait_profile(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    character_store, trait_store = _require_persist_services()
    if await character_store.get(character_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    row = await trait_store.get(character_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trait profile not found")
    return _read(row)


@router.post(
    "/characters/{character_id}/trait-profile/generate",
    response_model=TraitProfileGenerateResponse,
)
async def generate_trait_profile(
    character_id: str,
    body: TraitProfileGenerateRequest,
    user: Dict[str, Any] = Depends(require_admin),
):
    writer = _require_writer()
    character_store, trait_store = _require_persist_services()

    character = await character_store.get(character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    fields = [f.value for f in body.fields] if body.fields else None  # None -> all
    values, provider = await writer.write(
        character.persona,
        fields,
        body.enrichment.model_dump(),
        character_id=character_id,
        bio=character.bio,
    )

    if body.dry_run:
        return TraitProfileGenerateResponse(
            character_id=character_id,
            profile=TraitProfile.coerce(values),
            generated=values,
            generated_fields=list(values.keys()),
            provider=provider,
            persisted=False,
        )

    row = await trait_store.apply(character_id, generated=values, provider=provider)
    merged = TraitProfile.coerce((row or {}).get("profile") or values)
    logger.info(
        f"Trait profile generated for character {character_id}: "
        f"fields={list(values.keys())} provider={provider}"
    )
    return TraitProfileGenerateResponse(
        character_id=character_id,
        profile=merged,
        generated=values,
        generated_fields=list(values.keys()),
        provider=provider,
        persisted=True,
    )


@router.put("/characters/{character_id}/trait-profile", response_model=TraitProfileRead)
async def update_trait_profile(
    character_id: str,
    body: TraitProfileUpdate,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Manual per-field edit: only fields actually sent are written, provider='manual'."""
    character_store, trait_store = _require_persist_services()
    if await character_store.get(character_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    provided = body.model_dump(exclude_unset=True)
    if not provided:
        row = await trait_store.get(character_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Trait profile not found"
            )
        return _read(row)

    # Coerce the provided partial (repair/cap/NAKED-strip), then write only the
    # provided keys (never-clobber the rest).
    dumped = TraitProfile.coerce(provided).model_dump(mode="json")
    generated = {k: dumped[k] for k in provided.keys() if k in dumped}
    row = await trait_store.apply(character_id, generated=generated, provider="manual")
    logger.info(f"Trait profile manually updated for character {character_id}: {list(generated.keys())}")
    return _read(row)


@router.post("/trait-profiles/preview", response_model=TraitProfilePreviewResponse)
async def preview_trait_profile(
    body: TraitProfilePreviewRequest,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Generate suggestions from raw options without a character row. Writes nothing."""
    writer = _require_writer()
    fields = [f.value for f in body.fields] if body.fields else None
    values, provider = await writer.write(
        body.persona,
        fields,
        body.enrichment.model_dump(),
        character_id=None,
        bio=body.backstory,
    )
    return TraitProfilePreviewResponse(
        profile=TraitProfile.coerce(values), generated=values, provider=provider
    )


@router.post("/trait-profiles/backfill", response_model=TraitBackfillResponse)
async def backfill_trait_profiles(
    user: Dict[str, Any] = Depends(require_admin),
    limit: int = Query(
        500, ge=1, le=2000, description="Max characters WITHOUT a profile to process"
    ),
):
    """
    One-time rollout: iterate characters that lack a trait profile and generate one
    for each, best-effort (a failure on one character never sinks the rest). Returns a
    per-character {provider} on success or {error} on failure.
    """
    writer = _require_writer()
    character_store, trait_store = _require_persist_services()

    results: List[TraitBackfillItem] = []
    page_size = 100
    offset = 0
    while len(results) < limit:
        page = await character_store.list(limit=page_size, offset=offset)
        if not page:
            break
        for character in page:
            if len(results) >= limit:
                break
            existing = await trait_store.get(character.id)
            if existing is not None:
                continue  # already has a profile — skip
            try:
                values, provider = await writer.write(
                    character.persona, None, {}, character_id=character.id, bio=character.bio
                )
                await trait_store.apply(character.id, generated=values, provider=provider)
                results.append(TraitBackfillItem(character_id=character.id, provider=provider))
            except Exception as e:  # noqa: BLE001 - best-effort per character
                logger.error(f"Trait backfill failed for character {character.id}: {e}")
                results.append(TraitBackfillItem(character_id=character.id, error=str(e)))
        offset += page_size

    logger.info(f"Trait profile backfill processed {len(results)} character(s)")
    return TraitBackfillResponse(results=results)
