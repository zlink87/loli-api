# Admin UI Work Order — Options endpoint + creation/edit deltas (age cap 50, Teacher, poseText, persona voice)

**Audience:** the agent/developer building the **admin panel frontend** (separate repo).
**Backend status:** shipped on `main` (2026-07-13). All changes are additive and back-compatible — the current panel keeps working unchanged; this work order lets it stop hardcoding option lists and exposes a few new controls.

**Source of truth for enums:** previously `/openapi.json → components.schemas`. **New and preferred:** `GET /v1/options` (below) returns every selectable option as ready-to-render `{value, label}` pairs plus numeric constraints, in one call.

---

## 0. Why this work exists

The admin panel currently hardcodes every dropdown for character creation/editing and generation (ethnicity, hair, personality, occupation, outfits, poses, locations, …). Every time the backend enums change, the panel silently drifts out of sync. The new `GET /v1/options` endpoint makes the backend the single source of truth so the panel builds its forms from live data.

Two enum-level requests are already reflected there: **age max is now 50** (was 99), and **Teacher** was added to the occupation list.

---

## 1. What changed in the API (delta only)

| Change | Where | Panel impact |
|---|---|---|
| **New `GET /v1/options`** | admin-only endpoint | Fetch once, build all dropdowns from it. **WI-1.** |
| **Age max 50** (`PersonaOptions.age`, `le=50`) | character create/edit request | Clamp the age input/slider to 18–50. Sending >50 now 422s. **WI-2.** |
| **Teacher occupation** | `OccupationType` (now 44 values) | Appears automatically in `/v1/options` and `/openapi.json`. No hardcoded list to edit if you adopt WI-1. **WI-3.** |
| **New `poseText`** (optional, `≤200` chars) | `GenerateImageRequest` (image generation) | Optional freeform pose override field. **WI-4.** |
| **Persona `system_prompt` / `welcome_message` voice** | AI-generated persona fields | Generated text now reads as third-person description *about* the character (not "You are…"). Display/label nudge only. **WI-5.** |
| **New `persona.culture` (subculture)** | `PersonaOptions.culture`, optional | New dropdown, 16 values. Optional, default `None`. **WI-6.** |

Everything else (nudity handling, pose/outfit variety, Venice scene literalness) is **backend-internal behavior** — better images/scenes with **no panel change required** (see §5).

---

## 2. The endpoint contract — `GET /v1/options`

- **Auth:** admin JWT, same bearer as every other admin route (`require_admin`). Non-admin → `403`, unauthenticated → `401`.
- **Method/path:** `GET /v1/options`. Stateless, cacheable per app session (values only change on a backend deploy).
- **Response:** four groups, each a map of field → array of `{value, label}`. `value` is the enum value you submit back to the API; `label` is a Title-Cased display string (`"boss_ceo"` → `"Boss Ceo"` — override in the UI if you want nicer casing).

```jsonc
{
  "persona": {                       // character create/edit form
    "style":        [{ "value": "realistic", "label": "Realistic" }, …],   // 2
    "ethnicity":    [ … ],           // 5
    "hair_style":   [ … ],           // 6
    "hair_color":   [ … ],           // 5
    "eye_color":    [ … ],           // 3
    "body_type":    [ … ],           // 5
    "breast_size":  [ … ],           // 4
    "personality":  [ … ],           // 12
    "relationship": [ … ],           // 19
    "occupation":   [ … ],           // 44  (includes { "value": "teacher", "label": "Teacher" })
    "kinks":        [ … ],           // 23  (max 3 selectable — see constraints)
    "culture":      [ … ],           // 16  (new — subculture/aesthetic, optional)
    "constraints": {
      "age":            { "min": 18, "max": 50 },
      "kinks_max":      3,
      "name_max_length": 50
    }
  },
  "generation": {                    // image generation form
    "nudity_level":  [ … ],          // 5
    "outfit":        [ … ],          // 47
    "pose":          [ … ],          // 16
    "accessory":     [ … ],          // 5
    "photo_style":   [ … ],          // 4
    "aspect_ratios": ["2:3","3:4","1:1","9:16","16:9","3:2","4:3"],   // plain strings
    "resolutions":   [ … ]           // plain strings
  },
  "scene": {                         // story-batch / scene form
    "location":      [ … ],          // 31
    "time_of_day":   [ … ],
    "lighting":      [ … ],
    "shot_framing":  [ … ],
    "camera_angle":  [ … ],
    "expression":    [ … ]
  },
  "video": {                         // reels form
    "motion":        [ … ],          // 24
    "lengths":       [ … ],          // plain numbers
    "resolutions":   [ … ]           // plain strings
  }
}
```

`aspect_ratios`, `resolutions`, `lengths` are plain scalar arrays (not `{value,label}`) — render them directly. `voice` is intentionally **not** in the response: it is a free-text field on the backend, no fixed list exists.

---

## 3. Work items

