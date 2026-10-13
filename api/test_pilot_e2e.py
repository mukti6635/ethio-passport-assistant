"""Phase 10: the PILOT RUNBOOK executed end-to-end as a test.

Real processes, real HTTP, local everything:
- pgserver PostgreSQL with migrations 001+003+004+005 and two users
  created in auth.users (profiles must appear via the 005 trigger).
- The gateway as a subprocess in durable mode (ETHIO_TASK_STORE=pg,
  ETHIO_AUTH_MODE=jwt, HS256 test secret) — the same configuration the
  pilot uses with Supabase, with local Postgres standing in for it.
- The mock portal served on 127.0.0.1:8901; the real worker + Chromium.

Script (mirrors docs/PILOT_RUNBOOK.md §3 + OWNER_PILOT_CHECKLIST):
  401s -> A starts a task -> waiting_approval -> B sees nothing and
  cannot decide/execute -> A REJECTS -> job failed, nothing executed
  -> A starts task 2 -> A APPROVES -> job succeeded with a result
  -> gateway KILLED and restarted -> task 3 (waiting) restored ->
  approving it fails the job safely, approval never consumed.

This is a LOCAL simulation of the pilot: live Supabase is not involved
and no result here says anything about the remote project.

Run (as pgtest — Postgres refuses root):
  su - pgtest -c '~/workspace/ethio-live-venv/bin/python -m pytest api/test_pilot_e2e.py -q'
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
import pytest

pytest.importorskip("pgserver")
pytest.importorskip("psycopg2")
import pgserver  # noqa: E402
import psycopg2  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
SECRET = "pilot-e2e-hs256-test-secret"
USER_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
# The gateway port is chosen dynamically by the fixture: a fixed port
# once let a leaked gateway from a killed run silently answer the
# health check while pointing at a dead database.
_BASE = {"url": "http://127.0.0.1:0"}
INPUTS = {
    "fullName": "Test User",
    "dob": "1990-01-01",
    "phone": "0911123456",
    "nationalId": "12345678",
    "serviceType": "idcard",
    "birthPlace": "Addis Ababa",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_token(sub: uuid.UUID) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({
        "sub": str(sub), "aud": "authenticated", "role": "authenticated",
        "email": f"{str(sub)[:4]}@pilot.test",
        "iat": int(time.time()), "exp": int(time.time()) + 3600,
    }).encode())
    sig = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(),
                   hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(sig)}"


def _sql(name: str) -> str:
    return (REPO / "mobile/backend/migrations" / name).read_text().replace(
        'create extension if not exists "pgcrypto";', "")


@pytest.fixture(scope="module")
def pilot():
    pgdata = tempfile.mkdtemp(prefix="ethio-pg-pilot-")
    server = pgserver.get_server(pgdata)
    dsn = server.get_uri()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    for role in ("anon", "authenticated", "service_role"):
        cur.execute(f"create role {role} nologin")
    cur.execute((REPO / "api/local_pg_shims.sql").read_text())
    for name in ("001_initial_schema.sql", "003_job_persistence.sql",
                 "004_approvals.sql", "005_durable_agent_jobs.sql"):
        cur.execute(_sql(name))
    cur.execute("insert into auth.users (id) values (%s), (%s)",
                (str(USER_A), str(USER_B)))
    cur.execute("select count(*) from public.profiles")
    assert cur.fetchone()[0] == 2, "005 trigger must provision profiles"
    conn.close()

    portal = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8901", "--bind", "127.0.0.1",
         "--directory", str(REPO / "mobile/mock-portal")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # The portal port is fixed by the worker allowlist; verify what
    # answers there really is the mock (a stale identical server is
    # acceptable, anything else is not).
    import socket as _socket
    with _socket.socket() as _s:
        _s.bind(("127.0.0.1", 0))
        gw_port = _s.getsockname()[1]
    _BASE["url"] = f"http://127.0.0.1:{gw_port}"
    _check = httpx.Client(trust_env=False, timeout=5.0)
    for _ in range(40):
        try:
            r = _check.get("http://127.0.0.1:8901/index.html")
            if "pay-receipt" in r.text:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    else:
        raise RuntimeError("mock portal is not serving the expected page")
    env = dict(os.environ)
    env.update({
        "GATEWAY_API_KEY": "pilot-dev-key",
        "ETHIO_AUTH_MODE": "jwt",
        "SUPABASE_JWT_SECRET": SECRET,
        "ETHIO_TASK_STORE": "pg",
        "ETHIO_PG_DSN": dsn,
        "PLAYWRIGHT_BROWSERS_PATH": "/home/hatch/.cache/ms-playwright",
    })

    def start_gateway() -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "gateway:app",
             "--port", str(gw_port)],
            cwd=REPO / "api", env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = httpx.Client(trust_env=False, timeout=5.0)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if client.get(f"{_BASE['url']}/health").status_code == 200:
                    return proc
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        proc.kill()
        raise RuntimeError("gateway did not become healthy")

    proc = start_gateway()
    yield {"dsn": dsn, "start_gateway": start_gateway, "proc": proc}
    proc.kill()
    portal.kill()
    server.cleanup()
    shutil.rmtree(pgdata, ignore_errors=True)


def client(token: str | None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(trust_env=False, base_url=_BASE["url"],
                        headers=headers, timeout=30.0)


def start_task(token: str) -> str:
    res = client(token).post("/tasks", json={
        "goal": "Prepare my ID renewal (pilot)",
        "inputs": INPUTS, "runner": "worker", "session_id": "pilot",
    }, headers={"X-Ethio-Session": "pilot"})
    assert res.status_code == 202, res.text
    return res.json()["job_id"]


def wait_state(token: str, job_id: str, states: set[str],
               timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        res = client(token).get(f"/tasks/status/{job_id}")
        assert res.status_code == 200, res.text
        last = res.json()
        if last["state"] in states:
            return last
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} never reached {states}: {last}")


def pending(token: str) -> list:
    res = client(token).get("/approvals/pending")
    assert res.status_code == 200, res.text
    return res.json()["approvals"]


def test_pilot_end_to_end(pilot):
    tok_a, tok_b = mint_token(USER_A), mint_token(USER_B)

    # --- unauthenticated / malformed access fails closed
    assert client(None).post("/tasks", json={}).status_code == 401
    assert client("not-a-token").get("/approvals/pending").status_code == 401

    # --- task 1: A waits, B is fully isolated, A rejects -> no execution
    job1 = start_task(tok_a)
    wait_state(tok_a, job1, {"waiting_approval"})
    mine = pending(tok_a)
    assert len(mine) == 1 and mine[0]["job_id"] == job1
    approval1 = mine[0]["approval_id"]

    assert pending(tok_b) == []
    assert client(tok_b).get(f"/tasks/status/{job1}").status_code == 404
    assert client(tok_b).post(
        f"/approvals/{approval1}/decide",
        json={"approve": True}).status_code in (404, 409)
    assert client(tok_b).post(
        f"/approvals/{approval1}/execute",
        json={"job_id": job1, "action_type": "payment",
              "session_id": "pilot"}).status_code == 404

    res = client(tok_a).post(f"/approvals/{approval1}/decide",
                             json={"approve": False, "reason": "pilot reject"})
    assert res.status_code == 200, res.text
    final1 = wait_state(tok_a, job1, {"failed", "succeeded"})
    assert final1["state"] == "failed"
    blob = json.dumps(final1).lower()
    # Honesty: the job is failed, the payment step shows as BLOCKED
    # (never executed), and no receipt/success evidence is claimed.
    # (Per-step log lines like "input: succeeded (read-back matched)"
    # describe form fields, not the protected action.)
    assert "payment: blocked" in blob
    assert "rejected" in blob
    assert "receipt" not in blob

    # --- task 2: A approves -> verified success
    job2 = start_task(tok_a)
    wait_state(tok_a, job2, {"waiting_approval"})
    approval2 = pending(tok_a)[0]["approval_id"]
    res = client(tok_a).post(f"/approvals/{approval2}/decide",
                             json={"approve": True})
    assert res.status_code == 200, res.text
    final2 = wait_state(tok_a, job2, {"succeeded", "failed"})
    assert final2["state"] == "succeeded", final2
    assert final2.get("checkpoint") or final2.get("log")

    # --- task 3: gateway restart while waiting -> safe failure only
    job3 = start_task(tok_a)
    wait_state(tok_a, job3, {"waiting_approval"})
    approval3 = pending(tok_a)[0]["approval_id"]

    pilot["proc"].kill()
    pilot["proc"].wait(timeout=10)
    pilot["proc"] = pilot["start_gateway"]()

    restored = client(tok_a).get(f"/tasks/status/{job3}")
    assert restored.status_code == 200
    assert restored.json()["state"] == "waiting_approval"
    assert any(a["approval_id"] == approval3 for a in pending(tok_a))

    res = client(tok_a).post(f"/approvals/{approval3}/decide",
                             json={"approve": True})
    assert res.status_code == 200, res.text
    final3 = wait_state(tok_a, job3, {"failed", "succeeded"})
    assert final3["state"] == "failed"
    assert "session lost" in json.dumps(final3).lower() or \
        "restart" in json.dumps(final3).lower()

    # The approval was never consumed or executed (DB truth).
    conn = psycopg2.connect(pilot["dsn"])
    cur = conn.cursor()
    cur.execute("select consumed, execution_state from public.approvals "
                "where approval_id = %s", (approval3,))
    consumed, exec_state = cur.fetchone()
    assert consumed is False and exec_state == "not_started"
    cur.execute("select count(*) from public.agent_jobs where owner_id = %s",
                (str(USER_B),))
    assert cur.fetchone()[0] == 0
    conn.close()
