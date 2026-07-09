# Outfit Tier 2511 — repoint batches to the strong outfit tier

**What this is:** an ops runbook for moving the **Story-Batch outfit step** off its
current weak tier onto the strong `2511full` (Tier-A) quality tier. Confirmed this
session (2026-07-09): real batches are rendering on `rapid_cropstitch` — a
materially weaker tier — because of how the deployed environment's env vars
resolve. This doc covers what to change, what the RunPod worker volume needs
first, and how to prove the change actually took.

---

## 1. Why this matters

The outfit step (crop-and-stitch: remove the source garment, apply the target) is
the same graph shape across tiers but runs its `KSampler` at very different
strengths:

| Tier | Workflow file | Steps | cfg | denoise |
|---|---|---|---|---|
| `2511full` — **strong** (Tier A) | `workflows/outfit_cropstitch_2511full_API.json` | 20 | **2.5** | 0.9 |
| `rapid_cropstitch` — **weak** (V2) | `workflows/outfit_cropstitch_API.json` | 8 | **1.0** | 0.9 |
| `v1` — weakest (legacy, whole-frame, no crop-and-stitch) | `workflows/test_final_API.json` | — | — | — |

At `cfg 1.0` the negative prompt is mathematically inert (cfg 1 skips the negative
branch of classifier-free guidance), so nothing actively pushes the sampler away
from the source clothing — on a dressed source, the original garment tends to
reconstruct through the edit instead of being replaced. `2511full`'s `cfg 2.5` (full
non-distilled Qwen-Image-Edit-2511 + realism/NSFW LoRAs, loaded natively) is the
tier that reliably fixes this and removes the source garment.

**Confirmed this session:** live batches were resolving to `rapid_cropstitch`, not
`2511full` — because only `COMFYUI_OUTFIT_WORKFLOW_PATH_V2` was set on the deployed
environment; the stronger tier's var was never set there.

---

## 2. The precedence chain (background)

Both the interactive pipeline engine and the batch engine resolve the outfit
workflow through the same chain, strongest first (`loli_api/main.py`, batch-engine
construction):

```
COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH        # batch-ONLY override — takes precedence when set
  -> COMFYUI_OUTFIT_WORKFLOW_PATH_2511    # Tier A, strong
  -> COMFYUI_OUTFIT_WORKFLOW_PATH_V2      # Rapid crop-and-stitch, weak
  -> COMFYUI_OUTFIT_WORKFLOW_PATH         # V1 whole-frame, weakest (always set — the fallback)
```

All four are plain env vars (`loli_api/config.py`); the first three default to `""`
(falsy/skipped), the last defaults to `workflows/test_final_API.json`. Whichever is
first non-empty in that chain is what loads — and because these are hand-authored
ComfyUI graphs, nothing validates at request time that the "confirmed" tier is the
one that actually loaded. That's why this class of bug (a deploy env silently
landing on a weaker tier) ships unnoticed: every log line upstream keeps printing
generic "outfit workflow" text regardless of which file loaded.
`services/workflow_meta.py`'s `describe_template()` exists specifically to classify
a *loaded* template after the fact (node `"301"` present -> `2511full`; no `"301"`
but node `"235"` is `InpaintCropImproved` -> `rapid_cropstitch`; neither -> `v1`) —
see §5 for how to read it.

---

## 3. The fix — set the env var

On the API's deployment host (Railway, or wherever the `loli-api` control plane
runs — see `docs/DEPLOYMENT.md`), set:

```bash
COMFYUI_OUTFIT_WORKFLOW_PATH_2511=workflows/outfit_cropstitch_2511full_API.json
```

This cuts over the interactive outfit path, the `/v1/edit` pipeline, **and**
batches — all three share the same precedence chain.

**To stage it on batches only first** (leave interactive edits on the current
tier), set the batch-only override instead — it takes precedence over `_2511`/`_V2`
for the batch engine alone:

```bash
COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH=workflows/outfit_cropstitch_2511full_API.json
```

**Optional hard guard** — fail batch-worker startup instead of silently falling
back to `v1` if the chain ever resolves empty (e.g. a future CI-built image missing
the `.env`):

