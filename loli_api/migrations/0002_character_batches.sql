-- Character Batches — batch job tracking retargeted onto the REAL product schema.
-- Run this in the Supabase SQL editor (or via the CLI) once. Idempotent.
--
-- This migration REPLACES the story_* schema (0001_story_batches.sql):
--   * Characters are now real rows in public.characters (created by the API,
--     status 'draft' until the admin publishes them).
--   * Generated photos land in public.character_images, each wired to a
--     public.chat_persona_actions quick action.
--   * Only the async job state (batches + items) still needs dedicated tables,
--     created here WITHOUT the story_ prefix and FK'd to the real characters.
--
-- PRE-REQUISITE: public.characters, public.character_images and
-- public.chat_persona_actions already exist (product tables owned by the chat
-- app's DDL) — this migration intentionally does NOT create or alter them.
--
-- The API is single-admin and authenticates with the service-role key, so there
-- is no owner_id column and no owner RLS policy on these job tables.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Auto-update updated_at (shared with 0001; safe to re-create)
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------------
-- character_batches
-- ---------------------------------------------------------------------------
create table if not exists public.character_batches (
    id               uuid primary key default gen_random_uuid(),
    character_id     uuid not null references public.characters(id) on delete cascade,
    count            int  not null check (count between 1 and 50),
    controls         jsonb not null default '{}',
    likes            text[] not null default '{}',
    dislikes         text[] not null default '{}',
    status           text not null default 'pending',
    progress         real not null default 0,
    items_total      int  not null default 0,
    items_succeeded  int  not null default 0,
    items_failed     int  not null default 0,
    error            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index if not exists idx_character_batches_character on public.character_batches (character_id);
create index if not exists idx_character_batches_created   on public.character_batches (created_at desc);
create index if not exists idx_character_batches_status    on public.character_batches (status);

drop trigger if exists trg_character_batches_updated_at on public.character_batches;
create trigger trg_character_batches_updated_at
    before update on public.character_batches
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- character_batch_items
-- ---------------------------------------------------------------------------
create table if not exists public.character_batch_items (
    id                 uuid primary key default gen_random_uuid(),
    batch_id           uuid not null references public.character_batches(id) on delete cascade,
    scene_index        int  not null,
    scene_spec         jsonb not null,
    pipeline_request   jsonb,
    job_id             text,
    status             text not null default 'pending',
    preview_url        text,
    image_url          text,
    image_hash         text,
    seed               bigint,
    arc                text,
    beat               int,
    attempts           int  not null default 0,
    error_code         text,
    error_message      text,
    -- Set once the succeeded item's gallery row exists in character_images.
    -- Idempotency guard: reconciler retries/restarts skip re-inserting.
    character_image_id uuid references public.character_images(id) on delete set null,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    unique (batch_id, scene_index)
);

create index if not exists idx_character_batch_items_batch  on public.character_batch_items (batch_id, scene_index);
create index if not exists idx_character_batch_items_job    on public.character_batch_items (job_id);
create index if not exists idx_character_batch_items_status on public.character_batch_items (batch_id, status);

drop trigger if exists trg_character_batch_items_updated_at on public.character_batch_items;
create trigger trg_character_batch_items_updated_at
    before update on public.character_batch_items
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Row-level security.
-- These are internal job-tracking tables reached ONLY through the API's
-- service-role client (which BYPASSES RLS). Enabling RLS with NO policies is
-- deliberate: it denies all anon/authenticated access (defense-in-depth) while
-- leaving the service-role backend fully functional. Idempotent.
-- ---------------------------------------------------------------------------
alter table public.character_batches      enable row level security;
alter table public.character_batch_items  enable row level security;

-- ---------------------------------------------------------------------------
-- Cleanup of the superseded story_* schema (0001).
-- The story_* data is throwaway dev state; uncomment and run DELIBERATELY once
-- you have confirmed nothing you care about lives there.
-- ---------------------------------------------------------------------------
-- drop table if exists public.story_batch_items;
-- drop table if exists public.story_batches;
-- drop table if exists public.story_characters;
