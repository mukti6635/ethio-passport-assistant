# ETHIO — Owner Pilot Setup Checklist

Do these steps in order. Everything here uses the **development**
Supabase project and **test accounts only** — no real applicant data,
no real portal. Expected total time: ~30 minutes plus the smoke test.

Never paste passwords, tokens, or the service-role key into chat,
email, or this document. Record only the RESULT of each step
(pass/fail + what you saw), never the secrets themselves.

## Step 1 — Open the correct project
- [x] In the Supabase dashboard, open the project named **ethio**
      (URL contains `zvkkhojqwnsuggeslhga`). If you see a different
      project, stop — do not apply anything there.
      **DONE 2026-10-13** (agent-driven browser; owner signed in
      personally via takeover; a wrong-project detour was caught by
      the ref check before anything ran).

## Step 2 — Apply migration 004, then 005
- [x] SQL Editor → New query → paste ALL of
      `mobile/backend/migrations/004_approvals.sql` → Run.
      Expected: success, no errors. **DONE 2026-10-13 — "Success.
      No rows returned".**
- [x] New query → paste ALL of
      `mobile/backend/migrations/005_durable_agent_jobs.sql` → Run.
      Expected: success, no errors. (005 is safe to re-run; 004 is not.)
      **DONE 2026-10-13 — "Success" (after the standard
      destructive-operations confirmation).**

## Step 3 — Run the six verification queries
Use the queries in `docs/SUPABASE_MIGRATION_CHECKLIST.md`
("Post-migration verification"). All six were executed against the
identical schema locally on 2026-10-13 and matched; your results must
match too:
- [x] Query 1: table list includes `agent_jobs`, `approvals`,
      `task_events`, `profiles`. **Live: 13 tables.**
- [x] Query 2: **5 rows** (job RPCs). **Live: 5.**
- [x] Query 3: **3 rows** (approval RPCs). **Live: 3.**
- [x] Query 4: **2 rows, both `true`** (RLS on). **Live: both true.**
- [x] Query 5: **1 row** (profile trigger). **Live: 1.**
- [x] Query 6: **1 row** (one-active-job index). **Live: 1.**
If any result differs, stop and report ONLY the step number and the
count you got — not any secret values.
**All six confirmed on the LIVE project 2026-10-13, and re-confirmed
read-only in Phase 12 (auth.users = 0, profiles = 0 baseline).**

## Step 4 — Create TWO test users
- [x] Authentication → Users → Add user: `pilot-a@<your-domain>` with
      a password you store in your password manager.
      **DONE 2026-10-13** (owner, via dashboard; Auto Confirm on).
- [x] Add a second user `pilot-b@...` the same way. (Two users are
      required to prove one user cannot see the other's tasks.)
      **DONE 2026-10-13. Profile trigger verified live immediately
      after: auth.users = 2, profiles = 2, join = 2.**

## Step 5 — Run the pilot smoke test
Follow `docs/PILOT_RUNBOOK.md` §2 (start the stack — secrets in
`~/ethio-pilot.env`, never typed as exports) and §3 (session script),
including the reject path and the sign-out step. Then repeat the
script signed in as **pilot-b** and confirm pilot-b sees NONE of
pilot-a's approvals.
**DONE 2026-10-13 via the automated equivalent, `api/live_smoke.py`,
against the LIVE project: 9/9 scenarios passed (see Step 6). The
in-app manual script (sign-out step, session restore in the app)
remains for the on-device pilot.**

## Step 6 — Record results
Fill in and keep this table (results only, no secrets):

| Check | Result (pass/fail) | Notes (job ids, times) |
|---|---|---|
| Migrations applied, queries match | **pass** | Live 2026-10-13: 004+005 applied; six queries match (13 tables, 5+3 RPCs, RLS on, trigger, index) |
| Sign in / sign out (pilot-a) | **pass (API level)** | Live Auth password sign-in for pilot-a AND pilot-b → 200 (2026-10-13). In-app sign-out not yet exercised (no device run) |
| Session restores after app restart | not run | Requires the on-device/in-app pilot |
| Approve → mock task completes | **pass** | Live smoke S5: job succeeded; DB-verified (approval consumed, execution_state=succeeded, agent_jobs row has a verified final_result) |
| Reject → nothing executes, job failed | **pass** | Live smoke S4: job failed; DB-verified (approval rejected, consumed=false, execution_state=not_started) |
| pilot-b cannot see pilot-a's approvals | **pass** | Live smoke S3: B's pending list empty; B read → 404; B decide → 404/409; B execute → 404 |
| Gateway restart → fails safely, no execution | **pass** | Live smoke S6: waiting job restored after restart; approving the dead session failed the job safely; DB-verified approval never consumed |

Send the completed table back (it contains no secrets by design).
Any "fail" stops the pilot until it is reviewed — do not work around
a failed safety check.
