# Generation Nudity & Clothing — Admin Panel Integration Guide

Handoff spec for wiring the **admin "generate character / new photo" form** to the new
clothing + nudity controls on `POST /v1/generate/image` in `loli-api`. Everything here
is self-contained; you do not need the backend source.

**Why this exists:** the character-generation endpoint previously had **no clothing or
nudity control at all**. The base model is NSFW-tuned, so with no clothing clause it
rendered nude by default, and an outfit typed into the scene box was routinely
overridden. The backend now accepts the same `outfit` / `nudityLevel` / `accessories`
controls that the **Outfit Edit** tab already uses. This guide is about surfacing those
three controls on the **generation** form.

**Backend defaults are safe:** if you send none of the new fields, generation now
defaults to `nudityLevel=low` (fully clothed) with a neutral outfit. So the API is
already fixed for existing callers — this task is about giving admins explicit control.

---

## 0. Authoritative schema

The live OpenAPI schema is the source of truth for every field and enum value:

- **Swagger UI:** `GET {API_BASE}/docs`
- **Raw schema:** `GET {API_BASE}/openapi.json` → `components.schemas.GenerateImageRequest`

Prefer generating dropdown options from `/openapi.json` over hard-coding. The values
below are provided for convenience but OpenAPI is canonical.

---

## 1. What changed on the request

Endpoint (unchanged): `POST {API_BASE}/v1/generate/image` (JWT auth, returns `202` +
`jobId`; poll `GET /v1/jobs/{jobId}` exactly as today).

Three **new, optional** fields on the request body — all top-level (siblings of
`persona`, `context`, `shot`):

| Field         | Type              | Default   | Meaning |
|---------------|-------------------|-----------|---------|
| `nudityLevel` | enum string       | `"low"`   | `low` = fully clothed · `medium` = partial exposure · `high` = nude |
| `outfit`      | enum string \| null | `null`  | Specific outfit to generate in. `null` → a neutral outfit at the chosen `nudityLevel` |
| `accessories` | array of enum strings (max 5) \| null | `null` | Accessories to add |

**These are exactly the same three controls already on the Outfit Edit tab** — reuse
the same dropdown component, radio group, and accessory chips. The only difference is
they now attach to the generation form instead of the edit form.

### Enum values (identical to the Outfit Edit tab)

`nudityLevel` (radio — mirror the edit tab's labels):
- `low` — "Low · Suggestive / clothed"
- `medium` — "Medium · Partial nudity"
- `high` — "High · Full nudity"

`accessories` (multi-select chips, max 5): `necklace`, `earrings`, `glasses`, `hat`,
`sunglasses`

`outfit` (dropdown, 47 options — same list the Outfit Edit tab renders):

```
red_evening_gown, little_black_dress, white_summer_dress, floral_maxi_dress,
cocktail_dress, bodycon_dress, business_suit, blazer_trousers, pencil_skirt_set,
tuxedo, denim_jacket_jeans, graphic_tee_shorts, hoodie_joggers, flannel_shirt,
crop_top_cargo, yoga_outfit, tennis_outfit, running_gear, gym_set,
one_piece_swimsuit, bikini, leather_jacket, trench_coat, puffer_jacket, fur_coat,
kimono, sari, cheongsam, hanbok, dirndl, sequin_top_skirt, velvet_dress,
satin_slip_dress, jumpsuit, polka_dot_dress_50s, bell_bottoms_70s, power_suit_80s,
silk_pajamas, lace_bodysuit, satin_robe, oversized_streetwear, bomber_jacket_fit,
nurse_uniform, school_uniform, military_uniform, chef_uniform, naked
```

> The `naked` outfit and `nudityLevel=high` are the two explicit NSFW paths. If the
> generation form has an SFW/NSFW toggle or content gate, gate these the same way the
> Outfit Edit tab does.

---

## 2. UI to add on the generation form

Add a section (or reuse the Outfit-tab layout) with, in order:

1. **Outfit** — dropdown, optional. Include an explicit "Auto / none" option that maps
   to omitting `outfit` (or sending `null`). Label it e.g. "Default (auto)".
2. **Nudity Level** — radio, three options, default **Low**. Same labels/order as the
   Outfit Edit tab.
3. **Accessories** — up to 5 chips (same component as the edit tab).

Keep the existing `context` (scene description) free-text box. It still works and is
now **reinforced** by the clothing clause + nudity negative rather than fighting them —
so "wearing a blue business suit at the office" typed there will actually be honored.

---

## 3. Request example

```jsonc
POST /v1/generate/image
Authorization: Bearer <supabase-jwt>
Content-Type: application/json

{
  "persona": {
    "style": "realistic",
    "ethnicity": "asian",
    "age": 28,
    "hairStyle": "ponytail",
    "hairColor": "black",
    "eyeColor": "green",
    "bodyType": "average",
    "breastSize": "medium",
    "name": "Estella",
    "personality": "shy",
    "occupation": "nurse"
  },
  "context": "after a long shift, relaxing at home",
  "outfit": "blazer_trousers",     // NEW — optional, omit or null for auto
  "nudityLevel": "low",            // NEW — optional, defaults to "low"
  "accessories": ["necklace"],     // NEW — optional, max 5, omit or null for none
  "shot": { "framing": "waist_up", "angle": "eye_level", "photoStyle": "polished" },
  "output": { "aspectRatio": "2:3", "hires": true }
}
```

Response and polling are unchanged (`202` + `jobId` → poll `GET /v1/jobs/{jobId}`).

---

## 4. Behavior contract (so you can set expectations in the UI)

- **`low`** → character is fully clothed; the backend also suppresses nudity in the
  negative prompt. Skimpy-but-clothed outfits (bikini, sheer summer dress, lace
  bodysuit) still render correctly — only actual body exposure is suppressed.
- **`medium`** → partial exposure per the outfit's mid-level description; only explicit
  full-frontal nudity is suppressed.
- **`high`** (or `outfit: "naked"`) → nude output; nothing suppressed.
- **`outfit` omitted** → neutral outfit at the chosen level (clothed at `low`).
- **`outfit` + `nudityLevel` together** → the outfit is rendered at that nudity grade
  (e.g. `business_suit` + `medium` = the mid-level "unbuttoned" variant).

---

## 5. Validation / edge cases

- `accessories` is capped at **5**; the API returns `422` if longer — enforce max-5 in
  the UI.
- All three fields are optional; sending `null` or omitting them is valid and yields the
  safe clothed default.
- Values are lowercase snake_case enum strings exactly as listed. Unknown values →
  `422`.
- No new endpoint, no auth change, no response-shape change. This is purely additive on
  the request body.

---

## 6. Definition of done

- [ ] Generation form renders Outfit dropdown (with an "auto/none" option), Nudity radio
      (default Low), and Accessories chips (max 5) — reusing the Outfit Edit tab
      components.
- [ ] The three fields are sent on `POST /v1/generate/image` (omitted/null when unset).
- [ ] NSFW gating (if any) applies to `nudityLevel=high` and `outfit=naked` consistently
      with the Outfit Edit tab.
- [ ] Existing `context` free-text box retained.
- [ ] Options sourced from `/openapi.json` where practical rather than hard-coded.
