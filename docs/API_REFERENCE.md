# Loli API — API Reference

Base URL: discovered by frontends from Supabase `app_config.api_base_url`
(e.g. `http://localhost:8001` locally, or a public tunnel/host in production).

Interactive Swagger docs: `GET /docs` · OpenAPI JSON: `GET /openapi.json`

All request/response field casing below is **exact** — the API mixes `snake_case`
(`source_image`, `pipeline_order`) and `camelCase` (`nudityLevel`,
`negativePrompt`). Send them verbatim.

---

## Authentication

Every endpoint except `GET /health` and `GET /v1/preview/{token}` requires:

```
Authorization: Bearer <token>
```

**loli-api accepts either of two token types** (see `auth/dependencies.py::get_current_user`):

1. **Supabase user access token — PRIMARY (this is what frontends send).**
   When `SUPABASE_JWT_SECRET` is set on loli-api, the Bearer token is verified as a
   Supabase-issued JWT: HS256 signature against `SUPABASE_JWT_SECRET`, and the `aud`
   claim must equal `SUPABASE_JWT_AUDIENCE` (default `authenticated`). The user identity
   is the token's `sub` claim (the Supabase user UUID) and is used for job ownership.

2. **Internal HS256 token — FALLBACK (local dev / service tokens).**
   Signed with `JWT_SECRET_KEY`. In `DEBUG=true`, `GET /debug/token` mints one
   (`sub=test_user`). **`/debug/token` only exists when `DEBUG=true`** — it 404s in
   production. Do not build a frontend on it.

Verification order: if `SUPABASE_JWT_SECRET` is configured, the Supabase check runs
first; on failure it falls through to the internal HS256 check; if both fail → **401**.

### What a frontend must send

The signed-in user's **Supabase session access token**:

```
Authorization: Bearer <supabaseSession.access_token>
```

In `loli-ai-admin` this is obtained server-side in `requireAdmin()` via
`supabase.auth.getSession()` and forwarded by each `/api/v1/*` proxy route. (This
replaced the old `GET /debug/token` flow, which only worked while loli-api ran with
`DEBUG=true`.)

### Troubleshooting `401 Unauthorized`

- **loli-api `SUPABASE_JWT_SECRET` must equal the Supabase project's JWT secret**
  (Supabase Dashboard → Project Settings → API → JWT Secret). If unset or mismatched,
  every real user token is rejected → 401.
- **`SUPABASE_JWT_AUDIENCE` must match the token's `aud`** — Supabase user tokens use
  `authenticated`. A mismatch → 401.
- **The frontend must actually forward a non-null access token.** If the proxy returns
  401 *before* calling loli-api, the session/`access_token` was missing (user not signed
  in, or `getSession()` returned no token).
- **The frontend must call the loli-api instance whose `SUPABASE_JWT_SECRET` matches the
  project.** The base URL comes from `app_config.api_base_url`; if it points at a
  different/stale instance, tokens won't verify.

---

## Endpoints

### `GET /health`
Health check. No auth. Also probes the configured RunPod endpoint (non-fatal, log-only).
```json
{ "status": "healthy", "queueSize": 0, "version": "1.0.0" }
```

### `POST /v1/generate/image`
Generate a new character image from persona attributes. **202** on accept.

**Body — `GenerateImageRequest`:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | No | Client tracking id |
| `persona` | PersonaOptions | **Yes** | See below |
| `context` | string | No | Free-text scene context (≤2000), used verbatim in the assembled prompt |
| `output` | OutputOptions | No | `{ seed?, n? (1–4, default 1), aspectRatio?, resolution? }` |

**PersonaOptions:**

| Field | Type | Required | Values |
|---|---|---|---|
| `style` | enum | No | `realistic`, `anime` (default realistic) |
| `ethnicity` | enum | **Yes** | `caucasian`, `asian`, `black_afro`, `latina`, `arab` |
| `age` | int | **Yes** | 18–99 (hard-gated) |
| `hairStyle` | enum | **Yes** | `straight`, `bangs`, `curly`, `bun`, `short`, `ponytail` |
| `hairColor` | enum | **Yes** | `brunette`, `blonde`, `black`, `redhead`, `pink` |
| `eyeColor` | enum | **Yes** | `brown`, `blue`, `green` |
| `bodyType` | enum | No | `skinny`, `athletic`, `average`, `curvy`, `bbw` |
| `breastSize` | enum | No | `small`, `medium`, `large`, `extra_large` |
| `name` | string | **Yes** | 1–50 chars |
| `personality` | enum | No | 12 types |
| `relationship` | enum | No | 19 types |
| `occupation` | enum | No | **43 types** — see enums note below |
| `kinks` | list[enum] | No | ≤3 of 23 types |
| `culture` | enum \| null | No | **16 types** (subculture/aesthetic) — optional, default `None`. Canonical list: `GET /v1/options → persona.culture` (`{value,label}` pairs). Steers batches/generation and the trait-profile/persona writers; never touches nudity. |
| `voice` | string | No | |

