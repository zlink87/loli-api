# Loli API — Deployment Guide

This covers deploying **the API itself** (the FastAPI control plane) and a
**human walkthrough of the RunPod console** for the GPU side. For the exact RunPod
commands/payloads see [`RUNPOD_SETUP.md`](RUNPOD_SETUP.md); for every env var see
[`.env.example`](../.env.example).

## Architecture (after the RunPod Serverless migration)

There are now **two independent pieces** — deploy them separately:

```
┌─────────────────────────────┐         ┌──────────────────────────────────────┐
│  CONTROL PLANE               │  /run   │  GPU (RunPod Serverless)              │
│  loli-api (FastAPI)          │────────▶│  worker-comfyui + ComfyUI            │
│  cheap always-on host        │ /status │  models on /runpod-volume            │
│  NO GPU, ~1 vCPU / 1–2 GB    │◀────────│  output PNG ──S3──▶ Supabase Storage │
└─────────────────────────────┘  URL     └──────────────────────────────────────┘
        │ publishes BASE_URL → Supabase app_config (frontends discover the API here)
        ▼
  loli-ai (website) + loli-ai-admin (admin panel)
```

The control plane is now **light** (no torch/ComfyUI) — run it on a cheap CPU box, not a
GPU pod.

---

# Part 1 — Deploy the API (control plane)

## 1.1 Where to run it

Any small always-on Linux host that can expose a public HTTPS URL: a VPS (Hetzner, DigitalOcean),
a PaaS (Fly.io, Railway, Render), or a RunPod **CPU** pod. **~1 vCPU and 1–2 GB RAM is plenty** —
the service just builds JSON, calls RunPod/Supabase, and polls. Do **not** put it on a GPU pod.

## 1.2 Configure `.env`

```bash
git clone <repo> && cd loli-api
cp .env.example .env
# edit .env — fill in the values from Part 2 (RunPod) and your Supabase project
```

**Required in production** (the app refuses to start with `DEBUG=false` otherwise — see
`_validate_production_settings` in `loli_api/main.py`):
`JWT_SECRET_KEY`, `STORAGE_SIGNING_SECRET`, `SUPABASE_JWT_SECRET`, `RUNPOD_API_KEY`,
`RUNPOD_ENDPOINT_ID`, `CORS_ALLOW_ORIGINS`, `SOURCE_IMAGE_ALLOWED_HOSTS`.

## 1.3 Run it — pick one

### Option A — Docker (recommended)
```bash
docker build -f Dockerfile.api -t loli-api .
docker run -d --name loli-api --restart unless-stopped \
  --env-file .env -p 8001:8001 loli-api
docker logs -f loli-api          # watch startup
```

### Option B — systemd + virtualenv
```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-api.txt          # slim deps, NOT requirements.txt
cd loli_api && uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1
```
> **Use a single worker.** Job state is in-memory (per-process), so multiple uvicorn
> workers would make `GET /v1/jobs/{id}` miss jobs created in another process. To scale
> out, add the durable Supabase job store (the Step-B follow-up) first. One worker is fine —
> the service is I/O-bound and offloads all compute to RunPod.
As a service, `/etc/systemd/system/loli-api.service`:
```ini
[Unit]
Description=loli-api
After=network.target
[Service]
WorkingDirectory=/opt/loli-api/loli_api
EnvironmentFile=/opt/loli-api/.env
ExecStart=/opt/loli-api/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1
Restart=always
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now loli-api
```

### Option C — local/dev
```bash
pip install -r requirements-api.txt
cd loli_api && DEBUG=true python main.py     # auto-reload + /debug/* endpoints
```

> The full `requirements.txt` (torch + ComfyUI) is **only** for the RunPod worker image.
> The API host uses `requirements-api.txt`.

## 1.4 Give it a public HTTPS URL

The frontends don't hardcode the API URL — they read it from Supabase `app_config.api_base_url`,
which this app **publishes on startup** from `BASE_URL` (see `services/base_url_service.py`).
So whatever public URL you get, put it in `BASE_URL` and the admin/website pick it up
automatically. Two ways to get one:

- **Cloudflare Tunnel** (no open ports; what the project uses today):
  ```bash
  # quick/ephemeral:
  cloudflared tunnel --url http://localhost:8001
  # production: create a NAMED tunnel for a stable domain (api.yoursite.com)
  ```
