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

    def is_successful(self):
        return True


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
        )
        if name in sys.modules
    }

    mod = types.ModuleType("browser_use")
    llm_mod = types.ModuleType("browser_use.llm")

    class FakeChatOpenAI:
        def __init__(self, model=None, **kwargs):
            self.model = model

    class FakeBrowser:
        def __init__(self, cdp_url=None, **kwargs):
            self.cdp_url = cdp_url
            self.closed = False

        async def close(self):
            self.closed = True

    # gateway.py imports ChatOpenAI from browser_use.llm (0.13.x);
    # fake that module.
    llm_mod.ChatOpenAI = FakeChatOpenAI
    mod.llm = llm_mod
    mod.Browser = FakeBrowser

    # Mock _build_browser to avoid launching real Chrome in tests.
    # The real function launches Chrome via subprocess which fails in test env.
    import gateway as gw_module
    original_build_browser = gw_module._build_browser
    def fake_build_browser():
        return FakeBrowser(cdp_url="http://127.0.0.1:9999")
    monkeypatch.setattr(gw_module, "_build_browser", fake_build_browser)

    sys.modules["browser_use"] = mod
    sys.modules["browser_use.llm"] = llm_mod

    # The point: browser_use.Agent is monkeypatched, never the real thing.
    monkeypatch.setattr(mod, "Agent", FakeAgent, raising=False)

    FakeAgent.instances.clear()
    yield mod

    for name in (
        "browser_use",
        "browser_use.llm",
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
    # Task now prepends layout-adaptation guidance; goal must still be present.
    assert "fill the mock form" in agent.kwargs["task"]
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
    """ETHIO_LLM_PROVIDER=gemini + GEMINI_API_KEY -> Google's OpenAI-compatible
    endpoint, never at api.openai.com. The key itself is passed through, not
    logged or embedded anywhere."""
    monkeypatch.setenv("ETHIO_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    created = {}

    class SpyChatOpenAI:
        def __init__(self, model=None, base_url=None, api_key=None, **kwargs):
            created["model"] = model
            created["base_url"] = base_url
            created["api_key"] = api_key

    monkeypatch.setitem(
        sys.modules, "browser_use.llm",
        types.SimpleNamespace(ChatOpenAI=SpyChatOpenAI),
    )
    llm = gateway._build_llm()
    assert isinstance(llm, SpyChatOpenAI)
    assert created["base_url"] == gateway.GEMINI_OPENAI_BASE_URL
    assert "generativelanguage.googleapis.com" in created["base_url"]
    assert "api.openai.com" not in created["base_url"]
    assert created["model"] == "gemini-3.8-flash"
    assert created["api_key"] == "test-gemini-key"


def test_unknown_provider_falls_back_to_openai(fake_browser_use, monkeypatch):
    """Unknown ETHIO_LLM_PROVIDER value -> OpenAI fallback behavior."""
    monkeypatch.setenv("ETHIO_LLM_PROVIDER", "unknown-provider")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    created = {}

    class SpyChatOpenAI:
        def __init__(self, model=None, base_url=None, api_key=None, **kwargs):
            created["model"] = model
            created["base_url"] = base_url

    monkeypatch.setitem(
        sys.modules, "browser_use.llm",
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


def test_second_job_for_same_session_rejected(client, api_key, fake_browser_use, monkeypatch):
    """One active browser per session: a second POST /tasks returns 409."""
    monkeypatch.setattr(FakeAgent, "default_behavior", "hang")
    h = _h()
    job1 = _start(client, h)
    _wait_state(client, job1, h, "running")
    # Same session, second job -> 409 with the existing job id
    r = client.post(
        "/tasks",
        headers=h,
        json={"goal": "another", "session_id": "sess-A", "inputs": {}},
    )
    assert r.status_code == 409
    assert job1 in r.json()["detail"]
    # Different session is fine
    h2 = _h(session="other-session")
    job2 = _start(client, h2)
    assert job2 != job1


def test_global_concurrency_limit(client, api_key, fake_browser_use, monkeypatch):
    """Beyond ETHIO_MAX_CONCURRENT_JOBS, new jobs get 429."""
    monkeypatch.setattr(FakeAgent, "default_behavior", "hang")
    monkeypatch.setenv("ETHIO_MAX_CONCURRENT_JOBS", "2")
    ids = []
    for i in range(2):
        h = _h(session=f"sess-{i}")
        jid = _start(client, h)
        _wait_state(client, jid, h, "running")
        ids.append(jid)
    r = client.post(
        "/tasks",
        headers=_h(session="sess-overflow"),
        json={"goal": "x", "session_id": "sess-overflow", "inputs": {}},
    )
    assert r.status_code == 429
    assert "max 2" in r.json()["detail"]


def test_llm_uses_async_client_and_no_frequency_penalty(
    fake_browser_use, monkeypatch
):
    """Regression test: browser-use 0.13.x requires httpx.AsyncClient, and
    Gemini's OpenAI-compatible endpoint rejects frequency_penalty.

    The original failure: Agent.run() failed at Step 1 with "Connection error"
    because (1) httpx.Client was passed instead of httpx.AsyncClient, and
    (2) frequency_penalty was sent by default which Gemini rejects with 400.
    """
    monkeypatch.setenv("ETHIO_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    # Ensure the proxy is set so http_client gets created
    monkeypatch.setenv("https_proxy", "http://test-proxy:8080")

    created = {}

    class SpyChatOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "browser_use.llm",
        types.SimpleNamespace(ChatOpenAI=SpyChatOpenAI),
    )
    gateway._build_llm()

    # Must use AsyncClient (browser-use 0.13.x requirement)
    http_client = created.get("http_client")
    assert http_client is not None, "http_client must be provided"
    import httpx
    assert isinstance(http_client, httpx.AsyncClient), (
        f"Expected httpx.AsyncClient, got {type(http_client).__name__}. "
        "browser-use 0.13.x rejects httpx.Client."
    )

    # frequency_penalty must not be sent (Gemini rejects it with 400)
    assert created.get("frequency_penalty") is None, (
        "frequency_penalty must be None/omitted; "
        "Gemini's OpenAI endpoint returns 400 for this field."
    )


def test_task_prompt_includes_layout_adaptation_guidance(
    client, api_key, fake_browser_use, monkeypatch
):
    """Regression test: every agent task must include layout-adaptation guidance.

    The agent must identify fields from live page labels/names/state, not from
    fixed IDs or positions, and must stop on ambiguity. This test verifies the
    guidance is prepended to the task text without making any model request.
    """
    import gateway as gateway_module
    # Mock Groq credential since Groq is now the default provider
    monkeypatch.setattr(gateway_module, "_get_groq_credential", lambda: "test-groq-key")

    FakeAgent.instances.clear()

    # Build a minimal job and call _build_agent directly
    job = gateway_module.Job(
        job_id="test-adapt",
        session_id="test-session",
        goal="Fill the full name field",
        inputs={"full_name": "Abebe Tesfaye"},
    )

    def on_step(*args):
        pass

    agent = gateway_module._build_agent(job, on_step)
    task_text = agent.kwargs.get("task", "")

    # Original goal must be preserved
    assert "Fill the full name field" in task_text
    # Inputs must be preserved
    assert "Abebe Tesfaye" in task_text
    # Layout-adaptation guidance must be present
    assert "actual labels" in task_text
    assert "not from fixed IDs or screen positions" in task_text
    assert "verify the actual resulting value" in task_text
    assert "Stop and request clarification" in task_text
    assert "Never submit forms" in task_text
    assert "mock portal" in task_text


def test_groq_provider_selected_when_env_set(fake_browser_use, monkeypatch):
    """Provider selection: ETHIO_LLM_PROVIDER=groq uses Groq endpoint."""
    monkeypatch.setenv("ETHIO_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("https_proxy", "http://test-proxy:8080")

    created = {}

    class SpyChatOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "browser_use.llm",
        types.SimpleNamespace(ChatOpenAI=SpyChatOpenAI),
    )
    import gateway as gw
    gw._build_llm()

    assert created.get("base_url") == "https://api.groq.com/openai/v1"
    assert created.get("model") == "openai/gpt-oss-120b"  # default Groq model
    assert created.get("api_key") == "test-groq-key"


def test_groq_provider_fails_safely_without_key(fake_browser_use, monkeypatch):
    """Provider selection: groq without key raises, never falls back to Gemini."""
    monkeypatch.setenv("ETHIO_LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Ensure vault lookup fails too
    monkeypatch.setitem(sys.modules, "dynamic_credentials",
                        types.SimpleNamespace(
                            dynamic_credential_entry=lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("no vault"))))

    import gateway as gw
    import pytest
    with pytest.raises(RuntimeError, match="no Groq credential"):
        gw._build_llm()


def test_groq_is_default_provider(fake_browser_use, monkeypatch):
    """Provider selection: default (no ETHIO_LLM_PROVIDER) uses Groq."""
    monkeypatch.delenv("ETHIO_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("https_proxy", "http://test-proxy:8080")

    created = {}

    class SpyChatOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "browser_use.llm",
        types.SimpleNamespace(ChatOpenAI=SpyChatOpenAI),
    )
    import gateway as gw
    gw._build_llm()

    assert created.get("base_url") == "https://api.groq.com/openai/v1"
    assert created.get("model") == "openai/gpt-oss-120b"  # default Groq model


def test_gemini_selected_when_explicitly_configured(fake_browser_use, monkeypatch):
    """Provider selection: ETHIO_LLM_PROVIDER=gemini uses Gemini."""
    monkeypatch.setenv("ETHIO_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("https_proxy", "http://test-proxy:8080")

    created = {}

    class SpyChatOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "browser_use.llm",
        types.SimpleNamespace(ChatOpenAI=SpyChatOpenAI),
    )
    import gateway as gw
    gw._build_llm()

    assert "generativelanguage.googleapis.com" in created.get("base_url", "")
    assert created.get("model") == "gemini-3.8-flash"  # default Gemini model


def test_summarize_step_includes_loop_diagnostics():
    """Diagnostic logging: loop detector state appears when thresholds met."""
    import gateway as gw
    import types

    # Fake agent output with an action
    output = types.SimpleNamespace(
        current_state=types.SimpleNamespace(
            next_goal="fill the form",
            evaluation_previous_goal="",
        ),
        action=[{"input": {"index": 2, "text": "SECRET_VALUE_SHOULD_NOT_APPEAR"}}],
    )

    # Fake job with agent state showing loop detection
    loop = types.SimpleNamespace(
        max_repetition_count=5,
        consecutive_stagnant_pages=4,
    )
    state = types.SimpleNamespace(
        loop_detector=loop,
        consecutive_failures=3,
    )
    agent = types.SimpleNamespace(state=state)
    job = types.SimpleNamespace(agent=agent)

    text = gw._summarize_step(output, 7, job)

    # Action type logged, but never the value
    assert "input" in text
    assert "SECRET_VALUE_SHOULD_NOT_APPEAR" not in text
    # Loop diagnostics present
    assert "rep=5" in text
    assert "stag=4" in text
    assert "failures=3" in text


def test_summarize_step_omits_loop_diagnostics_when_calm():
    """Diagnostic logging: no loop noise when counts are low."""
    import gateway as gw
    import types

    output = types.SimpleNamespace(
        current_state=types.SimpleNamespace(next_goal="", evaluation_previous_goal=""),
        action=[{"navigate": {"url": "http://example.com"}}],
    )
    loop = types.SimpleNamespace(max_repetition_count=1, consecutive_stagnant_pages=1)
    state = types.SimpleNamespace(loop_detector=loop, consecutive_failures=0)
    job = types.SimpleNamespace(agent=types.SimpleNamespace(state=state))

    text = gw._summarize_step(output, 1, job)
    assert "loop:" not in text
    assert "failures=" not in text
    # URL is safe to log (it's the mock portal, not a secret)
    assert "navigate" in text


def test_start_rejects_oversized_goal(client, api_key, fake_browser_use):
    """Input validation: oversized goal rejected (DoS prevention)."""
    h = {"X-Ethio-Session": "s1", "Authorization": f"Bearer {api_key}"}
    r = client.post("/tasks", json={
        "goal": "x" * 3000,
        "inputs": {},
        "session_id": "s1",
    }, headers=h)
    assert r.status_code == 422


def test_start_rejects_too_many_inputs(client, api_key, fake_browser_use):
    """Input validation: too many inputs rejected."""
    h = {"X-Ethio-Session": "s1", "Authorization": f"Bearer {api_key}"}
    r = client.post("/tasks", json={
        "goal": "test",
        "inputs": {f"k{i}": "v" for i in range(60)},
        "session_id": "s1",
    }, headers=h)
    assert r.status_code == 422


def test_rate_limit_blocks_excessive_tasks(client, api_key, fake_browser_use, monkeypatch):
    """Rate limiting: session exceeding limit gets 429, no job created."""
    import gateway as gw
    # Set a low limit for testing
    monkeypatch.setenv("ETHIO_RATE_LIMIT_TASKS", "2")
    monkeypatch.setenv("ETHIO_RATE_LIMIT_WINDOW", "3600")
    # Clear any existing buckets
    gw._RATE_LIMIT_BUCKETS.clear()

    h = {"X-Ethio-Session": "rate-test", "Authorization": f"Bearer {api_key}"}

    # First 2 should succeed (but we need to cancel them to avoid session conflict)
    for i in range(2):
        r = client.post("/tasks", json={
            "goal": f"test {i}",
            "inputs": {},
            "session_id": "rate-test",
        }, headers=h)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        # Cancel to free the session for next request
        client.post(f"/tasks/cancel/{job_id}", json={"session_id": "rate-test"}, headers=h)

    # Third should be rate-limited
    r = client.post("/tasks", json={
        "goal": "test 3",
        "inputs": {},
        "session_id": "rate-test",
    }, headers=h)
    assert r.status_code == 429
    assert "rate limit" in r.json()["detail"].lower()
    assert "Retry-After" in r.headers


def test_rate_limit_isolated_per_session(client, api_key, fake_browser_use, monkeypatch):
    """Rate limiting: limits apply per session, not globally."""
    import gateway as gw
    monkeypatch.setenv("ETHIO_RATE_LIMIT_TASKS", "1")
    monkeypatch.setenv("ETHIO_RATE_LIMIT_WINDOW", "3600")
    gw._RATE_LIMIT_BUCKETS.clear()

    h1 = {"X-Ethio-Session": "sess-1", "Authorization": f"Bearer {api_key}"}
    h2 = {"X-Ethio-Session": "sess-2", "Authorization": f"Bearer {api_key}"}

    # Session 1 uses its allowance
    r = client.post("/tasks", json={"goal": "t", "inputs": {}, "session_id": "sess-1"}, headers=h1)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    client.post(f"/tasks/cancel/{job_id}", json={"session_id": "sess-1"}, headers=h1)

    # Session 1 now blocked
    r = client.post("/tasks", json={"goal": "t", "inputs": {}, "session_id": "sess-1"}, headers=h1)
    assert r.status_code == 429

    # Session 2 still allowed (isolated)
    r = client.post("/tasks", json={"goal": "t", "inputs": {}, "session_id": "sess-2"}, headers=h2)
    assert r.status_code == 202


def test_invalid_job_id_returns_404(client, api_key, fake_browser_use):
    """Recovery: invalid job IDs return 404, not 500."""
    h = {"X-Ethio-Session": "s1", "Authorization": f"Bearer {api_key}"}
    r = client.get("/tasks/status/nonexistent-job-id", headers=h)
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_cross_user_job_access_denied(client, api_key, fake_browser_use):
    """Isolation: user cannot access another user's job."""
    h1 = {"X-Ethio-Session": "user-a", "Authorization": f"Bearer {api_key}"}
    h2 = {"X-Ethio-Session": "user-b", "Authorization": f"Bearer {api_key}"}

    # User A creates a job
    r = client.post("/tasks", json={"goal": "t", "inputs": {}, "session_id": "user-a"}, headers=h1)
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # User B tries to access it -> 404 (not found, not forbidden, to avoid leaking existence)
    r = client.get(f"/tasks/status/{job_id}", headers=h2)
    assert r.status_code == 404

    # User B tries to cancel it -> 404
    r = client.post(f"/tasks/cancel/{job_id}", json={"session_id": "user-b"}, headers=h2)
    assert r.status_code == 404


def test_step_replay_detects_repetition_without_llm():
    """Deterministic replay: synthetic agent outputs trigger loop diagnostics.

    Uses recorded (sanitized) step patterns, no live LLM, no browser.
    Verifies the safety infrastructure catches repetition.
    """
    import gateway as gw
    import types

    # Simulate 5 steps with the same action (repetition pattern)
    # as observed in failed Groq runs
    for step_no in range(1, 6):
        output = types.SimpleNamespace(
            current_state=types.SimpleNamespace(
                next_goal="fill the name field",
                evaluation_previous_goal="",
            ),
            action=[{"input": {"index": 2}}],  # action type only, no values
        )
        # Create a fake job with loop detector state
        job = types.SimpleNamespace()
        job.agent = types.SimpleNamespace()
        job.agent.state = types.SimpleNamespace()
        job.agent.state.loop_detector = types.SimpleNamespace(
            max_repetition_count=step_no,
            consecutive_stagnant_pages=0,
        )
        job.agent.state.consecutive_failures = 0

        summary = gw._summarize_step(output, step_no, job)
        # Secret-safe: action type logged, no values
        assert "input" in summary
        assert "Abebe" not in summary  # no PII in test data anyway
        # Loop diagnostics appear when threshold met
        if step_no >= 3:
            assert "[loop:" in summary


def test_step_replay_safe_stop_on_stagnation():
    """Deterministic: stagnant pages trigger diagnostics."""
    import gateway as gw
    import types

    output = types.SimpleNamespace(
        current_state=types.SimpleNamespace(next_goal="", evaluation_previous_goal=""),
        action=[],
    )
    job = types.SimpleNamespace()
    job.agent = types.SimpleNamespace()
    job.agent.state = types.SimpleNamespace()
    job.agent.state.loop_detector = types.SimpleNamespace(
        max_repetition_count=0,
        consecutive_stagnant_pages=5,
    )
    job.agent.state.consecutive_failures = 0

    summary = gw._summarize_step(output, 8, job)
    assert "[loop:" in summary
    assert "stag=5" in summary


def test_orchestrator_verified_step_updates_state():
    """Orchestrator: verified action updates state correctly."""
    import sys
    sys.path.insert(0, "api")
    from orchestrator import SingleStepOrchestrator, OrchestratorState

    orch = SingleStepOrchestrator(goal="fill name", inputs={"name": "Test"})
    state = orch.record_step(
        action_type="input",
        observation="<input id='name' value='Test'>",
        verified=True,
        field_name="fullName",
        field_value="Test",
    )
    assert state == OrchestratorState.RUNNING
    assert orch.should_continue(state)
    assert len(orch.steps) == 1
    assert orch.steps[0].verified
    assert orch.verified_fields["fullName"] == "Test"


def test_orchestrator_failed_action_not_marked_complete():
    """Orchestrator: failed actions never marked complete; bounded retries."""
    import sys
    sys.path.insert(0, "api")
    from orchestrator import SingleStepOrchestrator, OrchestratorState

    orch = SingleStepOrchestrator(goal="fill name", inputs={})
    # 3 failures should exhaust retries
    for i in range(3):
        state = orch.record_step(
            action_type="input",
            observation="<input id='name' value=''>",
            verified=False,
        )
    assert state == OrchestratorState.FAILED
    assert not orch.should_continue(state)
    # No fields verified
    assert len(orch.verified_fields) == 0


def test_orchestrator_stagnation_triggers_safe_stop():
    """Orchestrator: repeated identical observations cause safe stop."""
    import sys
    sys.path.insert(0, "api")
    from orchestrator import SingleStepOrchestrator, OrchestratorState

    orch = SingleStepOrchestrator(goal="fill name", inputs={})
    obs = "<div>same page</div>"
    state = OrchestratorState.RUNNING
    for i in range(5):
        state = orch.record_step(
            action_type="click",
            observation=obs,  # identical each time
            verified=True,
        )
        if state != OrchestratorState.RUNNING:
            break
    assert state == OrchestratorState.STALLED
    assert not orch.should_continue(state)


def test_orchestrator_protected_action_requires_human():
    """Orchestrator: submit/payment/OTP actions trigger checkpoint."""
    import sys
    sys.path.insert(0, "api")
    from orchestrator import SingleStepOrchestrator, OrchestratorState

    orch = SingleStepOrchestrator(goal="submit form", inputs={})
    for action in ["submit", "payment", "otp"]:
        orch2 = SingleStepOrchestrator(goal="test", inputs={})
        state = orch2.record_step(
            action_type=action,
            observation="<form>",
            verified=True,
        )
        assert state == OrchestratorState.AWAITING_HUMAN, f"action={action}"
        assert not orch2.should_continue(state)


def test_orchestrator_summary_is_secret_safe():
    """Orchestrator: summary never contains field values."""
    import sys
    sys.path.insert(0, "api")
    from orchestrator import SingleStepOrchestrator

    orch = SingleStepOrchestrator(goal="test", inputs={})
    orch.record_step(
        action_type="input",
        observation="<input>",
        verified=True,
        field_name="fullName",
        field_value="Secret Value 123",
    )
    summary = orch.get_summary()
    # Field names OK, values never in summary
    assert "fullName" in summary["verified_fields"]
    assert "Secret Value 123" not in str(summary)


# ---------------------------------------------------------------------------
# Approval gate tests (15)
# ---------------------------------------------------------------------------

def _make_job_for_approval(client, api_key, session="appr-sess", goal="test"):
    """Create a job and return its id. Cancels any active job first."""
    import gateway as gw
    h = {"X-Ethio-Session": session, "Authorization": f"Bearer {api_key}"}
    # Clear rate-limit buckets for this session
    gw._RATE_LIMIT_BUCKETS.pop(session, None)
    r = client.post("/tasks", json={
        "goal": goal, "inputs": {}, "session_id": session,
    }, headers=h)
    assert r.status_code == 202, r.text
    return r.json()["job_id"], h


def _prepare(client, h, job_id, action="submit", params=None):
    """Prepare an approval; returns the response json."""
    params = params or {"form": "passport"}
    r = client.post("/approvals", json={
        "job_id": job_id,
        "action_type": action,
        "action_label": f"Test {action}",
        "consequence": "Test consequence.",
        "params": params,
        "params_summary": {"form": "passport"},
        "session_id": h["X-Ethio-Session"],
    }, headers=h)
    return r


def test_approval_01_create(client, api_key, fake_browser_use):
    """1. Creating an approval returns pending with id and expiry."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key)
    r = _prepare(client, h, job_id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == "pending"
    assert body["approval_id"]
    assert body["expires_at"] > body["created_at"]
    assert not body["consumed"]


def test_approval_02_transition_to_waiting(client, api_key, fake_browser_use):
    """2. Preparing approval moves a running job to waiting_approval."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s2")
    # Force job to running (simulates worker start)
    job = gw._JOBS[job_id]
    job.state = gw.JobState.RUNNING
    r = _prepare(client, h, job_id)
    assert r.status_code == 201
    assert gw._JOBS[job_id].state == gw.JobState.WAITING_APPROVAL


def test_approval_03_no_execute_while_pending(client, api_key, fake_browser_use):
    """3. Execute gate denies while approval is pending."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s3")
    r = _prepare(client, h, job_id)
    aid = r.json()["approval_id"]
    r = client.post(f"/approvals/{aid}/execute", json={
        "job_id": job_id, "action_type": "submit",
        "params": {"form": "passport"}, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 409


def test_approval_04_valid_approval_permits_one_execution(
    client, api_key, fake_browser_use
):
    """4. Approved approval authorizes exactly one execution."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s4")
    r = _prepare(client, h, job_id)
    aid = r.json()["approval_id"]
    # Decide approve
    r = client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["state"] == "approved"
    # Execute once: allowed
    r = client.post(f"/approvals/{aid}/execute", json={
        "job_id": job_id, "action_type": "submit",
        "params": {"form": "passport"}, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["authorized"] is True


def test_approval_05_rejection_prevents_execution(client, api_key, fake_browser_use):
    """5. Rejected approval can never execute."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s5")
    r = _prepare(client, h, job_id)
    aid = r.json()["approval_id"]
    r = client.post(f"/approvals/{aid}/decide", json={
        "approve": False, "reason": "not now",
        "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.json()["state"] == "rejected"
    r = client.post(f"/approvals/{aid}/execute", json={
        "job_id": job_id, "action_type": "submit",
        "params": {"form": "passport"}, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 409


def test_approval_06_expiry_prevents_execution(client, api_key, fake_browser_use):
    """6. Expired approval can never execute."""
    import gateway as gw
    from approvals import APPROVALS
    APPROVALS._approvals.clear()
    APPROVALS._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s6")
    # Prepare with 60s TTL (minimum allowed), then force-expire
    r = client.post("/approvals", json={
        "job_id": job_id, "action_type": "submit",
        "action_label": "x", "consequence": "y",
        "params": {"form": "passport"},
        "session_id": h["X-Ethio-Session"], "ttl_s": 60,
    }, headers=h)
    aid = r.json()["approval_id"]
    # Force expiry
    APPROVALS._approvals[aid].expires_at = 0
    # Decide should now report expired
    r = client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 409  # expired, cannot decide


def test_approval_07_duplicate_prepare_idempotent(client, api_key, fake_browser_use):
    """7. Same job+action+params returns the same pending approval."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s7")
    r1 = _prepare(client, h, job_id)
    r2 = _prepare(client, h, job_id)
    assert r1.json()["approval_id"] == r2.json()["approval_id"]


def test_approval_08_double_consume_denied(client, api_key, fake_browser_use):
    """8. Second execute with same approval is denied (exactly-once)."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s8")
    r = _prepare(client, h, job_id)
    aid = r.json()["approval_id"]
    client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    body = {"job_id": job_id, "action_type": "submit",
            "params": {"form": "passport"},
            "session_id": h["X-Ethio-Session"]}
    r1 = client.post(f"/approvals/{aid}/execute", json=body, headers=h)
    assert r1.status_code == 200
    r2 = client.post(f"/approvals/{aid}/execute", json=body, headers=h)
    assert r2.status_code == 409  # already consumed


def test_approval_09_concurrent_consume_single_winner(fake_browser_use):
    """9. Concurrent consume: exactly one thread wins."""
    import threading
    from approvals import ApprovalService
    svc = ApprovalService()
    a = svc.prepare(
        job_id="j1", session_id="s1", action_type="submit",
        action_label="x", consequence="y", params={"form": "p"},
    )
    svc.decide(a.approval_id, "s1", True)
    winners = []
    def attempt():
        r = svc.consume(a.approval_id, "s1", "j1", "submit", {"form": "p"})
        if r is not None:
            winners.append(1)
    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1


def test_approval_10_cross_user_denied(client, api_key, fake_browser_use):
    """10. Another session cannot see, decide, or execute the approval."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h1 = _make_job_for_approval(client, api_key, session="appr-a")
    h2 = {"X-Ethio-Session": "appr-b", "Authorization": f"Bearer {api_key}"}
    r = _prepare(client, h1, job_id)
    aid = r.json()["approval_id"]
    # List: user B sees nothing
    r = client.get("/approvals/pending", headers=h2)
    assert r.json()["approvals"] == []
    # Decide: denied
    r = client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": "appr-b",
    }, headers=h2)
    assert r.status_code == 409
    # Execute: denied (404 because the job itself is not visible to user B;
    # the approval gate would also deny it at 409 if the job existed)
    r = client.post(f"/approvals/{aid}/execute", json={
        "job_id": job_id, "action_type": "submit",
        "params": {"form": "passport"}, "session_id": "appr-b",
    }, headers=h2)
    assert r.status_code in (404, 409)


