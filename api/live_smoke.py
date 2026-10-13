#!/usr/bin/env python3
"""ETHIO live development smoke test — runs the pilot scenarios against
the LIVE development Supabase project (mock portal only; no real data).

This is the live counterpart of api/test_pilot_e2e.py (which proves the
same flow against a local Postgres standing in for Supabase).

Configuration comes ONLY from ~/ethio-pilot.env (override the path with
the ETHIO_PILOT_ENV environment variable). Required keys:

    SUPABASE_URL=https://<project-ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key — server only>
    PILOT_A_EMAIL=...            PILOT_A_PASSWORD=...
    PILOT_B_EMAIL=...            PILOT_B_PASSWORD=...
    PILOT_CONFIRM_PROJECT=<project-ref>   (typo guard: must match the
                                           ref inside SUPABASE_URL)

Secrets are read into memory only: never printed, never logged, never
written anywhere else. The run ends by scanning the captured gateway
log and asserting that none of the secrets appear in it.

Usage:
    python live_smoke.py --check-env   # validate the env file only
    python live_smoke.py               # run the full live smoke test

Exit codes: 0 = all scenarios passed (or env OK), 2 = env problem,
1 = a scenario failed.
"""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
API_DIR = REPO / "api"
VENV_PY = Path.home() / "workspace" / "ethio-live-venv" / "bin" / "python"
PORTAL_PORT = 8901  # MockPortalDriver's origin allowlist is fixed to this

INPUTS = {
    "fullName": "Test User",
    "dob": "1990-01-01",
    "phone": "0911123456",
    "nationalId": "12345678",
    "serviceType": "idcard",
    "birthPlace": "Addis Ababa",
}

REQUIRED_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "PILOT_A_EMAIL",
    "PILOT_A_PASSWORD",
    "PILOT_B_EMAIL",
    "PILOT_B_PASSWORD",
    "PILOT_CONFIRM_PROJECT",
]

RESULTS: list[tuple[str, bool, str]] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def load_env() -> dict[str, str]:
    path = Path(os.environ.get("ETHIO_PILOT_ENV", Path.home() / "ethio-pilot.env"))
    if not path.exists():
        print(f"env file not found: {path}")
        print("create it (chmod 600) with keys: " + ", ".join(REQUIRED_KEYS))
        sys.exit(2)
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing:
        print("env file is missing keys (names only): " + ", ".join(missing))
        sys.exit(2)
    ref = re.search(r"https://([a-z0-9]+)\.supabase\.co", env["SUPABASE_URL"])
    if not ref:
        print("SUPABASE_URL does not look like a Supabase project URL")
        sys.exit(2)
    if ref.group(1) != env["PILOT_CONFIRM_PROJECT"]:
        print("PILOT_CONFIRM_PROJECT does not match the ref in SUPABASE_URL — refusing")
        sys.exit(2)
    env["_PROJECT_REF"] = ref.group(1)
    return env


def check_env() -> None:
    env = load_env()
    print(f"env OK — project ref {env['_PROJECT_REF']}, all required keys present")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Live Supabase helpers (service key stays in memory, server-side only)
# ---------------------------------------------------------------------------


def _ext_client() -> httpx.Client:
    """Client for LIVE Supabase calls: honors the egress proxy and the
    system CA bundle (this sandbox's proxy presents its own CA chain).
    Loopback clients elsewhere in this file stay proxy-free."""
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or None
    )
    bundle = "/etc/ssl/certs/ca-certificates.crt"
    verify = os.environ.get("SSL_CERT_FILE") or (
        bundle if os.path.exists(bundle) else True
    )
    return httpx.Client(proxy=proxy, trust_env=False, timeout=30.0,
                        verify=verify)


def sign_in(env: dict[str, str], who: str) -> tuple[str, str]:
    """Password-grant sign-in. Returns (access_token, user_id)."""
    with _ext_client() as c:
        res = c.post(
            f"{env['SUPABASE_URL']}/auth/v1/token?grant_type=password",
            headers={"apikey": env["SUPABASE_SERVICE_KEY"],
                     "Content-Type": "application/json"},
            json={"email": env[f"PILOT_{who}_EMAIL"],
                  "password": env[f"PILOT_{who}_PASSWORD"]},
        )
    if res.status_code != 200:
        raise RuntimeError(f"sign-in {who} failed: HTTP {res.status_code}")
    body = res.json()
    return body["access_token"], body["user"]["id"]


def rest(env: dict[str, str], path: str) -> list:
    with _ext_client() as c:
        res = c.get(
            f"{env['SUPABASE_URL']}/rest/v1/{path}",
            headers={"apikey": env["SUPABASE_SERVICE_KEY"],
                     "Authorization": f"Bearer {env['SUPABASE_SERVICE_KEY']}"},
        )
    res.raise_for_status()
    return res.json()