- **Reverse proxy + TLS** on your own domain (Caddy is simplest):
  ```
  api.yoursite.com {
      reverse_proxy localhost:8001
  }
  ```

Set `BASE_URL=https://api.yoursite.com` (or the tunnel URL) in `.env` and restart.
Also add that origin's frontends to `CORS_ALLOW_ORIGINS`.

## 1.5 Verify

```bash
curl https://api.yoursite.com/health          # {"status":"healthy",...}
```
End-to-end: from the admin panel (or curl with a real Supabase JWT) call
`POST /v1/edit/outfit` with a Supabase `source_image`, then poll `GET /v1/jobs/{jobId}`
until `succeeded` and confirm `preview_url` opens.

---

# Part 2 — RunPod console setup (human walkthrough)

This is the click-through version of [`RUNPOD_SETUP.md`](RUNPOD_SETUP.md) (which has the exact
commands). Do it once.

### Step 0 — Account, billing, safety
Create a RunPod account, add credit, and **set a spending limit** (Settings → Billing). Serverless
GPUs cost money per second they run.

### Step 1 — API key
Settings → **API Keys** → create one. Copy it into `.env` as `RUNPOD_API_KEY`.

### Step 2 — Network volume (holds the ~20 GB of models)
Storage → **New Network Volume**. Pick a **datacenter with good GPU availability**, size **40 GB**,
name it `loli-comfy-models`. (The endpoint will be pinned to this datacenter, so choose one that
stocks your preferred GPU.)

### Step 3 — Put the models on the volume
Launch a **cheap pod** with this volume attached → open its **web terminal** → run the `wget`
download block from `RUNPOD_SETUP.md §1`. Also copy the **pose reference PNGs** into
`/runpod-volume/ComfyUI/input/poses/` (pose/pipeline edits need them). Then terminate the pod —
the volume keeps the files.

### Step 4 — Build the worker image
Build a `worker-comfyui` image that includes your custom nodes (sam3, faceanalysis, QwenVL, GGUF,
kjnodes, rgthree, JPS, easy-use, controlnet_aux) and push it to a registry (see `RUNPOD_SETUP.md §2`).
Tip: upload a workflow JSON to https://comfy.getrunpod.io to auto-detect required nodes.

### Step 5 — Supabase S3 keys (so the worker uploads outputs directly)
In Supabase: Project Settings → Storage → **S3 access** → create access keys. You'll paste these
onto the endpoint in Step 6 as `BUCKET_ENDPOINT_URL` / `BUCKET_ACCESS_KEY_ID` /
`BUCKET_SECRET_ACCESS_KEY`.

### Step 6 — Create the Serverless endpoint
Serverless → **New Endpoint**:
- **Image:** your worker image from Step 4.
- **GPU:** set a **priority list** for availability, e.g. `RTX 4090 → L40S → A5000` (24 GB floor;
  L40S/48 GB gives headroom for the quality pipeline). See the GPU discussion in `RUNPOD_SETUP.md`.
- **Network volume:** Advanced → attach `loli-comfy-models` (this pins the datacenter).
- **Workers:** Max = your target concurrency (start 5–20); set **Active = 1** and enable **FlashBoot**
  to avoid cold-start latency on every request.
- **Execution timeout:** ≥ 300 s.
- **Env vars:** add the Supabase S3 keys from Step 5.

### Step 7 — Wire it into the API
Copy the **Endpoint ID** into `.env` as `RUNPOD_ENDPOINT_ID` (and the API key from Step 1).
Restart the API. Run the smoke test in `RUNPOD_SETUP.md §7`.

---

## Cost & ops notes

- **Cold starts + idle dominate serverless cost**, not the GPU model. Keep ≥1 active worker +
  FlashBoot + models on the volume (never re-download).
- **Region pinning:** the volume ties the endpoint to one datacenter — the GPU priority list keeps
  jobs from stalling when your first-choice GPU is unavailable there.
- **Auth cutover:** production runs `DEBUG=false`, so `/debug/token` is gone — the frontends must
  send the signed-in user's **Supabase JWT**. Coordinate this change in `loli-ai-admin` / `loli-ai`.

## Environment variables

See [`.env.example`](../.env.example) — it is the source of truth and documents every variable
(server, RunPod, auth/security, Supabase storage + S3, xAI, notifications).
