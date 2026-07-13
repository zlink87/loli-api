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
mkdir -p ComfyUI/models/{diffusion_models,text_encoders,vae,checkpoints,sam3,upscale_models,loras}

# Z-Image Turbo (character generation)
# NOTE: the production workflow (amazing-z-photo_API_Create_CHAR.json) loads the
# bf16 UNET + qwen_3_4b text encoder. The nvfp4/fp4_mixed variants are the smaller
# alternatives — only needed if the workflow is switched to them.
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors -P ComfyUI/models/diffusion_models
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors -P ComfyUI/models/text_encoders
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_nvfp4.safetensors -P ComfyUI/models/diffusion_models
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b_fp4_mixed.safetensors -P ComfyUI/models/text_encoders
wget -c https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors -P ComfyUI/models/vae

# Qwen-Image-Edit-Rapid-AIO (outfit / pose / background edits)
wget -c https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO/resolve/main/v23/Qwen-Rapid-AIO-NSFW-v23.safetensors -P ComfyUI/models/checkpoints

# AnyPose LoRAs (required by the pose edit workflow, strength 0.7) -> ComfyUI/models/loras
# 2511-AnyPose-base-000006250.safetensors    # TODO: add download URL
# 2511-AnyPose-helper-00006000.safetensors   # TODO: add download URL

# Upscalers — REQUIRED for the hero-shot detail-refine pass
# (GENERATION_HIRES_DEFAULT=true / output.hires). Only .pth builds are publicly
# downloadable; the generation workflow references the .pth filenames.
wget -c https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x_Nickelback_70000G.pth -P ComfyUI/models/upscale_models
wget -c https://huggingface.co/FacehugmanIII/4x_foolhardy_Remacri/resolve/main/4x_foolhardy_Remacri.pth -P ComfyUI/models/upscale_models

# SAM3 segmentation model -> ComfyUI/models/sam3/sam3.pt  (per comfyui-sam3 node)
```

> **Detail-refine pass (`output.hires` / `GENERATION_HIRES_DEFAULT`):** hero-shot
> generation routes its output through an upscale-model round trip + refine steps
> (same output resolution, ~+50-100% GPU time). It fails with a ComfyUI node error
> (surfaces as `PROVIDER_ERROR`) if `4x_Nickelback_70000G.pth` is missing from
> `upscale_models/` — set `GENERATION_HIRES_DEFAULT=false` until the model is on
> the volume.

> **Pose references (pose & pipeline edits):** these ship **per-request** as base64
> `input.images[]` entries from `loli_api/assets/poses/` (generated once via
> `scripts/generate_pose_refs.py`). loli-api stages the correct PNG alongside the source
> image and sets node 170 (LoadImage) to the matching flat filename, so **no volume copy
> is required**. Pre-copying the PNGs to `/runpod-volume/ComfyUI/input/poses/` is an
> optional latency optimization only, not a requirement.

> **Do NOT download** the SD1.5 IP-Adapter FaceID models (`ip-adapter-faceid-*_sd15.*`,
> `CLIP-ViT-H-14`). They are architecturally incompatible with the Qwen/Z-Image (DiT)
> models in use and are not wired into any workflow. (They have been commented out of
> `download2.sh`.) See **§6 Quality / identity follow-ups**.

---

## 2. Build the worker image (ComfyUI + custom nodes)

The workflows reference these custom nodes, so the worker image must contain them:
`comfyui-sam3`, `comfyui_faceanalysis`, `ComfyUI-QwenVL`, `ComfyUI-GGUF`,
`comfyui-kjnodes`, `rgthree-comfy`, `ComfyUI_JPS-Nodes`, `comfyui-easy-use`,
`comfyui_controlnet_aux`, `rect`. (`rect` provides RectFill/RectSelect — the pose
workflow's node 170 face black-out uses it and the graph will not load without it.)
(Add `ComfyUI-Impact-Pack` + `ComfyUI-Impact-Subpack` if you adopt the detailer
follow-up in §6.)

Start from `runpod/worker-comfyui:<version>-base` and add the custom nodes via a
`Dockerfile` (clone each into `/comfyui/custom_nodes` and `pip install -r requirements.txt`),
**or** mount them from the network volume at container start:

```
# Container start command (volume-mounted custom nodes)
sh -c "ln -sfn /runpod-volume/ComfyUI/custom_nodes/* /comfyui/custom_nodes/ && \
       ln -sfn /runpod-volume/ComfyUI/models /comfyui/models && /start.sh"
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

## 5a. Dedicated video (reels) endpoint (optional)

