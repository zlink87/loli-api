# Character Video / Reel Generation — Admin Panel Integration Guide

Handoff spec for wiring the **admin panel** to the upcoming image-to-video ("reel")
feature in `loli-api`. Everything here is self-contained; you do not need the
backend source.

> ## ⚠️ STATUS: SPEC ONLY — NOT YET DEPLOYED
> The endpoints below **do not exist in the API yet**. Backend is currently gated
> on a manual GPU validation test (confirming the RunPod worker actually returns
> the generated video file). This doc describes the **planned contract** so admin
> panel work can proceed in parallel. Do not point a real UI at these paths until
> backend confirms they're live — check with backend or watch `/openapi.json` for
> `VideoGenerateRequest` to appear before wiring real requests.

**Why this exists:** characters currently only have still images. This feature
lets an admin turn one of a character's existing gallery photos into a short
"reel" (image-to-video clip) using WAN 2.2, review it, and publish it so it
appears in chat. Generated videos are **admin-only** — there is no end-user
generation path.

---

## 0. Authoritative schema (once shipped)

Once deployed, the live OpenAPI schema is the source of truth:

- **Swagger UI:** `GET {API_BASE}/docs`
- **Raw schema:** `GET {API_BASE}/openapi.json` → `components.schemas.VideoGenerateRequest`

Prefer generating dropdown options (e.g. `motion` values) from `/openapi.json`
over hard-coding once it's live. Values below are provided for planning only.

---

## 1. Auth

Same as every other admin endpoint (`characters`, `batches`) — a Supabase JWT
(`Authorization: Bearer <token>`) belonging to a user who is either:
- flagged `role: "admin"` / `app_metadata.role: "admin"` in the JWT, or
- allowlisted in the backend's admin config.

No new auth mechanism. If your admin panel already calls `POST /v1/characters`
or `/v1/batches`, this reuses that exact same session/token.

---

## 2. New endpoints (planned)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/characters/{character_id}/videos` | Start generating a reel from one of the character's existing stills. Returns `202` + `jobId` immediately (same async pattern as generation/edit). |
| `GET` | `/v1/characters/{character_id}/videos` | List this character's reels — both unpublished drafts and published ones — for the review UI. |
| `POST` | `/v1/characters/{character_id}/videos/{actionId}/publish` | Publish a draft reel so it goes live in chat. |
| `GET` | `/v1/jobs/{jobId}` | **Existing endpoint, reused as-is** — poll for generation progress/result exactly like image jobs. |

### 2.1 `POST /v1/characters/{character_id}/videos`

```jsonc
POST /v1/characters/f47ac10b-.../videos
Authorization: Bearer <admin-jwt>
Content-Type: application/json

{
  "source_image_id": "9c1e2a4f-...",   // required — id of an EXISTING character_images row (a still)
  "motion": "hair_in_wind",             // required — motion preset, see §3
  "motionPrompt": null,                 // optional — when set, interpreted by the LLM and replaces the preset (see §3)
  "seed": null,                         // optional — omit for random
  "negativePrompt": null,               // optional — extra negative terms
  "width": null,                        // optional — see §3.1; None = server default (480)
  "height": null                        // optional — see §3.1; None = server default (832)
}
```

Response — `202 Accepted`:
```jsonc
{
  "jobId": "vidjob_abc123",
  "status": "queued",
  "reviewRequired": false   // NOTE: misleading name here — see §5 "review" callout
}
```

`character_id` comes from the URL path — don't also send it in the body.
`source_image_id` **must** reference a still (`image_type != "video"`) belonging
to that same character; the backend rejects (`422`) an id from another character
or one that is itself a video.

### 2.2 Poll `GET /v1/jobs/{jobId}` — unchanged mechanism, new `type` values

Identical polling loop to every other job type in this API:

```jsonc
// while running
{ "jobId": "vidjob_abc123", "type": "video_gen", "status": "running", "progress": 0.4 }

// on success
{
  "jobId": "vidjob_abc123",
  "type": "video_gen",
  "status": "succeeded",
  "results": [
    { "type": "video", "previewUrl": "https://.../videos/vidjob_abc123.mp4", "sha256": "..." }
  ],
  "promptUsed": "...",
  "seedUsed": 88213481
}
```

**`previewUrl` for video is expected to be a stable, non-expiring URL** (the
production storage path uploads straight to the Supabase bucket and returns its
permanent public URL — unlike the time-limited signed preview URLs images get
from local-storage fallback). Don't build in an expiry/refresh assumption for
video previews; confirm this once real responses are available.

Videos are **1–4 minutes of GPU time**, much slower than an image job — don't
reuse an aggressive image-job poll interval; 5–10s is reasonable.

### 2.3 `GET /v1/characters/{character_id}/videos` — review list (planned shape)

```jsonc
[
  {
    "actionId": "b2b5...",             // chat_persona_actions.id — use this to publish
    "characterImageId": "d91a...",     // character_images.id (the gallery row)
    "videoUrl": "https://.../videos/vidjob_abc123.mp4",
    "sourceImageId": "9c1e2a4f-...",   // the still it was generated from
    "motion": "hair_in_wind",
    "seed": 88213481,
    "isPublished": false,               // maps to chat_persona_actions.is_active
    "createdAt": "2026-07-08T10:00:00Z"
  }
]
```

