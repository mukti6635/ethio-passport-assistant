# ETHIO — Release Checklist (development pilot candidate)

Branch: `work/ethio-market-readiness` (local, uncommitted).
Scope of this candidate: **supervised development pilot with mock
data only**. Not a public release.

## Code & tests — PASS (evidence from Phase 10 runs, 2026-10-13)

| Check | Status | Evidence |
|---|---|---|
| Backend test suite | PASS | 121 tests (120 prior + `api/test_pilot_e2e.py`), all passing |
| Live local pilot (runbook script over HTTP) | PASS | `api/test_pilot_e2e.py`: 2 JWT users, durable PG, approve→succeeded, reject→no execution, cross-user isolation, 401s, kill/restart→safe failure, approval never consumed (DB-verified) |
| Flutter analyze | PASS | No issues found |
| Flutter tests | PASS | 74 tests (incl. gateway route-shape tests added Phase 10) |
| Flutter web build (release) | PASS | `flutter build web --release` succeeded |
| Migration chain + checklist queries | PASS | Executed on local PG Phase 9: 6/6 expected values; 005 idempotent, 004 apply-once |
| RPC privilege lockdown | PASS | `test_pg_09`: PUBLIC/anon/authenticated cannot execute; service_role can |

## Phase 11 update (2026-10-13) — Android validation + security

| Check | Status | Evidence |
|---|---|---|
| Backend suite incl. new CORS tests | PASS | **125 tests** (94 batch incl. `api/test_cors.py` 4/4 + 12 E2E + 17 PG + durable restart + pilot) |
| Flutter (Phase 11 re-run) | PASS | analyze clean, 74/74 tests, web release build OK |
| Android toolchain | INSTALLED | JDK 17 + Android SDK (platforms 34/35, build-tools 34/35) at ~/workspace — installed locally without system changes |
| **Defect: release build had NO network permission** | FIXED | INTERNET was only in debug/profile manifests; added to the main manifest (`mobile/android/app/src/main/AndroidManifest.xml`) — without it a release APK cannot reach Supabase or the gateway at all |
| **Defect: no CORS anywhere** | FIXED | Gateway now supports opt-in `ETHIO_CORS_ORIGINS` (exact origins, wildcards refused, default off); the Flutter web pilot can be allowlisted without opening the API. `api/test_cors.py` |
| Cleartext policy | CORRECT | Debug manifest allows cleartext (dev gateway over LAN HTTP); main manifest does not — release stays HTTPS-only |
| Debug APK artifact | **BLOCKED (environment)** | Gradle's daemon↔client loopback TCP is intercepted by this sandbox ("Other TCP connections is turned off for this assistant" banner injected into Java socket reads; daemon dispatch fails). Not a project defect: manifests parse, toolchain + Gradle distribution verified. Build on any normal machine: `flutter build apk --debug` (env per AGENTS.md). No real-device test has occurred |
| Release signing | BLOCKED (owner) | `build.gradle.kts` still signs release with debug keys (template default). A real release needs the owner's keystore — never commit keystore passwords |
| App flow audit (Android lens) | PASS | PKCE auth, secure-storage session, token read fresh per gateway call, SDK-managed refresh, no hardcoded URLs/secrets in `lib/` |

## Phase 12 update (2026-10-13) — live development pilot

