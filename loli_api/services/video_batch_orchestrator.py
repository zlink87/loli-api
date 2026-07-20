"""
Video-batch orchestrator + reconciler (submit-only worker + durable reconciler).

``VideoBatchOrchestrator.launch_batch`` validates the character + every chosen
still, resolves each item's action (preset -> catalog snapshot; custom -> Venice
MotionWriter interpretation AT LAUNCH so the worker/reconciler stay network-free),
gates the explicit tier, resolves per-item dims/length/fps/seed, persists the batch
+ items, and returns an immediate estimate. Real (non-dry-run) batches flip to
'running'; the reconciler then drives all enqueueing + result collection.

``VideoBatchReconciler`` is a SEPARATE background task from the image
``BatchReconciler`` (the image path is untouched). Because the worker is submit-only
and persists ``runpod_request_id`` on the item, the reconciler owns the whole
lifecycle by polling RunPod directly:

  * Startup recovery: an in-flight item (queued/running) WITH a runpod_request_id is
    re-polled — a clip that COMPLETED while the API was down is recovered from the
    /status doc (RunPod holds the output within TTL); one WITHOUT a runpod_request_id
    was never submitted, so it is reset to pending.
  * Tick: poll each in-flight item -> COMPLETED publishes the reel (character_images
    video row + a DRAFT chat_persona_actions row, guards set BEFORE the terminal
    status) then marks it succeeded; FAILED/TIMED_OUT retries up to the attempt cap
    (attempts consumed ONLY by genuine RunPod failures, never by a deploy); pending
    items are enqueued up to the in-flight window; the aggregate is recomputed.
"""
import asyncio
import base64
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from models.batch import SeedStrategy
from models.video_batch import (
    VideoBatchCreate,
    VideoBatchRead,
    VideoBatchEstimate,
    VideoBatchItemRerun,
)
from models.requests import (
    VIDEO_DEFAULT_WIDTH,
    VIDEO_DEFAULT_HEIGHT,
    VIDEO_DEFAULT_LENGTH,
    VIDEO_DEFAULT_FPS,
)
from services.video_action_catalog import get_preset
from services.video_workflow import resolve_item_loras
from services.character_image_store import action_keywords
from services.video_batch_store import VideoBatchStore, TERMINAL_ITEM_STATUSES
from services.runpod_client import RunPodServerlessClient
from workers.video_batch_worker import VideoBatchJobRequest, VIDEO_BATCH_JOB_TYPE

logger = logging.getLogger(__name__)

STORAGE_FOLDER = "character_video_batches"

# Single-admin API: internal jobs are owned by this constant identity.
VIDEO_BATCH_JOB_OWNER = "video-batch-admin"

# Rough per-clip wall-clock (seconds) for the estimate, by resolved quality mode.
_EST_SECONDS_FAST = 150
_EST_SECONDS_MAX = 400


class CharacterNotFound(Exception):
    """Raised when launch_batch targets a character that does not exist."""


