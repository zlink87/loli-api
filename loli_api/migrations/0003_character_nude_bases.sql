-- Character Nude Bases — one identity-locked "nude/underwear base" render per character.
-- Run this in the Supabase SQL editor (or via the CLI) once. Idempotent.
--
-- WHY THIS TABLE EXISTS: story batches dress each scene by EDITING the character's
-- clothed hero photo. Swapping one outfit for another is a subtractive edit (remove
-- the old garment, add the new one) and unreliable — the hero's original clothing
-- (e.g. an open plaid shirt) tends to ghost through the new outfit. The fix is to
-- generate ONE nude base per character (avatar -> nude via the existing outfit-edit
-- machinery, head/face identity-locked exactly as every other outfit edit) and start
-- each batch scene's edit chain from THAT bare-skin base instead of the clothed hero,
-- so dressing becomes ADDITIVE (put clothes on bare skin). Skipping the outfit step
-- then simply leaves the scene nude.
--
-- This mirrors 0002_character_batches.sql: it is a loli-api-OWNED job/asset table,
-- NOT part of the shared product schema. The nude base is an INTERNAL generation
-- asset (never a gallery photo, never surfaced in chat), so it deliberately does NOT
-- live in public.character_images — it gets its own small table instead of polluting
-- the gallery or requiring a product-schema migration.
--
-- PRE-REQUISITE: public.characters already exists (a product table owned by the chat
-- app's DDL) — this migration intentionally does NOT create or alter it.
--
-- The API is single-admin and authenticates with the service-role key, so there is
-- no owner_id column and no owner RLS policy on this table.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Auto-update updated_at (shared with 0001/0002; safe to re-create)
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------------
-- character_nude_bases
--
-- One row per generation attempt. The batch engine reads the LATEST 'succeeded'
-- row's image_url as the scene edit source; a fresh 'pending' regeneration never
-- disturbs the current 'succeeded' one until it itself succeeds (no gap). job_id
-- correlates the in-flight outfit_edit job so GET /nude-base can finalize it on
-- read (the endpoint polls that job and writes image_url + flips status).
-- ---------------------------------------------------------------------------
create table if not exists public.character_nude_bases (
    id                uuid primary key default gen_random_uuid(),
    character_id      uuid not null references public.characters(id) on delete cascade,
    -- The clothed hero the base was derived from (provenance).
    source_image_url  text,
    -- The generated nude-base render (null until the job succeeds).
    image_url         text,
    image_hash        text,
    -- The outfit_edit Job that generates it (for reconcile-on-read finalization).
    job_id            text,
    status            text not null default 'pending',
    error             text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index if not exists idx_character_nude_bases_character on public.character_nude_bases (character_id, created_at desc);
create index if not exists idx_character_nude_bases_status    on public.character_nude_bases (character_id, status);
create index if not exists idx_character_nude_bases_job       on public.character_nude_bases (job_id);

drop trigger if exists trg_character_nude_bases_updated_at on public.character_nude_bases;
create trigger trg_character_nude_bases_updated_at
    before update on public.character_nude_bases
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Row-level security.
-- An internal asset table reached ONLY through the API's service-role client
-- (which BYPASSES RLS). Enabling RLS with NO policies is deliberate: it denies all
-- anon/authenticated access (defense-in-depth) while leaving the service-role
-- backend fully functional. Idempotent.
-- ---------------------------------------------------------------------------
alter table public.character_nude_bases enable row level security;
