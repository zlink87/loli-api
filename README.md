# Loli API

Character image generation and editing API for the Loli AI ecosystem.

## What it does

REST API that generates and edits AI character images using:
- **xAI Grok-4** for intelligent prompt generation from persona attributes
- **ComfyUI** with diffusion models for image generation and editing
- **SAM3 segmentation** for precise outfit/environment masking

## Ecosystem

| Component | Repo | Purpose |
|-----------|------|---------|
| **Loli API** (this) | `loli-api` | Image generation/editing backend |
| **Loli AI Admin** | `loli-ai-admin` | Admin panel for character management |
| **Loli AI** | `loli-ai` | User-facing website with chat |

## Tech Stack

- **API:** Python 3.10+ / FastAPI / Uvicorn (port 8001)
- **Image Engine:** ComfyUI v0.14.1 (port 8188, WebSocket)
- **Generation Model:** Z-Image Turbo (FP4 quantized)
- **Edit Model:** Qwen-Rapid-AIO-NSFW v23
- **Prompt LLM:** xAI Grok-4 (cloud API)
- **Auth:** JWT (HS256)
- **Storage:** Local with signed URLs, or Supabase
- **Queue:** In-memory asyncio (max 100 jobs)

## Quick Start

```bash
# 1. Install dependencies
bash setup.sh

# 2. Configure environment
cp .env.example loli_api/.env
# Edit .env with your API keys

# 3. Start (ComfyUI + API in tmux)
bash start.sh
```

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/v1/generate/image` | Generate character from persona |
| POST | `/v1/edit/outfit` | Change outfit (47 types, 3 nudity levels) |
| POST | `/v1/edit/pose` | Change pose (16 types with dynamic prompts) |
| POST | `/v1/edit/background` | Change environment/scene |
| POST | `/v1/edit` | Chain: pose → outfit → background |
| GET | `/v1/jobs/{jobId}` | Poll job status |
| DELETE | `/v1/jobs/{jobId}` | Cancel queued job |
| GET | `/v1/preview/{token}` | Access generated image |
| GET | `/health` | Health check |

**Swagger docs:** Available at `/docs` when the API is running.

## Project Structure

```
loli-api/
├── loli_api/                    # Main API application
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Pydantic settings (.env)
│   ├── api/v1/endpoints/        # Route handlers
│   ├── workers/                 # Async job processors
│   │   ├── base_worker.py       # Shared worker base class
│   │   ├── background_worker.py # Character generation
│   │   ├── outfit_worker.py     # Outfit editing
│   │   ├── pose_worker.py       # Pose editing
│   │   ├── background_edit_worker.py # Environment editing
│   │   └── pipeline_worker.py   # Chained operations
│   ├── services/                # Business logic
│   ├── models/                  # Pydantic models & enums
│   ├── auth/                    # JWT authentication
│   └── workflows/               # ComfyUI workflow JSONs
├── ComfyUI/                     # ComfyUI server + models
├── docs/                        # Project documentation
├── start.sh                     # Launch script (tmux)
├── setup.sh                     # Install dependencies
└── requirements.txt             # Python dependencies
```

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | JWT signing secret (change in production!) |
| `XAI_API_KEY` | xAI Grok API key for prompt generation |
| `COMFYUI_SERVER_ADDRESS` | ComfyUI server (default: `127.0.0.1:8188`) |
| `USE_SUPABASE_STORAGE` | Enable Supabase cloud storage |
| `BASE_URL` | Public URL (Cloudflare tunnel) |

## Deployment

Designed for **RunPod on-demand** GPU instances:
- **Images:** RTX A5000 (24GB VRAM, ~$0.22/hr)
- **Videos (future):** A100/H100 80GB
- Batch generation by admins, not 24/7

## Documentation

See `docs/` directory for detailed documentation.
