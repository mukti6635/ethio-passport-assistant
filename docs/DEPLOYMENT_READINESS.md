# ETHIO Deployment Readiness

**Status:** NOT PRODUCTION-READY (development release candidate)
**Last verified:** 2026-10-13

## What is verified working (with evidence)

| Area | Evidence |
|---|---|
| Approval gate (prepare/decide/consume, exactly-once) | `api/test_gateway.py` — 68 tests |
| WorkerLoop via real `/tasks` API (runner="worker") | `api/test_worker_api.py` — 8 tests |
| Real-browser E2E vs mock portal (12 scenarios) | `api/test_e2e.py` — 12 tests |
| Migrations 001+003+004 apply on real PostgreSQL | `api/test_postgres.py` — 7 tests (local pgserver) |
| Atomic claim RPC: 10-way concurrent race → 1 winner | test_postgres.py::test_pg_03 |
| RLS owner isolation (restricted role sees only own rows) | test_postgres.py::test_pg_02 |
| API restart behavior, memory mode (jobs honestly 404, no phantom execution) | `api/test_restart.py` — 1 test |
| **Durable tasks**: create/read/CAS transitions/duplicate guard on real PostgreSQL (migration 005) | `api/test_task_store_pg.py` — 10 tests (incl. RPC privilege lockdown with Supabase-style roles) |
| **Per-user auth**: Supabase JWT verification (HS256 + ES256/JWKS), rejection paths, cross-user isolation | `api/test_auth.py` — 9 tests |
| **Durable restart**: waiting job + pending approval restored after kill/restart; approval never executes without its live session; stale running job reconciled to FAILED | `api/test_restart_durable.py` — 1 test (real uvicorn + real PG) |
| Supabase task-store transport contract (RPC shapes, error mapping) | `api/test_supabase_task_store.py` — 4 tests (local stub) |
| Load: 3 and 6 concurrent worker jobs, 0 failures | `api/load_test.py` (see below) |

Total automated tests: **120** (68 + 8 + 12 + 7 + 10 + 9 + 4 + 1 + 1), all passing 2026-10-13 (Phase 6 audit re-run).

## Architecture state

- **Task runners:** `agent` (browser-use, default) and `worker`
  (WorkerLoop + Playwright vs the mock portal, approval-controlled).
- **Approval storage:** in-memory by default. Durable modes:
  `ETHIO_USE_SUPABASE=1` (+ URL/service key) → `SupabaseApprovalStore`;
  `ETHIO_TASK_STORE=pg` (+ `ETHIO_PG_DSN`) → `PgApprovalStore` against
  a local Postgres. Claim/record/reconcile call the migration-004
  Postgres RPCs (atomic, row-locked). All stores share the gateway's
  prepare/decide/claim contract. Factories **fail fast** on missing
  configuration — never a silent fallback to memory.
- **Job state:** mirrored to a durable task store (migration 005's
  `agent_jobs` RPCs: CAS transitions, one-active-job-per-session
  enforced by the database, succeeded-requires-verified-result at the
  SQL level). On startup, waiting jobs are restored with their pending
  approvals; interrupted jobs reconcile to FAILED; stale EXECUTING
  claims become UNKNOWN. Live browser sessions do NOT survive restart
  (by design): a restored job's approval can be decided, but executing
  it fails the job safely instead of dispatching anything. Memory
  mode keeps the honest old behavior (jobs 404 after restart).
- **Auth:** `ETHIO_AUTH_MODE=devkey` (default; shared key + session
  header, local development only) or `jwt` (pilot): the gateway
  verifies Supabase access tokens itself (HS256 secret or ES256 via
  JWKS), derives ownership from `sub`, and ignores client-supplied
  owner ids. Durable task modes refuse to start in devkey mode.

## Load test (sandbox, 2026-10-13)

Mock portal, worker jobs, this 8 GB sandbox:

| Concurrent jobs | Succeeded | Wall | Jobs/min | Median latency |
|---|---|---|---|---|
| 3 | 3 | 9.5s | 19.0 | 9.2s |
| 6 | 6 | 10.1s | 35.6 | 9.7s |

Throughput scaled near-linearly 3→6. The dominant production
constraint is not CPU: a worker job **holds a Chromium browser while
waiting for human approval**, so required concurrency ≈ arrival rate
× approval dwell time. 5,000 applicants/day is **not verified** —
it needs production-class hardware, the real portal's latency, and
measured approval dwell times.

## Known limitations

1. **Browser sessions are not durable** — a restart restores waiting
   jobs and approvals, but approval execution needs the live session;
   restored jobs fail safely on approve (operator re-runs the task).
2. **Single-worker assumption** — in-memory rate limiting is
   per-process; durable job/approval state is shared, but a
   multi-worker deployment still needs shared rate limiting and a
   worker-claim protocol for the live runners.
3. **Groq multi-step planning** via the browser-use agent runner is
   unreliable (root cause: model planning gap, 2026-10-12). The
   worker runner's deterministic policy is the reliable path for the
   mock workflow.
4. **Flutter app not compiled/verified in this environment** — no
   Flutter SDK available. The gateway config is now wired in
   routes.dart from `--dart-define` values; runtime sourcing of the
   user's Supabase token inside the app is not yet implemented.
   See DEVELOPMENT.md §6 for exact steps.
5. **Migrations 004+005 not applied to the live Supabase project** —
   the SQL, RPCs, stores, and restart flow are verified against a
   real local PostgreSQL only. The Supabase (PostgREST) task store is
   covered by a transport-contract stub test, not a live project.
6. **Live Supabase Auth not exercised** — JWT verification is proven
   with locally minted HS256/ES256 tokens. A real project's token
   flow (sign-in → token → gateway) still needs one live pass on a
   development project.

## Stagehand

Evaluated 2026-10-13 (v4.2.1): **rejected** as default. ~2× slower on
the deterministic path, ~12× slower startup, BYO-LLM callback
contract brittle, and ETHIO's gap is planning, not element location.
Isolated adapter kept at `api/stagehand_driver.py` (inert unless the
package is installed and explicitly used). Playwright remains default.

## Pre-pilot checklist

- [ ] Apply migrations 004+005 to the development Supabase project
      (see `docs/SUPABASE_MIGRATION_CHECKLIST.md`)
- [ ] Enable durable mode (`ETHIO_TASK_STORE=supabase`,
      `ETHIO_AUTH_MODE=jwt`) and run the checklist smoke test live
- [x] Implement `agent_jobs` persistence + restart rehydration
- [x] Per-user auth tokens (Supabase JWT; devkey is local-dev only)
- [ ] Flutter analyze + on-device approval flow test (needs SDK)
- [ ] Runtime token sourcing in the Flutter app (auth session → config)
- [ ] Load test on production-class hardware with approval dwell
- [ ] Third-party security audit
