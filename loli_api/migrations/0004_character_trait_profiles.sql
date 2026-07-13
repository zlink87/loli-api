-- Character Trait Profiles — one persistent "RPG character sheet" per character.
-- Run this in the Supabase SQL editor (or via the CLI) once. Idempotent.
--
-- WHY THIS TABLE EXISTS: today every character lives the same visual life —
-- only `occupation` structurally drives scene selection, personality/kinks are
-- mood-tint only, and batch-typed likes/dislikes are forgotten (never stored on
-- the character). A trait profile is the durable per-character taste — wardrobe
-- styles, favorite/never-worn outfits, favored/avoided locations, demeanor, home
-- interior style + palette, likes/dislikes, zodiac — that BIASES the existing
-- enum/pool machinery (wardrobe pools, demeanor-driven expression, styled home
-- scenery) so two differently-profiled characters produce visibly different
-- batches. Profile data NEVER enters a render prompt as free text (backstory /
-- home_description are display / LLM-context only) and NEVER touches nudity
-- controls (nudity belongs to the batch controls, not to taste).
--
-- This mirrors 0002_character_batches.sql / 0003_character_nude_bases.sql: a
-- loli-api-OWNED asset table, NOT part of the shared product schema. Generation
-- is a synchronous, never-raising Venice call producing ONE current-state row per
-- character — so there are deliberately NO status/job columns (unlike 0003's
-- async nude-base generation): the whole current profile is a single jsonb blob.
--
-- PRE-REQUISITE: public.characters already exists (a product table owned by the
-- chat app's DDL) — this migration intentionally does NOT create or alter it.
--
-- The API is single-admin and authenticates with the service-role key, so there
-- is no owner_id column and no owner RLS policy on this table.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Auto-update updated_at (shared with 0001/0002/0003; safe to re-create)
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------------
-- character_trait_profiles
--
-- Exactly ONE row per character (character_id UNIQUE): the character's current
-- trait sheet. `profile` is the whole TraitProfile serialized as jsonb (empty
-- default so a bare INSERT is always valid); `provider` records how it was last
-- authored ("venice" | "mixed" | "deterministic" | "manual"). Per-field
-- regeneration merges into `profile` in the store (never-clobber), so fields the
-- caller didn't (re)generate are preserved.
-- ---------------------------------------------------------------------------
create table if not exists public.character_trait_profiles (
    id                uuid primary key default gen_random_uuid(),
    character_id      uuid not null unique references public.characters(id) on delete cascade,
    profile           jsonb not null default '{}'::jsonb,
    provider          text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index if not exists idx_character_trait_profiles_character on public.character_trait_profiles (character_id);

drop trigger if exists trg_character_trait_profiles_updated_at on public.character_trait_profiles;
create trigger trg_character_trait_profiles_updated_at
    before update on public.character_trait_profiles
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Row-level security.
-- An internal asset table reached ONLY through the API's service-role client
-- (which BYPASSES RLS). Enabling RLS with NO policies is deliberate: it denies all
-- anon/authenticated access (defense-in-depth) while leaving the service-role
-- backend fully functional. Idempotent.
-- ---------------------------------------------------------------------------
alter table public.character_trait_profiles enable row level security;
