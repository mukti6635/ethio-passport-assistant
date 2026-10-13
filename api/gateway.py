"""ETHIO <-> browser-use gateway.

A small FastAPI service that exposes the browser-use agent over HTTP so the
ETHIO Flutter app can start browser tasks, follow their progress, pause for
human checkpoints (OTP / CAPTCHA / payment / legal review), resume, cancel,
and fetch verified evidence.

URL layout (matches what the Flutter `WebUiHttpAdapter` builds as
`{path}/{job_id}`)::

    POST /tasks                 -> {"job_id": str}            (202)
    GET  /tasks/status/{job_id} -> {"state": str, "log": [...]}
    POST /tasks/pause/{job_id}  -> {"ok": true}
    POST /tasks/resume/{job_id} -> {"ok": true}
    POST /tasks/cancel/{job_id} -> {"ok": true}
    GET  /tasks/evidence/{job_id} -> {"final_result": str|null,
                                      "artifacts": [...], "extracted": {...}}
    GET  /health                -> {"ok": true, "version": "1.0.0"}

Run with::

    uvicorn gateway:app --host 0.0.0.0 --port 8000

See README.md for the full environment-variable list.
"""

import asyncio
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator


def _sanitize_no_proxy() -> None:
    """Remove bracketed IPv6 entries from no_proxy/NO_PROXY.

    The sandbox sets no_proxy with entries like `[::1]` (bracketed). httpx
    cannot parse these and raises `Invalid port: ':1]'`, which breaks
    browser-use's internal httpx client (it creates its own AsyncClient
    that reads the env vars). Unbracketed `::1` works fine.
    """
    for key in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(key)
        if not val:
            continue
        parts = [p.strip() for p in val.split(",")]
        # Drop bracketed forms; keep the unbracketed equivalents.
        cleaned = [p for p in parts if not (p.startswith("[") and p.endswith("]"))]
        if cleaned != parts:
            os.environ[key] = ",".join(cleaned)


_sanitize_no_proxy()

logger = logging.getLogger("ethio.gateway")

VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------


class JobState(str, Enum):
    """State vocabulary the Flutter client understands."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_HUMAN = "awaiting_human"
    WAITING_APPROVAL = "waiting_approval"  # blocked on approval decision
    WAITING_INPUT = "waiting_input"  # blocked on user-provided information
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    # Alias used by newer clients:
    COMPLETED = "completed"


TERMINAL_STATES = {
    JobState.SUCCEEDED,
    JobState.COMPLETED,
    JobState.FAILED,
    JobState.CANCELLED,
    JobState.TIMED_OUT,
}

#: Valid state transitions. The backend rejects anything not listed.
#: `completed` is accepted as an alias of `succeeded` on read.
VALID_TRANSITIONS: Dict["JobState", set] = {
    JobState.QUEUED: {JobState.RUNNING, JobState.CANCELLED, JobState.FAILED},
    JobState.RUNNING: {
        JobState.PAUSED,
        JobState.AWAITING_HUMAN,
        JobState.WAITING_APPROVAL,
        JobState.WAITING_INPUT,
        JobState.SUCCEEDED,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.TIMED_OUT,
    },
    JobState.PAUSED: {JobState.RUNNING, JobState.CANCELLED, JobState.FAILED},
    JobState.AWAITING_HUMAN: {
        JobState.RUNNING, JobState.CANCELLED, JobState.FAILED,
    },
    JobState.WAITING_APPROVAL: {
        JobState.RUNNING, JobState.CANCELLED, JobState.FAILED,
    },
    JobState.WAITING_INPUT: {
        JobState.RUNNING, JobState.CANCELLED, JobState.FAILED,
    },
    JobState.SUCCEEDED: set(),
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
    JobState.TIMED_OUT: set(),
}


def _transition(job: "Job", to_state: "JobState") -> None:
    """Move a job to a new state, enforcing valid transitions.

    Raises HTTPException(409) on invalid transition. Never marks a task
    completed without the caller having verified completion evidence
    beforehand — this function only records the transition.
    """
    from fastapi import HTTPException

    allowed = VALID_TRANSITIONS.get(job.state, set())
    if to_state not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"invalid state transition: {job.state.value} -> {to_state.value}",
        )
    job.state = to_state
    _sync_job(job)

#: States that hold a browser slot. Anything not terminal is active.
_ACTIVE_STATES = {s for s in JobState} - TERMINAL_STATES


@dataclass
class Job:
    """One browser-automation job. Lives only in this process's memory."""

    job_id: str
    session_id: str  # value of the X-Ethio-Session header: isolates users
    goal: str
    inputs: Dict[str, str]
    state: JobState = JobState.QUEUED
    log: List[str] = field(default_factory=list)
    checkpoint: Optional[str] = None  # e.g. "otp" while awaiting_human
    final_result: Optional[str] = None
    error: Optional[str] = None
    agent: Any = None  # browser-use Agent, created when the job starts
    task: Optional["asyncio.Task[None]"] = None  # background runner
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None  # set when the agent starts
    ended_at: Optional[float] = None  # set on terminal state
    # WorkerLoop runner state (runner="worker"). Holds the live browser
    # session while the job is paused in waiting_approval so an approval
    # can resume the exact same page. Never serialized to clients.
    runner: str = "agent"
    worker_ctx: Optional[Dict[str, Any]] = None
    # Durable-sync bookkeeping (Phase 5). db_state is the last state
    # persisted to the task store (None = not persisted yet);
    # session_label is the client's X-Ethio-Session value (in JWT auth
    # mode the owner key is the verified user id and the label is an
    # untrusted client grouping hint, kept for record-keeping only).
    db_state: Optional[str] = None
    session_label: str = ""
    evidence: Optional[Dict[str, Any]] = None


# In-memory job registry. Fine for a single gateway process; a multi-worker
# deployment would need a shared store (Redis/Postgres) instead.
_JOBS: Dict[str, Job] = {}

# Rate limiting: per-session sliding window for task creation.
# In-memory only — suitable for single-worker deployments. A multi-worker
# production deployment MUST use a shared store (e.g. Redis) instead;
# do not call an in-memory limiter production-ready for multiple workers.
# Maps session_id -> list of task-creation timestamps (epoch seconds).
_RATE_LIMIT_BUCKETS: Dict[str, List[float]] = {}


def _check_rate_limit(session_id: str) -> None:
    """Enforce per-session task-creation rate limit.

    Raises HTTPException(429) if the session has exceeded its allowance.
    Does not create any job state — rejected requests never start work.
    """
    max_tasks = int(os.environ.get("ETHIO_RATE_LIMIT_TASKS", "20"))
    window = int(os.environ.get("ETHIO_RATE_LIMIT_WINDOW", "3600"))
    now = time.time()
    bucket = _RATE_LIMIT_BUCKETS.get(session_id, [])
    # Drop timestamps outside the window
    bucket = [t for t in bucket if now - t < window]
    if len(bucket) >= max_tasks:
        oldest = min(bucket)
        retry_after = int(window - (now - oldest)) + 1
        raise HTTPException(
            status_code=429,
            detail=f"rate limit exceeded: {max_tasks} tasks per {window}s",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)
    _RATE_LIMIT_BUCKETS[session_id] = bucket


# Operational counters. Reset on restart; a production deployment should
# export these to a real metrics backend.
_METRICS: Dict[str, int] = {
    "jobs_created": 0,
    "jobs_succeeded": 0,
    "jobs_failed": 0,
    "jobs_cancelled": 0,
    "jobs_timed_out": 0,
    "checkpoints_requested": 0,
}


