-- Local-only Supabase shims: let migrations 003/004 run on a plain
-- PostgreSQL instance (via pgserver) for verification. NOT for production
-- and never applied to the real Supabase project.
--
-- Provides:
--   auth.users stub + auth.uid() driven by the `app.test_uid` GUC
--   (mirrors how Supabase JWT claims drive auth.uid()).

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key
);

create or replace function auth.uid() returns uuid
language sql stable
as $$
  select nullif(current_setting('app.test_uid', true), '')::uuid
$$;

-- Note: gen_random_uuid() is built into PostgreSQL 13+, so pgcrypto
-- (not shipped with pgserver's binaries) is not required.
