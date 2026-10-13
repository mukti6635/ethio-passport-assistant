"""Phase 5 durable-task tests against a REAL local PostgreSQL.

Uses pgserver (bundled Postgres binaries) — no Supabase account, no
network, no production data. Applies:
  local_pg_shims.sql (auth stub)
  migration 001 (profiles + base tables)
  migration 003 (agent_jobs)
  migration 004 (approvals + atomic RPCs)
  migration 005 (agent_jobs RPCs, state vocabulary, profile trigger,
                 one-active-job-per-session index)

Verifies the Phase 5 requirements at the store level:
  1. Create task and read it back.
  2. "Restart" (fresh store instances) restores a pending task.
  3. Its pending approval is restored and decidable.
  4. Mismatched owner / approval access is rejected.
  5. Stale running job and stale execution recover to safe states.
  6. No duplicate execution after restart.
  7. Verified completion is recorded durably (and refused without a
     verified final_result).
  8. An uncertain (UNKNOWN) outcome is never blind-retried.
  9. Concurrent transitions/creates have exactly one winner.

Run: ~/workspace/ethio-pg-venv/bin/python -m pytest api/test_task_store_pg.py -q
"""

import os
import sys
import tempfile
import threading
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

pgserver = pytest.importorskip("pgserver")
psycopg2 = pytest.importorskip("psycopg2")

from approvals import Approval, ApprovalState, idempotency_key
from persistence import PgApprovalStore
from task_store import (
    DuplicateActiveJob,
    InvalidTransition,
    PgTaskStore,
)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def _read_local(rel):
    sql = _read(rel)
    return sql.replace('create extension if not exists "pgcrypto";', '')


@pytest.fixture(scope="module")
def pg():
    pgdata = tempfile.mkdtemp(prefix="ethio-pg-tasks-")
    server = pgserver.get_server(pgdata)
    uri = server.get_uri()
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(_read("api/local_pg_shims.sql"))
    cur.execute(_read_local("mobile/backend/migrations/001_initial_schema.sql"))
    cur.execute(_read_local("mobile/backend/migrations/003_job_persistence.sql"))
    cur.execute(_read_local("mobile/backend/migrations/004_approvals.sql"))
    cur.execute(_read_local("mobile/backend/migrations/005_durable_agent_jobs.sql"))
    # Seeding auth.users fires the 005 profile trigger; the explicit
    # profile insert stays as a belt-and-braces no-op.
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
    # /tmp is a small tmpfs in this sandbox: remove the data dir or
    # repeated runs fill it and Postgres starts failing with
    # misleading "no space left" errors.
    import shutil

    shutil.rmtree(pgdata, ignore_errors=True)


def make_record(owner=USER_A, session=None, runner="worker"):
    return {
        "job_id": uuid.uuid4().hex,
        "owner_key": owner,
        # Unique session per record by default: the one-active-job-per
        # (owner, session) index would (correctly) reject parallel
        # active jobs that share a session. Tests that exercise the
        # duplicate rule pass an explicit shared session.
        "session_id": session or f"sess-{uuid.uuid4().hex[:12]}",
        "goal": "Renew ID card",
        "inputs": {"fullName": "Test User"},
        "state": "queued",
        "log": [],
        "checkpoint": None,
        "final_result": None,
        "error": None,
        "evidence": None,
        "runner": runner,
        "created_at": time.time(),
        "started_at": None,
        "ended_at": None,
    }


def drive_to(store, rec, target):
    """Walk a record queued -> running -> target via CAS transitions."""
    store.transition(rec["job_id"], rec["owner_key"], "queued", "running")
    if target != "running":
        patch = {}
        if target == "succeeded":
            patch = {"final_result": "verified: receipt ETB 200 paid"}
        store.transition(
            rec["job_id"], rec["owner_key"], "running", target, patch
        )


PAYMENT_PARAMS = {"selector": "#btn-pay", "amount": "200"}


