"""
Character Image Generation API - Main Application Entry Point

A FastAPI service for generating character images using:
- xAI Grok-4 for prompt generation
- ComfyUI for image generation
- JWT authentication
- Local storage with signed URLs
"""
import asyncio
import logging
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from api.v1.router import api_router, configure_services
from services.job_manager import JobManager
from services.comfyui_client import ComfyUIClient
from services.runpod_client import RunPodServerlessClient
from services.prompt_generator import PromptGenerator
from services.storage_service import StorageService
from services.notification_service import NotificationService
from services.supabase_storage_service import SupabaseStorageService
from services.image_cache_service import ImageCacheService
from services.base_url_service import upload_base_url
from services import pose_assets
from workers.background_worker import BackgroundWorker, CleanupWorker
from workers.outfit_worker import OutfitBackgroundWorker
from workers.pose_worker import PoseBackgroundWorker
from workers.background_edit_worker import BackgroundEditWorker
from workers.pipeline_worker import PipelineBackgroundWorker
from workers.batch_pipeline_worker import BatchPipelineWorker
from services import supabase_db
from services.character_store import CharacterStore
from services.character_image_store import CharacterImageStore
from services.batch_store import BatchStore
from services.batch_orchestrator import BatchOrchestrator, BatchReconciler
from models.responses import HealthResponse, ErrorResponse
from models.enums import PoseType
from auth.dependencies import create_test_token

