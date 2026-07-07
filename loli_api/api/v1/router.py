"""
API v1 router - aggregates all endpoint routers.
"""
from fastapi import APIRouter

from .endpoints import (
    generate, jobs, preview, edit, outfit, pose, background, pipeline,
    characters, batches,
)

# Create main API router
api_router = APIRouter()

# Include endpoint routers
api_router.include_router(generate.router)
api_router.include_router(jobs.router)
api_router.include_router(preview.router)
api_router.include_router(edit.router)
api_router.include_router(outfit.router)
api_router.include_router(pose.router)
api_router.include_router(background.router)
api_router.include_router(pipeline.router)
api_router.include_router(characters.router)
api_router.include_router(batches.router)


def configure_services(
    job_manager,
    storage_service,
    notification_service=None,
    comfyui_client=None,
    edit_workflow_path: str = "",
    outfit_workflow_path: str = "",
    pose_workflow_path: str = "",
    image_cache_service=None,
    supabase_storage_service=None,
    runpod_client=None,
    character_store=None,
    batch_store=None,
    batch_orchestrator=None,
):
    """
    Configure services for all endpoint modules.
    Called from main.py during startup.
    """
    generate.set_job_manager(job_manager)
    generate.set_notification_service(notification_service)
    jobs.set_job_manager(job_manager)
    preview.set_storage_service(storage_service)
    if comfyui_client:
        edit.set_comfyui_client(comfyui_client)
    if runpod_client:
        edit.set_runpod_client(runpod_client)
    edit.set_storage_service(storage_service)
    if notification_service:
        edit.set_notification_service(notification_service)
        outfit.set_notification_service(notification_service)
    if edit_workflow_path:
        edit.set_edit_workflow_path(edit_workflow_path)
    if outfit_workflow_path:
        outfit.set_outfit_workflow_path(outfit_workflow_path)
    outfit.set_job_manager(job_manager)
    pose.set_job_manager(job_manager)
    if notification_service:
        pose.set_notification_service(notification_service)
    if pose_workflow_path:
        pose.set_pose_workflow_path(pose_workflow_path)
    background.set_job_manager(job_manager)
    if notification_service:
        background.set_notification_service(notification_service)
    if outfit_workflow_path:
        background.set_background_workflow_path(outfit_workflow_path)
    pipeline.set_job_manager(job_manager)
    if notification_service:
        pipeline.set_notification_service(notification_service)
    # Story Batches (optional — only wired when the Supabase DB is configured)
    if character_store is not None:
        characters.set_character_store(character_store)
    if batch_store is not None:
        batches.set_batch_store(batch_store)
    if batch_orchestrator is not None:
        batches.set_orchestrator(batch_orchestrator)
