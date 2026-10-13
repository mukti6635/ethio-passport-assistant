# ETHIO — Limited Development Pilot Runbook

Purpose: run a small, controlled development pilot of the ETHIO
gateway + Flutter app against the **local mock portal only**. This is
NOT a production launch. Real government portals, real applicant data,
and real payments are out of scope at this stage.

Status gate (all must be true before starting):
- Backend suite green (127 tests) and Flutter `analyze`/`test` green
  (74 tests) — see RELEASE_CHECKLIST.md for the evidence table.
- Migrations 001→005 applied to the DEVELOPMENT Supabase project only.
  **Done for the dev project `ethio` on 2026-10-13** (004+005 applied
  live; all six verification counts confirmed — RELEASE_CHECKLIST.md
  Phase 12 table).
- Pilot users are test accounts created for the pilot, with test data.

## 1. One-time setup (owner, ~15 minutes, no coding)

1. Supabase dashboard → SQL Editor: run, in order,
   `mobile/backend/migrations/004_approvals.sql` then
   `005_durable_agent_jobs.sql` (001–003 are already applied). Then run
   the verification queries in SUPABASE_MIGRATION_CHECKLIST.md — every
   count must match before continuing.
2. Dashboard → Authentication → Users: create one account per pilot
   tester (email + password). Share credentials with each tester
   privately, never in a group chat or document.
3. Note the project URL and the ANON (publishable) key from Project
   Settings → API. Never copy the service-role key into the app, a
   chat, or this runbook.

## 2. Start the pilot stack (developer machine)

Terminal 1 — mock portal:
```bash
cd ~/workspace/ethio-verify
python3 -m http.server 8901 --directory mobile/mock-portal
```

Terminal 2 — gateway (durable, per-user mode). Secrets go in an env
file OUTSIDE the repository — never typed as `export X=...` commands,
which would leave them in your shell history:
```bash
# One time: create the file with an editor, then lock it down.
cat > ~/ethio-pilot.env <<'EOF'
GATEWAY_API_KEY=<any dev value; required to be set, unused for auth in jwt mode>
ETHIO_AUTH_MODE=jwt
ETHIO_TASK_STORE=supabase
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=<service-role key — server only, never in the app>
EOF
chmod 600 ~/ethio-pilot.env

# Each session (the gateway must be started from the api/ directory —
# it imports its sibling modules directly):
cd ~/workspace/ethio-verify/api
set -a; . ~/ethio-pilot.env; set +a
~/workspace/ethio-live-venv/bin/python -m uvicorn gateway:app --port 8000
```
Confirm `curl http://127.0.0.1:8000/health` returns `{"ok": true, ...}`.

Terminal 3 — the app (on a machine with Flutter + a device/emulator):
```bash
cd mobile
flutter run \
  --dart-define=ETHIO_SUPABASE_URL=https://<project>.supabase.co \
  --dart-define=ETHIO_SUPABASE_ANON_KEY=<anon/publishable key> \
  --dart-define=ETHIO_GATEWAY_URL=http://<gateway-host>:8000 \
  --dart-define=ETHIO_SESSION_ID=pilot
```

## 3. Pilot session script (per tester)

**Automated equivalent (developer machine):** `api/live_smoke.py`
runs scenarios S1–S7 against the LIVE dev project — real sign-ins for
pilot-a/pilot-b, profile-trigger check, cross-user isolation,
reject/approve flows with database verification, restart recovery,
and a gateway-log secret scan. It reads every secret from
`~/ethio-pilot.env` (the §2 file, extended with `PILOT_A_EMAIL`,
`PILOT_A_PASSWORD`, `PILOT_B_EMAIL`, `PILOT_B_PASSWORD`, and the typo
guard `PILOT_CONFIRM_PROJECT=<project-ref>`), prints none of them,
and refuses to run against a project whose ref does not match the
confirm value. Validate the file first with
`python live_smoke.py --check-env`, then run it bare. The manual
script below remains the per-tester, in-app version of the same
checks.

1. Open a task → approval hub → sign in with your pilot account.
2. Ask the operator to start a mock task for you (worker runner,
   standard test data). A payment approval appears in the app.
3. Approve it. Expected: the mock task completes; `/tasks/status`
   shows `succeeded` with a result summary.
4. Repeat with a second task and REJECT the approval. Expected: the
   job ends `failed`; the action never executes.
5. Sign out. Expected: approvals disappear; the sign-in form returns.
6. Kill and restart the gateway mid-task on a third run. Expected:
   the waiting job is restored, its approval is still listed, and
   approving fails the job safely (session lost) instead of executing
   anything.

Record any deviation with the time and the job id — do not retry a
deviation repeatedly; report it.

## 4. Stop conditions (halt the pilot immediately if any occur)

- An approval executes without an explicit tap, or executes twice.
- One tester can see or act on another tester's task or approval.
- A token, password, or key appears in any log, screenshot, or chat.
- The gateway records `succeeded` for a task whose result was not
  verified on the mock portal.

## 5. After the pilot

- Collect: tester notes, job ids of deviations, gateway logs.
- Decide: fix-and-repeat, expand the tester group, or stop.
- **Data retention:** the pilot uses test accounts and mock data
  only. When the pilot ends, delete the pilot rows (`agent_jobs`,
  `approvals` for the test users) and the test accounts from the
  development project. Do not let pilot data accumulate, and never
  enter real personal data (names, ID numbers, documents) into the
  pilot system — the standard test data set exists for that reason.
- Nothing about this pilot authorizes a production deployment, a real
  portal integration, or handling real applicant data — those need
  their own review and the owner's explicit approval.

## 6. Troubleshooting

**Gateway exits immediately with "ETHIO_TASK_STORE=... requires
ETHIO_AUTH_MODE=jwt"** — the env file was not loaded in this shell.
Re-run `set -a; . ~/ethio-pilot.env; set +a` in the same terminal.

**Gateway exits with "SUPABASE_URL and SUPABASE_SERVICE_KEY are
required"** — one of the values is empty in `~/ethio-pilot.env`.
Check the file (do NOT paste its contents into a chat or ticket).

**App: every gateway call returns 401** — the user's token is missing
or expired, or the gateway is checking a different project. Confirm
the app was run with the same project's URL/anon key that the gateway
uses in `SUPABASE_URL`, and that the tester actually signed in (the
hub shows their email). On ES256 projects the gateway fetches the
project's JWKS from `SUPABASE_URL` — a wrong URL breaks verification
for every token.

**App: approvals list is empty but a task is waiting** — the task was
probably started under a different account or in devkey mode. Pending
approvals are per-user: sign in as the task's owner. Also check the
gateway terminal — a worker task that lost its browser session
(gateway restarted) fails safely instead of executing.

**409 "session already has an active job"** — one active job per
user+session is enforced. Wait for it to finish, cancel it, or use a
different `ETHIO_SESSION_ID` label for a parallel test.

**Approval shows "expired"** — approvals live 30 minutes. Start a
fresh task; never edit expiry values in the database.

**Job FAILED with "worker session lost (restart)"** — expected safe
behavior after a gateway restart during a waiting approval: the
approval is NOT consumed and nothing executed. Start a new task.

**Flutter: SDK reports version 0.0.0-unknown / pub get fails** — git
ownership guard; run
`git config --global --add safe.directory ~/workspace/flutter-sdk/flutter`
once, then retry.

**Mock portal unreachable (tasks fail at navigation)** — Terminal 1
must be running and the portal URL is
`http://127.0.0.1:8901/index.html`; the worker refuses any other
origin by design.
