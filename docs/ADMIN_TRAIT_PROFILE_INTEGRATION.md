# Admin Panel Integration — Character Trait Profiles, Profile Cards & Batch Quality (2026-07-13)

Audience: the admin-panel repo (and chat FE) — everything needed to plan UI work
against the loli-api changes shipped 2026-07-13. No backend reading required.

Status legend: **[LIVE]** = merged and tested in loli-api; **[B2 — landing]** =
implementation in final phase, same shapes, do not block planning on it.

---

## 0. TL;DR for the panel

New concept: every character has an auto-generated, admin-editable **trait
profile** (an RPG-style character sheet: wardrobe style, demeanor, taste/home
style, likes/dislikes, backstory, zodiac, quirks) plus a **public profile card**
(Candy.ai-style "About me": short hook description, humanized occupation,
personality adjectives, hobbies). The profile silently steers every photo batch
(what she wears, where she is, how she poses); the card is what end users see in
chat Discover/About.

Panel work items (details below):
1. **"Traits & Card" section** on the character page — view, edit-in-place,
   per-field regenerate, regenerate-all. (§3–§5)
2. **"Backfill profiles" action** on the characters list — one call fills every
   character that has no profile yet. (§5.5)
3. Nothing needed for batches to use profiles — it's automatic — but optionally
   surface the new **soft-bias batch controls** + `use_trait_profile` toggle in
   the batch launch form's advanced section. (§6)
4. Previously documented, still pending panel-side (see
   `ADMIN_STORY_BATCHES_V2_WORKORDER.md` §9): per-photo **Edit scene / Re-run**
   UI and sending **`characterId`** on standalone edit calls.
5. Chat FE: read the card from the new public table `character_profile_cards`
   (§7). "Read more" expands to the full bio (`characters.context`).

---

## 1. What changed server-side (context, no action needed)