Image-to-video (reel) jobs run WAN 2.2 14B two-stage (20+20 steps, 81 frames), which
takes far longer per job than a character-gen or edit call. The main endpoint built in
§4 above runs on an all-**A40** fleet — WAN 2.2 cannot finish a reel there inside
`RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS` (30 min default), so every reel dies with
`executionTimeout exceeded`. Reels need an fp8-capable fast GPU instead, so give them
their own endpoint rather than raising the timeout further.

Create a **second** Serverless endpoint (RunPod console → Serverless → New Endpoint):
- **Network volume:** attach the SAME volume as the main endpoint (`loli-comfy-models`,
  `EU-SE-1`) — this pins the new endpoint to the same datacenter so it can mount the
  volume, and reuses the already-populated models with no extra download.
- **Worker image:** the same image/template as the main endpoint (§2) — no separate
  build needed.
- **GPU:** priority order **L40S → RTX 6000 Ada → H100** (fp8-capable; A40 is not
  sufficient for this workload).
- **Active workers:** `0` (scale to zero when idle — reels are bursty/admin-triggered,
  not constant traffic like character-gen, so a cold start is an acceptable tradeoff).
- Add the same S3 env vars from §3.

Copy the new endpoint's ID and set it in loli-api's `.env`:
```
RUNPOD_VIDEO_ENDPOINT_ID=<the new endpoint id>
```
Leaving it unset (default) keeps today's behavior: reels share `RUNPOD_ENDPOINT_ID`
with every other job type.

---

## 5b. Dedicated batch endpoint (optional)

Story/trait **batch** jobs run each item's pipeline as several separate RunPod jobs
(pose + two 20-step 2511 passes). On the main §4 endpoint's all-**A40** fleet there
is no FP8 hardware, so the `fp8mixed` 2511 model runs dequantized and slow; items
can exceed the 10-min main per-job cap (`RUNPOD_EXECUTION_TIMEOUT_MS`) and get killed
and retried, and each cold start reloads ~20 GB from the volume (`BATCH_MAX_INFLIGHT=3`
fans that cold-start cost out three ways). Give batches their own fp8-capable endpoint
so items finish in minutes without timeout-retry churn.

Create a **third** Serverless endpoint (RunPod console → Serverless → New Endpoint):
- **Network volume:** attach the SAME volume as the main endpoint (`loli-comfy-models`,
  same datacenter) — reuses the already-populated ~20 GB of models with no extra
  download, and pins the endpoint to that datacenter so it can mount the volume.
- **Worker image / template:** the SAME worker image as the main endpoint (§2). RunPod
  binds a template to exactly one endpoint, so **clone** the main template (as was done
  for the video endpoint in §5a) rather than trying to share it.
- **GPU priority: `RTX A6000 → A40` (Ampere 48 GB ONLY — see warning).**
  **Verified 2026-07-13 in production: the CURRENT worker image CRASHES on Ada
  GPUs (L40S / L40 / RTX 6000 Ada)** — workers die ~2 min into the first job
  (at fp8 model load; the image's ComfyUI/torch build cannot run
  `qwen_image_edit_2511_fp8mixed` on Ada's native-FP8 path, while Ampere's
  dequantized path works). Symptom: jobs stuck in queue forever, workers
  flapping running → unhealthy, `stop container`/`create container` loops in
  worker logs, zero completions. Ampere-only immediately completed jobs.
  Re-adding Ada (for true FP8 speed) requires a worker-image upgrade
  (newer torch/ComfyUI with working Ada fp8 kernels) — test on ONE Ada worker
  before trusting it. **Exclude RTX 4090 / L4 (24 GB):** the 20 GB fp8 UNet +
  ~8 GB text encoder don't fit reliably, and the resulting OOM-retry churn is
  worse than a slower-but-roomy card.
- **FlashBoot:** ON.
- **Min / Active workers:** `1` while running batch sessions — this kills the ~4.5-min
  cold-start tax mid-batch. Scale back to `0` overnight so you stop paying for idle GPU
  when no batches are running (a min-1 worker bills continuously).
- **Max workers:** ≥ `BATCH_MAX_INFLIGHT` (3) so every in-flight batch item has a worker.
- **Idle timeout:** ~300 s — bridges the gaps between a single item's pipeline steps so
  the worker stays warm across pose → outfit → background instead of cold-starting each
  step.
- **Execution timeout:** ≥ 1200 s (matches `RUNPOD_BATCH_EXECUTION_TIMEOUT_MS`, 20 min).
- **Do NOT add the S3 `BUCKET_*` env vars to the worker template.** Verified
  2026-07-13: this worker image's direct-S3-upload path breaks job processing
  (every job fails with "Job processing failed" before the first step). The
  main template runs WITHOUT them — the worker returns outputs in the response
  and the API uploads to Supabase itself. Leave the template env empty.

