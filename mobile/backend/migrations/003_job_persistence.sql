-- ETHIO backend — migration 003: durable browser-agent job persistence
--
-- Replaces the gateway's in-memory _JOBS dict. Jobs survive restarts;
-- workers claim them atomically; clients poll for progress.
--
-- Design notes:
-- - One row per job. The gateway API remains the same; it reads/writes here
--   instead of the dict.
-- - `locked_by` / `locked_at`: worker claim via
--   UPDATE ... WHERE locked_by IS NULL (or lock expired) RETURNING *.
-- - `state` uses the same 8 values as the gateway JobState enum.
-- - `log` is a JSONB array of strings (append-only).
-- - `evidence` holds the final result + verification data (JSONB).
-- - RLS: users see only their own jobs (via owner_id).

create table public.agent_jobs (
  id            uuid primary key default gen_random_uuid(),
  owner_id      uuid not null references public.profiles(id) on delete cascade,
  session_id    text not null,
  goal          text not null,
  inputs        jsonb not null default '{}'::jsonb,
  state         text not null default 'queued'
                check (state in ('queued','running','paused','awaiting_human',
                                 'succeeded','failed','cancelled','timed_out')),
  log           jsonb not null default '[]'::jsonb,
  checkpoint    text,
  final_result  text,
  error         text,
  evidence      jsonb,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  ended_at      timestamptz,
  locked_by     text,
  locked_at     timestamptz,
  attempts      int not null default 0,
  -- Idempotency: same session + goal hash within 1h returns the existing job.
  idempotency_key text
);

create index agent_jobs_owner_state_idx
  on public.agent_jobs (owner_id, state);
create index agent_jobs_session_idx
  on public.agent_jobs (session_id);
create index agent_jobs_claim_idx
  on public.agent_jobs (state, locked_at)
  where state in ('queued','running');

alter table public.agent_jobs enable row level security;

create policy "agent_jobs_all_own"
  on public.agent_jobs for all
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- Workers use the service role (bypasses RLS). They claim with:
--
--   UPDATE public.agent_jobs
--   SET locked_by = $1, locked_at = now(), attempts = attempts + 1,
--       state = 'running', started_at = coalesce(started_at, now())
--   WHERE id = (
--     SELECT id FROM public.agent_jobs
--     WHERE state = 'queued'
--       AND (locked_by IS NULL OR locked_at < now() - interval '5 minutes')
--     ORDER BY created_at ASC
--     LIMIT 1
--     FOR UPDATE SKIP LOCKED
--   )
--   RETURNING *;
