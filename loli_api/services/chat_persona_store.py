"""
ChatPersonaStore — persists AI-generated persona/bio fields to the product schema.

Writes the free-text fields to `public.chat_personas`, links the row via
`characters.chat_persona_id`, and writes `characters.welcome_message` + `context`
(bio). Uses the service-role Supabase client (RLS bypassed), same as CharacterStore.

Per-field / never-clobber: only the columns the caller actually generated are put in
the UPDATE payload, so a field the caller did not request is never overwritten
(same conditional-`updates` technique as CharacterStore.update). Idempotent: reusing
an existing `characters.chat_persona_id` updates that row in place — no duplicates.
"""
import asyncio
import logging
from typing import Dict, Optional

from supabase import Client

logger = logging.getLogger(__name__)

_PERSONAS_TABLE = "chat_personas"
_CHARACTERS_TABLE = "characters"

# Generated-field keys that map to chat_personas columns (same names).
_PERSONA_COLS = {
    "system_prompt",
    "greeting_message",
    "tone",
    "style",
    "boundaries",
    "summary",
    "name",
}
# Generated-field key -> characters column.
_CHARACTER_FIELD_TO_COL = {
    "bio": "context",
    "welcome_message": "welcome_message",
}

# Defensive default so an INSERT never violates chat_personas.system_prompt NOT NULL.
# The endpoint is expected to generate a real system_prompt when creating a persona;
# this only guards against a caller reaching the store without one.
_DEFAULT_SYSTEM_PROMPT = (
    "She is a warm, engaging companion who loves easy, playful conversation "
    "and enjoys getting to know the person she is talking to."
)


class ChatPersonaStore:
    def __init__(self, client: Client):
        self.client = client

    async def get_persona(self, persona_id: str) -> Optional[dict]:
        def _select():
            return (
                self.client.table(_PERSONAS_TABLE)
                .select("*")
                .eq("id", persona_id)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return res.data[0] if res.data else None

    async def apply(
        self,
        character_id: str,
        *,
        generated: Dict[str, str],
        existing_persona_id: Optional[str] = None,
        model_id: Optional[str] = None,
        name_default: Optional[str] = None,
    ) -> dict:
        """Persist the generated fields. Returns {chat_persona_id, persona, welcome_message, bio}."""
        persona_payload = {k: v for k, v in generated.items() if k in _PERSONA_COLS}
        char_updates: Dict[str, str] = {}
        for key, col in _CHARACTER_FIELD_TO_COL.items():
            if key in generated:
                char_updates[col] = generated[key]

        persona_id = existing_persona_id
        created = False

        if existing_persona_id:
            payload = dict(persona_payload)
            if model_id:
                payload["model_id"] = model_id
            if payload:
                await asyncio.to_thread(
                    lambda: self.client.table(_PERSONAS_TABLE)
                    .update(payload)
                    .eq("id", existing_persona_id)
                    .execute()
                )
        elif persona_payload or model_id:
            insert = dict(persona_payload)
            if not insert.get("system_prompt"):
                logger.warning(
                    "Creating chat_persona without a generated system_prompt; "
                    "inserting a safe default to satisfy NOT NULL."
                )
                insert["system_prompt"] = _DEFAULT_SYSTEM_PROMPT
            if not insert.get("name") and name_default:
                insert["name"] = name_default
            if model_id:
                insert["model_id"] = model_id
            res = await asyncio.to_thread(
                lambda: self.client.table(_PERSONAS_TABLE).insert(insert).execute()
            )
            persona_id = res.data[0]["id"]
            created = True

        if created and persona_id:
            char_updates["chat_persona_id"] = persona_id

        if char_updates:
            await asyncio.to_thread(
                lambda: self.client.table(_CHARACTERS_TABLE)
                .update(char_updates)
                .eq("id", character_id)
                .execute()
            )

        persona_row = await self.get_persona(persona_id) if persona_id else None
        return {
            "chat_persona_id": persona_id,
            "persona": persona_row,
            "welcome_message": char_updates.get("welcome_message"),
            "bio": char_updates.get("context"),
        }
