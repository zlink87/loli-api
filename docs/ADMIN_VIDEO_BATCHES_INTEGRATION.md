# Character Video Batches — Admin Panel Integration Guide

Handoff spec for wiring the **admin panel** to the **per-character Video Batches**
feature in `loli-api`. Everything here is self-contained; you do not need the backend
source.

**What the feature does:** an admin opens a character, multi-selects N of its existing
gallery **stills**, assigns each still an **action** (a preset from a tiered action
catalog, or a hand-written motion prompt), picks batch-wide defaults, and launches. Each
item animates one still into a short WAN 2.2 image-to-video ("reel") clip. Generation is
async; the UI polls for progress. This is the **batch** sibling of the single-clip reel
feature (`docs/ADMIN_VIDEO_INTEGRATION.md`) — same output tables, same draft/publish
safety model, but N clips per launch instead of one.

**Where the data lands (this is the point):** succeeded items write to the REAL product
schema the chat app reads —

- every finished clip becomes a `character_images` row with `image_type='video'`
  (`source_image_id` points at the still it was animated from);
- each clip also gets a `chat_persona_actions` quick action (`media_type='video'`)
  created **as a DRAFT** (`is_active=false`) — nothing is visible in chat until it is
  published.

So after a batch completes the admin reviews the clips and publishes the good ones
(per-item or in bulk); publishing flips the draft quick actions active.

---

## 0. Authoritative schema

The live OpenAPI schema is the source of truth for every field and enum value:

- **Swagger UI:** `GET {API_BASE}/docs`
- **Raw schema:** `GET {API_BASE}/openapi.json` → `components.schemas.VideoBatchCreate`,
  `VideoBatchRead`, `VideoBatchItemRead`, `VideoActionCatalogRead`, …

Fetch `/openapi.json` at build time to generate types / dropdown option lists rather
than hard-coding. The values below are provided for convenience but OpenAPI is canonical.

> **Field casing (read this once).** The batch/item/estimate/catalog models serialize in
> **snake_case** (`items_total`, `source_image_id`, `motion_text`, `runpod_status`). Two
> ad-hoc endpoints return a small camelCase object instead: the bulk-publish response
> (`{ "batchId", "published" }`). Don't assume one casing across the whole surface —
> follow each shape below.

---

## 0.5 Base URL, auth & CORS (do this first)

- **Base URL (`{API_BASE}`):** get it from backend ops (the Railway/deploy URL). All
  paths below are under `/v1`.
- **Auth:** every endpoint is **admin-only** and uses the same bearer flow as
  `/v1/characters` and `/v1/batches`. Send the signed-in user's Supabase access token:
  `Authorization: Bearer <supabase_access_token>`. If the admin panel proxies through a
  server route (`forwardToApi`), that helper attaches the bearer — reuse it unchanged.
  A user is admin if their JWT has `app_metadata.role == "admin"` **or** their `sub` is in
  the backend `ADMIN_USER_IDS` allowlist. Non-admin → **403**; no/invalid token → **401**.
- **CORS:** the admin panel's origin must be on the backend `CORS_ALLOW_ORIGINS`
  allowlist or browser calls fail before auth runs. Coordinate with backend ops.

> Single-admin by design: there is no per-user isolation. Every admin sees the same
> characters and batches.

---

## 1. Data model & lifecycle

Two loli-api-owned tables back this feature (migration
`loli_api/migrations/0008_character_video_batches.sql`, run once): a batch header and its
items. You never read them directly — the endpoints below are your contract — but the
lifecycle drives all your UI states.

**Batch `status`:**

| status | meaning |
|---|---|
| `planning` | transient — rows being inserted at launch |
| `planned` | a **dry-run** result: items resolved + persisted, no GPU jobs enqueued (terminal until you launch it) |
| `running` | at least one item is not yet terminal |
| `completed` | every item succeeded |
| `partial` | some succeeded, some failed |
| `failed` | every item failed |
| `cancelled` | the batch was cancelled |

**Item `status`:** `pending` → `queued` → `running` → `succeeded` | `failed` |
`cancelled`.