# ---------------------------------------------------------------------------
# Local stack (mock portal + gateway in supabase durable mode)
# ---------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stack:
    def __init__(self, env: dict[str, str]):
        self.env = env
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.portal: subprocess.Popen | None = None
        self.gateway: subprocess.Popen | None = None
        self.log_path = Path("/tmp/ethio-live-smoke-gateway.log")

    def start_portal(self) -> None:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", PORTAL_PORT)) == 0:
                raise RuntimeError(f"port {PORTAL_PORT} is busy — stop the other portal first")
        self.portal = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(PORTAL_PORT),
             "--directory", str(REPO / "mobile" / "mock-portal")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                r = httpx.get(f"http://127.0.0.1:{PORTAL_PORT}/index.html",
                              trust_env=False, timeout=5)
                if r.status_code == 200 and "pay-receipt" in r.text:
                    return
            except Exception:
                pass
            time.sleep(0.2)
        raise RuntimeError("mock portal did not come up")

    def start_gateway(self) -> None:
        genv = dict(os.environ)
        genv.update({
            "GATEWAY_API_KEY": "live-smoke-local-key",
            "ETHIO_AUTH_MODE": "jwt",
            "ETHIO_TASK_STORE": "supabase",
            "ETHIO_USE_SUPABASE": "1",  # belt & braces; the factory now
            # also follows ETHIO_TASK_STORE=supabase on its own (Phase 12 fix)
            "SUPABASE_URL": self.env["SUPABASE_URL"],
            "SUPABASE_SERVICE_KEY": self.env["SUPABASE_SERVICE_KEY"],
            "PLAYWRIGHT_BROWSERS_PATH": str(Path.home() / ".cache" / "ms-playwright"),
        })
        genv.pop("SUPABASE_JWT_SECRET", None)  # live project is ES256/JWKS
        # The gateway's Supabase clients honor SSL_CERT_FILE; point it
        # at the system bundle so TLS verifies through an egress proxy
        # presenting its own CA chain (this sandbox). Proxy variables
        # are already inherited from os.environ above.
        bundle = "/etc/ssl/certs/ca-certificates.crt"
        if os.path.exists(bundle):
            genv.setdefault("SSL_CERT_FILE", bundle)
        self._log = open(self.log_path, "ab")
        self.gateway = subprocess.Popen(
            [str(VENV_PY), "-m", "uvicorn", "gateway:app", "--port", str(self.port)],
            cwd=API_DIR, env=genv, stdout=self._log, stderr=self._log)
        c = httpx.Client(trust_env=False, timeout=10)
        for _ in range(100):
            try:
                if c.get(f"{self.base}/health").status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.3)
        raise RuntimeError("gateway did not come up")

    def stop_gateway(self) -> None:
        if self.gateway:
            self.gateway.send_signal(signal.SIGTERM)
            try:
                self.gateway.wait(timeout=15)
            except Exception:
                self.gateway.kill()
            self.gateway = None

    def stop_all(self) -> None:
        self.stop_gateway()
        if self.portal:
            self.portal.terminate()
            self.portal = None


# ---------------------------------------------------------------------------
# Gateway client + scenario flow (mirrors api/test_pilot_e2e.py)
# ---------------------------------------------------------------------------