def _record_terminal(job: Job) -> None:
    """Record a job reaching a terminal state: metrics + end timestamp."""
    if job.ended_at is None:
        job.ended_at = time.time()
        _METRICS[f"jobs_{job.state.value}"] = (
            _METRICS.get(f"jobs_{job.state.value}", 0) + 1
        )
        duration = job.ended_at - (job.started_at or job.created_at)
        logger.info(
            "job %s ended: state=%s duration_s=%.1f steps=%d",
            job.job_id, job.state.value, duration, len(job.log),
        )
    _sync_job(job)


# ---------------------------------------------------------------------------
# Durable task sync (Phase 5). The live Job objects stay authoritative
# for their own process; the task store is the restart-recovery truth.
# _task_store is bound at import time further below (next to the
# approval store); it is None only before that binding runs.
# ---------------------------------------------------------------------------

_task_store: Any = None


def _job_record(job: Job) -> Dict[str, Any]:
    """Durable snapshot of a job. Lifecycle metadata only: never
    browser state, cookies, credentials, OTPs, or document contents."""
    return {
        "job_id": job.job_id,
        "owner_key": job.session_id,
        "session_id": job.session_label or job.session_id,
        "goal": job.goal,
        "inputs": dict(job.inputs),
        "state": job.state.value,
        "log": list(job.log),
        "checkpoint": job.checkpoint,
        "final_result": job.final_result,
        "error": job.error,
        "evidence": job.evidence,
        "runner": job.runner,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
    }


def _sync_job(job: Job) -> None:
    """Mirror a job's durable state to the task store.

    State changes go through the store's compare-and-swap transition
    from the last persisted state; field changes go through a
    state-guarded snapshot. A job may only be recorded SUCCEEDED with a
    verified final_result — without one the durable record is left
    untouched and the defect is logged. Store failures are logged
    loudly, never raised into request handling.
    """
    if _task_store is None or job.db_state is None:
        return
    try:
        if job.db_state != job.state.value:
            if (
                job.state in (JobState.SUCCEEDED, JobState.COMPLETED)
                and not (job.final_result or "").strip()
            ):
                logger.error(
                    "job %s reached %s without a verified final_result; "
                    "durable record left at %s",
                    job.job_id, job.state.value, job.db_state,
                )
                return
            patch = {
                k: v
                for k, v in (
                    ("checkpoint", job.checkpoint),
                    ("final_result", job.final_result),
                    ("error", job.error),
                )
                if v is not None
            }
            updated = _task_store.transition(
                job.job_id, job.session_id,
                job.db_state, job.state.value, patch,
            )
            if updated is None:
                if _task_store.durable:
                    logger.error(
                        "durable transition CAS lost for job %s "
                        "(%s -> %s): the row changed under us",
                        job.job_id, job.db_state, job.state.value,
                    )
                return
            job.db_state = job.state.value
        _task_store.update_snapshot(_job_record(job))
    except Exception:
        logger.exception("task store sync failed for job %s", job.job_id)


def _job_from_record(rec: Dict[str, Any]) -> Job:
    """Rebuild a live Job handle from a durable record after restart.

    The handle has NO browser session and NO runner task: it exists so
    status/evidence/decision flows work honestly. Any attempt to
    resume execution fails safely (see _resume_worker_job)."""
    job = Job(
        job_id=rec["job_id"],
        session_id=rec["owner_key"],
        goal=rec["goal"],
        inputs=dict(rec.get("inputs") or {}),
        runner=rec.get("runner") or "agent",
    )
    job.state = JobState(rec["state"])
    job.log = list(rec.get("log") or [])
    job.checkpoint = rec.get("checkpoint")
    job.final_result = rec.get("final_result")
    job.error = rec.get("error")
    job.evidence = rec.get("evidence")
    job.created_at = rec.get("created_at") or time.time()
    job.started_at = rec.get("started_at")
    job.ended_at = rec.get("ended_at")
    job.session_label = rec.get("session_id") or ""
    job.db_state = rec["state"]
    return job


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StartTaskBody(BaseModel):
    goal: str = Field(max_length=2000)
    inputs: Dict[str, str] = {}
    session_id: str = ""  # echoed by the client; the header is authoritative
    # "agent" (default): browser-use Agent runner.
    # "worker": WorkerLoop runner against the local mock portal only.
    runner: str = Field(default="agent", max_length=16)

    @field_validator("inputs")
    @classmethod
    def validate_inputs(cls, v: Dict[str, str]) -> Dict[str, str]:
        if len(v) > 50:
            raise ValueError("too many inputs (max 50)")
        for k, val in v.items():
            if len(k) > 100 or len(val) > 2000:
                raise ValueError("input key/value too long")
        return v


class PauseBody(BaseModel):
    checkpoint: Optional[str] = None
    session_id: str = ""


class ResumeBody(BaseModel):
    session_id: str = ""


class CancelBody(BaseModel):
    session_id: str = ""


# ---------------------------------------------------------------------------
# Auth + session isolation
# ---------------------------------------------------------------------------


class Principal(str):
    """The authenticated owner key, as a string.

    Equals the isolation key used across the gateway — the session id
    in devkey mode, the verified JWT `sub` in jwt mode — with auth
    metadata attached (.mode, .user_id, .session_label). Endpoints
    keep treating it as the owner/session string; auth-aware helpers
    read the attributes.
    """

    def __new__(
        cls, owner_key: str, *, user_id: Optional[str], mode: str,
        session_label: str = "",
    ) -> "Principal":
        obj = super().__new__(cls, owner_key)
        obj.user_id = user_id
        obj.mode = mode
        obj.session_label = session_label
        return obj


async def require_auth(request: Request) -> Principal:
    """Dependency: authenticate the caller, return the owner Principal.

    Modes (ETHIO_AUTH_MODE):
    - "devkey" (default, LOCAL DEVELOPMENT ONLY): shared
      GATEWAY_API_KEY bearer + X-Ethio-Session header; the session id
      is the isolation key. Fails closed (500) when the key is unset.
    - "jwt" (pilot): Supabase access token. The signature, expiry,
      audience, and issuer are verified (see auth.py); the owner is
      the token's `sub`. Client-supplied ids are never trusted.
    """
    mode = os.environ.get("ETHIO_AUTH_MODE", "devkey").strip().lower()
    if mode == "jwt":
        return _require_jwt(request)
    if mode != "devkey":
        logger.error("unknown ETHIO_AUTH_MODE %r - refusing to serve", mode)
        raise HTTPException(
            status_code=500, detail="server misconfigured: auth mode"
        )
    api_key = os.environ.get("GATEWAY_API_KEY")
    if not api_key:
        logger.error("GATEWAY_API_KEY is not set - refusing to serve")
        raise HTTPException(
            status_code=500, detail="server misconfigured: auth not set up"
        )
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {api_key}":
        raise HTTPException(status_code=401, detail="unauthorized")
    session_id = request.headers.get("x-ethio-session", "").strip()
    if not session_id:
        raise HTTPException(
            status_code=400, detail="missing X-Ethio-Session header"
        )
    return Principal(
        session_id, user_id=None, mode="devkey", session_label=session_id
    )


