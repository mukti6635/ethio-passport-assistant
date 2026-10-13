# ETHIO Development Guide

Reproducible local setup for the gateway, mock portal, worker, tests,
and mobile app. Everything here uses the **mock portal only** — never
point any of this at the real Ethiopian passport portal.

## 1. Start the pieces

```bash
cd ~/workspace/ethio-verify

# Mock portal (static, port 8901)
python3 -m http.server 8901 --directory mobile/mock-portal &

# Gateway API (port 8000) — started from inside api/ (see below)
cd ~/workspace/ethio-verify/api
GATEWAY_API_KEY=dev-key \
  ~/workspace/ethio-live-venv/bin/python -m uvicorn gateway:app \
  --port 8000
# NOTE: the gateway imports its sibling modules directly, so run it
# as `gateway:app` with cwd=api/. `api.gateway:app` from the repo
# root fails with ModuleNotFoundError (verified Phase 10).
```

Health check: `curl http://127.0.0.1:8000/health` → `{"ok": true}`.

## 2. Run a worker task by hand

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Authorization: Bearer dev-key" -H "X-Ethio-Session: demo-1" \
  -H "Content-Type: application/json" \
  -d '{"goal":"fill mock form","runner":"worker",
       "inputs":{"fullName":"Test User","dob":"1990-01-01",
       "phone":"0911123456","nationalId":"12345678",
       "serviceType":"idcard","birthPlace":"Addis Ababa"}}'
# → {"job_id": "..."}; poll GET /tasks/status/<id>
# When state = waiting_approval:
curl http://127.0.0.1:8000/approvals/pending \
  -H "Authorization: Bearer dev-key" -H "X-Ethio-Session: demo-1"
curl -X POST http://127.0.0.1:8000/approvals/<approval_id>/decide \
  -H "Authorization: Bearer dev-key" -H "X-Ethio-Session: demo-1" \
  -H "Content-Type: application/json" -d '{"approve": true}'
```

## 3. Test suites

Use the live venv python throughout.

```bash
V=~/workspace/ethio-live-venv/bin/python
$V -m pytest api/test_gateway.py -q      # 68: gateway + approvals + SQL contracts
$V -m pytest api/test_worker_api.py -q   # 8: /tasks worker lifecycle + recovery
$V -m pytest api/test_e2e.py -q          # 12: real-browser mock E2E (~2 min)
$V -m pytest api/test_restart.py -q      # 1: memory-mode restart behavior
$V -m pytest api/test_auth.py -q         # 9: Phase 5 JWT auth + isolation
$V -m pytest api/test_supabase_task_store.py -q  # 4: Supabase task-store transport contract
```

PostgreSQL verification (real local Postgres via pgserver — no
Supabase account needed). NOTE: PostgreSQL refuses to run as root, so
these run as the unprivileged `pgtest` user; /tmp is a small tmpfs —
if Postgres reports "no space left", delete stale `/tmp/ethio-pg-*`
data dirs.

```bash
su - pgtest -c '~/workspace/ethio-pg-venv/bin/python -m pytest \
  api/test_postgres.py api/test_task_store_pg.py -q'   # 7 + 9 tests
su - pgtest -c '~/workspace/ethio-live-venv/bin/python -m pytest \
  api/test_restart_durable.py -q'  # 1: durable-mode restart recovery
