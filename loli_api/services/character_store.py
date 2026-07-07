"""
CharacterStore — CRUD for characters, backed by the REAL product table
(public.characters) that the chat app reads.

The persona is stored in the table's flat typed columns (ethnicity, age,
hair_style, ...) and rebuilt into PersonaOptions on read. The hero photo is
written to profile_image_url / avatar_image_url / chat_avatar_url, and the
free-text bio maps to the `context` column. New characters are created with
status='draft'; the admin publishes them from the existing admin UI.

Single-admin API — no owner scoping (the service-role client bypasses RLS).
"""
import asyncio
import logging
from typing import List, Optional

from supabase import Client

from models.requests import PersonaOptions
from models.character import CharacterCreate, CharacterUpdate, CharacterRead

logger = logging.getLogger(__name__)

_TABLE = "characters"

# Status a batch-created character starts in; the admin flips it to the
# chat-visible status from the admin UI after reviewing the generated photos.
DRAFT_STATUS = "draft"


def _persona_to_columns(persona: PersonaOptions) -> dict:
    """Flatten PersonaOptions into the characters table's typed columns."""
    dump = persona.model_dump(mode="json")
    return {
        "style": dump["style"],
        "ethnicity": dump["ethnicity"],
        "age": dump["age"],
        "hair_style": dump["hairStyle"],
        "hair_color": dump["hairColor"],
        "eye_color": dump["eyeColor"],
        "body_type": dump["bodyType"],
        "breast_size": dump["breastSize"],
        "personality": dump.get("personality"),
        "relationship": dump.get("relationship"),
        "occupation": dump.get("occupation"),
        "kinks": dump.get("kinks") or [],
        "voice": dump.get("voice"),
    }


def _row_to_persona(row: dict) -> PersonaOptions:
    """Rebuild PersonaOptions from the flat characters columns."""
    return PersonaOptions(
        style=row["style"],
        ethnicity=row["ethnicity"],
        age=row["age"],
        hairStyle=row["hair_style"],
        hairColor=row["hair_color"],
        eyeColor=row["eye_color"],
        bodyType=row["body_type"],
        breastSize=row["breast_size"],
        name=row["name"],
        personality=row.get("personality"),
        relationship=row.get("relationship"),
        occupation=row.get("occupation"),
        kinks=row.get("kinks") or None,
        voice=row.get("voice"),
    )


def _row_to_character(row: dict) -> CharacterRead:
    return CharacterRead(
        id=row["id"],
        name=row["name"],
        persona=_row_to_persona(row),
        hero_image_url=row.get("profile_image_url") or "",
        bio=row.get("context"),
        status=row.get("status") or DRAFT_STATUS,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class CharacterStore:
    def __init__(self, client: Client):
        self.client = client

    async def create(self, data: CharacterCreate) -> CharacterRead:
        record = {
            "name": data.name or data.persona.name,
            **_persona_to_columns(data.persona),
            "context": data.bio,
            # The hero photo backs every image the chat app shows for the character.
            "profile_image_url": data.hero_image_url,
            "avatar_image_url": data.hero_image_url,
            "chat_avatar_url": data.hero_image_url,
            "status": DRAFT_STATUS,
        }

        def _insert():
            return self.client.table(_TABLE).insert(record).execute()

        res = await asyncio.to_thread(_insert)
        return _row_to_character(res.data[0])

    async def get(self, character_id: str) -> Optional[CharacterRead]:
        def _select():
            return (
                self.client.table(_TABLE)
                .select("*")
                .eq("id", character_id)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        if not res.data:
            return None
        return _row_to_character(res.data[0])

    async def list(self, limit: int = 50, offset: int = 0) -> List[CharacterRead]:
        def _select():
            return (
                self.client.table(_TABLE)
                .select("*")
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return [_row_to_character(r) for r in (res.data or [])]

    async def update(
        self, character_id: str, patch: CharacterUpdate
    ) -> Optional[CharacterRead]:
        updates: dict = {}
        if patch.persona is not None:
            updates.update(_persona_to_columns(patch.persona))
            updates["name"] = patch.name or patch.persona.name
        if patch.hero_image_url is not None:
            updates["profile_image_url"] = patch.hero_image_url
            updates["avatar_image_url"] = patch.hero_image_url
            updates["chat_avatar_url"] = patch.hero_image_url
        if patch.bio is not None:
            updates["context"] = patch.bio
        if patch.name is not None:
            updates["name"] = patch.name

        if not updates:
            return await self.get(character_id)

        def _update():
            return (
                self.client.table(_TABLE)
                .update(updates)
                .eq("id", character_id)
                .execute()
            )

        res = await asyncio.to_thread(_update)
        if not res.data:
            return None
        return _row_to_character(res.data[0])

    async def delete(self, character_id: str) -> bool:
        """
        Delete a character FK-safely: quick actions -> gallery images -> the row.
        The product tables' cascade behavior is owned by the chat app's DDL, so
        we don't rely on it. character_batches cascades via our own migration.
        """

        def _delete_actions():
            return (
                self.client.table("chat_persona_actions")
                .delete()
                .eq("character_id", character_id)
                .execute()
            )

        def _delete_images():
            return (
                self.client.table("character_images")
                .delete()
                .eq("character_id", character_id)
                .execute()
            )

        def _delete_character():
            return (
                self.client.table(_TABLE)
                .delete()
                .eq("id", character_id)
                .execute()
            )

        await asyncio.to_thread(_delete_actions)
        await asyncio.to_thread(_delete_images)
        res = await asyncio.to_thread(_delete_character)
        return bool(res.data)
