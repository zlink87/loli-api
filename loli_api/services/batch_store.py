"""
BatchStore — persistence for character batches and their items (Supabase Postgres).

Batches track the async generation of gallery photos for a REAL character row
(public.characters). The in-memory Job registry stays the source of truth for
live execution; batch_items is the durable projection that the reconciler keeps
in sync and re-derives batches from on restart.

Single-admin API — no owner scoping (the service-role client bypasses RLS).
"""
import asyncio
import logging
from typing import List, Optional

from supabase import Client

from models.batch import BatchControls, BatchRead, BatchDetailRead, BatchItemRead, assemble_story

logger = logging.getLogger(__name__)

_BATCHES = "character_batches"
_ITEMS = "character_batch_items"

# Non-terminal batch statuses (used by the startup reconciler).
ACTIVE_BATCH_STATUSES = ["pending", "planning", "running"]
TERMINAL_ITEM_STATUSES = {"succeeded", "failed", "cancelled"}


def _row_to_batch(row: dict) -> BatchRead:
    return BatchRead(
        id=row["id"],
        character_id=row["character_id"],
        count=row["count"],
        controls=BatchControls(**(row.get("controls") or {})),
        likes=row.get("likes") or [],
        dislikes=row.get("dislikes") or [],
        status=row["status"],
        progress=row.get("progress") or 0.0,
        items_total=row.get("items_total") or 0,
        items_succeeded=row.get("items_succeeded") or 0,
        items_failed=row.get("items_failed") or 0,
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_item(row: dict) -> BatchItemRead:
    return BatchItemRead(
        id=row["id"],
        scene_index=row["scene_index"],
        status=row["status"],
        scene_spec=row.get("scene_spec") or {},
        job_id=row.get("job_id"),
        preview_url=row.get("preview_url"),
        image_url=row.get("image_url"),
        image_hash=row.get("image_hash"),
        seed=row.get("seed"),
        arc=row.get("arc"),
        beat=row.get("beat"),
        attempts=row.get("attempts") or 0,
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        character_image_id=row.get("character_image_id"),
    )


class BatchStore:
    def __init__(self, client: Client):
        self.client = client

    # --- batches ---
    async def create_batch(
        self,
        character_id: str,
        count: int,
        controls: BatchControls,
        likes: Optional[List[str]] = None,
        dislikes: Optional[List[str]] = None,
    ) -> BatchRead:
        record = {
            "character_id": character_id,
            "count": count,
            "controls": controls.model_dump(mode="json"),
            "likes": likes or [],
            "dislikes": dislikes or [],
            "status": "planning",
            "progress": 0.0,
            "items_total": 0,
            "items_succeeded": 0,
            "items_failed": 0,
        }

        def _insert():
            return self.client.table(_BATCHES).insert(record).execute()

        res = await asyncio.to_thread(_insert)
        return _row_to_batch(res.data[0])

    async def set_batch_status(
        self, batch_id: str, status: str, error: Optional[str] = None
    ) -> None:
        updates = {"status": status}
        if error is not None:
            updates["error"] = error

        def _update():
            return self.client.table(_BATCHES).update(updates).eq("id", batch_id).execute()

        await asyncio.to_thread(_update)

    async def get_batch(self, batch_id: str) -> Optional[BatchRead]:
        def _select():
            return (
                self.client.table(_BATCHES)
                .select("*")
                .eq("id", batch_id)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return _row_to_batch(res.data[0]) if res.data else None

    async def get_batch_detail(self, batch_id: str) -> Optional[BatchDetailRead]:
        batch = await self.get_batch(batch_id)
        if batch is None:
            return None
        items = await self.list_items(batch_id)
        # Story is derived (no new storage) from the items' scene_spec jsonb; None for
        # non-story batches.
        story = assemble_story(items)
        return BatchDetailRead(**batch.model_dump(), items=items, story=story)

    async def list_batches(self, character_id: Optional[str] = None) -> List[BatchRead]:
        def _select():
            q = self.client.table(_BATCHES).select("*")
            if character_id:
                q = q.eq("character_id", character_id)
            return q.order("created_at", desc=True).execute()

        res = await asyncio.to_thread(_select)
        return [_row_to_batch(r) for r in (res.data or [])]

    async def list_active_batches(self) -> List[BatchRead]:
        """All non-terminal batches — for the reconciler loop and startup recovery."""
        def _select():
            return (
                self.client.table(_BATCHES)
                .select("*")
                .in_("status", ACTIVE_BATCH_STATUSES)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return [_row_to_batch(r) for r in (res.data or [])]

    # --- items ---
    async def insert_items(self, batch_id: str, items: List[dict]) -> List[BatchItemRead]:
        for it in items:
            it["batch_id"] = batch_id

        def _insert():
            return self.client.table(_ITEMS).insert(items).execute()

        res = await asyncio.to_thread(_insert)
        # Also bump items_total on the batch.
        await self._set_items_total(batch_id, len(items))
        return sorted((_row_to_item(r) for r in (res.data or [])), key=lambda i: i.scene_index)

    async def list_items(
        self, batch_id: str, statuses: Optional[List[str]] = None
    ) -> List[BatchItemRead]:
        def _select():
            q = self.client.table(_ITEMS).select("*").eq("batch_id", batch_id)
            if statuses:
                q = q.in_("status", statuses)
            return q.order("scene_index").execute()

        res = await asyncio.to_thread(_select)
        return [_row_to_item(r) for r in (res.data or [])]

    async def update_item_result(self, item_id: str, **fields) -> None:
        def _update():
            return self.client.table(_ITEMS).update(fields).eq("id", item_id).execute()

        await asyncio.to_thread(_update)

    async def update_item_by_job(self, job_id: str, **fields) -> None:
        def _update():
            return self.client.table(_ITEMS).update(fields).eq("job_id", job_id).execute()

        await asyncio.to_thread(_update)

    async def reset_item_for_retry(self, item_id: str) -> None:
        def _update():
            return (
                self.client.table(_ITEMS)
                .update({"status": "pending", "job_id": None, "error_code": None, "error_message": None})
                .eq("id", item_id)
                .execute()
            )

        await asyncio.to_thread(_update)

    async def update_batch_aggregate(self, batch_id: str) -> Optional[BatchRead]:
        """Recompute counts/progress/status from the batch's items."""
        items = await self.list_items(batch_id)
        total = len(items)
        succeeded = sum(1 for i in items if i.status == "succeeded")
        failed = sum(1 for i in items if i.status == "failed")
        cancelled = sum(1 for i in items if i.status == "cancelled")
        done = succeeded + failed + cancelled
        progress = (done / total) if total else 0.0

        if total == 0:
            status = "planning"
        elif done < total:
            status = "running"
        elif cancelled and (succeeded + failed) == 0:
            status = "cancelled"
        elif failed == 0:
            status = "completed"
        elif succeeded == 0:
            status = "failed"
        else:
            status = "partial"

        updates = {
            "items_total": total,
            "items_succeeded": succeeded,
            "items_failed": failed,
            "progress": progress,
            "status": status,
        }

        def _update():
            return self.client.table(_BATCHES).update(updates).eq("id", batch_id).execute()

        res = await asyncio.to_thread(_update)
        return _row_to_batch(res.data[0]) if res.data else None

    # --- internals ---
    async def _get_item(self, item_id: str) -> Optional[dict]:
        def _select():
            return self.client.table(_ITEMS).select("*").eq("id", item_id).limit(1).execute()

        res = await asyncio.to_thread(_select)
        return res.data[0] if res.data else None

    async def _set_items_total(self, batch_id: str, total: int) -> None:
        def _update():
            return self.client.table(_BATCHES).update({"items_total": total}).eq("id", batch_id).execute()

        await asyncio.to_thread(_update)
