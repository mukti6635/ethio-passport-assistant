"""Contract tests for the ETHIO browser-use gateway.

Uses FastAPI's TestClient with a MOCKED `browser_use.Agent` - no real
browser, no LLM key, no network. The fake `browser_use` module is injected
into `sys.modules`, and `browser_use.Agent` is monkeypatched per test.
"""

import sys
import time
import types

import pytest
from fastapi.testclient import TestClient

import gateway


# ---------------------------------------------------------------------------
# Fake browser_use
# ---------------------------------------------------------------------------


class FakeHistory:
    def __init__(self, result="mock-result-ok"):
        self._result = result

    def final_result(self):
        return self._result


class FakeStepOutput:
    """Junk step output: the gateway's summarizer must not crash on it."""

    class _CurrentState:
        next_goal = "fill in the name field"

    current_state = _CurrentState()
    action = [{"click_element": {"index": 3}}]


class FakeAgent:
    """Controllable stand-in for browser_use.Agent."""

    instances = []
    default_behavior = "hang"  # tests override per-test BEFORE starting a job

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.pause_calls = 0
        self.resume_calls = 0
        self.stop_calls = 0
        self.behavior = FakeAgent.default_behavior  # "hang" | "succeed" | "fail"
        self.fail_error = RuntimeError("boom")
        self._loop = None
        self._release = None
        FakeAgent.instances.append(self)

    async def run(self, *args, **kwargs):
        import asyncio

        self._loop = asyncio.get_running_loop()
        self._release = asyncio.Event()
        cb = self.kwargs.get("register_new_step_callback")
        if cb is not None:
            await cb(None, FakeStepOutput(), 1)
        if self.behavior == "fail":
            raise self.fail_error
        if self.behavior == "succeed":
            return FakeHistory()
        await self._release.wait()  # hang until released / stopped
        return FakeHistory()

    def release(self):
        """Thread-safe: called from the test thread."""
        if self._loop is not None and self._release is not None:
            self._loop.call_soon_threadsafe(self._release.set)

    def pause(self):
        self.pause_calls += 1

    def resume(self):
        self.resume_calls += 1

    def stop(self):
        self.stop_calls += 1
        self.release()


@pytest.fixture
def fake_browser_use(monkeypatch):
    """Inject a fake `browser_use` module and monkeypatch its Agent."""
    saved = {
        name: sys.modules[name]
        for name in (
            "browser_use",
            "browser_use.llm",
            "browser_use.browser",
            "browser_use.browser.browser",
            "langchain_openai",
        )
        if name in sys.modules
    }

    mod = types.ModuleType("browser_use")
    llm_mod = types.ModuleType("browser_use.llm")
    browser_pkg = types.ModuleType("browser_use.browser")
    browser_mod = types.ModuleType("browser_use.browser.browser")

    class FakeChatOpenAI:
        def __init__(self, model=None, **kwargs):
            self.model = model

    class FakeBrowserConfig:
        def __init__(self, headless=True, **kwargs):
            self.headless = headless

    class FakeBrowser:
        def __init__(self, config=None):
            self.config = config
            self.closed = False

        async def close(self):
            self.closed = True

    # gateway.py imports ChatOpenAI from langchain_openai (browser-use
    # 0.1.48 has no browser_use.llm module); fake that too.
    lc_mod = types.ModuleType("langchain_openai")
    lc_mod.ChatOpenAI = FakeChatOpenAI

    llm_mod.ChatOpenAI = FakeChatOpenAI
    browser_mod.Browser = FakeBrowser
    browser_mod.BrowserConfig = FakeBrowserConfig
    mod.llm = llm_mod
    mod.browser = browser_pkg
    browser_pkg.browser = browser_mod

    sys.modules["browser_use"] = mod
    sys.modules["browser_use.llm"] = llm_mod
    sys.modules["browser_use.browser"] = browser_pkg
    sys.modules["browser_use.browser.browser"] = browser_mod
    sys.modules["langchain_openai"] = lc_mod

    # The point: browser_use.Agent is monkeypatched, never the real thing.
    monkeypatch.setattr(mod, "Agent", FakeAgent, raising=False)

    FakeAgent.instances.clear()
    yield mod

    for name in (
        "browser_use",
        "browser_use.llm",
        "browser_use.browser",
        "browser_use.browser.browser",
        "langchain_openai",
    ):
        sys.modules.pop(name, None)
    sys.modules.update(saved)
    FakeAgent.instances.clear()


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_jobs():
    gateway._JOBS.clear()
    for key in gateway._METRICS:
        gateway._METRICS[key] = 0
    yield
    gateway._JOBS.clear()


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEY", "test-key")
    return "test-key"


@pytest.fixture
def client():
    # Context-manager form keeps ONE event loop alive for the whole test,
    # so background asyncio tasks (the job runners) survive across requests.
    # Without it, this starlette version closes the loop after each request.
    with TestClient(gateway.app) as c:
        yield c


