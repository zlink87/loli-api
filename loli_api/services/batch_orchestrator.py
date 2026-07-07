"""
Batch orchestrator + reconciler for character photo batches.

launch_batch(): loads the character, plans N scenes, persists the batch + items, and
returns an immediate cost/time estimate. Real (non-dry-run) batches are set to
'running'; the reconciler then drives all enqueueing and result collection.

BatchReconciler (single background task): every poll interval, for each 'running'
batch it (1) copies terminal child-job state into batch_items — writing each
succeeded photo into the REAL product tables (character_images + a
chat_persona_actions quick action) before the item is marked done, (2) retries
failed/lost items up to the attempt cap, (3) enqueues pending items up to a
per-batch in-flight window (fairness), and (4) recomputes the batch aggregate.
It re-derives state from the DB on startup, so a batch survives restarts.
"""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from models.enums import JobStatus
from models.batch import BatchCreate, BatchRead, BatchEstimate, BatchControls
from models.scene import SceneSpec
from services import story_planner
from services.story_planner import Character
from services.scene_mapper import scene_to_pipeline_request, resolve_seed
from services.batch_store import BatchStore, TERMINAL_ITEM_STATUSES
from services.character_store import CharacterStore
from services.character_image_store import CharacterImageStore, action_label

logger = logging.getLogger(__name__)

BATCH_JOB_TYPE = "batch_pipeline_edit"
STORAGE_FOLDER = "batch_edits"

# Single-admin API: internal jobs are owned by this constant identity so the
# in-memory Job registry's ownership check (get_job_for_user) stays consistent.
BATCH_JOB_OWNER = "batch-admin"


class CharacterNotFound(Exception):
    pass


def _active_steps_for_scene(scene: SceneSpec, controls: BatchControls) -> int:
    steps = 1  # background is effectively always present (location is required)
    if scene.pose is not None and scene.pose not in (controls.blocked_poses or []):
        steps += 1
    if scene.outfit is not None:
        steps += 1
    return steps


def compute_estimate(scenes: List[SceneSpec], controls: BatchControls, settings) -> BatchEstimate:
    total_jobs = sum(_active_steps_for_scene(s, controls) for s in scenes)
    avg = max(1, int(settings.RUNPOD_AVG_STEP_SECONDS))
    pool = max(1, int(settings.BATCH_WORKER_POOL_SIZE))
    base_seconds = total_jobs * avg / pool
    rate = float(getattr(settings, "RUNPOD_GPU_USD_PER_SECOND", 0.0) or 0.0)
    return BatchEstimate(
        items_total=len(scenes),
        est_runpod_jobs=total_jobs,
        est_seconds_min=int(base_seconds),
        est_seconds_max=int(base_seconds * 1.6),
        est_cost_usd=(round(total_jobs * avg * rate, 4) if rate > 0 else None),
    )


class BatchOrchestrator:
    def __init__(self, job_manager, character_store: CharacterStore, batch_store: BatchStore, settings):
        self.job_manager = job_manager
        self.character_store = character_store
        self.batch_store = batch_store
        self.settings = settings

    async def launch_batch(
        self, character_id: str, body: BatchCreate
    ) -> Tuple[BatchRead, BatchEstimate]:
        character = await self.character_store.get(character_id)
        if character is None:
            raise CharacterNotFound(character_id)

        batch = await self.batch_store.create_batch(
            character_id, body.count, body.controls,
            likes=body.likes, dislikes=body.dislikes,
        )

        # Ensure a base seed so PER_ITEM/FIXED strategies are reproducible.
        controls = body.controls
        if controls.base_seed is None and story_planner._val(controls.seed_strategy) != "random":
            controls = controls.model_copy(update={"base_seed": (abs(hash(batch.id)) % 1_000_000_000) or 1})

        planner_character = Character(
            persona=character.persona,
            likes=body.likes,
            dislikes=body.dislikes,
            hero_photo_url=character.hero_image_url,
        )
        scenes, provider = await story_planner.plan_scenes(
            planner_character, body.count, controls, settings=self.settings
        )
        logger.info(f"[BATCH {batch.id}] planned {len(scenes)} scenes via '{provider}'")

        rows = []
        for s in scenes:
            rows.append(
                {
                    "scene_index": s.global_index,
                    "scene_spec": s.model_dump(mode="json"),
                    "arc": s.arc_id,
                    "beat": s.beat_index,
                    "status": "pending",
                    "seed": resolve_seed(controls, s.global_index),
                    "attempts": 0,
                }
            )
        await self.batch_store.insert_items(batch.id, rows)

        estimate = compute_estimate(scenes, controls, self.settings)

        if body.dry_run:
            await self.batch_store.set_batch_status(batch.id, "planned")
            batch = await self.batch_store.get_batch(batch.id) or batch
            return batch, estimate

        await self.batch_store.set_batch_status(batch.id, "running")
        batch = await self.batch_store.get_batch(batch.id) or batch
        return batch, estimate

    async def confirm_batch(self, batch_id: str) -> Optional[BatchRead]:
        """
        Promote a dry-run ('planned') batch to a real run WITHOUT re-planning.

        The batch's items already carry their persisted scene_spec + seed, so flipping
        it to 'running' makes the reconciler enqueue exactly the previewed plan. Returns
        None if the batch does not exist; the endpoint enforces the 'planned' precondition.
        """
        batch = await self.batch_store.get_batch(batch_id)
        if batch is None:
            return None
        await self.batch_store.set_batch_status(batch_id, "running")
        return await self.batch_store.get_batch(batch_id)

    async def retry_failed(self, batch_id: str) -> Optional[BatchRead]:
        batch = await self.batch_store.get_batch(batch_id)
        if batch is None:
            return None
        failed = await self.batch_store.list_items(batch_id, statuses=["failed"])
        for item in failed:
            await self.batch_store.reset_item_for_retry(item.id)
        await self.batch_store.set_batch_status(batch_id, "running")
        return await self.batch_store.update_batch_aggregate(batch_id)

    async def cancel_batch(self, batch_id: str) -> bool:
        batch = await self.batch_store.get_batch(batch_id)
        if batch is None:
            return False
        items = await self.batch_store.list_items(batch_id)
        for item in items:
            if item.status in ("queued", "running") and item.job_id:
                await self.job_manager.cancel_job(item.job_id, BATCH_JOB_OWNER)
            if item.status in ("pending", "queued", "running"):
                await self.batch_store.update_item_result(item.id, status="cancelled")
        await self.batch_store.set_batch_status(batch_id, "cancelled")
        await self.batch_store.update_batch_aggregate(batch_id)
        return True


