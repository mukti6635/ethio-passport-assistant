-- ETHIO backend — migration 002: row-level security
-- Least privilege: every table is locked down; users can only touch their
-- own rows. The service role (backend only, never in the app) bypasses RLS.

-- Enable RLS on all user tables.
alter table public.profiles           enable row level security;
alter table public.tasks              enable row level security;
alter table public.requirements       enable row level security;
alter table public.documents          enable row level security;
alter table public.extractions        enable row level security;
alter table public.confirmed_fields   enable row level security;
alter table public.issues             enable row level security;
alter table public.checkpoints        enable row level security;
alter table public.browser_sessions   enable row level security;
alter table public.audit_events       enable row level security;

-- --------------------------------------------------------------- profiles
-- Users read/update only their own profile.
create policy "profiles_select_own"
  on public.profiles for select
  using (auth.uid() = id);
create policy "profiles_update_own"
  on public.profiles for update
  using (auth.uid() = id);

-- ------------------------------------------------------------------ tasks
create policy "tasks_all_own"
  on public.tasks for all
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- ------------------------------------------------------------ requirements
-- Reachable only through a task the user owns.
create policy "requirements_all_via_task"
  on public.requirements for all
  using (exists (
    select 1 from public.tasks t
    where t.id = requirements.task_id and t.owner_id = auth.uid()))
  with check (exists (
    select 1 from public.tasks t
    where t.id = requirements.task_id and t.owner_id = auth.uid()));

-- --------------------------------------------------------------- documents
create policy "documents_all_via_task"
  on public.documents for all
  using (exists (
    select 1 from public.tasks t
    where t.id = documents.task_id and t.owner_id = auth.uid()))
  with check (exists (
    select 1 from public.tasks t
    where t.id = documents.task_id and t.owner_id = auth.uid()));

-- -------------------------------------------------------------- extractions
create policy "extractions_all_via_task"
  on public.extractions for all
  using (exists (
    select 1 from public.tasks t
    where t.id = extractions.task_id and t.owner_id = auth.uid()))
  with check (exists (
    select 1 from public.tasks t
    where t.id = extractions.task_id and t.owner_id = auth.uid()));

-- ---------------------------------------------------------- confirmed_fields
create policy "confirmed_fields_all_via_task"
  on public.confirmed_fields for all
  using (exists (
    select 1 from public.tasks t
    where t.id = confirmed_fields.task_id and t.owner_id = auth.uid()))
  with check (exists (
    select 1 from public.tasks t
    where t.id = confirmed_fields.task_id and t.owner_id = auth.uid()));

-- ------------------------------------------------------------------- issues
create policy "issues_all_via_task"
  on public.issues for all
  using (exists (
    select 1 from public.tasks t
    where t.id = issues.task_id and t.owner_id = auth.uid()))
  with check (exists (
    select 1 from public.tasks t
    where t.id = issues.task_id and t.owner_id = auth.uid()));

-- --------------------------------------------------------------- checkpoints
-- Users may READ their checkpoints and may only move them pending → cancelled
-- themselves. Authorization (pending → authorized) is performed by the
-- backend service role after verifying an explicit user action — never by
-- direct client write. Enforced by splitting policies:
create policy "checkpoints_select_via_task"
  on public.checkpoints for select
  using (exists (
    select 1 from public.tasks t
    where t.id = checkpoints.task_id and t.owner_id = auth.uid()));
-- Clients can insert a pending checkpoint request for their own task...
create policy "checkpoints_insert_pending_own"
  on public.checkpoints for insert
  with check (
    status = 'pending'
    and exists (
      select 1 from public.tasks t
      where t.id = task_id and t.owner_id = auth.uid()));
-- ...and can only cancel their own pending checkpoints, never authorize.
create policy "checkpoints_update_cancel_own"
  on public.checkpoints for update
  using (exists (
      select 1 from public.tasks t
      where t.id = checkpoints.task_id and t.owner_id = auth.uid())
    and status = 'pending')
  with check (status = 'cancelled');

-- ---------------------------------------------------------- browser_sessions
create policy "browser_sessions_select_own"
  on public.browser_sessions for select
  using (auth.uid() = owner_id);
-- Sessions are created by the backend service role, not by clients.

-- --------------------------------------------------------------- audit_events
-- Append-only for users: they can read their own events; inserts happen
-- through the backend. No updates or deletes via the client.
create policy "audit_events_select_own"
  on public.audit_events for select
  using (auth.uid() = owner_id);

-- ------------------------------------------------------------------ storage
-- Private document bucket. One folder per user; users access only their own.
-- Run once in the SQL editor (or via the Supabase dashboard):
--
--   insert into storage.buckets (id, name, public)
--   values ('documents', 'documents', false)
--   on conflict (id) do nothing;
--
-- Then these storage policies:
create policy "documents_storage_select_own"
  on storage.objects for select
  using (bucket_id = 'documents'
    and (storage.foldername(name))[1] = auth.uid()::text);
create policy "documents_storage_insert_own"
  on storage.objects for insert
  with check (bucket_id = 'documents'
    and (storage.foldername(name))[1] = auth.uid()::text);
create policy "documents_storage_delete_own"
  on storage.objects for delete
  using (bucket_id = 'documents'
    and (storage.foldername(name))[1] = auth.uid()::text);