def _require_jwt(request: Request) -> Principal:
    from auth import (
        AuthError,
        expected_issuer,
        resolve_jwks,
        token_alg,
        verify_supabase_jwt,
    )

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    token = auth[len("Bearer "):].strip()
    secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    alg = token_alg(token)
    # Only pay the JWKS lookup for ES256 tokens (HS256 projects have
    # no JWKS endpoint worth calling per request).
    jwks = resolve_jwks() if alg == "ES256" else None
    # Misconfiguration is a property of the DEPLOYMENT, never of the
    # token: the token's alg is attacker-controlled, so keying a 500
    # off it turned every forged/garbled token on a JWKS (ES256)
    # project into a server error instead of a 401. 500 is reserved
    # for "no verification material configured at all"; everything
    # else is decided by verify_supabase_jwt, which fails closed with
    # AuthError (-> 401) for malformed tokens, wrong algs, HS256
    # tokens on a secret-less deployment, and unknown kids alike.
    jwks_available = bool(
        os.environ.get("ETHIO_JWT_JWKS_JSON") or os.environ.get("SUPABASE_URL")
    )
    if not secret and not jwks_available:
        logger.error("JWT mode with neither SUPABASE_JWT_SECRET nor a JWKS source - refusing")
        raise HTTPException(
            status_code=500,
            detail="server misconfigured: JWT verification not set up",
        )
    try:
        identity = verify_supabase_jwt(
            token,
            hs_secret=secret or None,
            jwks=jwks,
            issuer=expected_issuer(),
        )
    except AuthError:
        raise HTTPException(status_code=401, detail="unauthorized")
    session_label = request.headers.get("x-ethio-session", "").strip()
    return Principal(
        identity.user_id,
        user_id=identity.user_id,
        mode="jwt",
        session_label=session_label,
    )


def _check_body_session(body_session: str, session_id: str) -> None:
    """In devkey mode the body's session_id must match the header's.

    In JWT mode the body's session_id is an untrusted client label —
    ownership derives from the verified token alone — so no equality
    check applies (and none is needed for safety)."""
    if getattr(session_id, "mode", "devkey") == "jwt":
        return
    if body_session and body_session != session_id:
        raise HTTPException(
            status_code=400,
            detail="session_id in body does not match X-Ethio-Session header",
        )


def _get_job(job_id: str, session_id: str) -> Job:
    """Fetch a job, or 404. A session can never see another session's jobs."""
    job = _JOBS.get(job_id)
    if job is None or job.session_id != session_id:
        raise HTTPException(status_code=404, detail="job not found")
    return job


# ---------------------------------------------------------------------------
# browser-use wiring (imports are lazy so the module loads without the
# browser-use package installed - tests inject a fake instead)
# ---------------------------------------------------------------------------


#: Google's OpenAI-compatible Gemini endpoint (no extra dependency needed).
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _get_groq_credential() -> Optional[str]:
    """Resolve the Groq credential: raw GROQ_API_KEY env var, or the
    Secure Vault surrogate (``hsurr:*``) which the egress proxy swaps for the
    real key on the way out."""
    raw = os.environ.get("GROQ_API_KEY")
    if raw:
        return raw
    try:
        sys.path.insert(
            0, "/opt/hatch/skills/skill-creator/bin"
        )
        from dynamic_credentials import dynamic_credential_entry

        entry = dynamic_credential_entry("custom.groq", "access_token")
        surr = str(entry.get("surrogate", "")).strip()
        return surr or None
    except Exception as exc:  # authd unavailable (e.g. plain local dev)
        logger.debug("no vault Groq credential: %s", type(exc).__name__)
        return None


def _get_gemini_credential() -> Optional[str]:
    """Resolve the Gemini credential: raw GEMINI_API_KEY env var, or the
    Secure Vault surrogate (``hsurr:*``) which the egress proxy swaps for the
    real key on the way out. The surrogate is fetched fresh per job so a
    long-running gateway never uses a stale credential."""
    raw = os.environ.get("GEMINI_API_KEY")
    if raw:
        return raw
    # Vault-backed credential (this sandbox): ask authd for a surrogate.
    try:
        sys.path.insert(
            0, "/opt/hatch/skills/skill-creator/bin"
        )
        from dynamic_credentials import dynamic_credential_entry

        entry = dynamic_credential_entry("custom.google-gemini", "access_token")
        surr = str(entry.get("surrogate", "")).strip()
        return surr or None
    except Exception as exc:  # authd unavailable (e.g. plain local dev)
        logger.debug("no vault Gemini credential: %s", type(exc).__name__)
        return None


def _build_llm() -> Any:
    """Chat model for the agent. Provider choice is env-only.

    - Default (no ``ETHIO_LLM_PROVIDER``) or ``ETHIO_LLM_PROVIDER=groq`` ->
      Groq via OpenAI-compatible endpoint, model from ``ETHIO_LLM_MODEL``
      (default ``openai/gpt-oss-120b``), key from ``GROQ_API_KEY`` env or
      Secure Vault. Fails safely if the key is missing.
    - ``ETHIO_LLM_PROVIDER=gemini`` -> Gemini via Google's OpenAI-compatible
      endpoint, model from ``ETHIO_LLM_MODEL`` (default ``gemini-3.8-flash``).
    - Otherwise -> OpenAI, model from ``ETHIO_LLM_MODEL`` (default
      ``gpt-4o``), key from ``OPENAI_API_KEY``.

    The key is never logged, never sent to clients, and never hard-coded.

    Uses browser-use's own ChatOpenAI (0.13.x) which expects an
    ``httpx.AsyncClient``. ``frequency_penalty`` is left unset because
    Gemini's OpenAI-compatible endpoint rejects that field.
    """
    from browser_use.llm import ChatOpenAI
    import httpx

    # The sandbox's egress proxy breaks Playwright's CDP WebSocket to
    # localhost, so proxy env vars must be neutered. But the vault surrogate
    # needs the egress proxy for the LLM calls, so configure httpx with it
    # explicitly. Empty strings (not deletion) ensure all HTTP clients,
    # including Playwright's WebSocket, see "no proxy".
    proxy_url = (
        os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or None
    )
    for key in ("https_proxy", "http_proxy", "HTTPS_PROXY", "HTTP_PROXY",
                "ALL_PROXY", "all_proxy"):
        os.environ[key] = ""
    os.environ["no_proxy"] = "localhost,127.0.0.1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    def _make_client():
        return (
            httpx.AsyncClient(proxy=proxy_url, timeout=120.0)
            if proxy_url
            else None
        )

    provider = os.environ.get("ETHIO_LLM_PROVIDER", "groq").lower()

    # Groq is the default for local development (no Gemini quota consumption).
    if provider == "groq":
        groq_key = _get_groq_credential()
        if not groq_key:
            raise RuntimeError(
                "Groq is the default provider but no Groq credential found. "
                "Set GROQ_API_KEY env var or connect via Secure Vault. "
                "Set ETHIO_LLM_PROVIDER=gemini to use Gemini instead."
            )
        model = os.environ.get("ETHIO_LLM_MODEL", "openai/gpt-oss-120b")
        return ChatOpenAI(
            model=model,
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            http_client=_make_client(),
            frequency_penalty=None,
        )

    if provider == "gemini":
        gemini_key = _get_gemini_credential()
        if not gemini_key:
            raise RuntimeError(
                "ETHIO_LLM_PROVIDER=gemini but no Gemini credential found. "
                "Set GEMINI_API_KEY env var or connect via Secure Vault."
            )
        return ChatOpenAI(
            model=os.environ.get("ETHIO_LLM_MODEL", "gemini-3.8-flash"),
            base_url=os.environ.get("ETHIO_LLM_BASE_URL", GEMINI_OPENAI_BASE_URL),
            api_key=gemini_key,
            http_client=_make_client(),
            # Gemini's OpenAI-compatible endpoint rejects frequency_penalty.
            frequency_penalty=None,
        )
    model = os.environ.get("ETHIO_LLM_MODEL", "gpt-4o")
    # OPENAI_API_KEY is read from the environment by the client itself.
    return ChatOpenAI(model=model)


