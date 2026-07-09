# Character Batches — Admin Panel Integration Guide

Handoff spec for wiring the **admin area** to the Character Batches API in `loli-api`.
Everything here is self-contained; you do not need the backend source.

**What the feature does:** an admin defines one **Character** (a persona + a single
"hero" photo they love) and requests a **Batch** of 20–50 images. The backend plans a
coherent "story flow" of scenes (varied pose / outfit / nudity / background) from the
character's traits and generates each image by **editing the hero photo** (so the face
stays consistent). Generation is async; the UI polls for progress.

**Where the data lands (this is the point):** batches write to the REAL product
schema the chat app reads —

- the character is a real `characters` row (created as `status='draft'`; persona in
  the flat typed columns, `bio` → `context`, hero photo → `profile_image_url` /
  `avatar_image_url` / `chat_avatar_url`);
- every generated photo becomes a `character_images` row (`image_type='gallery'`);
- each photo also gets a `chat_persona_actions` quick action (`media_type='image'`,
  `trigger_type='manual'`, `sort_order=scene_index`) pointing at that image row.

So after a batch completes, the admin only reviews the photos and flips the
character's `status` to published (in the existing admin UI) — chat is then fully
wired: profile image + quick-action photo reveals.

---

## 0. Authoritative schema

The live OpenAPI schema is the source of truth for every field and enum value:

- **Swagger UI:** `GET {API_BASE}/docs`
- **Raw schema:** `GET {API_BASE}/openapi.json`

Fetch `/openapi.json` at build time (or once) to generate types / dropdown option
lists rather than hard-coding them. The values below are provided for convenience but
OpenAPI is canonical.

---

## 0.5 Base URL & CORS (do this first)

- **Base URL (`{API_BASE}`):** get it from backend ops (the tunnel/deploy URL). All
  paths below are relative to it, under `/v1`.
- **CORS:** the API only accepts cross-origin browser requests from origins on its
  `CORS_ALLOW_ORIGINS` allowlist. **Your admin panel's origin must be added to that
  env var on the backend**, or every request fails at the browser with a CORS error
  (before auth even runs). Coordinate this with backend ops as step one.

---

## 1. Auth (all endpoints are admin-only)

Send the signed-in user's **Supabase access token** as a Bearer header:

```
Authorization: Bearer <supabase_access_token>
```

A user is treated as admin if **either**:
- their JWT has `app_metadata.role == "admin"` (set this on the Supabase user), **or**
- their `sub` (user id) is in the backend's `ADMIN_USER_IDS` allowlist (env var).

Non-admins get **403**. No token / invalid token → **401**.

> The API is single-admin by design: there is no per-user data isolation. Every admin
> sees the same characters and batches.

---

## 2. The hero photo (important)

`hero_image_url` must be a URL on the backend's SSRF allowlist
(`SOURCE_IMAGE_ALLOWED_HOSTS`) — in practice a **Supabase Storage public URL**.

**UI flow:** upload the chosen photo to Supabase Storage first, take the resulting
public URL, and pass that as `hero_image_url` when creating the character. A raw file
upload to this API is not supported — it takes a URL.

> This also applies to characters created outside this API: batching one requires its
> `profile_image_url` host to be on the allowlist, otherwise items fail with
> `ENQUEUE_ERROR`.

---

## 3. Endpoints