**202 response** (all create endpoints share this shape):
```json
{ "jobId": "imgjob_abc123", "status": "queued", "reviewRequired": true }
```

### `POST /v1/edit/outfit`
Change clothing. **Body — `OutfitEditRequest`:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_image` | string(URL) | **Yes** | Must pass the SSRF host allowlist (`SOURCE_IMAGE_ALLOWED_HOSTS`) in prod |
| `outfit` | enum | **Yes** | One of **47** outfit types |
| `nudityLevel` | enum | No | `low`, `medium`, `high` (default low) |
| `accessories` | list[enum] | No | ≤5: `necklace`, `earrings`, `glasses`, `hat`, `sunglasses` |
| `negativePrompt` | string | No | Extra negative terms (≤2000) — **added; honored for outfit** |
| `seed` | int | No | |

### `POST /v1/edit/pose`
Change pose. **Body — `PoseEditRequest`:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_image` | string(URL) | **Yes** | |
| `pose` | enum | **Yes** | One of **16** pose types (below) |
| `negativePrompt` | string | No | **Accepted for shape-parity but IGNORED** — the pose workflow runs at cfg=1 with a zeroed negative branch |
| `seed` | int | No | |

**Pose types:** `standing_leaning`, `sitting`, `sitting_legs_wide_open`, `sofa`,
`lying_back`, `lying_stomach`, `kneeling`, `bending_over`, `hands_behind_head`,
`squatting`, `all_fours`, `spread_legs`, `eating`, `jogging`, `opening_fridge`, `cooking`.

> **Pose availability:** pose reference images ship with the API. Until they are
> installed, `POST /v1/edit/pose` (and `/v1/edit` with a `pose` step) returns
> **422** `"Pose reference not installed for pose '<value>'..."`. Handle 422 gracefully.

### `POST /v1/edit/background`
Change scene. **Body — `BackgroundEditRequest`:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_image` | string(URL) | **Yes** | |
| `prompt` | string | **Yes** | Scene description (≤2000) |
| `negativePrompt` | string | No | ≤2000 |
| `seed` | int | No | |

### `POST /v1/edit`  ← the pipeline endpoint (NOT `/v1/pipeline`)
Chain steps in one job. Default order `pose → outfit → background`; each step's output
feeds the next. **Body — `PipelineEditRequest`:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_image` | string(URL) | **Yes** | |
| `pose` | enum | No | Enables the pose step |
| `outfit` | enum | No | Enables the outfit step |
| `nudityLevel` | enum | No | For the outfit step |
| `accessories` | list[enum] | No | For the outfit step (≤5) |
| `prompt` | string | No | Enables the background step |
| `negativePrompt` | string | No | For the background step |
| `seed` | int | No | Shared across steps |
| `pipeline_order` | list[string] | No | e.g. `["outfit","pose"]` |

At least one of `pose` / `outfit` / `prompt` must be set. A `pose` step is subject to the
same 422 rule as `/v1/edit/pose`.

### `POST /v1/edit/image`  ← synchronous (no job polling)
Raw single-image edit via multipart form (`file` + optional `prompt`, `negativePrompt`,
`seed`, `inputUrl`). Returns **200** immediately with `{ editId, results, expiresAt }` —
do NOT poll it like the async endpoints.

### `GET /v1/jobs/{jobId}`
Poll status. **Response — `JobStatusResponse`:**
```json
{
  "jobId": "imgjob_abc123",
  "type": "text_to_image",
  "status": "succeeded",
  "progress": 1.0,
  "results": [ { "type": "image", "previewUrl": "https://...", "sha256": "..." } ],
  "reviewRequired": true,
  "expiresAt": "2026-01-09T16:00:00Z",
  "error": null,
  "promptUsed": "...", "seedUsed": 12345,
  "createdAt": "...", "updatedAt": "..."
}
```
- **`status` ∈ `queued` | `running` | `succeeded` | `failed`.**
- The image URL is **`results[0].previewUrl`** (nested, camelCase) — this is the only
  populated form; there is no top-level `previewUrl`/`preview_url`.
