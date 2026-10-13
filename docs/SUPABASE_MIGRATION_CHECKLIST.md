# ETHIO — Supabase Migration Checklist (development project)

Exact steps to bring a **development** Supabase project to the current
schema. Do NOT run these against a production project without a
separate review. The agent has not applied 004/005 to the live
project; 001–003 were applied earlier (verified 2026-10-12: 11 tables,
16 RLS policies).

## Order and contents

Apply in numeric order, each file once, via the Supabase SQL editor
(paste the whole file, run) or `supabase db push`:

| # | File | Contents |
|---|------|----------|
| 001 | `mobile/backend/migrations/001_initial_schema.sql` | App tables incl. `profiles` (owner = `auth.users.id`) |
| 002 | `mobile/backend/migrations/002_rls_policies.sql` | RLS + owner policies for the 001 tables |
| 003 | `mobile/backend/migrations/003_job_persistence.sql` | `agent_jobs` table + its RLS policy |
| 004 | `mobile/backend/migrations/004_approvals.sql` | `approvals`, `task_events`, atomic claim/record/reconcile functions |
| 005 | `mobile/backend/migrations/005_durable_agent_jobs.sql` | Job state vocabulary fix, `runner`/`updated_at`, profile auto-provision trigger, one-active-job index, job RPCs, privilege lockdown |

005 is written to be safely re-runnable (idempotent). 001–004 are not
fully idempotent — apply each exactly once to a fresh project.

## Why 005 exists (chain review findings)

- 003's `agent_jobs.state` CHECK predates the gateway's
  `waiting_approval` / `waiting_input` states — durable job writes
  would have been rejected by the database. 005 replaces the
  constraint with the gateway's full vocabulary.
- 001 says profiles are "created on first sign-in" but no trigger did
  it; `agent_jobs.owner_id` references `profiles`, so a brand-new
  user's first job insert would have failed its FK. 005 adds the
  standard `on_auth_user_created` trigger.
- The privileged job RPCs revoke EXECUTE from `public`/`anon`/
  `authenticated` and grant it to `service_role` only: the gateway
  (service role, server-side) is the only caller.

## Post-migration verification (SQL editor)

Run these and confirm the expected results:

```sql
-- 1. Tables exist (expect agent_jobs, approvals, task_events, profiles, ...)
select table_name from information_schema.tables
where table_schema = 'public' order by 1;

-- 2. Job RPCs exist (expect 5 rows)
select proname from pg_proc
where proname in ('create_agent_job','transition_agent_job',
  'get_agent_job','list_agent_jobs','reconcile_stale_agent_jobs');

-- 3. Approval RPCs exist (expect 3 rows)
select proname from pg_proc
where proname in ('claim_approval_for_execution',
  'record_approval_execution_result','reconcile_abandoned_approvals');

-- 4. RLS is on for the durable tables (expect 2 rows, both true)
select relname, relrowsecurity from pg_class
where relname in ('agent_jobs','approvals');

-- 5. Profile trigger exists (expect 1 row)
select tgname from pg_trigger where tgname = 'trg_on_auth_user_created';

-- 6. One-active-job index exists (expect 1 row)
select indexname from pg_indexes
where indexname = 'agent_jobs_one_active_per_session';
```

## Gateway configuration for durable mode

Server-side environment only (never in the Flutter app):

```
ETHIO_AUTH_MODE=jwt
ETHIO_TASK_STORE=supabase        # or pg + ETHIO_PG_DSN for local Postgres
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service-role key from Project Settings → API>
SUPABASE_JWT_SECRET=<legacy JWT secret>   # only for HS256 projects;
                                          # ES256 projects need no
                                          # secret: JWKS is fetched
                                          # from SUPABASE_URL
```

The gateway **fails fast at startup** when durable mode is requested
without these (no silent fallback to memory), and durable mode refuses
to run with `ETHIO_AUTH_MODE` unset (dev-key mode).

## Smoke test after configuring (development project only)

1. Sign a test user in (Supabase Auth) and get their access token.
2. `GET /approvals/pending` with `Authorization: Bearer <token>` → 200.
3. Start a worker task against the mock portal; approve the payment;
   confirm rows appear in `agent_jobs` and `approvals`.
4. Restart the gateway; the job (if still waiting) is restored and the
   approval remains decidable; nothing executes without its live
   session (see `api/test_restart_durable.py` for the local proof of
   this exact flow).

## Rollback

All migrations are additive (new tables/columns/functions, one
constraint widened, one trigger added). Rollback = remove the gateway's
durable env flags (reverts to in-memory mode); the tables can stay.
Dropping 005's functions is safe only while durable mode is off.