def test_approval_11_invalid_transitions_rejected(fake_browser_use):
    """11. Invalid job state transitions raise 409."""
    import gateway as gw
    from fastapi import HTTPException
    import pytest
    job = gw.Job(job_id="x", session_id="s", goal="g", inputs={})
    assert job.state == gw.JobState.QUEUED
    # queued -> succeeded is invalid
    with pytest.raises(HTTPException) as exc:
        gw._transition(job, gw.JobState.SUCCEEDED)
    assert exc.value.status_code == 409
    # queued -> running is valid
    gw._transition(job, gw.JobState.RUNNING)
    # running -> waiting_approval is valid
    gw._transition(job, gw.JobState.WAITING_APPROVAL)
    # waiting_approval -> running is valid (resume)
    gw._transition(job, gw.JobState.RUNNING)
    # terminal has no outgoing transitions
    gw._transition(job, gw.JobState.FAILED)
    with pytest.raises(HTTPException):
        gw._transition(job, gw.JobState.RUNNING)


def test_approval_12_cancel_cancels_approvals(client, api_key, fake_browser_use):
    """12. Cancelling a job cancels its pending approvals (recovery)."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s12")
    r = _prepare(client, h, job_id)
    aid = r.json()["approval_id"]
    # Cancel the job
    r = client.post(f"/tasks/cancel/{job_id}", json={
        "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 200
    # Approval is now cancelled; decide fails
    r = client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 409


def test_approval_13_approve_resumes_job(client, api_key, fake_browser_use):
    """13. Approving moves a waiting job back to running."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s13")
    job = gw._JOBS[job_id]
    job.state = gw.JobState.RUNNING
    r = _prepare(client, h, job_id)
    assert job.state == gw.JobState.WAITING_APPROVAL
    aid = r.json()["approval_id"]
    r = client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 200
    # Job resumed; worker must revalidate page state before continuing
    assert job.state == gw.JobState.RUNNING


