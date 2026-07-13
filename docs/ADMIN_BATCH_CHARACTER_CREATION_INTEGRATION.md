# Batch Character Creation — Admin Panel Integration Guide

Handoff spec for wiring the **admin "batch create characters" screen** to `loli-api`.
Everything here is self-contained; you do not need the backend source.

**What the feature does:** an admin builds a **list** of character drafts — each one is
the *same* option set the single "generate character" form already uses (persona +
outfit/nudity/scene/output). They can add as many drafts as they want (no cap), then hit
**Generate all**. Each draft is dispatched to RunPod as its **own independent
text-to-image job** (throttled server-side to 3 at a time so a big batch can't starve
interactive generation). The admin watches a results grid fill in, can **redo** any
individual photo, and finally **saves** characters — one at a time or all at once.

**Key architectural fact (read this):** generation and persistence are **decoupled**,
exactly like the existing single-character flow.

- **Generating** a batch writes **nothing** to the database. It only creates async jobs
  and returns their `jobId`s. The results are time-limited preview images.
- A character becomes a real `characters` row **only when the admin saves it** (via the
  existing `POST /v1/characters`, or the new bulk-save endpoint). There is **no batch
  record, no draft rows, no server-side grouping** — the batch lives entirely in the
  admin UI as a list of `jobId`s the client tracks. Close the tab mid-generation and the
  grouping is gone (finished previews still exist until they expire, but the UI has lost
  the list). This is intentional: it keeps the `characters` table free of abandoned
  drafts.

This is a **different** feature from **Character Batches / Story Batches**
(`docs/ADMIN_STORY_BATCHES_INTEGRATION.md`). Those take **one existing character** and
generate N scene *variations* by **editing its hero photo**. This feature creates **N
different characters from scratch**. Don't confuse the two `/v1/batches/*` (story) and
`/v1/generate/batch` (this) namespaces.

---

## 0. Status of endpoints

This guide documents the target contract. Endpoints are marked:

- **NEW** — being implemented in this change set (`POST /v1/generate/batch`,
  `POST /v1/scenes/randomize`, `POST /v1/characters/bulk`). Build the UI against these
  shapes; confirm they're deployed before shipping.
- **EXISTING** — already live and reused unchanged (`GET /v1/jobs/{jobId}`,
  `POST /v1/generate/image`, `POST /v1/characters`).

---

## 0.1 Authoritative schema

The live OpenAPI schema is the source of truth for every field and enum value:

- **Swagger UI:** `GET {API_BASE}/docs`
- **Raw schema:** `GET {API_BASE}/openapi.json`

Fetch `/openapi.json` at build time to generate types / dropdown option lists rather than
hard-coding them. The enum lists in §7 are provided for convenience but OpenAPI is
canonical — the batch item body is the **same `GenerateImageRequest`** the single form
already sends, so if your single-generate form is already OpenAPI-driven you reuse it
verbatim.

---

## 0.2 Base URL & CORS (do this first)

- **Base URL (`{API_BASE}`):** get it from backend ops (the tunnel/deploy URL). All paths
  below are relative to it, under `/v1`.
- **CORS:** the API only accepts cross-origin browser requests from origins on its
  `CORS_ALLOW_ORIGINS` allowlist. **Your admin panel's origin must be on that list** or
  every request fails at the browser before auth even runs. Coordinate with backend ops.

---

## 1. Auth (all endpoints are admin-only)

Send the signed-in user's **Supabase access token** as a Bearer header:

```
Authorization: Bearer <supabase_access_token>
```

A user is treated as admin if **either** their JWT has `app_metadata.role == "admin"`
**or** their `sub` is in the backend's `ADMIN_USER_IDS` allowlist. Non-admins get **403**;
no/invalid token → **401**.

> Note: `POST /v1/generate/image` (single) currently accepts any authenticated user, but
> the three **NEW** endpoints here are **admin-only**, consistent with `/v1/characters`.

---

## 2. End-to-end flow

