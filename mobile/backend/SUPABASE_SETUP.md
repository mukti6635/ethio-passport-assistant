# Supabase Setup for ETHIO

**Status:** Migrations ready, project not created. You need a Supabase account.

## What I prepared

Three migrations in `mobile/backend/migrations/`, in order:
1. `001_initial_schema.sql` — 10 tables (profiles, tasks, requirements, documents, extractions, confirmed_fields, issues, checkpoints, browser_sessions, audit_events)
2. `002_rls_policies.sql` — 16 RLS policies (users access only their own rows)
3. `003_job_persistence.sql` — `agent_jobs` table for durable browser-agent jobs, with worker claim protocol

All SQL syntax-checked (balanced parens, semicolons present).

## Steps for you (5 minutes)

1. Go to https://supabase.com/dashboard → **New project**
   - Name: `ethio` (or your choice)
   - Region: closest to your users (e.g., `ap-southeast-1` for Ethiopia/East Africa, or `eu-central-1`)
   - Database password: generate and save in your password manager

2. Wait for the project to provision (~2 min), then go to **SQL Editor**

3. Run the migrations in order — copy-paste each file's contents:
   - `001_initial_schema.sql`
   - `002_rls_policies.sql`
   - `003_job_persistence.sql`

4. Get your credentials from **Settings → API**:
   - Project URL (e.g., `https://xyz.supabase.co`)
   - `anon` public key (for the Flutter app)
   - `service_role` key (for the gateway backend — **never in the app**)

5. Configure:
   - **Flutter app:** Store URL + `anon` key in `flutter_secure_storage` (see `lib/integrations/supabase_adapter.dart`)
   - **Gateway:** Set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` env vars (see `docs/OPERATIONS.md`)

## What I cannot do

- Create the Supabase project (needs your account login)
- Run the migrations (needs the project's SQL editor or credentials)
- Verify the connection (needs the project URL + keys)

Once you've done steps 1–4, tell me and I'll wire the gateway to Supabase and verify the connection.
