"""
VideoBatchStore — persistence for per-character video batches and their items
(Supabase Postgres). Mirror of ``services/batch_store.py`` for the reel path.

An admin picks a character, picks N of its gallery stills, assigns each an action
(a preset from the tiered video action catalog, or a hand-written prompt), and
launches a batch. Each item animates one still into a short WAN 2.2 i2v clip;
outputs land as DRAFT chat actions the admin publishes per item.

Core design is a SUBMIT-ONLY worker + a durable reconciler: the worker submits to
RunPod and persists ``runpod_request_id`` on the item row; the
``VideoBatchReconciler`` polls RunPod status and owns persistence/retry/recovery,
so a deploy no longer strands in-flight clips.

Two read surfaces:
  * the typed ``VideoBatchItemRead`` (a subset of columns) for the admin API;
  * RAW row dicts (every column, incl. ``loras`` / ``runpod_request_id`` / ``job_id``
    / ``source_image_url``) for the reconciler + worker, which need render inputs
    and execution state the Read model deliberately omits.

Single-admin API — no owner scoping (the service-role client bypasses RLS).
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from supabase import Client

from models.video_batch import (
    VideoBatchRead,
    VideoBatchDetailRead,
    VideoBatchItemRead,
)

logger = logging.getLogger(__name__)

_BATCHES = "character_video_batches"
_ITEMS = "character_video_batch_items"

# Non-terminal batch statuses (used by the startup reconciler + the tick loop).
ACTIVE_BATCH_STATUSES = ["pending", "planning", "running"]
# Terminal item statuses the reconciler skips.
TERMINAL_ITEM_STATUSES = {"succeeded", "failed", "cancelled"}


def _row_to_batch(row: dict) -> VideoBatchRead:
    return VideoBatchRead(
        id=row["id"],
        character_id=row["character_id"],
        quality_mode=row.get("quality_mode") or "fast",
        defaults=row.get("defaults") or {},
        status=row["status"],
        progress=row.get("progress") or 0.0,
        items_total=row.get("items_total") or 0,
        items_succeeded=row.get("items_succeeded") or 0,
        items_failed=row.get("items_failed") or 0,
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_item(row: dict) -> VideoBatchItemRead:
    return VideoBatchItemRead(
        id=row["id"],
        item_index=row["item_index"],
        status=row["status"],
        source_image_id=row["source_image_id"],
        source_image_url=row.get("source_image_url"),
        action_kind=row.get("action_kind") or "preset",
        preset_id=row.get("preset_id"),
        custom_prompt=row.get("custom_prompt"),
        tier=row.get("tier"),
        motion_text=row.get("motion_text"),
        motion_label=row.get("motion_label"),
        quality_mode=row.get("quality_mode"),
        width=row.get("width"),
        height=row.get("height"),
        length=row.get("length"),
        fps=row.get("fps"),
        seed=row.get("seed"),
        attempts=row.get("attempts") or 0,
        runpod_status=row.get("runpod_status"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        video_url=row.get("video_url"),
        preview_url=row.get("preview_url"),
        character_image_id=row.get("character_image_id"),
        action_id=row.get("action_id"),
    )


class VideoBatchStore:
    def __init__(self, client: Client):
        self.client = client

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------
    async def create_batch(
        self,
        character_id: str,
        quality_mode: str,
        defaults: dict,
    ) -> VideoBatchRead:
        record = {
            "character_id": character_id,
            "quality_mode": quality_mode,
            "defaults": defaults or {},
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
        updates: Dict[str, Any] = {"status": status}
        if error is not None:
            updates["error"] = error

        def _update():
            return self.client.table(_BATCHES).update(updates).eq("id", batch_id).execute()

        await asyncio.to_thread(_update)

    async def get_batch(self, batch_id: str) -> Optional[VideoBatchRead]:
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

    async def get_batch_detail(self, batch_id: str) -> Optional[VideoBatchDetailRead]:
        batch = await self.get_batch(batch_id)
        if batch is None:
            return None
        items = await self.list_items(batch_id)
        return VideoBatchDetailRead(**batch.model_dump(), items=items)

    async def list_batches(
        self, character_id: Optional[str] = None
    ) -> List[VideoBatchRead]:
        def _select():
            q = self.client.table(_BATCHES).select("*")
            if character_id:
                q = q.eq("character_id", character_id)
            return q.order("created_at", desc=True).execute()

        res = await asyncio.to_thread(_select)
        return [_row_to_batch(r) for r in (res.data or [])]

    async def list_active_batches(self) -> List[VideoBatchRead]:
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

    async def update_batch_aggregate(self, batch_id: str) -> Optional[VideoBatchRead]:
        """Recompute counts/progress/status from the batch's items."""
        rows = await self.list_item_rows(batch_id)
        total = len(rows)
        succeeded = sum(1 for r in rows if r.get("status") == "succeeded")
        failed = sum(1 for r in rows if r.get("status") == "failed")
        cancelled = sum(1 for r in rows if r.get("status") == "cancelled")
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

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------
    async def insert_items(
        self, batch_id: str, items: List[dict]
    ) -> List[VideoBatchItemRead]:
        for it in items:
            it["batch_id"] = batch_id

        def _insert():
            return self.client.table(_ITEMS).insert(items).execute()

        res = await asyncio.to_thread(_insert)
        await self._set_items_total(batch_id, len(items))
        return sorted(
            (_row_to_item(r) for r in (res.data or [])),
            key=lambda i: i.item_index,
        )

    async def list_items(
        self, batch_id: str, statuses: Optional[List[str]] = None
    ) -> List[VideoBatchItemRead]:
        rows = await self.list_item_rows(batch_id, statuses=statuses)
        return [_row_to_item(r) for r in rows]

    async def list_item_rows(
        self, batch_id: str, statuses: Optional[List[str]] = None
    ) -> List[dict]:
        """RAW item rows (all columns) for the reconciler/worker, sorted by index."""
        def _select():
            q = self.client.table(_ITEMS).select("*").eq("batch_id", batch_id)
            if statuses:
                q = q.in_("status", statuses)
            return q.order("item_index").execute()

        res = await asyncio.to_thread(_select)
        return res.data or []

    async def get_item(
        self, item_id: str, batch_id: Optional[str] = None
    ) -> Optional[VideoBatchItemRead]:
        row = await self.get_item_row(item_id, batch_id=batch_id)
        return _row_to_item(row) if row else None

    async def get_item_row(
        self, item_id: str, batch_id: Optional[str] = None
    ) -> Optional[dict]:
        """RAW item row (all columns) for the reconciler/worker."""
        def _select():
            q = self.client.table(_ITEMS).select("*").eq("id", item_id)
            if batch_id is not None:
                q = q.eq("batch_id", batch_id)
            return q.limit(1).execute()

        res = await asyncio.to_thread(_select)
        return res.data[0] if res.data else None

    async def update_item(self, item_id: str, **fields) -> None:
        def _update():
            return self.client.table(_ITEMS).update(fields).eq("id", item_id).execute()

        await asyncio.to_thread(_update)

    async def update_item_by_runpod_id(self, runpod_request_id: str, **fields) -> None:
        def _update():
            return (
                self.client.table(_ITEMS)
                .update(fields)
                .eq("runpod_request_id", runpod_request_id)
                .execute()
            )

        await asyncio.to_thread(_update)

    async def reset_item_for_retry(self, item_id: str) -> None:
        """Reset an item to 'pending' for a retry/recovery re-enqueue.

        Clears the job link, the durable RunPod fields, and the error fields so the
        reconciler re-enqueues it cleanly. The attempt counter is LEFT UNTOUCHED so
        the retry cap still applies across dispatches (attempts accumulate)."""
        def _update():
            return (
                self.client.table(_ITEMS)
                .update({
                    "status": "pending",
                    "job_id": None,
                    "runpod_request_id": None,
                    "runpod_status": None,
                    "submitted_at": None,
                    "error_code": None,
                    "error_message": None,
                })
                .eq("id", item_id)
                .execute()
            )

        await asyncio.to_thread(_update)

    async def reset_item_for_rerun(
        self, item_id: str, *, seed: Optional[int] = None, action: Optional[dict] = None
    ) -> None:
        """Reset a succeeded/failed item to 'pending' for a single-item rerun.

        Beyond ``reset_item_for_retry`` this also clears the PUBLISH GUARDS
        (character_image_id / action_id) and the stale output URLs/hash, and resets
        the attempt counter so the retry cap applies fresh. When ``seed`` is given it
        replaces the stored seed (else the deterministic seed is kept). When
        ``action`` is given (a dict with action_kind/preset_id/custom_prompt/tier/
        motion_text/motion_label/loras) the item's action is changed on rerun."""
        updates: Dict[str, Any] = {
            "status": "pending",
            "job_id": None,
            "runpod_request_id": None,
            "runpod_status": None,
            "submitted_at": None,
            "error_code": None,
            "error_message": None,
            "character_image_id": None,
            "action_id": None,
            "video_url": None,
            "preview_url": None,
            "image_hash": None,
            "attempts": 0,
        }
        if seed is not None:
            updates["seed"] = seed
        if action:
            for key in (
                "action_kind", "preset_id", "custom_prompt", "tier",
                "motion_text", "motion_label", "loras",
            ):
                if key in action:
                    updates[key] = action[key]

        def _update():
            return self.client.table(_ITEMS).update(updates).eq("id", item_id).execute()

        await asyncio.to_thread(_update)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _set_items_total(self, batch_id: str, total: int) -> None:
        def _update():
            return (
                self.client.table(_BATCHES)
                .update({"items_total": total})
                .eq("id", batch_id)
                .execute()
            )

        await asyncio.to_thread(_update)