```
        ┌─ build drafts ──────────────────────────────────────────────┐
        │  Draft #1: persona + outfit/nudity/context/output           │
        │  Draft #2: … (Add character → new blank draft)              │
        │  Draft #N: …                        (no maximum)            │
        │  [Randomize scene] per draft → POST /v1/scenes/randomize    │
        └─────────────────────────────────────────────────────────────┘
                                   │  Generate all
                                   ▼
                   POST /v1/generate/batch { items:[…] }   ── NEW
                                   │  202 → [{index,id,jobId,status}]
                                   ▼
        ┌─ results grid: one tile per jobId ──────────────────────────┐
        │  poll GET /v1/jobs/{jobId} each  (queued→running→succeeded)  │
        │  succeeded → show results[0].previewUrl                     │
        │  [Redo] a tile → re-dispatch that one draft → new jobId     │
        └─────────────────────────────────────────────────────────────┘
                                   │  Save
                     ┌─────────────┴──────────────┐
                     ▼                            ▼
     Save one:  POST /v1/characters     Save all: POST /v1/characters/bulk  ── NEW
     (EXISTING, 201)                    ({items:[…]}, 200 w/ per-item result)
                     └─────────────┬──────────────┘
                                   ▼
                    characters rows (status='draft')
                 → admin publishes from existing character UI
```

---

## 3. Endpoints

Base path `/v1`. Async generation returns **202 Accepted**.

| Method | Path | Purpose | Success | Status |
|---|---|---|---|---|
| POST | `/v1/generate/batch` | Dispatch N character photos, one job each | 202 → `BatchGenerateResponse` | **NEW** |
| GET | `/v1/jobs/{jobId}` | Poll one job (per tile) | 200 → `JobStatusResponse` | EXISTING |
| DELETE | `/v1/jobs/{jobId}` | Cancel a still-**queued** job | 204 | EXISTING |
| POST | `/v1/scenes/randomize` | Venice writes a scene description | 200 → `SceneRandomizeResponse` | **NEW** |
| POST | `/v1/characters` | Save one character | 201 → `CharacterRead` | EXISTING |
| POST | `/v1/characters/bulk` | Save many characters at once | 200 → `BulkCharacterResponse` | **NEW** |

There is deliberately **no** "get batch" endpoint — the UI holds the list of `jobId`s and
polls each. If the page reloads and the list is lost, the admin re-generates.

---

## 4. `POST /v1/generate/batch` — dispatch the batch **(NEW)**