def test_approval_14_secret_params_rejected(client, api_key, fake_browser_use):
    """14. Approval params containing secret-like keys are rejected."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s14")
    r = client.post("/approvals", json={
        "job_id": job_id, "action_type": "otp",
        "action_label": "x", "consequence": "y",
        "params": {"otp_code": "123456"},
        "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 400
    assert "sensitive" in r.json()["detail"].lower()


def test_approval_15_no_secrets_in_logs_or_responses(
    client, api_key, fake_browser_use
):
    """15. Approval responses and job logs never contain param values."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="appr-s15")
    secret_value = "super-secret-value-xyz"
    r = _prepare(client, h, job_id, params={"field": secret_value})
    body = r.json()
    # Response has summary only, never raw params
    assert "params" not in body
    assert secret_value not in str(body)
    # Job log has action type only
    job = gw._JOBS[job_id]
    assert secret_value not in " ".join(job.log)


# ---------------------------------------------------------------------------
# Phase 2 integration tests: orchestrator -> approvals -> execution lifecycle
# ---------------------------------------------------------------------------

def _fresh_approval_service():
    from approvals import ApprovalService
    return ApprovalService()


def test_int_01_orchestrator_prepares_without_executing(fake_browser_use):
    """Agent proposes a protected action: approval prepared, nothing executed."""
    import sys
    sys.path.insert(0, "api")
    from orchestrator import (
        SingleStepOrchestrator, ActionDisposition,
    )
    svc = _fresh_approval_service()
    orch = SingleStepOrchestrator(goal="apply", inputs={})
    result = orch.propose_action(
        action_type="submit",
        params={"form": "passport"},
        approval_service=svc,
        job_id="job-1",
        session_id="sess-1",
        action_label="Submit passport application",
        consequence="Sends the application to the portal.",
        params_summary={"form": "passport"},
    )
    assert result.disposition == ActionDisposition.AWAITS_APPROVAL
    assert result.approval is not None
    assert result.approval.state.value == "pending"
    # The orchestrator itself performed no browser action.
    assert orch.steps == []


