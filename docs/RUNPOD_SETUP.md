# RunPod Serverless Setup (loli-api)

This guide sets up the GPU side of loli-api on **RunPod Serverless**. The FastAPI app is
now a thin control plane: it builds the ComfyUI workflow JSON and submits it to a RunPod
Serverless endpoint running `runpod-workers/worker-comfyui`. The GPU worker runs ComfyUI,
uploads the output image directly to Supabase Storage (S3 API), and the result URL flows
back to the job.

```
loli-api (FastAPI)  ──/run──▶  RunPod Serverless endpoint (worker-comfyui + ComfyUI)
       ▲                              │ models mounted from /runpod-volume
       │ poll /status                 │ output PNG ──S3 upload──▶ Supabase Storage
       └──────────── job preview_url ◀┘
```

You will do this once in the RunPod web console. Total model footprint ≈ 20 GB.

---

## 1. Create a Network Volume (holds the ~20 GB of models)

RunPod console → **Storage → New Network Volume**.
- **Datacenter:** pick one with good GPU availability (e.g. `EU-RO-1` or `US-*`). The
  endpoint will be pinned to this datacenter.
- **Size:** **40 GB** (20 GB models + headroom for ComfyUI cache and pose references).
- Name it e.g. `loli-comfy-models`.

The volume mounts at **`/runpod-volume`** inside every worker.

### Populate the volume with models

Start a cheap **GPU Pod** (or CPU pod) with this network volume attached, open a terminal,
and download the models into the ComfyUI model folders on the volume. These are the exact
files loli-api expects (from `setup.sh` / `download2.sh`):

```bash
cd /runpod-volume
mkdir -p ComfyUI/models/{diffusion_models,text_encoders,vae,checkpoints,sam3,upscale_models} \
         ComfyUI/input/poses

# Z-Image Turbo (character generation)
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_nvfp4.safetensors -P ComfyUI/models/diffusion_models
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b_fp4_mixed.safetensors -P ComfyUI/models/text_encoders
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors -P ComfyUI/models/vae

# Qwen-Image-Edit-Rapid-AIO (outfit / pose / background edits)
wget -c https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO/resolve/main/v23/Qwen-Rapid-AIO-NSFW-v23.safetensors -P ComfyUI/models/checkpoints

# Upscalers (quality)
# 4x_foolhardy_Remacri.safetensors, 4x_Nickelback_70000G.safetensors -> ComfyUI/models/upscale_models
# SAM3 segmentation model -> ComfyUI/models/sam3/sam3.pt  (per comfyui-sam3 node)
```

> **Pose references (required for pose & pipeline edits):** copy the pose reference PNGs
> from this repo's ComfyUI input into `/runpod-volume/ComfyUI/input/poses/`. The pose
> workflow loads them **by filename** (LoadImage node 170), so they must exist on the
> worker or pose/pipeline jobs fail with a missing-image error.

> **Do NOT download** the SD1.5 IP-Adapter FaceID models (`ip-adapter-faceid-*_sd15.*`,
> `CLIP-ViT-H-14`). They are architecturally incompatible with the Qwen/Z-Image (DiT)
> models in use and are not wired into any workflow. (They have been commented out of
> `download2.sh`.) See **§6 Quality / identity follow-ups**.

---

## 2. Build the worker image (ComfyUI + custom nodes)

The workflows reference these custom nodes, so the worker image must contain them:
`comfyui-sam3`, `comfyui_faceanalysis`, `ComfyUI-QwenVL`, `ComfyUI-GGUF`,
`comfyui-kjnodes`, `rgthree-comfy`, `ComfyUI_JPS-Nodes`, `comfyui-easy-use`,
`comfyui_controlnet_aux`. (Add `ComfyUI-Impact-Pack` + `ComfyUI-Impact-Subpack` if you
adopt the detailer follow-up in §6.)

Start from `runpod/worker-comfyui:<version>-base` and add the custom nodes via a
`Dockerfile` (clone each into `/comfyui/custom_nodes` and `pip install -r requirements.txt`),
**or** mount them from the network volume at container start:

```
# Container start command (volume-mounted custom nodes)
sh -c "ln -sfn /runpod-volume/ComfyUI/custom_nodes/* /comfyui/custom_nodes/ && \
       ln -sfn /runpod-volume/ComfyUI/models /comfyui/models && \
       ln -sfn /runpod-volume/ComfyUI/input/poses /comfyui/input/poses && /start.sh"
```

Tip: upload a workflow JSON to https://comfy.getrunpod.io to auto-detect required custom
nodes and generate a worker repo.

---

## 3. Configure Supabase Storage as the worker's S3 target

