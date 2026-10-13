"""API integration tests: tasks created through POST /tasks run through
the real WorkerLoop + Playwright against the local mock portal.

These exercise the actual /tasks execution path (runner="worker"), not
WorkerLoop directly. Mock portal only; no real portal, no real payments.

Run: pytest api/test_worker_api.py -q
"""

import functools
import http.server
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PORTAL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "mobile", "mock-portal",
)

INPUTS = {
    "fullName": "Test User",
    "dob": "1990-01-01",
    "phone": "0911123456",
    "nationalId": "12345678",
    "serviceType": "idcard",
    "birthPlace": "Addis Ababa",
}


@pytest.fixture(scope="module")
def portal_server():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=PORTAL_DIR
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8901), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


@pytest.fixture()
def api(monkeypatch):
    """Fresh gateway TestClient + clean state, mirroring test_gateway."""
    monkeypatch.setenv("GATEWAY_API_KEY", "test-key")
    import importlib
    import gateway as gw
    importlib.reload(gw)
    from fastapi.testclient import TestClient

    with TestClient(gw.app) as client:
        yield client, gw


def headers(session="wapi-1"):
    return {
        "X-Ethio-Session": session,
        "Authorization": "Bearer test-key",
    }


def start_worker_job(client, session="wapi-1", inputs=None):
    r = client.post("/tasks", json={
        "goal": "fill the mock passport form and pay",
        "inputs": inputs or INPUTS,
        "session_id": session,
        "runner": "worker",
    }, headers=headers(session))
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def wait_for_state(client, job_id, session, states, timeout=30):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/tasks/status/{job_id}", headers=headers(session))
        assert r.status_code == 200, r.text
        last = r.json()
        if last["state"] in states:
            return last
        time.sleep(0.25)
    raise AssertionError(
        f"job did not reach {states} in {timeout}s; last={last}"
    )


def pending_approval(client, gw, job_id, session):
    r = client.get("/approvals/pending", headers=headers(session))
    assert r.status_code == 200
    mine = [a for a in r.json()["approvals"] if a["job_id"] == job_id]
    assert mine, "expected a pending approval for the job"
    return mine[-1]


# 1+2+3+4: task reaches worker; safe actions verified; protected pauses;
# API reports waiting_approval.
def test_api_01_worker_pauses_at_protected_action(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client)
    status = wait_for_state(
        client, job_id, "wapi-1", {"waiting_approval"}, timeout=40
    )
    assert status["state"] == "waiting_approval"
    log = "\n".join(status["log"])
    # Safe actions executed and verified before the pause.
    assert "fullName" in log
    assert "worker paused" in log
    # The protected payment was NOT executed: approval still unconsumed.
    approval = pending_approval(client, gw, job_id, "wapi-1")
    assert approval["action_type"] == "payment"
    assert approval["state"] == "pending"
    assert not approval["consumed"]


# 5+8: approval permits the exact action; verified result reaches the API.
def test_api_02_approve_resumes_and_completes(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client, session="wapi-2")
    wait_for_state(client, job_id, "wapi-2", {"waiting_approval"}, timeout=40)
    approval = pending_approval(client, gw, job_id, "wapi-2")
    r = client.post(
        f"/approvals/{approval['approval_id']}/decide",
        json={"approve": True, "session_id": "wapi-2"},
        headers=headers("wapi-2"),
    )
    assert r.status_code == 200
    assert r.json()["state"] == "approved"
    status = wait_for_state(
        client, job_id, "wapi-2", {"succeeded", "failed"}, timeout=40
    )
    assert status["state"] == "succeeded", status["log"]
    log = "\n".join(status["log"])
    assert "payment: succeeded" in log or "approved action payment" in log
    # Evidence endpoint serves the verified result.
    r = client.get(f"/tasks/evidence/{job_id}", headers=headers("wapi-2"))
    assert r.status_code == 200
    assert r.json()["final_result"]


# 6: rejection prevents execution and stops the task.
def test_api_03_reject_stops_task(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client, session="wapi-3")
    wait_for_state(client, job_id, "wapi-3", {"waiting_approval"}, timeout=40)
    approval = pending_approval(client, gw, job_id, "wapi-3")
    r = client.post(
        f"/approvals/{approval['approval_id']}/decide",
        json={"approve": False, "reason": "not now",
              "session_id": "wapi-3"},
        headers=headers("wapi-3"),
    )
    assert r.status_code == 200
    status = wait_for_state(
        client, job_id, "wapi-3", {"failed"}, timeout=20
    )
    assert "rejected" in "\n".join(status["log"])
    # Execute attempt after rejection is denied.
    r = client.post(
        f"/approvals/{approval['approval_id']}/execute",
        json={"job_id": job_id, "action_type": "payment",
              "params": {"selector": "#btn-pay",
                          "verify_visible": "#pay-ok", "amount": "200"},
              "session_id": "wapi-3"},
        headers=headers("wapi-3"),
    )
    assert r.status_code == 409


