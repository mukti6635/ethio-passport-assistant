-- ETHIO backend — migration 001: initial schema
-- Target: Supabase (PostgreSQL 15+). Run with `supabase db push` or paste
-- into the Supabase SQL editor in order.
--
-- Design rules:
--  * Every row belongs to exactly one user (owner_id = auth.uid()).
--  * Raw OCR output (extractions) is stored separately from user-confirmed
--    data (confirmed_fields) — they are different tables on purpose.
--  * Secrets, document bytes, and identity numbers never go in audit events.
--  * updated_at is maintained by trigger.

-- Enable UUID generation
create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------- profiles
-- One row per authenticated user. Created on first sign-in.
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  preferred_locale text not null default 'en'
    check (preferred_locale in ('en', 'am', 'om')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ------------------------------------------------------------------- tasks
-- One row per user task (e.g. "Passport application — Renewal").
create table public.tasks (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles (id) on delete cascade,
  service_id text not null,                       -- e.g. 'passport'
  title text not null,
  stage text not null default 'requirements'      -- TaskStage name
    check (stage in ('intake','requirements','documents','review','issues',
                     'approvals','appointment','done')),
  answers jsonb not null default '{}'::jsonb,      -- intake answers
  appointment jsonb,                               -- office/day/time/reference
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index tasks_owner_idx on public.tasks (owner_id, created_at desc);

-- ------------------------------------------------------------ requirements
-- Dynamic per-task requirements and their status.
create table public.requirements (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks (id) on delete cascade,
  requirement_id text not null,                   -- catalog id, e.g. 'national_id'
  label text not null,                            -- resolved display label
  status text not null default 'missing'
    check (status in ('missing','uploaded','verified')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (task_id, requirement_id)
);
create index requirements_task_idx on public.requirements (task_id);

-- --------------------------------------------------------------- documents
-- Metadata only. File bytes live in private Supabase Storage
-- (bucket: 'documents', path: '<owner_id>/<task_id>/<doc_id>.<ext>').
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks (id) on delete cascade,
  requirement_id text not null,
  owner_id uuid not null references public.profiles (id) on delete cascade,
  storage_path text not null,
  file_name text not null,
  mime_type text not null,
  size_bytes integer not null check (size_bytes > 0),
  -- Validation outcome, set by the pipeline before extraction.
  validation_status text not null default 'pending'
    check (validation_status in ('pending','valid','rejected')),
  validation_note text,
  created_at timestamptz not null default now()
);
create index documents_task_idx on public.documents (task_id);

-- -------------------------------------------------------------- extractions
-- RAW, UNTRUSTED OCR output. Never treat as verified truth.
create table public.extractions (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents (id) on delete cascade,
  task_id uuid not null references public.tasks (id) on delete cascade,
  field_name text not null,                       -- language-independent key
  field_value text not null,                      -- raw OCR text
  confidence double precision not null check (confidence between 0 and 1),
  created_at timestamptz not null default now()
);
create index extractions_task_idx on public.extractions (task_id);

-- ---------------------------------------------------------- confirmed_fields
-- USER-CONFIRMED data only. The agent may act on these; never on extractions.
create table public.confirmed_fields (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks (id) on delete cascade,
  field_name text not null,                       -- language-independent key
  field_value text not null,
  source text not null default 'user'             -- 'user' | 'user_correction'
    check (source in ('user','user_correction')),
  confirmed_at timestamptz not null default now(),
  unique (task_id, field_name)
);
create index confirmed_fields_task_idx on public.confirmed_fields (task_id);

-- ------------------------------------------------------------------- issues
-- Missing information and conflicts. Conflicts are never auto-resolved.
create table public.issues (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks (id) on delete cascade,
  kind text not null check (kind in ('missing','conflict')),
  title text not null,
  detail text not null,
  options jsonb not null default '[]'::jsonb,     -- candidate values
  resolution text,                               -- NULL until user resolves
  resolved_at timestamptz,
  created_at timestamptz not null default now()
);
create index issues_task_idx on public.issues (task_id);

-- --------------------------------------------------------------- checkpoints
-- Human checkpoints. Server-side state; the agent cannot advance without a
-- matching 'authorized' row created by an explicit user action.
create table public.checkpoints (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks (id) on delete cascade,
  kind text not null
    check (kind in ('otp','captcha','payment','legal','appointment')),
  status text not null default 'pending'
    check (status in ('pending','authorized','expired','cancelled')),
  -- Authorization evidence (who/when), never secrets or codes.
  authorized_by uuid references public.profiles (id),
  authorized_at timestamptz,
  expires_at timestamptz,
  detail jsonb not null default '{}'::jsonb,      -- e.g. {amount, currency}
  created_at timestamptz not null default now(),
  unique (task_id, kind)
);
create index checkpoints_task_idx on public.checkpoints (task_id);

-- ---------------------------------------------------------- browser_sessions
-- References to isolated browser-automation sessions. One session belongs to
-- one user and one task; users can never see each other's sessions.
create table public.browser_sessions (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks (id) on delete cascade,
  owner_id uuid not null references public.profiles (id) on delete cascade,
  external_session_id text,                      -- provider's session id
  status text not null default 'created'
    check (status in ('created','running','paused','done','failed','cancelled')),
  goal text not null,
  evidence jsonb,                                -- verified outcome + references
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index browser_sessions_owner_idx on public.browser_sessions (owner_id);

-- --------------------------------------------------------------- audit_events
-- Minimal audit trail. NEVER store secrets, document contents, identity
-- numbers, OTP codes, or payment credentials here.
create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  task_id uuid references public.tasks (id) on delete cascade,
  owner_id uuid not null references public.profiles (id) on delete cascade,
  event text not null,                           -- e.g. 'checkpoint.authorized'
  metadata jsonb not null default '{}'::jsonb,   -- non-sensitive only
  created_at timestamptz not null default now()
);
create index audit_events_task_idx on public.audit_events (task_id, created_at desc);

-- ------------------------------------------------------- updated_at trigger
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

create trigger trg_profiles_updated
  before update on public.profiles
  for each row execute function public.touch_updated_at();
create trigger trg_tasks_updated
  before update on public.tasks
  for each row execute function public.touch_updated_at();
create trigger trg_requirements_updated
  before update on public.requirements
  for each row execute function public.touch_updated_at();
create trigger trg_browser_sessions_updated
  before update on public.browser_sessions
  for each row execute function public.touch_updated_at();