def client(stack: Stack, token: str | None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(trust_env=False, base_url=stack.base,
                        headers=headers, timeout=30.0)


def start_task(stack: Stack, token: str) -> str:
    res = client(stack, token).post("/tasks", json={
        "goal": "Prepare my ID renewal (live pilot)",
        "inputs": INPUTS, "runner": "worker", "session_id": "pilot",
    }, headers={"X-Ethio-Session": "pilot"})
    assert res.status_code == 202, res.text
    return res.json()["job_id"]


def wait_state(stack: Stack, token: str, job_id: str,
               states: set[str], timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        res = client(stack, token).get(f"/tasks/status/{job_id}")
        assert res.status_code == 200, res.text
        last = res.json()
        if last["state"] in states:
            return last
        time.sleep(0.5)
    raise AssertionError(f"job never reached {states}: {last}")


def pending(stack: Stack, token: str) -> list:
    res = client(stack, token).get("/approvals/pending")
    assert res.status_code == 200, res.text
    return res.json()["approvals"]


def main() -> None:
    if "--check-env" in sys.argv:
        check_env()
    env = load_env()
    print(f"live smoke against project ref {env['_PROJECT_REF']} (mock portal only)")

    tok_a = tok_b = uid_a = uid_b = ""
    try:
        tok_a, uid_a = sign_in(env, "A")
        tok_b, uid_b = sign_in(env, "B")
        report("sign-in pilot-a and pilot-b (live Auth)", True)
    except Exception as exc:
        report("sign-in pilot-a and pilot-b (live Auth)", False, str(exc))
        finish(env, tok_a, tok_b)

    # Profile trigger: both users must have auto-provisioned profiles.
    try:
        profiles = rest(env, "profiles?select=id")
        ids = {row["id"] for row in profiles}
        ok = uid_a in ids and uid_b in ids
        report("profile trigger provisioned both users (live)", ok,
               f"{len(profiles)} profile rows")
    except Exception as exc:
        report("profile trigger provisioned both users (live)", False, str(exc))

    stack = Stack(env)
    try:
        stack.start_portal()
        stack.start_gateway()

        # S1 — unauthenticated fails closed.
        ok = (client(stack, None).post("/tasks", json={}).status_code == 401
              and client(stack, "not-a-token").get("/approvals/pending").status_code == 401)
        report("S1 unauthenticated/garbage requests rejected (401)", ok)

        # S2+S3+S4 — task 1: A waits; B fully isolated; A rejects.
        job1 = start_task(stack, tok_a)
        wait_state(stack, tok_a, job1, {"waiting_approval"})
        mine = pending(stack, tok_a)
        assert len(mine) == 1 and mine[0]["job_id"] == job1
        approval1 = mine[0]["approval_id"]
        report("S2 user A task reaches waiting_approval; A can inspect it", True)

        isolated = (
            pending(stack, tok_b) == []
            and client(stack, tok_b).get(f"/tasks/status/{job1}").status_code == 404
            and client(stack, tok_b).post(
                f"/approvals/{approval1}/decide",
                json={"approve": True}).status_code in (404, 409)
            and client(stack, tok_b).post(
                f"/approvals/{approval1}/execute",
                json={"job_id": job1, "action_type": "payment",
                      "session_id": "pilot"}).status_code == 404)
        report("S3 user B cannot see, decide, or execute A's task", isolated)

        res = client(stack, tok_a).post(
            f"/approvals/{approval1}/decide",
            json={"approve": False, "reason": "live pilot reject"})
        assert res.status_code == 200, res.text
        final1 = wait_state(stack, tok_a, job1, {"failed", "succeeded"})
        rows = rest(env, f"approvals?approval_id=eq.{approval1}"
                         "&select=state,consumed,execution_state")
        db_ok = (len(rows) == 1 and rows[0]["state"] == "rejected"
                 and rows[0]["consumed"] is False
                 and rows[0]["execution_state"] == "not_started")
        report("S4 reject -> job failed, approval unconsumed, nothing executed",
               final1["state"] == "failed" and db_ok)

        # S5 — task 2: approve -> completes with a verified result.
        job2 = start_task(stack, tok_a)
        wait_state(stack, tok_a, job2, {"waiting_approval"})
        approval2 = pending(stack, tok_a)[0]["approval_id"]
        res = client(stack, tok_a).post(
            f"/approvals/{approval2}/decide", json={"approve": True})
        assert res.status_code == 200, res.text
        final2 = wait_state(stack, tok_a, job2, {"succeeded", "failed"})
        rows = rest(env, f"approvals?approval_id=eq.{approval2}"
                         "&select=state,consumed,execution_state")
        jobs = rest(env, "agent_jobs?session_id=eq.pilot&state=eq.succeeded"
                         "&select=state,final_result")
        db_ok = (len(rows) == 1 and rows[0]["consumed"] is True
                 and rows[0]["execution_state"] == "succeeded"
                 and any(j.get("final_result") for j in jobs))
        report("S5 approve -> job succeeded with verified result (DB-checked)",
               final2["state"] == "succeeded" and db_ok)

        # S6 — restart while waiting: restored, approval not consumed,
        # approving a dead session fails safely.
        job3 = start_task(stack, tok_a)
        wait_state(stack, tok_a, job3, {"waiting_approval"})
        approval3 = pending(stack, tok_a)[0]["approval_id"]
        stack.stop_gateway()
        stack.start_gateway()
        restored = client(stack, tok_a).get(f"/tasks/status/{job3}")
        assert restored.status_code == 200 and restored.json()["state"] == "waiting_approval"
        res = client(stack, tok_a).post(
            f"/approvals/{approval3}/decide", json={"approve": True})
        assert res.status_code == 200, res.text
        final3 = wait_state(stack, tok_a, job3, {"failed", "succeeded"})
        rows = rest(env, f"approvals?approval_id=eq.{approval3}"
                         "&select=consumed,execution_state")
        db_ok = (len(rows) == 1 and rows[0]["consumed"] is False
                 and rows[0]["execution_state"] == "not_started")
        blob = json.dumps(final3).lower()
        report("S6 restart -> waiting job restored; approval on dead session "
               "fails safely, never consumed",
               final3["state"] == "failed" and db_ok
               and ("session lost" in blob or "restart" in blob))
    except Exception as exc:
        report("scenario flow completed without harness errors", False, str(exc))
    finally:
        stack.stop_all()

    finish(env, tok_a, tok_b)


def finish(env: dict[str, str], *tokens: str) -> None:
    # S7 — the captured gateway log must contain no secret material.
    try:
        log = Path("/tmp/ethio-live-smoke-gateway.log").read_text(errors="ignore")
        secrets = [env["SUPABASE_SERVICE_KEY"], env["PILOT_A_PASSWORD"],
                   env["PILOT_B_PASSWORD"], *[t for t in tokens if t]]
        leaked = any(s and s in log for s in secrets)
        report("S7 gateway log contains no passwords, tokens, or keys", not leaked)
    except Exception as exc:
        report("S7 gateway log contains no passwords, tokens, or keys", False, str(exc))
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} live scenarios passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