Use this to render a review queue: thumbnail/video preview, the source still for
comparison, and a **Publish** button per unpublished item.

The persisted chat quick-action button caption (the `chat_persona_actions.label`)
is derived server-side: for a custom `motionPrompt` it is the LLM-generated
`motionLabel`; otherwise it is derived from the chosen `motion` preset.

### 2.4 `POST /v1/characters/{character_id}/videos/{actionId}/publish`

No body. Flips `chat_persona_actions.is_active` from `false` → `true` for that
row. Returns the updated row (`200`) with `isPublished: true`. This is a one-way
action in the UI — there's no unpublish endpoint planned; if you need to pull a
published clip, that's a manual/backend task for now.

---

## 3. `motion` — candidate preset values

Planning-stage list (confirm against `/openapi.json` once shipped):

`subtle_idle`, `slow_turn`, `hair_in_wind`, `hair_flip`, `blow_kiss`, `wave`,
`walk_toward`, `look_over_shoulder`, `wink`, `lip_bite`, `bend_to_camera`,
`head_tilt`, `adjust_hair`, `glance_up_through_lashes`, `gentle_laugh`,
`shoulder_sway`, `come_hither`, `twirl`, `peace_sign`, `touch_lips`,
`slow_stretch`, `lean_on_hand`, `gaze_and_smile`, `nod_and_smile`

Render as a dropdown, one clear default (`subtle_idle` — lowest motion, safest
for identity). `motionPrompt` is an optional free-text field for admins who want
to describe their own motion. When set, it is interpreted by the LLM (Venice) into
a WAN-friendly description and a short button label, and **replaces** the preset
entirely (the preset is ignored); it falls back to the raw text when the LLM is
off/down. Treat it like an "advanced" field, not primary UI.

### 3.1 `width` / `height` — optional resolution opt-in

Both default to `null` → the server default of **480×832** (safe for the current
RunPod worker GPU tier). To render a sharper clip, send an allowlisted `(width,
height)` **pair** — either both or neither:

- `480 × 832` (default)
- `576 × 1024`
- `720 × 1280` (WAN 2.2 14B native tier — sharpest, but ~2–3× VRAM / slower)

Any other pair, or only one of the two set, → `422`. Higher tiers risk OOM on
the current worker (`max_oom_attempts=1`); 720p should become the default only
once the worker GPU tier is confirmed to tolerate it.

### 3.2 Frame interpolation (deploy-side, OFF by default)

Smooth 16→32fps playback (RIFE/FILM) is shipped as a separate workflow,
`workflows/wan_i2v_interp.json`, and is **off by default**. An operator enables it
by pointing `COMFYUI_VIDEO_INTERP_WORKFLOW_PATH` at that file; when unset the worker
uses the normal `wan_i2v.json`. The output frame_rate is scaled automatically
(gen fps × interpolation multiplier) so playback stays real-time. Requires the
RunPod worker image to have the ComfyUI `FrameInterpolate` node **and** a staged
RIFE/FILM weight — a deploy-side action; do not enable it until that image is
confirmed, or generation will fail on the worker.

### 3.3 First-last-frame (FLF2V) endings (deploy-side, OFF by default)

The `useFlf2v` request flag (defaults `false`) opts a reel into the first-last-frame
path: WAN is conditioned on **both** the source still (start frame) and a controlled
**end frame**, so the clip resolves on an in-focus, camera-facing beat and identity
drift drops (the model synthesises coherent mid-frames instead of drifting to a soft,
out-of-focus tail). It is shipped as a separate workflow, `workflows/wan_i2v_flf2v.json`
(a `WanFirstLastFrameToVideo` graph), and is **doubly gated**: it runs only when the
request sets `useFlf2v: true` **AND** the operator has pointed
`COMFYUI_VIDEO_FLF2V_WORKFLOW_PATH` at that file. When either is missing, or if the
end frame can't be produced, the worker silently falls back to the normal i2v path —
`useFlf2v` never hard-fails a job.

**End frame — which tier ships:** the end frame is a **deterministic PIL crop-zoom**
(~1.18× toward the upper-centre/face) of the source still (Tier 2). This is
identity-perfect (a straight crop of the source), always succeeds, and needs no extra
GPU/network. A Tier-1 "soft-smile, camera-facing" edit-pipeline variant was scoped but
**not shipped** — the existing still-edit path is async/queue-based with no synchronous
single-still helper, so it would require a second RunPod round-trip and can't be
verified locally (a hook + `TODO(tier1)` is left in `services/end_frame.py`).

**Deploy gate:** enabling FLF2V requires the RunPod worker image to have the
`WanFirstLastFrameToVideo` node (ComfyUI ≥ 0.3.48). Do not point
`COMFYUI_VIDEO_FLF2V_WORKFLOW_PATH` at the file until that image is confirmed, or
generation will fail on the worker.

