"""api/test_cors.py — CORS is opt-in via ETHIO_CORS_ORIGINS (Phase 11).

The gateway serves native apps (no CORS) by default. The Flutter web
pilot needs explicit origins. These tests run the import in a
subprocess because the middleware is wired at import time from the
environment, and they verify actual response headers with TestClient
inside that subprocess.

Run: pytest api/test_cors.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

API_DIR = os.path.dirname(os.path.abspath(__file__))

_PROBE = r"""
import json, os
import gateway
from fastapi.testclient import TestClient

client = TestClient(gateway.app)
origin = os.environ.get("PROBE_ORIGIN", "")
headers = {"Origin": origin} if origin else {}
res = client.get("/health", headers=headers)
pre = client.options(
    "/tasks", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization",
    }) if origin else None
print(json.dumps({
    "origins": gateway._cors_origins(),
    "acao": res.headers.get("access-control-allow-origin"),
    "preflight_acao": (pre.headers.get("access-control-allow-origin")
                       if pre is not None else None),
    "preflight_status": pre.status_code if pre is not None else None,
}))
"""


def _probe(env_extra: dict, origin: str = "") -> dict:
    env = dict(os.environ)
    env.pop("ETHIO_CORS_ORIGINS", None)
    env.update(env_extra)
    if origin:
        env["PROBE_ORIGIN"] = origin
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=API_DIR, env=env,
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_no_env_means_no_cors_headers():
    r = _probe({}, origin="http://localhost:8080")
    assert r["origins"] == []
    assert r["acao"] is None
    assert r["preflight_acao"] is None


def test_listed_origin_gets_headers_and_preflight():
    r = _probe({"ETHIO_CORS_ORIGINS": "http://localhost:8080"},
               origin="http://localhost:8080")
    assert r["origins"] == ["http://localhost:8080"]
    assert r["acao"] == "http://localhost:8080"
    assert r["preflight_status"] == 200
    assert r["preflight_acao"] == "http://localhost:8080"


def test_unlisted_origin_gets_nothing():
    r = _probe({"ETHIO_CORS_ORIGINS": "http://localhost:8080"},
               origin="https://evil.example")
    assert r["acao"] is None
    assert r["preflight_acao"] is None


def test_wildcard_is_refused():
    r = _probe({"ETHIO_CORS_ORIGINS": "*"}, origin="https://x.example")
    assert r["origins"] == []
    assert r["acao"] is None