def _build_browser() -> Any:
    """A fresh headless browser for one job.

    Launches Chrome ourselves with IPv4-only remote debugging, then hands
    browser-use the CDP URL. This avoids CDP connections to `localhost`
    (which can resolve to ::1 in this sandbox while Chrome listens on
    127.0.0.1).
    """
    import socket as _socket
    import subprocess
    import time as _time
    import urllib.request

    from browser_use import Browser

    headless_raw = os.environ.get("ETHIO_HEADLESS", "true").lower()
    headless = headless_raw not in ("0", "false", "no", "off")
    chrome_path = os.environ.get("ETHIO_CHROME_PATH") or (
        os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux/chrome")
    )
    if not os.path.exists(chrome_path):
        raise RuntimeError(f"Chrome not found at {chrome_path}")

    # Find a free port for this job's debugging endpoint.
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dbg_port = s.getsockname()[1]

    user_data_dir = f"/tmp/ethio-chrome-{os.getpid()}-{dbg_port}"
    os.makedirs(user_data_dir, exist_ok=True)
    args = [
        chrome_path,
        "--headless=new" if headless else "--headless=false",
        f"--remote-debugging-port={dbg_port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={user_data_dir}",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "about:blank",
    ]
    proc = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    # Wait for the DevTools endpoint to come up.
    cdp_url = f"http://127.0.0.1:{dbg_port}"
    deadline = _time.time() + 30
    while _time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"{cdp_url}/json/version", timeout=2
            ) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError("Chrome exited during startup")
        _time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("Chrome DevTools endpoint did not come up")

    browser = Browser(cdp_url=cdp_url)
    # Stash for cleanup: kill Chrome and remove the profile dir when done.
    browser._ethio_chrome_proc = proc  # type: ignore[attr-defined]
    browser._ethio_user_data_dir = user_data_dir  # type: ignore[attr-defined]
    return browser


def _summarize_step(agent_output: Any, step_number: int, job: Any = None) -> str:
    """One short log line per agent step. Never raises.

    Secret-safe: logs action types and diagnostic metadata only.
    Never logs field values, credentials, or personal data.
    If job is provided, includes loop-detector state for diagnosing
    repetition loops.
    """
    try:
        current = getattr(agent_output, "current_state", None)
        goal = (
            getattr(current, "next_goal", None)
            or getattr(current, "evaluation_previous_goal", None)
            or ""
        )
        goal = str(goal).strip().replace("\n", " ")[:160]
        actions = getattr(agent_output, "action", None) or []
        names: List[str] = []
        for action in actions:
            if isinstance(action, dict) and action:
                action_name = str(next(iter(action)))
                # Sanitize: log action type only, never parameter values
                # (which may contain typed text, credentials, or PII)
                names.append(action_name)
            else:
                names.append(type(action).__name__)
        action_part = ", ".join(names[:3]) if names else "thinking"
        text = f"step {step_number}: {action_part}"
        if goal:
            text += f" - {goal}"
        # Loop-detector diagnostics (safe metadata only)
        if job is not None:
            try:
                agent = getattr(job, "agent", None)
                state = getattr(agent, "state", None)
                loop = getattr(state, "loop_detector", None)
                if loop is not None:
                    rep = getattr(loop, "max_repetition_count", 0)
                    stag = getattr(loop, "consecutive_stagnant_pages", 0)
                    if rep >= 3 or stag >= 3:
                        text += f" [loop: rep={rep} stag={stag}]"
                failures = getattr(state, "consecutive_failures", 0)
                if failures >= 2:
                    text += f" [failures={failures}]"
            except Exception:
                pass  # diagnostics must never break the run
        return text[:400]
    except Exception as exc:  # never let logging break the run
        return f"step {step_number}: (unreadable step: {type(exc).__name__})"


def _build_agent(job: Job, on_step: Any) -> Any:
    """Create the browser-use Agent for a job. Called inside the runner."""
    import browser_use

    llm = _build_llm()
    browser = _build_browser()
    # Layout-adaptation guidance: the agent must work from the live page,
    # not from assumptions about IDs or positions. Appended to every job's
    # goal so the instruction is present regardless of the caller's wording.
    _ADAPT_GUIDANCE = (
        "Work from the current page as you find it. Identify fields from "
        "their actual labels, accessible names, surrounding text, and "
        "current page state — not from fixed IDs or screen positions. "
        "Reassess the page after each meaningful action and verify the "
        "actual resulting value. Stop and request clarification when "
        "information is missing, ambiguous, or conflicting. Never submit "
        "forms, bypass OTP/CAPTCHA, initiate payment, choose an appointment, "
        "or perform final submission without the required human checkpoint "
        "and authorization. Operate only on the supplied mock portal."
    )
    task_text = f"{_ADAPT_GUIDANCE}\n\nGoal: {job.goal}"
    if job.inputs:
        lines = "\n".join(f"- {k}: {v}" for k, v in job.inputs.items())
        task_text = f"{task_text}\n\nInputs:\n{lines}"
    max_steps = int(os.environ.get("ETHIO_MAX_STEPS", "50"))
    # Vision can be disabled for text-only models (e.g. Groq) via
    # ETHIO_USE_VISION=false. Default is true (Gemini + screenshots).
    use_vision = os.environ.get("ETHIO_USE_VISION", "true").lower() != "false"
    # When vision is off, trim the DOM snapshot to reduce token usage
    # for smaller-context models. Default 40000 is kept when vision is on.
    max_elements = 10000 if not use_vision else 40000
    agent_kwargs: dict[str, Any] = {}
    if not use_vision:
        # Minimal system prompt for text-only models: replaces browser-use's
        # ~6k-token default. Keeps safety rules; drops verbose instructions.
        agent_kwargs["override_system_message"] = (
            "You are a browser automation agent. You receive the page's "
            "interactive elements as a text list with indexes. "
            "Use only the existing mock portal page you were given. "
            "Identify fields from their labels, types, and placeholders. "
            "Never guess when a field is ambiguous — pause and report. "
            "After typing into a field, read its actual value back to verify. "
            "Pause when information is missing or conflicting. "
            "Never submit forms. Never bypass OTP, CAPTCHA, or payment. "
            "Never access real passport sites or applications."
        )
    agent = browser_use.Agent(
        task=task_text,
        llm=llm,
        browser=browser,
        register_new_step_callback=on_step,
        max_actions_per_step=5,
        use_vision=use_vision,
        max_clickable_elements_length=max_elements,
        **agent_kwargs,
    )
    # stash for cleanup; not part of any public API
    agent._ethio_browser = browser
    agent._ethio_max_steps = max_steps
    return agent


def _safe_stop(agent: Any) -> None:
    try:
        agent.stop()
    except Exception as exc:
        logger.warning("agent.stop() raised: %s", type(exc).__name__)


async def _safe_close_browser(agent: Any) -> None:
    browser = getattr(agent, "_ethio_browser", None)
    if browser is None:
        return
    try:
        await browser.close()
    except Exception as exc:
        logger.warning("browser.close() raised: %s", type(exc).__name__)
    # If we launched Chrome ourselves (cdp_url mode), kill the process and
    # remove its profile dir so nothing leaks between jobs.
    proc = getattr(browser, "_ethio_chrome_proc", None)
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    user_data_dir = getattr(browser, "_ethio_user_data_dir", None)
    if user_data_dir:
        import shutil

        shutil.rmtree(user_data_dir, ignore_errors=True)


