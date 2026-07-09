# Admin UI Work Order — Story Batches v2 (persona-driven stories, nudity arc, structured prompts)

**Audience:** the agent/developer building the **admin panel frontend** (separate repo).
**Backend status:** shipped and on `main` (latest: `73f4d79c`). API is additive and back-compatible — the current admin panel keeps working unchanged; this work order only *adds* controls that expose new capability.

**Source of truth for the contract:** [`docs/ADMIN_STORY_BATCHES_INTEGRATION.md`](./ADMIN_STORY_BATCHES_INTEGRATION.md) — read §3 (endpoints), §4 (request/response shapes), §7 (enums), and the **dated addenda** at the bottom (currently five: 07-07 "photo management + time-of-day"; 07-09 "nudity arc, structured description channels, outfit strength"; 07-09 "5-level nudity scale + `period_days`"; 07-09 "auto-generate the full persona on character creation"; 07-09 "per-character nude base (additive dressing for batches)"). `/openapi.json` is canonical for enum option lists. This work order tells you *what UI to build*; that doc tells you *the exact field shapes*.

---

## 0. Why this work exists (context)

Story batches previously produced repetitive, generic sets: every photo looked similar, the character's job/kinks/relationship never shaped the day, outfits often didn't change, and nudity was flat. The backend now:

- **Drives the story from who she is** — her `occupation`, `relationship`, `personality`, and `kinks` (already stored on the character) now shape a realistic "day in her life" with a real work chapter.
- **Enforces variety** — no more triplicate "silk pajamas · sitting".
- **Supports a nudity arc** — a start level that builds up to a finish level across the set (the feature you asked for as "a slider with start and finish points").
- **Splits the render prompt into channels** — each photo carries `outfit_detail` + `expression` in addition to scene text.
- **Adds outfit-strength knobs** — for when a dressed avatar keeps showing through a planned outfit change.

The admin UI needs a handful of additions to surface these. **Only one is strictly required** to deliver the headline feature (the nudity arc slider); the rest are display + advanced options.

---

## 1. What changed in the API (delta only)

All additions live on `controls` (in `BatchCreate`), in each item's `scene_spec` (in `BatchDetailRead`), or on `CharacterCreate`. Nothing was removed or renamed.

| New field | Where | Type / range | Purpose |
|---|---|---|---|
| `start_nudity` | `controls` | `"low"｜"suggestive"｜"medium"｜"revealing"｜"high"｜null` | Photo 1's nudity; ramps up to `max_nudity`. **The nudity-arc START handle.** (5-stop scale — see the 2026-07-09 "5-level nudity scale" addendum.) |
| `outfit_denoise` | `controls` | `float 0.5–0.95｜null` | Outfit-change strength (advanced). |
| `outfit_prompt_mode` | `controls` | `"standard"｜"replace"` | "replace" = remove current clothing first (advanced). |
| `outfit_detail` | item `scene_spec` | `string｜null` (≤160) | Concrete garment description for that photo (display only). |
| `expression` | item `scene_spec` | `string｜null` (≤80) | That photo's facial expression/mood (display only). |
| `period_days` | `controls` | `int 1–7` (default `1`) | Number of day-cycles the story spans. **See WI-7.** |
| `generate_persona` | `CharacterCreate` | `bool` (default `false`) | Generate + persist the full chat persona via Venice in the SAME creation call. **See WI-8.** |
| `persona_fields` | `CharacterCreate` | `PersonaField[]｜null` | Optional override of which fields `generate_persona` writes; `null` = the sensible default (see WI-8). |
| `persona_enrichment` | `CharacterCreate` | object｜null | Optional transient flavor for generation (not stored). |
| `persona_model_id` | `CharacterCreate` | `string｜null` | Optional model_id recorded on the created persona row. |

`max_nudity` already existed and is now **both** the hard ceiling **and** the nudity-arc FINISH handle.

---

## 2. Work items

### WI-1 — Nudity arc control (**required**; this is the headline feature)

**Build:** in the **Batch launch modal**, replace the single `max_nudity` dropdown with a **two-handle "Nudity arc" control**: a **Start** handle and a **Finish** handle over five stops.

