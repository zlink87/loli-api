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

    # ComfyUI
    COMFYUI_SERVER_ADDRESS: str = "127.0.0.1:8188"
    COMFYUI_WORKFLOW_PATH: str = "workflows/amazing-z-photo_API_Create_CHAR.json"
    COMFYUI_EDIT_WORKFLOW_PATH: str = "workflows/edit.json"
    COMFYUI_OUTFIT_WORKFLOW_PATH: str = "workflows/test_final_API.json"
    COMFYUI_POSE_WORKFLOW_PATH: str = "workflows/edit_pose_action.json"
    COMFYUI_INPUT_DIR: str = "../ComfyUI/input"

    # Image Cache (for outfit edit)
    IMAGE_CACHE_TTL_SECONDS: int = 1800  # 30 minutes
    IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS: int = 60  # 1 minute

    # xAI Grok
    XAI_API_KEY: str = ""
    XAI_BASE_URL: str = "https://api.x.ai/v1"
    XAI_MODEL: str = "grok-4"

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
