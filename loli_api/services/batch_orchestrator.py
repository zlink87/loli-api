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
from models.trait_profile import TraitProfile
from services import story_planner
from services import scene_direction
from services.story_planner import Character
from services.scene_mapper import scene_to_pipeline_request, resolve_seed
from services.trait_profile_merge import apply_trait_profile
from services.batch_store import BatchStore, TERMINAL_ITEM_STATUSES
from services.character_store import CharacterStore
from services.character_image_store import CharacterImageStore, action_label, action_keywords

logger = logging.getLogger(__name__)

BATCH_JOB_TYPE = "batch_pipeline_edit"
STORAGE_FOLDER = "batch_edits"

# Single-admin API: internal jobs are owned by this constant identity so the
# in-memory Job registry's ownership check (get_job_for_user) stays consistent.
BATCH_JOB_OWNER = "batch-admin"


class CharacterNotFound(Exception):
    pass


def _single_pass_eligible_scene(
    scene: SceneSpec, controls: BatchControls, *, single_pass: bool, has_nude_base: bool
) -> bool:
    """Estimate-side mirror of scene_mapper's single-pass eligibility: an item collapses
    to ONE pose-graph job when single-pass is on, the character has a nude base (the swap
    source), and the scene sets both a (non-blocked) pose and an outfit (NAKED counts)."""
    if not (single_pass and has_nude_base):
        return False
    pose_active = scene.pose is not None and scene.pose not in (controls.blocked_poses or [])
    outfit_active = scene.outfit is not None
    return pose_active and outfit_active


def _active_steps_for_scene(
    scene: SceneSpec, controls: BatchControls, *,
    single_pass: bool = False, has_nude_base: bool = False,
) -> int:
    # Single-pass collapses an eligible item to ONE pose-graph job (outfit + scene + pose
    # rendered in one full-frame re-diffusion from the nude base). Defaults (both False)
    # reproduce the legacy per-step count exactly.
    if _single_pass_eligible_scene(
        scene, controls, single_pass=single_pass, has_nude_base=has_nude_base
    ):
        return 1
    steps = 1  # background is effectively always present (location is required)
    if scene.pose is not None and scene.pose not in (controls.blocked_poses or []):
        steps += 1
    if scene.outfit is not None:
        steps += 1
    return steps


