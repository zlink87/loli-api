"""
Character management endpoints (batch generation). Admin-only.

POST/GET/PATCH/DELETE /v1/characters — real rows in the product `characters`
table (created as status='draft'), reusable across batches.

Photo management (the admin gallery):
  GET    /v1/characters/{id}/images            — list the character's photos
  DELETE /v1/characters/{id}/images/{imageId}  — remove a photo (+ its quick action)
  PUT    /v1/characters/{id}/avatar            — make an existing photo the avatar
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth.admin import require_admin
from models.character import (
    CharacterCreate,
    CharacterUpdate,
    CharacterRead,
    BulkCharacterCreate,
    BulkCharacterResponse,
    BulkCharacterItemResult,
    BulkCharacterError,
)
from models.persona import PersonaEnrichment, PersonaField
from services.character_image_store import action_keywords

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/characters", tags=["Characters"])

_character_store = None
_character_image_store = None
_persona_writer = None
_chat_persona_store = None
_trait_profile_writer = None
_trait_profile_store = None
# Optional async callable (character, user_id) -> nude-base row | None, wired in
# router.configure_services to nude_base.submit_nude_base_for_new_character. Used only
# to auto-submit a nude base on creation (Part 3); None (not wired) degrades to a no-op.
_nude_base_submitter = None


def set_character_store(store) -> None:
    global _character_store
    _character_store = store


def set_nude_base_submitter(submitter) -> None:
    """Set the (optional) nude-base auto-submitter used on character creation (Part 3)."""
    global _nude_base_submitter
    _nude_base_submitter = submitter


def set_character_image_store(store) -> None:
    global _character_image_store
    _character_image_store = store


def set_persona_writer(writer) -> None:
    global _persona_writer
    _persona_writer = writer


def set_chat_persona_store(store) -> None:
    global _chat_persona_store
    _chat_persona_store = store


def set_trait_profile_writer(writer) -> None:
    global _trait_profile_writer
    _trait_profile_writer = writer


def set_trait_profile_store(store) -> None:
    global _trait_profile_store
    _trait_profile_store = store


def get_character_store():
    if _character_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Character store not configured (Supabase DB required)",
        )
    return _character_store


def get_character_image_store():
    if _character_image_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Character image store not configured (Supabase DB required)",
        )
    return _character_image_store


class CharacterImageRead(BaseModel):
    """One gallery photo as the admin app consumes it."""
    id: str
    imageUrl: Optional[str] = None
    imageType: Optional[str] = None
    isAvatar: bool = False
    outfit: Optional[str] = None
    prompt: Optional[str] = None
    createdAt: Optional[str] = None


class AvatarSet(BaseModel):
    """Body for PUT /v1/characters/{id}/avatar."""
    imageId: str = Field(..., description="character_images.id of an existing photo")


class ImageSave(BaseModel):
    """
    Body for POST /v1/characters/{id}/images — the admin "Save" button.

    Generation/edit jobs only upload to storage and return a preview URL;
    NOTHING is attached to the character until the admin explicitly saves it
    with this endpoint. (Batches are the deliberate exception: they persist
    every succeeded item automatically.)
    """
    imageUrl: str = Field(..., description="The job's preview/storage URL to attach")
    prompt: Optional[str] = Field(default=None, description="Prompt used (provenance)")
    seed: Optional[int] = Field(default=None, description="Seed used (provenance)")
    outfit: Optional[str] = Field(default=None, description="Outfit value, if an outfit edit")
    label: Optional[str] = Field(
        default=None,
        max_length=40,
        description="When set, also creates a chat quick action with this caption",
    )
    setAsAvatar: bool = Field(
        default=False, description="Also make this photo the character's avatar"
    )


def _image_read(row: dict) -> CharacterImageRead:
    return CharacterImageRead(
        id=row["id"],
        imageUrl=row.get("image_url"),
        imageType=row.get("image_type"),
        isAvatar=bool(row.get("is_avatar")),
        outfit=row.get("outfit"),
        prompt=row.get("prompt"),
        createdAt=row.get("created_at"),
    )


# Default field set for CharacterCreate.generate_persona: every generatable field
# except 'name' (already set via persona.name at creation time).
_DEFAULT_PERSONA_FIELDS = [f for f in PersonaField if f != PersonaField.name]


async def _generate_traits_best_effort(character: CharacterRead) -> None:
    """
    Generate + persist the character's trait profile (WS-B). Best-effort: a failure is
    logged and swallowed so it NEVER fails character creation (covers /characters/bulk).
    Writes to character_trait_profiles only, so the character row is unaffected.
    """
    if _trait_profile_writer is None or _trait_profile_store is None:
        logger.warning(
            "generate_traits requested but trait services not configured — skipping "
            f"(character {character.id})"
        )
        return
    try:
        values, provider = await _trait_profile_writer.write(
            character.persona, None, {}, character_id=character.id, bio=character.bio
        )
        await _trait_profile_store.apply(character.id, generated=values, provider=provider)
        logger.info(
            f"Trait profile auto-generated on creation for character {character.id}: "
            f"provider={provider}"
        )
    except Exception as e:  # noqa: BLE001 - traits must never fail creation
        logger.error(
            f"generate_traits failed for character {character.id}; creation still "
            f"succeeded: {e}"
        )


async def _submit_nude_base_best_effort(character: CharacterRead, user_id: str) -> None:
    """
    Auto-submit the character's identity-locked nude base on creation (Part 3), reusing
    the SAME t2i submit path as POST /v1/characters/{id}/nude-base via the wired
    submitter. Best-effort: a missing submitter (nude-base services not configured / the
    T2I flag off) is a silent no-op, and ANY submission failure is logged and swallowed
    so it NEVER fails character creation (covers /characters/bulk). Writes only to the
    nude-base store/queue, so the character row is unaffected.
    """
    if _nude_base_submitter is None:
        return
    try:
        nb = await _nude_base_submitter(character, user_id)
        if nb is not None:
            logger.info(
                f"Nude base auto-submitted on creation for character {character.id}"
            )
    except Exception as e:  # noqa: BLE001 - nude base must never fail creation
        logger.error(
            f"Auto nude-base submission failed for character {character.id}; creation "
            f"still succeeded: {e}"
        )


async def _create_character_with_persona(
    body: CharacterCreate, user_id: str = "admin"
) -> CharacterRead:
    """
    Create one character row and, best-effort, generate + persist its chat persona
    (when body.generate_persona is set), its trait profile (when body.generate_traits
    is set — default on), and its nude base (when body.generate_nude_base is set —
    default on, and only when the nude-base services are configured). Shared by POST
    /v1/characters (single) and POST /v1/characters/bulk so both behave identically.
    All generation blocks are best-effort: a failure is logged and creation still
    succeeds (it never raises). ``user_id`` is the acting admin, recorded on the
    nude-base job.
    """
    store = get_character_store()
    character = await store.create(body)

    if body.generate_persona:
        if _persona_writer is None or _chat_persona_store is None:
            logger.warning(
                "generate_persona requested but persona services not configured — skipping "
                f"(character {character.id})"
            )
        else:
            try:
                if body.persona_fields is not None:
                    effective_fields = list(body.persona_fields)
                else:
                    effective_fields = list(_DEFAULT_PERSONA_FIELDS)
                    if body.bio and body.bio.strip():
                        # A bio typed on this same request is never silently overwritten by
                        # generation — regenerating it too requires an explicit persona_fields.
                        effective_fields = [f for f in effective_fields if f != PersonaField.bio]

                if effective_fields:
                    enrichment = (body.persona_enrichment or PersonaEnrichment()).model_dump()
                    display_name = character.name or character.persona.name

                    values, provider = await _persona_writer.write(
                        character.persona, effective_fields, enrichment, name=display_name
                    )
                    await _chat_persona_store.apply(
                        character.id,
                        generated=values,
                        existing_persona_id=None,
                        model_id=body.persona_model_id,
                        name_default=display_name,
                    )
                    logger.info(
                        f"Persona auto-generated on creation for character {character.id}: "
                        f"fields={list(values.keys())} provider={provider}"
                    )
                    # chat_persona_store.apply() writes characters.chat_persona_id (and
                    # possibly welcome_message/context) via its own path, so the object from
                    # store.create() above is now stale — refresh before returning it.
                    refreshed = await store.get(character.id)
                    if refreshed is not None:
                        character = refreshed
            except Exception as e:
                logger.error(
                    f"generate_persona failed for character {character.id}; creation still "
                    f"succeeded: {e}"
                )

    # Trait profile is opt-OUT (default on) and independent of the persona block.
    if body.generate_traits:
        await _generate_traits_best_effort(character)

    # Nude base is opt-OUT (default on), best-effort, and independent of the blocks
    # above. Only submits when the nude-base services are configured AND the T2I flag
    # is on (both checked inside the wired submitter); a failure never fails creation.
    if body.generate_nude_base:
        await _submit_nude_base_best_effort(character, user_id)

    return character


@router.post("", response_model=CharacterRead, status_code=status.HTTP_201_CREATED)
async def create_character(
    body: CharacterCreate,
    user: Dict[str, Any] = Depends(require_admin),
):
    return await _create_character_with_persona(body, user.get("sub", "admin"))


@router.post("/bulk", response_model=BulkCharacterResponse)
async def create_characters_bulk(
    body: BulkCharacterCreate,
    user: Dict[str, Any] = Depends(require_admin),
):
    """
    Save many characters at once (Batch Character Creation "Save all").

    Each item runs the SAME logic as POST /v1/characters (including the optional
    generate_persona path). Items succeed/fail INDEPENDENTLY — a bad item is reported as
    a per-item failure without rolling back the good ones — and results are returned in
    request order. Configuration errors (no DB) 503 the whole request, matching single.
    """
    # Fail the whole request up-front (503) if the store isn't configured — nothing could
    # be saved anyway. Done before the loop so it isn't swallowed as a per-item failure.
    get_character_store()

    user_id = user.get("sub", "admin")
    results = []
    for index, item in enumerate(body.items):
        try:
            character = await _create_character_with_persona(item, user_id)
            results.append(
                BulkCharacterItemResult(index=index, status="created", character=character)
            )
        except HTTPException:
            # Config/availability errors (e.g. store 503) fail the whole request.
            raise
        except Exception as e:  # noqa: BLE001 - a bad item must not sink the good ones
            logger.error(f"Bulk character save failed for item {index}: {e}")
            results.append(
                BulkCharacterItemResult(
                    index=index,
                    status="failed",
                    error=BulkCharacterError(code="CREATE_ERROR", message=str(e)),
                )
            )

    created = sum(1 for r in results if r.status == "created")
    logger.info(
        f"Bulk character save: {created}/{len(results)} created "
        f"({len(results) - created} failed)"
    )
    return BulkCharacterResponse(results=results)


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


# ---------------------------------------------------------------------------
# Photo management (admin gallery)
# ---------------------------------------------------------------------------
@router.post(
    "/{character_id}/images",
    response_model=CharacterImageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save an image to the character's gallery (the admin Save button)",
    description=(
        "Attaches a generated/edited image (by its preview/storage URL) to the "
        "character as a character_images row. Optionally creates a chat quick "
        "action (label) and/or sets the photo as the avatar. Images are NOT "
        "attached automatically by generate/edit jobs — only by this call "
        "(batches remain the auto-persisting exception)."
    ),
)
async def save_character_image(
    character_id: str,
    body: ImageSave,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_store()
    images = get_character_image_store()
    if await store.get(character_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    image_id = await images.create_image(
        character_id,
        image_url=body.imageUrl,
        prompt=body.prompt,
        seed=body.seed,
        outfit=body.outfit,
    )
    if body.label:
        await images.create_action(
            character_id,
            character_image_id=image_id,
            media_url=body.imageUrl,
            label=body.label,
            trigger_keywords=action_keywords(None, extra_texts=[body.label, body.outfit]),
        )
    if body.setAsAvatar:
        await images.set_avatar(character_id, image_id)

    logger.info(
        f"Saved image to character {character_id} -> {image_id}"
        f"{' (+action)' if body.label else ''}{' (+avatar)' if body.setAsAvatar else ''}"
    )
    row = await images.get_image(image_id)
    return _image_read(row)


@router.get("/{character_id}/images", response_model=List[CharacterImageRead])
async def list_character_images(
    character_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    """All of the character's photos (gallery + avatar + video rows), newest first."""
    images = get_character_image_store()
    rows = await images.list_character_images(character_id)
    return [_image_read(r) for r in rows]