def test_int_02_safe_action_executes_now(fake_browser_use):
    """Non-protected actions are not gated."""
    import sys
    sys.path.insert(0, "api")
    from orchestrator import (
        SingleStepOrchestrator, ActionDisposition,
    )
    svc = _fresh_approval_service()
    orch = SingleStepOrchestrator(goal="apply", inputs={})
    result = orch.propose_action(
        action_type="input",
        params={"field": "name"},
        approval_service=svc,
        job_id="job-1",
        session_id="sess-1",
        action_label="Fill name",
        consequence="Types into a field.",
    )
    assert result.disposition == ActionDisposition.EXECUTE_NOW
    assert result.approval is None


def test_int_03_changed_params_invalidate_approval(fake_browser_use):
    """Different params -> different idempotency key -> fresh approval."""
    svc = _fresh_approval_service()
    a1 = svc.prepare(
        job_id="j", session_id="s", action_type="submit",
        action_label="x", consequence="y", params={"amount": "100"},
    )
    a2 = svc.prepare(
        job_id="j", session_id="s", action_type="submit",
        action_label="x", consequence="y", params={"amount": "200"},
    )
    assert a1.approval_id != a2.approval_id
    # Old approval cannot authorize the new params.
    svc.decide(a1.approval_id, "s", True)
    claimed = svc.claim_for_execution(
        a1.approval_id, "s", "j", "submit", {"amount": "200"}
    )
    assert claimed is None  # params mismatch