async def _run_job(job: Job) -> None:
    """Background runner: executes the agent, enforces timeout, records."""
    timeout_s = float(os.environ.get("ETHIO_JOB_TIMEOUT_S", "1200"))

    async def on_step(browser_state: Any, agent_output: Any, step_no: int) -> None:
        job.log.append(_summarize_step(agent_output, step_no, job))

    try:
        job.agent = _build_agent(job, on_step)
    except Exception as exc:
        job.state = JobState.FAILED
        # Never put exception text from unknown sources in the log blindly;
        # the type name plus a short message is enough for debugging.
        job.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        job.log.append(f"failed to start: {job.error}")
        logger.exception("job %s failed to start", job.job_id)
        _record_terminal(job)
        return

    agent = job.agent
    _transition(job, JobState.RUNNING)
    job.started_at = time.time()
    job.log.append("agent started")
    logger.info("job %s running (timeout %ss)", job.job_id, timeout_s)

    try:
        history = await asyncio.wait_for(
            agent.run(max_steps=agent._ethio_max_steps), timeout=timeout_s
        )
        # Capture the final result BEFORE recording the terminal state:
        # the durable store refuses a SUCCEEDED record without the
        # verified result attached, by design.
        try:
            job.final_result = history.final_result()
        except Exception:
            job.final_result = None
        # run() only returns when the agent finished on its own; a pause or
        # cancel keeps it alive, so reaching here means it is done.
        if job.state == JobState.RUNNING:
            try:
                successful = history.is_successful()
            except Exception:
                successful = None
            # The agent can stop early (e.g. consecutive failures) without
            # raising; only claim success when it says it succeeded.
            if successful:
                job.state = JobState.SUCCEEDED
                job.log.append("agent finished successfully")
            else:
                job.state = JobState.FAILED
                job.error = "agent stopped without completing the task"
                job.log.append(job.error)
            _record_terminal(job)
    except asyncio.TimeoutError:
        job.state = JobState.TIMED_OUT
        job.error = f"timed out after {timeout_s:g}s"
        job.log.append(job.error)
        logger.warning("job %s timed out", job.job_id)
        _safe_stop(agent)
        _record_terminal(job)
    except asyncio.CancelledError:
        # Cancelled via POST /tasks/cancel/{id}: the endpoint already set the
        # terminal state, so just make sure the agent is stopped.
        _safe_stop(agent)
        raise
    except Exception as exc:
        job.state = JobState.FAILED
        job.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        job.log.append(f"failed: {job.error}")
        logger.exception("job %s failed", job.job_id)
        _record_terminal(job)
    finally:
        await _safe_close_browser(agent)


# ---------------------------------------------------------------------------
# WorkerLoop runner (runner="worker"): mock portal only.
#
# Drives the tested WorkerLoop (OBSERVE -> REASON -> ACT -> VERIFY) with a
# deterministic mock-portal policy derived from the job inputs:
#   fill each input field (safe, read-back verified)
#   -> Continue to review (safe click, step verified)
#   -> Continue to verification (safe click, step verified)
#   -> Pay (PROTECTED: approval prepared, job pauses in waiting_approval)
#   -> payment verified via #pay-ok visibility, job completes.
# OTP/CAPTCHA remain human checkpoints and are never automated.
# ---------------------------------------------------------------------------


def _mock_portal_policy(job: Job):
    """Stateful policy closure for the mock-portal worker runner."""
    stage = {"idx": 0}
    fields = list(job.inputs.items())

    def policy(obs, inputs):
        idx = stage["idx"]
        # Stage 1: fill each input field on the form step.
        if idx < len(fields):
            field_id, value = fields[idx]
            stage["idx"] += 1
            return (
                "input",
                {"field": field_id, "value": value},
                {"field": field_id},
                f"Fill {field_id}",
                "Types a value into the mock form.",
            )
        # Stage 2: form -> review.
        if idx == len(fields):
            stage["idx"] += 1
            return (
                "click",
                {"selector": "#btn-to-review", "verify_step": "review"},
                {"step": "review"},
                "Continue to review",
                "Moves to the review step.",
            )
        # Stage 3: review -> checkpoints.
        if idx == len(fields) + 1:
            stage["idx"] += 1
            return (
                "click",
                {"selector": "#btn-to-checkpoints",
                 "verify_step": "checkpoints"},
                {"step": "checkpoints"},
                "Continue to verification",
                "Moves to the verification step.",
            )
        # Stage 4: payment is PROTECTED. The orchestrator prepares an
        # approval; the worker must not click until the user approves.
        if idx == len(fields) + 2:
            stage["idx"] += 1
            return (
                "payment",
                {"selector": "#btn-pay", "verify_visible": "#pay-ok",
                 "amount": "200"},
                {"amount": "ETB 200.00 (SIMULATED)"},
                "Pay ETB 200.00 (SIMULATED)",
                "Records a simulated payment on the mock portal. "
                "No real charge is made.",
            )
        return None  # workflow complete

    return policy


async def _close_worker_ctx(job: Job) -> None:
    """Close the worker's browser session if one is open."""
    ctx = job.worker_ctx or {}
    browser = ctx.get("browser")
    pw = ctx.get("playwright")
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if pw is not None:
        try:
            await pw.stop()
        except Exception:
            pass
    job.worker_ctx = None


async def _drive_worker_until_pause(job: Job) -> None:
    """Run worker steps until DONE / FAILED / WAITING_APPROVAL.

    On WAITING_APPROVAL the job is transitioned and the browser session
    is kept in job.worker_ctx so a later approval resumes the same page.
    """
    from worker import WorkerState

    ctx = job.worker_ctx or {}
    loop = ctx.get("loop")
    assert loop is not None
    for _ in range(50):  # bounded; the policy is finite
        state = await loop.run_step()
        if state == WorkerState.WAITING_APPROVAL:
            # Find the approval the orchestrator just prepared.
            pending = _approval_service.list_pending(job.session_id)
            mine = [a for a in pending if a.job_id == job.job_id]
            if mine:
                approval = mine[-1]
                ctx["pending_approval_id"] = approval.approval_id
                ctx["pending_action_type"] = approval.action_type
                ctx["pending_params"] = dict(ctx.get("last_params") or {})
                job.checkpoint = f"approval:{approval.approval_id}"
            if job.state == JobState.RUNNING:
                _transition(job, JobState.WAITING_APPROVAL)
            job.log.append("worker paused: waiting for approval")
            logger.info("job %s waiting_approval", job.job_id)
            return
        if state == WorkerState.DONE:
            job.state = JobState.SUCCEEDED
            job.final_result = "mock workflow completed and verified"
            job.log.append("worker finished: all steps verified")
            _record_terminal(job)
            await _close_worker_ctx(job)
            return
        if state == WorkerState.FAILED:
            job.state = JobState.FAILED
            job.error = "worker step failed verification"
            job.log.append(job.error)
            _record_terminal(job)
            await _close_worker_ctx(job)
            return
    # Budget exhausted without finishing.
    job.state = JobState.FAILED
    job.error = "worker step budget exhausted"
    job.log.append(job.error)
    _record_terminal(job)
    await _close_worker_ctx(job)


async def _run_worker_job(job: Job) -> None:
    """Background runner for runner="worker" jobs (mock portal only)."""
    from worker import MockPortalDriver, WorkerLoop

    portal_url = os.environ.get(
        "ETHIO_MOCK_PORTAL_URL", "http://127.0.0.1:8901/index.html"
    )
    _transition(job, JobState.RUNNING)
    job.started_at = time.time()
    job.log.append("worker started (mock portal)")
    logger.info("job %s worker running", job.job_id)
    try:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto(portal_url)
        driver = MockPortalDriver(page)
        # Wrap the policy to remember the last proposed params so the
        # resume path can claim with the exact prepared parameters.
        base_policy = _mock_portal_policy(job)
        ctx: Dict[str, Any] = {
            "playwright": pw, "browser": browser, "page": page,
        }

        def policy(obs, inputs):
            proposal = base_policy(obs, inputs)
            if proposal is not None:
                ctx["last_params"] = dict(proposal[1])
            return proposal

        loop = WorkerLoop(
            task_id=job.job_id,
            session_id=job.session_id,
            goal=job.goal,
            inputs=dict(job.inputs),
            driver=driver,
            approval_service=_approval_service,
            policy=policy,
            on_event=lambda e: job.log.append(
                f"worker {e.proposed_action}: {e.result} ({e.verification})"
            ),
        )
        ctx["loop"] = loop
        job.worker_ctx = ctx
        await _drive_worker_until_pause(job)
    except Exception as exc:
        job.state = JobState.FAILED
        job.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        job.log.append(f"worker failed to start: {job.error}")
        logger.exception("job %s worker failed", job.job_id)
        _record_terminal(job)
        await _close_worker_ctx(job)