| Check | Status | Evidence |
|---|---|---|
| **Live migrations 004+005 applied** | **DONE (live)** | Applied to the dev project `ethio` (`zvkkhojqwnsuggeslhga`) via the dashboard SQL Editor (owner signed in personally; agent pasted + ran). 004: "Success. No rows returned". 005: "Success" after the standard destructive-operations confirmation |
| **Live schema verification** | **PASS (live)** | All six checklist queries on the live DB match: 13 public tables (11 + approvals + task_events), job RPCs = 5, approval RPCs = 3, RLS true on agent_jobs + approvals, profile trigger present, one-active-job index present. Re-confirmed read-only in Phase 12 |
| Live users/profiles baseline | VERIFIED (live) | `auth.users` = 0, `profiles` = 0 on the live project (read-only, 2026-10-13). Pilot users NOT yet created — owner step (passwords are never set by the agent or sent via chat) |
| **Defect: forged/garbled tokens on a JWKS-only deployment returned 500** | **FIXED** | Found by running the gateway against the live project's real JWKS (single ES256 key): no-token 401, but garbage and forged-HS256 tokens → 500, because `_require_jwt` keyed its "misconfigured" branch off the token's attacker-controlled alg. Fix: 500 only when NO verification material is configured at all; all token faults → `AuthError` → 401. Regression: `test_auth_10`/`test_auth_11`; live-config re-check after fix: 401/401/401/401 |
| Live-config auth rejection (smoke scenario 1, partial) | PASS (live config) | Gateway in JWT mode verifying against the live project's JWKS: unauthenticated, garbage-token, and forged-token requests all rejected 401; gateway logs contain no credential material (scanned) |
| Full live smoke (scenarios 2–6) | **PASS (live)** | **`api/live_smoke.py` 9/9 against the LIVE project, 2026-10-13**: live sign-ins, profile trigger (2 rows), S1 401s, S2 task→waiting_approval, S3 cross-user isolation (404s), S4 reject→failed + DB-verified unconsumed, S5 approve→succeeded + DB-verified result, S6 restart→restored, dead-session approval fails safely + never consumed, S7 log secret-scan clean. Locally also proved by `api/test_pilot_e2e.py` |
| **Defect: durable split-brain (durable jobs, in-memory approvals)** | **FIXED** | First live-smoke run failed S4–S6: `build_approval_store()` required `ETHIO_USE_SUPABASE=1` while the task store keyed off `ETHIO_TASK_STORE=supabase`, so approvals silently stayed in memory. Factory now follows the task-store switch (fail-fast retained); regression `test_sb_05`; runner also sets both switches |
| **Defect: Supabase HTTP clients ignored egress proxy / CA bundle** | **FIXED** | `task_store.py` + `auth.py` JWKS fetch hardcoded `trust_env=False` (no proxy, no `SSL_CERT_FILE`) — unreachable from any proxied network. Both now wire the proxy + CA bundle explicitly with a loopback bypass (mirrors the gateway's existing LLM-client pattern); the `requests`-based approval store already honored the environment. Verified live: JWKS fetch returns the project's key, store reads return live rows |
| Backend suite (Phase 12 final re-run) | PASS | **128 tests** (127 + `test_sb_05`): gateway 68, worker_api 8, auth 11, supabase store 5, restart 1, CORS 4, E2E 12, PG 17, durable restart 1, pilot 1 |
| Flutter (Phase 12 re-run) | PASS | analyze clean, 74/74 tests, web release build OK |
| Android (Phase 12 recheck) | STILL BLOCKED (environment) | Toolchain intact (JDK 17, platforms 34/35); the Java loopback interception is still active (minimal echo test still receives the sandbox banner instead of its own bytes). The banner indicates this is a user-controlled Muse Permissions setting — owner's choice, not something the agent changes. No APK built, no device test claimed |

## Phase 13 update (2026-10-13) — app-layer validation

Scope: Flutter sign-in / sign-out / session restoration / token refresh / gateway requests / approval-rejection UI. No live resources touched.

| Item | Result | Evidence |
|---|---|---|
| Auth/session audit | PASS (2 latent defects found + fixed) | Sign-in trims email, maps SDK errors to presentable messages, never includes tokens in errors. Session persists via `SecureSessionStorage` (platform keystore). Gateway credential resolved FRESH per call from `currentSession`; auth-state stream triggers hub re-resolve on sign-in/out/refresh; sign-out clears the approval list state and re-shows the sign-in form |
| Defect: captured-session token staleness (latent) | FIXED | `_SupabaseSession.accessToken` read the Session object captured at sign-in; gotrue replaces that object on refresh, so any holder of an `AuthSession` would serve the pre-refresh token. It now reads through the SDK's current session (the hub's live path already used the fresh provider; this closes the trap for all callers) |
| Defect: approval card decided with a snapshot token | FIXED | The card received the token at list-fetch time; after an hourly rotation a decision could 401 and Retry reused the stale key. Card now accepts an optional `configResolver` and resolves the CURRENT config at tap time (hub passes `GatewaySessionConfig.currentConfig`); a resolver reporting signed-out sends nothing and shows an honest error. Snapshot props retained for compatibility |
| Stale doc comment | FIXED | `supabase_adapter.dart` header claimed the adapter "has NOT been compiled yet" — untrue since Phase 8; corrected |
| App-layer tests | PASS — **80/80** (74 + 6 new) | New coverage in `test/gateway_auth_test.dart`: tap Approve posts `approve=true` to `/approvals/{id}/decide` and shows the server-verified state; tap Reject posts `approve=false`; a failed decision shows the error and Retry repeats the SAME direction (never flips a rejection); the fresh resolver's token wins over the snapshot at tap time; signed-out resolver sends zero requests; `SecureSessionStorage` persist → read-back → remove round-trip (the sign-out path) against a fake platform storage |
| flutter analyze | PASS | No issues |
| Web release build | PASS | `flutter build web --release` ✓ Built build/web |
| Android debug APK | **STILL BLOCKED (environment — unchanged)** | Toolchain verified intact (JDK 17 + Android SDK under ~/workspace). Minimal Java loopback echo re-test (2026-10-13): the payload never arrived — the sandbox's interception of non-tracked loopback TCP is still active, which kills Gradle daemon↔client communication. Per the runtime's own banner this is governed by **Muse Settings → Permissions → Direct network protocols → "Other TCP connections"**. The owner set it to **Ask** on 2026-10-13 and the loopback test was retried three times (30s / 100s / 170s, the last with the approval queue monitored live): the refusal banner is gone but the connection now *hangs* — no per-destination approval is ever generated for a raw JVM socket, so Gradle remains blocked in this sandbox. The agent does not bypass it. No APK produced; no device test claimed — build on a normal computer (instructions below) |

