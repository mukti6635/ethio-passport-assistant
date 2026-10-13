"""Mock-portal load test for ETHIO worker jobs (measurement, not a gate).

Starts the real gateway (uvicorn subprocess) + the local mock portal,
then runs N concurrent worker jobs (one session each, since the gateway
allows one active job per session). Every job: fill 6 fields, navigate
to checkpoints, pause at the protected payment. The harness then
approves all and measures completion.

Reports per-level: success/failure counts, wall time, per-job latency
median/p95, and peak system memory used. This measures THIS sandbox
(8 GB RAM); it does not establish production capacity.

Usage:
  python api/load_test.py [levels...]     e.g. python api/load_test.py 3 6
"""

import functools
import http.server
import json
import os
import statistics
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))
PORTAL_DIR = os.path.join(ROOT, "..", "mobile", "mock-portal")
GW_PORT = 8913
BASE = f"http://127.0.0.1:{GW_PORT}"

import httpx

client = httpx.Client(trust_env=False, timeout=15)

INPUTS = {
    "fullName": "Load User", "dob": "1990-01-01", "phone": "0911123456",
    "nationalId": "12345678", "serviceType": "idcard",
    "birthPlace": "Addis Ababa",
}


def mem_used_mb():
    with open("/proc/meminfo") as f:
        info = dict(
            line.split(":", 1) for line in f if ":" in line
        )
    total = int(info["MemTotal"].split()[0])
    avail = int(info["MemAvailable"].split()[0])
    return (total - avail) // 1024


def headers(session):
    return {"X-Ethio-Session": session,
            "Authorization": "Bearer test-key"}


def run_level(n, server_proc):
    sessions = [f"load-{i}" for i in range(n)]
    created = {}
    start = time.time()
    for s in sessions:
        r = client.post(f"{BASE}/tasks", json={
            "goal": "load: fill mock form and pay", "inputs": INPUTS,
            "session_id": s, "runner": "worker",
        }, headers=headers(s))
        assert r.status_code == 202, r.text
        created[s] = {"job_id": r.json()["job_id"], "t0": time.time()}
    # Wait for all to reach waiting_approval.
    pending = dict(created)
    deadline = time.time() + 180
    while pending and time.time() < deadline:
        for s in list(pending):
            r = client.get(
                f"{BASE}/tasks/status/{pending[s]['job_id']}",
                headers=headers(s),
            )
            st = r.json()["state"]
            if st == "waiting_approval":
                pending[s]["t_pause"] = time.time()
                del pending[s]
            elif st in ("failed", "cancelled", "timed_out"):
                pending[s]["failed_at_pause"] = st
                del pending[s]
        if pending:
            time.sleep(0.3)
    peak_mem = mem_used_mb()
    # Approve all.
    for s, rec in created.items():
        if "t_pause" not in rec:
            continue
        r = client.get(f"{BASE}/approvals/pending", headers=headers(s))
        mine = [a for a in r.json()["approvals"]
                if a["job_id"] == rec["job_id"]]
        if not mine:
            rec["failed_at_pause"] = "no approval found"
            continue
        aid = mine[-1]["approval_id"]
        r = client.post(f"{BASE}/approvals/{aid}/decide", json={
            "approve": True, "session_id": s,
        }, headers=headers(s))
        assert r.status_code == 200, r.text
    # Wait for terminal states.
    remaining = {s: r for s, r in created.items() if "t_pause" in r}
    deadline = time.time() + 180
    while remaining and time.time() < deadline:
        for s in list(remaining):
            r = client.get(
                f"{BASE}/tasks/status/{remaining[s]['job_id']}",
                headers=headers(s),
            )
            st = r.json()["state"]
            if st in ("succeeded", "failed", "cancelled", "timed_out"):
                remaining[s]["final"] = st
                remaining[s]["t_end"] = time.time()
                del remaining[s]
        if remaining:
            time.sleep(0.3)
    wall = time.time() - start
    succeeded = sum(1 for r in created.values()
                    if r.get("final") == "succeeded")
    failed = n - succeeded
    lat = [r["t_end"] - r["t0"] for r in created.values()
           if r.get("final") == "succeeded"]
    return {
        "concurrent_jobs": n,
        "succeeded": succeeded,
        "failed": failed,
        "wall_s": round(wall, 1),
        "jobs_per_min": round(n / wall * 60, 1) if wall else None,
        "latency_median_s": round(statistics.median(lat), 2) if lat else None,
        "latency_max_s": round(max(lat), 2) if lat else None,
        "peak_mem_used_mb_at_pause": peak_mem,
        "failures_detail": {
            s: r.get("final") or r.get("failed_at_pause") or "timeout"
            for s, r in created.items() if r.get("final") != "succeeded"
        },
    }


def main():
    levels = [int(x) for x in sys.argv[1:]] or [3, 6]
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=PORTAL_DIR
    )
    portal = http.server.ThreadingHTTPServer(("127.0.0.1", 8901), handler)
    threading.Thread(target=portal.serve_forever, daemon=True).start()

    env = dict(os.environ)
    env["GATEWAY_API_KEY"] = "test-key"
    env["ETHIO_MAX_CONCURRENT_JOBS"] = "20"
    env["ETHIO_RATE_LIMIT_TASKS"] = "1000"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "gateway:app",
         "--port", str(GW_PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if client.get(f"{BASE}/health", timeout=2).status_code == 200:
                    break
            except Exception:
                time.sleep(0.3)
        results = []
        base_mem = mem_used_mb()
        for n in levels:
            res = run_level(n, proc)
            res["baseline_mem_mb"] = base_mem
            results.append(res)
            print(json.dumps(res, indent=2), flush=True)
            time.sleep(3)  # let browsers fully close between levels
        print(json.dumps({"levels": results}, indent=2))
    finally:
        proc.kill()
        portal.shutdown()


if __name__ == "__main__":
    main()