@router.delete(
    "/{character_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a photo from the character's gallery",
    description=(
        "Removes the character_images row AND its chat quick action; derived "
        "video rows are detached (source_image_id nulled), not deleted. The "
        "storage object is kept (public URLs may be cached). Deleting the "
        "current avatar does NOT clear the character's avatar URLs — set a new "
        "avatar via PUT /avatar."
    ),
)
async def delete_character_image(
    character_id: str,
    image_id: str,
    user: Dict[str, Any] = Depends(require_admin),
):
    images = get_character_image_store()
    deleted = await images.delete_image(character_id, image_id)
    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found for this character",
        )
    logger.info(f"Deleted character image {image_id} (character {character_id})")
    return None


@router.put(
    "/{character_id}/avatar",
    response_model=CharacterRead,
    summary="Make an existing photo the character's avatar",
    description=(
        "Points profile_image_url / avatar_image_url / chat_avatar_url at the "
        "chosen photo and maintains the is_avatar flag on character_images."
    ),
)
async def set_character_avatar(
    character_id: str,
    body: AvatarSet,
    user: Dict[str, Any] = Depends(require_admin),
):
    store = get_character_store()
    images = get_character_image_store()
    if await store.get(character_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    url = await images.set_avatar(character_id, body.imageId)
    if url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found for this character",
        )
    logger.info(f"Set avatar for character {character_id} -> image {body.imageId}")
    character = await store.get(character_id)
    if character is None:  # deleted concurrently
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return character
