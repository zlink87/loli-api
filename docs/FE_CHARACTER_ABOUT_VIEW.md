# FE Work Order — Character "About" View in Chat (loli-ai / Ember)

Audience: the loli-ai client repo. What to render on the character profile /
"About" view inside chat (the Candy.ai-style card), from which tables, with
exact queries and fallbacks. Backend work is DONE and live after the next
loli-api deploy + one backfill call; the FE can build against real data.

---

## 1. Data sources (all readable with the FE's anon/authenticated key)

| Table | What the About view uses |
|---|---|
| `characters` | `name`, `age`, `ethnicity`, `body_type`, `relationship`, `occupation` (fallback only), `context` (FULL bio — the "Read more" target), `chat_avatar_url` / `profile_image_url`, `welcome_message`, `status` |
| `character_profile_cards` (NEW — public SELECT policy `character_profile_cards_public_read`, verified in prod) | `short_description`, `display_occupation`, `display_personality[]`, `display_hobbies[]`, `language`, `zodiac` |
| `character_images` | gallery photos (already in use) |

One extra query per character page:

```js
const { data: card } = await supabase
  .from('character_profile_cards')
  .select('short_description, display_occupation, display_personality, display_hobbies, language, zodiac')
  .eq('character_id', characterId)
  .maybeSingle();          // null until backfill / first generation — handle gracefully
```

## 2. View composition (top to bottom)

**Header**
- `characters.name` (+ `, {age}` in the muted style already used on Discover).
- **Short description** — `card.short_description` (a 2–3 sentence hook, ≤220
  chars, written for end users). Below it a **"Read more"** control that
  expands to `characters.context` (the full bio, up to ~4000 chars — render
  with paragraph breaks, collapse back supported).
- Fallback when `card` is null: show the first ~180 chars of
  `characters.context` + "Read more" (i.e., today's behavior).

**"About me" facts grid** (two columns, icon + label + value — same layout as
the current version; values change source):

| Tile | Source | Formatting |
|---|---|---|
| AGE | `characters.age` | as-is |
| BODY | `characters.body_type` | humanize enum: `snake_case` → Title Case ("curvy" → "Curvy") |
| ETHNICITY | `characters.ethnicity` | humanized label map (e.g. `black_afro` → "Black", `caucasian` → "Caucasian", `asian` → "Asian", `latina` → "Latina", `arab` → "Middle Eastern") |
| LANGUAGE | `card.language` | default "English" when card null; keep the flag icon |
| RELATIONSHIP | `characters.relationship` | humanize enum; "None" when null |
| OCCUPATION | `card.display_occupation` | **prefer the card** ("Heiress and Socialite"); fallback: humanized `characters.occupation` enum |
| HOBBIES | `card.display_hobbies` | join with ", " (2–5 items, ≤32 chars each); **hide the tile when card null/empty** |
| PERSONALITY | `card.display_personality` | join with ", " ("Well-educated, Spoiled, Charming"); fallback: humanized `characters.personality` single enum |
| ZODIAC (new tile) | `card.zodiac` | Title Case + sign emoji (♌ Leo …); **hide when null** — nice differentiator vs Candy |

**Gallery strip** (unchanged) — `character_images` as today. Note for the
gating layer: every batch-generated image row carries `outfit` and
`metadata.workflow_meta` server-side; nudity-based blur/unlock rules are a
separate work order if wanted.

## 3. Rules & don'ts

- **Graceful null card**: the card row appears when the admin runs the
  backfill once, when a character is created, or when an admin edits the
  profile. Until then every tile must fall back per the table above — never
  block the view on the card.
- **Never display**: `chat_personas.system_prompt` / `boundaries` (chat-engine
  internals), `characters.kinks` (drives generation flavor, not profile copy),
  and anything from `character_trait_profiles` (not readable by the FE key by
  design — its user-facing projection IS the card table).
- **No caching beyond the session**: admins can regenerate any card field;
  re-fetch on view open is cheap (single indexed row).
- `display_*` values are already human-written (the LLM/deterministic writer
  produces final copy) — render verbatim, no extra title-casing on them.

## 4. Consistency promise (why this is worth building)

The card is generated from the SAME character sheet that now steers her photo
batches: the hobbies shown are the likes that bias her scenes, her personality
adjectives match the demeanor that shapes her poses, her home photos render in
her interior style. About view, chat persona, and gallery all describe the
same person — no more generic copy next to mismatched photos.

## 5. Optional follow-ups (not in this work order)

- Surface `quirks` / `backstory` on the About view — requires loli-api to
  mirror them into `character_profile_cards` (small change; request it if the
  design wants them).
- Nudity-tier blur/unlock on gallery images for free vs premium
  (`profiles.subscription_tier`) — separate work order; the data exists
  server-side per image.