async def _resume_worker_job(job: Job, approval_id: str) -> None:
    """Resume a waiting worker job after the user approved.

    Claims and executes ONLY the exact prepared action, verifies the
    postcondition in the browser, then continues the worker loop.
    If the worker session is gone (process restart), the job fails
    safely: the protected action is NOT executed and nothing is
    marked complete.
    """
    ctx = job.worker_ctx
    if not ctx or ctx.get("loop") is None:
        job.state = JobState.FAILED
        job.error = (
            "worker session lost (restart); protected action was not "
            "executed; operator review required"
        )
        job.log.append(job.error)
        _record_terminal(job)
        return
    loop = ctx["loop"]
    action_type = ctx.get("pending_action_type") or "payment"
    params = dict(ctx.get("pending_params") or {})
    try:
        event = await loop.execute_approved(approval_id, action_type, params)
    except Exception as exc:
        job.state = JobState.FAILED
        job.error = f"resume failed: {type(exc).__name__}"
        job.log.append(job.error)
        _record_terminal(job)
        await _close_worker_ctx(job)
        return
    job.log.append(
        f"worker approved action {action_type}: {event.result} "
        f"({event.verification})"
    )
    if event.result != "succeeded":
        job.state = JobState.FAILED
        job.error = f"approved action did not verify: {event.result}"
        job.log.append(job.error)
        _record_terminal(job)
        await _close_worker_ctx(job)
        return
    # Continue the remaining workflow steps.
    if job.state == JobState.WAITING_APPROVAL:
        _transition(job, JobState.RUNNING)
    await _drive_worker_until_pause(job)



# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="ETHIO browser-use gateway", version=VERSION)


def _cors_origins() -> list[str]:
    """Browser origins allowed to call the gateway (Flutter web pilot).

    Native apps are not subject to CORS, so this is opt-in: only the
    origins listed in ETHIO_CORS_ORIGINS (comma-separated) get CORS
    headers. Unset/empty (the default) means no CORS headers at all —
    the pre-Phase-11 behavior. Wildcards are refused: an entry of "*"
    is dropped so a misconfiguration cannot open the gateway to every
    website while it holds user tokens.
    """
    raw = os.environ.get("ETHIO_CORS_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return [o for o in origins if o != "*"]


_CORS = _cors_origins()
if _CORS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Ethio-Session"],
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    """No auth. For load balancers and the Flutter client's ping."""
    return {"ok": True, "version": VERSION}


@app.on_event("startup")
async def _restore_durable_state() -> None:
    """Rebuild live job handles from the durable task store.

    Only human-paced waiting states (waiting_approval, waiting_input)
    are restored as live handles: their approvals remain decidable,
    and any approval resumes into the safe 'session lost' path rather
    than executing anything. Jobs that were queued/running/paused/
    awaiting_human belonged to a dead process — their browser session
    is gone — so they are reconciled to FAILED (interrupted) in the
    store and never restored, never auto-retried. In memory mode the
    store is empty at boot and this is a no-op.
    """
    if _task_store is None:
        return
    try:
        active = _task_store.list_active()
    except Exception:
        logger.exception("durable job restore failed at startup")
        return
    for rec in active:
        state = rec["state"]
        if state in ("waiting_approval", "waiting_input"):
            job = _job_from_record(rec)
            _JOBS[job.job_id] = job
            logger.info(
                "restored job %s in state %s (no live browser session)",
                job.job_id, state,
            )
        elif state in ("queued", "running", "paused", "awaiting_human"):
            try:
                _task_store.transition(
                    rec["job_id"], rec["owner_key"], state, "failed",
                    {
                        "error": (
                            "interrupted by gateway restart; live "
                            "session lost; nothing was auto-retried"
                        ),
                        "log_entry": "failed at startup reconciliation",
                    },
                )
                logger.info(
                    "reconciled interrupted job %s (%s -> failed)",
                    rec["job_id"], state,
                )
            except Exception:
                logger.exception(
                    "failed to reconcile interrupted job %s", rec["job_id"]
                )
    # Stale EXECUTING approval claims from the dead process become
    # UNKNOWN (never blind-retried), same rule as the manual endpoint.
    # Durable stores only: in memory mode the singleton may hold live
    # claims from this process's own tests/requests.
    if getattr(_approval_service, "durable", False):
        try:
            abandoned = _approval_service.reconcile_abandoned(0)
            if abandoned:
                logger.warning(
                    "startup: %d stale approval executions marked UNKNOWN",
                    len(abandoned),
                )
        except Exception:
            logger.exception("startup approval reconciliation failed")


@app.get("/metrics")
async def metrics(session_id: str = Depends(require_auth)) -> Dict[str, Any]:
    """Operational counters (auth required). Resets on restart; export to a
    real metrics backend for production."""
    by_state: Dict[str, int] = {}
    for job in _JOBS.values():
        by_state[job.state.value] = by_state.get(job.state.value, 0) + 1
    return {
        "version": VERSION,
        "counters": dict(_METRICS),
        "jobs_by_state": by_state,
        "jobs_tracked": len(_JOBS),
    }


@app.post("/tasks", status_code=202)
async def start_task(
    body: StartTaskBody, session_id: str = Depends(require_auth)
) -> Dict[str, str]:
    """Start a browser task. Returns immediately; poll /tasks/status/{id}."""
    _check_body_session(body.session_id, session_id)
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal must not be empty")
    # Rate limit: per-session task creation. Rejected requests never
    # create jobs or launch browsers.
    _check_rate_limit(session_id)
    # Bounded concurrency: refuse new jobs when too many are active, and
    # refuse a second concurrent job for the same session (one browser per
    # applicant prevents state corruption).
    max_jobs = int(os.environ.get("ETHIO_MAX_CONCURRENT_JOBS", "10"))
    active = sum(
        1 for j in _JOBS.values() if j.state in _ACTIVE_STATES
    )
    if active >= max_jobs:
        raise HTTPException(
            status_code=429,
            detail=f"server busy: {active} jobs running (max {max_jobs})",
        )
    for j in _JOBS.values():
        if j.session_id == session_id and j.state in _ACTIVE_STATES:
            raise HTTPException(
                status_code=409,
                detail=f"session already has active job {j.job_id}",
            )
    job_id = uuid.uuid4().hex
    runner = body.runner if body.runner in ("agent", "worker") else "agent"
    job = Job(
        job_id=job_id,
        session_id=session_id,
        goal=body.goal.strip(),
        inputs=dict(body.inputs),
        runner=runner,
    )
    job.session_label = getattr(session_id, "session_label", "") or ""
    # Persist BEFORE launching the runner: in durable mode the job
    # must exist in the store before any transition can be mirrored,
    # and the database's one-active-job-per-session rule is the final
    # arbiter (mapped to 409). A durable-store outage fails the
    # request loudly (503) instead of starting untracked work.
    if _task_store is not None:
        from task_store import DuplicateActiveJob

        try:
            _task_store.create(_job_record(job))
            job.db_state = job.state.value
        except DuplicateActiveJob:
            raise HTTPException(
                status_code=409,
                detail="session already has an active job",
            )
        except Exception:
            logger.exception("task store create failed for job %s", job_id)
            raise HTTPException(
                status_code=503, detail="durable task store unavailable"
            )
    _JOBS[job_id] = job
    if runner == "worker":
        job.task = asyncio.create_task(_run_worker_job(job))
    else:
        job.task = asyncio.create_task(_run_job(job))
    _METRICS["jobs_created"] += 1
    logger.info("job %s created for session %s", job_id, session_id[:8] + "...")
    return {"job_id": job_id}


@app.get("/tasks/status/{job_id}")
async def job_status(
    job_id: str, session_id: str = Depends(require_auth)
) -> Dict[str, Any]:
    job = _get_job(job_id, session_id)
    return {"state": job.state.value, "log": list(job.log)}


@app.post("/tasks/pause/{job_id}")
async def pause_job(
    job_id: str, body: PauseBody, session_id: str = Depends(require_auth)
) -> Dict[str, bool]:
    """Pause the agent. With a checkpoint name the job waits for the human
    (state `awaiting_human`); otherwise it is a plain `paused`."""
    _check_body_session(body.session_id, session_id)
    job = _get_job(job_id, session_id)
    if job.state in TERMINAL_STATES:
        raise HTTPException(
            status_code=409, detail=f"cannot pause a {job.state.value} job"
        )
    if job.state in (JobState.PAUSED, JobState.AWAITING_HUMAN):
        return {"ok": True}  # already paused: harmless no-op
    if job.state != JobState.RUNNING or job.agent is None:
        raise HTTPException(status_code=409, detail="job is not running yet")
    job.agent.pause()
    if body.checkpoint:
        job.state = JobState.AWAITING_HUMAN
        job.checkpoint = body.checkpoint
        job.log.append(f"paused for human checkpoint: {body.checkpoint}")
        _METRICS["checkpoints_requested"] += 1
    else:
        job.state = JobState.PAUSED
        job.log.append("paused by operator")
    _sync_job(job)
    return {"ok": True}


@app.post("/tasks/resume/{job_id}")
async def resume_job(
    job_id: str, body: ResumeBody, session_id: str = Depends(require_auth)
) -> Dict[str, bool]:
    _check_body_session(body.session_id, session_id)
    job = _get_job(job_id, session_id)
    if job.state in TERMINAL_STATES:
        raise HTTPException(
            status_code=409, detail=f"cannot resume a {job.state.value} job"
        )
    if job.state == JobState.RUNNING:
        return {"ok": True}  # already running: harmless no-op
    if job.state not in (JobState.PAUSED, JobState.AWAITING_HUMAN):
        raise HTTPException(status_code=409, detail="job is not paused")
    job.agent.resume()
    job.state = JobState.RUNNING
    job.checkpoint = None
    job.log.append("resumed")
    _sync_job(job)
    return {"ok": True}


@app.post("/tasks/cancel/{job_id}")
async def cancel_job(
    job_id: str, body: CancelBody, session_id: str = Depends(require_auth)
) -> Dict[str, bool]:
    """Cancel a job. Idempotent: cancelling a terminal job is a no-op."""
    _check_body_session(body.session_id, session_id)
    job = _get_job(job_id, session_id)
    if job.state in TERMINAL_STATES:
        return {"ok": True}
    job.state = JobState.CANCELLED
    job.log.append("cancelled by operator")
    _record_terminal(job)
    # Cancel any pending approvals so they can never execute.
    _approval_service.cancel_for_job(job.job_id, session_id)
    # Stop the runner BEFORE closing its browser: closing a page while
    # the worker is mid-operation races Playwright and can hang the
    # close. Cancel first, give the task a brief moment to unwind,
    # then close whatever session remains.
    if job.task is not None and not job.task.done():
        job.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(job.task), timeout=2)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
    if job.worker_ctx is not None:
        await _close_worker_ctx(job)
    if job.agent is not None:
        _safe_stop(job.agent)
    return {"ok": True}