class BatchReconciler:
    """Single background task that drives all running batches."""

    def __init__(
        self,
        job_manager,
        character_store: CharacterStore,
        batch_store: BatchStore,
        settings,
        supabase_storage_service=None,
        character_image_store: Optional[CharacterImageStore] = None,
    ):
        self.job_manager = job_manager
        self.character_store = character_store
        self.batch_store = batch_store
        self.settings = settings
        self.supabase_storage = supabase_storage_service
        self.character_image_store = character_image_store
        self._running = False
        self._task = None
        self._max_inflight = max(1, int(settings.BATCH_MAX_INFLIGHT))
        self._max_attempts = max(1, int(settings.BATCH_ITEM_MAX_ATTEMPTS))
        self._poll = max(1, int(settings.RUNPOD_POLL_INTERVAL_SECONDS))

    async def start(self) -> None:
        self._running = True
        await self._recover_on_startup()
        self._task = asyncio.create_task(self._loop())
        logger.info("Batch reconciler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Batch reconciler stopped")

    async def _recover_on_startup(self) -> None:
        """Reset orphaned 'running/queued' items whose in-memory job is gone."""
        try:
            batches = await self.batch_store.list_active_batches()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Batch recovery skipped (store unavailable): {e}")
            return
        for batch in batches:
            if batch.status != "running":
                continue
            items = await self.batch_store.list_items(batch.id)
            for item in items:
                if item.status in ("queued", "running") and item.job_id:
                    job = await self.job_manager.get_job(item.job_id)
                    if job is None:  # in-memory job lost across restart
                        await self.batch_store.reset_item_for_retry(item.id)
                        logger.info(f"[RECOVERY] reset orphaned item {item.id} in batch {batch.id}")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.error(f"Batch reconciler tick error: {e}")
            await asyncio.sleep(self._poll)

    async def _tick(self) -> None:
        batches = await self.batch_store.list_active_batches()
        char_cache: Dict[str, object] = {}
        for batch in batches:
            if batch.status != "running":
                continue
            await self._reconcile_batch(batch, char_cache)

    async def _reconcile_batch(self, batch: BatchRead, char_cache: Dict[str, object]) -> None:
        items = await self.batch_store.list_items(batch.id)

        # 1. Collect terminal child-job states into batch_items.
        for item in items:
            if item.status in TERMINAL_ITEM_STATUSES:
                continue
            if not item.job_id:
                continue
            job = await self.job_manager.get_job(item.job_id)
            if job is None:
                await self._handle_lost(item)
            elif job.status == JobStatus.SUCCEEDED:
                await self._handle_succeeded(batch, item, job)
            elif job.status == JobStatus.FAILED:
                await self._handle_failed(item, job)
            else:
                if item.status != "running":
                    await self.batch_store.update_item_result(item.id, status="running")

        # 2. Enqueue pending items up to the in-flight window.
        items = await self.batch_store.list_items(batch.id)
        inflight = sum(1 for i in items if i.status in ("queued", "running"))
        pending = [i for i in items if i.status == "pending"]
        pending.sort(key=lambda i: i.scene_index)

        if pending and inflight < self._max_inflight:
            character = char_cache.get(batch.character_id)
            if character is None:
                character = await self.character_store.get(batch.character_id)
                char_cache[batch.character_id] = character
            if character is not None:
                planner_character = Character(
                    persona=character.persona,
                    likes=batch.likes,
                    dislikes=batch.dislikes,
                    hero_photo_url=character.hero_image_url,
                )
                for item in pending:
                    if inflight >= self._max_inflight:
                        break
                    await self._enqueue_item(batch, planner_character, item)
                    inflight += 1

        # 3. Recompute the batch aggregate.
        await self.batch_store.update_batch_aggregate(batch.id)

    async def _enqueue_item(self, batch: BatchRead, character: Character, item) -> None:
        try:
            scene = SceneSpec(**item.scene_spec)
            request = scene_to_pipeline_request(character, scene, batch.controls, seed=item.seed)
            job = await self.job_manager.create_job(request, BATCH_JOB_OWNER, job_type=BATCH_JOB_TYPE)
            await self.batch_store.update_item_result(
                item.id,
                job_id=job.job_id,
                pipeline_request=request.model_dump(mode="json"),
                status="queued",
                attempts=(item.attempts or 0) + 1,
            )
            logger.info(f"[BATCH {batch.id}] enqueued item {item.scene_index} -> {job.job_id}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[BATCH {batch.id}] failed to enqueue item {item.id}: {e}")
            await self.batch_store.update_item_result(
                item.id, status="failed", error_code="ENQUEUE_ERROR", error_message=str(e)
            )

    async def _handle_succeeded(self, batch: BatchRead, item, job) -> None:
        """
        Publish the finished photo into the product tables, THEN mark the item done.

        Ordering matters: the reconciler skips terminal items, so the item must not
        be marked 'succeeded' until the character_images row exists — a failed
        gallery write leaves the item non-terminal and is retried next tick (the
        in-memory job is retained for ~24h). item.character_image_id guards against
        double-inserting on such retries.
        """
        image_url = self._stable_image_url(job.job_id) or job.preview_url

        character_image_id = item.character_image_id
        if character_image_id is None and self.character_image_store is not None and image_url:
            try:
                character_image_id = await self._publish_image(batch, item, job, image_url)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"[BATCH {batch.id}] gallery write failed for item {item.id} "
                    f"(will retry next tick): {e}"
                )
                return  # keep the item non-terminal so the next tick retries

        await self.batch_store.update_item_result(
            item.id,
            status="succeeded",
            preview_url=job.preview_url,
            image_url=image_url,
            image_hash=job.image_hash,
            seed=job.seed_used,
            character_image_id=character_image_id,
        )

    async def _publish_image(self, batch: BatchRead, item, job, image_url: str) -> str:
        """Create the character_images row + its chat quick action; returns the image id."""
        scene = SceneSpec(**item.scene_spec) if item.scene_spec else None
        pipeline_request = None
        try:
            # pipeline_request was persisted at enqueue time; prefer its prompt.
            row = await self.batch_store._get_item(item.id)
            pipeline_request = (row or {}).get("pipeline_request")
        except Exception:  # noqa: BLE001
            pass

        prompt = None
        if isinstance(pipeline_request, dict):
            prompt = pipeline_request.get("prompt")
        if not prompt and scene is not None:
            prompt = scene.beat_description

        outfit = None
        accessories: List[str] = []
        beat_description = None
        arc_title = None
        if scene is not None:
            outfit = scene.outfit.value if scene.outfit is not None else None
            accessories = [a.value for a in (scene.accessories or [])]
            beat_description = scene.beat_description
            arc_title = scene.arc_title

        image_id = await self.character_image_store.create_image(
            batch.character_id,
            image_url=image_url,
            original_image_url=job.preview_url,
            prompt=prompt,
            seed=job.seed_used,
            outfit=outfit,
            accessories=accessories,
            metadata={
                "batch_id": batch.id,
                "scene_index": item.scene_index,
                "arc": item.arc,
                "beat": item.beat,
                "image_hash": job.image_hash,
                "scene_spec": item.scene_spec,
            },
        )
        await self.character_image_store.create_action(
            batch.character_id,
            character_image_id=image_id,
            media_url=image_url,
            label=action_label(beat_description, arc_title, item.scene_index),
            suggested_prompt=beat_description,
            sort_order=item.scene_index,
        )
        logger.info(
            f"[BATCH {batch.id}] published item {item.scene_index} -> "
            f"character_images {image_id} (+ quick action)"
        )
        return image_id

    async def _handle_failed(self, item, job) -> None:
        if (item.attempts or 0) < self._max_attempts:
            await self.batch_store.reset_item_for_retry(item.id)
            logger.info(f"[RETRY] item {item.id} (attempt {item.attempts})")
        else:
            await self.batch_store.update_item_result(
                item.id,
                status="failed",
                error_code=job.error_code or "BATCH_EDIT_ERROR",
                error_message=job.error_message,
            )

    async def _handle_lost(self, item) -> None:
        if (item.attempts or 0) < self._max_attempts:
            await self.batch_store.reset_item_for_retry(item.id)
        else:
            await self.batch_store.update_item_result(
                item.id, status="failed", error_code="LOST_JOB",
                error_message="Worker job disappeared (restart/cleanup)",
            )

    def _stable_image_url(self, job_id: str) -> Optional[str]:
        if self.supabase_storage is None:
            return None
        try:
            return self.supabase_storage.get_public_url(f"{STORAGE_FOLDER}/{job_id}.png")
        except Exception:  # noqa: BLE001
            return None
