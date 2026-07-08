# Ops Runbook — Reels reliability + RunPod cold-start (owner actions)

These are the steps that must be done **outside the codebase** (RunPod dashboard,
Supabase, GitHub Actions). The code-side Phase-0 fixes are already committed
(head-mask fail-closed, tighter outfit feather, reel-persistence surfacing,
keep-warm service, `NO_OUTPUT_ERROR` classification). Do these in order.

---

## 1. Diagnose why reels fail (do FIRST — don't guess)

The real RunPod error already reaches the local job record.

1. Reproduce one failing reel (admin UI, or `POST /v1/characters/{id}/videos`), note the `jobId`.
2. `GET /v1/jobs/{jobId}` (as admin) → read `error_message` + `error_code`.
3. Cross-check RunPod → Serverless → your endpoint → **Requests** → open the failed request → **Logs**
   (ComfyUI stderr shows validation/CUDA/S3 errors the local record may truncate).
   API alternative: `GET https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/status/<runpod_id>`
   with `Authorization: Bearer $RUNPOD_API_KEY`.

**Map the error to the fix:**

| Error signature | Cause | Fix |
|---|---|---|
| `node type VideoImagesBridge does not exist` (or KeyError on class_type at validation) | **Deployed worker image is stale** | §2 Redeploy |
| `...safetensors ... not in list` / `FileNotFoundError` on a WAN weight | WAN weights missing/misnamed on the volume | §3 Re-stage weights |
| `mime type ... not supported` / S3 `AccessDenied` / `Payload too large` | Supabase bucket rejects `video/mp4` | §4 Bucket config |
| `CUDA out of memory` → `GPU_OOM_ERROR` | Dual-14B + 81-frame decode too big | §5 env + Phase-2 Lightning |
| local `... exceeded local timeout` / `TIMED_OUT` | Cold-load of ~35 GB too slow | §6 cold-start + Phase-2 Lightning |
| Job **SUCCEEDED** but reel missing from review; log `Reel persistence failed:` | DB write failed | Already fixed in code — it now reports **FAILED / `REEL_PERSIST_ERROR`** with the preview URL kept for recovery |

---

## 2. Redeploy the worker image (most likely reel fix)

The `VideoImagesBridge` node — and the staged masking nodes (`ClothesSegment`,
`SAM3Segment`, crop-and-stitch) — only exist in a freshly built image.

1. GitHub → **Actions → "Build worker image"** → confirm the latest run is green and
   newer than the reels commit (`3ab10d7`). If not, **Run workflow** (manual dispatch).
2. Copy the immutable tag from the run's "Compute image name" step:
   `ghcr.io/zlink87/loli-worker:<sha>`.
3. RunPod → endpoint → **Settings** → set **Container Image** to that **`:<sha>` digest**
   (not `:latest` — RunPod caches `:latest` and may not repull) → **Save / release new workers**.
4. If GHCR is private: ensure the endpoint has Container Registry Auth (GH PAT, `read:packages`).
5. Re-run one reel; confirm §1 step 2 reaches `SUCCEEDED` with an `.mp4` `preview_url`.

> Rule of thumb: **any Dockerfile.worker / worker_custom_nodes change requires this redeploy** —
> the GH Action only builds+pushes; nothing auto-updates the running endpoint.

---

## 3. Verify WAN weights on the network volume (if §1 shows a missing file)

Launch a cheap Pod with the models volume attached → Web Terminal:

```
ls -la /runpod-volume/models/diffusion_models/   # wan2.2_i2v_high/low_noise_14B_fp8_scaled.safetensors
ls -la /runpod-volume/models/text_encoders/       # umt5_xxl_fp8_e4m3fn_scaled.safetensors
ls -la /runpod-volume/models/vae/                 # wan_2.1_vae.safetensors
df -h /runpod-volume                              # free space
```

If any WAN file is missing/short, re-run the WAN block of `download2.sh` (lines ~83-94) on the volume. No image rebuild needed.

---

## 4. Supabase bucket — allow video (if §1 shows a MIME/size reject)

Supabase → Storage → bucket `images_generated` → Settings:
- **Allowed MIME types:** add `video/mp4` (and `video/webm`).
- **File size limit:** raise above the largest reel (a 480×832×81f H.264 clip is ~1–5 MB; the MIME allowlist is the more common blocker).

---

## 5. OOM insurance (endpoint env, no rebuild)

RunPod → endpoint → **Settings → Environment Variables**:
- `PYTORCH_CUDA_ALLOC_CONF = expandable_segments:True`

(The durable OOM/timeout fix is **Phase 2**: WAN LightX2V 4-step Lightning LoRAs — ~20× faster, volume + JSON only, no rebuild.)

---

## 6. Cold-start — cheapest optimizations (chosen path: no 24/7 active worker)

RunPod → endpoint → **Settings**:
- [ ] **Resize the network volume to ≥ 80 GB.** Current 40 GB can't hold the ~20 GB image stack + ~35 GB WAN. Volumes only grow. (Do this before §3.)
- [ ] **Idle timeout → 120–300 s** (from ~5 s). *Biggest free win* — a worker survives between requests in a session instead of re-streaming ~35 GB on every one.
- [ ] **FlashBoot: ON** (free; helps most once traffic is steady).
- [ ] **GPU priority list**: 2–3 types (e.g. RTX 4090 → L40S → A5000, 24 GB floor) + allow all regions the volume supports → avoids "throttled" waits that feel like cold starts.
- [ ] Confirm the endpoint env also has the Supabase S3 `BUCKET_*` vars (per `RUNPOD_SETUP.md`).

**Optional API keep-warm pinger (code, OFF by default):** to keep a worker warm through
short gaps *within* an active session, set on the API host:
```
WARMUP_ENABLED=true
WARMUP_INTERVAL_SECONDS=200     # ping cadence within the warm window
WARMUP_WINDOW_MINUTES=15        # keep pinging this long after the last real job
WARMUP_WORKFLOW_PATH=           # empty -> generation workflow; point at a tiny 1-step graph to cut cost
```
It only pings while a real job ran within the window, so it costs nothing when idle.
Each ping is a real `/run` job (a `/health` probe does NOT hold a worker warm), so
point `WARMUP_WORKFLOW_PATH` at a minimal graph to keep it cheap. This is a
complement to the dashboard settings above, not a replacement.

---

## Verify

- **Reels:** after §2 (+§3/§4 if indicated), a submitted reel reaches `SUCCEEDED` with an `.mp4` preview and appears in the review queue.
- **Cold-start:** two back-to-back generations — the second skips the multi-minute cold start (warm worker within the idle window).
- **Masking (already shipped, server-side):** on a hero with a hard-to-detect face, an outfit edit no longer destroys the face (fail-closed head box), and edge bleed is reduced (tighter feather).
