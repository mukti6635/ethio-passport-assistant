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
from pydantic import BaseModel

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
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATES = {
    JobState.SUCCEEDED,
    JobState.FAILED,
    JobState.CANCELLED,
    JobState.TIMED_OUT,
}

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


# In-memory job registry. Fine for a single gateway process; a multi-worker
# deployment would need a shared store (Redis/Postgres) instead.
_JOBS: Dict[str, Job] = {}

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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StartTaskBody(BaseModel):
    goal: str
    inputs: Dict[str, str] = {}
    session_id: str = ""  # echoed by the client; the header is authoritative


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


async def require_auth(request: Request) -> str:
    """Dependency: valid Bearer token + X-Ethio-Session header.

    Returns the session id. Fails closed (500) when the server itself is
    misconfigured, so the gateway can never run without authentication.
    """
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
    return session_id


def _check_body_session(body_session: str, header_session: str) -> None:
    """The client sends session_id in the body too; it must match the header."""
    if body_session and body_session != header_session:
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

    - Gemini credential available (``GEMINI_API_KEY`` env or Secure Vault)
      -> Gemini via Google's OpenAI-compatible endpoint, model from
      ``ETHIO_LLM_MODEL`` (default ``gemini-3.8-flash``).
    - Otherwise -> OpenAI, model from ``ETHIO_LLM_MODEL`` (default
      ``gpt-4o``), key from ``OPENAI_API_KEY``.

    The key is never logged, never sent to clients, and never hard-coded.
    """
    # NOTE: browser-use 0.1.48 has no `browser_use.llm` module; the
    # project's own WebUI uses langchain_openai.ChatOpenAI instead.
    from langchain_openai import ChatOpenAI
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

    gemini_key = _get_gemini_credential()
    if gemini_key:
        http_client = httpx.Client(proxy=proxy_url, timeout=120.0) if proxy_url else None
        return ChatOpenAI(
            model=os.environ.get("ETHIO_LLM_MODEL", "gemini-3.8-flash"),
            base_url=os.environ.get("ETHIO_LLM_BASE_URL", GEMINI_OPENAI_BASE_URL),
            api_key=gemini_key,
            http_client=http_client,
        )
    model = os.environ.get("ETHIO_LLM_MODEL", "gpt-4o")
    # OPENAI_API_KEY is read from the environment by the client itself.
    return ChatOpenAI(model=model)


def _build_browser() -> Any:
    """A fresh headless browser for one job.

    Lets browser-use manage Chrome via Playwright's native launch (not CDP
    to an external process). Points it at Playwright's bundled Chromium and
    forces the DevTools endpoint onto IPv4 127.0.0.1 to dodge the sandbox's
    localhost->::1 IPv6 mismatch.
    """
    from browser_use.browser.browser import Browser, BrowserConfig

    headless_raw = os.environ.get("ETHIO_HEADLESS", "true").lower()
    headless = headless_raw not in ("0", "false", "no", "off")
    chrome_path = os.environ.get("ETHIO_CHROME_PATH") or (
        os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux/chrome")
    )
    kwargs: dict = {"headless": headless}
    if os.path.exists(chrome_path):
        kwargs["chrome_instance_path"] = chrome_path
    # Note: do NOT force --remote-debugging-address; Chrome's default
    # localhost binding is dual-stack and matches browser-use's localhost
    # CDP connection. Forcing IPv4-only breaks the ::1 resolution.
    return Browser(config=BrowserConfig(**kwargs))


def _summarize_step(agent_output: Any, step_number: int) -> str:
    """One short log line per agent step. Never raises."""
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
                names.append(str(next(iter(action))))
            else:
                names.append(type(action).__name__)
        action_part = ", ".join(names[:3]) if names else "thinking"
        text = f"step {step_number}: {action_part}"
        if goal:
            text += f" - {goal}"
        return text[:300]
    except Exception as exc:  # never let logging break the run
        return f"step {step_number}: (unreadable step: {type(exc).__name__})"


def _build_agent(job: Job, on_step: Any) -> Any:
    """Create the browser-use Agent for a job. Called inside the runner."""
    import browser_use

    llm = _build_llm()
    browser = _build_browser()
    task_text = job.goal
    if job.inputs:
        lines = "\n".join(f"- {k}: {v}" for k, v in job.inputs.items())
        task_text = f"{task_text}\n\nInputs:\n{lines}"
    max_steps = int(os.environ.get("ETHIO_MAX_STEPS", "50"))
    agent = browser_use.Agent(
        task=task_text,
        llm=llm,
        browser=browser,
        register_new_step_callback=on_step,
        max_actions_per_step=5,
        # Memory (mem0 embeddings) needs an OpenAI key we don't have; the
        # agent works fine without long-term memory for single tasks.
        enable_memory=False,
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


async def _run_job(job: Job) -> None:
    """Background runner: executes the agent, enforces timeout, records."""
    timeout_s = float(os.environ.get("ETHIO_JOB_TIMEOUT_S", "1200"))

    async def on_step(browser_state: Any, agent_output: Any, step_no: int) -> None:
        job.log.append(_summarize_step(agent_output, step_no))

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
    job.state = JobState.RUNNING
    job.started_at = time.time()
    job.log.append("agent started")
    logger.info("job %s running (timeout %ss)", job.job_id, timeout_s)

    try:
        history = await asyncio.wait_for(
            agent.run(max_steps=agent._ethio_max_steps), timeout=timeout_s
        )
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
        try:
            job.final_result = history.final_result()
        except Exception:
            job.final_result = None
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
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="ETHIO browser-use gateway", version=VERSION)


@app.get("/health")
async def health() -> Dict[str, Any]:
    """No auth. For load balancers and the Flutter client's ping."""
    return {"ok": True, "version": VERSION}


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
    job = Job(
        job_id=job_id,
        session_id=session_id,
        goal=body.goal.strip(),
        inputs=dict(body.inputs),
    )
    _JOBS[job_id] = job
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
    if job.agent is not None:
        _safe_stop(job.agent)
    if job.task is not None and not job.task.done():
        job.task.cancel()
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
