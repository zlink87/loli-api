# Admin UI Work Order — Story Batches v2 (persona-driven stories, nudity arc, structured prompts)

**Audience:** the agent/developer building the **admin panel frontend** (separate repo).
**Backend status:** shipped and on `main` (commit `248a343d`). API is additive and back-compatible — the current admin panel keeps working unchanged; this work order only *adds* controls that expose new capability.

**Source of truth for the contract:** [`docs/ADMIN_STORY_BATCHES_INTEGRATION.md`](./ADMIN_STORY_BATCHES_INTEGRATION.md) — read §3 (endpoints), §4 (request/response shapes), §7 (enums), and the **Addendum (2026-07-09)** at the bottom. `/openapi.json` is canonical for enum option lists. This work order tells you *what UI to build*; that doc tells you *the exact field shapes*.

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

All additions live on `controls` (in `BatchCreate`) or in each item's `scene_spec` (in `BatchDetailRead`). Nothing was removed or renamed.

| New field | Where | Type / range | Purpose |
|---|---|---|---|
| `start_nudity` | `controls` | `"low"｜"medium"｜"high"｜null` | Photo 1's nudity; ramps up to `max_nudity`. **The nudity-arc START handle.** |
| `outfit_denoise` | `controls` | `float 0.5–0.95｜null` | Outfit-change strength (advanced). |
| `outfit_prompt_mode` | `controls` | `"standard"｜"replace"` | "replace" = remove current clothing first (advanced). |
| `outfit_detail` | item `scene_spec` | `string｜null` (≤160) | Concrete garment description for that photo (display only). |
| `expression` | item `scene_spec` | `string｜null` (≤80) | That photo's facial expression/mood (display only). |

`max_nudity` already existed and is now **both** the hard ceiling **and** the nudity-arc FINISH handle.

---

## 2. Work items

### WI-1 — Nudity arc control (**required**; this is the headline feature)

**Build:** in the **Batch launch modal**, replace the single `max_nudity` dropdown with a **two-handle "Nudity arc" control**: a **Start** handle and a **Finish** handle over three stops.

- Stops (3): `low` = **Fully clothed** · `medium` = **Partial nudity** · `high` = **Full nudity**. (Use these labels — they match the generation-nudity admin doc.)
- **Start handle → `controls.start_nudity`**, **Finish handle → `controls.max_nudity`**.
- **Constraint:** Start ≤ Finish (never allow Start above Finish).
- **Send both values explicitly** on submit. You may leave `escalation` at its default `"building"` — an explicit `start_nudity` overrides the escalation derivation anyway.
- **Copy under the control:** "The story stays at the Start level and builds up to the Finish level across the set. It can stay lower when a scene calls for it (e.g. at work), but never escalates past the per-photo target." (This is the *guided-ceiling* semantics — see the 07-09 addendum.)
- **Presets** (nice UX): "No nudity" (low→low), "Slow build" (low→high), "Spicy throughout" (medium→high), "Constant" (X→X). These are just handle positions.
- **`sfw_only` toggle interaction:** when `sfw_only` is ON (or `content_rating: "sfw"`), force both handles to `low` and disable the control.

**Acceptance criteria:**
- Launching low→high on an 8-photo batch and opening the dry-run storyboard shows `scene_spec.nudityLevel` **non-decreasing**, starting `low`, reaching `high` by the end.
- Setting Start = Finish = `medium` yields all-`medium` items.
- `sfw_only` forces every item to `low` regardless of handle positions.

> Note: even without this control the arc works via the default (`escalation:"building"` ⇒ low→max), but there'd be no way for the admin to set the **start point** — which is the whole ask. WI-1 is what exposes it.

### WI-2 — Advanced outfit-strength controls (optional; collapsible "Advanced")

**Build:** in an **Advanced** section of the launch modal:
- `outfit_denoise` — a slider `0.5–0.95` with an **"Auto"** state that sends `null` (engine default ≈ 0.80). Label: "Outfit change strength". Helper: "Higher forces the new outfit over the avatar's current clothing more strongly. Try 0.85 if outfits aren't changing."
- `outfit_prompt_mode` — a toggle `Standard ｜ Replace`. Helper: "Replace explicitly removes current clothing first — use when a dressed avatar keeps showing through."

**Acceptance criteria:** both default to Auto/Standard and are omitted (or sent as `null`/`"standard"`) when untouched; the batch behaves identically to today when they're at defaults.

### WI-3 — Storyboard card: show the new per-photo channels (recommended; display only)

**Build:** on each storyboard/item card (dry-run preview **and** results grid), in addition to the existing `outfit · pose · narrative`, surface from `scene_spec`:
- **`outfit_detail`** as the garment caption when present (fall back to the `outfit` enum label when `null`).
- **`expression`** as a small mood tag when present.
- **`nudityLevel`** as a small badge (Fully clothed / Partial / Full) — this makes the arc *visible* as you scan the set.

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
- **`start_nudity` ≤ `max_nudity`** always.
- **Everything additive** — if the panel sends no new fields, batches behave exactly as before.

---

## 5. Enum sources

Pull option lists from `/openapi.json → components.schemas`: `NudityLevel`, `OccupationType`, `RelationshipType`, `PersonalityType`, `KinkType`, `OutfitType`, `PoseType`, `LocationType`, `PhotoStyleType`, `SeedStrategy`. Scene-only enums nested in `scene_spec` (`TimeOfDayType`, `LightingType`) are **display-only** and listed in contract doc §7. All values are lowercase `snake_case`.

---

## 6. Definition of done

- [ ] Nudity-arc two-handle control (WI-1) sends `start_nudity` + `max_nudity`; verified via dry-run storyboard (non-decreasing arc; `sfw_only` forces low).
- [ ] Advanced outfit controls (WI-2) present, default to Auto/Standard, omitted/`null` when untouched.
- [ ] Storyboard cards show `outfit_detail` / `expression` / `nudityLevel` when present, degrade cleanly when `null` (WI-3).
- [ ] Character form surfaces occupation/relationship/personality/kinks with the "shapes her story" hint (WI-4).
- [ ] Likes/dislikes re-sent on every launch (WI-5).
- [ ] No appearance text ever enters a batch request; existing batches (no new fields) still work.
```
