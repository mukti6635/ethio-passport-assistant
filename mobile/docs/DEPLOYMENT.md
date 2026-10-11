# ETHIO — Deployment Guide

Separate deployables. Separate environments. Nothing shares secrets.

## Components

| # | Component | What it is | Where it runs |
|---|-----------|------------|---------------|
| 1 | Flutter client | This repo (`lib/`) | Play Store (APK/AAB), web hosting |
| 2 | Backend API + DB | Supabase project (`backend/migrations/`) | supabase.com (managed) |
| 3 | AI provider | Pluggable (`lib/agent/` consumes an interface) | Provider API (e.g. Gemini) |
| 4 | Browser workers | Browser Use WebUI + adapter (`lib/integrations/`) | Your server (Docker) |
| 5 | Mock portal | `mock-portal/` | Local only — never deployed |

## Environments

- **dev**: local Flutter run, in-memory store, mock browser simulator,
  mock portal. No real credentials anywhere.
- **staging**: Supabase free-tier project `ethio-staging`, test users,
  browser workers pointed at the **mock portal only**.
- **prod**: Supabase project `ethio-prod`, real users, browser workers
  pointed at real portals with human checkpoints enforced.

Distinguish them with a `--dart-define=ETHIO_ENV=staging|prod` flag
read at startup (default `dev`). Never let `dev` config reach prod.

## Environment variables (no real secrets here — examples only)

```bash
# Supabase (from dashboard → Project Settings → API)
SUPABASE_URL=https://xyzcompany.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOi...            # safe for client (RLS enforced)

# Server-side ONLY (never in the app, never in git)
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...    # Edge Functions / backend only

# AI provider (server-side; the app never holds this key)
AI_PROVIDER=gemini
AI_API_KEY=...                             # secret manager / .env on server

# Browser workers
BROWSER_WEBUI_URL=http://localhost:7788    # your WebUI host
BROWSER_API_KEY=...                        # secret manager / .env on server
```

Enter secrets via the hosting provider's secret manager or a local `.env`
file that is git-ignored. Never paste secrets into chat.

## Deploy steps (first small release)

1. **Backend**: create Supabase project, run `backend/migrations/*.sql`,
   create the private `documents` bucket, run the RLS negative tests in
   `backend/README.md`.
2. **Client (Android)**: `flutter build appbundle --release
   --dart-define=ETHIO_ENV=prod`; upload the AAB to the Play Console
   (internal testing track first).
3. **Client (web)**: `flutter build web --release
   --dart-define=ETHIO_ENV=prod`; host `build/web/` on any static host.
4. **Browser workers**: deploy Browser Use WebUI per its own docs
   (Docker), put the adapter config behind your API, keep keys server-side.
   Start with 1 worker; add more only after measuring.
5. **Smoke test**: run through one full task on staging with the mock
   portal before pointing anything at a real portal.

## Scaling notes (toward ~2,000 applicants/day)

- Put browser tasks on a queue (one task = one queued job); workers pull
  jobs, never direct user→worker calls.
- Isolate browser sessions: one browser profile per task, wiped afterwards.
- Cap concurrent sessions per worker (start with 2–4, measure, then raise).
- Health-check workers; auto-restart unhealthy ones; requeue their jobs.
- Track per-task latency, failure rate, and AI-token cost; alert on spikes.
- Overload policy: queue with a visible position beats failing fast.
- Do NOT claim 2,000/day capacity until a load test with representative
  tasks proves it. Measure first.

## Backup & rollback

- Supabase: enable daily backups (dashboard → Database → Backups);
  test restore on staging quarterly.
- Client: every release is a git tag; rolling back = republishing the
  previous AAB/web build.
- Migrations are versioned (`001_`, `002_`, …); each new migration must
  include its own rollback notes at the top of the file.

## Pre-pilot checklist (Definition of Done)

- [ ] `flutter analyze` clean, all tests pass (run, don't assume).
- [ ] RLS negative tests pass on staging.
- [ ] Checkpoint bypass tests pass (agent cannot self-authorize).
- [ ] No secret in the repo (`git grep -i "service_role\|api_key"` empty).
- [ ] Privacy notices visible before upload/payment/legal screens.
- [ ] Mock-portal e2e passes, including network-failure recovery.
- [ ] App never claims a submission/payment/appointment without evidence.
- [ ] Known limitations documented (see README "Prototype boundaries").
