"""Durable-mode API-restart recovery test (Phase 5).

The Phase 4/5 gap this closes: in memory mode a restart loses jobs
(404) — see test_restart.py. In durable mode (ETHIO_TASK_STORE=pg +
ETHIO_AUTH_MODE=jwt) the same scenario must behave differently:

- a job paused in waiting_approval is RESTORED after restart, with its
  pending approval still listed and decidable
- approving it does NOT execute the protected action (the browser
  session died with the old process): the job fails safely and the
  approval is never consumed
- a job left 'running' by the dead process is reconciled to FAILED
  (interrupted) at startup — never resumed, never completed
- another user's token cannot see the restored job

Runs the real gateway under uvicorn against a real local PostgreSQL
(pgserver) and the real mock portal. Must run as a NON-root user
(PostgreSQL refuses to run as root):

  su pgtest -c '~/workspace/ethio-live-venv/bin/python -m pytest \
      api/test_restart_durable.py -q'
"""

import base64
import functools
import hashlib
import hmac
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))
PORTAL_DIR = os.path.join(ROOT, "..", "mobile", "mock-portal")
GW_PORT = 8941
BASE = f"http://127.0.0.1:{GW_PORT}"

httpx = pytest.importorskip("httpx")
pgserver = pytest.importorskip("pgserver")
psycopg2 = pytest.importorskip("psycopg2")

_client = httpx.Client(trust_env=False)

SECRET = "restart-durable-test-secret"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
INPUTS = {
    "fullName": "Test User", "dob": "1990-01-01", "phone": "0911123456",
    "nationalId": "12345678", "serviceType": "idcard",
    "birthPlace": "Addis Ababa",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint(sub):
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "sub": sub, "aud": "authenticated",
        "iat": int(time.time()), "exp": int(time.time()) + 3600,
    }
    signing = (
        f"{_b64(json.dumps(header).encode())}."
        f"{_b64(json.dumps(claims).encode())}"
    )
    sig = hmac.new(SECRET.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{_b64(sig)}"


def headers(sub):
    return {"Authorization": f"Bearer {mint(sub)}", "X-Ethio-Session": "dev-1"}


def _read(rel):
    with open(os.path.join(ROOT, "..", rel)) as f:
        return f.read()


def _read_local(rel):
    return _read(rel).replace(
        'create extension if not exists "pgcrypto";', ""
    )


@pytest.fixture(scope="module")
def pg():
    pgdata = tempfile.mkdtemp(prefix="ethio-pg-durable-")
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
    cur.execute("insert into auth.users (id) values (%s)", (USER_A,))
    # A job the "previous process" left mid-flight: startup must
    # reconcile it to FAILED, never restore or complete it.
    stale_id = uuid.uuid4()
    cur.execute(
        """insert into public.agent_jobs
           (id, owner_id, session_id, goal, inputs, state, runner)
           values (%s::uuid, %s::uuid, 'stale-sess', 'leftover', '{}'::jsonb,
                   'running', 'worker')""",
        (str(stale_id), USER_A),
    )
    conn.close()
    yield uri, str(stale_id)
    server.cleanup()
    import shutil

    shutil.rmtree(pgdata, ignore_errors=True)


@pytest.fixture(scope="module")
def portal():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=PORTAL_DIR
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8901), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def start_server(dsn):
    env = dict(os.environ)
    env.update({
        "ETHIO_AUTH_MODE": "jwt",
        "SUPABASE_JWT_SECRET": SECRET,
        "ETHIO_TASK_STORE": "pg",
        "ETHIO_PG_DSN": dsn,
        "ETHIO_RATE_LIMIT_TASKS": "1000",
        "PLAYWRIGHT_BROWSERS_PATH": "/home/hatch/.cache/ms-playwright",
    })
    env.pop("SUPABASE_URL", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "gateway:app",
         "--port", str(GW_PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            r = _client.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return proc
        except Exception:
            pass
        time.sleep(0.3)
    proc.kill()
    raise RuntimeError("gateway did not start")


def wait_state(job_id, want, timeout=60):
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        r = _client.get(
            f"{BASE}/tasks/status/{job_id}", headers=headers(USER_A), timeout=5
        )
        if r.status_code == 200:
            state = r.json()["state"]
            if state == want:
                return state
        time.sleep(0.3)
    return state


def test_durable_restart_restores_waiting_job(pg, portal):
    dsn, stale_id = pg
    proc = start_server(dsn)
    try:
        # The stale 'running' row was reconciled at startup.
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "select state, error from public.agent_jobs where id = %s::uuid",
            (stale_id,),
        )
        state, error = cur.fetchone()
        assert state == "failed"
        assert "interrupted by gateway restart" in error
        conn.close()

        # Drive a real worker job to waiting_approval.
        r = _client.post(f"{BASE}/tasks", json={
            "goal": "fill mock form", "inputs": INPUTS,
            "session_id": "dev-1", "runner": "worker",
        }, headers=headers(USER_A), timeout=10)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        assert wait_state(job_id, "waiting_approval") == "waiting_approval"
        r = _client.get(
            f"{BASE}/approvals/pending", headers=headers(USER_A), timeout=5
        )
        mine = [a for a in r.json()["approvals"] if a["job_id"] == job_id]
        assert len(mine) == 1
        approval_id = mine[0]["approval_id"]
    finally:
        proc.kill()
        proc.wait(timeout=10)

    # --- restart: the job and its approval must be restored ---
    proc = start_server(dsn)
    try:
        r = _client.get(
            f"{BASE}/tasks/status/{job_id}", headers=headers(USER_A),
            timeout=5,
        )
        assert r.status_code == 200
        assert r.json()["state"] == "waiting_approval"
        # Another user cannot see it.
        r = _client.get(
            f"{BASE}/tasks/status/{job_id}", headers=headers(USER_B),
            timeout=5,
        )
        assert r.status_code == 404
        # The pending approval survived and is listed for the owner.
        r = _client.get(
            f"{BASE}/approvals/pending", headers=headers(USER_A), timeout=5
        )
        assert any(
            a["approval_id"] == approval_id for a in r.json()["approvals"]
        )
        # Approving must NOT execute anything: the browser session is
        # gone, so the job fails safely and the approval is never
        # consumed.
        r = _client.post(
            f"{BASE}/approvals/{approval_id}/decide",
            json={"approve": True}, headers=headers(USER_A), timeout=5,
        )
        assert r.status_code == 200
        assert wait_state(job_id, "failed", timeout=30) == "failed"
        r = _client.post(
            f"{BASE}/approvals/{approval_id}/execute",
            json={
                "job_id": job_id, "action_type": "payment",
                "params": {"selector": "#btn-pay",
                           "verify_visible": "#pay-ok", "amount": "200"},
            },
            headers=headers(USER_A), timeout=5,
        )
        assert r.status_code == 409
        # Database truth: approval unconsumed, never started executing.
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "select consumed, execution_state from public.approvals "
            "where approval_id = %s",
            (approval_id,),
        )
        consumed, execution_state = cur.fetchone()
        assert consumed is False
        assert execution_state == "not_started"
        cur.execute(
            "select state from public.agent_jobs where id = %s::uuid",
            (job_id,),
        )
        assert cur.fetchone()[0] == "failed"
        conn.close()
    finally:
        proc.kill()
        proc.wait(timeout=10)