| Setting / flag | Default | Effect |
|---|---|---|
| `COMFYUI_VIDEO_FLF2V_WORKFLOW_PATH` (env) | `""` (OFF) | Path to the FLF2V graph; empty disables the branch entirely |
| `useFlf2v` (request) | `false` | Per-reel opt-in; only honored when the env path above is set |

---

## 4. UI to add

1. **Entry point:** on a character's detail/gallery view, a "Generate Reel" action
   next to (or on) each existing still — this is how `source_image_id` gets set.
   **Exclude any row that is itself a video** from being pickable as a source.
2. **Generate form:** motion preset dropdown (default `subtle_idle`) + optional
   free-text "describe your own motion" field (LLM-interpreted, replaces the
   preset), behind an "Advanced" disclosure. Submit → `202` +
   `jobId` → start polling `GET /v1/jobs/{jobId}` (reuse your existing image-job
   poller if it's generic).
3. **Progress state:** video jobs are slow (up to several minutes) — show a
   clear "generating your reel, this can take a few minutes" state, not a
   spinner sized for image-job latency.
4. **Review queue:** a new "Reels" tab/section per character (or a shared
   cross-character queue) driven by `GET /v1/characters/{id}/videos`, showing
   unpublished drafts first. Each item: inline video player, the source still
   for side-by-side comparison, **Publish** button.
5. **Face-drift check (important — see §5):** before publishing, an admin should
   actually watch the clip, not just skim a thumbnail — WAN can drift the
   character's face over the clip, and that's the entire reason this feature is
   draft-then-publish instead of auto-live.

---

## 5. Behavior contract

- **Nothing is public until explicitly published.** A successful generation job
  does *not* mean the clip is visible in chat — it lands as an inactive
  `chat_persona_actions` row. Only the `.../publish` call makes it live. Treat
  `reviewRequired: false` in the job-creation response as a **naming artifact of
  the shared job-response schema** — it does *not* mean "safe to auto-publish."
  Review for this feature is enforced by the draft/publish split, not that flag.
- **Identity can drift.** Unlike image edits (which are guaranteed to preserve
  the face — see the outfit/pose tabs), video is generative motion from a start
  frame and can visibly warp the face on longer or higher-motion clips. Backend
  is adding a face-lock pass, but **admin visual review before publishing is the
  actual safety net** — don't skip it in the UI flow (e.g. don't add a "publish
  all" bulk action).
- **One still → one clip per request.** There's no batch/multi-clip generation
  in this slice — each request is a single reel from a single chosen still.

---

## 6. Validation / edge cases

- `source_image_id` not found, not owned by `character_id`, or itself a video →
  `422`.
- `motion` must be one of the enum values — unknown value → `422`.
- Publishing an already-published action, or an unknown `actionId` → `404`/`409`
  (exact code TBD — check `/openapi.json`/response once shipped).
- Video generation is **admin-only** — expect `403` if the calling user isn't
  an admin (identical to `/v1/characters` today).

---

## 7. Open questions for backend (resolve before or during integration)

- **Does the admin panel already have a way to list a character's existing
  gallery stills (`character_images`)?** This API has historically been
  **write-only** for that table — there is no general "list a character's
  images" endpoint today, only the new video-specific list in §2.3. If the
  admin panel currently shows the gallery via a direct Supabase read, the
  "pick a source still" UI can keep using that; if not, flag this back — a
  general gallery-list endpoint may need to be added alongside this feature.
- **Exact HTTP status codes** for the publish edge cases in §6 — placeholders
  until implemented; confirm against `/openapi.json` or ask backend.
- **RLS on the chat app's own read path for `chat_persona_actions`.** This backend
  writes with a service-role key (bypasses RLS), but if the chat app reads with a
  different, more restrictive policy (e.g. one that implicitly assumed
  `media_type='image'`), a published video could have `is_active=true` in the DB
  and **still never render** for end users — with no error anywhere. Whoever owns
  the chat app's Supabase policies should confirm `media_type='video'` rows are
  readable before this ships.
- **Supabase Storage bucket MIME/size limits.** The bucket videos upload into needs
  `video/mp4` added to its allowed MIME types and a size limit that comfortably
  covers a short clip (~5–30 MB). This is a Supabase Studio config change, not
  something either app's code controls — confirm it's been done before testing
  playback.

---

## 8. Definition of done

- [ ] "Generate Reel" entry point added per still in the character gallery
      (excludes video rows as source candidates).
- [ ] Generate form: motion dropdown (default `subtle_idle`) + optional
      free-text "describe your own motion" (LLM-interpreted, replaces the preset)
      behind an Advanced disclosure.
- [ ] Job polling reuses/extends the existing poller; progress UI accounts for
      multi-minute video generation time.
- [ ] Reels review queue (`GET /v1/characters/{id}/videos`) with inline video
      preview + Publish button per draft.
- [ ] Publish action wired (`POST .../videos/{actionId}/publish`); no bulk/auto
      publish added.
- [ ] Confirmed with backend: gallery-list access for the source-still picker
      (§7), exact error codes (§6), and that `/openapi.json` now exposes
      `VideoGenerateRequest` before treating this as live.
