-- ETHIO backend — migration 005: durable agent jobs (RPCs, constraints,
-- profile provisioning) — Phase 5.
--
-- Depends on: 001 (profiles), 003 (agent_jobs), 004 (approvals).
-- Apply AFTER 004. Safe to re-run: every statement is idempotent.
--
-- What this fixes/adds:
-- 1. agent_jobs.state CHECK now matches the gateway's actual JobState
--    vocabulary (003 predated waiting_approval / waiting_input).
-- 2. runner + updated_at columns (updated_at drives stale detection).
-- 3. Profile auto-provisioning: 001 says profiles are "created on first
--    sign-in" but no trigger ever did it — a fresh user's first job
--    insert would fail the owner FK. handle_new_user closes that gap.
-- 4. One active job per (owner_id, session_id), enforced by a partial
--    unique index — the database is the arbiter, not app memory.
-- 5. SECURITY DEFINER RPCs for the state machine: create, CAS
--    transition (with the gateway's transition map and the rule that
--    'succeeded' requires a recorded verified result), get, list, and
--    stale-job reconciliation. Execute is revoked from public roles;
--    only the server-side service role may call them.

-- ------------------------------------------------------------- 1. states
alter table public.agent_jobs
  drop constraint if exists agent_jobs_state_check;
alter table public.agent_jobs
  add constraint agent_jobs_state_check
  check (state in ('queued','running','paused','awaiting_human',
                   'waiting_approval','waiting_input',
                   'succeeded','completed','failed','cancelled',
                   'timed_out'));

-- ------------------------------------------------------------ 2. columns
alter table public.agent_jobs
  add column if not exists runner text not null default 'agent';
alter table public.agent_jobs
  add column if not exists updated_at timestamptz not null default now();

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_agent_jobs_updated on public.agent_jobs;
create trigger trg_agent_jobs_updated
  before update on public.agent_jobs
  for each row execute function public.touch_updated_at();

-- ------------------------------------------------- 3. profile provisioning
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id) values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists trg_on_auth_user_created on auth.users;
create trigger trg_on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ------------------------------------------------- 4. one active job/session
create unique index if not exists agent_jobs_one_active_per_session
  on public.agent_jobs (owner_id, session_id)
  where state in ('queued','running','paused','awaiting_human',
                  'waiting_approval','waiting_input');

create index if not exists agent_jobs_updated_idx
  on public.agent_jobs (updated_at)
  where state in ('queued','running');

-- ---------------------------------------------------------------- 5. RPCs
-- Create. Returns the row. A duplicate active job for the session raises
-- unique_violation (SQLSTATE 23505) from the partial index — callers map
-- it to HTTP 409. State starts 'queued'.
create or replace function public.create_agent_job(
  p_id uuid,
  p_owner_id uuid,
  p_session_id text,
  p_goal text,
  p_inputs jsonb,
  p_runner text
)
returns public.agent_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.agent_jobs;
begin
  insert into public.agent_jobs
    (id, owner_id, session_id, goal, inputs, runner, state)
  values
    (p_id, p_owner_id, p_session_id, p_goal,
     coalesce(p_inputs, '{}'::jsonb), coalesce(p_runner, 'agent'),
     'queued')
  returning * into v_row;
  return v_row;
end;
$$;

-- Atomic compare-and-swap transition. The row is updated only if it is
-- still in p_from_state and belongs to p_owner_id. The transition map
-- mirrors the gateway's VALID_TRANSITIONS; anything else raises
-- check_violation. 'succeeded'/'completed' REQUIRE a non-empty verified
-- final_result in the patch — the database refuses to record an
-- unverified completion. p_patch keys (all optional): checkpoint,
-- final_result, error, evidence (jsonb), log_entry (appended to log).
-- Returns the updated row, or no row when the CAS lost / not owner.
create or replace function public.transition_agent_job(
  p_id uuid,
  p_owner_id uuid,
  p_from_state text,
  p_to_state text,
  p_patch jsonb default '{}'::jsonb
)
returns public.agent_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.agent_jobs;
  v_allowed boolean;
begin
  v_allowed := case p_from_state
    when 'queued' then p_to_state in ('running','cancelled','failed')
    when 'running' then p_to_state in ('paused','awaiting_human',
      'waiting_approval','waiting_input','succeeded','completed',
      'failed','cancelled','timed_out')
    when 'paused' then p_to_state in ('running','cancelled','failed')
    when 'awaiting_human' then p_to_state in ('running','cancelled','failed')
    when 'waiting_approval' then p_to_state in ('running','cancelled','failed')
    when 'waiting_input' then p_to_state in ('running','cancelled','failed')
    else false
  end;
  if not v_allowed then
    raise exception 'invalid state transition: % -> %', p_from_state, p_to_state
      using errcode = 'check_violation';
  end if;
  if p_to_state in ('succeeded','completed')
     and coalesce(p_patch ->> 'final_result', '') = '' then
    raise exception 'refusing to mark job % succeeded without a verified final_result', p_id
      using errcode = 'check_violation';
  end if;

  update public.agent_jobs
  set state = p_to_state,
      checkpoint = case when p_patch ? 'checkpoint'
                        then p_patch ->> 'checkpoint' else checkpoint end,
      final_result = case when p_patch ? 'final_result'
                          then p_patch ->> 'final_result' else final_result end,
      error = case when p_patch ? 'error'
                   then p_patch ->> 'error' else error end,
      evidence = case when p_patch ? 'evidence'
                      then p_patch -> 'evidence' else evidence end,
      log = case when p_patch ? 'log_entry'
                 then log || jsonb_build_array(p_patch ->> 'log_entry')
                 else log end,
      started_at = case when p_to_state = 'running' and started_at is null
                        then now() else started_at end,
      ended_at = case when p_to_state in ('succeeded','completed','failed',
                                          'cancelled','timed_out')
                      then now() else ended_at end
  where id = p_id and owner_id = p_owner_id and state = p_from_state
  returning * into v_row;
  return v_row;  -- null when CAS lost or not the owner