class VideoBatchValidationError(Exception):
    """A launch/rerun validation failure with an HTTP status hint for the endpoint."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _val(v: Any) -> Optional[str]:
    """Enum-or-str value accessor (str-Enum members and raw strings both work)."""
    if v is None:
        return None
    return getattr(v, "value", v)


def _resolve_item_seed(
    strategy: Any, base_seed: Optional[int], item_index: int, override: Optional[int]
) -> Optional[int]:
    """Per-item seed from the batch seed strategy (mirrors scene_mapper.resolve_seed)."""
    if override is not None:
        return override
    strat = _val(strategy)
    if strat == SeedStrategy.RANDOM.value or base_seed is None:
        return None
    if strat == SeedStrategy.FIXED.value:
        return base_seed
    # per_item
    return ((base_seed + item_index * 7919) % 1_000_000_000) or 1


def compute_estimate(
    quality_mode: str, item_count: int, settings
) -> VideoBatchEstimate:
    """Advisory cost/time preview — one GPU job per item, bounded by the in-flight window."""
    per_clip = _EST_SECONDS_MAX if _val(quality_mode) == "max" else _EST_SECONDS_FAST
    inflight = max(1, int(getattr(settings, "VIDEO_BATCH_MAX_INFLIGHT", 2)))
    base_seconds = item_count * per_clip / inflight
    rate = float(getattr(settings, "RUNPOD_GPU_USD_PER_SECOND", 0.0) or 0.0)
    return VideoBatchEstimate(
        items_total=item_count,
        est_seconds_min=int(base_seconds),
        est_seconds_max=int(base_seconds * 1.8),
        est_cost_usd=(round(item_count * per_clip * rate, 4) if rate > 0 else None),
    )


class VideoBatchOrchestrator:
    def __init__(
        self,
        job_manager,
        character_store,
        video_batch_store: VideoBatchStore,
        character_image_store,
        motion_writer,
        settings,
        video_runpod_client=None,
        lightning_available: Optional[bool] = None,
    ):
        self.job_manager = job_manager
        self.character_store = character_store
        self.video_batch_store = video_batch_store
        self.character_image_store = character_image_store
        # Interprets a custom motionPrompt at launch (never raises; None -> raw text).
        self.motion_writer = motion_writer
        self.settings = settings
        # The DEDICATED video-endpoint client, so cancel_batch can abort in-flight
        # RunPod jobs directly via runpod_request_id (never the main endpoint).
        self.video_runpod_client = video_runpod_client
        # Whether the lightning graph is configured (gates the explicit tier alongside
        # VIDEO_BATCH_EXPLICIT_ENABLED). Defaults to reading the master gate off settings.
        if lightning_available is None:
            lightning_available = bool(
                getattr(settings, "COMFYUI_VIDEO_LIGHTNING_WORKFLOW_PATH", "")
            )
        self.lightning_available = lightning_available

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------
    async def launch_batch(
        self, character_id: str, body: VideoBatchCreate
    ) -> Tuple[VideoBatchRead, VideoBatchEstimate]:
        character = await self.character_store.get(character_id)
        if character is None:
            raise CharacterNotFound(character_id)

        defaults = body.defaults
        quality_mode = _val(body.quality_mode) or "fast"

        # Base seed (needed for fixed/per_item) resolved up front so validation can fail
        # BEFORE any batch row is created (no orphan batches on a bad item).
        strategy = defaults.seed_strategy
        base_seed = defaults.base_seed
        if base_seed is None and _val(strategy) != SeedStrategy.RANDOM.value:
            base_seed = random.randint(1, 1_000_000_000)

        # Validate + resolve every item BEFORE persisting anything.
        rows: List[dict] = []
        for index, item in enumerate(body.items):
            rows.append(
                await self._resolve_item_row(
                    character_id, index, item, defaults, quality_mode, strategy, base_seed
                )
            )

        # Persist the batch (with the resolved base_seed folded into defaults so the
        # plan is reproducible) then the items.
        defaults_dump = defaults.model_dump(mode="json")
        defaults_dump["base_seed"] = base_seed
        batch = await self.video_batch_store.create_batch(
            character_id, quality_mode, defaults_dump
        )
        await self.video_batch_store.insert_items(batch.id, rows)

        estimate = compute_estimate(quality_mode, len(rows), self.settings)

        if body.dry_run:
            await self.video_batch_store.set_batch_status(batch.id, "planned")
        else:
            await self.video_batch_store.set_batch_status(batch.id, "running")
        batch = await self.video_batch_store.get_batch(batch.id) or batch
        return batch, estimate

    async def _resolve_item_row(
        self, character_id, index, item, defaults, quality_mode, strategy, base_seed
    ) -> dict:
        """Validate one item + resolve its persisted render inputs (a row dict)."""
        # --- validate the source still ---
        still = await self.character_image_store.get_image(item.source_image_id)
        if not still or still.get("character_id") != character_id:
            raise VideoBatchValidationError(
                f"item {index}: source_image_id not found for this character", 404
            )
        if still.get("image_type") == "video":
            raise VideoBatchValidationError(
                f"item {index}: source_image_id refers to a video; pick a still image", 422
            )
        source_url = still.get("image_url")
        if not source_url:
            raise VideoBatchValidationError(
                f"item {index}: source still has no image_url", 422
            )

        # --- resolve the action (preset snapshot OR custom LLM interpretation) ---
        action = await self._resolve_action(index, item)

        # --- resolve dims / length / fps / seed ---
        item_quality = _val(item.quality_mode) or quality_mode
        if action["tier"] == "explicit":
            item_quality = "fast"  # explicit forces the lightning path
        width = defaults.width or VIDEO_DEFAULT_WIDTH
        height = defaults.height or VIDEO_DEFAULT_HEIGHT
        length = item.length or defaults.length or VIDEO_DEFAULT_LENGTH
        fps = item.fps or defaults.fps or VIDEO_DEFAULT_FPS
        seed = _resolve_item_seed(strategy, base_seed, index, item.seed)

        return {
            "item_index": index,
            "source_image_id": item.source_image_id,
            "source_image_url": source_url,
            "action_kind": action["action_kind"],
            "preset_id": action["preset_id"],
            "custom_prompt": action["custom_prompt"],
            "tier": action["tier"],
            "motion_text": action["motion_text"],
            "motion_label": action["motion_label"],
            "loras": action["loras"],
            "quality_mode": item_quality,
            "width": width,
            "height": height,
            "length": length,
            "fps": fps,
            "seed": seed,
            "negative_prompt": defaults.negative_prompt,
            "status": "pending",
            "attempts": 0,
        }

    async def _resolve_action(self, index, item) -> dict:
        """Resolve a create/rerun item's action to persisted fields, gating explicit.

        Preset -> catalog snapshot (motion text + tier + loras). Custom -> Venice
        MotionWriter interpretation at launch (never raises; falls back to the raw text)."""
        if item.preset_id and item.preset_id.strip():
            preset = get_preset(item.preset_id.strip())
            if preset is None:
                raise VideoBatchValidationError(
                    f"item {index}: unknown preset_id '{item.preset_id}'", 422
                )
            tier = preset.tier.value
            self._gate_explicit(index, tier)
            return {
                "action_kind": "preset",
                "preset_id": preset.id,
                "custom_prompt": None,
                "tier": tier,
                "motion_text": preset.prompt,
                "motion_label": preset.label,
                "loras": resolve_item_loras(preset),
            }

        # custom prompt
        raw = (item.custom_prompt or "").strip()
        if self.motion_writer is not None:
            motion_text, motion_label, _provider = await self.motion_writer.interpret(raw)
        else:
            motion_text, motion_label = raw, raw[:40]
        return {
            "action_kind": "custom",
            "preset_id": None,
            "custom_prompt": raw,
            "tier": None,
            "motion_text": motion_text,
            "motion_label": motion_label,
            "loras": [],
        }

    def _gate_explicit(self, index, tier: Optional[str]) -> None:
        """Reject an explicit-tier item when the path is unset or the flag is off."""
        if tier != "explicit":
            return
        if not self.lightning_available:
            raise VideoBatchValidationError(
                f"item {index}: explicit-tier actions require the lightning video "
                "workflow (COMFYUI_VIDEO_LIGHTNING_WORKFLOW_PATH is unset)", 422
            )
        if not bool(getattr(self.settings, "VIDEO_BATCH_EXPLICIT_ENABLED", False)):
            raise VideoBatchValidationError(
                f"item {index}: the explicit action tier is disabled "
                "(VIDEO_BATCH_EXPLICIT_ENABLED=false)", 422
            )

    # ------------------------------------------------------------------
    # Lifecycle actions
    # ------------------------------------------------------------------
    async def confirm_batch(self, batch_id: str) -> Optional[VideoBatchRead]:
        """Promote a dry-run ('planned') batch to a real run without re-resolving items."""
        batch = await self.video_batch_store.get_batch(batch_id)
        if batch is None:
            return None
        await self.video_batch_store.set_batch_status(batch_id, "running")
        return await self.video_batch_store.get_batch(batch_id)

    async def retry_failed(self, batch_id: str) -> Optional[VideoBatchRead]:
        batch = await self.video_batch_store.get_batch(batch_id)
        if batch is None:
            return None
        failed = await self.video_batch_store.list_item_rows(batch_id, statuses=["failed"])
        for row in failed:
            await self.video_batch_store.reset_item_for_retry(row["id"])
        await self.video_batch_store.set_batch_status(batch_id, "running")
        return await self.video_batch_store.update_batch_aggregate(batch_id)

    async def rerun_item(
        self, batch_id: str, item_id: str, body: Optional[VideoBatchItemRerun] = None
    ) -> Optional[VideoBatchRead]:
        """Re-run one succeeded/failed item, optionally with a new action / seed.

        Supersedes the item's previously published gallery clip + quick action (so the
        rerun REPLACES it rather than orphaning a row), resets the item to 'pending'
        (clearing publish guards), and flips a settled batch back to 'running'. The
        endpoint enforces the succeeded/failed precondition."""
        body = body or VideoBatchItemRerun()
        batch = await self.video_batch_store.get_batch(batch_id)
        if batch is None:
            return None
        row = await self.video_batch_store.get_item_row(item_id, batch_id=batch_id)
        if row is None:
            return None

        # Optional action change (re-resolves motion text / tier / loras, gating explicit).
        action = None
        if (body.preset_id and body.preset_id.strip()) or (
            body.custom_prompt and body.custom_prompt.strip()
        ):
            action = await self._resolve_action(row.get("item_index", 0), body)

        seed = None
        if body.reseed:
            seed = random.randint(1, 1_000_000_000)
        elif body.new_seed is not None:
            seed = body.new_seed

        # Supersede the previously published gallery clip so the rerun replaces it.
        if row.get("character_image_id") and self.character_image_store is not None:
            try:
                await self.character_image_store.delete_image(
                    batch.character_id, row["character_image_id"]
                )
            except Exception as e:  # noqa: BLE001 — a stale image must not block the rerun
                logger.warning(
                    f"[VIDEO_BATCH {batch_id}] could not delete previous clip "
                    f"{row['character_image_id']} for item {item_id}: {e}"
                )

        await self.video_batch_store.reset_item_for_rerun(item_id, seed=seed, action=action)
        await self.video_batch_store.set_batch_status(batch_id, "running")
        return await self.video_batch_store.update_batch_aggregate(batch_id)

    async def cancel_batch(self, batch_id: str, video_runpod_client=None) -> bool:
        """Cancel a batch — abort in-flight RunPod jobs via runpod_request_id directly."""
        batch = await self.video_batch_store.get_batch(batch_id)
        if batch is None:
            return False
        client = video_runpod_client or self.video_runpod_client
        rows = await self.video_batch_store.list_item_rows(batch_id)
        for row in rows:
            rid = row.get("runpod_request_id")
            if row["status"] in ("queued", "running") and rid and client is not None:
                try:
                    await client.cancel(rid)
                except Exception:  # noqa: BLE001 — cancellation is best-effort
                    pass
            if row["status"] in ("pending", "queued", "running"):
                await self.video_batch_store.update_item(row["id"], status="cancelled")
        await self.video_batch_store.set_batch_status(batch_id, "cancelled")
        await self.video_batch_store.update_batch_aggregate(batch_id)
        return True

    # ------------------------------------------------------------------
    # Bulk publish
    # ------------------------------------------------------------------
    async def publish_batch(self, batch_id: str) -> Optional[int]:
        """Flip every succeeded item's draft action to active. Returns the count published."""
        batch = await self.video_batch_store.get_batch(batch_id)
        if batch is None:
            return None
        rows = await self.video_batch_store.list_item_rows(batch_id, statuses=["succeeded"])
        published = 0
        for row in rows:
            action_id = row.get("action_id")
            if not action_id or self.character_image_store is None:
                continue
            updated = await self.character_image_store.set_action_active(
                action_id, batch.character_id, is_active=True
            )
            if updated:
                published += 1
        return published