An item is only marked `succeeded` **after** its `character_images` row +
`chat_persona_actions` draft exist (publish-before-terminal), so `items_succeeded`
doubles as "clips ready to publish".

**Poll cadence:** after launching, `GET /v1/video-batches/{id}` every ~5–10s while
`status ∈ {planning, running}`; stop on any terminal status. Video is GPU-heavy — do not
reuse an image-job's aggressive poll interval (see §6 on liveness).

---

## 2. Endpoints

Base path `/v1`. All return JSON; async actions return **202 Accepted**.

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/v1/characters/{id}/video-batches` | Plan + persist + (async) launch a batch | 202 → `VideoBatchLaunchResponse` |
| GET | `/v1/characters/{id}/video-batches` | List a character's video batches | 200 → `VideoBatchRead[]` |
| GET | `/v1/video-batches/action-catalog` | Tiered action catalog for the picker | 200 → `VideoActionCatalogRead` |
| GET | `/v1/video-batches/{id}` | Batch aggregate **+ all items** | 200 → `VideoBatchDetailRead` |
| GET | `/v1/video-batches/{id}/results?ready_only=true` | Succeeded items (clip URLs) | 200 → `VideoBatchItemRead[]` |
| POST | `/v1/video-batches/{id}/launch` | Promote a dry-run (`planned`) batch as-is | 202 → `VideoBatchRead` |
| POST | `/v1/video-batches/{id}/retry` | Re-enqueue failed items | 202 → `VideoBatchRead` |
| POST | `/v1/video-batches/{id}/publish` | Bulk-flip succeeded items' draft actions active | 200 → `{ batchId, published }` |
| DELETE | `/v1/video-batches/{id}` | Cancel the batch (aborts in-flight GPU jobs) | 204 |
| POST | `/v1/video-batches/{id}/items/{item_id}/rerun` | Re-run one succeeded/failed item | 202 → `VideoBatchItemRead` |

**Per-item publish** reuses the **existing single-reel route** (not a new one):
`POST /v1/characters/{id}/videos/{action_id}/publish` (see
`docs/ADMIN_VIDEO_INTEGRATION.md` §2.4). Use the item's `action_id` as `{action_id}`.

**Error codes:** 401 (auth), 403 (not admin), 404 (character / batch / item / still not
found), 409 (launch when not `planned` / retry when nothing failed / rerun an item that
isn't `succeeded`|`failed`), 422 (validation — bad preset, still from another character,
still that is itself a video, explicit tier gated off), 503 (video-batch services not
configured on the backend — Supabase DB + `RUNPOD_VIDEO_ENDPOINT_ID` +
`COMFYUI_VIDEO_LIGHTNING_WORKFLOW_PATH` all required).

> `GET /v1/video-batches/action-catalog` is the one exception: it does **not** touch the
> DB, so it answers even on a backend where the batch services are otherwise 503. You can
> render the picker before confirming the rest of the feature is live.

---

## 3. Request / response shapes

### 3.1 `VideoBatchCreate` → `POST /v1/characters/{id}/video-batches`

```jsonc
{
  "quality_mode": "fast",          // "fast" (lightning, ~1.5-3 min/clip) | "max" (baseline, slower/max fidelity). Default "fast".
  "defaults": {                    // VideoBatchDefaults — batch-wide; each item may override a subset
    "width": null,                 // null = server default (480). If set, (width,height) MUST be an allowlisted PAIR (§3.3)
    "height": null,                // null = server default (832)
    "length": null,                // frame count: 49 | 81. null = server default (81)
    "fps": null,                   // 8-30. null = server default (16)
    "seed_strategy": "per_item",   // "fixed" | "per_item" | "random". Default "per_item"
    "base_seed": null,             // 1..1e9; auto-filled server-side for fixed/per_item if omitted (echoed back in defaults)
    "interpolate": false,          // RIFE frame interpolation (2x frames, smoother playback)
    "negative_prompt": null        // <=2000 chars, folded into every item
  },
  "items": [                       // 1..50 items, one clip each
    {
      "source_image_id": "9c1e-...", // REQUIRED — a character_images still that belongs to THIS character
      "preset_id": "hair_in_wind",   // action-catalog preset id — provide EITHER this...
      "custom_prompt": null,         // ...OR a hand-written motion (XOR; exactly one required). <=2000 chars
      "seed": null,                  // per-item override (1..1e9)
      "length": null,                // per-item override (49|81)
      "fps": null,                   // per-item override (8-30)
      "quality_mode": null           // per-item override "fast"|"max"
    }
  ],
  "dry_run": false                 // true = plan + resolve + persist items, return estimate, but DON'T enqueue GPU jobs
}
```

- **`source_image_id`** must reference a still (`image_type != "video"`) belonging to the
  same character, else the whole request is rejected (`404`/`422`).
- **`preset_id` XOR `custom_prompt`** — exactly one per item. A `custom_prompt` is
  interpreted by the LLM (Venice MotionWriter) **at launch** into a WAN-friendly motion
  description + a short button label, and persisted; it falls back to the raw text when
  the LLM is off/down. It never hard-fails a launch.

**Response `VideoBatchLaunchResponse` (202):**

```jsonc
{
  "batch": { /* VideoBatchRead */ },
  "estimate": {
    "items_total": 6,
    "est_seconds_min": 450,
    "est_seconds_max": 810,
    "est_cost_usd": null            // populated only if backend sets a GPU $/s rate
  }
}
```

Show the estimate immediately so the admin knows the time before results exist. The
estimate assumes one GPU job per item bounded by the backend in-flight window.

### 3.2 `VideoBatchRead` / `VideoBatchDetailRead` → `GET /v1/video-batches/{id}`

```jsonc
{
  "id": "uuid",
  "character_id": "uuid",
  "quality_mode": "fast",
  "defaults": { /* echoed VideoBatchDefaults, with the resolved base_seed folded in */ },
  "status": "running",             // see §1
  "progress": 0.5,                 // 0.0-1.0 (done / total)
  "items_total": 6,
  "items_succeeded": 3,
  "items_failed": 0,
  "error": null,
  "created_at": "…", "updated_at": "…",
  "items": [ /* VideoBatchItemRead[] — ONLY on the detail endpoint */ ]
}
```

**`VideoBatchItemRead`** (one still → one action → one child clip):

```jsonc
{
  "id": "uuid",
  "item_index": 0,                 // ordering within the batch
  "status": "succeeded",           // pending|queued|running|succeeded|failed|cancelled
  "source_image_id": "9c1e-...",   // the still it was animated from
  "source_image_url": "https://…/still.png",  // snapshot for side-by-side review
  "action_kind": "preset",         // "preset" | "custom"
  "preset_id": "hair_in_wind",     // set for preset items
  "custom_prompt": null,           // set for custom items (the raw text the admin typed)
  "tier": "charm_idle",            // catalog tier snapshot; null for custom items
  "motion_text": "hair flowing…",  // resolved WAN motion text (preset snapshot or LLM output)
  "motion_label": "Hair In Wind",  // the chat quick-action button caption
  "quality_mode": "fast",
  "width": 480, "height": 832, "length": 81, "fps": 16,
  "seed": 331198,
  "attempts": 1,                   // GPU attempts consumed (only genuine RunPod failures, not deploys)
  "runpod_status": "COMPLETED",    // live RunPod status: IN_QUEUE|IN_PROGRESS|COMPLETED|FAILED|…
  "error_code": null, "error_message": null,
  "video_url": "https://…/clip.mp4",  // the finished clip (stable public URL)
  "preview_url": "https://…/clip.mp4",
  "character_image_id": "uuid",    // the character_images video row (set once succeeded; publish guard)
  "action_id": "uuid"              // the chat_persona_actions DRAFT row (set once succeeded; publish guard)
}
```

**For display use `video_url`.** `runpod_status` + `attempts` are your liveness signals
(§6). `character_image_id` / `action_id` are set only on succeeded items — use `action_id`
to publish that item.

### 3.3 `width` / `height` — optional resolution opt-in

Both default to `null` → the server default **480×832**. To render sharper, send an
allowlisted **pair** (both or neither): `480×832`, `576×1024`, or `720×1280` (WAN 2.2 14B
native tier — sharpest, most VRAM/slowest). Any other pair, or only one set → `422`.

### 3.4 `VideoActionCatalogRead` → `GET /v1/video-batches/action-catalog`

```jsonc
{
  "tiers": [
    {
      "tier": "charm_idle",
      "label": "Charm & Idle",
      "presets": [
        { "id": "subtle_idle", "label": "Subtle Idle", "tier": "charm_idle" },
        { "id": "gaze_and_smile", "label": "Gaze And Smile", "tier": "charm_idle" }
        // …
      ]
    },
    { "tier": "playful",  "label": "Playful",  "presets": [ /* … */ ] },
    { "tier": "glamour",  "label": "Glamour",  "presets": [ /* … */ ] },
    { "tier": "tease",    "label": "Tease",    "presets": [ /* … */ ] },
    { "tier": "explicit", "label": "Explicit", "presets": [ /* … */ ] }
  ]
}
```

Groups arrive in **ascending intensity order** (`charm_idle` → `playful` → `glamour` →
`tease` → `explicit`) — render them in the order returned. The five tier values are stable;
prefer the server-provided `label` for headings.

### 3.5 `VideoBatchItemRerun` → `POST /v1/video-batches/{id}/items/{item_id}/rerun`

```jsonc
{
  "new_seed": null,      // explicit seed for the rerun (1..1e9); ignored when reseed=true
  "reseed": false,       // derive a fresh random seed (overrides new_seed)
  "preset_id": null,     // OPTIONAL: change the action to this preset on rerun (XOR custom_prompt)
  "custom_prompt": null  // OPTIONAL: change the action to this hand-written motion (XOR preset_id)
}
```

Body is optional (send `{}` to rerun as-is). Returns the reset `VideoBatchItemRead`. Only
a `succeeded` or `failed` item can be rerun (`409` otherwise). A rerun **supersedes** the
item's previously published clip — the old gallery row is deleted and the item is reset
(clip + publish guards cleared, attempts reset) so the reconciler regenerates it. Leaving
both `preset_id`/`custom_prompt` null keeps the item's current action.

---

## 4. Action catalog UI

The catalog is a tiered set of ~36 selectable actions (24 carried over from the
single-clip motion presets, plus glamour/tease/explicit additions). Build the per-item
action picker from `GET /v1/video-batches/action-catalog`:

1. **Group by tier, in the returned order** (ascending intensity). Use each group's
   `label` as the section heading.
2. **The `explicit` tier is gated.** Hide it behind an **admin toggle / disclosure** that
   is OFF by default. Even with the toggle on, the backend independently gates explicit
   items: a launch containing an explicit preset is rejected (`422`) unless the operator
   has enabled `VIDEO_BATCH_EXPLICIT_ENABLED` **and** the lightning workflow is configured.
   Surface that `422` message rather than pretending it succeeded.
3. **Custom motion (free text).** Offer an "Describe your own motion" field per item as an
   advanced option. It is interpreted server-side at launch; there is no client-side
   motion grammar. To preview the interpreted result before spending GPU, use **dry-run**
   (§5) — each item's `motion_text` + `motion_label` come back populated on the `planned`
   batch.
4. A sensible default preset for a fresh item is `subtle_idle` (lowest motion, safest for
   identity).

---

## 5. Build-a-batch flow

The recommended launch flow mirrors Story Batches' preview→confirm:

1. **Pick a character** → open its gallery.
2. **Multi-select stills** to animate. **Exclude any row that is itself a video** from
   being pickable as a source (only `image_type != "video"` stills are valid).
3. **Per-item action** — for each selected still, choose a catalog preset (grouped picker,
   §4) or type a custom motion. Optionally override per-item seed / length / fps /
   quality_mode.
4. **Batch defaults** — `quality_mode` (**fast** default = lightning; **max** = baseline
   slower/sharper), `interpolate` (smoother 2× playback), resolution (§3.3),
   seed_strategy + base_seed, a shared negative prompt.
5. **Dry-run preview** — `POST …/video-batches` with `"dry_run": true`. Returns a
   `planned` batch; `GET /v1/video-batches/{id}` shows every item with its resolved
   `motion_text` (the interpreted custom motion, or the preset snapshot), `motion_label`,
   `tier`, and per-item render params — plus the `estimate`. Render this as a review sheet.
6. **Launch** — if approved, `POST /v1/video-batches/{id}/launch` on the **same** batch
   promotes the exact previewed plan to `running` (no re-resolution). `launch` returns
   **409** if the batch isn't `planned` (e.g. already running). Alternatively submit a
   fresh batch with `dry_run: false` to plan-and-run in one call.
7. **Poll** `GET /v1/video-batches/{id}` (§1) and render the items grid live.

---

## 6. Honest liveness (fold in the batch-reliability lessons)

Video is slow and the operator must not misread a healthy batch as frozen. These lessons
carry over from the 2026-07-14 batch-reliability work order
(`docs/ADMIN_BATCH_UI_RELIABILITY_WORKORDER.md`):

- **RunPod GPU cold starts queue jobs for ~4–5 minutes.** During that window items sit in
  `queued`/`running` with no visible progress but are perfectly healthy. Show a per-item
  elapsed timer (derive from `updated_at`, label it "in state for N min") and a muted
  "GPU cold start can take ~5 min" hint under ~6 min; escalate styling (amber) past
  ~10 min. **Do not** auto-suggest cancelling a slow-but-healthy item.
- **Surface `runpod_status` + `attempts`.** `runpod_status` (`IN_QUEUE`/`IN_PROGRESS`/…)
  is the live truth for an in-flight item; `attempts` shows genuine GPU retries. Add
  `queued`/`running` to any status filter chips so the operator can isolate in-flight work.
- **Cancel is destructive — confirm it.** `DELETE /v1/video-batches/{id}` aborts in-flight
  RunPod jobs directly (via each item's durable handle) and marks the batch + open items
  `cancelled`. The GPU work already running is **discarded and still billed**. The confirm
  dialog must say how many items are in-flight and warn that their (paid) work is thrown
  away. Do not add a "cancel everything" reflex to a batch that merely looks slow.
- **A `failed` item is not the end.** Use `POST …/retry` (batch-level, re-enqueues all
  `failed` items) or per-item **rerun** (§3.5). `attempts` is bounded by a backend cap;
  once exhausted the item stays `failed` with an `error_message`.

---

## 7. Publish flow

Nothing is visible in chat until explicitly published — a succeeded item lands as a
**draft** quick action (`chat_persona_actions.is_active = false`).

- **Review before publishing.** WAN is generative motion from a start frame and can drift
  the character's face on longer/higher-motion clips. An admin should **watch the clip**
  (not skim a thumbnail) before publishing — this draft/publish split is the safety net.
- **Per-item publish:** `POST /v1/characters/{id}/videos/{action_id}/publish` (the
  existing single-reel route) using the item's `action_id`. Flips that one draft active.
- **Bulk publish:** `POST /v1/video-batches/{id}/publish` flips **every** succeeded item's
  draft action active and returns `{ "batchId": "…", "published": <count> }`. Because
  video can drift identity, prefer per-item publish after review; reserve bulk publish for
  a batch the admin has already watched through.
- There is no unpublish endpoint here; pulling a published clip is a manual/backend task.

---

## 8. Durability note (this subsystem no longer strands clips)

Unlike the older image Story Batches (whose in-flight job state lived only in memory, so a
deploy failed items with `LOST_JOB`), the video-batch path is **submit-only worker + durable
reconciler**: the worker persists a `runpod_request_id` on each item the moment it submits,
and a background reconciler polls RunPod and owns publish/retry/recovery. Practical
consequences for the UI:

- **A deploy/restart mid-batch no longer strands in-flight clips.** After a restart the
  reconciler re-polls each item's durable handle; a clip that finished while the API was
  down is recovered and published on the next tick.
- **Attempts are consumed only by genuine RunPod failures**, never by a deploy — so a
  redeploy won't burn an item's retry budget.
- **Expect a brief "running with no progress" window right after a restart** while the
  reconciler re-attaches to in-flight jobs. That is normal recovery, not a stuck batch —
  the elapsed-time hint (§6) should absorb it without alarming the operator.

---

## 9. Gotchas checklist

- [ ] Admin panel origin on the backend `CORS_ALLOW_ORIGINS`, or browser calls fail before
      auth.
- [ ] Admin JWT satisfies `require_admin` (role claim or allowlist) or you get `403`.
- [ ] Source stills must belong to the character and **not** be videos — exclude
      `image_type='video'` rows from the picker (the backend also enforces this with `422`).
- [ ] Exactly one of `preset_id` / `custom_prompt` per item (both or neither → `422`).
- [ ] `explicit` tier is doubly gated (admin toggle in the UI **and**
      `VIDEO_BATCH_EXPLICIT_ENABLED` on the backend). Surface the `422` if the backend flag
      is off.
- [ ] If you set resolution, send an allowlisted `(width, height)` pair (both or neither),
      else `422`.
- [ ] Launch / retry / rerun / cancel are **202/204 async** — don't expect clips in the
      response; poll.
- [ ] Prefer `video_url` for display; treat video preview URLs as stable public URLs.
- [ ] Cancel discards in-flight, billed GPU work — confirm with an in-flight count warning.
- [ ] `503` on these endpoints means the backend video-batch services aren't configured
      (DB + `RUNPOD_VIDEO_ENDPOINT_ID` + `COMFYUI_VIDEO_LIGHTNING_WORKFLOW_PATH`) — surface a
      clear "video batches unavailable" state. The action-catalog endpoint still answers.
- [ ] Run migration `loli_api/migrations/0008_character_video_batches.sql` once (the
      product `characters` / `character_images` / `chat_persona_actions` tables must
      already exist).
- [ ] Published video quick actions rely on the chat runtime reading `media_type='video'`
      rows — confirm the chat app's RLS/read path allows them (same open question as the
      single-reel feature, `docs/ADMIN_VIDEO_INTEGRATION.md` §7).

---

## 10. Definition of done

- [ ] Character gallery lets the admin **multi-select stills** as batch sources (video rows
      excluded).
- [ ] Per-item **action picker** built from `GET …/action-catalog`, grouped by tier in
      ascending order, with the **explicit tier behind an OFF-by-default admin toggle** and
      a custom free-text motion option.
- [ ] Batch defaults form: `quality_mode` (fast default), `interpolate`, resolution (§3.3),
      seed strategy + base_seed, negative prompt; `estimate` shown on submit.
- [ ] **Dry-run preview** (`dry_run:true` → storyboard the `planned` batch's resolved
      `motion_text`/`motion_label` + estimate) → **Launch this plan**
      (`POST …/{id}/launch`).
- [ ] Batch detail: `progress` bar + counts; live items grid (poll §1); per-item clip /
      spinner / error chip; **per-item elapsed timer + cold-start hint** (§6);
      `runpod_status` + `attempts` surfaced.
- [ ] **Retry failed** (`POST …/retry`, enabled when `items_failed > 0`) and per-item
      **rerun** (`POST …/items/{item_id}/rerun`) wired.
- [ ] **Cancel** (`DELETE …`) behind a confirm dialog that warns about in-flight, billed
      GPU work.
- [ ] **Publish**: per-item (`POST /v1/characters/{id}/videos/{action_id}/publish`) after
      review + optional **bulk** (`POST …/{id}/publish`); admin watches clips before
      publishing (no reflexive "publish all").
- [ ] Confirmed with backend: `/openapi.json` exposes `VideoBatchCreate`, the video-batch
      services are live (not `503`), and `VIDEO_BATCH_EXPLICIT_ENABLED` is set if the
      explicit tier is to be usable.