# Configure logging
log_dir = Path(settings.LOG_FILE).parent
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
    handlers=[
        logging.FileHandler(settings.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Suppress noisy third-party loggers
# logging.getLogger("httpx").setLevel(logging.WARNING)
# logging.getLogger("httpcore").setLevel(logging.WARNING)
# logging.getLogger("websockets").setLevel(logging.WARNING)
# logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("watchfiles").setLevel(logging.WARNING)

# Initialize services (singleton instances)
job_manager = JobManager(max_queue_size=settings.MAX_QUEUE_SIZE)

comfyui_client = ComfyUIClient(
    server_address=settings.COMFYUI_SERVER_ADDRESS
)

# RunPod Serverless client — GPU work runs on RunPod, not a local ComfyUI.
runpod_client = RunPodServerlessClient(
    api_key=settings.RUNPOD_API_KEY,
    endpoint_id=settings.RUNPOD_ENDPOINT_ID,
    base_url=settings.RUNPOD_BASE_URL,
    default_execution_timeout_ms=settings.RUNPOD_EXECUTION_TIMEOUT_MS,
    default_ttl_ms=settings.RUNPOD_TTL_MS,
)
job_manager.attach_runpod_client(runpod_client)

prompt_generator = PromptGenerator(
    api_key=settings.XAI_API_KEY,
    base_url=settings.XAI_BASE_URL,
    model=settings.XAI_MODEL
)

storage_service = StorageService(
    storage_dir=settings.STORAGE_DIR,
    signing_secret=settings.STORAGE_SIGNING_SECRET,
    base_url=settings.BASE_URL,
    default_expiry_minutes=settings.PREVIEW_EXPIRY_MINUTES
)

# Initialize Supabase storage if enabled
supabase_storage_service = None
if settings.USE_SUPABASE_STORAGE:
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
        supabase_storage_service = SupabaseStorageService(
            supabase_url=settings.SUPABASE_URL,
            supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY,
            bucket_name=settings.SUPABASE_BUCKET_NAME
        )
        logger.info("Supabase storage enabled")
    else:
        logger.warning("USE_SUPABASE_STORAGE=true but credentials missing, falling back to local storage")

notification_service = NotificationService(
    response_webhook_url=settings.GOOGLE_CHAT_RESPONSE_WEBHOOK_URL,
    payload_webhook_url=settings.GOOGLE_CHAT_PAYLOAD_WEBHOOK_URL
)

# Initialize image cache service for outfit edit
image_cache_service = ImageCacheService(
    ttl_seconds=settings.IMAGE_CACHE_TTL_SECONDS,
    cleanup_interval_seconds=settings.IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS,
    comfyui_input_dir=settings.COMFYUI_INPUT_DIR
)
logger.info(
    f"Image cache service initialized: "
    f"ttl={settings.IMAGE_CACHE_TTL_SECONDS}s, "
    f"cleanup_interval={settings.IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS}s"
)

# Initialize workers
background_worker = BackgroundWorker(
    job_manager=job_manager,
    comfyui_client=comfyui_client,
    prompt_generator=prompt_generator,
    storage_service=storage_service,
    workflow_path=settings.COMFYUI_WORKFLOW_PATH,
    notification_service=notification_service,
    supabase_storage_service=supabase_storage_service,
    runpod_client=runpod_client
)

cleanup_worker = CleanupWorker(
    job_manager=job_manager,
    storage_service=storage_service
)

outfit_worker = OutfitBackgroundWorker(
    job_manager=job_manager,
    comfyui_client=comfyui_client,
    storage_service=storage_service,
    workflow_path=settings.COMFYUI_OUTFIT_WORKFLOW_PATH,
    image_cache_service=image_cache_service,
    notification_service=notification_service,
    supabase_storage_service=supabase_storage_service,
    runpod_client=runpod_client
)

pose_worker = PoseBackgroundWorker(
    job_manager=job_manager,
    comfyui_client=comfyui_client,
    storage_service=storage_service,
    workflow_path=settings.COMFYUI_POSE_WORKFLOW_PATH,
    image_cache_service=image_cache_service,
    notification_service=notification_service,
    supabase_storage_service=supabase_storage_service,
    runpod_client=runpod_client
)

background_edit_worker = BackgroundEditWorker(
    job_manager=job_manager,
    comfyui_client=comfyui_client,
    storage_service=storage_service,
    workflow_path=settings.COMFYUI_OUTFIT_WORKFLOW_PATH,  # Same template as outfit
    image_cache_service=image_cache_service,
    notification_service=notification_service,
    supabase_storage_service=supabase_storage_service,
    runpod_client=runpod_client
)

pipeline_worker = PipelineBackgroundWorker(
    job_manager=job_manager,
    comfyui_client=comfyui_client,
    storage_service=storage_service,
    pose_workflow_path=settings.COMFYUI_POSE_WORKFLOW_PATH,
    outfit_workflow_path=settings.COMFYUI_OUTFIT_WORKFLOW_PATH,
    image_cache_service=image_cache_service,
    notification_service=notification_service,
    supabase_storage_service=supabase_storage_service,
    runpod_client=runpod_client
)

# --- Character Batches subsystem (optional; requires Supabase DB) ---
character_store = None
character_image_store = None
batch_store = None
batch_orchestrator = None
batch_reconciler = None
batch_engine = None
batch_workers = []

if supabase_db.is_configured():
    _db = supabase_db.get_supabase_db_client()
    character_store = CharacterStore(_db)
    character_image_store = CharacterImageStore(_db)
    batch_store = BatchStore(_db)
    batch_orchestrator = BatchOrchestrator(job_manager, character_store, batch_store, settings)
    batch_reconciler = BatchReconciler(
        job_manager, character_store, batch_store, settings,
        supabase_storage_service=supabase_storage_service,
        character_image_store=character_image_store,
    )
    # One shared step-execution engine (templates loaded once); M lightweight workers
    # drain the dedicated batch queue in parallel, isolated from interactive edits.
    batch_engine = PipelineBackgroundWorker(
        job_manager=job_manager,
        comfyui_client=comfyui_client,
        storage_service=storage_service,
        pose_workflow_path=settings.COMFYUI_POSE_WORKFLOW_PATH,
        outfit_workflow_path=settings.COMFYUI_OUTFIT_WORKFLOW_PATH,
        image_cache_service=image_cache_service,
        notification_service=notification_service,
        supabase_storage_service=supabase_storage_service,
        runpod_client=runpod_client,
    )
    for i in range(settings.BATCH_WORKER_POOL_SIZE):
        batch_workers.append(BatchPipelineWorker(
            job_manager=job_manager,
            engine=batch_engine,
            storage_service=storage_service,
            supabase_storage_service=supabase_storage_service,
            notification_service=notification_service,
            name=f"batch-{i}",
        ))
    logger.info(f"Character Batches enabled: {settings.BATCH_WORKER_POOL_SIZE} batch workers")
else:
    logger.info("Character Batches disabled (Supabase DB not configured)")


def _validate_production_settings() -> None:
    """
    Fail fast in production (DEBUG=false) if security-critical settings are missing
    or left at their insecure defaults. Prevents shipping weak secrets or an
    unconfigured GPU backend.
    """
    if settings.DEBUG:
        return  # development mode — allow defaults

    problems = []
    if settings.JWT_SECRET_KEY in ("", "change-this-secret-key-in-production"):
        problems.append("JWT_SECRET_KEY is unset or default")
    if settings.STORAGE_SIGNING_SECRET in ("", "change-this-signing-secret-in-production"):
        problems.append("STORAGE_SIGNING_SECRET is unset or default")
    if not settings.SUPABASE_JWT_SECRET:
        problems.append("SUPABASE_JWT_SECRET is required for user authentication")
    if settings.GPU_BACKEND == "runpod":
        if not settings.RUNPOD_API_KEY:
            problems.append("RUNPOD_API_KEY is required")
        if not settings.RUNPOD_ENDPOINT_ID:
            problems.append("RUNPOD_ENDPOINT_ID is required")
    if not settings.cors_allow_origins_list:
        problems.append("CORS_ALLOW_ORIGINS is empty (no frontend will be able to call the API)")
    if not settings.source_image_allowed_hosts_list:
        problems.append("SOURCE_IMAGE_ALLOWED_HOSTS is empty (SSRF allowlist disabled)")

    if problems:
        raise RuntimeError(
            "Refusing to start in production with insecure/missing settings:\n  - "
            + "\n  - ".join(problems)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown of background workers.
    """
    logger.info("=" * 50)
    logger.info("Character Image Generation API Starting...")
    logger.info("=" * 50)
    _validate_production_settings()
    logger.info(f"ComfyUI Server: {settings.COMFYUI_SERVER_ADDRESS}")
    logger.info(f"Storage Dir: {settings.STORAGE_DIR}")
    logger.info(f"Supabase Storage: {'Enabled' if settings.USE_SUPABASE_STORAGE else 'Disabled'}")
    logger.info(f"Outfit Workflow: {settings.COMFYUI_OUTFIT_WORKFLOW_PATH}")
    logger.info(f"Pose Workflow: {settings.COMFYUI_POSE_WORKFLOW_PATH}")
    logger.info(f"Edit Workflow: {settings.COMFYUI_EDIT_WORKFLOW_PATH}")
    logger.info(f"Image Cache TTL: {settings.IMAGE_CACHE_TTL_SECONDS}s")
    logger.info(f"Debug Mode: {settings.DEBUG}")

    # Preload pose reference assets into the in-process cache. Missing assets do
    # NOT block boot — pose/pipeline endpoints 422 cleanly until the references
    # are generated (scripts/generate_pose_refs.py); non-pose endpoints are
    # unaffected.
    total_poses = len(list(PoseType))
    installed = pose_assets.preload()
    logger.info(f"Pose references: {installed}/{total_poses} installed")
    missing = pose_assets.missing_pose_assets()
    if missing:
        logger.warning(
            "Pose references missing for: "
            + ", ".join(p.value for p in missing)
            + ". Pose and pipeline (with pose) requests will return 422 until "
            "scripts/generate_pose_refs.py is run."
        )

    # Configure services for API endpoints
    configure_services(
        job_manager,
        storage_service,
        notification_service,
        comfyui_client,
        settings.COMFYUI_EDIT_WORKFLOW_PATH,
        settings.COMFYUI_OUTFIT_WORKFLOW_PATH,
        settings.COMFYUI_POSE_WORKFLOW_PATH,
        image_cache_service,
        supabase_storage_service,
        runpod_client,
        character_store=character_store,
        batch_store=batch_store,
        batch_orchestrator=batch_orchestrator,
    )

    # Sync BASE_URL to Supabase so external services know our tunnel URL
    await upload_base_url(settings.BASE_URL, settings.SUPABASE_UPDATE_BASE_URL_API_KEY)

    # Start background workers
    try:
        await background_worker.start()
        await outfit_worker.start()
        await pose_worker.start()
        await background_edit_worker.start()
        await pipeline_worker.start()
        # await cleanup_worker.start()
        await image_cache_service.start_cleanup_worker()
        for w in batch_workers:
            await w.start()
        if batch_reconciler:
            await batch_reconciler.start()
        logger.info("Background workers started successfully")
    except Exception as e:
        logger.error(f"Failed to start background workers: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down...")
    await background_worker.stop()
    await outfit_worker.stop()
    await pose_worker.stop()
    await background_edit_worker.stop()
    await pipeline_worker.stop()
    for w in batch_workers:
        await w.stop()
    if batch_reconciler:
        await batch_reconciler.stop()
    await cleanup_worker.stop()
    await image_cache_service.stop_cleanup_worker()
    logger.info("Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Loli API — Character Image Generation",
    description="""
## Overview
Character image generation and editing API powered by ComfyUI and xAI Grok-4.
Part of the Loli AI ecosystem (admin panel + website + this API).

## Authentication
All endpoints (except `/health` and `/v1/preview`) require JWT Bearer token authentication.
Pass token as `Authorization: Bearer <token>` header.

## Endpoints

### Character Generation
- **POST /v1/generate/image** — Generate a new character image from persona attributes

### Image Editing
- **POST /v1/edit/outfit** — Change character outfit/clothing (47 outfit types, 3 nudity levels)
- **POST /v1/edit/pose** — Change character pose (16 pose types with reference images)
- **POST /v1/edit/background** — Change environment/scene (with natural lighting adaptation)
- **POST /v1/edit** — Chain multiple edits: pose → outfit → background

### Job Management
- **GET /v1/jobs/{jobId}** — Poll job status and get result URLs
- **DELETE /v1/jobs/{jobId}** — Cancel a queued job
- **GET /v1/preview/{token}** — Access generated image via signed URL

## Async Workflow
1. Submit a request → receive `jobId` (HTTP 202)
2. Poll `GET /v1/jobs/{jobId}` until `status` is `succeeded` or `failed`
3. Access `preview_url` from the succeeded job response

## Rate Limiting
- Maximum queue size: 100 jobs per type
- Jobs older than 24 hours are automatically cleaned up
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware — restrict to the configured allowlist (admin panel + website).
# A wildcard origin combined with credentials is invalid/insecure, so when no
# allowlist is set we fall back to no cross-origin access (deny) rather than "*".
_cors_origins = settings.cors_allow_origins_list
if not _cors_origins:
    logger.warning(
        "CORS_ALLOW_ORIGINS is empty — cross-origin browser requests will be blocked. "
        "Set it to the admin panel + website origins in production."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests and responses."""
    import time
    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time
    status_code = response.status_code

    # Log all requests, especially errors (4xx, 5xx)
    if status_code >= 400:
        logger.warning(
            f"[HTTP] {request.method} {request.url.path} | "
            f"Status: {status_code} | Duration: {duration:.3f}s | "
            f"Client: {request.client.host if request.client else 'unknown'}"
        )
    else:
        logger.info(
            f"[HTTP] {request.method} {request.url.path} | "
            f"Status: {status_code} | Duration: {duration:.3f}s"
        )

    return response


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors."""
    errors = exc.errors()
    detail = "; ".join([f"{e['loc'][-1]}: {e['msg']}" for e in errors])
    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "detail": detail,
            "statusCode": 422
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "detail": "An unexpected error occurred",
            "statusCode": 500
        }
    )


# Include API router
app.include_router(api_router, prefix="/v1")


# Health check endpoint (no auth required)
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
    description="Check service health and queue status. No authentication required."
)
async def health_check():
    """
    Health check endpoint.

    Returns:
    - Service status
    - Current queue size
    - API version
    """
    # Non-fatal RunPod endpoint probe: log-only, never affects the response body
    # or status code. Capped at 2s — the client's own retry/backoff loop could
    # otherwise hang this request for ~90s.
    if runpod_client.is_configured():
        try:
            await asyncio.wait_for(runpod_client.health(), timeout=2.0)
        except Exception as e:
            logger.warning(f"/health: RunPod endpoint probe failed: {e}")

    return HealthResponse(
        status="healthy",
        queueSize=job_manager.queue_size(),
        version="1.0.0"
    )


# Debug endpoints (only in debug mode)
if settings.DEBUG:
    @app.get("/debug/token", tags=["Debug"])
    async def get_debug_token(user_id: str = "test_user"):
        """Generate a test JWT token (DEBUG MODE ONLY)."""
        token = create_test_token(user_id)
        return {"token": token, "user_id": user_id}

    @app.get("/debug/storage-stats", tags=["Debug"])
    async def get_storage_stats():
        """Get storage statistics (DEBUG MODE ONLY)."""
        return storage_service.get_storage_stats()

    @app.get("/debug/comfyui-status", tags=["Debug"])
    async def get_comfyui_status():
        """Check ComfyUI server status (DEBUG MODE ONLY)."""
        return comfyui_client.check_server_status()

    @app.get("/debug/image-cache-stats", tags=["Debug"])
    async def get_image_cache_stats():
        """Get image cache statistics (DEBUG MODE ONLY)."""
        return image_cache_service.get_stats()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
