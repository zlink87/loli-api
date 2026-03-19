# Loli API — Deployment Guide

## RunPod Setup

This API runs on RunPod on-demand GPU instances. It is not designed for 24/7 operation — spin up when generating, shut down when done.

**Recommended GPUs:**
- **RTX A5000** (24GB VRAM) — image generation/editing
- **A100 / H100** — future video generation workloads

### First-Time Setup

1. Launch a RunPod pod with the desired GPU and a PyTorch template
2. Clone the repo
3. Run setup:
   ```bash
   bash setup.sh
   ```
   This installs pip dependencies from `requirements.txt` and downloads models to `ComfyUI/models/`:
   - `diffusion_models/z_image_turbo_nvfp4.safetensors`
   - `text_encoders/qwen_3_4b_fp4_mixed.safetensors`
   - `vae/ae.safetensors`
   - `checkpoints/Qwen-Rapid-AIO-NSFW-v23.safetensors`

4. Create `.env` file (see Environment Variables below)

### Starting the Service

```bash
bash start.sh
```

This creates a tmux session named `loli` with two panes:
- **Left pane:** ComfyUI on port 8188
- **Right pane:** FastAPI on port 8001

To reattach: `tmux attach -t loli`

### Cloudflare Tunnel

For public HTTPS access without opening ports:

```bash
cloudflared tunnel --url http://localhost:8001
```

Update `BASE_URL` in `.env` with the generated tunnel URL. The API automatically syncs this URL to Supabase on startup so external services (admin panel) can discover it.

## Environment Variables

Create a `.env` file in the project root. All settings are defined in `loli_api/config.py`.

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET_KEY` | (change me) | Secret for signing JWT tokens |
| `XAI_API_KEY` | (none) | xAI API key for Grok-4 prompt generation |
| `BASE_URL` | `http://localhost:8001` | Public base URL (set to Cloudflare tunnel URL) |
| `STORAGE_SIGNING_SECRET` | (change me) | Secret for signing preview URLs |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_HOST` | `0.0.0.0` | Server bind address |
| `APP_PORT` | `8001` | Server port |
| `DEBUG` | `false` | Enable debug mode (auto-reload, debug endpoints) |
| `COMFYUI_SERVER_ADDRESS` | `127.0.0.1:8188` | ComfyUI WebSocket address |
| `COMFYUI_INPUT_DIR` | `../ComfyUI/input` | ComfyUI input directory for uploaded images |
| `XAI_BASE_URL` | `https://api.x.ai/v1` | xAI API base URL |
| `XAI_MODEL` | `grok-4` | xAI model name |
| `STORAGE_DIR` | `./storage/images` | Local image storage path |
| `PREVIEW_EXPIRY_MINUTES` | `60` | Signed URL expiry time |
| `MAX_QUEUE_SIZE` | `100` | Max jobs per queue |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_FILE` | `logs/app.log` | Log file path |
| `IMAGE_CACHE_TTL_SECONDS` | `1800` | Source image cache TTL (30 min) |
| `IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS` | `60` | Cache cleanup interval |

### Supabase Storage (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_SUPABASE_STORAGE` | `false` | Enable Supabase cloud storage |
| `SUPABASE_URL` | (none) | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | (none) | Supabase service role key |
| `SUPABASE_BUCKET_NAME` | `images_generated` | Storage bucket name |
| `SUPABASE_UPDATE_BASE_URL_API_KEY` | (none) | API key for syncing BASE_URL to Supabase |

### Notifications (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CHAT_RESPONSE_WEBHOOK_URL` | (none) | Webhook for job completion notifications |
| `GOOGLE_CHAT_PAYLOAD_WEBHOOK_URL` | (none) | Webhook for payload/debug notifications |

### Workflow Paths

These rarely need changing:

| Variable | Default |
|----------|---------|
| `COMFYUI_WORKFLOW_PATH` | `workflows/amazing-z-photo_API_Create_CHAR.json` |
| `COMFYUI_EDIT_WORKFLOW_PATH` | `workflows/edit.json` |
| `COMFYUI_OUTFIT_WORKFLOW_PATH` | `workflows/test_final_API.json` |
| `COMFYUI_POSE_WORKFLOW_PATH` | `workflows/edit_pose_action.json` |