The worker uploads output images directly to Supabase Storage via its S3-compatible API
(so large images don't round-trip through FastAPI). In Supabase: **Project Settings →
Storage → S3 access** → create access keys. Endpoint is
`https://<project-ref>.supabase.co/storage/v1/s3`.

Set these env vars **on the RunPod endpoint** (worker-comfyui reads them to enable S3 output):
```
BUCKET_ENDPOINT_URL = https://<project-ref>.supabase.co/storage/v1/s3
BUCKET_ACCESS_KEY_ID = <supabase s3 access key id>
BUCKET_SECRET_ACCESS_KEY = <supabase s3 secret>
# Region is typically the project's region, e.g. us-east-1
```
When S3 is configured, worker-comfyui returns `output.images[].type = "s3_url"` and the
URL in `data` — loli-api records it directly as the job's `preview_url`. If you leave S3
unset, the worker returns base64 and loli-api falls back to uploading via its own Supabase
service.

---

## 4. Create the Serverless endpoint

RunPod console → **Serverless → New Endpoint**.
- **Worker image:** the image from §2.
- **Network volume:** attach `loli-comfy-models` (Advanced → Network Volumes). This pins
  the endpoint to the volume's datacenter.
- **GPU:** 24 GB class (e.g. RTX A5000 / L4 / 4090) — fits all models with margin.
- **Workers:** set **Max workers** to your expected concurrency (e.g. 5–20) and **Active
  workers** ≥ 1 if you want to avoid cold starts; enable **FlashBoot**.
- **Idle timeout:** a few seconds to scale to zero when idle.
- **Execution timeout:** ≥ 300 s (matches `RUNPOD_EXECUTION_TIMEOUT_MS` default of 600 s).
- Add the S3 env vars from §3.

Copy the **Endpoint ID** and create a **RunPod API key** (Settings → API Keys).

---

## 5. Point loli-api at the endpoint (`.env`)

Set these in loli-api's `.env` (see `.env.example`):
```
GPU_BACKEND=runpod
RUNPOD_API_KEY=<your runpod api key>
RUNPOD_ENDPOINT_ID=<your endpoint id>
RUNPOD_EXECUTION_TIMEOUT_MS=600000
RUNPOD_TTL_MS=3600000

# Output delivery (FastAPI side, used only for the base64 fallback path)
USE_SUPABASE_STORAGE=true
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_BUCKET_NAME=images_generated

# Security (required in production; the app refuses to start otherwise)
DEBUG=false
JWT_SECRET_KEY=<random 32+ char secret>
STORAGE_SIGNING_SECRET=<random 32+ char secret>
SUPABASE_JWT_SECRET=<Supabase project JWT secret>
CORS_ALLOW_ORIGINS=https://admin.yoursite.com,https://yoursite.com
SOURCE_IMAGE_ALLOWED_HOSTS=<project-ref>.supabase.co
```

---

## 6. Quality / identity follow-ups (need ComfyUI to validate)

These improve identity preservation and reduce deformities but change the ComfyUI workflow
**graph topology**, so they must be built and tested against a running ComfyUI (they are not
done in code yet). The negative prompts and identity-preservation language ARE already
injected by the API (`services/prompt_constants.py`).

1. **Face/hair mask-lock** (outfit + background): add a `SAM3Grounding("face, head, hair,
   neck")` → `GrowMaskWithBlur` → `MaskComposite(subtract)` so the edit mask excludes the
   face/hair region (sampler physically cannot repaint the face). For background, make the
   edit region the inverse of the person mask.
2. **FaceWarp restore** (uses installed `comfyui_faceanalysis`): after VAEDecode, warp the
   source/avatar face back onto the result.
3. **Hands detailer**: install `ComfyUI-Impact-Pack` + a hand YOLO detector and add a
   `DetailerForEach` pass for hands. Use FaceWarp (not a face detailer) for the face so
   identity is never regenerated.
4. **Upscale on edits**: add `UpscaleModelLoader (Remacri)` + `ImageUpscaleWithModel` to the
   edit workflows. Update the worker output-node IDs if you add nodes after the SaveImage.

---

## 7. Smoke test

```bash
# Submit a tiny test job directly to RunPod (replace IDs):
curl -X POST https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/run \
  -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  -d '{"input":{"workflow": <a small ComfyUI API-format graph>}}'

# Then poll:
curl https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/status/<id> \
  -H "Authorization: Bearer $RUNPOD_API_KEY"
```

End-to-end: start loli-api, call `POST /v1/edit/outfit` with a Supabase `source_image`,
then poll `GET /v1/jobs/{jobId}` until `succeeded` and confirm `preview_url` resolves.
```
