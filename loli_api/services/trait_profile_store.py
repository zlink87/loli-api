"""
TraitProfileStore — persists a character's trait profile to character_trait_profiles.

One row per character (character_id UNIQUE, migration 0004): the whole
TraitProfile lives in the `profile` jsonb column, with a `provider` label. Uses
the service-role Supabase client (RLS bypassed), same as CharacterStore.

Per-field / never-clobber: `apply` merges ONLY the generated keys into the existing
`profile` jsonb (read-merge-write), so a field the caller did not (re)generate is
preserved — the jsonb-blob analogue of ChatPersonaStore's conditional-column
UPDATE. Idempotent: an existing row is updated in place (no duplicates).

`apply` ALSO flattens the public profile-card fields (short_description,
display_occupation, display_personality, display_hobbies, language) + zodiac from the
merged profile into the FE-readable character_profile_cards table (migration 0005).
That card write is BEST-EFFORT: a failure is logged but never fails the profile write.
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from supabase import Client

logger = logging.getLogger(__name__)

_TABLE = "character_trait_profiles"
_CARD_TABLE = "character_profile_cards"


def _card_payload(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten the public-card columns out of the merged profile jsonb."""
    def _lst(v):
        return [str(x) for x in v] if isinstance(v, list) else []

    return {
        "short_description": profile.get("short_description"),
        "display_occupation": profile.get("display_occupation"),
        "display_personality": _lst(profile.get("display_personality")),
        "display_hobbies": _lst(profile.get("display_hobbies")),
        "language": profile.get("language") or "English",
        # zodiac is mirrored from the profile onto the card.
        "zodiac": profile.get("zodiac"),
    }


class TraitProfileStore:
    def __init__(self, client: Client):
        self.client = client

    async def get(self, character_id: str) -> Optional[dict]:
        """The character's trait-profile row (or None). Callers coerce `profile`."""
        def _select():
            return (
                self.client.table(_TABLE)
                .select("*")
                .eq("character_id", character_id)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return res.data[0] if res.data else None

    async def apply(
        self,
        character_id: str,
        *,
        generated: Dict[str, Any],
        provider: Optional[str] = None,
    ) -> dict:
        """
        Merge the generated fields into the character's profile jsonb (never-clobber:
        only these keys are overwritten; untouched keys are preserved) and record the
        provider. Inserts the row on first write, updates in place thereafter. Returns
        the persisted row.
        """
        existing = await self.get(character_id)
        merged: Dict[str, Any] = dict((existing or {}).get("profile") or {})
        for key, value in (generated or {}).items():
            merged[key] = value

        if existing:
            payload: Dict[str, Any] = {"profile": merged}
            if provider is not None:
                payload["provider"] = provider

            def _update():
                return (
                    self.client.table(_TABLE)
                    .update(payload)
                    .eq("character_id", character_id)
                    .execute()
                )

            await asyncio.to_thread(_update)
        else:
            record: Dict[str, Any] = {"character_id": character_id, "profile": merged}
            if provider is not None:
                record["provider"] = provider

            def _insert():
                return self.client.table(_TABLE).insert(record).execute()

            await asyncio.to_thread(_insert)

        # Best-effort: mirror the public card fields into the FE-readable card table.
        await self._upsert_card(character_id, merged)

        row = await self.get(character_id)
        return row if row is not None else {
            "character_id": character_id,
            "profile": merged,
            "provider": provider,
        }

    async def _get_card(self, character_id: str) -> Optional[dict]:
        def _select():
            return (
                self.client.table(_CARD_TABLE)
                .select("character_id")
                .eq("character_id", character_id)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return res.data[0] if res.data else None

    async def _upsert_card(self, character_id: str, merged: Dict[str, Any]) -> None:
        """
        Flatten the merged profile's public-card fields into character_profile_cards
        (never-clobber: `merged` already carries untouched fields forward). BEST-EFFORT:
        a failure (e.g. the card table not yet migrated) is logged, never raised — the
        profile write must not depend on the derived card.
        """
        try:
            payload = _card_payload(merged)
            existing = await self._get_card(character_id)
            if existing:
                def _update():
                    return (
                        self.client.table(_CARD_TABLE)
                        .update(payload)
                        .eq("character_id", character_id)
                        .execute()
                    )

                await asyncio.to_thread(_update)
            else:
                record = {"character_id": character_id, **payload}

                def _insert():
                    return self.client.table(_CARD_TABLE).insert(record).execute()

                await asyncio.to_thread(_insert)
        except Exception as e:  # noqa: BLE001 - card is derived; never fail the profile write
            logger.warning(
                f"Profile-card write failed for character {character_id} "
                f"(trait profile still saved): {e}"
            )
