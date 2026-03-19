# Loli API — API Reference

Base URL: `https://<your-tunnel>.trycloudflare.com` (or `http://localhost:8001` locally)

Interactive Swagger docs: `GET /docs`

## Authentication

All endpoints except `/health` and `/v1/preview/{token}` require a JWT Bearer token:

```
Authorization: Bearer <token>
```

Tokens are HS256-signed with `JWT_SECRET_KEY`. Default expiry: 60 minutes.

---

## Endpoints

### `GET /health`

Health check. No auth required.

**Response:**
```json
{ "status": "healthy", "queueSize": 3, "version": "1.0.0" }
```

---

### `POST /v1/generate/image`

Generate a new character image from persona attributes.

**Request body — `GenerateImageRequest`:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | No | Client-provided tracking ID |
| `persona` | PersonaOptions | **Yes** | Character attributes (see below) |
| `context` | string | No | Scene context for prompt (max 2000 chars) |
| `isEnhance` | bool | No | Use Grok-4 to enhance prompt (default: true) |
| `output.seed` | int | No | Seed for reproducibility (1-1000000000) |
| `output.n` | int | No | Number of images, 1-4 (default: 1) |

**PersonaOptions fields:**

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `style` | enum | No | `realistic`, `anime` (default: realistic) |
| `ethnicity` | enum | **Yes** | `caucasian`, `asian`, `black_afro`, `latina`, `arab` |
| `age` | int | **Yes** | 18-99 |
| `hairStyle` | enum | **Yes** | `straight`, `bangs`, `curly`, `bun`, `short`, `ponytail` |
| `hairColor` | enum | **Yes** | `brunette`, `blonde`, `black`, `redhead`, `pink` |
| `eyeColor` | enum | **Yes** | `brown`, `blue`, `green` |
| `bodyType` | enum | No | `skinny`, `athletic`, `average`, `curvy`, `bbw` |
| `breastSize` | enum | No | `small`, `medium`, `large`, `extra_large` |
| `name` | string | **Yes** | Character name (1-50 chars) |
| `personality` | enum | No | 12 types (e.g. `shy`, `dominant`, `innocent`) |
| `relationship` | enum | No | 18 types (e.g. `girlfriend`, `stranger`, `boss`) |
| `occupation` | enum | No | 42 types (e.g. `nurse`, `student`, `model`) |
| `kinks` | list[enum] | No | Max 3 from 23 types |

**Response (202):**
```json
{ "jobId": "imgjob_abc123", "status": "queued", "reviewRequired": true }
```

---

### `POST /v1/edit/outfit`

Change character clothing/outfit.

**Request body — `OutfitEditRequest`:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_image` | string (URL) | **Yes** | Source image URL |
| `outfit` | enum | **Yes** | One of 44 outfit types (see enums.py) |
| `nudityLevel` | enum | No | `low`, `medium`, `high` (default: low) |
| `accessories` | list[enum] | No | Max 5: `necklace`, `earrings`, `glasses`, `hat`, `sunglasses` |
| `seed` | int | No | Seed for reproducibility |

**Response (202):** Same jobId format as generate.

---

### `POST /v1/edit/pose`

Change character pose using reference pose images.

**Request body — `PoseEditRequest`:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_image` | string (URL) | **Yes** | Source image URL |
| `pose` | enum | **Yes** | One of 16 pose types |
| `seed` | int | No | Seed for reproducibility |

**Pose types:** `standing_leaning`, `sitting`, `sitting_legs_wide_open`, `sofa`, `lying_back`, `lying_stomach`, `kneeling`, `bending_over`, `hands_behind_head`, `squatting`, `all_fours`, `spread_legs`, `eating`, `jogging`, `opening_fridge`, `cooking`

**Response (202):** Same jobId format.

---

### `POST /v1/edit/background`

Change scene/environment around a character.

**Request body — `BackgroundEditRequest`:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_image` | string (URL) | **Yes** | Source image URL |
| `prompt` | string | **Yes** | Scene description (max 2000 chars) |
| `negativePrompt` | string | No | What to avoid (max 2000 chars) |
| `seed` | int | No | Seed for reproducibility |

**Response (202):** Same jobId format.

---

### `POST /v1/pipeline`

Chain multiple edit steps in one request. Default order: pose -> outfit -> background. Each step's output feeds into the next.

**Request body — `PipelineEditRequest`:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_image` | string (URL) | **Yes** | Source image URL |
| `pose` | enum | No | Pose type (enables pose step) |
| `outfit` | enum | No | Outfit type (enables outfit step) |
| `nudityLevel` | enum | No | For outfit step (default: low) |
| `accessories` | list[enum] | No | For outfit step (max 5) |
| `prompt` | string | No | Background prompt (enables background step) |
| `negativePrompt` | string | No | For background step |
| `seed` | int | No | Shared seed across all steps |
| `pipeline_order` | list[string] | No | Override step order, e.g. `["outfit", "pose"]` |

At least one of `pose`, `outfit`, or `prompt` must be provided.

**Response (202):** Same jobId format.

---

### `GET /v1/jobs/{jobId}`

Poll job status.

**Response:**
```json
{
  "jobId": "imgjob_abc123",
  "type": "text_to_image",
  "status": "succeeded",
  "progress": 1.0,
  "results": [
    { "type": "image", "previewUrl": "https://...", "sha256": "abc..." }
  ],
  "promptUsed": "A beautiful portrait of...",
  "seedUsed": 12345,
  "createdAt": "2026-01-09T14:00:00Z",
  "updatedAt": "2026-01-09T14:02:00Z",
  "expiresAt": "2026-01-09T16:00:00Z"
}
```

**Status values:** `queued`, `running`, `succeeded`, `failed`

When `status` is `failed`, an `error` object is included with `code` and `message`.

---

### `DELETE /v1/jobs/{jobId}`

Cancel a queued job. Jobs already running cannot be cancelled.

---

### `GET /v1/preview/{token}`

Access a generated image via signed URL. No auth required. Token encodes path and expiry.

Query param: `path` — the image path within storage.

---

## Async Workflow

1. Submit request -> receive `jobId` (HTTP 202)
2. Poll `GET /v1/jobs/{jobId}` until `status` is `succeeded` or `failed`
3. Access image via `previewUrl` from the response

## Error Codes

| Code | Meaning |
|------|---------|
| `VALIDATION_ERROR` | Invalid request parameters |
| `PROVIDER_ERROR` | ComfyUI execution failed |
| `GPU_OOM_ERROR` | CUDA out-of-memory (retried automatically) |
| `DOWNLOAD_ERROR` | Failed to download source image |
| `NO_OUTPUT_ERROR` | ComfyUI produced no output image |
| `QUEUE_FULL` | Job queue at max capacity (100) |
