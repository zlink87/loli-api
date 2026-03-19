# Loli API — Development Guide

## Project Structure

```
loli_api/
├── main.py                         # App entry point, service init, lifespan
├── config.py                       # Pydantic Settings (loads from .env)
├── api/
│   └── v1/
│       ├── router.py               # Aggregates all endpoint routers
│       └── endpoints/
│           ├── generate.py         # POST /v1/generate/image
│           ├── outfit.py           # POST /v1/edit/outfit
│           ├── pose.py             # POST /v1/edit/pose
│           ├── background.py       # POST /v1/edit/background
│           ├── pipeline.py         # POST /v1/pipeline
│           ├── edit.py             # Legacy edit endpoint
│           ├── jobs.py             # GET/DELETE /v1/jobs/{jobId}
│           └── preview.py          # GET /v1/preview/{token}
├── workers/
│   ├── base_worker.py              # BaseEditWorker — abstract base for all edit workers
│   ├── background_worker.py        # Image generation worker + cleanup worker
│   ├── outfit_worker.py            # Outfit edit worker
│   ├── pose_worker.py              # Pose edit worker
│   ├── background_edit_worker.py   # Background/scene edit worker
│   └── pipeline_worker.py          # Chains pose → outfit → background
├── services/
│   ├── comfyui_client.py           # WebSocket client for ComfyUI
│   ├── prompt_generator.py         # xAI Grok-4 prompt generation
│   ├── job_manager.py              # In-memory job queue (asyncio.Queue)
│   ├── storage_service.py          # Local storage + signed URLs
│   ├── supabase_storage_service.py # Supabase cloud storage
│   ├── notification_service.py     # Google Chat webhook notifications
│   ├── image_cache_service.py      # Source image cache (avoids re-download)
│   ├── face_identity_service.py    # Face crop extraction (Phase 1)
│   └── base_url_service.py         # Syncs BASE_URL to Supabase
├── models/
│   ├── enums.py                    # All enum types (outfits, poses, etc.)
│   ├── requests.py                 # Pydantic request models
│   └── responses.py                # Pydantic response models
├── auth/
│   ├── jwt_handler.py              # JWT encode/decode
│   └── dependencies.py             # FastAPI auth dependencies
└── workflows/                      # ComfyUI workflow JSON files
    ├── amazing-z-photo_API_Create_CHAR.json
    ├── test_final_API.json
    ├── edit_pose_action.json
    ├── edit_final_AIO.json
    └── edit.json
```

## Key Services

| Service | Purpose |
|---------|---------|
| `ComfyUIClient` | WebSocket connection to ComfyUI. Uploads images, executes workflows, retrieves outputs. |
| `PromptGenerator` | Calls xAI Grok-4 to convert PersonaOptions into detailed image prompts. |
| `JobManager` | In-memory job registry with per-type `asyncio.Queue`. Tracks status, progress, results. |
| `StorageService` | Saves images to local filesystem, generates HMAC-signed preview URLs with expiry. |
| `SupabaseStorageService` | Uploads images to Supabase Storage bucket. Used when `USE_SUPABASE_STORAGE=true`. |
| `NotificationService` | Sends job completion/failure notifications to Google Chat via webhooks. |
| `ImageCacheService` | Caches downloaded source images in ComfyUI's input dir. TTL-based with background cleanup. |
| `FaceIdentityService` | Extracts face crops for identity preservation (Phase 1 — extraction only, no workflow integration yet). |

## Worker Pattern

All edit workers extend `BaseEditWorker` (`workers/base_worker.py`), which provides:

- **Lifecycle:** `start()` / `stop()` — manages asyncio task and workflow loading
- **Worker loop:** Dequeues jobs, skips cancelled ones, dispatches to `_process_job()`
- **Image handling:** `download_and_upload_image()` — downloads source (with cache), uploads to ComfyUI
- **OOM retry:** `execute_with_oom_retry()` — retries workflow on CUDA OOM (configurable attempts)
- **Output saving:** `save_output_image()` — saves to Supabase or local storage
- **Error handling:** `handle_job_failure()` — categorizes errors, updates status, sends notification

### Subclass contract

Implement these four members:

```python
class MyEditWorker(BaseEditWorker):
    @property
    def worker_name(self) -> str:
        return "MyEdit"

    async def _get_next_job(self) -> str:
        return await self.job_manager.my_edit_queue.get()

    def _mark_job_done(self) -> None:
        self.job_manager.my_edit_queue.task_done()

    async def _process_job(self, job: Job) -> None:
        # 1. Download/upload source image
        # 2. Prepare workflow (inject nodes)
        # 3. Execute with OOM retry
        # 4. Save output
        # 5. Update job status
        ...
```

## Adding a New Edit Type

1. **Add enums** in `models/enums.py` (e.g., new `FilterType`)
2. **Add request model** in `models/requests.py`
3. **Create endpoint** in `api/v1/endpoints/my_edit.py`:
   - Define the route (`POST /v1/edit/my_edit`)
   - Validate request, create job, enqueue it
4. **Create worker** in `workers/my_edit_worker.py`:
   - Extend `BaseEditWorker`
   - Implement `_process_job()` with workflow preparation logic
5. **Add workflow JSON** in `loli_api/workflows/`
6. **Register in router** — add to `api/v1/router.py` imports and `configure_services()`
7. **Wire up in main.py** — instantiate worker, start/stop in lifespan
8. **Add queue** in `JobManager` if needed (new `asyncio.Queue`)

## ComfyUI Workflows

Workflow files are JSON exports from ComfyUI's web editor, stored in `loli_api/workflows/`. Each worker loads its workflow template at startup and injects parameters at runtime.

Workflow preparation happens in each worker's `_process_job()` method via `prepare_*_workflow()` functions that modify the JSON nodes:

- Set input image filename
- Set prompt text
- Set seed value
- Configure model-specific parameters (steps, CFG, denoise)

To create or modify a workflow:
1. Open ComfyUI web UI at `http://localhost:8188`
2. Build/edit the workflow visually
3. Export as API format JSON
4. Save to `loli_api/workflows/`
5. Write the `prepare_*_workflow()` function that maps request params to node values

## Configuration

All config is in `config.py` using Pydantic Settings. Values load from environment variables and `.env` file. Access anywhere via:

```python
from config import settings
settings.COMFYUI_SERVER_ADDRESS  # "127.0.0.1:8188"
```

## Debug Mode

Set `DEBUG=true` to enable:
- Uvicorn auto-reload
- Debug endpoints: `GET /debug/token`, `GET /debug/storage-stats`, `GET /debug/comfyui-status`, `GET /debug/image-cache-stats`
