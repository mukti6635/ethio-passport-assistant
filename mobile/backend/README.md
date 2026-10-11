# ETHIO Backend — Supabase

The Flutter app is built against repository interfaces
(`lib/backend/repository.dart`). This folder holds everything needed to
stand up the real backend. The app keeps working with its in-memory store
until you complete the steps below.

## What you need from the user (Muktar)

These steps need a human with a browser — they create real cloud resources:

1. **Create a Supabase project** at https://supabase.com/dashboard
   (free tier is enough to start). Name it `ethio`.
2. **Run the migrations**: open the Supabase SQL editor and paste, in order:
   - `migrations/001_initial_schema.sql`
   - `migrations/002_rls_policies.sql`
   Then run the storage-bucket block commented at the bottom of `002`
   (creates the private `documents` bucket).
3. **Copy two values** from Project Settings → API:
   - Project URL (e.g. `https://xyzcompany.supabase.co`)
   - `anon` public key
4. **Enter them in the app** — never in chat, never in source control.
   The app will read them from a local `.env`-style config you create on
   your machine (see "Wiring the app" below).
5. **Service-role key**: stays in the Supabase dashboard. It is used only
   by server-side code (e.g. a small Edge Function that flips checkpoints
   `pending → authorized`). Never paste it into the app or chat.

## Wiring the app (developer step, after 1–4)

1. Add dependencies: `supabase_flutter`, `flutter_secure_storage`.
2. Create `lib/backend/config.dart` (git-ignored) returning your
   `SupabaseConfig(projectUrl: ..., anonKey: ...)`.
3. Replace the `TaskStore` construction in `lib/app.dart` with
   `SupabaseTaskRepository` / `SupabaseAuthRepository`.
4. The checkpoint-authorization Edge Function (to write):
   verifies the user's explicit action (e.g. signed payment callback),
   then — using the service-role key — updates
   `public.checkpoints` to `authorized`. Clients cannot do this directly;
   RLS forbids it (see `checkpoints_update_cancel_own`).

## Security model (summary)

- RLS on every table; users see only their own rows (verified by policy,
  not by hiding UI).
- `documents` storage bucket is private; paths are namespaced per user.
- Raw OCR (`extractions`) and confirmed data (`confirmed_fields`) are
  separate tables; the agent may only act on confirmed data.
- Checkpoints: clients can request/cancel; only the server authorizes.
- Audit events reject sensitive keys in code (`logEvent` throws).

## Testing the policies

After migrating, run these negative checks in the SQL editor as two
different users (Supabase → Authentication → create two test users,
then use "Impersonate"):
- User A inserts a task; User B `select * from tasks` must return zero rows.
- User B tries `update tasks set stage='done' where id = <A's task>` —
  must affect zero rows.
- User A inserts a checkpoint with `status='authorized'` directly —
  must fail (policy only allows `pending` inserts).