end;
$$;

create or replace function public.get_agent_job(
  p_id uuid,
  p_owner_id uuid
)
returns public.agent_jobs
language sql
security definer
set search_path = public
as $$
  select * from public.agent_jobs
  where id = p_id and owner_id = p_owner_id;
$$;

create or replace function public.list_agent_jobs(
  p_owner_id uuid
)
returns setof public.agent_jobs
language sql
security definer
set search_path = public
as $$
  select * from public.agent_jobs
  where owner_id = p_owner_id
  order by created_at asc;
$$;

-- Restart/crash reconciliation. 'running' jobs whose worker stopped
-- reporting (updated_at older than the threshold) become 'failed' with
-- an explicit interruption error — never 'succeeded', never silently
-- resumed: a live browser session does not survive a restart, and any
-- protected action in flight is tracked separately at the approval
-- level (migration 004's reconcile marks those UNKNOWN). 'queued' jobs
-- that never started fail the same way. Human-paced states
-- (waiting_*, paused, awaiting_human) are NOT touched.
create or replace function public.reconcile_stale_agent_jobs(
  p_stale_seconds int
)
returns setof public.agent_jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  update public.agent_jobs
  set state = 'failed',
      error = 'interrupted: worker stopped reporting (restart or crash); '
              'no outcome was verified, nothing was auto-retried',
      ended_at = now()
  where state in ('queued','running')
    and updated_at < now() - make_interval(secs => p_stale_seconds)
  returning *;
end;
$$;

-- ------------------------------------------------------------ privileges
-- These functions are server-side only. Revoke from API roles; grant to
-- the service role where it exists (Supabase). On a bare local Postgres
-- there is no service_role — the block is a no-op and the database
-- superuser (the local dev connection) retains access.
do $$
begin
  revoke all on function public.create_agent_job(uuid, uuid, text, text, jsonb, text)
    from public, anon, authenticated;
  revoke all on function public.transition_agent_job(uuid, uuid, text, text, jsonb)
    from public, anon, authenticated;
  revoke all on function public.get_agent_job(uuid, uuid)
    from public, anon, authenticated;
  revoke all on function public.list_agent_jobs(uuid)
    from public, anon, authenticated;
  revoke all on function public.reconcile_stale_agent_jobs(int)
    from public, anon, authenticated;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    grant execute on function public.create_agent_job(uuid, uuid, text, text, jsonb, text)
      to service_role;
    grant execute on function public.transition_agent_job(uuid, uuid, text, text, jsonb)
      to service_role;
    grant execute on function public.get_agent_job(uuid, uuid) to service_role;
    grant execute on function public.list_agent_jobs(uuid) to service_role;
    grant execute on function public.reconcile_stale_agent_jobs(int) to service_role;
  end if;
exception when undefined_object then
  -- anon/authenticated roles absent (bare local Postgres): nothing to do.
  null;
end;
$$;

-- -------------------------------------------- 6. migration 004 RPC lockdown
-- 004's approval functions are SECURITY DEFINER but shipped without an
-- execute lockdown: Postgres grants EXECUTE to PUBLIC by default, so
-- any API role could have called them directly, bypassing the
-- gateway's job-state binding checks. Lock them down the same way and
-- pin their search_path.
do $$
begin
  revoke all on function public.claim_approval_for_execution(text, text, text, text, text)
    from public, anon, authenticated;
  revoke all on function public.record_approval_execution_result(text, text, text, boolean, text)
    from public, anon, authenticated;
  revoke all on function public.reconcile_abandoned_approvals(int)
    from public, anon, authenticated;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    grant execute on function public.claim_approval_for_execution(text, text, text, text, text)
      to service_role;
    grant execute on function public.record_approval_execution_result(text, text, text, boolean, text)
      to service_role;
    grant execute on function public.reconcile_abandoned_approvals(int)
      to service_role;
  end if;
exception when undefined_object then
  null;
end;
$$;

alter function public.claim_approval_for_execution(text, text, text, text, text)
  set search_path = public;
alter function public.record_approval_execution_result(text, text, text, boolean, text)
  set search_path = public;
alter function public.reconcile_abandoned_approvals(int)
  set search_path = public;