Batch generation quality (all **[LIVE]**, automatic):
- **Nudity labels are now truthful.** Every outfit has an "exposure cap" (a
  t-shirt can't render "mostly nude" no matter the prompt). High-nudity slots
  now receive garments that can actually show that level (robe/lingerie/naked
  class); in the rare case nothing suitable is allowed, the item's nudity label
  is lowered to match reality. The chip on the card always matches the pixels.
- **Photos read like a life, not a photoshoot.** Every batch item now carries an
  expression (previously none → permanent camera-smile); ~1/3 of items are
  candid/camera-unaware; no pose or expression repeats on adjacent items; the
  "sultry, seductive" mood phrase appears on only ~1/3 of eligible items and
  never on low-nudity/public scenes; pose repetition capped globally.
- **Render tier**: batches run the full 2511 graphs (outfit + pose, cfg 2.5,
  live negative prompts). Backgrounds remain on the fast tier by design.
- **Character generation (hero photos)**: subtle color-grade clause for richer,
  non-washed-out color (env-tunable `GENERATION_COLOR_GRADE`; empty disables).

Trait profiles (**[LIVE]** foundation, **[LIVE]** batch consumption):
- Generated automatically on character create (flag `generate_traits`, default
  `true` on `POST /v1/characters`, also bulk).
- One Venice LLM call authors the sheet + card; every enum field is validated
  against real vocabularies; deterministic fallback guarantees a complete
  profile even with no LLM. Free text (backstory, home description, card text)
  is display/chat-only — it NEVER enters image prompts.
- **[LIVE]** At batch launch the profile fills any controls the admin left unset:
  wardrobe soft-pool (≈3x weighting, variety preserved), `never_wears` hard-
  blocked, favorite locations favored / avoided blocked (work locations
  protected), demeanor biases poses + expressions, interior style + palette
  render HER home consistently in every home-location photo. Explicit admin
  values always win. The profile can never raise nudity above batch settings.

---

## 2. Data model the panel touches

| Store | Access | Contents |
|---|---|---|
| `character_trait_profiles` (jsonb `profile`, `provider`) | **API only** (service role; panel uses the endpoints below) | the full sheet + card source of truth |
| `character_profile_cards` (flat columns) | **public SELECT** (anon+authenticated) — for the chat FE | short_description, display_occupation, display_personality[], display_hobbies[], language, zodiac |
| `characters.context` | existing | full bio ("read more" target) |

`provider` values: `venice` (LLM), `deterministic` (fallback), `mixed`
(per-field mix), `manual` (admin edited).

---

## 3. The TraitProfile object (returned/edited via API)

All fields optional; lists deduped server-side; unknown enum values are
repaired (fuzzy) or dropped — the panel can submit user input as-is.

**Sheet (drives image generation):**

| Field | Type / limit | Vocabulary source |
|---|---|---|
| `wardrobe_styles` | ≤3 of WardrobeStyleType | options endpoint (§5.6) |
| `favorite_outfits` | ≤5 of OutfitType | options |
| `never_wears` | ≤8 of OutfitType (hard-blocked in batches) | options |
| `favorite_locations` | ≤5 of LocationType | options |
| `avoided_locations` | ≤8 of LocationType | options |
| `demeanor` | ≤2 of DemeanorType | options |
| `interior_style` | 1 of InteriorStyleType (her home's look) | options |
| `color_palette` | 1 of PaletteType | options |
| `likes` / `dislikes` | ≤12 each, free keywords ≤120 chars | free text |
| `zodiac` | 1 of 12 | options |

**Display-only (never rendered into images):**

| Field | Type / limit | Shown where |
|---|---|---|
| `backstory` | ≤800 chars | admin + chat context |
| `home_description` | ≤400 chars | admin + chat context |
| `quirks` | ≤6 items ≤120 chars | admin + chat context |

**Card (mirrored to `character_profile_cards` on every save):**

| Field | Type / limit | Example |
|---|---|---|
| `short_description` | ≤220 chars, hook voice | "Wealthy Russian heiress, accustomed to luxury…" |
| `display_occupation` | ≤40 chars | "Heiress and Socialite" |
| `display_personality` | 2–4 items ≤24 chars | "Well-educated", "Spoiled", "Charming" |
| `display_hobbies` | 2–5 items ≤32 chars | "Exclusive parties", "Five-star hotels" |
| `language` | string, default "English" | — |

---

## 4. Semantics the UI should communicate

- **Never-clobber edits**: PUT changes only the fields sent; regenerate changes
  only the fields requested. Safe to wire per-field save buttons.
- **Wardrobe is a bias, not a uniform**: her styles weight picks ~3x and
  `never_wears` is absolute, but occasional off-style outfits still appear (by
  design, for variety). Occupation uniforms (nurse etc.) always allowed in work
  scenes regardless of style tags.
- **Nudity is untouchable from the profile** — batch controls alone govern it.
  Don't present profile fields as affecting explicitness.
- **`culture` (subculture) is a persona-level INPUT, not a profile field** — it lives on
  the character (`persona.culture`, set at creation or via `PATCH /v1/characters/{id}`;
  see `docs/ADMIN_OPTIONS_ENDPOINT_WORKORDER.md`), not inside `TraitProfile`. It has no
  key in the §3 table and no control in the trait-profile panel. Regenerating a profile
  (§5.2) simply *respects* whatever `culture` is currently set on the character — it leans
  the writer's wardrobe/location/interior/likes/bio choices toward that subculture — but
  there is nothing to edit here directly.
- **Batch launch overrides**: anything set explicitly in the launch form beats
  the profile for that batch. `use_trait_profile: false` ignores the profile
  entirely for that batch.

---

## 5. Admin API (all `require_admin`, prefix `/v1`) — **[LIVE]**

### 5.1 Read
`GET /characters/{id}/trait-profile`
→ `{character_id, profile: TraitProfile, provider, created_at, updated_at}`;
404 if character or profile missing (show "Generate" CTA on 404).

### 5.2 Generate / regenerate (LLM with fallback)
`POST /characters/{id}/trait-profile/generate`
```jsonc
{
  "fields": ["backstory", "wardrobe_styles"],   // omit = ALL fields
  "enrichment": {                               // optional, transient flavor input
    "likes": ["champagne"], "dislikes": [], "interests": [], "hobbies": [], "language": "English"
  },
  "dry_run": false                              // true = preview result, persist nothing
}
```
→ `{character_id, profile, generated, generated_fields, provider, persisted}`
Panel mapping: "Regenerate" button per field → `fields:[that]`; "Regenerate
all" → omit; preview toggle → `dry_run`.

### 5.3 Manual edit
`PUT /characters/{id}/trait-profile` — body: any subset of TraitProfile fields
(only sent fields change) → TraitProfileRead. Saved as `provider: "manual"`.

### 5.4 Stateless preview (character creation form, before the row exists)
`POST /trait-profiles/preview` — `{persona, fields?, enrichment?, backstory?}`
→ `{profile, generated, provider}`; writes nothing.

### 5.5 Backfill existing characters
`POST /trait-profiles/backfill?limit=500`
→ `{results: [{character_id, provider | error}]}` — iterates characters with no
profile, best-effort each. Idempotent (skips characters that have one). Panel:
one button + results toast; re-run until `results` comes back empty.

### 5.6 Vocabularies
`GET /v1/options` now includes a `trait_profile` group (wardrobe styles,
demeanor, zodiac, interior styles, palettes) alongside the existing outfit /
location groups. Build all dropdowns from options — never hardcode.

### 5.7 Character creation
`POST /v1/characters` accepts `generate_traits: bool` (default `true`) next to
the existing `generate_persona`. Both are best-effort — creation never fails
because generation failed.

---

## 6. Batch launch form — optional additions **[LIVE]**

`BatchCreate` gains `use_trait_profile: bool = true`. `BatchControls` gains
optional soft-bias fields the panel MAY expose in an "advanced" section (they
are normally profile-derived; explicit values win): `wardrobe_outfits`,
`favored_outfits`, `favored_locations`, `demeanor`, `interior_style`,
`color_palette`. Minimum viable panel change: a single "Use character's trait
profile" checkbox (default on). Existing controls unchanged.

`character_batches.controls` jsonb also records `_planner_provider` and the
batch row exposes `planner_provider` — worth showing on batch detail.

### 6.1 Single-photo generation can also be trait-themed **[LIVE]**

Batches were always the main consumer of the profile; single-photo character
generation now gets an optional, thin slice of the same bias. `POST /v1/generate/image`
(and each item of `POST /v1/generate/batch`) accepts three optional fields:

| Field | Type | Effect |
|---|---|---|
| `characterId` | `string｜null` | When set, the server loads that character's trait profile and auto-fills `wardrobeStyles` + `demeanor` below (best-effort; unknown id or no profile = no-op). |
| `wardrobeStyles` | `WardrobeStyleType[]｜null` (≤3) | Biases the auto-varied clothing toward these styles. |
| `demeanor` | `DemeanorType｜null` | Biases the auto-varied facial expression toward this demeanor. |

Semantics mirror the edit endpoints' `characterId`/`identityAnchors` pattern:

- **Bias only, and only on the variety path.** `wardrobeStyles` narrows the seeded
  default-clothing pool ONLY when no explicit `outfit` is sent AND generation variety
  is enabled; `demeanor` swaps the seeded expression pool ONLY when no explicit `shot`
  is sent. With an explicit outfit/shot, or variety off, both are inert.
- **Never touches identity or nudity.** This is wardrobe/expression flavor; skin, hair,
  face and `nudityLevel` are unaffected. (Skin-tone identity anchoring on generation is
  a separate concern and unchanged.)
- **Explicit wins.** An explicit `wardrobeStyles`/`demeanor` in the request is never
  overridden by the profile; each field is filled independently only when absent.
- **Panel action: optional.** Nothing is required — omitting all three preserves today's
  behavior byte-for-byte. If you already send `characterId` on edit calls, sending it on
  a generate call for an existing character is the one-line way to keep her wardrobe on-
  brand across ad-hoc photos.

## 7. Chat FE — the About card

One query per character page:
```sql
select short_description, display_occupation, display_personality,
       display_hobbies, language, zodiac
from character_profile_cards where character_id = :id;
```
- Public read policy verified in prod (`character_profile_cards_public_read`).
- "Read more" → `characters.context` (full bio, already readable by FE).
- Age/body/ethnicity/relationship stay on `characters` as today.
- Rows appear when: a character is created (auto-gen), the backfill runs, or an
  admin saves the profile. Handle absent-row gracefully (fallback to today's
  layout).

## 8. Deploy checklist (already done in prod unless noted)

- [x] `character_trait_profiles` + `character_profile_cards` tables
- [x] `character_profile_cards` public SELECT policy (verified)
- [x] Batch env: 2511 outfit+pose tiers + `BATCH_REQUIRE_CROPSTITCH_OUTFIT=true`
- [ ] `ON DELETE CASCADE` alters for both new tables (SQL provided in chat)
- [ ] Remove stale `ATCH_REQUIRE_CROPSTITCH_OUTFIT` env var
- [ ] Deploy loli-api after B2 merges; then run the backfill once
