# Loli API — Project Overview

Character image generation and editing API powered by ComfyUI and xAI Grok-4. Designed for batch generation by admins on on-demand GPUs, not 24/7 production serving.

## Ecosystem

| Repo | Purpose | Stack |
|------|---------|-------|
| **loli-api** (this) | Image generation/editing API | Python / FastAPI / ComfyUI |
| **loli-ai-admin** | Admin panel — triggers generation, reviews results | Next.js |
| **loli-ai** | Public website — displays generated content | Next.js |

## Architecture

```
Admin Panel (loli-ai-admin)
    │
    ▼
Cloudflare Tunnel (public URL)
    │
    ▼
FastAPI (port 8001) ──► xAI Grok-4 (prompt generation)
    │                 ──► Supabase (image storage)
    │                 ──► Google Chat (job notifications)
    ▼
ComfyUI (port 8188, WebSocket)
    │
    ▼
GPU (RTX A5000 / A100 / H100 on RunPod)
```

**Request flow:** Admin submits job via API -> FastAPI queues it -> background worker sends workflow to ComfyUI over WebSocket -> ComfyUI renders on GPU -> output saved to Supabase (or local) -> admin polls job status and retrieves signed preview URL.

## Tech Stack

- **Runtime:** Python 3.10+
- **Framework:** FastAPI + Uvicorn
- **Image engine:** ComfyUI v0.14.1
- **Models:** Z-Image Turbo (generation), Qwen-Rapid-AIO-NSFW v23 (editing)
- **Prompt AI:** xAI Grok-4 via OpenAI-compatible API
- **Auth:** JWT Bearer tokens (HS256)
- **Storage:** Local filesystem with signed URLs, optional Supabase cloud storage
- **Notifications:** Google Chat webhooks
- **Config:** Pydantic Settings, loaded from `.env`

## Key Design Decisions

- **Async job queue:** All generation/edit requests return a `jobId` immediately (HTTP 202). Workers process jobs in background via `asyncio.Queue`.
- **On-demand GPUs:** Runs on RunPod serverless/on-demand instances. `start.sh` launches both ComfyUI and the API in a tmux session.
- **Worker pattern:** Each edit type (outfit, pose, background) has its own worker extending `BaseEditWorker`. Pipeline worker chains them.
- **OOM retry:** Workers automatically retry on CUDA out-of-memory errors (up to 3 attempts).
- **Image cache:** Downloaded source images are cached locally to avoid re-downloading for chained edits.
