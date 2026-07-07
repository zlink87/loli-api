# Character Batches — integration reference

> **STATUS: fully wired and verified** — the app imports cleanly, all routes
> register, and the unit-test suite passes. Batches write to the REAL product
> schema (`characters`, `character_images`, `chat_persona_actions`); the old
> `story_*` tables are superseded. Operator steps that still matter: **section 4
> (env vars), section 5 (run the SQL migration), section 6 (verify)**.

## 0. What a batch produces (the data contract)

One batch run against a character produces rows the chat app reads directly:

| Table | Rows | Written by |
|---|---|---|
| `characters` | 1 (created earlier via `POST /v1/characters`, `status='draft'`) | `CharacterStore` — persona in flat typed columns, `bio` → `context`, hero photo → `profile_image_url`/`avatar_image_url`/`chat_avatar_url` |
| `character_images` | 1 per succeeded item (`image_type='gallery'`) | `CharacterImageStore` via the reconciler |
| `chat_persona_actions` | 1 per photo (quick action, `media_type='image'`, `trigger_type='manual'`, `sort_order=scene_index`) | `CharacterImageStore` via the reconciler |
| `character_batches` / `character_batch_items` | job tracking (status/progress/retries/scene specs) | `BatchStore` |

Ordering guarantee: an item is only marked `succeeded` AFTER its
`character_images` + quick-action rows exist; `character_batch_items.character_image_id`
is the idempotency guard (no duplicate gallery rows on retries/restarts).

The API is **single-admin**: there is no `owner_id` anywhere; auth is
`require_admin` only. Internal GPU jobs are owned by the constant
`BATCH_JOB_OWNER = "batch-admin"` (`services/batch_orchestrator.py`).

`likes`/`dislikes` are **batch-level** knobs now (fields on the
`POST /v1/characters/{id}/batches` body) — they bias scene planning only and are
persisted on `character_batches`, not on the character.

Every edit step of every item gets the batch's photographic finish
(`controls.photo_style`, default `polished`) appended to its prompt — see
`prompt_constants.EDIT_PHOTO_STYLE_SUFFIXES` / `apply_edit_photo_style` and
`pipeline_worker._build_step_workflow`. `candid_phone` preserves the legacy raw
look byte-identically.

## 1. `loli_api/services/job_manager.py` — dedicated batch queue

`batch_pipeline_queue` + the `batch_pipeline_edit` job type (`batjob_` prefix),
with `get_next_batch_pipeline_job()` / `mark_batch_pipeline_done()` and
queue-size branches. Isolates batch GPU work from interactive edits.

## 2. `loli_api/api/v1/router.py` — routers + service wiring

`characters.router` and `batches.router` are included; `configure_services(...)`
takes `character_store` / `batch_store` / `batch_orchestrator` and injects them
into the endpoint modules when the Supabase DB is configured (otherwise the
endpoints return 503).

## 3. `loli_api/main.py` — the batch subsystem singletons

Built only when `supabase_db.is_configured()`:

```python
_db = supabase_db.get_supabase_db_client()
character_store = CharacterStore(_db)
character_image_store = CharacterImageStore(_db)   # writes character_images + quick actions
batch_store = BatchStore(_db)
batch_orchestrator = BatchOrchestrator(job_manager, character_store, batch_store, settings)
batch_reconciler = BatchReconciler(
    job_manager, character_store, batch_store, settings,
    supabase_storage_service=supabase_storage_service,
    character_image_store=character_image_store,
)
# one shared PipelineBackgroundWorker engine + BATCH_WORKER_POOL_SIZE BatchPipelineWorkers
```

`lifespan` starts/stops the batch workers and the reconciler alongside the other
background workers, and passes the stores into `configure_services(...)`.

## 4. Environment (`.env`) — settings (all have safe defaults)

```
# Admins allowed to use /v1/characters and /v1/batches (JWT `sub`, comma-separated).
# Alternatively set app_metadata.role = "admin" on the Supabase user.
ADMIN_USER_IDS=

# Batch execution
BATCH_WORKER_POOL_SIZE=3        # keep RunPod max_workers >= this
BATCH_MAX_INFLIGHT=3            # per-batch fairness window
BATCH_ITEM_MAX_ATTEMPTS=2
RUNPOD_AVG_STEP_SECONDS=60      # estimate only
RUNPOD_GPU_USD_PER_SECOND=0     # >0 to surface est_cost_usd

# Story planner
STORY_PLANNER_PROVIDER=         # empty = auto (grok primary, deterministic fallback)
ANTHROPIC_API_KEY=              # optional, SFW-only planner
ANTHROPIC_MODEL=claude-sonnet-4-5
```

`SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` must be set (already used for storage) —
they also back the DB. `USE_SUPABASE_STORAGE=true` is recommended so batch outputs
land in the `batch_edits/` folder with stable public URLs.

The character's hero photo host must be on the `SOURCE_IMAGE_ALLOWED_HOSTS`
allowlist (normally your Supabase storage host) — this includes characters whose
`profile_image_url` was set by the other admin app.

## 5. Run the DB migration

Apply `loli_api/migrations/0002_character_batches.sql` in the Supabase SQL editor
(or CLI). It creates ONLY the job-tracking tables `character_batches` and
`character_batch_items` (FK → the real `public.characters`); it does NOT touch
`characters` / `character_images` / `chat_persona_actions`, which must already
exist. Idempotent — safe to re-run. The commented `drop table story_*` block at
the bottom removes the superseded 0001 tables when you're ready.

## 6. Verify

```bash
# Unit tests (offline; no RunPod / Supabase needed)
python -m pytest loli_api/tests/ -q

# End-to-end dry run (no GPU spend):
#   POST /v1/characters                     -> characters row (status='draft')
#   POST /v1/characters/{id}/batches        {"count": 6, "dry_run": true,
#                                            "likes": ["coffee"], "dislikes": ["gyms"]}
#   GET  /v1/batches/{id}                   -> 6 planned, persisted items
#   POST /v1/batches/{id}/launch            -> generates the previewed plan
# After completion: character_images has N gallery rows, chat_persona_actions has
# N matching quick actions, and character_batch_items.character_image_id is set.
```