def compute_estimate(
    scenes: List[SceneSpec], controls: BatchControls, settings, *, has_nude_base: bool = False
) -> BatchEstimate:
    # Read the single-pass flag off settings so the estimate matches what the reconciler
    # actually enqueues; getattr keeps test settings stubs (which may omit it) on the
    # legacy count. Eligibility also needs a nude base (the single-pass swap source) —
    # ``has_nude_base`` is resolved by the caller (launch_batch) so this stays sync/pure.
    single_pass = bool(getattr(settings, "BATCH_SINGLE_PASS_EDIT", False))
    total_jobs = sum(
        _active_steps_for_scene(
            s, controls, single_pass=single_pass, has_nude_base=has_nude_base
        )
        for s in scenes
    )
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
    def __init__(
        self,
        job_manager,
        character_store: CharacterStore,
        batch_store: BatchStore,
        settings,
        character_image_store: Optional[CharacterImageStore] = None,
        trait_profile_store=None,
        nude_base_store=None,
    ):
        self.job_manager = job_manager
        self.character_store = character_store
        self.batch_store = batch_store
        self.settings = settings
        # Optional — used by rerun_item to supersede a previously published gallery
        # image so a rerun REPLACES it instead of orphaning/duplicating a row.
        self.character_image_store = character_image_store
        # Optional — when wired AND body.use_trait_profile, launch_batch folds the
        # character's saved TraitProfile into the batch controls/likes/dislikes as a soft
        # bias (best-effort, never blocks). None -> feature inert (batches unchanged).
        self.trait_profile_store = trait_profile_store
        # Optional per-character nude-base lookup (same store the reconciler uses). Only
        # read by launch_batch's cost/time ESTIMATE, so it knows whether single-pass
        # collapse applies (single-pass needs the nude base as the swap source). None ->
        # the estimate assumes no nude base (legacy multi-step counts).
        self.nude_base_store = nude_base_store

    async def launch_batch(
        self, character_id: str, body: BatchCreate
    ) -> Tuple[BatchRead, BatchEstimate]:
        character = await self.character_store.get(character_id)
        if character is None:
            raise CharacterNotFound(character_id)

        # Variety-only batches: story mode is retired from the admin flow. Force it OFF
        # before planning so a stale admin payload (story_mode=True) can never re-enable the
        # old story-director path — batches always run the coherent variety planner now.
        controls = body.controls
        if getattr(controls, "story_mode", False):
            controls = controls.model_copy(update={"story_mode": False})
        likes = body.likes
        dislikes = body.dislikes

        # Trait-profile + culture bias (WS-B): fold the character's saved profile AND its
        # culture into the effective controls/likes/dislikes BEFORE persisting the batch, so
        # the stored row carries the effective values and the reconciler re-derives the same
        # Character with no changes. Best-effort: a load/merge failure NEVER blocks a launch
        # (falls back to the raw body). Gated only on use_trait_profile — the trait store may
        # be absent yet the character still carry a culture, so the merge runs regardless.
        if body.use_trait_profile:
            controls, likes, dislikes = await self._apply_trait_profile(
                character_id, character, controls, likes, dislikes
            )

        batch = await self.batch_store.create_batch(
            character_id, body.count, controls,
            likes=likes, dislikes=dislikes,
        )

        # Ensure a base seed so PER_ITEM/FIXED strategies are reproducible.
        if controls.base_seed is None and story_planner._val(controls.seed_strategy) != "random":
            controls = controls.model_copy(update={"base_seed": (abs(hash(batch.id)) % 1_000_000_000) or 1})

        planner_character = Character(
            persona=character.persona,
            likes=likes,
            dislikes=dislikes,
            hero_photo_url=character.hero_image_url,
            bio=character.bio,  # story-mode narrative coherence
        )
        scenes, provider = await story_planner.plan_scenes(
            planner_character, body.count, controls, settings=self.settings
        )
        logger.info(f"[BATCH {batch.id}] planned {len(scenes)} scenes via provider '{provider}'")
        # Persist the resolved provider on the batch row so silent Venice->deterministic
        # fallbacks (the Venice client never raises) are visible after the fact.
        await self.batch_store.set_planner_provider(batch.id, provider)
        # WS-SD: Venice writes each item's photographic staging (HOW it looks) on the FINAL,
        # already-coherent facts. Best-effort + validated + fallback-safe (never raises;
        # provider "deterministic"/no key -> a no-op that leaves the fields None). SKIPPED
        # on a dry_run: a preview must stay network-free (this is the batch's one live
        # planning-time enrichment call), so the writer is only invoked for a real launch.
        if not body.dry_run:
            scenes = await scene_direction.apply_scene_directions(
                scenes, controls, settings=self.settings, batch_id=batch.id
            )

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

        # Single-pass estimate exactness: whether a nude base exists (the single-pass swap
        # source) is per-character, so resolve it here (best-effort, async) and feed the
        # otherwise-pure estimator — this matches what the reconciler will actually enqueue.
        has_nude_base = bool(await self._resolve_nude_base_url(character_id))
        estimate = compute_estimate(
            scenes, controls, self.settings, has_nude_base=has_nude_base
        )

        if body.dry_run:
            await self.batch_store.set_batch_status(batch.id, "planned")
            batch = await self.batch_store.get_batch(batch.id) or batch
            return batch, estimate

        await self.batch_store.set_batch_status(batch.id, "running")
        batch = await self.batch_store.get_batch(batch.id) or batch
        return batch, estimate

    async def _apply_trait_profile(
        self, character_id: str, character, controls: BatchControls,
        likes: List[str], dislikes: List[str],
    ) -> Tuple[BatchControls, List[str], List[str]]:
        """
        Best-effort: load the character's saved TraitProfile (when a store is wired) and
        fold it — together with the character's culture — into the batch controls/likes/
        dislikes (services.trait_profile_merge.apply_trait_profile). NEVER raises: a missing
        profile row, an un-migrated table, or any store error logs a warning and merges with
        profile=None (so a lone culture still biases the batch), and a merge failure returns
        the inputs unchanged — a trait-profile problem can never block a batch launch. The
        occupation (work-location protection) and culture both come from the character's
        persona. A character with neither a profile nor a culture yields byte-identical
        controls, since apply_trait_profile no-ops when both are absent.
        """
        persona = getattr(character, "persona", None)
        culture = getattr(persona, "culture", None)
        occupation = getattr(persona, "occupation", None)
        try:
            profile = None
            if self.trait_profile_store is not None:
                row = await self.trait_profile_store.get(character_id)
                if row:
                    profile = TraitProfile.coerce(row.get("profile"))
            return apply_trait_profile(
                controls, likes, dislikes, profile, occupation, culture=culture
            )
        except Exception as e:  # noqa: BLE001 — trait profile is a soft bias, never a gate
            logger.warning(
                f"[BATCH] trait-profile merge skipped for character {character_id}: {e}"
            )
            return controls, likes, dislikes

    async def _resolve_nude_base_url(self, character_id: str) -> Optional[str]:
        """The character's nude-base URL (single-pass swap source), or None.

        Best-effort and used ONLY by the estimate: None when the store is unwired, no
        base exists, or the lookup fails — every such case falls back to a legacy
        multi-step estimate (and the reconciler independently re-resolves the base at
        enqueue time, so a stale/missing estimate never changes what actually runs)."""
        if self.nude_base_store is None:
            return None
        try:
            return await self.nude_base_store.get_active_url(character_id)
        except Exception as e:  # noqa: BLE001 — an estimate lookup must never block a launch
            logger.warning(f"nude base lookup failed for character {character_id}: {e}")
            return None

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

    async def rerun_item(
        self, batch_id: str, item_id: str, *, seed: Optional[int] = None
    ) -> Optional[BatchRead]:
        """
        Re-run a single item (Phase 3), mirroring retry_failed for one photo.

        Supersedes the item's previously published gallery image + quick action (so
        the rerun REPLACES it rather than leaving the old character_images row orphaned
        and inserting a duplicate on the next success), resets the item to 'pending'
        with cleared error/image fields and the resolved seed, and flips a settled
        (completed/partial/failed) batch back to 'running'. The reconciler's normal
        poll loop then picks the pending item up and enqueues it via _enqueue_item.

        Returns the refreshed batch, or None if the batch/item doesn't exist. The
        endpoint enforces the succeeded/failed status precondition.
        """
        batch = await self.batch_store.get_batch(batch_id)
        if batch is None:
            return None
        item = await self.batch_store.get_item(item_id, batch_id=batch_id)
        if item is None:
            return None

        # Supersede the previously published gallery image so the rerun replaces it.
        # _handle_succeeded's idempotency guard is item.character_image_id, which
        # reset_item_for_rerun clears below — so without this delete the next success
        # would insert a SECOND character_images row and orphan the old one.
        if item.character_image_id and self.character_image_store is not None:
            try:
                await self.character_image_store.delete_image(
                    batch.character_id, item.character_image_id
                )
            except Exception as e:  # noqa: BLE001 — a stale image must not block the rerun
                logger.warning(
                    f"[BATCH {batch_id}] could not delete previous image "
                    f"{item.character_image_id} for item {item_id}: {e}"
                )

        await self.batch_store.reset_item_for_rerun(item_id, seed=seed)
        # Flip a settled batch back to running; update_batch_aggregate then recomputes
        # counters (the now-pending item drops out of items_succeeded/items_failed) and
        # re-derives the status as 'running' since done < total.
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
        nude_base_store=None,
    ):
        self.job_manager = job_manager
        self.character_store = character_store
        self.batch_store = batch_store
        self.settings = settings
        self.supabase_storage = supabase_storage_service
        self.character_image_store = character_image_store
        # Optional per-character nude-base lookup. When wired AND a character has a
        # succeeded nude base, scenes edit from it (additive dressing); otherwise the
        # source stays the clothed hero (unchanged). None -> feature inert.
        self.nude_base_store = nude_base_store
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
        # character_id -> resolved nude-base URL (or None), memoized per tick.
        nude_cache: Dict[str, Optional[str]] = {}
        for batch in batches:
            if batch.status != "running":
                continue
            await self._reconcile_batch(batch, char_cache, nude_cache)

    async def _resolve_nude_base_url(self, character_id: str) -> Optional[str]:
        """The character's additive-dressing source (latest succeeded nude base), or None.

        None when the store is unwired, no base exists, or the lookup fails — every
        such case falls back to the clothed hero photo in scene_mapper (unchanged)."""
        if self.nude_base_store is None:
            return None
        try:
            return await self.nude_base_store.get_active_url(character_id)
        except Exception as e:  # noqa: BLE001 — a lookup failure must not stall the batch
            logger.warning(f"nude base lookup failed for character {character_id}: {e}")
            return None

    async def _reconcile_batch(
        self, batch: BatchRead, char_cache: Dict[str, object], nude_cache: Dict[str, Optional[str]]
    ) -> None:
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
            if batch.character_id not in nude_cache:
                nude_cache[batch.character_id] = await self._resolve_nude_base_url(batch.character_id)
            if character is not None:
                planner_character = Character(
                    persona=character.persona,
                    likes=batch.likes,
                    dislikes=batch.dislikes,
                    hero_photo_url=character.hero_image_url,
                    # THE activation line: when set, scene_mapper sources scene edits from
                    # the nude base instead of the clothed hero (additive dressing).
                    nude_base_url=nude_cache.get(batch.character_id),
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
            # single_pass is the settings flag (scene_mapper stays settings-free); it only
            # takes effect when the item is eligible (nude-base source + pose + outfit).
            # reruns/retries flow through here too, so they inherit it automatically.
            # getattr keeps test settings stubs (which may omit the field) on the legacy path.
            request = scene_to_pipeline_request(
                character, scene, batch.controls, seed=item.seed,
                single_pass=getattr(self.settings, "BATCH_SINGLE_PASS_EDIT", False),
            )
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

        # Phase 5 observability: persist the EXACT per-step positive/negative
        # prompts (captured live during execution — see workers/pipeline_worker.py
        # ``_extract_step_prompts`` / ``job.debug_meta``) into the item's OWN
        # pipeline_request jsonb, alongside the resolved planner provider, so a bad
        # image is attributable to planner (scene_spec) vs. render (this) in one
        # look without cross-referencing character_images. Best-effort and AFTER
        # the terminal update above: unlike the gallery write, a failure here must
        # never leave the item stuck non-terminal — it's pure diagnostics.
        await self._persist_item_debug(batch, item, job)

    async def _persist_item_debug(self, batch: BatchRead, item, job) -> None:
        """
        Phase 5: extend the existing WS3.1 per-step trace (``job.debug_meta``,
        already reused verbatim in ``_publish_image`` as
        ``character_images.metadata.workflow_meta``) with the composed
        positive/negative prompt strings, and additionally persist it onto the
        batch item's own ``pipeline_request["_debug"]`` (no DB migration — the
        column already exists) so it's queryable per-item without a join.

        A no-op when the job carries no step trace (e.g. a hand-built test
        double, or a job type that predates ``debug_meta``) — nothing to persist.
        """
        debug_meta = getattr(job, "debug_meta", None) or {}
        steps = debug_meta.get("steps") or []
        if not steps:
            return
        payload = {
            "steps": [
                {
                    "step": s.get("step"),
                    "tier": s.get("tier"),
                    "seed": s.get("seed"),
                    "positive": s.get("positive_prompt"),
                    "negative": s.get("negative_prompt"),
                }
                for s in steps
            ],
            # Cheap: already read off the batch row (BatchStore._row_to_batch)
            # with no extra query — see BatchRead.planner_provider's docstring.
            "planner_provider": getattr(batch, "planner_provider", None),
        }
        try:
            await self.batch_store.merge_item_debug(item.id, payload)
        except Exception as e:  # noqa: BLE001 — diagnostics must never block the item
            logger.warning(
                f"[BATCH {batch.id}] failed to persist item debug for {item.id}: {e}"
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
        narrative = None
        story_title = None
        if scene is not None:
            outfit = scene.outfit.value if scene.outfit is not None else None
            accessories = [a.value for a in (scene.accessories or [])]
            beat_description = scene.beat_description
            arc_title = scene.arc_title
            narrative = scene.narrative
            story_title = scene.story_title

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
                # Story text surfaced for cheap reads (also inside scene_spec).
                "narrative": narrative,
                "story_title": story_title,
                # WS3.1 observability: per-step workflow tier/path/seed, captured
                # LIVE during execution (BatchPipelineWorker._process_job appends to
                # job.debug_meta via the shared engine's workflow_meta — see
                # workers/batch_pipeline_worker.py and services/workflow_meta.py).
                # `job` here is the actual in-memory Job object handed to us by
                # _handle_succeeded (job_manager.get_job(item.job_id)), so
                # debug_meta is cheaply reachable directly off it; BatchReconciler
                # holds no reference to the batch engine to fall back to, and none
                # is needed since this is the load-bearing, already-populated
                # signal. getattr guards test doubles / older in-memory jobs that
                # predate this field.
                "workflow_meta": getattr(job, "debug_meta", None) or {},
            },
        )
        await self.character_image_store.create_action(
            batch.character_id,
            character_image_id=image_id,
            media_url=image_url,
            label=action_label(beat_description, arc_title, item.scene_index),
            # The story beat reads out in chat when the user taps the quick action.
            suggested_prompt=narrative or beat_description,
            sort_order=item.scene_index,
            trigger_keywords=action_keywords(item.scene_spec, extra_texts=[beat_description]),
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