Base path: `/v1`. All return JSON. Async endpoints return **202 Accepted**.

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/v1/characters` | Create a character (real `characters` row, `status='draft'`) | 201 → `CharacterRead` |
| GET | `/v1/characters?limit=&offset=` | List characters | 200 → `CharacterRead[]` |
| GET | `/v1/characters/{id}` | Get one | 200 → `CharacterRead` |
| PATCH | `/v1/characters/{id}` | Update (partial) | 200 → `CharacterRead` |
| DELETE | `/v1/characters/{id}` | Delete (removes its quick actions + gallery images + batches) | 204 |
| POST | `/v1/characters/{id}/batches` | Plan + launch a batch | 202 → `BatchLaunchResponse` |
| GET | `/v1/characters/{id}/batches` | List batches for a character | 200 → `BatchRead[]` |
| GET | `/v1/batches/{id}` | Batch status + all items | 200 → `BatchDetailRead` |
| GET | `/v1/batches/{id}/results?ready_only=true` | Finished items only | 200 → `BatchItemRead[]` |
| POST | `/v1/batches/{id}/launch` | Run a dry-run (`planned`) batch as-is | 202 → `BatchRead` |
| POST | `/v1/batches/{id}/retry` | Re-run failed items | 202 → `BatchRead` |
| DELETE | `/v1/batches/{id}` | Cancel the batch | 204 |

**Error codes:** 401 (auth), 403 (not admin), 404 (not found), 409 (retry when nothing
failed / launch when not `planned`), 422 (validation — bad enum / URL not allowlisted),
503 (batch services not configured — backend Supabase DB missing).

**Pagination:** `GET /v1/characters` takes `limit` (default 50, 1–200) and `offset`
(default 0). It returns a plain `CharacterRead[]` with no total-count header — page by
requesting until you get fewer than `limit` rows. `GET /v1/characters/{id}/batches`
returns all of a character's batches (no pagination).

---

## 4. Request / response shapes

### 4.1 `PersonaOptions` (the character's identity + traits)

```jsonc
{
  "style": "realistic",          // realistic | anime  (default realistic)
  "ethnicity": "caucasian",      // REQUIRED
  "age": 28,                     // REQUIRED, 18–99
  "hairStyle": "straight",       // REQUIRED
  "hairColor": "blonde",         // REQUIRED
  "eyeColor": "green",           // REQUIRED
  "bodyType": "curvy",           // default average
  "breastSize": "medium",        // default medium
  "name": "Estella",             // REQUIRED, 1–50 chars
  "personality": "temptress",    // optional
  "relationship": "girlfriend",  // optional
  "occupation": "nurse",         // optional — drives the story arcs
  "kinks": ["playful_teasing", "slow_sensual"], // optional, max 3
  "voice": null                  // optional
}
```

The persona is stored in the `characters` table's flat columns (`ethnicity`,
`hair_style`, `kinks[]`, …) — it round-trips through the API unchanged.

### 4.2 `CharacterCreate` → `POST /v1/characters`

```jsonc
{
  "persona": { /* PersonaOptions */ },
  "hero_image_url": "https://<proj>.supabase.co/storage/v1/object/public/images/estella.png",
  "bio": "Night-shift nurse, introverted, loves slow mornings.",  // optional, ≤4000 → stored as characters.context
  "name": null   // optional; defaults to persona.name
}
```

`CharacterRead` (also returned by GET/PATCH) adds: `id`, `status` (`draft` until
published), `created_at`, `updated_at`.

`CharacterUpdate` (PATCH) — every field optional; send only what changes.

> `likes` / `dislikes` moved off the character: they are **batch-level** fields now
> (see 4.3) because they only tune scene planning.

### 4.3 `BatchCreate` → `POST /v1/characters/{id}/batches`

```jsonc
{
  "count": 24,                 // REQUIRED, 1–50
  "dry_run": false,            // true = plan only, NO image generation (see §6)
  "likes": ["coffee", "silk", "rainy days"],   // bias scenes toward these
  "dislikes": ["gyms", "neon clubs"],          // soft-excluded from scenes
  "controls": {
    "max_nudity": "medium",    // low | suggestive | medium | revealing | high — hard ceiling, never exceeded
    "sfw_only": false,         // true forces nudity=low and drops the "naked" outfit
    "content_rating": "nsfw",  // nsfw | sfw
    "escalation": "building",  // building (nudity rises across the set) | flat
    "photo_style": "polished", // polished (default) | studio | candid_phone (legacy raw look)
    "period_days": 1,          // NEW 2026-07-09 — 1–7; days the story spans (default 1, see addendum)
    "arc_count": 4,            // optional 1–8; capped by available story arcs
    "seed_strategy": "per_item", // per_item | fixed | random
    "base_seed": 42,           // optional; enables reproducible plans/images
    "allowed_outfits": null,   // optional allowlist of outfit enums
    "blocked_outfits": ["naked"], // default blocks "naked"
    "blocked_poses": [],
    "allowed_locations": null,
    "blocked_locations": [],
    "pipeline_order": null
  }
}
```

`controls` is optional — omit it for sensible defaults (max_nudity=medium, blocks
"naked", building escalation, per_item seeds, polished finish, period_days=1).

**`photo_style`** applies the photographic finish to every generated photo:
`polished` = retouched editorial glamour (matches the hero-card generation look),
`studio` = clean softbox studio, `candid_phone` = the legacy raw phone-cam look.

**Response `BatchLaunchResponse` (202):**

```jsonc
{
  "batch": { /* BatchRead */ },
  "estimate": {
    "items_total": 24,
    "est_runpod_jobs": 58,     // total GPU jobs (each image = 1–3 steps)
    "est_seconds_min": 1160,
    "est_seconds_max": 1856,
    "est_cost_usd": null       // populated only if backend sets a GPU rate
  },
  "provider": null             // planner used; currently always null in the body (logged server-side)
}
```

Show the estimate immediately so the admin knows the time/jobs before results exist.

### 4.4 `BatchRead` / `BatchDetailRead` → `GET /v1/batches/{id}`

```jsonc
{
  "id": "uuid",
  "character_id": "uuid",
  "count": 24,
  "controls": { /* echoed */ },
  "likes": ["coffee"], "dislikes": ["gyms"],
  "status": "running",         // see status list below
  "progress": 0.42,            // 0.0–1.0
  "items_total": 24,
  "items_succeeded": 10,
  "items_failed": 0,
  "error": null,
  "created_at": "…", "updated_at": "…",
  "items": [ /* BatchItemRead[] — only on the detail endpoint */ ]
}
```

**`BatchItemRead`** (one planned scene / one image):

```jsonc
{
  "id": "uuid",
  "scene_index": 0,            // ordering within the story
  "status": "succeeded",       // pending|queued|running|succeeded|failed|cancelled
  "scene_spec": {              // the plan for this beat (great for a storyboard view)
    "arc_id": "morning_home", "arc_title": "A slow morning at home",
    "beat_index": 0, "global_index": 0,
    "beat_description": "Waking up slow, wrapped in a robe",
    "pose": "sitting", "outfit": "satin_robe", "nudityLevel": "low",
    "accessories": null,
    "location": "home_bedroom", "time_of_day": "early_morning", "lighting": "natural_soft",
    "background_text": null, "mood_kinks": ["slow_sensual"], "mood_personality": "temptress",
    "seed": 331198
  },
  "job_id": "batjob_…",
  "image_url": "https://<proj>.supabase.co/storage/v1/object/public/images/batch_edits/batjob_….png",
  "preview_url": "…",          // may be a signed/expiring URL; prefer image_url
  "image_hash": "sha256…",
  "seed": 331198,
  "arc": "morning_home", "beat": 0,
  "attempts": 1,
  "error_code": null, "error_message": null,
  "character_image_id": "uuid" // the character_images row created for this photo
}
```

**For display use `image_url`** (stable public URL). `preview_url` can expire.
`character_image_id` links the item to its `character_images` gallery row (and the
quick action pointing at it) — set only on succeeded items.

---

## 5. Status values

**Batch `status`:**
`planning` → `running` → one of `completed` (all ok) / `partial` (some failed) /
`failed` (all failed) / `cancelled`. Plus `planned` (a dry-run result, terminal).

**Item `status`:** `pending` → `queued` → `running` → `succeeded` | `failed` |
`cancelled`.

An item is only marked `succeeded` **after** its `character_images` +
`chat_persona_actions` rows exist, so `items_succeeded` doubles as "photos visible to
chat" (once the character is published).

**Polling:** after launching, `GET /v1/batches/{id}` every ~5s while
`status ∈ {planning, running}`; stop on any terminal status. Render the items grid live:
spinner for pending/queued/running, the image for succeeded, an error chip (with
`error_message`) for failed.

---

## 6. Dry-run (storyboard preview before spending GPU)

`POST …/batches` with `"dry_run": true` **plans and persists the scenes but generates
no images**. The returned batch has `status: "planned"`; `GET /v1/batches/{id}` shows
all items with their `scene_spec` populated and no `image_url`. Use this to render a
**storyboard preview** (beat descriptions, pose/outfit/location per scene) so the admin
can review the story before committing.

**To run the previewed plan as-is**, call `POST /v1/batches/{id}/launch` on the *same*
batch. It promotes the `planned` batch to `running` and generates exactly the scenes
you previewed (same items, same seeds) — no re-planning. This is the recommended
"preview → confirm" flow:

1. `POST …/batches` with `dry_run: true` → storyboard the returned `planned` batch.
2. If approved, `POST /v1/batches/{id}/launch` → it starts generating and you poll as usual.
3. `launch` returns **409** if the batch isn't in the `planned` state (e.g. already running).

(Alternatively, submitting a brand-new batch with `dry_run: false` also works; with a
fixed `base_seed` + deterministic planner it reproduces the same plan, but `launch` on
the existing batch is exact and avoids a duplicate.)

---

## 7. Enum values

**In OpenAPI (`/openapi.json` → `components.schemas`)** — pull option lists from here:
persona enums (`EthnicityType`, `HairStyleType`, `HairColorType`, `EyeColorType`,
`BodyType`, `BreastSize`, `PersonalityType`, `RelationshipType`, `OccupationType`,
`KinkType`, `StyleType`), the edit enums (`OutfitType` 47, `PoseType` 16,
`AccessoryType` 5, `NudityLevel`), and — because they're used by `BatchControls` —
**`LocationType`**, **`SeedStrategy`** and **`PhotoStyleType`**.

**NOT in OpenAPI — documented here only.** `scene_spec` is returned as a free-form
`dict`, so the two enums nested inside it never appear in the schema. You only need
these to *display* storyboard labels (the planner chooses them; the UI never inputs
them). Values are lowercase `snake_case`, so rendering them raw is fine:

- **`TimeOfDayType`**: `early_morning`, `morning`, `daytime`, `golden_hour`, `sunset`,
  `evening`, `night`
- **`LightingType`**: `natural_soft`, `bright_daylight`, `golden_warm`, `moody_dim`,
  `neon`, `candlelit`, `studio_softbox`, `backlit_rim`, `overcast`

**Plain string fields on `BatchControls`** (constrained by convention, not enum types):
`content_rating` ∈ {`nsfw`, `sfw`}, `escalation` ∈ {`building`, `flat`}.

**`LocationType`** (also inline for convenience):

- `home_bedroom`, `home_living_room`, `home_kitchen`, `home_bathroom`,
  `home_balcony`, `home_office`, `office`, `hospital_ward`, `classroom`, `photo_studio`,
  `gym`, `yoga_studio`, `restaurant_kitchen`, `library`, `salon`, `stage`, `lab`, `beach`,
  `park`, `city_street`, `forest_trail`, `rooftop`, `poolside`, `garden`, `cafe`,
  `restaurant`, `bar`, `nightclub`, `hotel_room`, `luxury_lounge`, `car_interior`

All enum values are lowercase `snake_case` strings.

---

## 8. Suggested admin UI

1. **Characters list** — cards with hero thumbnail + name + `status` chip
   (draft/published); "New character".
2. **Character form** — hero upload (→ Supabase → URL), persona fields (dropdowns from
   OpenAPI enums), bio. Create/Update/Delete.
3. **Character detail** — persona summary + "New batch" + batch history
   (`GET /v1/characters/{id}/batches`).
4. **Batch launch modal** — `count` slider (1–50), likes/dislikes tag inputs, controls
   (max_nudity, escalation, photo_style, sfw toggle, blocked outfits/poses/locations,
   seed strategy + base_seed). Show the `estimate` on submit. Recommended flow:
   **Preview** (`dry_run:true`) → render the storyboard from each item's `scene_spec` →
   **Launch this plan** (`POST /v1/batches/{id}/launch`) to generate exactly what was
   previewed. (A direct **Generate** button with `dry_run:false` is also fine.)
5. **Batch detail** — header with `progress` bar + counts; live items grid (poll §5);
   per-item: image (`image_url`) / spinner / error. Actions: **Retry failed**
   (`POST …/retry`, enabled when `items_failed > 0`) and **Cancel** (`DELETE …`).
6. **Publish** — once the photos look right, flip the character's `status` in the
   existing admin UI (this API leaves it `draft`); the quick actions are already wired.

---

## 9. Gotchas checklist

- [ ] Admin panel origin must be on the backend's `CORS_ALLOW_ORIGINS` or browser calls
      fail with a CORS error before auth even runs.
- [ ] Admin JWT must satisfy `require_admin` (role claim or allowlist) or you get 403.
- [ ] `hero_image_url` must be on the backend SSRF allowlist (Supabase public URL) or 422 —
      also true for characters created outside this API (their `profile_image_url`).
- [ ] Launch/retry/cancel are **202 async** — don't expect images in the response; poll.
- [ ] Prefer `image_url` over `preview_url` for display (preview URLs can expire).
- [ ] `arc_count` is capped by how many story arcs exist for the character's occupation,
      so you may get fewer arcs than requested (not an error).
- [ ] `503` on batch endpoints means the backend's Supabase DB isn't configured — surface
      a clear "batches unavailable" state.
- [ ] Deleting a character deletes its quick actions, gallery images, and batches.
- [ ] Batch-created characters stay `status='draft'` until published — chat won't show
      them (or their quick actions) before that.
- [ ] Run migration `loli_api/migrations/0002_character_batches.sql` once (creates the
      `character_batches` job tables; the product tables must already exist).

---

## 10. Supabase schema (reference)

Current `public` schema. **The API endpoints are your contract — OpenAPI (§0) is
canonical.** This is provided so you understand where data lands and which tables the
admin panel / chat runtime may read directly.

How this feature relates to the tables:

- **Written by this API:** `characters` (created `status='draft'`), `character_images`
  (batch photos, `image_type='gallery'`), `chat_persona_actions` (one quick action per
  photo), and its own job tables `character_batches` / `character_batch_items`.
- **Read by the chat runtime:** `characters`, `character_images`, `chat_persona_actions`,
  `chat_personas` (linked via `characters.chat_persona_id`), `conversations`,
  `chat_messages`.
- **Publishing:** this API leaves `characters.status='draft'`; the admin flips it to the
  chat-visible value and (optionally) sets `chat_persona_id`/`welcome_message` in the
  existing admin UI. Those two columns are never touched by batches.

> The export format below omits `ON DELETE` actions, `UNIQUE` constraints, and indexes.
> In reality `character_batch_items` has `UNIQUE (batch_id, scene_index)`, and the job
> tables' FKs cascade (`character_batches.character_id` → `characters` cascades;
> `character_batch_items.character_image_id` → `character_images` is `SET NULL`).

```sql
-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.chat_personas (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  system_prompt text NOT NULL,
  greeting_message text,
  tone text,
  style text,
  boundaries text,
  summary text,
  model_id text NOT NULL DEFAULT 'venice-uncensored'::text,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT chat_personas_pkey PRIMARY KEY (id)
);
CREATE TABLE public.characters (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  style text NOT NULL DEFAULT 'realistic'::text,
  ethnicity text NOT NULL,
  age integer NOT NULL,
  hair_style text NOT NULL,
  hair_color text NOT NULL,
  eye_color text NOT NULL,
  body_type text NOT NULL,
  breast_size text NOT NULL,
  personality text,
  relationship text,
  occupation text,
  kinks ARRAY NOT NULL DEFAULT '{}'::text[],
  voice text,
  context text,
  chat_persona_id uuid,
  avatar_image_url text,
  profile_image_url text,
  profile_image_2_url text,
  chat_avatar_url text,
  welcome_message text,
  status text NOT NULL DEFAULT 'draft'::text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT characters_pkey PRIMARY KEY (id),
  CONSTRAINT characters_chat_persona_id_fkey FOREIGN KEY (chat_persona_id) REFERENCES public.chat_personas(id)
);
CREATE TABLE public.character_images (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  character_id uuid NOT NULL,
  image_type text NOT NULL,
  image_url text NOT NULL,
  original_image_url text,
  provider text,
  model text,
  prompt text,
  cost numeric NOT NULL DEFAULT 0,
  latency numeric NOT NULL DEFAULT 0,
  file_size integer,
  outfit text,
  accessories ARRAY NOT NULL DEFAULT '{}'::text[],
  seed integer,
  source_image_id uuid,
  is_avatar boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT character_images_pkey PRIMARY KEY (id),
  CONSTRAINT character_images_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id),
  CONSTRAINT character_images_source_image_id_fkey FOREIGN KEY (source_image_id) REFERENCES public.character_images(id)
);
CREATE TABLE public.chat_persona_actions (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  character_id uuid NOT NULL,
  label text NOT NULL,
  suggested_prompt text,
  character_image_id uuid,
  media_url text,
  media_type text NOT NULL DEFAULT 'image'::text,
  trigger_type text NOT NULL DEFAULT 'manual'::text,
  trigger_after_messages integer,
  trigger_keywords ARRAY NOT NULL DEFAULT '{}'::text[],
  sort_order integer NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT chat_persona_actions_pkey PRIMARY KEY (id),
  CONSTRAINT chat_persona_actions_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id),
  CONSTRAINT chat_persona_actions_character_image_id_fkey FOREIGN KEY (character_image_id) REFERENCES public.character_images(id)
);
CREATE TABLE public.conversations (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  character_id uuid NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT conversations_pkey PRIMARY KEY (id),
  CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id),
  CONSTRAINT conversations_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id)
);
CREATE TABLE public.chat_messages (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL,
  role text NOT NULL,
  content text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT chat_messages_pkey PRIMARY KEY (id),
  CONSTRAINT chat_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id)
);
CREATE TABLE public.profiles (
  id uuid NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT profiles_pkey PRIMARY KEY (id),
  CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id)
);
CREATE TABLE public.admin_users (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  auth_user_id uuid NOT NULL UNIQUE,
  email text NOT NULL UNIQUE,
  role text NOT NULL DEFAULT 'editor'::text,
  display_name text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT admin_users_pkey PRIMARY KEY (id),
  CONSTRAINT admin_users_auth_user_id_fkey FOREIGN KEY (auth_user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.app_config (
  key text NOT NULL,
  value text NOT NULL,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT app_config_pkey PRIMARY KEY (key)
);
CREATE TABLE public.ai_generated_images (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  provider text,
  model text,
  prompt text,
  original_image_url text,
  supabase_image_url text,
  cost numeric,
  latency numeric,
  image_width integer,
  image_height integer,
  file_size integer,
  metadata jsonb,
  CONSTRAINT ai_generated_images_pkey PRIMARY KEY (id)
);
CREATE TABLE public.character_batches (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  character_id uuid NOT NULL,
  count integer NOT NULL CHECK (count >= 1 AND count <= 50),
  controls jsonb NOT NULL DEFAULT '{}'::jsonb,
  likes ARRAY NOT NULL DEFAULT '{}'::text[],
  dislikes ARRAY NOT NULL DEFAULT '{}'::text[],
  status text NOT NULL DEFAULT 'pending'::text,
  progress real NOT NULL DEFAULT 0,
  items_total integer NOT NULL DEFAULT 0,
  items_succeeded integer NOT NULL DEFAULT 0,
  items_failed integer NOT NULL DEFAULT 0,
  error text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT character_batches_pkey PRIMARY KEY (id),
  CONSTRAINT character_batches_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id)
);
CREATE TABLE public.character_batch_items (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL,
  scene_index integer NOT NULL,
  scene_spec jsonb NOT NULL,
  pipeline_request jsonb,
  job_id text,
  status text NOT NULL DEFAULT 'pending'::text,
  preview_url text,
  image_url text,
  image_hash text,
  seed bigint,
  arc text,
  beat integer,
  attempts integer NOT NULL DEFAULT 0,
  error_code text,
  error_message text,
  character_image_id uuid,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT character_batch_items_pkey PRIMARY KEY (id),
  CONSTRAINT character_batch_items_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.character_batches(id),
  CONSTRAINT character_batch_items_character_image_id_fkey FOREIGN KEY (character_image_id) REFERENCES public.character_images(id)
);
```

---

## Addendum (2026-07-07): photo management + time-of-day

### Photo management (admin gallery)

All admin-gated (same JWT as the other character routes):

```
POST   /v1/characters/{id}/images        body: { "imageUrl": "<preview/storage URL>",
                                                 "prompt"?: str, "seed"?: int, "outfit"?: str,
                                                 "label"?: str, "setAsAvatar"?: bool }
  -> 201 CharacterImageRead. THE SAVE BUTTON: generation/edit jobs only upload to
     storage and return a preview URL — nothing is attached to the character until
     the admin saves it with this call. "label" also creates a chat quick action;
     "setAsAvatar" additionally makes it the avatar. (Batches are the deliberate
     exception: they persist every succeeded item automatically.)

GET    /v1/characters/{id}/images
  -> [ { "id", "imageUrl", "imageType", "isAvatar", "outfit", "prompt", "createdAt" }, ... ]
     Newest first. imageType: "gallery" | "video" (avatar rows keep their type).

DELETE /v1/characters/{id}/images/{imageId}
  -> 204. Removes the character_images row AND its chat quick action
     (chat_persona_actions). Derived video rows are detached (source_image_id
     nulled), not deleted. Storage object kept. Deleting the current avatar does
     NOT clear the character's avatar URLs — set a new avatar first/after.

PUT    /v1/characters/{id}/avatar        body: { "imageId": "<character_images.id>" }
  -> CharacterRead. Points profile_image_url / avatar_image_url / chat_avatar_url
     at that photo and maintains the is_avatar flag on character_images.
```

### Time-of-day / lighting for hero generation

`POST /v1/generate/image` — `shot` gains two optional fields:

```jsonc
"shot": {
  "framing": "waist_up",          // unchanged defaults
  "angle": "eye_level",
  "photoStyle": "polished",
  "timeOfDay": "night",           // early_morning|morning|daytime|golden_hour|sunset|evening|night
  "lighting": "neon"              // optional flavor: natural_soft|bright_daylight|golden_warm|
                                  //   moody_dim|neon|candlelit|studio_softbox|backlit_rim|overcast
}
```

`timeOfDay` is ENFORCED, not advisory: the phrase becomes a verified prompt token
(survives prompt polish) and the polished photo-style wrapper swaps its lighting
sentence to a matching grade — so "night" produces a polished low-key night look
instead of the daylight grade fighting the request. Omit it for the default
bright editorial look. Free-text "at night" in `prompt` is no longer the way to
ask for night — use `shot.timeOfDay`.

Consistency note for card sets: hero cards look most uniform when generated with
the same `shot` values (defaults) and at most ~2 kinks per persona (the prompt
layer now caps kink mood phrases at 2). Outfit texts that emphasize skirts/legs
will pull the crop wider than waist_up — pick `framing: "three_quarter"` for
those instead of fighting it.

---

## Addendum (2026-07-09): nudity arc, structured description channels, outfit strength

### `start_nudity` + the nudity arc

`controls.start_nudity` (optional `NudityLevel`) sets photo 1's nudity target; the
server ramps it up to `max_nudity` (the finish level) across the batch. Derivation
when `start_nudity` is omitted (`null`):

- `escalation: "building"` → starts **low**, rises to `max_nudity` (a real rising
  ceiling, not just a flat cap).
- `escalation: "flat"` → constant at `max_nudity` for every photo (today's
  ceiling-only behavior — unchanged back-compat default).
- An **explicit `start_nudity` always wins** over either derivation.

```jsonc
"controls": {
  "max_nudity": "high",
  "start_nudity": "low",     // NEW — photo 1 starts low, ramps toward "high" by the end
  "escalation": "building"
}
```

**Semantics — a guided ceiling, not a strict override.** The server computes a
per-photo nudity *target* (a monotonically non-decreasing ceiling walking from
`start_nudity` to `max_nudity` across the batch) and enforces it server-side: a
planned photo can never exceed its target, but it MAY stay lower when the scene
calls for it (e.g. a hospital-shift scene mid-batch stays modest) — so the sequence
never de-escalates once it has risen, without being forced onto a rigid per-photo
schedule either. In a dry-run storyboard (`dry_run: true`), each item's
`scene_spec.nudityLevel` already reflects this enforcement — read it directly, there
is no separate "target" field to inspect.

### Structured description channels: `outfit_detail` + `expression`

Each item's `scene_spec` can now carry two additional identity-free fields, alongside
the existing `beat_description` / `setting` / `activity`:

```jsonc
"scene_spec": {
  ...
  "outfit_detail": "champagne silk pajama set, camisole and shorts",  // NEW, nullable
  "expression": "sleepy soft smile",                                  // NEW, nullable
  ...
}
```

- `outfit_detail` (≤160 chars) — a concrete garment description (colors/fabric/fit)
  that sharpens the chosen `outfit` enum's generic tier prose for that photo's
  render. Clothing only.
- `expression` (≤80 chars) — that photo's facial expression/mood only (never facial
  features like eyes/lips/face shape). Only has a visible effect on photos that also
  have a `pose` planned — non-posed photos keep the hero's face byte-locked, so
  there's nothing for a prompted expression to change there.

Both are populated only when the story director (Venice provider) authored the
batch — they are `null` on the deterministic fallback planner. Nothing new to build
in the admin UI beyond optionally surfacing them on a storyboard card.

### Outfit application strength: `outfit_denoise` + `outfit_prompt_mode`

Two new `controls` knobs tune how strongly the outfit step overrides the hero's
current clothing — useful when a dressed avatar keeps "showing through" a planned
outfit change:

```jsonc
"controls": {
  "outfit_denoise": 0.85,          // optional float 0.5-0.95; null = engine default (~0.80)
  "outfit_prompt_mode": "replace"  // "standard" (default) | "replace"
}
```

- `outfit_denoise` — raises the outfit step's regeneration strength within the
  crop-and-stitch edit region. Higher = the new garment overrides the source
  clothing more strongly (small tradeoff: a bit more regeneration drift). Only takes
  effect on the crop-and-stitch outfit tiers (see below); inert on the legacy V1
  whole-frame graph.
- `outfit_prompt_mode: "replace"` — swaps the outfit step's instruction to an
  explicit "remove the current clothing completely, then apply: {description}"
  lead-in, instead of the default "change the outfit to: {description}" phrasing.
  Reach for this when dressed-avatar → dressed-target swaps keep reconstructing the
  original garment.

Both default to today's behavior (`null` / `"standard"`) — treat them as an
"advanced" batch-launch option, not a required field.

### Likes/dislikes are batch-level and NOT persisted (reminder)

Calling this out explicitly since it trips people up: `likes` / `dislikes` on
`BatchCreate` only bias *that one batch's* planning — they are not saved onto the
character or carried into the next batch. **The admin UI must (re)send them on every
batch launch**, including a relaunch for the same character, if it wants consistent
likes/dislikes-driven scenes; there is nothing server-side to prefill from a prior
batch.

### Outfit rendering tiers (context for `outfit_denoise`/`outfit_prompt_mode`)

The outfit step resolves through a 3-tier chain, strongest first: Tier-A full 2511
(`2511full`) → Rapid crop-and-stitch (`rapid_cropstitch`) → legacy whole-frame
(`v1`, weakest — only reachable via a mis-deployed environment). This is backend
config, not an admin-panel input, but if outfit changes look weak or absent across a
batch, ask backend ops to check `GET /debug/workflow-config` (debug builds only)
before reaching for `outfit_denoise` / `outfit_prompt_mode` — a batch stuck on the
`v1` tier needs a deployment fix, not a stronger prompt.

---

## Addendum (2026-07-09): 5-level nudity scale + `period_days` (multi-day story) control

### Nudity scale expanded to 5 levels

`NudityLevel` (used by `controls.max_nudity` / `controls.start_nudity` and returned in
each item's `scene_spec.nudityLevel`) now has **5** values instead of 3. `low` /
`medium` / `high` are unchanged — same values, same meaning, fully back-compatible.
`suggestive` and `revealing` are new, slotting in as finer steps:

| value | admin label | meaning |
|---|---|---|
| `low` | Fully clothed | fully dressed |
| `suggestive` | Suggestive | clothed but teasing — tight/short, cleavage, hint of skin |
| `medium` | Partial nudity | unbuttoned/lingerie, some exposure |
| `revealing` | Mostly nude | largely exposed, covering little |
| `high` | Full nudity | full nudity |

This is the same scale documented in full in
`docs/ADMIN_GENERATION_NUDITY_INTEGRATION.md` (2026-07-09 addendum there) — the two
surfaces (single-photo generation and story batches) now share one 5-stop scale.
Everywhere `max_nudity` / `start_nudity` are set (§4.3) or `scene_spec.nudityLevel` is
displayed (§4.4), all 5 values are valid; the nudity-arc semantics from the addendum
above (guided ceiling, monotonically non-decreasing) are unchanged — just walking a
finer-grained 5-stop ladder instead of 3.

### `controls.period_days` — how many days the story spans

```jsonc
"controls": {
  "period_days": 3   // NEW — optional int, 1–7, default 1
}
```

- `period_days: 1` (default) — today's behavior, unchanged: a single curated
  wake→sleep day (early morning through night).
- `period_days: N` (2–7) — N day-cycles, each with **different** activities, so the
  batch reads like a real multi-day life (a workday, a day off, errands, a night out)
  instead of one day's beats stretched thin.
- `time_of_day` across the batch is now curated as a **monotonic progression** for the
  whole span — it no longer bounces around within a day. For `period_days > 1`, the
  early_morning → night progression repeats once per day-cycle.

Omitting `period_days` (or sending `1`) is fully back-compatible with today's
single-day planning — this is purely additive.

---

## Addendum (2026-07-09): auto-generate the full persona on character creation

**The gap this closes:** `POST /v1/characters` never called Venice — it only wrote the
flat trait columns. Generating a persona required a SEPARATE follow-up call to
`POST /v1/characters/{id}/persona` (§3), and in practice the admin panel was only
requesting `system_prompt`, leaving `greeting_message` / `tone` / `style` /
`boundaries` / `summary` / `welcome_message` empty on every new character. This
addendum adds an opt-in flag so ONE call to `POST /v1/characters` can create the
character **and** write its full persona.

### `CharacterCreate` gains 4 new optional fields

```jsonc
{
  "persona": { /* PersonaOptions */ },
  "hero_image_url": "https://<proj>.supabase.co/storage/v1/object/public/images/estella.png",
  "bio": "Night-shift nurse, introverted, loves slow mornings.",
  "name": null,

  "generate_persona": true,        // NEW, default false — generate + persist the full
                                    // chat persona via Venice in this same call
  "persona_fields": null,          // NEW, optional — which fields to generate; null =
                                    // the sensible default below. Ignored if
                                    // generate_persona is false.
  "persona_enrichment": null,      // NEW, optional — transient likes/dislikes/interests/
                                    // hobbies/language to flavor generation (not stored)
  "persona_model_id": null         // NEW, optional — model_id recorded on the created
                                    // chat_persona row
}
```

**Default `persona_fields` (when `null`)**: every generatable field —
`system_prompt`, `greeting_message`, `tone`, `style`, `boundaries`, `summary`,
`welcome_message`, `bio` — **except**:
- `name`, since `persona.name` was just set explicitly, and
- `bio`, **only when this same request's own `bio` field is non-empty** — a bio you
  typed at creation is never silently overwritten by generation. If you want Venice
  to (re)write the bio too, include `"bio"` explicitly in `persona_fields`.

**Resilience**: a persona-generation failure (Venice error, Supabase write error)
never fails character creation — the character is already created by that point, so
creation always returns normally; the response's `chat_persona_id` simply stays
`null` if generation didn't complete. Same for the (unusual) case where persona
services aren't configured on the backend at all.

**Response is unchanged** (`CharacterRead`) — no new response fields. When
generation succeeds, `chat_persona_id` (already part of `CharacterRead`) is
populated in the same response; the generated prose itself lives in
`chat_personas` (read it the same way the "Edit Chat Persona" panel already does,
via `chat_persona_id`).

Omitting `generate_persona` (or sending `false`) is fully back-compatible with
today's two-call flow — this is purely additive.

---

## Addendum (2026-07-09): per-character nude base (additive dressing for batches)

**The bug this fixes.** Batches dress each scene by *editing the character's clothed
hero photo*. Swapping one outfit for another is a **subtractive** edit (remove the old
garment, add the new one) and it's unreliable — the hero's original clothing (e.g. an
open plaid shirt) tends to **ghost through** the supposedly-different outfit, so "the
outfit doesn't fully change." The fix: generate **one identity-locked nude base** per
character (the avatar undressed to bare skin, done once) and start each batch scene's
edit chain from *that* base instead of the clothed hero. Dressing then becomes
**additive** — clothes onto bare skin — which eliminates the ghost-garment problem, and
makes nudity trivial (a scene with no outfit step simply stays nude/base).

**How identity stays safe.** The base is produced by the **existing** outfit-edit path
(`outfit=naked` at high nudity) — the same server-side YuNet head mask + crop-and-stitch
composite-back that locks the face/head byte-for-byte on every other outfit edit. No new
identity mechanism; the face on the nude base is the hero's face, pixel-for-pixel.

### Endpoints (admin-only, character-scoped)

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/v1/characters/{id}/nude-base` | Generate the character's nude base (async) | 202 → `NudeBaseStatusResponse` |
| GET  | `/v1/characters/{id}/nude-base` | Status; **finalizes** the base once its job succeeds | 200 → `NudeBaseStatusResponse` |

`POST` takes **no body**. It returns a `jobId` — poll it exactly like any other edit
(`GET /v1/jobs/{jobId}`). The base is persisted the moment you call
`GET /v1/characters/{id}/nude-base` after that job has succeeded (the GET reconciles the
job and writes the final URL — there is no separate "confirm" call). POST is idempotent
while a generation is already in flight (it returns the in-progress one instead of
spawning a duplicate).

```jsonc
// NudeBaseStatusResponse
{
  "characterId": "uuid",
  "status": "pending",          // pending → succeeded | failed
  "jobId": "outjob_…",          // the outfit_edit job (poll it, or re-GET this endpoint)
  "imageUrl": null,             // set once status is "succeeded"
  "error": null,                // set when status is "failed"
  "createdAt": "…", "updatedAt": "…"
}
```

**Errors:** 404 (character missing on POST / no base yet on GET), 422 (character has no
hero image), 503 (Supabase DB not configured), plus the usual 401/403.

### Batches use it automatically — nothing to send

This is **character-level, not batch-level**: there is **no `controls.*` change**. Once a
character has a succeeded nude base, every subsequent batch for that character sources its
scene edits from the base automatically. A character **without** one plans and batches
**exactly as today** (the edit chain falls back to the clothed hero) — so this is purely
additive and safe to roll out per-character. Suggested admin UI: a "Generate nude base"
button on the character detail page with a pending/ready indicator; batches need no new
control.

> **Moderation / consent.** This deliberately **creates and stores an explicit nude
> asset** per character (in the loli-api-owned `character_nude_bases` table — an internal
> asset, never shown in chat and never added to the gallery). It is an **explicit,
> per-character admin action** — never auto-generated on character creation or batch
> launch. Only run it for characters where that is intended and permitted.

- [ ] Run migration `loli_api/migrations/0003_character_nude_bases.sql` once (creates the
      `character_nude_bases` job/asset table; the product `characters` table must already
      exist).
