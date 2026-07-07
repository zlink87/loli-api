-- Story Batches — persistence for characters, batches and batch items.
-- Run this in the Supabase SQL editor (or via the CLI) once.
--
-- Tables are namespaced with a `story_` prefix so they never collide with existing
-- product tables (e.g. a pre-existing `characters` or `batches`). If you re-run
-- after a failed attempt, it is safe (idempotent).
--
-- The API authenticates with the service-role key, which BYPASSES RLS; ownership
-- is enforced in application code (every query filters by owner_id). The RLS
-- policies below are defense-in-depth for any future direct-from-frontend access
-- with a user (anon) JWT.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Auto-update updated_at
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------------
-- story_characters
-- ---------------------------------------------------------------------------
create table if not exists public.story_characters (
    id             uuid primary key default gen_random_uuid(),
    owner_id       uuid not null,
    name           text not null,
    persona        jsonb not null,
    hero_image_url text not null,
    likes          text[] not null default '{}',
    dislikes       text[] not null default '{}',
    bio            text,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create index if not exists idx_story_characters_owner         on public.story_characters (owner_id);
create index if not exists idx_story_characters_owner_created on public.story_characters (owner_id, created_at desc);

drop trigger if exists trg_story_characters_updated_at on public.story_characters;
create trigger trg_story_characters_updated_at
    before update on public.story_characters
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- story_batches
-- ---------------------------------------------------------------------------
create table if not exists public.story_batches (
    id               uuid primary key default gen_random_uuid(),
    character_id     uuid not null references public.story_characters(id) on delete cascade,
    owner_id         uuid not null,
    count            int  not null check (count between 1 and 50),
    controls         jsonb not null default '{}',
    status           text not null default 'pending',
    progress         real not null default 0,
    items_total      int  not null default 0,
    items_succeeded  int  not null default 0,
    items_failed     int  not null default 0,
    error            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index if not exists idx_story_batches_character      on public.story_batches (character_id);
create index if not exists idx_story_batches_owner_created  on public.story_batches (owner_id, created_at desc);
create index if not exists idx_story_batches_status         on public.story_batches (status);

drop trigger if exists trg_story_batches_updated_at on public.story_batches;
create trigger trg_story_batches_updated_at
    before update on public.story_batches
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- story_batch_items
-- ---------------------------------------------------------------------------
create table if not exists public.story_batch_items (
    id               uuid primary key default gen_random_uuid(),
    batch_id         uuid not null references public.story_batches(id) on delete cascade,
    scene_index      int  not null,
    scene_spec       jsonb not null,
    pipeline_request jsonb,
    job_id           text,
    status           text not null default 'pending',
    preview_url      text,
    image_url        text,
    image_hash       text,
    seed             bigint,
    arc              text,
    beat             int,
    attempts         int  not null default 0,
    error_code       text,
    error_message    text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    unique (batch_id, scene_index)
);

create index if not exists idx_story_batch_items_batch  on public.story_batch_items (batch_id, scene_index);
create index if not exists idx_story_batch_items_job    on public.story_batch_items (job_id);
create index if not exists idx_story_batch_items_status on public.story_batch_items (batch_id, status);

drop trigger if exists trg_story_batch_items_updated_at on public.story_batch_items;
create trigger trg_story_batch_items_updated_at
    before update on public.story_batch_items
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Row-level security (defense-in-depth; service-role backend bypasses these)
-- ---------------------------------------------------------------------------
alter table public.story_characters  enable row level security;
alter table public.story_batches      enable row level security;
alter table public.story_batch_items  enable row level security;

drop policy if exists story_characters_owner on public.story_characters;
create policy story_characters_owner on public.story_characters
    using (owner_id = auth.uid()) with check (owner_id = auth.uid());

drop policy if exists story_batches_owner on public.story_batches;
create policy story_batches_owner on public.story_batches
    using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- batch_items inherit ownership via their parent batch.
drop policy if exists story_batch_items_owner on public.story_batch_items;
create policy story_batch_items_owner on public.story_batch_items
    using (exists (select 1 from public.story_batches b
                   where b.id = story_batch_items.batch_id and b.owner_id = auth.uid()))
    with check (exists (select 1 from public.story_batches b
                        where b.id = story_batch_items.batch_id and b.owner_id = auth.uid()));
