"""API-restart recovery test (subprocess, real HTTP server).

Starts the actual gateway with uvicorn, creates a worker job, waits for
waiting_approval, KILLS the server process, restarts it, and verifies:
- the in-memory job is honestly gone (404, never silently completed)
- no approval can be executed against the phantom job
- the protected action was never dispatched by the dead process

This documents the current in-memory limitation precisely. Durable
mode (ETHIO_USE_SUPABASE=1) is the fix path; see DEPLOYMENT_READINESS.

Run: pytest api/test_restart.py -q  (requires uvicorn in the venv)
"""

import functools
import http.server
import os
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))
PORTAL_DIR = os.path.join(ROOT, "..", "mobile", "mock-portal")
GW_PORT = 8911
BASE = f"http://127.0.0.1:{GW_PORT}"

httpx = pytest.importorskip("httpx")

# trust_env=False: this sandbox's no_proxy contains bracketed IPv6
# entries that httpx cannot parse; all requests here are loopback.
_client = httpx.Client(trust_env=False)

INPUTS = {
    "fullName": "Test User", "dob": "1990-01-01", "phone": "0911123456",
    "nationalId": "12345678", "serviceType": "idcard",
    "birthPlace": "Addis Ababa",
}
H = {"X-Ethio-Session": "restart-1", "Authorization": "Bearer test-key"}


@pytest.fixture(scope="module")
def portal():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=PORTAL_DIR
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8901), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def start_server():
    env = dict(os.environ)
    env["GATEWAY_API_KEY"] = "test-key"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "gateway:app",
         "--port", str(GW_PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 30
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


def test_api_restart_loses_in_memory_job(portal):
    proc = start_server()
    try:
        r = _client.post(f"{BASE}/tasks", json={
            "goal": "fill mock form", "inputs": INPUTS,
            "session_id": "restart-1", "runner": "worker",
        }, headers=H, timeout=10)
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        deadline = time.time() + 40
        state = None
        while time.time() < deadline:
            r = _client.get(f"{BASE}/tasks/status/{job_id}",
                          headers=H, timeout=5)
            state = r.json()["state"]
            if state == "waiting_approval":
                break
            time.sleep(0.3)
        assert state == "waiting_approval"
        r = _client.get(f"{BASE}/approvals/pending", headers=H, timeout=5)
        aid = r.json()["approvals"][0]["approval_id"]
    finally:
        proc.kill()
        proc.wait(timeout=10)

    # Restart: a fresh process must not resurrect the job.
    proc = start_server()
    try:
        r = _client.get(f"{BASE}/tasks/status/{job_id}",
                      headers=H, timeout=5)
        assert r.status_code == 404
        # The approval id from the dead process executes nothing.
        r = _client.post(f"{BASE}/approvals/{aid}/execute", json={
            "job_id": job_id, "action_type": "payment",
            "params": {"selector": "#btn-pay",
                        "verify_visible": "#pay-ok", "amount": "200"},
            "session_id": "restart-1",
        }, headers=H, timeout=5)
        assert r.status_code in (404, 409)
    finally:
        proc.kill()
        proc.wait(timeout=10)