### WI-1 — Replace hardcoded dropdowns with `/v1/options` (**required**; the headline)
On admin app load (or first time a form opens), `GET /v1/options`, cache it, and build every create/edit/generation dropdown from it. Delete the hardcoded arrays. Persist the submitted `value` exactly; show `label` (or your own prettier casing). Fallback: if the fetch fails, keep the last-known list or the existing hardcoded arrays so forms still render — this endpoint is additive, not a hard dependency.

**Acceptance:** no option list is hardcoded in the panel; adding an enum value on the backend appears in the panel after a reload with no frontend change.

### WI-2 — Age input max 50 (**required**; tiny)
Clamp the age control to `constraints.age` (18–50). The old 99 ceiling now fails validation (`422`). If any saved character has age >50 (shouldn't, but old data), the edit form should still load it and only clamp on change.

### WI-3 — Teacher occupation (**free** if WI-1 adopted)
Nothing to do beyond WI-1 — Teacher flows in automatically. If you have NOT yet adopted WI-1, add `teacher` to the hardcoded occupation list.

### WI-4 — Optional `poseText` on the image generation form (optional; small)
Add an optional single-line "Pose (freeform)" text input (≤200 chars) to the image-generation form, mapping to `poseText` on `GenerateImageRequest`. When set, the backend uses it verbatim for the body position and skips its automatic pose rotation. Leave empty for the default (the backend now auto-varies pose/framing per image). Omit the field entirely when blank.

### WI-5 — Persona editor: voice/label nudge (recommended; display-only)
AI-generated persona fields changed voice:
- **`system_prompt`** is now a third-person description *about* the character for the reader ("{name} is a 24-year-old…"), **not** an instruction addressed to the AI ("You are…, Stay in character…").
- **`welcome_message`** asterisk actions now describe *her own* action ("*I lean back in my chair…*"), never the user's ("*You lean back…*").

The panel needs no functional change — it still displays/edits whatever the backend generates. Optional polish: relabel the "System Prompt (Required)" field to something like **"Character Description"** so the third-person copy reads correctly to admins; the field key on the wire is unchanged.

### WI-6 — `persona.culture` (subculture) dropdown (optional; new)
`GET /v1/options → persona.culture` returns 16 `{value, label}` entries — a subculture/
aesthetic pick (Goth, Punk, E-girl, Grunge, Y2K, Cottagecore, Dark Academia, Old Money,
Streetwear Baddie, Kawaii / Harajuku, Gyaru, Boho / Hippie, Pin-up / Rockabilly, Rocker /
Biker, Rave / Festival, Sporty / Gym). Render the dropdown in **response order** — that
order is the intended UI order, don't re-sort alphabetically.

- **Optional, no default value.** It is not listed under `constraints`, has no required
  minimum — the field is entirely skippable. The dropdown should default to a **"None (no
  subculture)"** entry.
- **Create form:** selecting "None" means **omit `culture` from the payload** — don't send
  `""` or a placeholder value.
- **Edit form:** selecting "None" on a character that already has a `culture` set should
  send `culture: null` in the `PATCH /v1/characters/{id}` body to clear it; leaving it
  untouched (not sending the key at all) leaves the existing value unchanged.
- Steers generation (clothing/scenes/poses/interior) and feeds the AI trait-profile/persona
  writers — no panel logic needed beyond collecting and sending the value; see
  `docs/ADMIN_TRAIT_PROFILE_INTEGRATION.md` for the trait-profile interaction.

---

## 4. Guardrails (do NOT change these)

- Keep submitting enum **`value`** strings (e.g. `"boss_ceo"`, `"teacher"`), never the `label`.
- Don't invent options client-side; if you need a new one, add it to the backend enum so `/v1/options` stays authoritative.
- `GET /v1/options` is admin-only — send the admin bearer, same as other admin calls.

## 5. Backend behavior changes (FYI — no panel action)

These improve output with no contract change: character-generation now reflects **age** (18/21/28 look different), enforces the requested **nudity level** with positive-token clothing + coverage phrasing, and **varies pose/framing/outfit per image** (previously every image was the same waist-up front-facing crop). Venice-authored **scene/story render text** is now literal and directional instead of flowery. If the panel shows generated scene captions, expect plainer, more concrete wording.

## 6. Definition of done

- [ ] Panel fetches `GET /v1/options` and builds all create/edit/generation dropdowns from it; no hardcoded option arrays remain (WI-1).
- [ ] Age control clamped to 18–50 (WI-2).
- [ ] Teacher selectable as an occupation (WI-3).
- [ ] Optional freeform pose field wired to `poseText`, omitted when blank (WI-4).
- [ ] Persona System Prompt field renders third-person copy correctly (optionally relabeled) (WI-5).
- [ ] `culture` dropdown built from `persona.culture` (16 entries, response order), defaults to "None (no subculture)"; "None" omits the field on create and sends `null` on edit (WI-6).
