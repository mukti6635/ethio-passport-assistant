-- ETHIO backend — migration 004: approvals and task events
--
-- Backend-enforced human approval for protected actions (submit, payment,
-- OTP, CAPTCHA, appointment, final legal submission). An LLM prompt is not
-- a security boundary: the agent prepares an action, the user approves via
-- an authenticated endpoint, and the execution gate consumes the approval
-- exactly once.
--
-- Design notes:
-- - `approvals`: one row per prepared protected action. `params_hash` is the
--   SHA-256 idempotency key over (action_type, canonical params); the same
--   job + action + params returns the existing pending row instead of a
--   duplicate. `consumed` is set atomically at execution; only one consumer
--   wins (see the gateway's ApprovalService.consume for the in-memory
--   equivalent; the DB path uses SELECT ... FOR UPDATE).
-- - `task_events`: append-only event log per job (plan/step/observation/
--   approval/result/error/status). Powers progress UI and audit.
-- - RLS: users see only their own rows via owner_id. Workers use the
--   service role (bypasses RLS).
-- - NEVER store secrets here: no API keys, passwords, OTP values, CAPTCHA
--   solutions, or raw document contents. params_summary holds non-sensitive
--   display strings only.

create table public.approvals (
  id            uuid primary key default gen_random_uuid(),
  approval_id   text not null unique,          -- secrets.token_urlsafe(24)
  job_id        text not null,                 -- gateway job id (hex)
  owner_id      uuid not null references public.profiles(id) on delete cascade,
  session_id    text not null,
  action_type   text not null,                 -- submit|payment|otp|captcha|appointment|...
  action_label  text not null,                 -- human-readable, e.g. "Submit passport application"
  consequence   text not null,                 -- plain-words description of what approval does
  params_hash   text not null,                 -- sha256 idempotency key (32 hex chars)
  params_summary jsonb not null default '{}'::jsonb,  -- non-sensitive display only
  state         text not null default 'pending'
                check (state in ('pending','approved','rejected','expired','cancelled')),
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null default now() + interval '30 minutes',
  decided_at    timestamptz,
  decided_by    text,                          -- session_id of decider
  decision_reason text,
  consumed      boolean not null default false,
  consumed_at   timestamptz,
  -- Execution lifecycle: approved -> executing -> succeeded/failed/unknown.
  -- 'unknown' = dispatched but outcome unverified (crash); never retried.
  execution_state text not null default 'not_started'
                check (execution_state in
                  ('not_started','executing','succeeded','failed','unknown')),
  execution_id  text,
  execution_started_at timestamptz,
  execution_ended_at   timestamptz,
  execution_evidence   text,
  -- Idempotency: one pending approval per job + action + params.
  unique (job_id, params_hash)
);

create index approvals_owner_state_idx
  on public.approvals (owner_id, state);
create index approvals_session_idx
  on public.approvals (session_id);
create index approvals_job_idx
  on public.approvals (job_id);
create index approvals_expires_idx
  on public.approvals (expires_at)
  where state = 'pending';

alter table public.approvals enable row level security;

create policy "approvals_all_own"
  on public.approvals for all
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- Atomic consume (run inside a transaction from the gateway/worker):
--
--   SELECT * FROM public.approvals
--   WHERE approval_id = $1
--     AND state = 'approved'
--     AND consumed = false
--     AND expires_at > now()
--   FOR UPDATE;
--   -- then, only if a row was returned:
--   UPDATE public.approvals
--   SET consumed = true, consumed_at = now()
--   WHERE approval_id = $1 AND consumed = false;
-- The second UPDATE's row count tells you whether you won the race.

create table public.task_events (
  id            bigserial primary key,
  job_id        text not null,
  owner_id      uuid not null references public.profiles(id) on delete cascade,
  session_id    text not null,
  kind          text not null
                check (kind in ('plan','step','observation','approval','result','error','status')),
  title         text not null,
  detail        text not null default '',
  created_at    timestamptz not null default now()
);

create index task_events_job_idx
  on public.task_events (job_id, id);
create index task_events_owner_idx
  on public.task_events (owner_id, created_at desc);

alter table public.task_events enable row level security;

create policy "task_events_all_own"
  on public.task_events for all
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- ---------------------------------------------------------------------------
-- Atomic execution claim (RPC)
--
-- The gateway's REST-based claim in api/persistence.py checks-then-updates,
-- which has a race window under concurrent workers. This function performs
-- the claim atomically with row-level locking:
--   - SELECT ... FOR UPDATE locks the approval row inside the transaction.
--   - All validity conditions are checked while the lock is held.
--   - The UPDATE flips execution_state to 'executing' and assigns a unique
--     execution_id; competing workers block on the lock, then re-read the
--     new state and fail their own checks.
-- Returns the claimed row, or no rows when the claim is denied.
-- ---------------------------------------------------------------------------

create or replace function public.claim_approval_for_execution(
  p_approval_id text,
  p_session_id text,
  p_job_id text,
  p_params_hash text,
  p_execution_id text
)
returns setof public.approvals
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.approvals%rowtype;
begin
  -- Lock the row; concurrent claims serialize here.
  select * into v_row
  from public.approvals
  where approval_id = p_approval_id
  for update;

  if not found then
    return;
  end if;

  -- Ownership and binding.
  if v_row.session_id <> p_session_id then return; end if;
  if v_row.job_id <> p_job_id then return; end if;

  -- State: must be approved, unexpired, unconsumed, not yet executing.
  if v_row.state <> 'approved' then return; end if;
  if v_row.expires_at <= now() then return; end if;
  if v_row.consumed then return; end if;
  if v_row.execution_state <> 'not_started' then return; end if;

  -- Exact prepared action: params hash must match.
  if v_row.params_hash <> p_params_hash then return; end if;

  -- Claim atomically.
  update public.approvals
  set consumed = true,
      consumed_at = now(),
      execution_state = 'executing',
      execution_id = p_execution_id,
      execution_started_at = now()
  where approval_id = p_approval_id
  returning * into v_row;

  return next v_row;
end;
$$;

-- Record the verified outcome of a claimed execution. Only the holder of
-- the execution_id may record; only from the 'executing' state.
create or replace function public.record_approval_execution_result(
  p_approval_id text,
  p_session_id text,
  p_execution_id text,
  p_succeeded boolean,
  p_evidence text
)
returns setof public.approvals
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.approvals%rowtype;
begin
  select * into v_row
  from public.approvals
  where approval_id = p_approval_id
  for update;

  if not found then return; end if;
  if v_row.session_id <> p_session_id then return; end if;
  if v_row.execution_state <> 'executing' then return; end if;
  if v_row.execution_id <> p_execution_id then return; end if;

  update public.approvals
  set execution_state = case when p_succeeded then 'succeeded' else 'failed' end,
      execution_ended_at = now(),
      execution_evidence = left(coalesce(p_evidence, ''), 500)
  where approval_id = p_approval_id
  returning * into v_row;

  return next v_row;
end;
$$;

-- Crash recovery: stale 'executing' claims become 'unknown' (never
-- blindly retried). Returns the reconciled rows for operator review.
create or replace function public.reconcile_abandoned_approvals(
  p_max_age_seconds int default 300
)
returns setof public.approvals
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  update public.approvals
  set execution_state = 'unknown',
      execution_ended_at = now()
  where execution_state = 'executing'
    and execution_started_at < now() - make_interval(secs => p_max_age_seconds)
  returning *;
end;
$$;