```

Load test (mock portal, worker jobs):

```bash
$V api/load_test.py 3 6     # concurrency levels; prints JSON results
```

## 4. Environment variables

| Variable | Meaning |
|---|---|
| `GATEWAY_API_KEY` | Devkey auth mode only. Shared API key for all gateway endpoints except `/health`. |
| `ETHIO_AUTH_MODE` | `devkey` (default, local dev only) or `jwt` (pilot: Supabase access tokens verified by the gateway; owner = token `sub`). |
| `SUPABASE_JWT_SECRET` | HS256 JWT verification (legacy Supabase projects). ES256 projects verify via JWKS fetched from `SUPABASE_URL` — no secret needed. |
| `ETHIO_JWT_JWKS_JSON` | Optional inline JWKS (self-hosted/local tests). Operator-set trust root, server-side only. |
| `ETHIO_TASK_STORE` | `memory` (default), `pg` (local Postgres via `ETHIO_PG_DSN`), or `supabase`. Durable modes require `ETHIO_AUTH_MODE=jwt` and fail fast otherwise. |
| `ETHIO_PG_DSN` | psycopg2 DSN for `pg` durable mode (tasks + approvals in one local Postgres). |
| `GROQ_API_KEY` | Groq key (default LLM provider) or via Secure Vault `custom.groq`. |
| `GEMINI_API_KEY` | Gemini key; provider selected explicitly, never a silent fallback. |
| `ETHIO_LLM_PROVIDER` | `groq` (default) or `gemini`. |
| `ETHIO_MOCK_PORTAL_URL` | Worker runner target (default `http://127.0.0.1:8901/index.html`). Origin allowlist is enforced in code regardless. |
| `ETHIO_USE_SUPABASE` | `1` enables the Supabase approval store (implies the Supabase task store too). Fails fast without the two below. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Durable store config. Service key is server-side only — never in the app/APK. |
| `ETHIO_MAX_CONCURRENT_JOBS` | Default 10. Each worker job holds a Chromium. |
| `ETHIO_RATE_LIMIT_TASKS`, `ETHIO_RATE_LIMIT_WINDOW` | Task creation rate limit per session (default 20 / 3600s). |
| `ETHIO_JOB_TIMEOUT_S` | Agent-runner job timeout (default 1200). |

## 5. Database migrations