### Outstanding device-test requirements (owner, on a real device or normal machine)
1. Install the debug APK (build instructions below) or run `flutter run` on a connected device.
2. Sign in as pilot-a → open the approval hub → confirm the pending list loads.
3. Create a mock task (runbook), approve from the device → task completes; repeat and reject → task fails, nothing executes.
4. Sign out → confirm the approval section returns to the sign-in form and no approvals are visible.
5. Kill and relaunch the app → confirm the session restores WITHOUT signing in again (secure-storage restore).
6. Leave the hub open across a token rotation (~1 hour) → decide an approval → it must succeed (Phase 13 resolver fix) — or force rotation by restarting the gateway's token lifetime in the dev project.

### Build the debug APK on a normal computer (no sandbox restrictions)
```bash
# Prerequisites: Flutter SDK 3.27.x and Android SDK (platform 34+) installed
cd ethio-verify/mobile
flutter pub get
flutter build apk --debug \
  --dart-define=ETHIO_SUPABASE_URL=https://zvkkhojqwnsuggeslhga.supabase.co \
  --dart-define=ETHIO_SUPABASE_ANON_KEY=<anon/publishable key from the dashboard> \
  --dart-define=ETHIO_GATEWAY_URL=<gateway URL reachable from the device> \
  --dart-define=ETHIO_GATEWAY_AUTH_MODE=jwt
# Output: build/app/outputs/flutter-apk/app-debug.apk
```
(The anon/publishable key is a public client key, safe in the app; the service-role key must NEVER be passed here.)

## Defects found in Phase 10 and fixed

| Defect | Fix |
|---|---|
| Dart `GatewayTaskClient` used `/tasks/{id}` + `/tasks/{id}/cancel` — routes the gateway does not serve (mocked tests could not see it) | Corrected to `/tasks/status/{id}` + `/tasks/cancel/{id}`; Dart tests now assert the exact paths; the live pilot test exercises the real routes |
| Runbook + DEVELOPMENT.md + OPERATIONS.md showed `uvicorn api.gateway:app` from the repo root → ModuleNotFoundError | All docs now use `gateway:app` from inside `api/` |
| Root `.env.example` was the upstream browser-use template (wrong product) | Replaced with an ETHIO gateway template, placeholders only |
| Runbook put secrets in shell history (inline `export`) | Env-file pattern (Phase 9), retained |

## Hygiene — PASS

| Check | Status | Evidence |
|---|---|---|
| Secrets in the change set | PASS | Pattern scan over diff + untracked files: no real keys/tokens (only labeled local test fixtures) |
| `.env` files ignored | PASS | Root `.gitignore`: `.env`, `.env.*`, `*.env` ignored; `.env.example` templates excepted; `ethio-pilot.env` ignored |
| Flutter build artifacts ignored | PASS | `mobile/.gitignore` incl. `.flutter-plugins` (Phase 8) |
| No service-role key in the app | PASS | App config is dart-defines (URL + publishable anon key only); gateway client sends the user's own token |
| Government disclaimer in app | PASS | "Independent assistant. Not affiliated with any government agency." + prototype notices in `mobile/lib/l10n/strings.dart` |

## Accompanies the application (must be committed together)

- Code: `api/` (gateway, approvals, auth, worker, orchestrator,
  persistence, task_store), `mobile/lib/` (incl. backend/gateway
  client + app services), `mobile/test/gateway_auth_test.dart`.
- Migrations: `mobile/backend/migrations/004_approvals.sql`,
  `005_durable_agent_jobs.sql` (001–003 already on the dev project).
- Config templates: `.env.example`, `mobile/.env.example`,
  `mobile/pubspec.lock` (updated resolution).
- Docs: `DEPLOYMENT_READINESS.md`, `DEVELOPMENT.md`, `OPERATIONS.md`,
  `SUPABASE_MIGRATION_CHECKLIST.md`, `PILOT_RUNBOOK.md`,
  `OWNER_PILOT_CHECKLIST.md`, this checklist.

## NOT verified — FAIL/BLOCKED for anything beyond the pilot

| Item | Status |
|---|---|
| Live dev Supabase: migrations 004+005 applied | DONE 2026-10-13 — applied + six verification queries confirmed live (Phase 12 table) |
| Live Supabase Auth sign-in → gateway | DONE 2026-10-13 — live sign-ins + full gateway smoke PASS 9/9 (Phase 12 table). Remaining: the in-app/on-device run (sign-out, session restore in the app) |
| On-device run (Android) | BLOCKED — sandbox cannot complete a Gradle build (see Phase 11 table); build the debug APK on a normal machine, then run the pilot on a device |
| Local debug APK | NOT PRODUCED — environment-blocked (Phase 11 table); build command documented |
| Multi-worker deployment | NOT BUILT — single-worker assumption documented |
| Capacity (any applicants/day figure) | NOT VERIFIED — no claim made |
| Backups/monitoring for a hosted deployment | NOT APPLICABLE yet — no hosting chosen; pilot runs on a dev machine |

## Owner results (fill in after dashboard verification)

Use the table in `docs/OWNER_PILOT_CHECKLIST.md` step 6 and return
it. The pilot is accepted only when every row passes.