def prepare_payment(approvals, job_id, owner=USER_A):
    """Prepare via the gateway's real calling convention (kwargs)."""
    return approvals.prepare(
        job_id=job_id,
        session_id=owner,
        action_type="payment",
        action_label="Pay ETB 200",
        consequence="Simulated charge",
        params=dict(PAYMENT_PARAMS),
        params_summary={"amount": "200"},
    )


# ---------------------------------------------------------------------------
# 0. Migration 005 proofs: profile trigger + state vocabulary.
# ---------------------------------------------------------------------------


def test_pg_00_profile_trigger_and_state_vocabulary(pg):
    conn = psycopg2.connect(pg)
    conn.autocommit = True
    cur = conn.cursor()
    # The 005 trigger auto-provisioned profiles for the seeded users.
    cur.execute("select count(*) from public.profiles where id in (%s, %s)",
                (USER_A, USER_B))
    assert cur.fetchone()[0] == 2
    # A brand-new auth user gets a profile with no manual insert.
    new_user = str(uuid.uuid4())
    cur.execute("insert into auth.users (id) values (%s)", (new_user,))
    cur.execute("select count(*) from public.profiles where id = %s",
                (new_user,))
    assert cur.fetchone()[0] == 1
    conn.close()


# ---------------------------------------------------------------------------
# 1. Create + read back.
# ---------------------------------------------------------------------------


def test_pg_01_create_and_read_back(pg):
    store = PgTaskStore(pg)
    rec = make_record()
    created = store.create(rec)
    assert created["state"] == "queued"
    fetched = store.get(rec["job_id"], USER_A)
    assert fetched is not None
    assert fetched["goal"] == "Renew ID card"
    assert fetched["inputs"] == {"fullName": "Test User"}
    assert fetched["runner"] == "worker"
    assert fetched["job_id"] == rec["job_id"]


# ---------------------------------------------------------------------------
# 2 + 3. Restart restores the pending task and its pending approval.
# ---------------------------------------------------------------------------


def test_pg_02_restart_restores_task_and_approval(pg):
    store = PgTaskStore(pg)
    approvals = PgApprovalStore(pg)
    rec = make_record()
    store.create(rec)
    drive_to(store, rec, "waiting_approval")
    approval = prepare_payment(approvals, rec["job_id"])

    # "Restart": brand-new store instances over the same database.
    store2 = PgTaskStore(pg)
    approvals2 = PgApprovalStore(pg)
    active = store2.list_active()
    mine = [r for r in active if r["job_id"] == rec["job_id"]]
    assert len(mine) == 1
    assert mine[0]["state"] == "waiting_approval"
    pending = approvals2.list_pending(USER_A)
    assert any(a.approval_id == approval.approval_id for a in pending)
    # The restored approval is decidable by its owner.
    decided = approvals2.decide(approval.approval_id, USER_A, True)
    assert decided is not None
    assert decided.state == ApprovalState.APPROVED


# ---------------------------------------------------------------------------
# 4. Mismatched owner is rejected everywhere.
# ---------------------------------------------------------------------------


def test_pg_03_owner_mismatch_rejected(pg):
    store = PgTaskStore(pg)
    approvals = PgApprovalStore(pg)
    rec = make_record()
    store.create(rec)
    assert store.get(rec["job_id"], USER_B) is None
    assert store.transition(rec["job_id"], USER_B, "queued", "running") is None
    approval = prepare_payment(approvals, rec["job_id"])
    assert approvals.get(approval.approval_id, USER_B) is None
    assert approvals.decide(approval.approval_id, USER_B, True) is None
    assert approvals.list_pending(USER_B) == []
    # Owner's row is untouched by the foreign attempts.
    assert store.get(rec["job_id"], USER_A)["state"] == "queued"


# ---------------------------------------------------------------------------
# 5. Stale job + stale execution recover to safe states.
# ---------------------------------------------------------------------------


