"""
NudeBaseStore — persistence for per-character nude bases (Supabase Postgres).

A nude base is ONE identity-locked nude/underwear render of a character, generated
once from the clothed hero photo via the existing outfit-edit machinery. Batches
then start each scene's edit chain from it so dressing is ADDITIVE (clothes onto
bare skin) instead of subtractive (swapping one outfit for another, which lets the
hero's original garment ghost through). See migration 0003_character_nude_bases.sql.

This is a loli-api-OWNED table (like character_batches), NOT the product schema —
the nude base is an internal asset, never a gallery photo or a chat quick action.

Single-admin API — no owner scoping (the service-role client bypasses RLS).
"""
import asyncio
import logging
from typing import Optional

from supabase import Client

from models.nude_base import NudeBaseRead

logger = logging.getLogger(__name__)

_TABLE = "character_nude_bases"

# The status a succeeded base carries — its image_url is the additive-dressing source.
SUCCEEDED_STATUS = "succeeded"


def _row_to_nude_base(row: dict) -> NudeBaseRead:
    return NudeBaseRead(
        id=row["id"],
        character_id=row["character_id"],
        source_image_url=row.get("source_image_url"),
        image_url=row.get("image_url"),
        image_hash=row.get("image_hash"),
        job_id=row.get("job_id"),
        status=row.get("status") or "pending",
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class NudeBaseStore:
    def __init__(self, client: Client):
        self.client = client

    async def create(
        self,
        character_id: str,
        *,
        job_id: str,
        source_image_url: Optional[str] = None,
    ) -> NudeBaseRead:
        """Insert a fresh 'pending' base row for an in-flight generation job."""
        record = {
            "character_id": character_id,
            "job_id": job_id,
            "source_image_url": source_image_url,
            "status": "pending",
        }

        def _insert():
            return self.client.table(_TABLE).insert(record).execute()

        res = await asyncio.to_thread(_insert)
        return _row_to_nude_base(res.data[0])

    async def get_latest(self, character_id: str) -> Optional[NudeBaseRead]:
        """Most recent base row of ANY status (for status display + reconcile-on-read)."""
        def _select():
            return (
                self.client.table(_TABLE)
                .select("*")
                .eq("character_id", character_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return _row_to_nude_base(res.data[0]) if res.data else None

    async def get_active_url(self, character_id: str) -> Optional[str]:
        """
        The additive-dressing source: image_url of the latest SUCCEEDED base, or None.

        None means "no usable nude base yet" — the batch engine then falls back to the
        clothed hero photo (unchanged legacy behavior). A pending regeneration does NOT
        clear the current succeeded one, so there is never a gap.
        """
        def _select():
            return (
                self.client.table(_TABLE)
                .select("image_url")
                .eq("character_id", character_id)
                .eq("status", SUCCEEDED_STATUS)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        if not res.data:
            return None
        return res.data[0].get("image_url")

    async def update_status(
        self,
        nude_base_id: str,
        status: str,
        *,
        image_url: Optional[str] = None,
        image_hash: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[NudeBaseRead]:
        """Finalize a base row (succeeded -> image_url set; failed -> error set)."""
        updates: dict = {"status": status}
        if image_url is not None:
            updates["image_url"] = image_url
        if image_hash is not None:
            updates["image_hash"] = image_hash
        if error is not None:
            updates["error"] = error

        def _update():
            return self.client.table(_TABLE).update(updates).eq("id", nude_base_id).execute()

        res = await asyncio.to_thread(_update)
        return _row_to_nude_base(res.data[0]) if res.data else None
