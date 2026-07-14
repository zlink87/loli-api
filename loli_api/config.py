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
    # V2 crop-and-stitch outfit graph (ClothesSegment/crop-and-stitch). EMPTY keeps
    # the interactive outfit worker on V1 (test_final_API.json). Set to
    # "workflows/outfit_cropstitch_API.json" to cut the /v1/edit/outfit path over to
    # V2 — the preparer auto-detects the graph, and background/pose/batch stay on V1
    # for rollback. Requires the worker image's staged nodes (redeploy first).
    COMFYUI_OUTFIT_WORKFLOW_PATH_V2: str = ""
    # Tier A quality path: FULL (non-distilled) Qwen-Image-Edit-2511 + realism/NSFW
    # LoRAs, loaded natively (UNet+CLIP+VAE) at >20 steps / cfg 2.5 instead of the
    # 4-8 step distilled Rapid-AIO. EMPTY keeps the fast Rapid V2 path. Set to
    # "workflows/outfit_cropstitch_2511full_API.json" to cut the interactive outfit +
    # /v1/edit pipeline over to the full model. Takes precedence over _V2. Same
    # crop-and-stitch graph (auto-detected), so no code change; background/batch stay
    # on the fast path for cost. REQUIRES the worker image to stage the 2511 model +
    # LoRA files first (see download2.sh Tier-A section) — redeploy before enabling.
    COMFYUI_OUTFIT_WORKFLOW_PATH_2511: str = ""
    # WS3.2: batch-ONLY outfit workflow path override, independent of the interactive
    # /v1/edit/outfit and /v1/edit pipeline engines' own tier-precedence chain above.
    # EMPTY (default) -> the batch engine follows that SAME chain (_2511 or _V2 or V1;
    # see main.py). Set this only when the batch engine specifically needs a different
    # template than the interactive engines (e.g. a staged rollout to batches first).
    COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH: str = ""
    COMFYUI_POSE_WORKFLOW_PATH: str = "workflows/edit_pose_action.json"
    # D3 quality path: run the pose (re-pose) step on the FULL (non-distilled)
    # Qwen-Image-Edit-2511 stack + realism/NSFW LoRAs at 20 steps / cfg 2.5 with a
    # LIVE negative, instead of the distilled Rapid-AIO v1 graph (edit_pose_action.json:
    # 4 steps, cfg 1, negatives inert via ConditioningZeroOut). EMPTY (default) keeps
    # the v1 graph. Set to "workflows/pose_2511_API.json" to cut the pose step over to
    # the 2511 tier — the preparer auto-detects the graph (same node-id contract as v1)
    # and only then wires the negative. Takes precedence over COMFYUI_POSE_WORKFLOW_PATH
    # (mirrors the outfit _2511 precedence). REQUIRES the worker image to stage the 2511
    # model + LoRA files first (same five files as the outfit 2511 tier — see
    # docs/OPS_OUTFIT_TIER_2511.md §4); redeploy before enabling.
    COMFYUI_POSE_WORKFLOW_PATH_2511: str = ""
    COMFYUI_VIDEO_WORKFLOW_PATH: str = "workflows/wan_i2v.json"
    # Frame-interpolation variant of the reel workflow (RIFE/FILM 16->32fps, kills
    # judder). EMPTY (default) -> OFF: the video worker uses COMFYUI_VIDEO_WORKFLOW_PATH.
    # Point this at "workflows/wan_i2v_interp.json" ONLY once the RunPod worker image
    # is confirmed to have the FrameInterpolate node + a staged RIFE/FILM weight
    # (a deploy-side action) — otherwise generation will fail on that worker.
    COMFYUI_VIDEO_INTERP_WORKFLOW_PATH: str = ""
    # First-last-frame (FLF2V) variant of the reel workflow: conditions WAN on both
    # a start frame (source still) and a controlled END frame so the clip resolves
    # on an in-focus, camera-facing beat and identity drift drops. EMPTY (default)
    # -> OFF: the video worker never takes the FLF2V branch regardless of the
    # per-request useFlf2v flag. Point this at "workflows/wan_i2v_flf2v.json" ONLY
    # once the RunPod worker image is confirmed to have the WanFirstLastFrameToVideo
    # node (a deploy-side action) — otherwise generation will fail on that worker.
    COMFYUI_VIDEO_FLF2V_WORKFLOW_PATH: str = ""
    COMFYUI_INPUT_DIR: str = "../ComfyUI/input"

    # WS4.1/4.2 — pose face-alignment diagnostics (flag-gated, default OFF).
    # Root-causing small face misalignments on posed batch items: every posed
    # item's face comes from this step (full-frame regen + ReActorFaceSwap,
    # node 200), so it's the final word on the face. WS4.1 captures the
    # pre-ReActor frame (node 8 VAEDecode) alongside the normal post-swap
    # SaveImage (node 164) so the two can be A/B'd to classify the cause
    # (inswapper low-res paste / codeformer over-restoration / blend-seam /
    # head-angle mismatch). WS4.2 exposes the ReActor restore-visibility /
    # codeformer-weight knobs (node 200) without a code change, once 4.1's
    # data suggests they're the lever to pull. CodeFormer semantics are easy to
    # get backwards: a HIGH codeformer_weight stays FAITHFUL to the swapped input
    # face (less hallucinated repaint), while a LOW weight lets CodeFormer
    # smooth/hallucinate more (the plastic look); restore_visibility is how
    # strongly the CodeFormer-restored face is blended over the raw swap, so a
    # LOWER visibility keeps more of the raw swap's real skin texture. The pose
    # graphs now bake 0.65 restore-visibility / 0.7 codeformer-weight. The -1.0
    # sentinel on the float knobs means "leave those baked values alone" (0.0 is
    # itself a valid override, so unlike the request-model fields elsewhere,
    # None can't double as the "no override" marker on a typed float setting).
    POSE_DEBUG_SAVE_PRE_REACTOR: bool = False
    POSE_REACTOR_RESTORE_VISIBILITY: float = -1.0
    POSE_REACTOR_CODEFORMER_WEIGHT: float = -1.0
    # Dark asset (07-14, ships OFF): sharper face-restore model for the pose ReActor
    # pass (node 200's face_restore_model). GPEN-BFR is sharper/less waxy than the
    # template's baked CodeFormer. Empty (default) leaves node 200 untouched -> the
    # template's baked model (codeformer-v0.1.0.pth) keeps loading, byte-identical
    # behavior. Set to e.g. "GPEN-BFR-512.onnx" ONLY AFTER that file exists in
    # facerestore_models/ on the RunPod volume (download2.sh §8e/§10f; see
    # docs/RUNPOD_SETUP.md "Dark quality assets") — otherwise the worker fails to
    # load the model.
    POSE_REACTOR_FACE_RESTORE_MODEL: str = ""
    # Pose output resolution (node 93, ImageScaleToTotalPixels.megapixels). 0.0
    # (default) keeps the pose template's baked 1.0 MP canvas; a value > 0 scales
    # the pose-reference-derived latent to that many megapixels before the full
    # re-diffusion, so the single-pass batch path can render at a higher output
    # resolution (prod sets 1.74 ~ 1080x1620). No-op when the graph lacks node 93.
    POSE_OUTPUT_MEGAPIXELS: float = 0.0

    # WS-N2 (Natural de-synthetic): per-style LoRA strengths for the pose graph's LoRA
    # stack — node 304 (URP realism), 305 (NSFW), 306 (skin) on the skinlora tier. The
    # baked strengths (0.8 / 0.65 / 1.0) apply identically to EVERY style, so natural and
    # candid_phone batches still render editorial/contrasty. For those two styles the
    # pipeline dials the whole stack DOWN with these values; polished/studio/None leave
    # the baked strengths untouched. The -1.0 sentinel means "leave that node's baked
    # strength alone" (same convention as the POSE_REACTOR_* knobs above — 0.0 is itself a
    # valid strength, so None can't double as the no-override marker on a typed float).
    # No-op on the v1 Rapid pose graph, which carries none of these LoRA nodes.
    NATURAL_LORA_URP: float = 0.6
    NATURAL_LORA_NSFW: float = 0.5
    NATURAL_LORA_SKIN: float = 0.7

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
    # Dedicated serverless endpoint for video (reel) jobs. EMPTY (default) -> reels
    # share RUNPOD_ENDPOINT_ID like every other job type. The main endpoint's fleet
    # is all NVIDIA A40s; WAN 2.2 14B two-stage (20+20 steps, 81 frames) can't finish
    # there inside RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS, so every reel dies with
    # "executionTimeout exceeded". Set this to a second endpoint id in the SAME
    # datacenter as the models network volume (so it can attach the volume), backed
    # by an fp8-capable fast GPU (L40S / RTX 6000 Ada / H100), so reels stop landing
    # on A40-class workers.
    RUNPOD_VIDEO_ENDPOINT_ID: str = ""

    # Batch (Story/trait batch) pipeline items run each step as a separate RunPod
    # job, and the 2511 tier's multi-step items (pose + two 20-step passes) can run
    # longer than the main 10-min per-job cap (RUNPOD_EXECUTION_TIMEOUT_MS) — on the
    # all-A40 fleet with no FP8 hardware the fp8mixed model runs dequantized and
    # slow — so batch jobs get their own, longer caps.
    RUNPOD_BATCH_EXECUTION_TIMEOUT_MS: int = 1_200_000   # 20 min per-job cap
    RUNPOD_BATCH_TTL_MS: int = 3_600_000                 # 60 min total lifespan
    # Dedicated serverless endpoint for BATCH pipeline jobs. EMPTY (default) ->
    # batches share RUNPOD_ENDPOINT_ID like every other job type — byte-identical
    # legacy behavior. The main endpoint's all-A40 fleet has no FP8 hardware, so the
    # 2511 tier's 3-step items run dequantized/slow and can blow past the main
    # 10-min per-job cap and get killed and retried. Set this to a second endpoint
    # id in the SAME datacenter as the models network volume (so it can attach the
    # volume), backed by an fp8-capable 48 GB GPU (L40S / L40 / RTX 6000 Ada), so
    # batch items stop landing on A40-class workers and stop timing out.
    RUNPOD_BATCH_ENDPOINT_ID: str = ""

    # Keep-warm pinger (OPTIONAL, OFF by default). When enabled, the API submits a
    # lightweight warm-up job to the RunPod endpoint every WARMUP_INTERVAL_SECONDS
    # for as long as WARMUP_WINDOW_MINUTES after the last REAL job — so an active
    # admin session doesn't pay a cold start on every request. This costs GPU
    # seconds per ping; the PRIMARY cold-start mitigation is the RunPod dashboard
    # settings (raise idle timeout, enable FlashBoot). Point WARMUP_WORKFLOW_PATH
    # at a minimal 1-step / tiny-resolution graph to keep each ping cheap; empty
    # falls back to the generation workflow (COMFYUI_WORKFLOW_PATH).
    WARMUP_ENABLED: bool = False
    WARMUP_INTERVAL_SECONDS: int = 200          # ping cadence within the warm window
    WARMUP_WINDOW_MINUTES: int = 15             # keep pinging this long after real traffic
    WARMUP_WORKFLOW_PATH: str = ""              # empty -> COMFYUI_WORKFLOW_PATH

    # Image Cache (for outfit edit)
    IMAGE_CACHE_TTL_SECONDS: int = 1800  # 30 minutes
    IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS: int = 60  # 1 minute

    # Venice (LLM provider — OpenAI-compatible, uncensored). Used for both the
    # single-image scene writer and the batch story planner. Left unset by default
    # (deterministic assembler + deterministic planner work without it).
    VENICE_API_KEY: str = ""
    VENICE_BASE_URL: str = "https://api.venice.ai/api/v1"
    VENICE_MODEL: str = "venice-uncensored"

    # Persona/bio writer (Feature 1: AI chat-persona generation). Uses Venice above.
    # Empty PERSONA_WRITER_MODEL -> VENICE_MODEL. Works keyless (deterministic templates).
    PERSONA_WRITER_TEMPERATURE: float = 0.8
    PERSONA_WRITER_MAX_TOKENS: int = 1200
    PERSONA_WRITER_MODEL: str = ""

    # Trait-profile writer (WS-B: the durable per-character "RPG character sheet").
    # Uses Venice above. Empty TRAIT_WRITER_MODEL -> VENICE_MODEL. Works keyless
    # (deterministic fallback tables). Lower temperature than persona: the output is a
    # coherent structured taste sheet, not flavorful prose.
    TRAIT_WRITER_TEMPERATURE: float = 0.7
    TRAIT_WRITER_MAX_TOKENS: int = 900
    TRAIT_WRITER_MODEL: str = ""

    # Motion writer (Reels: interpret a custom motionPrompt into a WAN-friendly
    # description + button label). Uses Venice above. Empty MOTION_WRITER_MODEL ->
    # VENICE_MODEL. Works keyless (deterministic fallback = the raw user text).
    MOTION_WRITER_MODEL: str = ""
    MOTION_WRITER_TEMPERATURE: float = 0.7
    MOTION_WRITER_MAX_TOKENS: int = 200

    # Scene writer (Batch Character Creation: Venice writes a short, identity-free
    # scene/environment sentence the admin drops into GenerateImageRequest.context).
    # Uses Venice above. Empty SCENE_WRITER_MODEL -> VENICE_MODEL. Works keyless
    # (deterministic curated fallback varied by input; never breaks the flow).
    SCENE_WRITER_MODEL: str = ""
    SCENE_WRITER_TEMPERATURE: float = 0.6  # low: literal, camera-sees scene text (not flowery)
    SCENE_WRITER_MAX_TOKENS: int = 160

    # Story planner (batch story-director): lower temperature keeps Venice's
    # render-bound scene fields (setting/activity/pose_detail/outfit_detail/expression)
    # literal and directional — physically concrete, camera-instruction language a
    # diffusion model can render — instead of flowery narrative prose.
    STORY_PLANNER_TEMPERATURE: float = 0.6

    # Scene-direction writer (WS-SD): the deterministic planner decides WHAT each photo
    # is (outfit/pose/location/nudity/time — all coherence-guarded); Venice writes HOW IT
    # LOOKS — 1-3 sentences of concrete photographic staging per item (furniture/objects/
    # where she is in the space/camera feel), validated hard and fallback-safe. This is
    # per-item DECORATION, never narrative (the retired STORY mode hallucinated).
    #   "venice"        -> ONE batched Venice call per batch writes every item's direction
    #                      (default; each item that fails validation keeps its staging phrase).
    #   "deterministic" -> Venice is skipped entirely; each item keeps its bare staging phrase
    #                      (byte-identical to the pre-scene-direction batch).
    # Uses Venice above. Empty SCENE_DIRECTION_MODEL -> VENICE_MODEL. Works keyless
    # (no key -> the deterministic path, no network).
    SCENE_DIRECTION_PROVIDER: str = "venice"
    # Bounded planning-time enrichment: the batch POST waits at most this long for Venice's
    # staging pass, and the fallback (each item keeps its bare staging phrase) is SILENT, so
    # a slow provider can't stall a launch. Kept short on purpose.
    SCENE_DIRECTION_TIMEOUT_SECONDS: float = 8.0
    SCENE_DIRECTION_MODEL: str = ""
    SCENE_DIRECTION_TEMPERATURE: float = 0.7  # literal staging, not flowery prose
    # A FLOOR, not a cap: scene_direction.write_batch raises the effective max_tokens to
    # 400 + 130*item_count when a batch needs more, so a large batch can't be silently
    # truncated into an all-fallback response. Bumped above this only to raise the floor.
    SCENE_DIRECTION_MAX_TOKENS: int = 4000

    # Character generation: run the second detail-refine pass by default
    # (upscale-model round trip + refine steps; same output resolution,
    # ~+50-100% GPU time per image). Requires 4x_Nickelback_70000G.safetensors
    # in upscale_models/ on the RunPod volume — set false until it's uploaded.
    # Per-request override: output.hires.
    GENERATION_HIRES_DEFAULT: bool = True

    # WS3 kill-switch for all character-generation prompt variety (default-outfit
    # pools + seeded shot/pose rotation, so batch cards stop looking identical).
    # True -> the worker passes a per-job variety_seed into prompt assembly; False
    # -> variety_seed=None everywhere, i.e. byte-identical legacy prompts. Age
    # accuracy and nudity flavor-gating are NOT gated by this (they always apply).
    GENERATION_VARIETY_ENABLED: bool = True

    # Subtle color-grade clause appended to the GENERATION (character-gen,
    # text-to-image) photo-style wrapper only -- node 125 of the Z-Image Turbo
    # workflow (services.prompt_constants.photo_style_template). Feedback: hero
    # photos render realistic (the "android phone cam-quality" style wording is
    # deliberate and stays) but flat/desaturated. This clause boosts color
    # richness/finish WITHOUT reaching for "vibrant/HDR/oversaturated" language
    # that would flip the look into an Instagram-filter aesthetic. Tunable via
    # env so wording can be adjusted without a redeploy. Empty string disables
    # it entirely -> byte-identical legacy prompts on every generation style.
    # Does NOT touch the qwen EDIT-pipeline suffixes (EDIT_PHOTO_STYLE_SUFFIXES) --
    # those are a separate, positive-prompt-only mechanism for a different model.
    GENERATION_COLOR_GRADE: str = (
        "rich true-to-life colors with gentle film-like saturation, subtle "
        "warm color grading, balanced contrast, no washed-out or faded tones"
    )

    # Output finishing: subtle film-grain + local-contrast pass applied to
    # final, user-facing edit outputs at upload time (services.image_finish,
    # hooked into SupabaseStorageService.upload_image). Mitigates the
    # "plastic" look of AI-generated skin by reintroducing photographic
    # high-frequency texture. Scoped to services.image_finish.FINISH_FOLDERS
    # (edit outputs only) -- NOT character_creation (the generation look users
    # already love) and NOT nude_bases (an edit SOURCE; grain there would
    # compound through re-diffusion). Master switch -- OUTPUT_FILM_GRAIN_STRENGTH
    # below still gates the pass even when this is True (0 disables it).
    # Default OFF (2026-07-14): live A/B read as visible noise, not film feel;
    # re-enable only at a lower strength (<=0.015) if ever revisited.
    OUTPUT_FILM_GRAIN: bool = False
    # Grain amplitude as a fraction of the 0-255 luma range (e.g. 0.03 -> ~3%
    # of full-scale noise in shadows/mids, tapering in bright highlights).
    # 0 disables the finishing pass even when OUTPUT_FILM_GRAIN is True.
    OUTPUT_FILM_GRAIN_STRENGTH: float = 0.03

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
    # Batch Character Creation — dedicated pool of text_to_image workers draining
    # the isolated `creation_queue` (POST /v1/generate/batch), so a large character
    # batch can't starve the interactive single-generate queue (self.queue). Runs the
    # SAME text_to_image pipeline as the single BackgroundWorker; keep RunPod
    # max_workers >= this.
    CREATION_BATCH_WORKER_POOL_SIZE: int = 3
    # Generous maxsize for `creation_queue` so a realistic admin batch fits in one
    # atomic dispatch (POST /v1/generate/batch enqueues all-or-nothing; a batch larger
    # than this 429s). Independent of MAX_QUEUE_SIZE (the per-interactive-queue cap).
    CREATION_QUEUE_MAX_SIZE: int = 500
    # Max in-flight items per batch (fairness: stops one batch monopolizing the queue).
    BATCH_MAX_INFLIGHT: int = 3
    # Per-item retry attempts before an item is marked failed.
    BATCH_ITEM_MAX_ATTEMPTS: int = 2
    # Single-pass batch pipeline. True (default): an eligible batch item (nude-base
    # source + a pose + an outfit) renders outfit + scene + pose in ONE pose-graph
    # job — the pose step re-diffuses the whole frame anyway, so it dresses and
    # re-scenes straight from the nude base, and the separate outfit/background
    # steps (which only built a throwaway reference for it) collapse away. False ->
    # the legacy 3-step chain (outfit -> background -> pose) runs unchanged. Only
    # the batch scene mapper sets the per-request flag; interactive /v1/edit is
    # never single-pass.
    BATCH_SINGLE_PASS_EDIT: bool = True
    # WS3.2: fail fast at batch-worker startup if the batch engine's RESOLVED outfit
    # template is NOT a crop-and-stitch graph (workflow_meta tier "v1") — guards
    # against a mis-deployed environment (e.g. a CI-built image missing the
    # gitignored .env, so COMFYUI_OUTFIT_WORKFLOW_PATH_2511/_V2 read empty and the
    # chain silently lands on the weak V1 whole-frame graph) shipping degraded batch
    # outfit quality with no visible error. False (default) preserves today's
    # silent-fallback-to-V1 behavior for back-compat; flip true once Phase 0
    # diagnostics confirm the deployment resolves a crop-stitch tier.
    BATCH_REQUIRE_CROPSTITCH_OUTFIT: bool = False
    # Solo-subject background threshold (nude base / admin-reviewed assets only).
    # 0.0 (default) = DISABLED. When > 0 AND a PipelineEditRequest sets
    # soloSubject=true, the background step raises node 202's GroundingDINO
    # person-detector confidence threshold to this value so low-confidence
    # background passersby fall OUT of the protected person mask and get painted
    # over by the backdrop regen. FAIL-OPEN: if the MAIN subject also scores below
    # this the whole frame becomes editable — only safe for admin-reviewed assets
    # like the nude base, never the interactive /v1/edit/background path (which
    # never sets soloSubject). A sane starting value is ~0.4 (the template default
    # is 0.3); tune against real hero photos before enabling.
    SOLO_BG_PERSON_THRESHOLD: float = 0.0
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

    # -----------------------------------------------------------------------
    # WS-N — Nude base rebuild (text-to-image base + ReActor face lock).
    # True (default, the NEW path): the nude base is GENERATED from scratch like
    # char-gen (Z-Image Turbo, COMFYUI_WORKFLOW_PATH) using the character's locked
    # identity + a forced NAKED clause + a neutral standing full-body pose + a plain
    # studio backdrop + the NATURAL photo style, at a deterministic per-character
    # seed, then ONE ReActor face pass swaps the ORIGINAL hero photo's face onto it.
    # This is pose-independent and mask-free, so an unusual hero crop can no longer
    # produce the old two-headed edit-based composite. False -> the LEGACY edit-based
    # path (outfit step in "nude_base" prompt mode + background step on the hero,
    # via the pipeline engine) runs UNCHANGED as a fallback. See
    # api/v1/endpoints/nude_base.py and workers/nude_base_worker.py.
    NUDE_BASE_T2I: bool = True

    # -----------------------------------------------------------------------
    # WS-N face swap — the base is a BODY reference; final faces always come
    # from the HERO via the pose-step ReActor (every published batch photo's
    # face is stamped there), so face-locking the base too is unnecessary GPU
    # work and creates a confusing hero-vs-base identity mismatch in the admin
    # (the base's own face never reaches a published photo). False (default):
    # the t2i base worker skips the ReActor face pass entirely — the t2i
    # output IS the final base image. Set true to restore the old
    # face-locked bases (the GPEN/FaceBoost restore path below stays wired
    # and still applies whenever this is on).
    NUDE_BASE_FACE_SWAP: bool = False

    # -----------------------------------------------------------------------
    # WS-N face-restore quality — inswapper_128 synthesizes identity at only
    # 128px, so the WS-N ReActor swap's restore step is what determines how
    # sharp the final face reads. GPEN-BFR-512 restores at 512px (sharper,
    # less waxy than CodeFormer on a large/close-up face). Set to
    # "codeformer-v0.1.0.pth" to roll back to the old restorer. Empty string
    # keeps the worker's baked REACTOR_FACE_RESTORE_MODEL default (see
    # workers/nude_base_worker.py).
    NUDE_BASE_FACE_RESTORE_MODEL: str = "GPEN-BFR-512.onnx"
    # Wire ReActorFaceBoost onto the WS-N swap: restores + upscales the
    # swapped face BEFORE it is pasted back onto the base, instead of relying
    # solely on the main node's own restore — the actual fix for a 128px swap
    # landing on a close-up face. Requires the worker image's ReActor pack to
    # ship the ReActorFaceBoost node; if a pinned build lacks it, the job
    # fails validation loudly rather than silently skipping the boost, so
    # flip this False to roll back cleanly.
    NUDE_BASE_FACE_BOOST: bool = True

    # -----------------------------------------------------------------------
    # WS-M — outfit mask diagnostics (flag-gated, default OFF). When True, every
    # outfit-step engine (interactive /v1/edit/outfit, the /v1/edit pipeline, and the
    # batch engine) resolves to workflows/outfit_cropstitch_maskpreview_API.json instead
    # of its normal render graph (see main.py). That graph shares the identical mask
    # chain (SAM person / ClothesSegment -> head-subtract -> crop -> soften) but its
    # SaveImage outputs the editable MASK (white = will be edited) rather than the edited
    # photo, so an operator can eyeball what region the outfit step will repaint —
    # confirming the hardened soft edge on a dressed source and, critically, that a nude
    # source still masks the torso (not an empty ClothesSegment). No diffusion runs
    # (the KSampler branch is dead for the mask output), so it is cheap. Mirrors
    # POSE_DEBUG_SAVE_PRE_REACTOR: set it in .env, restart, submit one outfit edit, then
    # turn it back off. Leave OFF in production.
    OUTFIT_DEBUG_SAVE_MASK: bool = False

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