def test_pg_04_stale_recovery(pg):
    store = PgTaskStore(pg)
    rec = make_record()
    store.create(rec)
    drive_to(store, rec, "running")
    # Age the row as if its worker died 10 minutes ago. The 005
    # updated_at trigger would (correctly) refresh the timestamp on
    # any ordinary update, so disable it to simulate a dead worker
    # that stopped writing entirely.
    conn = psycopg2.connect(pg)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("alter table public.agent_jobs disable trigger trg_agent_jobs_updated")
    cur.execute(
        "update public.agent_jobs set updated_at = now() - interval '10 minutes' "
        "where id = %s::uuid",
        (str(uuid.UUID(rec["job_id"])),),
    )
    cur.execute("alter table public.agent_jobs enable trigger trg_agent_jobs_updated")
    conn.close()
    reconciled = store.reconcile_stale(120)
    mine = [r for r in reconciled if r["job_id"] == rec["job_id"]]
    assert len(mine) == 1
    assert mine[0]["state"] == "failed"
    assert "interrupted" in (mine[0]["error"] or "")
    # A fresh running job is NOT reconciled.
    rec2 = make_record()
    store.create(rec2)
    drive_to(store, rec2, "running")
    reconciled2 = store.reconcile_stale(120)
    assert all(r["job_id"] != rec2["job_id"] for r in reconciled2)
    store.transition(rec2["job_id"], USER_A, "running", "failed")


# ---------------------------------------------------------------------------
# 6 + 8. Claim once; after "restart" and after UNKNOWN, never again.
# ---------------------------------------------------------------------------


def test_pg_05_no_duplicate_execution_and_no_blind_retry(pg):
    approvals = PgApprovalStore(pg)
    store = PgTaskStore(pg)
    rec = make_record()
    store.create(rec)
    drive_to(store, rec, "waiting_approval")
    approval = prepare_payment(approvals, rec["job_id"])
    approvals.decide(approval.approval_id, USER_A, True)
    params = {"selector": "#btn-pay", "amount": "200"}

    claimed = approvals.claim_for_execution(
        approval.approval_id, USER_A, rec["job_id"], "payment", params
    )
    assert claimed is not None
    # A second claim — including from a "restarted" store — loses.
    approvals2 = PgApprovalStore(pg)
    assert approvals2.claim_for_execution(
        approval.approval_id, USER_A, rec["job_id"], "payment", params
    ) is None
    # The execution's outcome becomes uncertain (no result recorded);
    # reconciliation marks it UNKNOWN...
    reconciled = approvals2.reconcile_abandoned(0)
    mine = [a for a in reconciled if a.approval_id == approval.approval_id]
    assert len(mine) == 1
    assert mine[0].execution_state.value == "unknown"
    # ...and UNKNOWN is terminal for execution: never claimable again.
    assert approvals2.claim_for_execution(
        approval.approval_id, USER_A, rec["job_id"], "payment", params
    ) is None


# ---------------------------------------------------------------------------
# 7. Verified completion is durable; unverified completion is refused.
# ---------------------------------------------------------------------------


def test_pg_06_verified_completion_durable(pg):
    store = PgTaskStore(pg)
    rec = make_record()
    store.create(rec)
    store.transition(rec["job_id"], USER_A, "queued", "running")
    # Without a verified final_result the database refuses success.
    with pytest.raises(InvalidTransition):
        store.transition(rec["job_id"], USER_A, "running", "succeeded")
    done = store.transition(
        rec["job_id"], USER_A, "running", "succeeded",
        {"final_result": "verified: receipt ETB 200 paid"},
    )
    assert done is not None
    assert done["state"] == "succeeded"
    assert done["final_result"] == "verified: receipt ETB 200 paid"
    assert done["ended_at"] is not None
    # Read back through a fresh store: the completion is durable.
    fetched = PgTaskStore(pg).get(rec["job_id"], USER_A)
    assert fetched["state"] == "succeeded"
    # Terminal states have no outgoing transitions.
    with pytest.raises(InvalidTransition):
        store.transition(rec["job_id"], USER_A, "succeeded", "running")


