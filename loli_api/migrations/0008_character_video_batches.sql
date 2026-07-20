-- Per-character admin video batches — durable batch job tracking for reels.
-- Run this in the Supabase SQL editor (or via the CLI) once. Idempotent.
--
-- An admin picks a character, picks N of its gallery stills, assigns each an
-- action (a preset from the tiered video action catalog, or a hand-written
-- prompt), and launches a batch. Each item animates one still into a short WAN
-- 2.2 i2v clip; outputs land as DRAFT chat actions the admin publishes per item.
--
-- Core design is submit-only worker + durable reconciler: the worker submits to
-- RunPod and persists runpod_request_id on the item row; a VideoBatchReconciler
-- polls RunPod status and owns persistence/retry/recovery, so a deploy no longer
-- strands in-flight clips.
--
-- PRE-REQUISITE: public.characters, public.character_images and
-- public.chat_persona_actions already exist (product tables owned by the chat
-- app's DDL) — this migration intentionally does NOT create or alter them.
--
-- House style of 0002: idempotent DDL, set_updated_at() trigger, RLS enabled
-- with no policies (the API is single-admin and uses the service-role key), and
-- FKs to the product tables it does not create.

create extension if not exists "pgcrypto";
create or replace function set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;

create table if not exists public.character_video_batches (
    id               uuid primary key default gen_random_uuid(),
    character_id     uuid not null references public.characters(id) on delete cascade,
    quality_mode     text not null default 'fast',          -- 'fast' (lightning) | 'max' (baseline)
    defaults         jsonb not null default '{}',           -- w/h/length/fps/seed_strategy/base_seed/interpolate/negative
    status           text not null default 'pending',       -- planning|running|completed|partial|failed|cancelled|planned
    progress         real not null default 0,
    items_total      int  not null default 0,
    items_succeeded  int  not null default 0,
    items_failed     int  not null default 0,
    error            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);
create index if not exists idx_cvb_character on public.character_video_batches (character_id);
create index if not exists idx_cvb_created   on public.character_video_batches (created_at desc);
create index if not exists idx_cvb_status    on public.character_video_batches (status);
drop trigger if exists trg_cvb_updated_at on public.character_video_batches;
create trigger trg_cvb_updated_at before update on public.character_video_batches
    for each row execute function set_updated_at();

create table if not exists public.character_video_batch_items (
    id                 uuid primary key default gen_random_uuid(),
    batch_id           uuid not null references public.character_video_batches(id) on delete cascade,
    item_index         int  not null,
    source_image_id    uuid not null references public.character_images(id) on delete cascade,
    source_image_url   text not null,
    action_kind        text not null,                        -- 'preset' | 'custom'
    preset_id          text,
    custom_prompt      text,
    tier               text,                                 -- charm_idle|playful|glamour|tease|explicit, null for custom
    motion_text        text,
    motion_label       text,
    loras              jsonb,                                -- [{name,strength_high,strength_low}]
    quality_mode       text not null default 'fast',
    width              int,  height int,  length int,  fps int,
    seed               bigint,
    negative_prompt    text,
    status             text not null default 'pending',      -- pending|queued|running|succeeded|failed|cancelled
    job_id             text,
    runpod_request_id  text,                                 -- DURABLE
    runpod_status      text,
    submitted_at       timestamptz,
    attempts           int  not null default 0,
    error_code         text,
    error_message      text,
    video_url          text,
    preview_url        text,
    image_hash         text,
    character_image_id uuid references public.character_images(id) on delete set null,
    action_id          uuid references public.chat_persona_actions(id) on delete set null,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    unique (batch_id, item_index)
);
create index if not exists idx_cvbi_batch   on public.character_video_batch_items (batch_id, item_index);
create index if not exists idx_cvbi_status  on public.character_video_batch_items (batch_id, status);
create index if not exists idx_cvbi_job     on public.character_video_batch_items (job_id);
create index if not exists idx_cvbi_runpod  on public.character_video_batch_items (runpod_request_id);
drop trigger if exists trg_cvbi_updated_at on public.character_video_batch_items;
create trigger trg_cvbi_updated_at before update on public.character_video_batch_items
    for each row execute function set_updated_at();

alter table public.character_video_batches      enable row level security;
alter table public.character_video_batch_items  enable row level security;
