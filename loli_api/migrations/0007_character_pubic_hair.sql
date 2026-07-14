-- Character pubic-hair grooming — a single persona column on public.characters.
-- Run this ONCE in the Supabase SQL editor (or via the CLI). Idempotent
-- (add column if not exists), so re-running is a no-op.
--
-- WHY THIS MIGRATION EXISTS: pubic_hair (shaved, trimmed, landing_strip, natural,
-- full) is a new optional persona dimension (loli-api PubicHairType, models/enums.py)
-- that steers genital-area grooming/realism ONLY where the area is exposed (a
-- NAKED-class outfit at HIGH nudity, and the character's nude base). It is persisted
-- alongside the rest of the flat persona on the character row, so the store needs one
-- column to write/read it.
--
-- Unlike 0006 (culture, a nullable column), this column is NOT NULL DEFAULT 'shaved':
-- the product treats an unspecified value as "shaved" everywhere (the phrase helper
-- services/attribute_phrases.pubic_hair_phrase resolves None -> shaved), so the DB
-- default backfills every existing row to the same 'shaved' the API would render, and
-- the store never writes NULL (services/character_store._persona_to_columns coerces an
-- unset persona value to 'shaved'). The vocabulary itself is enforced APP-SIDE
-- (PubicHairType), NOT by a DB check constraint, so the append-only enum can grow
-- without a schema change; an unknown/garbage stored value degrades to None on read
-- (services/character_store._valid_pubic_hair) and then resolves to the shaved default.
--
-- DEPLOY ORDER: run this migration BEFORE deploying the code that writes the column —
-- PostgREST rejects an insert/update referencing a column the schema cache does not yet
-- know about. The READ path is tolerant of the column's absence (a pre-migration row
-- with no such column reads as None -> shaved), so a code deploy that briefly races
-- ahead of the migration degrades safely rather than erroring on GET.

alter table public.characters
  add column if not exists pubic_hair text not null default 'shaved';

comment on column public.characters.pubic_hair is
  'Pubic-hair grooming (loli-api PubicHairType value: shaved, trimmed, landing_strip, natural, full). NOT NULL DEFAULT ''shaved''; only rendered where the genital area is exposed.';