class VideoBatchReconciler:
    """Single background task that drives all running video batches (submit-only path)."""

    def __init__(
        self,
        job_manager,
        video_batch_store: VideoBatchStore,
        character_image_store,
        video_runpod_client,
        settings,
        supabase_storage_service=None,
    ):
        self.job_manager = job_manager
        self.video_batch_store = video_batch_store
        self.character_image_store = character_image_store
        # The DEDICATED video-endpoint client the worker submitted to — polled here
        # (never the main endpoint; a WAN clip can't finish on the A40 fleet).
        self.runpod_client = video_runpod_client
        self.supabase_storage = supabase_storage_service
        self.settings = settings
        self._running = False
        self._task = None
        self._max_inflight = max(1, int(getattr(settings, "VIDEO_BATCH_MAX_INFLIGHT", 2)))
        self._max_attempts = max(1, int(getattr(settings, "VIDEO_BATCH_ITEM_MAX_ATTEMPTS", 2)))
        self._poll = max(1, int(getattr(settings, "RUNPOD_POLL_INTERVAL_SECONDS", 5)))

    async def start(self) -> None:
        self._running = True
        await self._recover_on_startup()
        self._task = asyncio.create_task(self._loop())
        logger.info("Video-batch reconciler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Video-batch reconciler stopped")

    async def _recover_on_startup(self) -> None:
        """Recover in-flight items after a restart (durable runpod_request_id)."""
        try:
            batches = await self.video_batch_store.list_active_batches()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Video-batch recovery skipped (store unavailable): {e}")
            return
        for batch in batches:
            if batch.status != "running":
                continue
            rows = await self.video_batch_store.list_item_rows(batch.id)
            for row in rows:
                if row["status"] not in ("queued", "running"):
                    continue
                if row.get("runpod_request_id"):
                    # May have COMPLETED while we were down — poll to recover the output.
                    await self._poll_item(batch, row)
                else:
                    # Never submitted (worker lost before the submit persisted) -> pending.
                    await self.video_batch_store.reset_item_for_retry(row["id"])
                    logger.info(
                        f"[RECOVERY] reset never-submitted item {row['id']} in batch {batch.id}"
                    )

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.error(f"Video-batch reconciler tick error: {e}")
            await asyncio.sleep(self._poll)

    async def _tick(self) -> None:
        batches = await self.video_batch_store.list_active_batches()
        for batch in batches:
            if batch.status != "running":
                continue
            await self._reconcile_batch(batch)

    async def _reconcile_batch(self, batch: VideoBatchRead) -> None:
        rows = await self.video_batch_store.list_item_rows(batch.id)

        # 1. Poll in-flight items (those with a durable RunPod handle). Items that are
        #    queued/running WITHOUT a handle are mid-submit by a worker — leave them.
        for row in rows:
            if row["status"] in TERMINAL_ITEM_STATUSES:
                continue
            if not row.get("runpod_request_id"):
                continue
            await self._poll_item(batch, row)

        # 2. Enqueue pending items up to the in-flight window (fairness).
        rows = await self.video_batch_store.list_item_rows(batch.id)
        inflight = sum(1 for r in rows if r["status"] in ("queued", "running"))
        pending = sorted(
            (r for r in rows if r["status"] == "pending"), key=lambda r: r["item_index"]
        )
        for row in pending:
            if inflight >= self._max_inflight:
                break
            await self._enqueue_item(batch, row)
            inflight += 1

        # 3. Recompute the batch aggregate.
        await self.video_batch_store.update_batch_aggregate(batch.id)

    async def _poll_item(self, batch: VideoBatchRead, row: dict) -> None:
        rid = row["runpod_request_id"]
        try:
            doc = await self.runpod_client.status(rid)
        except Exception as e:  # noqa: BLE001 — a transient poll error leaves the item untouched
            logger.warning(
                f"[VIDEO_BATCH {batch.id}] poll of item {row['id']} (runpod {rid}) failed: {e}"
            )
            return
        st = (doc.get("status") or "").upper()
        if st == "COMPLETED":
            await self._handle_completed(batch, row, doc)
        elif st in ("FAILED", "TIMED_OUT"):
            await self._handle_failed(batch, row, error=RunPodServerlessClient.extract_error(doc))
        elif st == "CANCELLED":
            await self.video_batch_store.update_item(
                row["id"], status="cancelled", runpod_status=st
            )
        else:
            # IN_QUEUE / IN_PROGRESS — keep the row's live status in sync.
            if row["status"] != "running" or row.get("runpod_status") != st:
                await self.video_batch_store.update_item(
                    row["id"], status="running", runpod_status=st
                )

    async def _handle_completed(self, batch: VideoBatchRead, row: dict, doc: dict) -> None:
        media = self._first_media(doc.get("output"))
        if media is None:
            # COMPLETED with no usable output — treat as a genuine failure (attempt-consuming).
            await self._handle_failed(
                batch, row, error="RunPod COMPLETED but returned no video output"
            )
            return

        video_url = media.get("url")
        video_hash = None
        if not video_url:
            data = media.get("data")
            if not data:
                await self._handle_failed(
                    batch, row, error="RunPod COMPLETED but output had neither url nor data"
                )
                return
            if self.supabase_storage is None:
                await self._handle_failed(
                    batch, row,
                    error="RunPod returned base64 video but no Supabase storage is configured",
                )
                return
            try:
                raw = base64.b64decode(data)
                ext = "mp4"
                filename = media.get("filename")
                if filename and "." in filename:
                    ext = filename.rsplit(".", 1)[-1].lower()
                video_url, video_hash = await asyncio.to_thread(
                    self.supabase_storage.upload_video,
                    video=raw,
                    video_id=row["id"],
                    folder=STORAGE_FOLDER,
                    ext=ext,
                    content_type=media.get("content_type") or "video/mp4",
                )
            except Exception as e:  # noqa: BLE001 — upload failure: retry next tick, non-terminal
                logger.error(
                    f"[VIDEO_BATCH {batch.id}] video upload failed for item {row['id']} "
                    f"(will retry next tick): {e}"
                )
                return

        # Publish BEFORE terminal, with set-once idempotency guards.
        try:
            await self._publish_reel(batch, row, video_url, video_hash)
        except Exception as e:  # noqa: BLE001 — keep non-terminal so the next tick retries
            logger.error(
                f"[VIDEO_BATCH {batch.id}] publish failed for item {row['id']} "
                f"(will retry next tick): {e}"
            )
            return

        await self.video_batch_store.update_item(
            row["id"],
            status="succeeded",
            runpod_status="COMPLETED",
            video_url=video_url,
            preview_url=video_url,
            error_code=None,
            error_message=None,
        )
        logger.info(
            f"[VIDEO_BATCH {batch.id}] item {row['item_index']} SUCCEEDED -> {video_url}"
        )

    async def _publish_reel(
        self, batch: VideoBatchRead, row: dict, video_url: str, video_hash
    ) -> None:
        """Write the character_images video row + its DRAFT chat action (guards set once)."""
        if self.character_image_store is None:
            raise RuntimeError("character image store not configured")

        character_image_id = row.get("character_image_id")
        action_id = row.get("action_id")
        motion_text = row.get("motion_text")
        motion_label = row.get("motion_label") or "Reel"

        if character_image_id is None:
            character_image_id = await self.character_image_store.create_image(
                batch.character_id,
                image_url=video_url,
                original_image_url=row.get("source_image_url"),
                prompt=motion_text,
                seed=row.get("seed"),
                image_type="video",
                source_image_id=row.get("source_image_id"),
                metadata={
                    "media_type": "video",
                    "motion": row.get("preset_id") or motion_label,
                    "batch_id": batch.id,
                    "item_index": row.get("item_index"),
                    "tier": row.get("tier"),
                    "action_kind": row.get("action_kind"),
                    "video_hash": video_hash,
                },
            )
            # Persist the guard IMMEDIATELY so a crash before the action never orphans it.
            await self.video_batch_store.update_item(
                row["id"], character_image_id=character_image_id
            )

        if action_id is None:
            source_scene = await self._source_scene(row.get("source_image_id"), batch.id)
            action_id = await self.character_image_store.create_action(
                batch.character_id,
                character_image_id=character_image_id,
                media_url=video_url,
                label=motion_label,
                media_type="video",
                is_active=False,  # DRAFT — admin publishes after review
                sort_order=row.get("item_index") or 0,
                trigger_keywords=action_keywords(
                    source_scene, extra_texts=[motion_label, motion_text]
                ),
            )
            await self.video_batch_store.update_item(row["id"], action_id=action_id)

        logger.info(
            f"[VIDEO_BATCH {batch.id}] published item {row['item_index']} -> "
            f"character_images {character_image_id} (+ draft action)"
        )

    async def _source_scene(self, source_image_id, batch_id) -> Optional[dict]:
        """Best-effort scene_spec of the source still (for keyword enrichment); never raises."""
        if not source_image_id or self.character_image_store is None:
            return None
        try:
            src = await self.character_image_store.get_image(source_image_id)
            if src:
                return (src.get("metadata") or {}).get("scene_spec")
        except Exception as e:  # noqa: BLE001 — keywords are best-effort, never a gate
            logger.warning(
                f"[VIDEO_BATCH {batch_id}] source scene lookup failed: {e}"
            )
        return None

    async def _handle_failed(
        self, batch: VideoBatchRead, row: dict, error: Optional[str] = None
    ) -> None:
        attempts = row.get("attempts") or 0
        if attempts < self._max_attempts:
            await self.video_batch_store.reset_item_for_retry(row["id"])
            logger.info(
                f"[VIDEO_BATCH {batch.id}] RETRY item {row['id']} (attempt {attempts}): {error}"
            )
        else:
            await self.video_batch_store.update_item(
                row["id"],
                status="failed",
                error_code="VIDEO_RUNPOD_FAILED",
                error_message=(error or "RunPod job failed")[:500],
            )
            logger.error(
                f"[VIDEO_BATCH {batch.id}] item {row['id']} FAILED after {attempts} attempts: {error}"
            )

    async def _enqueue_item(self, batch: VideoBatchRead, row: dict) -> None:
        try:
            request = VideoBatchJobRequest(
                batch_id=batch.id,
                item_id=row["id"],
                character_id=batch.character_id,
                source_image=row["source_image_url"],
                motion_text=row.get("motion_text") or "",
                quality_mode=row.get("quality_mode") or "fast",
                tier=row.get("tier"),
                negative_prompt=row.get("negative_prompt"),
                seed=row.get("seed"),
                width=row.get("width"),
                height=row.get("height"),
                length=row.get("length"),
                fps=row.get("fps"),
                loras=row.get("loras") or [],
                interpolate=bool((batch.defaults or {}).get("interpolate", False)),
            )
            job = await self.job_manager.create_job(
                request, VIDEO_BATCH_JOB_OWNER, job_type=VIDEO_BATCH_JOB_TYPE
            )
            await self.video_batch_store.update_item(
                row["id"],
                job_id=job.job_id,
                status="queued",
                attempts=(row.get("attempts") or 0) + 1,
            )
            logger.info(
                f"[VIDEO_BATCH {batch.id}] enqueued item {row['item_index']} -> {job.job_id}"
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[VIDEO_BATCH {batch.id}] failed to enqueue item {row['id']}: {e}")
            await self.video_batch_store.update_item(
                row["id"], status="failed", error_code="ENQUEUE_ERROR", error_message=str(e)
            )

    @staticmethod
    def _first_media(output: Optional[dict]) -> Optional[Dict[str, Any]]:
        """First media descriptor from a RunPod output doc, preferring video over image."""
        media = RunPodServerlessClient.parse_output(output)
        if not media:
            return None
        for m in media:
            if m.get("kind") == "video":
                return m
        return media[0]