- Stops (5, least→most explicit): `low` = **Fully clothed** · `suggestive` = **Suggestive** · `medium` = **Partial nudity** · `revealing` = **Mostly nude** · `high` = **Full nudity**. (Use these labels — they match the generation-nudity admin doc's 2026-07-09 addendum.)
- **Start handle → `controls.start_nudity`**, **Finish handle → `controls.max_nudity`**.
- **Constraint:** Start ≤ Finish on the 5-stop scale (never allow Start above Finish).
- **Send both values explicitly** on submit. You may leave `escalation` at its default `"building"` — an explicit `start_nudity` overrides the escalation derivation anyway.
- **Copy under the control:** "The story stays at the Start level and builds up to the Finish level across the set. It can stay lower when a scene calls for it (e.g. at work), but never escalates past the per-photo target." (This is the *guided-ceiling* semantics — see the 07-09 addendum.)
- **Presets** (nice UX): "No nudity" (low→low), "Slow build" (low→high), "Spicy throughout" (medium→high), "Constant" (X→X). These are just handle positions — with 5 stops available you can also offer finer ones, e.g. "Tease" (low→suggestive) or "Bare it all" (revealing→high).
- **`sfw_only` toggle interaction:** when `sfw_only` is ON (or `content_rating: "sfw"`), force both handles to `low` and disable the control.

**Acceptance criteria:**
- Launching low→high on an 8-photo batch and opening the dry-run storyboard shows `scene_spec.nudityLevel` **non-decreasing** across all 5 stops, starting `low`, reaching `high` by the end.
- Setting Start = Finish = `medium` yields all-`medium` items.
- `sfw_only` forces every item to `low` regardless of handle positions.

> Note: even without this control the arc works via the default (`escalation:"building"` ⇒ low→max), but there'd be no way for the admin to set the **start point** — which is the whole ask. WI-1 is what exposes it.

### WI-2 — Advanced outfit-strength controls (optional; collapsible "Advanced")

> **⚠️ Correction (2026-07-09, post-launch): the default below changed, and it's a required fix, not optional.** Real production batches showed the panel was sending `outfit_prompt_mode: "standard"` explicitly on every launch (not omitting it) — that **silently overrides** the backend's new default and was a direct contributor to the "clothes don't fully change" bug. The engine default is now **`"replace"`** (see the 2026-07-09 addendum in the contract doc). Update the panel to match:

**Build:** in an **Advanced** section of the launch modal:
- `outfit_denoise` — a slider `0.5–0.95` with an **"Auto"** state that sends `null` (engine default is now **0.85** when an outfit is present, was ~0.80). Label: "Outfit change strength". Helper: "Higher forces the new outfit over the avatar's current clothing more strongly."
- `outfit_prompt_mode` — a toggle `Standard ｜ Replace`, **defaulting to Replace** (was Standard). Helper: "Replace explicitly removes current clothing first — recommended; switch to Standard only if you want the new outfit to blend with what she's already wearing."

**Acceptance criteria:** both are **omitted from the request when untouched** (don't hardcode a value — let the engine default win, so a future backend tuning change doesn't require another panel deploy to pick up); if you DO send them explicitly for some reason, send `outfit_prompt_mode: "replace"` and `outfit_denoise: null`, not `"standard"`/a stale numeric default.

### WI-3 — Storyboard card: show the new per-photo channels (recommended; display only)

**Build:** on each storyboard/item card (dry-run preview **and** results grid), in addition to the existing `outfit · pose · narrative`, surface from `scene_spec`:
- **`outfit_detail`** as the garment caption when present (fall back to the `outfit` enum label when `null`).
- **`expression`** as a small mood tag when present.
- **`nudityLevel`** as a small badge (Fully clothed / Suggestive / Partial nudity / Mostly nude / Full nudity) — this makes the arc *visible* as you scan the set.

**Notes:** both new fields are `null` on the deterministic-fallback planner (only the Venice story director authors them) — render nothing when `null`, never show "null". Occasionally (~1 in 8) the LLM's `outfit_detail` may not perfectly match the `outfit` enum; the enum label is the reliable one, so prefer it if you only show one.

**Acceptance criteria:** a dry-run storyboard renders `outfit_detail`/`expression`/`nudityLevel` when present and degrades cleanly to the enum labels when absent.

### WI-4 — Character form: make the story-shaping traits first-class (recommended; mostly UX)

The fields already exist in `PersonaOptions` (§4.1 of the contract doc) — no new API. But they now **materially drive the story**, so the UX should encourage setting them:
- Surface **`occupation`**, **`relationship`**, **`personality`**, **`kinks`** (max 3) prominently on the character form (dropdowns/multiselect from OpenAPI enums), with a hint: "These shape her story — e.g. a nurse's day includes a hospital shift."
- No appearance/identity text goes anywhere near batch inputs — the backend keeps identity pixel-locked and scrubs any appearance words. The admin never types scene/outfit/pose free-text for a batch; the planner chooses those.

**Acceptance criteria:** a character created with `occupation: "nurse"` + `kinks` produces a dry-run batch whose storyboard includes a `hospital_ward` work chapter and reflects the kinks in `mood_kinks`.

### WI-5 — Likes/dislikes are per-batch and NOT persisted (reminder; small UX)

`likes`/`dislikes` are on `BatchCreate`, not the character. They only bias *that one batch*. The UI **must re-send them on every launch** (including a relaunch for the same character). Nice-to-have: remember the last-used likes/dislikes per character in local storage and prefill — but always send them in the request.

### WI-6 — Tier/health awareness (optional; ops-facing)

If outfit changes look weak/absent across a whole batch, that's usually a backend deployment issue (the outfit step running on the weak `v1` tier), **not** something `outfit_denoise` fixes. Backend ops can check `GET /debug/workflow-config` (debug builds only). If you want, surface a subtle "outfit rendering degraded" admin banner when support flags it — but this is not a required input.

### WI-7 — Period / days control (recommended; small UX addition)

**Build:** in the **Batch launch modal**, add a small stepper or segmented control labeled e.g. "Story length" for `controls.period_days`, ranging **1–7** (default **1**), sending `controls.period_days` on submit (omit or send `1` for today's behavior).

- `1` — a single curated day (wake → sleep, early morning through night). Today's behavior, unchanged.
- `2`–`7` — that many day-cycles, each with **different** activities (e.g. a workday, a day off, errands, a night out) rather than one day's beats stretched thin.
- Helper copy: "How many days this story spans. More days means more variety — each day gets its own activities."
- The storyboard's `time_of_day` tags now flow chronologically across the whole span (they no longer bounce within a day); for `period_days > 1` the early_morning→night progression repeats once per day-cycle. This is a scene-planning consequence of the control, not a separate field to build.

**Acceptance criteria:**
- Omitting `period_days` (or sending `1`) behaves identically to today.
- Launching with `period_days: 3` and opening the dry-run storyboard shows `time_of_day` tags progressing chronologically and repeating that progression roughly once per day-cycle, with visibly different activities/locations per cycle rather than one stretched-out day.

### WI-8 — Auto-generate the full persona on character creation (**required**; fixes the mostly-empty persona bug)

**The problem:** today the character-creation flow leaves the persona mostly blank. `System Prompt` ends up populated (a backend safety guarantee force-generates it), but `Greeting Message`, `Tone`, `Style`, `Boundaries`, and `Summary` stay empty — because generation was never requested for them. This is a two-call gap: `POST /v1/characters` creates the character; a fully separate `POST /v1/characters/{id}/persona` call (previously only invoked for `system_prompt`) is what actually writes the rest.

**Build:** when submitting the **New Character** form, send `generate_persona: true` on the SAME `POST /v1/characters` call — do not make a second request.

```jsonc
POST /v1/characters
{
  "persona": { /* PersonaOptions, as today */ },
  "hero_image_url": "...",
  "bio": "Night-shift nurse, introverted, loves slow mornings.",  // optional, as today
  "name": null,
  "generate_persona": true   // NEW — the only field you need to add to this call
}
```

- That single flag generates + persists `system_prompt`, `greeting_message`, `tone`, `style`, `boundaries`, `summary`, and `welcome_message` via Venice, all in this one request. If you left `bio` empty above, `bio` is generated too; if you typed a `bio`, it is preserved (never silently overwritten — see the contract doc's 2026-07-09 "auto-generate persona" addendum for the exact default-field rule, and `persona_fields` if you want to override it, e.g. to force-regenerate `bio` too).
- The response is the same `CharacterRead` shape as today — no new fields to read. `chat_persona_id` (already part of `CharacterRead`) will be populated when generation succeeded; the "Edit Chat Persona" panel will show the generated text exactly the way it already does today for any existing character.
- **Retire the separate "generate system_prompt only" call this flow currently makes on creation** — it's superseded by this one flag.
- The standalone `POST /v1/characters/{id}/persona` endpoint (§3) still exists and still matters — keep it for **re-generating** a field later (e.g. an admin clicks "Regenerate greeting" on an existing character from the Edit Chat Persona panel in your first screenshot). This work item is specifically about the *creation* flow.

**Acceptance criteria:**
- Creating a character with `generate_persona: true` and opening its "Edit Chat Persona" panel immediately afterward shows `System Prompt`, `Greeting Message`, `Tone`, `Style`, `Boundaries`, and `Summary` all populated — not just `System Prompt`.
- Creating a character with `generate_persona: true` and a typed `bio` shows that exact bio text preserved (not overwritten by generation).
- Creating a character without `generate_persona` (or with it `false`/omitted) behaves exactly as today (empty persona fields, unchanged).

---

## 3. Reference: dry-run storyboard with the new fields

`POST /v1/characters/{id}/batches` with `dry_run: true` returns a `planned` batch; then `GET /v1/batches/{id}` gives items whose `scene_spec` looks like this (nurse, low→high arc):

```jsonc
// request
{
  "count": 8,
  "dry_run": true,
  "likes": ["coffee", "silk"],
  "dislikes": ["loud crowds"],
  "controls": {
    "start_nudity": "low",     // ← WI-1 Start handle
    "max_nudity": "high",      // ← WI-1 Finish handle
    "escalation": "building",
    "outfit_denoise": 0.85,    // ← WI-2 (optional)
    "outfit_prompt_mode": "replace"
  }
}

// one item's scene_spec in the GET /v1/batches/{id} response
{
  "arc_id": "on_the_ward", "arc_title": "On Shift",
  "beat_description": "Restocking the supply cart between rounds",
  "setting": "a bright hospital ward corridor lined with carts",
  "activity": "restocking a supply cart",
  "outfit_detail": "fitted white nurse uniform dress with badge",  // ← WI-3
  "expression": "cheeky over-shoulder smirk",                      // ← WI-3
  "pose": "bending_over", "outfit": "nurse_uniform",
  "nudityLevel": "low",                                            // ← WI-3 badge
  "location": "hospital_ward", "time_of_day": "morning", "lighting": "bright_daylight",
  "mood_kinks": ["playful_teasing"],
  "narrative": "By mid-morning she is all business on the ward…"   // gallery text; DISPLAY-ok, never an input
}
```

Recommended flow stays the same: **Preview** (`dry_run:true`) → render storyboard → **Launch this plan** (`POST /v1/batches/{id}/launch`). See contract doc §6.

---

## 4. Guardrails (do NOT change these)

- **Never send appearance/identity text into a batch.** No face/hair/body/age/ethnicity descriptions anywhere. Identity is pixel-locked to the hero photo; the backend scrubs stray appearance words. The admin only picks *controls* and *traits*; the planner authors the scenes.
- **The admin never inputs scene enums** (outfit/pose/location per photo) for story batches — the planner chooses them. `allowed_/blocked_` lists are the only scene-vocab levers, and they already exist.
- **`start_nudity` ≤ `max_nudity`** always (compared on the 5-stop scale: low < suggestive < medium < revealing < high).
- **Everything additive** — if the panel sends no new fields, batches behave exactly as before.

---

## 5. Enum sources

Pull option lists from `/openapi.json → components.schemas`: `NudityLevel`, `OccupationType`, `RelationshipType`, `PersonalityType`, `KinkType`, `OutfitType`, `PoseType`, `LocationType`, `PhotoStyleType`, `SeedStrategy`. Scene-only enums nested in `scene_spec` (`TimeOfDayType`, `LightingType`) are **display-only** and listed in contract doc §7. All values are lowercase `snake_case`.

---

## 6. Definition of done

- [ ] Nudity-arc two-handle control (WI-1, 5-stop: low/suggestive/medium/revealing/high) sends `start_nudity` + `max_nudity`; verified via dry-run storyboard (non-decreasing arc; `sfw_only` forces low).
- [ ] Advanced outfit controls (WI-2) present; **default is now Replace/Auto** (not Standard); omitted from the request when untouched.
- [ ] Storyboard cards show `outfit_detail` / `expression` / `nudityLevel` when present, degrade cleanly when `null` (WI-3).
- [ ] Character form surfaces occupation/relationship/personality/kinks with the "shapes her story" hint (WI-4).
- [ ] Likes/dislikes re-sent on every launch (WI-5).
- [ ] Period/days control (WI-7) sends `controls.period_days` (1–7); omitted or `1` behaves identically to today.
- [ ] Character creation sends `generate_persona: true` (WI-8); the created character's persona shows all 6+ generated fields populated, not just System Prompt; a typed `bio` is preserved.
- [ ] Nude-base generate/status UI (WI-9) present on the character detail view; batches for that character visibly stop showing her original outfit ghosting through.
- [ ] No appearance text ever enters a batch request; existing batches (no new fields) still work.

---

## WI-9 — Nude base: additive dressing per character (new; optional but recommended)

**Why:** batches dress each scene by editing the character's clothed hero photo — a subtractive edit (remove the old garment, add the new one) that isn't always reliable; the avatar's original clothing can ghost through a "changed" outfit. A **nude base** — one identity-locked bare-skin render, generated once per character from her existing hero photo — flips this to an *additive* edit (clothes go ONTO bare skin), which is far more reliable. It's entirely new backend surface with no existing UI.

**Build:** on the character detail view, near the hero photo:
- A **"Generate nude base"** action → `POST /v1/characters/{id}/nude-base` (admin-only, 202 → `{characterId, status, jobId, imageUrl, error, createdAt, updatedAt}`, `status="pending"`). Same async pattern as every other edit: it queues a job, nothing renders synchronously.
- Poll `GET /v1/characters/{id}/nude-base` (same response shape) until `status` is `"succeeded"` or `"failed"` — this endpoint finalizes the job on read, so simple polling (e.g. every 2–3s) is enough; no separate confirm step. `imageUrl` is populated once `succeeded`.
- Show a status badge: none yet / generating / ready / failed (with `error` message + a retry = call `POST` again).
- **Do not surface the nude image anywhere public** — no gallery, no chat, no character card. It's an internal rendering asset only; keep it behind the same admin-only view as generation.
- **Consent/moderation copy**: this explicitly creates and stores a nude asset for that character. Add a short confirmation step ("Generate an internal nude base for {name}? Only do this for characters where this is intended.") before the first call — don't make it a one-click accident.

**Acceptance criteria:**
- Triggering generation on a character with no base shows "generating" then transitions to "ready" (or "failed" with a retry option) without a page reload.
- A character with **no** nude base generated behaves in batches exactly as before (no visible change) — this control is purely additive/opt-in, nothing to migrate.
- After generating a base, running a batch for that character and comparing to a prior one shows outfit changes taking more reliably (this is the actual acceptance test — the API contract alone doesn't prove the fix, a real batch does).

---

## 7. Known render limits (set expectations)

*(Added 2026-07-09, from this session's render-pipeline investigation. Companion ops
doc: [`docs/OPS_OUTFIT_TIER_2511.md`](./OPS_OUTFIT_TIER_2511.md).)*

These are backend rendering-pipeline realities, not admin-panel bugs — set
expectations accordingly rather than building or promising a control that can't
move the pixels.

**Head accessories can't change.** `glasses` / `earrings` / `hat` / `sunglasses`
(`AccessoryType`) all sit on or immediately around the head, which is the identity
anchor: the outfit step masks the head out of its edit region (a server-computed
head-protect mask, subtracted before the crop-and-stitch sampler runs), and the
background step masks the *entire* person and composites them back byte-identical.
Whatever survives those two steps then has its face restored again by the pose
step's face-swap. So an avatar's glasses/earrings/hat appear identically in every
photo by construction — an `accessories` value can select them (on a single-photo
edit, or via the story planner's `scene_spec.accessories`) but nothing visibly
changes. Only `necklace` sits low enough (below the head-mask's chin/jaw padding)
to land in the editable region and actually render. Don't promise an accessories
control for head items.

**Poses can look stiff/repetitive.** Each of the 16 `PoseType` values is driven by
exactly one fixed reference image (`assets/poses/pose_ref_<value>.png`) that the
pose workflow instructs the model to copy closely ("Make the person in image 1 do
the exact same pose of the person in image 2 ... match image 2 accurately"). Every
photo using a given pose type therefore looks near-identical to every other photo
using that same type, and the achievable variety across a whole batch is capped at
16 silhouettes total. Fixing this needs more/varied reference images per pose, or a
pose-generation model — a backend change, not something an admin input can reach.

**"Generate" re-plans; "Launch this plan" reproduces the preview.**
`POST /v1/characters/{id}/batches` — what the "Generate {count}" button calls,
whether `dry_run` is `true` or `false` — always calls the story planner fresh. With
Venice as the planner (temperature 0.7), that means a second "Generate" with
identical inputs produces a **different** storyboard than the one just previewed.
Only `POST /v1/batches/{id}/launch` ("Launch this plan") skips planning entirely
and reuses the previewed batch's persisted `scene_spec` rows as-is. So the
"preview → confirm" flow in the contract doc's §6 isn't just a nicety — it's the
only path that renders exactly what was previewed. Consider making the UI's
primary Generate action reuse an existing preview (`dry_run:true` first, then
launch that) rather than exposing a plain "Generate" that silently re-plans.