Request: a list of items, where **each item is a full `GenerateImageRequest`** — the exact
body the single `POST /v1/generate/image` form already builds. Set each item's optional
`id` to a **client-side ref** (e.g. your draft's local uuid) so you can correlate results
back to the right tile.

```jsonc
POST /v1/generate/batch
Authorization: Bearer <supabase-jwt>
Content-Type: application/json

{
  "items": [
    {
      "id": "draft-a1",                     // your client ref — echoed back
      "persona": {
        "style": "realistic", "ethnicity": "asian", "age": 26,
        "hairStyle": "ponytail", "hairColor": "black", "eyeColor": "brown",
        "bodyType": "average", "breastSize": "medium", "name": "Sakura",
        "personality": "shy", "occupation": "nurse"
      },
      "context": "after a long shift, relaxing at home",  // scene (see §5)
      "outfit": "nurse_uniform",             // optional
      "nudityLevel": "low",                  // optional, default low
      "accessories": ["necklace"],           // optional, max 5
      "shot": { "framing": "waist_up", "angle": "eye_level", "photoStyle": "polished" },
      "output": { "aspectRatio": "2:3", "hires": true }
    },
    {
      "id": "draft-b2",
      "persona": { "ethnicity": "latina", "age": 30, "hairStyle": "curly",
        "hairColor": "brunette", "eyeColor": "green", "bodyType": "curvy",
        "breastSize": "large", "name": "Valentina" },
      "context": "sunset rooftop bar, city lights",
      "nudityLevel": "suggestive"
    }
  ]
}
```

Response (**202**):

```jsonc
{
  "items": [
    { "index": 0, "id": "draft-a1", "jobId": "imgjob_abc123", "status": "queued" },
    { "index": 1, "id": "draft-b2", "jobId": "imgjob_def456", "status": "queued" }
  ]
}
```

- **No maximum** number of items. Concurrency is bounded server-side by a dedicated worker
  pool (3), on a queue isolated from interactive single-generate traffic — so a 40-item
  batch just drains 3-at-a-time and won't block someone using the single form.
- Each `item` is validated independently. If **any** item fails Pydantic validation (bad
  enum, age < 18, > 5 accessories, …) the whole request returns **422** and **nothing is
  enqueued** — fix the flagged item and resubmit. Validate in the UI to avoid this.
- `id` is optional and free-form (≤ 100 chars). If omitted, correlate tiles by `index` /
  `jobId` instead.
- **429** if the batch queue is at capacity — retry after a moment; none were enqueued.

Then poll each `jobId` exactly as the single flow does (next section).

---

## 5. Polling each tile — `GET /v1/jobs/{jobId}` **(EXISTING, unchanged)**

One poll loop per tile. Status progression: `queued → running → succeeded | failed`.

```jsonc
GET /v1/jobs/imgjob_abc123
Authorization: Bearer <supabase-jwt>

// succeeded:
{
  "jobId": "imgjob_abc123",
  "type": "text_to_image",
  "status": "succeeded",
  "progress": 1.0,
  "results": [
    { "type": "image",
      "previewUrl": "https://<project>.supabase.co/storage/v1/object/public/images/…png",
      "sha256": "…" }
  ],
  "expiresAt": "2026-07-09T18:00:00Z",   // preview lifetime — see §8
  "promptUsed": "…",
  "seedUsed": 12345,
  "reviewRequired": true
}

// failed:
{ "jobId":"imgjob_abc123", "status":"failed",
  "error": { "code":"PROVIDER_ERROR", "message":"Upstream provider failed" } }
```

- Show `results[0].previewUrl` in the tile on `succeeded`.
- On `failed`, surface `error.message` and offer **Redo** (§6).
- Poll interval ~2–3 s per tile; stop polling a tile once terminal. Jobs are scoped to the
  authenticated user — you only see your own.
- `DELETE /v1/jobs/{jobId}` cancels a tile **only while `queued`** (204). A `running` job
  can't be cancelled (400) — let it finish or ignore the result.

---

## 6. Redo a single tile

There is no special "redo" endpoint — redo = re-dispatch that **one** draft and swap the
tile's `jobId`. Two equivalent options:

- Call `POST /v1/generate/batch` with a single-item `items` array, or
- Call `POST /v1/generate/image` (single) with that item's body.

Either returns a fresh `jobId`; replace the old one in the tile and resume polling. To get
a **different** photo (not a re-roll of the identical seed), either omit `output.seed` or
pass a new random `output.seed`.

---

## 7. `POST /v1/scenes/randomize` — "Randomize scene" button **(NEW)**

Generates an **identity-free scene/environment sentence** with Venice (the LLM) that the
admin drops into a draft's `context` field. All inputs optional; send the draft's persona
to theme the scene to her occupation/personality.

```jsonc
POST /v1/scenes/randomize
Authorization: Bearer <supabase-jwt>
Content-Type: application/json

{
  "persona": { "occupation": "nurse", "personality": "shy", … },  // optional, themes it
  "hint": "somewhere cosy at night"                               // optional free-text seed
}
```

Response (**200**):

```jsonc
{
  "scene": "After a long hospital shift, unwinding on her apartment balcony under warm evening light",
  "provider": "venice"   // "venice" (LLM) or "deterministic" (fallback) — for display only
}
```

**How to use it:** put the returned `scene` string straight into that draft's `context`
field (the same free-text scene box as the single form). On the next **Generate**, it
flows into the prompt verbatim. The admin can edit it before generating.

**Contract & guarantees:**
- The endpoint **never fails the flow**: if the LLM is unavailable it returns a
  deterministic fallback scene with `provider:"deterministic"`. Treat a non-200 as a soft
  error (keep the existing `context`); never block generation on it.
- The scene is **identity-free by design** — it describes environment / activity / mood /
  time-of-day only. It will **not** contain hair/eye/body/ethnicity/age terms, so it can't
  fight the persona's locked identity. Don't post-process it to add appearance words.
- It's stateless — nothing is stored. Call it as many times as the admin clicks
  "randomize"; each returns a fresh scene.

---

## 8. Saving — one, or all at once

Saving is the **only** step that writes to the database. A saved character is a real
`characters` row with `status='draft'` (persona in flat typed columns; hero photo →
`profile_image_url` / `avatar_image_url` / `chat_avatar_url`; `bio` → `context`). The
admin publishes it later from the existing character UI.

**The hero photo = the tile's `previewUrl`.** In production, `results[0].previewUrl` is a
Supabase Storage URL (on the SSRF allowlist), so it is valid as `hero_image_url` verbatim
— identical to how the single-character save works today.

> ⚠️ **Preview lifetime.** `previewUrl` carries an `expiresAt`. With no batch-size cap an
> admin may review for a while, so **save before `expiresAt`**. If a preview has expired,
> **Redo** that tile to get a fresh URL, then save. (Same constraint as single save, just
> a wider window.)

### 8.1 Save one — `POST /v1/characters` **(EXISTING)**

```jsonc
POST /v1/characters                       // 201 → CharacterRead
{
  "persona": { …the draft's PersonaOptions… },   // reuse the exact persona you generated with
  "hero_image_url": "https://<project>.supabase.co/…/sakura.png",   // = tile previewUrl
  "bio": "A night-shift nurse; introverted, loves slow mornings.",  // optional
  "generate_persona": true    // optional: also writes the chat persona (system_prompt, greeting…) via Venice in-call
}
```

### 8.2 Save all — `POST /v1/characters/bulk` **(NEW)**

One round-trip that persists every character the admin kept. Each item is the same
`CharacterCreate` body as §8.1. Items succeed/fail **independently** — a bad item does not
roll back the good ones.

```jsonc
POST /v1/characters/bulk
{
  "items": [
    { "persona": {…}, "hero_image_url": "https://…/sakura.png",   "generate_persona": true },
    { "persona": {…}, "hero_image_url": "https://…/valentina.png" }
  ]
}
```

Response (**200**), per-item outcome, in request order:

```jsonc
{
  "results": [
    { "index": 0, "status": "created", "character": { …CharacterRead… } },
    { "index": 1, "status": "failed",  "error": { "code": "CREATE_ERROR",
        "message": "…save-time failure detail…" } }
  ]
}
```

Show a per-row ✓ / ✗ and offer retry on the failed rows only. (Only include tiles that
**succeeded** generation and that the admin chose to keep — don't send failed/empty tiles.)

> **Two error tiers — important.** Bulk save has *two* distinct failure modes:
> - **Whole-request 422** for **malformed items** — because each item is the same
>   `CharacterCreate` shape as single save, any Pydantic-level problem (bad/missing enum,
>   `name` too long, or a `hero_image_url` whose **host isn't on the SSRF allowlist**)
>   fails the *entire* request at parse time and saves nothing. In practice this won't
>   happen for a normal flow: the personas were already valid enough to generate, and the
>   hero URLs are Supabase preview URLs from successful jobs (allowlisted hosts). Validate
>   drafts client-side and you won't hit it.
> - **Per-item `status:"failed"` (200)** for **save-time** failures (DB/store errors, a
>   persona-generation hiccup) — these are isolated per the contract: the good items still
>   save. `error.code` is `CREATE_ERROR`.

---

## 9. `PersonaOptions` & `GenerateImageRequest` (reference)

The batch item body is **exactly** `GenerateImageRequest` — no new fields. If your single
"generate character" form already builds this, reuse it. Summary of the parts:

> **New field — `culture` (subculture), and existing-characters note.** `persona.culture`
> is a new **optional** field (see enum list below). It's the *same* `PersonaOptions` used
> by `POST /v1/characters` / `POST /v1/characters/bulk`, so this applies there too, not
> just to generation. Every character created **before** this feature has `culture = NULL`
> — zero behavior change for her. `culture` set at creation only steers *this and future*
> generations for that character; changing it later on an already-saved character happens
> via `PATCH /v1/characters/{id}` (outside this batch-create flow) and only affects
> *future* batches — it never retroactively touches her existing hero photo.

`persona` (`PersonaOptions`) — required core identity:

```jsonc
{
  "style": "realistic",        // realistic | anime         (default realistic)
  "ethnicity": "caucasian",    // REQUIRED
  "age": 28,                   // REQUIRED, 18–99
  "hairStyle": "straight",     // REQUIRED
  "hairColor": "blonde",       // REQUIRED
  "eyeColor": "green",         // REQUIRED
  "bodyType": "curvy",         // default average
  "breastSize": "medium",      // default medium
  "name": "Estella",           // REQUIRED, 1–50
  "personality": "temptress",  // optional
  "relationship": "girlfriend",// optional
  "occupation": "nurse",       // optional
  "kinks": ["playful_teasing", "slow_sensual"], // optional, max 3
  "culture": "goth",           // optional, 16 values — omit for "None (no subculture)"
  "voice": null                // optional
}
```

Top-level generation fields (siblings of `persona`):

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | string \| null | null | Client ref, echoed back in batch response (≤100 chars) |
| `context` | string \| null | null | Scene hint, used verbatim. **This is where the randomized scene goes** (≤2000) |
| `outfit` | enum \| null | null | 47 outfit options; null → neutral outfit at the chosen level |
| `nudityLevel` | enum | `low` | `low` · `suggestive` · `medium` · `revealing` · `high` |
| `accessories` | enum[] \| null | null | max 5: `necklace`,`earrings`,`glasses`,`hat`,`sunglasses` |
| `shot` | object \| null | hero defaults | `framing`,`angle`,`expression`,`photoStyle`,`timeOfDay`,`lighting` |
| `output` | object \| null | defaults | `aspectRatio`,`resolution`,`seed`,`hires` |

Enum value lists (canonical source = `/openapi.json`):

- **style:** `realistic`, `anime`
- **ethnicity:** `caucasian`, `asian`, `black_afro`, `latina`, `arab`
- **culture (subculture, optional):** 16 values — `goth`, `punk`, `e_girl`, `grunge`,
  `y2k`, `cottagecore`, `dark_academia`, `old_money`, `streetwear_baddie`,
  `kawaii_harajuku`, `gyaru`, `boho_hippie`, `pinup_rockabilly`, `rocker_biker`,
  `rave_festival`, `sporty_gym`. Default `None`. Build the create-form dropdown with a
  pre-selected **"None (no subculture)"** entry that **omits** `culture` from the payload
  entirely (don't send `""` or a placeholder value) — this is the only field on the form
  designed to be skippable that way.
- **hairStyle:** `straight`, `bangs`, `curly`, `bun`, `short`, `ponytail`
- **hairColor:** `brunette`, `blonde`, `black`, `redhead`, `pink`
- **eyeColor:** `brown`, `blue`, `green`
- **bodyType:** `skinny`, `athletic`, `average`, `curvy`, `bbw`
- **breastSize:** `small`, `medium`, `large`, `extra_large`
- **personality:** `nympho`,`lover`,`submissive`,`dominant`,`temptress`,`innocent`,`caregiver`,`experimenter`,`mean`,`confidant`,`shy`,`queen`
- **relationship / occupation / kinks / outfit:** long lists — pull from OpenAPI. (occupation ≈ 44 values, kinks ≈ 23, outfit = 47.)
- **shot.framing:** `portrait_closeup`,`chest_up`,`waist_up`,`three_quarter`,`full_body`,`selfie`
- **shot.angle:** `eye_level`,`high_angle`,`low_angle`,`three_quarter_view`,`side_profile`
- **shot.photoStyle:** `natural`,`polished`,`studio`,`candid_phone`
- **output.aspectRatio / resolution:** whitelisted presets — pull from OpenAPI (bad value → 422).

---

## 10. Validation / edge cases

- **Whole-batch 422:** one invalid item fails the entire `POST /v1/generate/batch`; none
  enqueue. Validate each draft in the UI (required persona fields, age 18–99, name 1–50,
  ≤3 kinks, ≤5 accessories) before submitting.
- **No cap** on batch size, but be reasonable in the UI — 40 items at 3 concurrent × ~30–60 s
  each ≈ 7–13 min. Show an aggregate progress ("12 / 40 done").
- **Ephemeral batch:** the server has no batch record. If the page reloads, the `jobId`
  list is lost — persist it in local/session storage if you want reload-resilience, or
  just re-generate.
- **Preview expiry:** save before `expiresAt`; else Redo (§8).
- **Scene randomize** is best-effort — never block generation on it.
- **Bulk save** isolates **save-time** failures per item (partial success, `status:"failed"`),
  but a **malformed** item (bad enum / non-allowlisted `hero_image_url` host) 422s the
  whole request at parse time — see the two-tier note in §8.2. Single save is
  all-or-nothing for its one row.
- All enum values are lowercase snake_case exactly as listed. Unknown values → 422.

---

## 11. Definition of done

- [ ] "Add character" builds an unbounded list of drafts, each using the existing
      single-generate option set (persona + outfit/nudity/accessories/shot/output +
      `context`).
- [ ] Per-draft **Randomize scene** calls `POST /v1/scenes/randomize` and drops the
      returned `scene` into that draft's `context` (editable), failing soft.
- [ ] **Generate all** posts `POST /v1/generate/batch` with each draft as a
      `GenerateImageRequest` item (client `id` set for correlation).
- [ ] Results grid polls `GET /v1/jobs/{jobId}` per tile; shows preview on success, error
      + **Redo** on failure.
- [ ] **Redo** re-dispatches a single draft and swaps the tile's `jobId`.
- [ ] **Save** one (`POST /v1/characters`) and **Save all**
      (`POST /v1/characters/bulk`) using each tile's `previewUrl` as `hero_image_url`;
      per-item ✓/✗ on bulk; only kept/succeeded tiles are sent.
- [ ] Saves happen before preview `expiresAt`; expired tiles prompt a Redo.
- [ ] Options sourced from `/openapi.json` where practical rather than hard-coded.
- [ ] Admin-only auth (Bearer + admin) on all three NEW endpoints.
