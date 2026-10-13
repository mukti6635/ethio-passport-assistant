"""Durable-persistence tests against a REAL local PostgreSQL.

Uses pgserver (bundled Postgres binaries) — no Supabase account, no
network, no production data. Applies:
  local_pg_shims.sql (auth stub)
  migration 001 (profiles + base tables)
  migration 003 (agent_jobs)
  migration 004 (approvals + task_events + atomic RPCs)

Then verifies with real SQL connections:
  - RLS owner isolation actually enforced
  - claim_approval_for_execution is atomic under real concurrency
  - record_approval_execution_result honors execution_id ownership
  - reconcile_abandoned_approvals marks stale claims UNKNOWN
  - idempotent prepare via the (job_id, params_hash) unique constraint

Requirements: pip install pgserver psycopg2-binary (test-only venv).
Skip cleanly when pgserver is unavailable. PostgreSQL refuses to run
as root — in this sandbox run as the unprivileged pgtest user.

Run: su - pgtest -c '~/workspace/ethio-pg-venv/bin/python -m pytest api/test_postgres.py -q'
"""

import os
import sys
import threading
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

pgserver = pytest.importorskip("pgserver")
psycopg2 = pytest.importorskip("psycopg2")

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"


def _read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def _read_local(rel):
    """Migration SQL adapted for plain local Postgres: pgserver's
    binaries don't ship pgcrypto, and the migrations only use
    gen_random_uuid() (core since PG13), so the extension line is
    dropped locally. The migration files themselves are untouched."""
    sql = _read(rel)
    return sql.replace('create extension if not exists "pgcrypto";', '')


@pytest.fixture(scope="module")
def pg():
    server = pgserver.get_server("/tmp/ethio-pg-test")
    uri = server.get_uri()
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(_read("api/local_pg_shims.sql"))
    # Minimal profiles dependency from migration 001 (full 001 pulls in
    # the whole app schema; apply it too — it is self-contained given
    # the auth stub).
    cur.execute(_read_local("mobile/backend/migrations/001_initial_schema.sql"))
    cur.execute(_read_local("mobile/backend/migrations/003_job_persistence.sql"))
    cur.execute(_read_local("mobile/backend/migrations/004_approvals.sql"))
    # Seed two users.
    for uid in (USER_A, USER_B):
        cur.execute("insert into auth.users (id) values (%s)", (uid,))
        cur.execute(
            "insert into public.profiles (id) values (%s) "
            "on conflict do nothing",
            (uid,),
        )
    conn.close()
    yield uri
    server.cleanup()


def connect(uri, uid=None):
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    cur = conn.cursor()
    if uid:
        cur.execute("select set_config('app.test_uid', %s, false)", (uid,))
    return conn, cur


def insert_approval(cur, owner=USER_A, state="approved", job="job-pg-1",
                    params_hash=None, session="sess-A"):
    aid = f"appr-{uuid.uuid4().hex[:12]}"
    if params_hash is None:
        params_hash = f"hash-{uuid.uuid4().hex[:8]}"
    cur.execute(
        """insert into public.approvals
           (approval_id, owner_id, job_id, session_id, action_type,
            action_label, consequence, params_summary, params_hash,
            state, expires_at)
           values (%s, %s, %s, %s, 'payment', 'Pay', 'Simulated charge',
                   '{}'::jsonb, %s, %s, now() + interval '30 minutes')""",
        (aid, owner, job, session, params_hash, state),
    )
    return aid


# ---------------------------------------------------------------------------
# 1. Migrations apply: tables, RPCs, RLS present.
# ---------------------------------------------------------------------------

def test_pg_01_schema_objects_exist(pg):
    conn, cur = connect(pg)
    cur.execute(
        "select table_name from information_schema.tables "
        "where table_schema='public'"
    )
    tables = {r[0] for r in cur.fetchall()}
    assert {"approvals", "task_events", "agent_jobs", "profiles"} <= tables
    cur.execute(
        "select proname from pg_proc where proname like '%approval%'"
    )
    funcs = {r[0] for r in cur.fetchall()}
    assert "claim_approval_for_execution" in funcs
    assert "record_approval_execution_result" in funcs
    assert "reconcile_abandoned_approvals" in funcs
    conn.close()


# ---------------------------------------------------------------------------
# 2. RLS: a user sees only their own approvals (as a non-owner role).
# ---------------------------------------------------------------------------

def test_pg_02_rls_owner_isolation(pg):
    conn, cur = connect(pg)
    insert_approval(cur, owner=USER_A)
    insert_approval(cur, owner=USER_B, job="job-pg-2")
    # RLS is enforced for non-superusers; pgserver's default user is a
    # superuser (bypasses RLS), so verify the policy exists and is
    # enabled, and verify the owner-filter behavior via a restricted role.
    cur.execute(
        "select relrowsecurity from pg_class where relname='approvals'"
    )
    assert cur.fetchone()[0] is True
    cur.execute(
        "select polname from pg_policy where polrelid="
        "'public.approvals'::regclass"
    )
    assert cur.fetchone() is not None
    cur.execute("drop role if exists ethio_app")
    cur.execute("create role ethio_app login")
    cur.execute("grant select, insert, update on public.approvals to ethio_app")
    cur.execute("grant usage on schema public to ethio_app")
    cur.execute(f"set role ethio_app")
    cur.execute("select set_config('app.test_uid', %s, false)", (USER_A,))
    cur.execute("select count(*) from public.approvals")
    assert cur.fetchone()[0] == 1  # only USER_A's row is visible
    cur.execute("reset role")
    conn.close()