def _h(key="test-key", session="sess-A"):
    headers = {"X-Ethio-Session": session}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _start(client, headers, goal="do the thing", inputs=None):
    body = {"goal": goal, "inputs": inputs or {}, "session_id": headers["X-Ethio-Session"]}
    r = client.post("/tasks", json=body, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def _wait_state(client, job_id, headers, want, timeout=8.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/tasks/status/{job_id}", headers=headers)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["state"] == want:
            return last
        time.sleep(0.05)
    raise AssertionError(f"never reached {want}; last={last}")


def _release_agent(agent, timeout=8.0):
    deadline = time.time() + timeout
    while agent._release is None and time.time() < deadline:
        time.sleep(0.02)
    assert agent._release is not None, "agent never started its run loop"
    agent.release()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_health_needs_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "1.0.0"}


def test_start_rejects_missing_token(client, api_key):
    r = client.post("/tasks", json={"goal": "x"}, headers=_h(key=None))
    assert r.status_code == 401


def test_start_rejects_wrong_token(client, api_key):
    r = client.post("/tasks", json={"goal": "x"}, headers=_h(key="wrong"))
    assert r.status_code == 401


def test_missing_api_key_fails_closed(client, monkeypatch):
    monkeypatch.delenv("GATEWAY_API_KEY", raising=False)
    r = client.post("/tasks", json={"goal": "x"}, headers=_h())
    assert r.status_code == 500
    assert "misconfigured" in r.json()["detail"]


def test_missing_session_header_rejected(client, api_key):
    r = client.post(
        "/tasks",
        json={"goal": "x"},
        headers={"Authorization": "Bearer test-key"},
    )
    assert r.status_code == 400


def test_body_session_must_match_header(client, api_key, fake_browser_use):
    headers = _h(session="sess-A")
    body = {"goal": "x", "inputs": {}, "session_id": "sess-B"}
    r = client.post("/tasks", json=body, headers=headers)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


def test_session_isolation(client, api_key, fake_browser_use):
    a = _h(session="sess-A")
    b = _h(session="sess-B")
    job_id = _start(client, a)

    assert client.get(f"/tasks/status/{job_id}", headers=b).status_code == 404
    assert (
        client.post(
            f"/tasks/pause/{job_id}", json={"session_id": "sess-B"}, headers=b
        ).status_code
        == 404
    )
    assert client.get(f"/tasks/evidence/{job_id}", headers=b).status_code == 404
    # Owner still sees it.
    assert client.get(f"/tasks/status/{job_id}", headers=a).status_code == 200


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_full_lifecycle_pause_resume_cancel(client, api_key, fake_browser_use):
    h = _h()
    job_id = _start(client, h, goal="fill the mock form")
    # Wait for running BEFORE touching instances: the gateway sets RUNNING
    # only after the agent is created, so this removes the race where the
    # background task hasn't run yet when POST /tasks returns 202.
    _wait_state(client, job_id, h, "running")
    agent = FakeAgent.instances[-1]
    assert agent.kwargs["task"].startswith("fill the mock form")
    # Step callback fed the log without crashing.
    status = client.get(f"/tasks/status/{job_id}", headers=h).json()
    assert any("click_element" in line for line in status["log"])

    # Pause without checkpoint -> paused.
    r = client.post("/tasks/pause/{0}".format(job_id), json={"session_id": "sess-A"}, headers=h)
    assert r.json() == {"ok": True}
    assert agent.pause_calls == 1
    assert _wait_state(client, job_id, h, "paused")["state"] == "paused"

    # Resume -> running.
    r = client.post(f"/tasks/resume/{job_id}", json={"session_id": "sess-A"}, headers=h)
    assert r.json() == {"ok": True}
    assert agent.resume_calls == 1
    _wait_state(client, job_id, h, "running")

    # Pause WITH checkpoint -> awaiting_human.
    r = client.post(
        f"/tasks/pause/{job_id}",
        json={"checkpoint": "otp", "session_id": "sess-A"},
        headers=h,
    )
    assert r.json() == {"ok": True}
    assert _wait_state(client, job_id, h, "awaiting_human")["state"] == "awaiting_human"

    # Resume from checkpoint -> running again.
    client.post(f"/tasks/resume/{job_id}", json={"session_id": "sess-A"}, headers=h)
    _wait_state(client, job_id, h, "running")

    # Let the agent finish -> succeeded, evidence available.
    _release_agent(agent)
    done = _wait_state(client, job_id, h, "succeeded")
    assert done["state"] == "succeeded"
    ev = client.get(f"/tasks/evidence/{job_id}", headers=h)
    assert ev.status_code == 200
    assert ev.json()["final_result"] == "mock-result-ok"


def test_cancel_is_idempotent(client, api_key, fake_browser_use):
    h = _h()
    job_id = _start(client, h)
    # Same race fix: RUNNING implies the agent instance exists.
    _wait_state(client, job_id, h, "running")
    agent = FakeAgent.instances[-1]

    assert client.post(f"/tasks/cancel/{job_id}", json={"session_id": "sess-A"}, headers=h).json() == {"ok": True}
    assert agent.stop_calls >= 1
    assert _wait_state(client, job_id, h, "cancelled")["state"] == "cancelled"

    # Second cancel: harmless no-op.
    r = client.post(f"/tasks/cancel/{job_id}", json={"session_id": "sess-A"}, headers=h)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Pause/resume on a terminal job -> 409, not silent weirdness.
    assert client.post(f"/tasks/pause/{job_id}", json={"session_id": "sess-A"}, headers=h).status_code == 409
    assert client.post(f"/tasks/resume/{job_id}", json={"session_id": "sess-A"}, headers=h).status_code == 409


def test_evidence_only_for_terminal_jobs(client, api_key, fake_browser_use):
    h = _h()
    job_id = _start(client, h)
    _wait_state(client, job_id, h, "running")
    # Still running: the gateway must not invent evidence.
    assert client.get(f"/tasks/evidence/{job_id}", headers=h).status_code == 404


def test_agent_exception_marks_failed_without_secrets(
    client, api_key, fake_browser_use, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-do-not-log")
    monkeypatch.setattr(FakeAgent, "default_behavior", "fail")
    h = _h()
    job_id = _start(client, h)
    done = _wait_state(client, job_id, h, "failed", timeout=10.0)
    assert done["state"] == "failed"
    assert any("boom" in line for line in done["log"])
    assert not any("sk-super-secret" in line for line in done["log"])


def test_job_timeout(client, api_key, fake_browser_use, monkeypatch):
    monkeypatch.setenv("ETHIO_JOB_TIMEOUT_S", "0.2")
    h = _h()
    job_id = _start(client, h)
    done = _wait_state(client, job_id, h, "timed_out", timeout=10.0)
    assert done["state"] == "timed_out"
    assert any("timed out" in line for line in done["log"])
    # Evidence is available for terminal jobs, even timed-out ones.
    assert client.get(f"/tasks/evidence/{job_id}", headers=h).status_code == 200


def test_start_rejects_empty_goal(client, api_key, fake_browser_use):
    r = client.post("/tasks", json={"goal": "   ", "inputs": {}}, headers=_h())
    assert r.status_code == 400


def test_gemini_key_routes_to_google_openai_endpoint(
    fake_browser_use, monkeypatch
):
    """GEMINI_API_KEY set -> ChatOpenAI pointed at Google's OpenAI-compatible
    endpoint, never at api.openai.com. The key itself is passed through, not
    logged or embedded anywhere."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    created = {}

    class SpyChatOpenAI:
        def __init__(self, model=None, base_url=None, api_key=None, **kwargs):
            created["model"] = model
            created["base_url"] = base_url
            created["api_key"] = api_key

    monkeypatch.setitem(
        sys.modules, "langchain_openai",
        types.SimpleNamespace(ChatOpenAI=SpyChatOpenAI),
    )
    llm = gateway._build_llm()
    assert isinstance(llm, SpyChatOpenAI)
    assert created["base_url"] == gateway.GEMINI_OPENAI_BASE_URL
    assert "generativelanguage.googleapis.com" in created["base_url"]
    assert "api.openai.com" not in created["base_url"]
    assert created["model"] == "gemini-3.8-flash"
    assert created["api_key"] == "test-gemini-key"


def test_no_gemini_key_falls_back_to_openai(fake_browser_use, monkeypatch):
    """Without GEMINI_API_KEY the gateway keeps the previous OpenAI behavior."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    created = {}

    class SpyChatOpenAI:
        def __init__(self, model=None, base_url=None, api_key=None, **kwargs):
            created["model"] = model
            created["base_url"] = base_url

    monkeypatch.setitem(
        sys.modules, "langchain_openai",
        types.SimpleNamespace(ChatOpenAI=SpyChatOpenAI),
    )
    gateway._build_llm()
    assert created["model"] == "gpt-4o"
    assert created["base_url"] is None


def test_metrics_endpoint_reports_counters(client, api_key, fake_browser_use):
    """GET /metrics (auth required) exposes job counters and state breakdown."""
    # No auth -> rejected
    assert client.get("/metrics").status_code in (401, 403, 422)
    h = _h()
    r = client.get("/metrics", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == gateway.VERSION
    assert body["counters"]["jobs_created"] == 0

    job_id = _start(client, h)
    _wait_state(client, job_id, h, "running")
    r = client.get("/metrics", headers=h)
    body = r.json()
    assert body["counters"]["jobs_created"] == 1
    assert body["jobs_by_state"].get("running", 0) >= 1
