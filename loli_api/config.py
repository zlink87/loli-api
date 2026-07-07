"""
Application configuration using Pydantic Settings.
Loads from environment variables and .env file.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Server
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8001
    DEBUG: bool = False

    # JWT Authentication
    JWT_SECRET_KEY: str = "change-this-secret-key-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # ComfyUI (workflow templates are still loaded locally and sent to RunPod;
    # COMFYUI_SERVER_ADDRESS is only used for the optional local-dev fallback.)
    COMFYUI_SERVER_ADDRESS: str = "127.0.0.1:8188"
    COMFYUI_WORKFLOW_PATH: str = "workflows/amazing-z-photo_API_Create_CHAR.json"
    COMFYUI_EDIT_WORKFLOW_PATH: str = "workflows/edit.json"
    COMFYUI_OUTFIT_WORKFLOW_PATH: str = "workflows/test_final_API.json"
    COMFYUI_POSE_WORKFLOW_PATH: str = "workflows/edit_pose_action.json"
    COMFYUI_VIDEO_WORKFLOW_PATH: str = "workflows/wan_i2v.json"
    COMFYUI_INPUT_DIR: str = "../ComfyUI/input"

    # GPU execution backend: "runpod" (serverless) or "local" (legacy WebSocket)
    GPU_BACKEND: str = "runpod"

    # RunPod Serverless
    RUNPOD_API_KEY: str = ""
    RUNPOD_ENDPOINT_ID: str = ""
    RUNPOD_BASE_URL: str = "https://api.runpod.ai/v2"
    RUNPOD_EXECUTION_TIMEOUT_MS: int = 600_000   # policy.executionTimeout (per-job cap)
    RUNPOD_TTL_MS: int = 3_600_000               # policy.ttl (total job lifespan)
    RUNPOD_POLL_INTERVAL_SECONDS: int = 5        # reconciler poll cadence
    # Video (reel) jobs run for minutes and cold-load ~33 GB of WAN models, so
    # they need much longer caps than image jobs.
    RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS: int = 1_800_000   # 30 min per-job cap
    RUNPOD_VIDEO_TTL_MS: int = 5_400_000                 # 90 min total lifespan

    # Image Cache (for outfit edit)
    IMAGE_CACHE_TTL_SECONDS: int = 1800  # 30 minutes
    IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS: int = 60  # 1 minute

    # Venice (LLM provider — OpenAI-compatible, uncensored). Used for both the
    # single-image scene writer and the batch story planner. Left unset by default
    # (deterministic assembler + deterministic planner work without it).
    VENICE_API_KEY: str = ""
    VENICE_BASE_URL: str = "https://api.venice.ai/api/v1"
    VENICE_MODEL: str = "venice-uncensored"

    # Character generation: run the second detail-refine pass by default
    # (upscale-model round trip + refine steps; same output resolution,
    # ~+50-100% GPU time per image). Requires 4x_Nickelback_70000G.safetensors
    # in upscale_models/ on the RunPod volume — set false until it's uploaded.
    # Per-request override: output.hires.
    GENERATION_HIRES_DEFAULT: bool = True

    # Anthropic Claude (story planner — SFW-only fallback provider).
    # Claude refuses explicit adult content, so it is never routed NSFW batches;
    # it stays a guarded, optional SFW planner. Left unset by default.
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5"

    # Story Batches (persona-driven batch generation).
    # Preferred planner provider: "venice" | "deterministic" | "claude" | "manual".
    # Empty -> auto-select (venice primary, deterministic fallback, claude SFW-only).
    STORY_PLANNER_PROVIDER: str = ""
    # Number of dedicated batch pipeline workers (real parallelism for batches,
    # isolated from interactive /v1/edit traffic). Keep RunPod max_workers >= this.
    BATCH_WORKER_POOL_SIZE: int = 3
    # Max in-flight items per batch (fairness: stops one batch monopolizing the queue).
    BATCH_MAX_INFLIGHT: int = 3
    # Per-item retry attempts before an item is marked failed.
    BATCH_ITEM_MAX_ATTEMPTS: int = 2
    # Rough per-step wall-clock estimate (seconds) used only for BatchEstimate.
    RUNPOD_AVG_STEP_SECONDS: int = 60
    # Optional GPU cost rate (USD/second) for BatchEstimate.est_cost_usd. 0 -> omit.
    RUNPOD_GPU_USD_PER_SECOND: float = 0.0
    # Comma-separated allowlist of admin user IDs (JWT `sub`). Combined with the
    # app_metadata.role == "admin" claim check in require_admin.
    ADMIN_USER_IDS: str = ""

    # Storage
    STORAGE_DIR: str = "./storage/images"
    STORAGE_SIGNING_SECRET: str = "change-this-signing-secret-in-production"
    BASE_URL: str = "http://localhost:8001"
    PREVIEW_EXPIRY_MINUTES: int = 60

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # Queue
    MAX_QUEUE_SIZE: int = 100

    # Notifications
    GOOGLE_CHAT_RESPONSE_WEBHOOK_URL: str = ""
    GOOGLE_CHAT_PAYLOAD_WEBHOOK_URL: str = ""

    # Supabase Storage
    USE_SUPABASE_STORAGE: bool = False
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_BUCKET_NAME: str = "images_generated"
    SUPABASE_UPDATE_BASE_URL_API_KEY: str = ""

    # Supabase Auth (verify user JWTs issued by Supabase, instead of /debug/token)
    # Symmetric JWT secret from the Supabase project (Settings → API → JWT secret).
    SUPABASE_JWT_SECRET: str = ""
    SUPABASE_JWT_AUDIENCE: str = "authenticated"

    # Supabase Storage S3-compatible endpoint (used by the RunPod worker to upload
    # output images directly). Mirror these onto the RunPod endpoint env vars.
    SUPABASE_S3_ENDPOINT: str = ""               # https://{project}.supabase.co/storage/v1/s3
    SUPABASE_S3_REGION: str = "us-east-1"
    SUPABASE_S3_ACCESS_KEY_ID: str = ""
    SUPABASE_S3_SECRET_ACCESS_KEY: str = ""

    # Security
    # Comma-separated allowlist of CORS origins (admin panel + website). Empty -> deny cross-origin.
    CORS_ALLOW_ORIGINS: str = ""
    # Comma-separated allowlist of hosts permitted as source_image (e.g. the Supabase domain).
    SOURCE_IMAGE_ALLOWED_HOSTS: str = ""

    @property
    def cors_allow_origins_list(self) -> list[str]:
        """Parsed CORS origin allowlist."""
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    @property
    def source_image_allowed_hosts_list(self) -> list[str]:
        """Parsed source_image host allowlist (lowercased)."""
        return [h.strip().lower() for h in self.SOURCE_IMAGE_ALLOWED_HOSTS.split(",") if h.strip()]

    @property
    def admin_user_ids_list(self) -> list[str]:
        """Parsed admin user-id allowlist (JWT `sub` values)."""
        return [u.strip() for u in self.ADMIN_USER_IDS.split(",") if u.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
