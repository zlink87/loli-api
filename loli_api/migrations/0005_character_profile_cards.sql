-- Character Profile Cards — the PUBLIC display card the chat FE shows for a character
-- (Candy.ai-style: hook + humanized title + adjective chips + hobby chips). Run this in
-- the Supabase SQL editor once. Idempotent.
--
-- WHY THIS TABLE EXISTS: the trait profile (0004) is an internal BIAS sheet reached only
-- through the service-role backend. The chat FE, however, needs a small set of
-- human-facing display fields (short "read more" hook, humanized occupation, personality
-- + hobby chips, language, zodiac) to render the character's public profile card. Rather
-- than make the FE parse the internal profile jsonb (or reach loli-api), those fields are
-- FLATTENED into this dedicated, FE-readable table by TraitProfileStore whenever a profile
-- is written. It is derived data — the trait writer/store is the single source of truth.
--
-- KEY DIFFERENCE FROM 0004 (character_trait_profiles): 0004 is RLS-enabled with NO
-- policies (service-role only — internal bias data). THIS table is PUBLIC DISPLAY data, so
-- RLS is enabled WITH a read-only SELECT policy for anon + authenticated (so the chat FE
-- can read cards directly with its normal client). WRITES remain service-role only — the
-- service-role client bypasses RLS, and no INSERT/UPDATE/DELETE policy is granted, so anon
-- + authenticated can read but never write. Everything here is non-sensitive display copy.
--
-- PRE-REQUISITE: public.characters already exists (a product table owned by the chat app's
-- DDL) — this migration intentionally does NOT create or alter it.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Auto-update updated_at (shared with 0001/0002/0003/0004; safe to re-create)
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------------
-- character_profile_cards
--
-- Exactly ONE row per character (character_id UNIQUE): the flattened public card,
-- upserted by TraitProfileStore alongside every profile write (per-field never-clobber,
-- zodiac mirrored from the profile). Plain typed columns so the FE reads them directly.
-- ---------------------------------------------------------------------------
create table if not exists public.character_profile_cards (
    id                   uuid primary key default gen_random_uuid(),
    character_id         uuid not null unique references public.characters(id) on delete cascade,
    short_description    text,
    display_occupation   text,
    display_personality  text[] not null default '{}',
    display_hobbies      text[] not null default '{}',
    language             text not null default 'English',
    zodiac               text,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

create index if not exists idx_character_profile_cards_character on public.character_profile_cards (character_id);

drop trigger if exists trg_character_profile_cards_updated_at on public.character_profile_cards;
create trigger trg_character_profile_cards_updated_at
    before update on public.character_profile_cards
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Row-level security — PUBLIC READ, service-role-only WRITE.
-- Unlike 0004 (RLS-enabled, NO policies = deny all non-service-role), this is public
-- display data: enable RLS and grant a read-only SELECT policy to anon + authenticated so
-- the chat FE can read cards with its normal client. No write policy is granted, so those
-- roles can never INSERT/UPDATE/DELETE; the backend's service-role client bypasses RLS and
-- remains the only writer. Idempotent (drop-then-create the policy).
-- ---------------------------------------------------------------------------
alter table public.character_profile_cards enable row level security;

drop policy if exists character_profile_cards_public_read on public.character_profile_cards;
create policy character_profile_cards_public_read
    on public.character_profile_cards
    for select
    to anon, authenticated
    using (true);