```bash
BATCH_REQUIRE_CROPSTITCH_OUTFIT=true
```

Default is `false` (preserves today's silent-fallback-to-V1 behavior). When `true`,
`BatchPipelineWorker.start()` raises `RuntimeError` naming the resolved path if the
batch engine's outfit tier comes back `v1` (`workers/batch_pipeline_worker.py`,
`_check_cropstitch_outfit_required`).

**Restart the API** after changing any of these — workflow templates load once at
worker startup, not per-request.

---

## 4. Prerequisite — stage the 2511 models on the RunPod volume

The `2511full` workflow loads five files by exact filename (its loader nodes
`301`/`302`/`303`/`304`/`305` are hardcoded to these names) that the Rapid tier does
not need. If they're missing on the volume, 2511 jobs fail loudly on the worker —
better than silently reconstructing the source garment, but confirm they're staged
**before** flipping the env var:

| File | Target folder | Purpose |
|---|---|---|
| `qwen_image_edit_2511_fp8mixed.safetensors` | `diffusion_models/` | Tier-A UNet (~20 GB) |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | `text_encoders/` | Text encoder (~8 GB; shared with base Qwen-Image-Edit) |
| `qwen_image_vae.safetensors` | `vae/` | VAE |
| `URP_20.safetensors` | `loras/` | Realism LoRA — anti-plastic, identity-preserving |
| `qwen-image-edit-plus-nsfw-lora.safetensors` | `loras/` | NSFW LoRA — **required** for HIGH-tier editing (base 2511 is only mildly NSFW) |

Reference: `download2.sh` §10 ("TIER A — FULL (non-distilled) Qwen-Image-Edit-2511
quality path", lines 156–181) has the `wget` block for all five — it exists and is
current. **Note the script's own caveat**: those URLs were not download-tested when
added; verify each against the current Comfy-Org / author HF repos before relying
on a fresh volume build (repo paths and casing drift over time).

**Cost:** adds ~30 GB to the worker image, and 20 sampler steps on the full
non-distilled model vs. 8 on the distilled Rapid checkpoint puts `2511full` at
roughly **2–3x the GPU time** of the current tier, per outfit step. Budget
accordingly — a batch item may chain outfit + pose + background in one job.

---

## 5. Verify it took

Any of these read the same ground truth (what actually loaded), not the static
config default:

1. **Startup log**, after redeploy — look for the **batch engine** line
   specifically:
   ```
   [WORKFLOW-RESOLVED] outfit -> .../workflows/outfit_cropstitch_2511full_API.json tier=2511full
   [WORKFLOW-RESOLVED] batch engine: {'pose': {...}, 'outfit': {'tier': '2511full', ...}, 'background': {...}}
   ```
   (`pipeline_worker._load_workflows`, emitted per engine at boot.)

2. **`GET /debug/workflow-config`** (DEBUG builds only) — resolved
   `{path, tier, sampler}` per engine per step:
   ```jsonc
   {
     "pipeline": {"outfit": {"path": "...", "tier": "2511full", "sampler": {"steps": 20, "cfg": 2.5, "denoise": 0.9}}, ...},
     "batch":    {"outfit": {"path": "...", "tier": "2511full", "sampler": {"steps": 20, "cfg": 2.5, "denoise": 0.9}}, ...}
   }
   ```

3. **Per-image, after the fact** — every generated batch photo records which tier
   actually rendered it, written at publish time from the live job's step trace:
   ```
   character_images.metadata -> workflow_meta -> steps[] -> {step: "outfit", tier: "2511full", workflow_path, seed}
   ```
   Query new batch items and confirm `tier == "2511full"` on the `"outfit"` step
   entry — not `"rapid_cropstitch"` or `"v1"`.

---

## 6. Rollback

Unset `COMFYUI_OUTFIT_WORKFLOW_PATH_2511` (and `COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH`
if you set that instead) and restart. The chain falls back to whatever was
previously resolving (`_V2` / `rapid_cropstitch` if still set, else `v1`). No code
change, no worker image change required.