@app.get("/tasks/evidence/{job_id}")
async def job_evidence(
    job_id: str, session_id: str = Depends(require_auth)
) -> Dict[str, Any]:
    """Verified outcome of a finished job. 404 until the job is terminal -
    the gateway never invents evidence for a job that is still running."""
    job = _get_job(job_id, session_id)
    if job.state not in TERMINAL_STATES:
        raise HTTPException(
            status_code=404, detail="evidence not available yet"
        )
    return {
        "final_result": job.final_result,
        "artifacts": [],
        "extracted": {},
    }


# ---------------------------------------------------------------------------
# Approval gate: backend-enforced human approval for protected actions.
# An LLM prompt is not a security boundary. The agent prepares an action;
# the user approves; the gate verifies and consumes exactly once.
# ---------------------------------------------------------------------------

from approvals import ApprovalState as _ApprovalState
from persistence import build_approval_store

# Storage selection is explicit: ETHIO_USE_SUPABASE=1 requires
# SUPABASE_URL + SUPABASE_SERVICE_KEY (build_approval_store raises
# otherwise — no silent fallback to memory when durability is
# required). Default local mode uses the in-memory singleton.
_approval_service = build_approval_store()

# Durable task storage (Phase 5): build_task_store() raises on any
# misconfigured durable mode (see task_store.py). Default: memory.
from task_store import build_task_store

_task_store = build_task_store()


class PrepareApprovalBody(BaseModel):
    job_id: str = Field(max_length=64)
    action_type: str = Field(max_length=64)
    action_label: str = Field(max_length=200)
    consequence: str = Field(max_length=1000)
    params: Dict[str, Any] = {}
    params_summary: Dict[str, str] = {}
    session_id: str = ""
    ttl_s: Optional[float] = Field(default=None, ge=60, le=86400)


class DecideApprovalBody(BaseModel):
    approve: bool
    reason: Optional[str] = Field(default=None, max_length=500)
    session_id: str = ""


class ExecuteApprovalBody(BaseModel):
    job_id: str = Field(max_length=64)
    action_type: str = Field(max_length=64)
    params: Dict[str, Any] = {}
    session_id: str = ""


def _approval_to_dict(a: Any) -> Dict[str, Any]:
    """Secret-safe serialization: never includes raw params or secrets."""
    return {
        "approval_id": a.approval_id,
        "job_id": a.job_id,
        "action_type": a.action_type,
        "action_label": a.action_label,
        "consequence": a.consequence,
        "params_summary": dict(a.params_summary),
        "state": a.state.value,
        "created_at": a.created_at,
        "expires_at": a.expires_at,
        "decided_at": a.decided_at,
        "decided_by": (
            a.decided_by[:8] + "..." if a.decided_by else None
        ),
        "consumed": a.consumed,
        "execution_state": a.execution_state.value,
        "execution_id": (
            a.execution_id[:8] + "..." if a.execution_id else None
        ),
    }


@app.post("/approvals", status_code=201)
async def prepare_approval(
    body: PrepareApprovalBody, session_id: str = Depends(require_auth)
) -> Dict[str, Any]:
    """Prepare a protected action for human approval. Idempotent: the same
    job + action + params returns the existing pending approval."""
    _check_body_session(body.session_id, session_id)
    job = _get_job(body.job_id, session_id)
    if job.state in TERMINAL_STATES:
        raise HTTPException(
            status_code=409, detail="job is already terminal"
        )
    # Never store secrets in approval params. Reject obvious secret keys.
    for key in body.params:
        lowered = key.lower()
        if any(s in lowered for s in ("password", "secret", "otp", "token", "key", "pin")):
            raise HTTPException(
                status_code=400,
                detail=f"param '{key}' looks sensitive; do not put secrets in approvals",
            )
    approval = _approval_service.prepare(
        job_id=job.job_id,
        session_id=session_id,
        action_type=body.action_type,
        action_label=body.action_label,
        consequence=body.consequence,
        params=dict(body.params),
        params_summary=dict(body.params_summary),
        ttl_s=body.ttl_s,
    )
    # Move the job to waiting_approval when the first approval is prepared.
    if job.state == JobState.RUNNING:
        try:
            _transition(job, JobState.WAITING_APPROVAL)
        except HTTPException:
            pass  # already in a waiting state; keep it
        job.checkpoint = f"approval:{approval.approval_id}"
        job.log.append(
            f"approval requested: {approval.action_type} "
            f"(id {approval.approval_id[:8]}...)"
        )
        # The checkpoint/log were set after the transition above;
        # sync once more so the durable record is not a step behind.
        _sync_job(job)
    logger.info(
        "approval %s prepared for job %s action %s",
        approval.approval_id[:8], job.job_id[:8], approval.action_type,
    )
    return _approval_to_dict(approval)


