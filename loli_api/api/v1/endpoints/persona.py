"""
AI persona / bio generation endpoints. Admin-only.

POST /v1/characters/{id}/persona — generate + persist the requested chat-persona
                                   fields (per-field; untouched fields preserved).
POST /v1/personas/preview        — stateless suggestions (no character row, no write).

Venice writes each free-text field in its own Candy.ai voice; results are persisted
to chat_personas + characters.chat_persona_id / welcome_message / context.
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from auth.admin import require_admin
from models.persona import (
    ChatPersonaRead,
    PersonaGenerateRequest,
    PersonaGenerateResponse,
    PersonaPreviewRequest,
    PersonaPreviewResponse,
)
from services.chat_persona_store import _PERSONA_COLS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Persona"])

_persona_writer = None
_character_store = None
_chat_persona_store = None


def set_persona_writer(writer) -> None:
    global _persona_writer
    _persona_writer = writer


def set_character_store(store) -> None:
    global _character_store
    _character_store = store


def set_chat_persona_store(store) -> None:
    global _chat_persona_store
    _chat_persona_store = store


def _require_writer():
    if _persona_writer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Persona writer not configured",
        )
    return _persona_writer


def _require_persist_services():
    if _character_store is None or _chat_persona_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Persona persistence not configured (Supabase DB required)",
        )
    return _character_store, _chat_persona_store


def _persona_read(row: dict) -> ChatPersonaRead:
    def s(v):
        return None if v is None else str(v)

    return ChatPersonaRead(
        id=row["id"],
        name=row.get("name"),
        system_prompt=row.get("system_prompt"),
        greeting_message=row.get("greeting_message"),
        tone=row.get("tone"),
        style=row.get("style"),
        boundaries=row.get("boundaries"),
        summary=row.get("summary"),
        model_id=row.get("model_id"),
        is_active=row.get("is_active"),
        created_at=s(row.get("created_at")),
        updated_at=s(row.get("updated_at")),
    )


@router.post("/characters/{character_id}/persona", response_model=PersonaGenerateResponse)
async def generate_persona(
    character_id: str,
    body: PersonaGenerateRequest,
    user: Dict[str, Any] = Depends(require_admin),
):
    writer = _require_writer()
    character_store, chat_persona_store = _require_persist_services()

    character = await character_store.get(character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    requested = [f.value for f in body.fields]
    display_name = body.name or character.name or character.persona.name

    # When a NEW chat_persona will be created, guarantee a real system_prompt is
    # generated (chat_personas.system_prompt is NOT NULL) rather than falling back to
    # the store's bare default. Only on a real (persisted) run.
    effective = list(requested)
    will_create = character.chat_persona_id is None and any(f in _PERSONA_COLS for f in requested)
    if not body.dry_run and will_create and "system_prompt" not in effective:
        effective.append("system_prompt")

    enrichment = body.enrichment.model_dump()
    values, provider = await writer.write(
        character.persona, effective, enrichment, name=display_name
    )

    if body.dry_run:
        return PersonaGenerateResponse(
            character_id=character_id,
            chat_persona_id=character.chat_persona_id,
            welcome_message=values.get("welcome_message"),
            bio=values.get("bio"),
            generated=values,
            generated_fields=list(values.keys()),
            provider=provider,
            persisted=False,
        )

    result = await chat_persona_store.apply(
        character_id,
        generated=values,
        existing_persona_id=character.chat_persona_id,
        model_id=body.model_id,
        name_default=display_name,
    )
    persona_row = result.get("persona")
    logger.info(
        f"Persona generated for character {character_id}: fields={list(values.keys())} "
        f"provider={provider} persona_id={result.get('chat_persona_id')}"
    )
    return PersonaGenerateResponse(
        character_id=character_id,
        chat_persona_id=result.get("chat_persona_id"),
        persona=_persona_read(persona_row) if persona_row else None,
        welcome_message=result.get("welcome_message"),
        bio=result.get("bio"),
        generated=values,
        generated_fields=list(values.keys()),
        provider=provider,
        persisted=True,
    )


@router.post("/personas/preview", response_model=PersonaPreviewResponse)
async def preview_persona(
    body: PersonaPreviewRequest,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Generate suggestions from raw options without a character row. Writes nothing."""
    writer = _require_writer()
    display_name = body.name or body.persona.name
    values, provider = await writer.write(
        body.persona, [f.value for f in body.fields], body.enrichment.model_dump(), name=display_name
    )
    return PersonaPreviewResponse(generated=values, provider=provider)