# ---------------------------------------------------------------------------
# 9. Concurrency: one winner for transitions and for session creates.
# ---------------------------------------------------------------------------


def test_pg_07_concurrent_transitions_single_winner(pg):
    store = PgTaskStore(pg)
    rec = make_record()
    store.create(rec)
    store.transition(rec["job_id"], USER_A, "queued", "running")
    results = []
    lock = threading.Lock()

    def attempt():
        won = store.transition(
            rec["job_id"], USER_A, "running", "waiting_approval"
        )
        with lock:
            results.append(won is not None)

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    assert store.get(rec["job_id"], USER_A)["state"] == "waiting_approval"


def test_pg_08_concurrent_create_single_active(pg):
    store = PgTaskStore(pg)
    session = f"sess-{uuid.uuid4().hex[:8]}"
    outcomes = []
    lock = threading.Lock()

    def attempt():
        rec = make_record(session=session)
        try:
            store.create(rec)
            with lock:
                outcomes.append("created")
        except DuplicateActiveJob:
            with lock:
                outcomes.append("duplicate")

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("created") == 1
    assert outcomes.count("duplicate") == 7


# ---------------------------------------------------------------------------
# 10. RPC privilege lockdown, with Supabase-style roles pre-created.
# (Separate cluster: roles must exist BEFORE migrations run, as they
# do on Supabase, so the migrations' grant blocks actually execute.)
# ---------------------------------------------------------------------------

JOB_RPCS = [
    "create_agent_job(uuid,uuid,text,text,jsonb,text)",
    "transition_agent_job(uuid,uuid,text,text,jsonb)",
    "get_agent_job(uuid,uuid)",
    "list_agent_jobs(uuid)",
    "reconcile_stale_agent_jobs(integer)",
]
APPROVAL_RPCS = [
    "claim_approval_for_execution(text,text,text,text,text)",
    "record_approval_execution_result(text,text,text,boolean,text)",
    "reconcile_abandoned_approvals(integer)",
]


@pytest.fixture(scope="module")
def pg_roles():
    pgdata = tempfile.mkdtemp(prefix="ethio-pg-roles-")
    server = pgserver.get_server(pgdata)
    uri = server.get_uri()
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    cur = conn.cursor()
    for role in ("anon", "authenticated", "service_role"):
        cur.execute(f"create role {role} nologin")
    cur.execute(_read("api/local_pg_shims.sql"))
    cur.execute(_read_local("mobile/backend/migrations/001_initial_schema.sql"))
    cur.execute(_read_local("mobile/backend/migrations/003_job_persistence.sql"))
    cur.execute(_read_local("mobile/backend/migrations/004_approvals.sql"))
    cur.execute(_read_local("mobile/backend/migrations/005_durable_agent_jobs.sql"))
    conn.close()
    yield uri
    server.cleanup()
    import shutil

    shutil.rmtree(pgdata, ignore_errors=True)


def test_pg_09_rpc_privileges(pg_roles):
    conn = psycopg2.connect(pg_roles)
    conn.autocommit = True
    cur = conn.cursor()
    for sig in JOB_RPCS + APPROVAL_RPCS:
        for role in ("public", "anon", "authenticated"):
            cur.execute(
                "select has_function_privilege(%s, %s, 'execute')",
                (role, f"public.{sig}"),
            )
            assert cur.fetchone()[0] is False, f"{role} can execute {sig}"
        cur.execute(
            "select has_function_privilege('service_role', %s, 'execute')",
            (f"public.{sig}",),
        )
        assert cur.fetchone()[0] is True, f"service_role cannot execute {sig}"
    # RLS is enabled on both durable tables.
    cur.execute(
        "select relname, relrowsecurity from pg_class "
        "where relname in ('agent_jobs', 'approvals') order by 1"
    )
    rows = cur.fetchall()
    assert len(rows) == 2 and all(r[1] for r in rows)
    conn.close()