@app.get("/approvals/pending")
async def list_pending_approvals(
    session_id: str = Depends(require_auth),
) -> Dict[str, Any]:
    """List this user's pending approvals. Never returns another user's."""
    approvals = _approval_service.list_pending(session_id)
    return {"approvals": [_approval_to_dict(a) for a in approvals]}


@app.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    body: DecideApprovalBody,
    session_id: str = Depends(require_auth),
) -> Dict[str, Any]:
    """Approve or reject. Only the owning session may decide. Duplicate or
    stale decisions are rejected safely (idempotent no-op -> 409)."""
    _check_body_session(body.session_id, session_id)
    approval = _approval_service.decide(
        approval_id, session_id, body.approve, body.reason
    )
    if approval is None:
        # If the approval expired while a worker job was waiting, fail
        # the job safely: the protected action can never execute.
        stale = _approval_service.get(approval_id, session_id)
        if stale is not None and stale.state == _ApprovalState.EXPIRED:
            stale_job = _JOBS.get(stale.job_id)
            if (
                stale_job is not None
                and stale_job.session_id == session_id
                and stale_job.state == JobState.WAITING_APPROVAL
            ):
                stale_job.state = JobState.FAILED
                stale_job.error = "approval expired before a decision"
                stale_job.log.append(stale_job.error)
                _record_terminal(stale_job)
                await _close_worker_ctx(stale_job)
        raise HTTPException(
            status_code=409,
            detail="approval not found, not yours, expired, or already decided",
        )
    # Resume or fail the job based on the decision.
    job = _JOBS.get(approval.job_id)
    if job is not None and job.session_id == session_id:
        if approval.state == _ApprovalState.APPROVED:
            if job.state == JobState.WAITING_APPROVAL:
                job.log.append(
                    f"approval granted: {approval.action_type} "
                    f"(id {approval.approval_id[:8]}...)"
                )
                if job.runner == "worker":
                    # Resume the worker: it claims + executes + verifies
                    # the exact prepared action, then continues.
                    asyncio.create_task(
                        _resume_worker_job(job, approval.approval_id)
                    )
                else:
                    try:
                        _transition(job, JobState.RUNNING)
                    except HTTPException:
                        pass
        else:
            # Rejection prevents the protected action from executing.
            job.log.append(
                f"approval rejected: {approval.action_type} "
                f"(id {approval.approval_id[:8]}...)"
            )
            if job.runner == "worker" and job.state == JobState.WAITING_APPROVAL:
                job.state = JobState.FAILED
                job.error = "protected action rejected by user"
                job.log.append(job.error)
                _record_terminal(job)
                await _close_worker_ctx(job)
    logger.info(
        "approval %s decided: %s",
        approval.approval_id[:8], approval.state.value,
    )
    return _approval_to_dict(approval)


@app.post("/approvals/{approval_id}/execute")
async def execute_approved_action(
    approval_id: str,
    body: ExecuteApprovalBody,
    session_id: str = Depends(require_auth),
) -> Dict[str, Any]:
    """Execution gate: claim an approved approval for dispatch.

    Verifies ownership, job binding, param match, approved state, and
    unconsumed status atomically. Only one concurrent caller wins.
    Returns an execution_id the worker must use when reporting the
    browser-verified outcome via /approvals/{id}/result.

    This is the ONLY path that authorizes a protected action — the agent
    cannot bypass it by calling another function.
    """
    _check_body_session(body.session_id, session_id)
    job = _get_job(body.job_id, session_id)
    # Binding: an approval may only execute against its own job, and
    # only while that job is in an executable state (waiting on this
    # approval, or running under the orchestrator). A terminal or
    # mismatched job can never authorize a dispatch.
    if job.state not in (JobState.WAITING_APPROVAL, JobState.RUNNING):
        raise HTTPException(
            status_code=409,
            detail=f"job is {job.state.value}; it cannot execute approvals",
        )
    approval = _approval_service.claim_for_execution(
        approval_id,
        session_id,
        body.job_id,
        body.action_type,
        dict(body.params),
    )
    if approval is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "execution denied: approval missing, not yours, not approved, "
                "expired, already consumed, or params do not match"
            ),
        )
    # The gate has authorized exactly one dispatch. Record it in the job log
    # (action type only — never parameter values).
    job.log.append(
        f"protected action dispatched: {approval.action_type} "
        f"(execution {approval.execution_id[:8]}...)"
    )
    logger.info(
        "protected action %s dispatched for job %s",
        approval.action_type, job.job_id[:8],
    )
    return {
        "authorized": True,
        "approval_id": approval.approval_id,
        "action_type": approval.action_type,
        "execution_id": approval.execution_id,
        "execution_state": approval.execution_state.value,
        # The caller performs the browser action now, verifies the observed
        # result itself, then reports via /approvals/{id}/result. It must
        # NOT mark anything complete without verification.
    }


class ExecutionResultBody(BaseModel):
    execution_id: str = Field(max_length=64)
    succeeded: bool
    evidence: Optional[str] = Field(default=None, max_length=500)
    session_id: str = ""


@app.post("/approvals/{approval_id}/result")
async def record_execution_result(
    approval_id: str,
    body: ExecutionResultBody,
    session_id: str = Depends(require_auth),
) -> Dict[str, Any]:
    """Record the browser-verified outcome of a claimed execution.

    Only the holder of the execution_id may record. Transitions
    EXECUTING -> SUCCEEDED/FAILED. On success the job may resume; the
    gateway revalidates page state before continuing (the orchestrator
    does this via its observation step).
    """
    _check_body_session(body.session_id, session_id)
    approval = _approval_service.record_execution_result(
        approval_id,
        session_id,
        body.execution_id,
        body.succeeded,
        body.evidence,
    )
    if approval is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "result rejected: unknown claim, wrong execution_id, "
                "or already recorded"
            ),
        )
    job = _JOBS.get(approval.job_id)
    if job is not None and job.session_id == session_id:
        job.log.append(
            f"protected action {approval.execution_state.value}: "
            f"{approval.action_type} (execution {approval.execution_id[:8]}...)"
        )
        if approval.execution_state.value == "succeeded":
            # Resume only if the job is still waiting; the worker revalidates
            # the page before the next step (orchestrator observation).
            if job.state == JobState.WAITING_APPROVAL:
                try:
                    _transition(job, JobState.RUNNING)
                except HTTPException:
                    pass
    return {
        "approval_id": approval.approval_id,
        "execution_state": approval.execution_state.value,
    }


@app.post("/approvals/reconcile")
async def reconcile_abandoned_approvals(
    session_id: str = Depends(require_auth),
) -> Dict[str, Any]:
    """Crash recovery: mark stale EXECUTING claims as UNKNOWN.

    These must never be blindly retried — the browser action may already
    have taken effect. Returns them for operator review.
    """
    abandoned = _approval_service.reconcile_abandoned()
    mine = [a for a in abandoned if a.session_id == session_id]
    return {
        "reconciled": [
            {
                "approval_id": a.approval_id,
                "job_id": a.job_id,
                "action_type": a.action_type,
                "execution_id": a.execution_id,
                "execution_state": a.execution_state.value,
            }
            for a in mine
        ]
    }
