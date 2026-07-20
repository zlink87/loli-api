"""
API v1 router - aggregates all endpoint routers.
"""
from fastapi import APIRouter

from .endpoints import (
    generate, jobs, preview, edit, outfit, pose, background, pipeline,
    characters, batches, video, video_batches, persona, nude_base, scenes, options,
    trait_profile,
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
api_router.include_router(video.router)
api_router.include_router(video_batches.router)
api_router.include_router(persona.router)
api_router.include_router(nude_base.router)
api_router.include_router(scenes.router)
api_router.include_router(options.router)
api_router.include_router(trait_profile.router)


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
    character_image_store=None,
    batch_store=None,
    batch_orchestrator=None,
    video_batch_store=None,
    video_batch_orchestrator=None,
    persona_writer=None,
    motion_writer=None,
    chat_persona_store=None,
    nude_base_store=None,
    scene_writer=None,
    trait_profile_writer=None,
    trait_profile_store=None,
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
    # Trait-aware standalone edits (Phase 4): the outfit/pose/background/pipeline
    # edit endpoints can auto-populate identityAnchors from a characterId. Wired
    # only when the Supabase-backed character store exists; the endpoints degrade
    # gracefully (proceed without anchors) when it is absent.
    if character_store is not None:
        outfit.set_character_store(character_store)
        pose.set_character_store(character_store)
        background.set_character_store(character_store)
        pipeline.set_character_store(character_store)
    # WS-T trait-aware edits: the outfit endpoint surfaces a never-wears advisory, and
    # the background/pipeline endpoints resolve a HOME-like location's interiorStyle/
    # colorPalette from the character's trait profile. Wired only when the Supabase-
    # backed trait store exists; the endpoints degrade gracefully when it is absent.
    if trait_profile_store is not None:
        outfit.set_trait_profile_store(trait_profile_store)
        background.set_trait_profile_store(trait_profile_store)
        pipeline.set_trait_profile_store(trait_profile_store)
    # Story Batches (optional — only wired when the Supabase DB is configured)
    if character_store is not None:
        characters.set_character_store(character_store)
    if character_image_store is not None:
        characters.set_character_image_store(character_image_store)
    if batch_store is not None:
        batches.set_batch_store(batch_store)
    if batch_orchestrator is not None:
        batches.set_orchestrator(batch_orchestrator)
    # Per-character Video Batches (optional — only wired when the Supabase DB is
    # configured AND the lightning video graph + dedicated RunPod video endpoint are
    # set; the routes 503 until both stores are injected). See main.py's gate.
    if video_batch_store is not None:
        video_batches.set_video_batch_store(video_batch_store)
    if video_batch_orchestrator is not None:
        video_batches.set_video_batch_orchestrator(video_batch_orchestrator)
    # Persona/bio writer (Feature 1). Writer works keyless (deterministic); persistence
    # is Supabase-gated (character_store + chat_persona_store).
    if persona_writer is not None:
        persona.set_persona_writer(persona_writer)
    if character_store is not None:
        persona.set_character_store(character_store)
    if chat_persona_store is not None:
        persona.set_chat_persona_store(chat_persona_store)
    # POST /v1/characters can optionally generate the persona in the same call
    # (CharacterCreate.generate_persona) — reuses these same already-built instances.
    if persona_writer is not None:
        characters.set_persona_writer(persona_writer)
    if chat_persona_store is not None:
        characters.set_chat_persona_store(chat_persona_store)
    # Nude base (per-character identity-locked undressed render) — admin, Supabase-gated.
    # Batches auto-use it once generated (activated in BatchReconciler); the endpoints
    # 503 until the stores are wired, so nothing changes for characters without one.
    nude_base.set_job_manager(job_manager)
    if character_store is not None:
        nude_base.set_character_store(character_store)
    if nude_base_store is not None:
        nude_base.set_nude_base_store(nude_base_store)
        # Part 3: POST /v1/characters (+ /bulk) auto-submits a nude base on creation,
        # reusing the SAME t2i submit path as POST /characters/{id}/nude-base. Wired
        # only when the nude-base store exists; the submitter self-gates on the job
        # manager + settings.NUDE_BASE_T2I, and characters degrades to a no-op without it.
        characters.set_nude_base_submitter(nude_base.submit_nude_base_for_new_character)
    # Reels (image-to-video) — admin, Supabase-gated
    video.set_job_manager(job_manager)
    if notification_service:
        video.set_notification_service(notification_service)
    if character_image_store is not None:
        video.set_character_image_store(character_image_store)
    if motion_writer is not None:
        video.set_motion_writer(motion_writer)
    # Scene randomizer (Batch Character Creation) — admin, stateless, works keyless
    # (deterministic fallback) and uses Venice when VENICE_API_KEY is set.
    if scene_writer is not None:
        scenes.set_scene_writer(scene_writer)
    # Character trait profiles (WS-B). Writer works keyless (deterministic tables);
    # persistence is Supabase-gated (character_store + trait_profile_store).
    if trait_profile_writer is not None:
        trait_profile.set_trait_profile_writer(trait_profile_writer)
    if character_store is not None:
        trait_profile.set_character_store(character_store)
    if trait_profile_store is not None:
        trait_profile.set_trait_profile_store(trait_profile_store)
    # Trait-aware character generation (B3): POST /v1/generate/image|batch can
    # auto-fill wardrobeStyles/demeanor from a characterId. Wired only when the
    # Supabase-backed trait store exists; degrades gracefully when absent.
    if trait_profile_store is not None:
        generate.set_trait_profile_store(trait_profile_store)
    # Culture-aware generation (Stage 3): the same endpoints adopt a character's stored
    # persona.culture (then fall back to it for wardrobeStyles/demeanor). Wired only when
    # the Supabase-backed character store exists; degrades gracefully when absent.
    if character_store is not None:
        generate.set_character_store(character_store)
    # POST /v1/characters can optionally generate the trait profile in the same call
    # (CharacterCreate.generate_traits) — reuses these same already-built instances.
    if trait_profile_writer is not None:
        characters.set_trait_profile_writer(trait_profile_writer)
    if trait_profile_store is not None:
        characters.set_trait_profile_store(trait_profile_store)
