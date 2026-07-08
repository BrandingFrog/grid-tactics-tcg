-- Discord login + cloud deck sync (user 2026-07-08).
-- Run once in the Supabase SQL editor (Dashboard -> SQL -> New query).
-- Idempotent: safe to re-run.

create table if not exists gt_users (
    discord_id   text primary key,
    username     text not null default '',
    display_name text not null default '',
    avatar_url   text not null default '',
    updated_at   timestamptz not null default now()
);

create table if not exists gt_decks (
    discord_id text not null references gt_users(discord_id) on delete cascade,
    slot       integer not null,
    name       text not null default '',
    cards      jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    primary key (discord_id, slot)
);

create index if not exists gt_decks_discord_idx on gt_decks(discord_id);

-- Keep updated_at fresh on writes.
create or replace function gt_touch_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists gt_users_touch on gt_users;
create trigger gt_users_touch before update on gt_users
    for each row execute function gt_touch_updated_at();

drop trigger if exists gt_decks_touch on gt_decks;
create trigger gt_decks_touch before update on gt_decks
    for each row execute function gt_touch_updated_at();

-- The game server uses the service/secret key (bypasses RLS). If you also
-- expose these tables to the browser anon key, add RLS policies scoped to
-- auth.uid(); the server path does not require them.
