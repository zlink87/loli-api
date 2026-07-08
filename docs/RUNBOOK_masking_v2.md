# Masking V2 (crop-and-stitch) — deploy & test runbook

The V2 outfit-edit graph fixes the mangled-garment-boundary problem: instead of
re-diffusing the whole body at low effective resolution, it masks the edit region
(person or garment) **minus the head**, crops to it, regenerates at full model
resolution, and stitches it back so **every pixel outside the mask — including the
face — is byte-identical to the source**.

**All the code is written and tested (122 unit tests pass). V2 is OFF by default**
(`COMFYUI_OUTFIT_WORKFLOW_PATH_V2=""`), so nothing changes until you deliberately
enable it. Your job is: redeploy the worker, flip the flag, look at the output,
keep it or roll back. The old graph stays intact for instant rollback.

Files added:
- `loli_api/workflows/outfit_cropstitch_API.json` — the V2 graph.
- `loli_api/workflows/outfit_cropstitch_maskpreview_API.json` — same graph but the
  output is the **editable mask** (the inpaint chain is pruned, so it runs fast/cheap).

---

## Step 1 — Redeploy the worker image (required once)

V2 uses `ClothesSegment` + `InpaintCropImproved` + `InpaintStitchImproved`, which
are baked into the worker image but may not be on the running endpoint yet. Follow
[RUNBOOK_reels_and_coldstart.md](RUNBOOK_reels_and_coldstart.md) §2 (redeploy pinned
to the `:<sha>` digest). This is the *same* redeploy that fixes reels — do it once.

**Verify the nodes are live** (from a shell that can reach the endpoint, or the Pod
web terminal): `GET http://127.0.0.1:8188/object_info` and grep for
`ClothesSegment`, `InpaintCropImproved`, `InpaintStitchImproved`, `DifferentialDiffusion`.
If any is missing, the image is stale — redeploy before continuing.

---

## Step 2 — Preview the mask first (fast, cheap, no Qwen inference)

Before spending GPU on real edits, confirm the mask is correct.

1. On the API host set: `COMFYUI_OUTFIT_WORKFLOW_PATH_V2=workflows/outfit_cropstitch_maskpreview_API.json` and restart the API.
2. Run one outfit edit (`POST /v1/edit/outfit`) on a representative hero — ideally the
   pink-hair `crop_top_cargo` case from the bug report, plus one nude source and one
   with voluminous/long hair.
3. The returned image is the **editable mask** (white = will be edited). Confirm:
   - White covers the **body/garment** region.
   - **Black over the face and hair** (the head-protect subtraction is working).
   - No white bleeding far into the background.

If the head isn't protected (white over the face): the server head mask isn't being
staged — check the API log for `Head mask staged (...)`. With the Phase-0 fail-closed
fix, even an undetected face gets a protective box, so this should always be black
over the head.

---

## Step 3 — Real A/B test

1. Set `COMFYUI_OUTFIT_WORKFLOW_PATH_V2=workflows/outfit_cropstitch_API.json` and restart the API.
2. Re-run the same edits. Compare against V1 (unset the var to get V1). Look for:
   - Clean garment/waist boundary (the original bug).
   - Face/hair/skin **identical** to the source.
   - Sharper fabric detail (full-resolution crop).
3. Tune if needed (all server-side, no rebuild — restart API to reload):
   - `outfit_cropstitch_API.json` node `106.denoise` (BODY 0.85 / GARMENT 0.80) — lower = more faithful to the source body, higher = more outfit change.
   - node `235.output_target_width/height` (1024) — sampling resolution of the crop.
   - node `235.context_from_mask_extend_factor` (1.2) and `mask_blend_pixels` (16) — how much context around the mask and how soft the stitched seam is.

---

## Step 4 — (Optional) Turn on the tight GARMENT mask per outfit

By default every outfit uses **BODY mode** (person mask + crop-and-stitch) — universal
and safe for nude *and* dressed sources. **GARMENT mode** (`ClothesSegment`) gives an
even tighter, semantic clothing mask (also excludes hair/skin) but **only works on a
dressed source** (it finds nothing on a nude body).

To graduate an outfit (e.g. the `crop_top_cargo` bug case) after you've confirmed it on
a **dressed** source: add it to `GARMENT_MODE_OUTFITS` in
[outfit.py](loli_api/api/v1/endpoints/outfit.py) (currently an empty set), restart the
API, and re-preview the mask (Step 2) to confirm the clothing is tightly masked.

---

## Rollback

Set `COMFYUI_OUTFIT_WORKFLOW_PATH_V2=""` and restart the API — instantly back to V1
(`test_final_API.json`). Background, pose, and batch edits are **never** touched by this
flag; they stay on V1 throughout.

## Notes / limits of this first cut
- **Interactive `/v1/edit/outfit` only.** Background/pose/batch stay on V1 by design
  (smaller blast radius). Once V2 is proven, the batch pipeline can be pointed at it too
  (one line in `main.py`, `pipeline_worker` outfit path).
- **Head protection is the server YuNet mask** (now fail-closed). SAM3 "face, hair, neck"
  refinement was intentionally left out of this cut to avoid loading a 6–8 GB model on
  every edit; add it later if BODY-mode edges need hair-following.
- If the first real run errors, paste me the RunPod job error — a hand-authored graph
  occasionally needs one wiring tweak, and the message pinpoints it.
