-- Character culture / subculture tag — a single optional column on public.characters.
-- Run this ONCE in the Supabase SQL editor (or via the CLI). Idempotent
-- (add column if not exists), so re-running is a no-op.
--
-- WHY THIS MIGRATION EXISTS: culture (goth, punk, e_girl, ...) is a new optional
-- persona dimension (loli-api CultureType, models/enums.py) that steers a character's
-- styling, wardrobe and scenery. It is persisted alongside the rest of the flat persona
-- on the character row, so the store needs one nullable text column to write/read it.
--
-- FIRST loli-api migration to ALTER public.characters. 0004/0005 deliberately did NOT
-- touch this table (it is a PRODUCT table owned by the chat app's DDL — those migrations
-- only CREATED loli-api-owned side tables). This one makes a strictly-additive change:
-- a single nullable column, NO default, NO constraint, NO index. Existing rows and any
-- old insert/update payloads are unaffected (the column is simply NULL = no culture).
--
-- The vocabulary is enforced APP-SIDE (models/enums.py CultureType), NOT by a DB check
-- constraint, so the append-only enum can grow without a schema change; unknown/garbage
-- stored values degrade to NULL on read (services/character_store._valid_culture).
--
-- DEPLOY ORDER: this migration MUST be run BEFORE deploying the code that writes the
-- column — PostgREST rejects an insert/update referencing a column the schema cache does
-- not yet know about, so the new persona write path would 400 until the column exists.

alter table public.characters
  add column if not exists culture text;

comment on column public.characters.culture is
  'Optional culture/subculture tag (loli-api CultureType value: goth, punk, e_girl, ...). NULL = none.';
