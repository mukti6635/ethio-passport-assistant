"""Transport-contract tests for SupabaseTaskStore.

A local HTTP stub emulates the PostgREST RPC endpoints the store
calls. This verifies request shapes (RPC names, parameter names,
service-role headers) and response handling (row parsing, id
normalization, error-code mapping) WITHOUT a Supabase project. The
SQL semantics behind those RPCs are verified for real in
test_task_store_pg.py; live Supabase verification remains outstanding
and is not claimed here.

Run: ~/workspace/ethio-live-venv/bin/python -m pytest api/test_supabase_task_store.py -q
"""

import http.server
import json
import os
import sys
import threading
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from task_store import (
    DuplicateActiveJob,
    InvalidTransition,
    SupabaseTaskStore,
)

OWNER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
JOB_UUID = "12345678-1234-1234-1234-123456789abc"
JOB_HEX = JOB_UUID.replace("-", "")


def job_row(state="queued"):
    return {
        "id": JOB_UUID,
        "owner_id": OWNER,
        "session_id": "sess-1",
        "goal": "Renew ID card",
        "inputs": {"fullName": "Test User"},
        "state": state,
        "log": [],
        "checkpoint": None,
        "final_result": None,
        "error": None,
        "evidence": None,
        "runner": "worker",
        "created_at": "2026-10-13T00:00:00+00:00",
        "started_at": None,
        "ended_at": None,
    }


class _Stub:
    """Scriptable PostgREST stub. `script` maps RPC name -> (status, payload)."""

    def __init__(self):
        self.script = {}
        self.requests = []

    def handler(self, req):
        length = int(req.headers.get("Content-Length") or 0)
        body = json.loads(req.rfile.read(length) or b"{}")
        self.requests.append({
            "path": req.path,
            "headers": dict(req.headers),
            "body": body,
        })
        fn = req.path.rsplit("/", 1)[-1].split("?")[0]
        status, payload = self.script.get(fn, (200, []))
        data = json.dumps(payload).encode()
        req.send_response(status)
        req.send_header("Content-Type", "application/json")
        req.send_header("Content-Length", str(len(data)))
        req.end_headers()
        req.wfile.write(data)


@pytest.fixture()
def stub():
    s = _Stub()
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), lambda *a, **kw: _Handler(s, *a, **kw)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield s
    server.shutdown()


class _Handler(http.server.BaseHTTPRequestHandler):
    def __init__(self, stub, *a, **kw):
        self._stub = stub
        super().__init__(*a, **kw)

    def do_POST(self):
        self._stub.handler(self)

    def do_GET(self):
        self._stub.handler(self)

    def do_PATCH(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


def record():
    return {
        "job_id": JOB_HEX,
        "owner_key": OWNER,
        "session_id": "sess-1",
        "goal": "Renew ID card",
        "inputs": {"fullName": "Test User"},
        "state": "queued",
        "log": [],
        "checkpoint": None,
        "final_result": None,
        "error": None,
        "evidence": None,
        "runner": "worker",
        "created_at": time.time(),
        "started_at": None,
        "ended_at": None,
    }


def test_sb_01_create_calls_rpc_and_parses_row(stub):
    stub.script["create_agent_job"] = (200, [job_row()])
    store = SupabaseTaskStore(stub.url, "service-key-xyz")
    created = store.create(record())
    assert created["job_id"] == JOB_HEX  # dashes normalized to gateway hex
    assert created["state"] == "queued"
    req = stub.requests[-1]
    assert req["path"].endswith("/rest/v1/rpc/create_agent_job")
    assert req["body"]["p_owner_id"] == OWNER
    assert req["body"]["p_id"] == JOB_UUID
    # Service-role credentials travel in headers, server-side only.
    lowered = {k.lower(): v for k, v in req["headers"].items()}
    assert lowered.get("authorization") == "Bearer service-key-xyz"
    assert lowered.get("apikey") == "service-key-xyz"


def test_sb_02_create_duplicate_maps_23505(stub):
    stub.script["create_agent_job"] = (409, {"code": "23505", "message": "dup"})
    store = SupabaseTaskStore(stub.url, "k")
    with pytest.raises(DuplicateActiveJob):
        store.create(record())


def test_sb_03_transition_cas_and_invalid(stub):
    store = SupabaseTaskStore(stub.url, "k")
    # CAS lost: RPC returns no row -> None (not an exception).
    stub.script["transition_agent_job"] = (200, [])
    assert store.transition(JOB_HEX, OWNER, "queued", "running") is None
    # Invalid transition is rejected client-side before any HTTP call.
    with pytest.raises(InvalidTransition):
        store.transition(JOB_HEX, OWNER, "queued", "succeeded",
                         {"final_result": "x"})
    # Succeeded without a verified result never leaves the process.
    with pytest.raises(InvalidTransition):
        store.transition(JOB_HEX, OWNER, "running", "succeeded")
    # Server-side rejection (23514) also maps to InvalidTransition.
    stub.script["transition_agent_job"] = (400, {"code": "23514"})
    with pytest.raises(InvalidTransition):
        store.transition(JOB_HEX, OWNER, "running", "paused")


def test_sb_04_get_and_missing_rpc_fails_loudly(stub):
    stub.script["get_agent_job"] = (200, [job_row(state="waiting_approval")])
    store = SupabaseTaskStore(stub.url, "k")
    got = store.get(JOB_HEX, OWNER)
    assert got["state"] == "waiting_approval"
    # Missing RPC (migration not applied) must raise, never fall back.
    stub.script["get_agent_job"] = (404, {"code": "PGRST202"})
    with pytest.raises(RuntimeError, match="migrations 003 \\+ 005"):
        store.get(JOB_HEX, OWNER)


def test_sb_05_approval_store_follows_supabase_task_store(monkeypatch):
    """Phase 12 regression (found by the live smoke): with
    ETHIO_TASK_STORE=supabase the approval factory used to fall through
    to the in-memory store unless ETHIO_USE_SUPABASE=1 was also set —
    durable jobs with memory approvals, a silent split-brain. The
    task-store switch must select the Supabase approval store too."""
    from persistence import SupabaseApprovalStore, build_approval_store

    monkeypatch.setenv("ETHIO_TASK_STORE", "supabase")
    monkeypatch.delenv("ETHIO_USE_SUPABASE", raising=False)
    monkeypatch.delenv("ETHIO_APPROVAL_STORE", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    assert isinstance(build_approval_store(), SupabaseApprovalStore)
    # Same selection, missing credentials: fail fast, never memory.
    monkeypatch.delenv("SUPABASE_SERVICE_KEY")
    with pytest.raises(RuntimeError, match="approval storage requested"):
        build_approval_store()