def test_int_04_execution_lifecycle_claim_then_result(fake_browser_use):
    """approved -> executing -> succeeded, with execution_id binding."""
    svc = _fresh_approval_service()
    a = svc.prepare(
        job_id="j", session_id="s", action_type="payment",
        action_label="x", consequence="y", params={"amount": "50"},
    )
    svc.decide(a.approval_id, "s", True)
    claimed = svc.claim_for_execution(
        a.approval_id, "s", "j", "payment", {"amount": "50"}
    )
    assert claimed is not None
    assert claimed.execution_state.value == "executing"
    assert claimed.execution_id
    # Wrong execution_id cannot record.
    bad = svc.record_execution_result(
        a.approval_id, "s", "wrong-id", True
    )
    assert bad is None
    # Correct execution_id records.
    done = svc.record_execution_result(
        a.approval_id, "s", claimed.execution_id, True,
        evidence="payment verified on page",
    )
    assert done.execution_state.value == "succeeded"
    # Double-record denied.
    again = svc.record_execution_result(
        a.approval_id, "s", claimed.execution_id, True
    )
    assert again is None


def test_int_05_crash_after_dispatch_marked_unknown(fake_browser_use):
    """Abandoned EXECUTING claims become UNKNOWN, never auto-retried."""
    svc = _fresh_approval_service()
    a = svc.prepare(
        job_id="j", session_id="s", action_type="submit",
        action_label="x", consequence="y", params={},
    )
    svc.decide(a.approval_id, "s", True)
    claimed = svc.claim_for_execution(a.approval_id, "s", "j", "submit", {})
    assert claimed is not None
    # Simulate crash: execution started long ago, no result recorded.
    claimed.execution_started_at = 0
    abandoned = svc.reconcile_abandoned(max_age_s=60)
    assert len(abandoned) == 1
    assert abandoned[0].execution_state.value == "unknown"
    # UNKNOWN cannot be re-claimed or re-executed.
    retry = svc.claim_for_execution(a.approval_id, "s", "j", "submit", {})
    assert retry is None