Copy the new endpoint's ID and set it on the API deployment's env (see `.env.example`):
```
RUNPOD_BATCH_ENDPOINT_ID=<the new endpoint id>
```
Leaving it unset (default) keeps today's behavior: batches share `RUNPOD_ENDPOINT_ID`
with every other job type.

> **Live endpoint (created 2026-07-13):** id `4x3p45rwcqssu6`, template
> `loli-worker-batch` (env EMPTY — see S3 warning above) on the shared
> `loli-comfy-models` volume. GPU pool switched to **A6000/A40 Ampere-only**
> the same evening after the Ada crash was confirmed live. FlashBoot on,
> min 1 / max 3, 20-min execution timeout, ~300s idle.

> **Future ops task — worker-image slimming:** the ~4.5-min cold start is dominated
> by loading the worker image + 20 GB of models. Slimming the image (fewer custom
> nodes / smaller base) is a separate ops task tracked outside this endpoint setup;
> min-1 workers during batch sessions is the interim mitigation.

---

## 5c. Dark quality assets (07-14)

Two more model files upgrade skin realism and face-restore sharpness on the 2511
tier. Both ship **dark**: the code that reads them is already merged (workflow
graphs + env-var plumbing), but nothing changes at runtime until the files exist
on the volume AND one of the env vars below is set.

**Files to stage** (`download2.sh` §8f / §10f have the `wget` commands):

| File | Target folder | Purpose |
|---|---|---|
| `qwen-edit-skin.safetensors` | `loras/` | Skin realism LoRA (node `306` on the new `*_skinlora` graphs) — fights the plastic/waxy skin look, stacked after the realism LoRA (node 304) + softened NSFW LoRA (node 305 @ 0.65) |
| `GPEN-BFR-512.onnx` | `facerestore_models/` | Sharper, less-waxy face-restore model than the baked CodeFormer, for the pose ReActor pass (node 200, or node `215` `ReActorFaceBoost`) |

**Activation levers** — flip **ONE at a time**, verify a batch, and keep rollback
simple: revert the env var and restart (no worker-image change needed, same as
every other tier switch in this doc).

```bash
# (A) Skin-LoRA variant graphs — interactive pose step + interactive/pipeline/batch
# outfit step. Requires the same 5 Tier-A 2511 volume files as the existing
# 2511full graph (docs/OPS_OUTFIT_TIER_2511.md §4) PLUS qwen-edit-skin.safetensors.
COMFYUI_POSE_WORKFLOW_PATH_2511=workflows/pose_2511_skinlora_API.json
COMFYUI_OUTFIT_WORKFLOW_PATH_2511=workflows/outfit_cropstitch_2511full_skinlora_API.json
# or batch-only (leaves interactive edits on the current outfit graph):
COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH=workflows/outfit_cropstitch_2511full_skinlora_API.json

# (B) Sharper face-restore model for the EXISTING ReActor node 200 — works on ANY
# pose graph already loaded (v1 or 2511, skinlora or not); no workflow-path change.
POSE_REACTOR_FACE_RESTORE_MODEL=GPEN-BFR-512.onnx

# (C) ReActorFaceBoost — GPEN-BFR run as a dedicated boost stage ahead of the main
# swap (node 215 feeds node 200's optional face_boost input). This is an ALTERNATE
# pose graph, mutually exclusive with (A)'s pose graph — both set the same env var.
COMFYUI_POSE_WORKFLOW_PATH_2511=workflows/pose_2511_faceboost_API.json
```

Notes:
- (A) and (C) both set `COMFYUI_POSE_WORKFLOW_PATH_2511` — pick ONE pose graph at a
  time; there is no combined skinlora+faceboost graph yet. (B) is independent and
  layers on top of whichever pose graph is loaded, since it only overrides node
  200's `face_restore_model` field.
- **Assumption flagged for verification**: `ReActorFaceBoost`'s node/input names
  (`boost_model`, `interpolation`, `visibility`, `codeformer_weight`,
  `restore_with_main_after`, and the main `ReActorFaceSwap` node's optional
  `face_boost` input) were confirmed against the upstream
  `Gourieff/ComfyUI-ReActor` `nodes.py` source on GitHub — the ReActor pack is
  **not** installed in this repo's local `ComfyUI/custom_nodes/`, so re-check
  against the version actually running on the worker image before trusting (C)
  in production.

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