- On `failed`, `error` = `{ "code": "...", "message": "..." }`.

### `DELETE /v1/jobs/{jobId}`
Cancel a queued or in-flight job (best-effort; terminal jobs return false). **204/200.**

### `GET /v1/preview/{token}`
Fetch a generated image via signed URL. No auth. Query param `path` = storage path.

---

## Async workflow
1. `POST` a create endpoint → `{ jobId, status: "queued", reviewRequired }` (202).
2. Poll `GET /v1/jobs/{jobId}` until `status` is `succeeded` or `failed`.
3. Render `results[0].previewUrl`; respect `expiresAt`.

## Error codes (`error.code` on failed jobs; `error`/`detail` on 4xx)
| Code | Meaning |
|---|---|
| `VALIDATION_ERROR` | Invalid request (422) |
| `PROVIDER_ERROR` | RunPod/ComfyUI worker execution failed |
| `GPU_OOM_ERROR` | GPU out-of-memory on the worker |
| `DOWNLOAD_ERROR` | Failed to download `source_image` |
| `NO_OUTPUT_ERROR` | Worker produced no image |
| `CANCELLED` | Cancelled by user |
| `QUEUE_FULL` | Per-type queue at capacity (100) |

---

## Enums note — occupation (recently corrected)
`OccupationType` has **43** values. Three were recently normalized; frontends must send
the API values, not the short forms:

| Send (API value) | NOT |
|---|---|
| `babysitter_au_pair` | ~~`babysitter`~~ |
| `movie_star_actress` | ~~`movie_star`~~ |
| `singer_musician` | ~~`singer`~~ |

Outfit (47), pose (16), nudity (`low`/`medium`/`high`), and all persona enums must match
`loli_api/models/enums.py` exactly — a mismatch is a **422**.

---

## Enums note — `culture` (new, optional)
`PersonaOptions.culture` (`CultureType`) is a new **optional, nullable** field — a
subculture/aesthetic pick, distinct from `ethnicity`. Omit or send `null` for no
subculture (default). It flows through `GenerateImageRequest`, `CharacterCreate`,
`BulkCharacterCreate`, and `PATCH /v1/characters/{id}` (sending `culture: null` clears a
previously-set value). 16 values:

`goth`, `punk`, `e_girl`, `grunge`, `y2k`, `cottagecore`, `dark_academia`, `old_money`,
`streetwear_baddie`, `kawaii_harajuku`, `gyaru`, `boho_hippie`, `pinup_rockabilly`,
`rocker_biker`, `rave_festival`, `sporty_gym`.

Human labels (for display) are available pre-built at `GET /v1/options` →
`persona.culture` as `{value, label}` pairs, in the same order as above (e.g.
`kawaii_harajuku` → "Kawaii / Harajuku"). `culture` steers batch/generation wardrobe,
locations, poses, home interior + makeup styling, and feeds the trait-profile/persona
writers — it never affects nudity settings.

---

## Frontend integration checklist (for aligning loli-ai-admin / loli-ai)
- **Auth:** send `Authorization: Bearer <supabase session access_token>` on every
  `/v1/*` call. Do **not** use `/debug/token` (dev-only, 404s in prod).
- **loli-api env:** `SUPABASE_JWT_SECRET` = the Supabase project's JWT secret;
  `SUPABASE_JWT_AUDIENCE=authenticated`. Without these matching, all user tokens → 401.
- **Base URL:** keep publishing/reading `app_config.api_base_url`; point it at the
  correct loli-api instance.
- **Pipeline path is `POST /v1/edit`** (never `/v1/pipeline`).
- **Read `results[0].previewUrl`** for the image; handle `status` `queued|running|
  succeeded|failed` and `error.{code,message}`.
- **Occupation values:** use `babysitter_au_pair` / `movie_star_actress` /
  `singer_musician`.
- **Pose 422:** treat `422 "Pose reference not installed"` as "pose temporarily
  unavailable," not a hard error.
- **`negativePrompt`** is accepted on outfit/background/pipeline (honored) and pose
  (accepted but ignored).