def test_int_06_crash_before_dispatch_recoverable(fake_browser_use):
    """Approved but never claimed: still executable after restart."""
    svc = _fresh_approval_service()
    a = svc.prepare(
        job_id="j", session_id="s", action_type="submit",
        action_label="x", consequence="y", params={},
    )
    svc.decide(a.approval_id, "s", True)
    # "Restart": create a new service instance sharing the same dict
    # (simulates process restart with durable storage).
    svc2 = _fresh_approval_service()
    svc2._approvals = svc._approvals
    svc2._by_idempotency = svc._by_idempotency
    claimed = svc2.claim_for_execution(a.approval_id, "s", "j", "submit", {})
    assert claimed is not None
    assert claimed.execution_state.value == "executing"


def test_int_07_gateway_execute_returns_execution_id(
    client, api_key, fake_browser_use
):
    """POST /execute returns execution_id; POST /result records outcome."""
    import gateway as gw
    gw._approval_service._approvals.clear()
    gw._approval_service._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="int-s7")
    r = _prepare(client, h, job_id)
    aid = r.json()["approval_id"]
    client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    r = client.post(f"/approvals/{aid}/execute", json={
        "job_id": job_id, "action_type": "submit",
        "params": {"form": "passport"},
        "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["execution_id"]
    assert body["execution_state"] == "executing"
    # Report the verified result.
    r = client.post(f"/approvals/{aid}/result", json={
        "execution_id": body["execution_id"],
        "succeeded": True,
        "evidence": "submit button confirmed on page",
        "session_id": h["X-Ethio-Session"],
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["execution_state"] == "succeeded"


def test_int_08_reconcile_endpoint(client, api_key, fake_browser_use):
    """/approvals/reconcile surfaces abandoned executions for review."""
    import gateway as gw
    svc = gw._approval_service
    svc._approvals.clear()
    svc._by_idempotency.clear()
    job_id, h = _make_job_for_approval(client, api_key, session="int-s8")
    r = _prepare(client, h, job_id)
    aid = r.json()["approval_id"]
    client.post(f"/approvals/{aid}/decide", json={
        "approve": True, "session_id": h["X-Ethio-Session"],
    }, headers=h)
    r = client.post(f"/approvals/{aid}/execute", json={
        "job_id": job_id, "action_type": "submit",
        "params": {"form": "passport"},
        "session_id": h["X-Ethio-Session"],
    }, headers=h)
    # Force the claim to look abandoned.
    svc._approvals[aid].execution_started_at = 0
    r = client.post("/approvals/reconcile", headers=h)
    assert r.status_code == 200
    rec = r.json()["reconciled"]
    assert len(rec) == 1
    assert rec[0]["execution_state"] == "unknown"
    assert rec[0]["approval_id"] == aid


class _FakeTransport:
    """In-memory fake for the Supabase REST API."""

    def __init__(self):
        self.rows = []
        self.calls = []

    def _match(self, params):
        out = list(self.rows)
        for k, v in (params or {}).items():
            if k in ("select", "order"):
                continue
            if v.startswith("eq."):
                out = [r for r in out if str(r.get(k)) == v[3:]]
        return out

    def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, params))
        return _FakeResp(200, self._match(params))

    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, json))
        if "/rpc/" in url:
            return self._rpc(url.rsplit("/", 1)[-1], json)
        # Enforce unique (job_id, params_hash).
        for r in self.rows:
            if (r["job_id"] == json["job_id"]
                    and r["params_hash"] == json["params_hash"]):
                return _FakeResp(409, {"error": "duplicate"})
        self.rows.append(dict(json))
        return _FakeResp(201, [dict(json)])

    def _rpc(self, fn, body):
        """Emulate the migration-004 Postgres functions on the fake rows.

        Mirrors the SQL semantics (verified for real in
        test_postgres.py): claim validates + flips state; record honors
        execution_id; reconcile marks stale 'executing' as 'unknown'.
        """
        import time as _time

        if fn == "claim_approval_for_execution":
            for r in self.rows:
                if r["approval_id"] != body["p_approval_id"]:
                    continue
                if r["session_id"] != body["p_session_id"]:
                    return _FakeResp(200, [])
                if r["job_id"] != body["p_job_id"]:
                    return _FakeResp(200, [])
                if r["state"] != "approved" or r.get("consumed"):
                    return _FakeResp(200, [])
                if r.get("execution_state", "not_started") != "not_started":
                    return _FakeResp(200, [])
                if r["params_hash"] != body["p_params_hash"]:
                    return _FakeResp(200, [])
                r["consumed"] = True
                r["execution_state"] = "executing"
                r["execution_id"] = body["p_execution_id"]
                from persistence import _ts
                r["execution_started_at"] = _ts(_time.time())
                return _FakeResp(200, [dict(r)])
            return _FakeResp(200, [])
        if fn == "record_approval_execution_result":
            for r in self.rows:
                if r["approval_id"] != body["p_approval_id"]:
                    continue
                if r.get("execution_state") != "executing":
                    return _FakeResp(200, [])
                if r.get("execution_id") != body["p_execution_id"]:
                    return _FakeResp(200, [])
                r["execution_state"] = (
                    "succeeded" if body["p_succeeded"] else "failed"
                )
                return _FakeResp(200, [dict(r)])
            return _FakeResp(200, [])
        if fn == "reconcile_abandoned_approvals":
            from datetime import datetime
            now = _time.time()
            out = []
            for r in self.rows:
                if r.get("execution_state") != "executing":
                    continue
                started = r.get("execution_started_at")
                if started:
                    age = now - datetime.fromisoformat(started).timestamp()
                    if age > body["p_max_age_seconds"]:
                        r["execution_state"] = "unknown"
                        out.append(dict(r))
            return _FakeResp(200, out)
        return _FakeResp(404, {"error": f"unknown rpc {fn}"})

    def patch(self, url, headers=None, params=None, json=None):
        self.calls.append(("PATCH", url, params))
        matched = self._match(params)
        for r in matched:
            r.update(json)
        return _FakeResp(200, matched)


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def test_int_09_supabase_store_roundtrip(fake_browser_use):
    """SupabaseApprovalStore works against a fake transport."""
    import sys
    sys.path.insert(0, "api")
    from persistence import SupabaseApprovalStore
    from approvals import Approval, ApprovalState
    import time as _time

    t = _FakeTransport()
    store = SupabaseApprovalStore(
        "https://example.supabase.co", "service-key", transport=t
    )
    # Gateway calling convention (Phase 5): kwargs, same as
    # ApprovalService.prepare. The store mints the approval id.
    stored = store.prepare(
        job_id="j1", session_id="s1", action_type="submit",
        action_label="Submit", consequence="Sends it.",
        params={"x": "1"}, params_summary={},
    )
    aid = stored.approval_id
    assert aid
    fetched = store.get(aid, "s1")
    assert fetched is not None
    assert fetched.action_type == "submit"
    # Cross-user: not found.
    assert store.get(aid, "other") is None
    # Decide + claim + result.
    decided = store.decide(aid, "s1", True)
    assert decided.state == ApprovalState.APPROVED
    claimed = store.claim_for_execution(aid, "s1", "j1", "submit", {})
    # params {} hash differs from the prepared {"x": "1"} hash, so the
    # claim is refused — param binding is enforced.
    assert claimed is None