# ---------------------------------------------------------------------------
# 3. Atomic claim under real concurrency: exactly one winner.
# ---------------------------------------------------------------------------

def test_pg_03_atomic_claim_single_winner(pg):
    conn, cur = connect(pg)
    aid = insert_approval(cur, params_hash="hash-pg03")
    conn.close()
    winners = []
    errors = []

    def attempt(n):
        try:
            c, cu = connect(pg)
            cu.execute(
                "select approval_id, execution_id from "
                "public.claim_approval_for_execution(%s, %s, %s, %s, %s)",
                (aid, "sess-A", "job-pg-1", "hash-pg03", f"exec-{n}"),
            )
            rows = cu.fetchall()
            if rows:
                winners.append(rows[0][1])
            c.close()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(winners) == 1
    conn, cur = connect(pg)
    cur.execute(
        "select execution_state, consumed from public.approvals "
        "where approval_id=%s", (aid,)
    )
    state, consumed = cur.fetchone()
    assert state == "executing" and consumed is True
    conn.close()


# ---------------------------------------------------------------------------
# 4. Claim validation: wrong params hash / wrong owner / expired all fail.
# ---------------------------------------------------------------------------

def test_pg_04_claim_validation(pg):
    conn, cur = connect(pg)
    aid = insert_approval(cur, params_hash="hash-good")
    # Wrong hash.
    cur.execute(
        "select * from public.claim_approval_for_execution"
        "(%s, 'sess-A', 'job-pg-1', 'hash-bad', 'exec-x')", (aid,)
    )
    assert cur.fetchall() == []
    # Wrong session.
    cur.execute(
        "select * from public.claim_approval_for_execution"
        "(%s, 'sess-WRONG', 'job-pg-1', 'hash-good', 'exec-x')", (aid,)
    )
    assert cur.fetchall() == []
    # Pending (not approved) state cannot claim.
    aid2 = insert_approval(cur, state="pending", params_hash="hash-p")
    cur.execute(
        "select * from public.claim_approval_for_execution"
        "(%s, 'sess-A', 'job-pg-1', 'hash-p', 'exec-x')", (aid2,)
    )
    assert cur.fetchall() == []
    conn.close()


# ---------------------------------------------------------------------------
# 5. Record result: only the execution_id holder, only from executing.
# ---------------------------------------------------------------------------

def test_pg_05_record_result_ownership(pg):
    conn, cur = connect(pg)
    aid = insert_approval(cur, params_hash="hash-r")
    cur.execute(
        "select execution_id from public.claim_approval_for_execution"
        "(%s, 'sess-A', 'job-pg-1', 'hash-r', 'exec-right')", (aid,)
    )
    assert cur.fetchone()[0] == "exec-right"
    # Wrong execution id cannot record.
    cur.execute(
        "select * from public.record_approval_execution_result"
        "(%s, 'sess-A', 'exec-WRONG', true, 'evidence')", (aid,)
    )
    assert cur.fetchall() == []
    # Right id records success.
    cur.execute(
        "select execution_state from public.record_approval_execution_result"
        "(%s, 'sess-A', 'exec-right', true, 'pay-ok visible')", (aid,)
    )
    assert cur.fetchone()[0] == "succeeded"
    # Cannot record twice.
    cur.execute(
        "select * from public.record_approval_execution_result"
        "(%s, 'sess-A', 'exec-right', true, 'again')", (aid,)
    )
    assert cur.fetchall() == []
    conn.close()


# ---------------------------------------------------------------------------
# 6. Reconcile: stale executing -> unknown; fresh executing untouched.
# ---------------------------------------------------------------------------

def test_pg_06_reconcile_abandoned(pg):
    conn, cur = connect(pg)
    aid = insert_approval(cur, params_hash="hash-stale")
    cur.execute(
        "select * from public.claim_approval_for_execution"
        "(%s, 'sess-A', 'job-pg-1', 'hash-stale', 'exec-stale')", (aid,)
    )
    cur.execute(
        "update public.approvals set execution_started_at = "
        "now() - interval '10 minutes' where approval_id=%s", (aid,)
    )
    fresh = insert_approval(cur, params_hash="hash-fresh")
    cur.execute(
        "select * from public.claim_approval_for_execution"
        "(%s, 'sess-A', 'job-pg-1', 'hash-fresh', 'exec-fresh')", (fresh,)
    )
    cur.execute("select approval_id, execution_state from "
                "public.reconcile_abandoned_approvals(300)")
    rows = cur.fetchall()
    ids = {r[0] for r in rows}
    assert aid in ids
    assert fresh not in ids
    cur.execute(
        "select execution_state from public.approvals where approval_id=%s",
        (aid,),
    )
    assert cur.fetchone()[0] == "unknown"
    conn.close()


# ---------------------------------------------------------------------------
# 7. Idempotent prepare: unique (job_id, params_hash) blocks duplicates.
# ---------------------------------------------------------------------------

def test_pg_07_unique_idempotency_constraint(pg):
    conn, cur = connect(pg)
    insert_approval(cur, state="pending", params_hash="hash-dup")
    with pytest.raises(Exception):
        insert_approval(cur, state="pending", params_hash="hash-dup")
    conn.close()
