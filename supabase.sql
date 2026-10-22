create table if not exists public.app_state (
  id text primary key,
  data jsonb not null
);
alter table public.app_state enable row level security;
-- Nepřidávat veřejné politiky. Server používá service role key pouze na backendu.