def test_int_10_supabase_store_idempotent_prepare(fake_browser_use):
    """Duplicate prepare returns existing row (409 -> fetch)."""
    import sys
    sys.path.insert(0, "api")
    from persistence import SupabaseApprovalStore
    from approvals import Approval
    import time as _time

    t = _FakeTransport()
    store = SupabaseApprovalStore(
        "https://example.supabase.co", "service-key", transport=t
    )
    def mk():
        return store.prepare(
            job_id="j9", session_id="s9", action_type="payment",
            action_label="Pay", consequence="Charges.",
            params={"amount": "200"}, params_summary={},
        )

    first = mk()
    # Second prepare with same job+params triggers the 409 path.
    second = mk()
    assert second.approval_id == first.approval_id
    assert len(t.rows) == 1  # no duplicate row


# ---------------------------------------------------------------------------
# SQL contract tests for migration 004 (no live Postgres in this env)
# ---------------------------------------------------------------------------

def _read_migration_004():
    import os
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "mobile", "backend", "migrations", "004_approvals.sql",
    )
    with open(path) as f:
        return f.read()


def test_sql_01_claim_uses_row_locking(fake_browser_use):
    """The atomic claim must use SELECT ... FOR UPDATE."""
    sql = _read_migration_004()
    assert "claim_approval_for_execution" in sql
    assert "for update" in sql.lower()
    # All validity conditions present in the claim.
    for cond in ("approved", "expires_at", "consumed", "not_started",
                 "params_hash", "session_id", "job_id"):
        assert cond in sql, cond


def test_sql_02_execution_columns_and_states(fake_browser_use):
    """approvals table carries the full execution lifecycle."""
    sql = _read_migration_004().lower()
    for col in ("execution_state", "execution_id", "execution_started_at",
                "execution_ended_at", "execution_evidence"):
        assert col in sql, col
    for state in ("not_started", "executing", "succeeded", "failed",
                  "unknown"):
        assert f"'{state}'" in sql, state


def test_sql_03_reconcile_marks_unknown(fake_browser_use):
    """Reconciliation marks stale executing claims as unknown."""
    sql = _read_migration_004().lower()
    assert "reconcile_abandoned_approvals" in sql
    assert "execution_state = 'unknown'" in sql
    assert "execution_state = 'executing'" in sql


def test_sql_04_rls_and_uniqueness(fake_browser_use):
    """RLS owner policies and idempotency uniqueness are defined."""
    sql = _read_migration_004().lower()
    assert "enable row level security" in sql
    assert "auth.uid() = owner_id" in sql
    assert "unique (job_id, params_hash)" in sql