# 7: expiry prevents stale execution and fails the waiting job.
def test_api_04_expiry_fails_task(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client, session="wapi-4")
    wait_for_state(client, job_id, "wapi-4", {"waiting_approval"}, timeout=40)
    approval = pending_approval(client, gw, job_id, "wapi-4")
    # Force expiry (simulates the TTL elapsing).
    gw._approval_service._approvals[approval["approval_id"]].expires_at = 0
    r = client.post(
        f"/approvals/{approval['approval_id']}/decide",
        json={"approve": True, "session_id": "wapi-4"},
        headers=headers("wapi-4"),
    )
    assert r.status_code == 409
    status = wait_for_state(
        client, job_id, "wapi-4", {"failed"}, timeout=20
    )
    assert "expired" in "\n".join(status["log"])


# 9: duplicate decision / competing execute cannot run the action twice.
def test_api_05_no_double_execution(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client, session="wapi-5")
    wait_for_state(client, job_id, "wapi-5", {"waiting_approval"}, timeout=40)
    approval = pending_approval(client, gw, job_id, "wapi-5")
    aid = approval["approval_id"]
    r = client.post(
        f"/approvals/{aid}/decide",
        json={"approve": True, "session_id": "wapi-5"},
        headers=headers("wapi-5"),
    )
    assert r.status_code == 200
    # Duplicate decision: denied.
    r = client.post(
        f"/approvals/{aid}/decide",
        json={"approve": True, "session_id": "wapi-5"},
        headers=headers("wapi-5"),
    )
    assert r.status_code == 409
    wait_for_state(
        client, job_id, "wapi-5", {"succeeded", "failed"}, timeout=40
    )
    # Direct execute after the worker already claimed: denied.
    r = client.post(
        f"/approvals/{aid}/execute",
        json={"job_id": job_id, "action_type": "payment",
              "params": {"selector": "#btn-pay",
                          "verify_visible": "#pay-ok", "amount": "200"},
              "session_id": "wapi-5"},
        headers=headers("wapi-5"),
    )
    assert r.status_code == 409


# 10: uncertain post-dispatch outcome (worker session lost) -> safe failure,
# never silent completion, action not repeated.
def test_api_06_restart_loses_session_safely(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client, session="wapi-6")
    wait_for_state(client, job_id, "wapi-6", {"waiting_approval"}, timeout=40)
    approval = pending_approval(client, gw, job_id, "wapi-6")
    # Simulate process restart: the live browser session is gone.
    job = gw._JOBS[job_id]
    saved_ctx = job.worker_ctx
    job.worker_ctx = None
    r = client.post(
        f"/approvals/{approval['approval_id']}/decide",
        json={"approve": True, "session_id": "wapi-6"},
        headers=headers("wapi-6"),
    )
    assert r.status_code == 200
    status = wait_for_state(
        client, job_id, "wapi-6", {"failed"}, timeout=20
    )
    log = "\n".join(status["log"])
    assert "session lost" in log
    # The approval was never claimed/executed by the lost worker.
    stored = gw._approval_service._approvals[approval["approval_id"]]
    assert not stored.consumed
    # Cleanup the real browser session we detached.
    if saved_ctx and saved_ctx.get("browser") is not None:
        import asyncio
        async def _cleanup():
            try:
                await saved_ctx["browser"].close()
            except Exception:
                pass
            try:
                await saved_ctx["playwright"].stop()
            except Exception:
                pass
        asyncio.get_event_loop().run_until_complete(_cleanup()) \
            if False else None  # browser process exits with test session


# 11: another user cannot read or control the task.
def test_api_07_cross_user_isolation(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client, session="wapi-7a")
    wait_for_state(client, job_id, "wapi-7a", {"waiting_approval"}, timeout=40)
    # Status: 404 for another session.
    r = client.get(f"/tasks/status/{job_id}", headers=headers("wapi-7b"))
    assert r.status_code == 404
    # Pending approvals: invisible.
    r = client.get("/approvals/pending", headers=headers("wapi-7b"))
    assert r.json()["approvals"] == []
    # Cancel: denied.
    r = client.post(
        f"/tasks/cancel/{job_id}",
        json={"session_id": "wapi-7b"},
        headers=headers("wapi-7b"),
    )
    assert r.status_code == 404
    # Cleanup: cancel as the owner.
    client.post(
        f"/tasks/cancel/{job_id}",
        json={"session_id": "wapi-7a"},
        headers=headers("wapi-7a"),
    )


# P3: duplicate worker job for the same session is refused while active.
def test_api_08_duplicate_session_job_refused(api, portal_server):
    client, gw = api
    job_id = start_worker_job(client, session="wapi-8")
    # Job is active (paused at its protected action) — a second job for
    # the same session must be refused, and cancelling the paused job
    # is a clean, terminal operation.
    wait_for_state(client, job_id, "wapi-8", {"waiting_approval"}, timeout=40)
    r = client.post("/tasks", json={
        "goal": "second job", "inputs": INPUTS,
        "session_id": "wapi-8", "runner": "worker",
    }, headers=headers("wapi-8"))
    assert r.status_code == 409
    r = client.post(
        f"/tasks/cancel/{job_id}",
        json={"session_id": "wapi-8"},
        headers=headers("wapi-8"),
    )
    assert r.status_code == 200
    status = wait_for_state(
        client, job_id, "wapi-8", {"cancelled"}, timeout=20
    )
    assert status["state"] == "cancelled"