Order: `mobile/backend/migrations/001 → 002 → 003 → 004 → 005`, in
the Supabase SQL editor. Migration 004 adds the approvals/task_events
tables **and** the atomic RPCs the durable stores depend on — the
stores raise a clear error if they are missing. Migration 005 adds
the durable job RPCs, fixes the `agent_jobs` state vocabulary, adds
profile auto-provisioning, and locks down RPC privileges. Full
step-by-step with post-migration verification queries:
`docs/SUPABASE_MIGRATION_CHECKLIST.md`. Local verification of the SQL:
`api/test_postgres.py` + `api/test_task_store_pg.py` (apply
001+003+004+005 to a throwaway Postgres with `api/local_pg_shims.sql`
stubbing Supabase's `auth` schema).

## 6. Flutter app — authentication & gateway (Phase 7)

Verified in the sandbox (Phase 8): a Flutter SDK (3.27.4) is
installed at `~/workspace/flutter-sdk/flutter` — prepend its `bin` to
PATH. (If Flutter reports version 0.0.0-unknown, run
`git config --global --add safe.directory ~/workspace/flutter-sdk/flutter`
once — the sandbox's git ownership guard otherwise hides the version.)

```bash
export PATH=$HOME/workspace/flutter-sdk/flutter/bin:$PATH
cd mobile
flutter pub get              # resolves supabase_flutter 2.15.4 (lockfile tracked)
flutter analyze              # → No issues found (2026-10-13)
flutter test                 # → 73/73 passed, incl. gateway_auth_test.dart
                             # (MOCKED tests: fake tokens + MockClient,
                             # no network, no live Supabase)
flutter build web --release  # → succeeded (full app compiles + links)
flutter run                  # on device/emulator, with defines below
```

What exists now:
- `backend/supabase_adapter.dart` — real Supabase auth via
  supabase_flutter: email sign-in/sign-up/sign-out, session
  restoration, auth-state stream, SDK-managed token refresh; the
  session persists in flutter_secure_storage (gotrue `LocalStorage`
  adapter). Errors surface as `EthioAuthException`; no token is ever
  put in an error or a log.
- `backend/gateway_client.dart` — `GatewaySessionConfig` resolves a
  FRESH gateway credential per call (the signed-in user's access
  token in jwt mode; the dev key in devkey mode) and
  `GatewayTaskClient` calls `/tasks` (start/poll/cancel) and
  `/approvals/*`. The client never sends an owner id: the gateway
  derives ownership from the verified token.
- `backend/app_services.dart` + `main.dart` — startup wiring. The
  approval hub shows a sign-in form in jwt mode when signed out, the
  signed-in email + sign-out when signed in, and re-fetches approvals
  whenever the auth state changes. Decided approvals render their
  server-verified state with no action buttons.

Configuration (all `--dart-define`, nothing hard-coded):
- `ETHIO_SUPABASE_URL`, `ETHIO_SUPABASE_ANON_KEY` — Supabase dashboard
  → Project Settings → API. The anon key is publishable; the
  service-role key must NEVER be in the app.
- `ETHIO_GATEWAY_URL` — gateway base URL.
- `ETHIO_GATEWAY_AUTH_MODE` — `jwt` (default when a user session can
  exist) or `devkey`.
- `ETHIO_GATEWAY_CREDENTIAL` — devkey mode only: the gateway's
  `GATEWAY_API_KEY` (development only).
- `ETHIO_SESSION_ID` — client session label (not an identity).

Devkey quick check (no Supabase):

```bash
flutter run \
  --dart-define=ETHIO_GATEWAY_URL=http://127.0.0.1:8000 \
  --dart-define=ETHIO_GATEWAY_AUTH_MODE=devkey \
  --dart-define=ETHIO_GATEWAY_CREDENTIAL=dev-key \
  --dart-define=ETHIO_SESSION_ID=demo-1
```

Mock-portal smoke test (jwt mode):
1. Apply migrations 001→005 to the dev project (see
   SUPABASE_MIGRATION_CHECKLIST.md) and create a test user in the
   Supabase dashboard (Authentication → Users).
2. Start the gateway in durable jwt mode (§2 env) and the mock
   portal: `python3 -m http.server 8901 --directory mobile/mock-portal`.
3. Run the app with the Supabase + gateway defines (no
   ETHIO_GATEWAY_CREDENTIAL).
4. Open a task's approval hub and sign in with the test user. Start a
   worker task so a payment approval appears; approve it in the app
   and confirm the job completes (check `/tasks/status`). Repeat and
   reject: the job must end `failed` and the action must never run.
5. Sign out: the section returns to the sign-in form. Restart the app
   while signed in: the session must restore from secure storage.

## 7. Troubleshooting

- **Tests suddenly very slow / timeouts:** leaked Chromium from a
  killed test run exhausts memory. Clean up:
  `pkill -f ms-playwright` (sandbox only), then re-run.
- **`httpx.InvalidURL: Invalid port ':1]'`:** this sandbox's `no_proxy`
  contains bracketed IPv6 entries httpx cannot parse. Use
  `httpx.Client(trust_env=False)` for loopback clients, or sanitize
  `NO_PROXY` in the client process (see `api/benchmark_drivers.py`).
- **E2E event-loop errors:** Playwright async objects are bound to
  their creating loop — `api/test_e2e.py` uses one persistent loop;
  don't wrap calls in per-call `asyncio.run()`.
- **Payment never verifies in the mock:** the mock's `#pay-ok` flow
  needs `id="pay-receipt"` on the receipt span (fixed 2026-10-13);
  if the mock is regenerated, keep that id.
- **Stagehand experiments:** use a throwaway venv
  (`pip install stagehand==4.2.1`) and Playwright's *full* Chromium
  via `executable_path` (the headless shell lacks extension support).
- **Postgres "No space left on device" (pgserver suites):** /tmp is a
  512MB tmpfs and every pgserver data dir is ~39MB. Delete stale
  `/tmp/ethio-pg-*` dirs. The fixtures remove their dirs on teardown,
  but killed runs leak them.
- **Postgres refuses to start as root:** run the PG suites as the
  `pgtest` user (see §3). The gateway/worker suites run as any user.
