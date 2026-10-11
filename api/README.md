# ETHIO browser-use gateway

HTTP bridge between the ETHIO Flutter app and `browser-use`. The official
Browser Use WebUI (`webui.py`) is Gradio-only and exposes no REST API, so
this small FastAPI service drives `browser_use.Agent` directly and exposes
the task lifecycle the Flutter `WebUiHttpAdapter` expects.

## Run

```bash
# from the repository root
pip install -r requirements.txt        # browser-use and friends
pip install -r api/requirements.txt    # fastapi, uvicorn, ...

export GATEWAY_API_KEY="pick-a-long-random-secret"
export OPENAI_API_KEY="your-openai-key"   # the agent's LLM key, server-side

uvicorn api.gateway:app --host 0.0.0.0 --port 8000
```

## Environment variables

| Variable              | Default   | Purpose                                            |
|-----------------------|-----------|----------------------------------------------------|
| `GATEWAY_API_KEY`     | *(none)*  | **Required.** Bearer token the Flutter app sends. If unset the gateway fails closed (HTTP 500 on every authenticated endpoint) — it never runs without auth. |
| `OPENAI_API_KEY`      | *(none)*  | LLM key for the agent. Never sent to clients.      |
| `ETHIO_LLM_MODEL`     | `gpt-4o`  | Model passed to `browser_use.llm.ChatOpenAI`.      |
| `ETHIO_HEADLESS`      | `true`    | Run the browser headless (`false` to watch it).    |
| `ETHIO_MAX_STEPS`     | `50`      | Max agent steps per task.                          |
| `ETHIO_JOB_TIMEOUT_S` | `1200`    | Job timeout in seconds; timed-out jobs are stopped and marked `timed_out`. |

No real values are stored anywhere in this repo. Production should inject
them from a secret manager.

## Endpoint contract

All endpoints except `/health` require:

- `Authorization: Bearer <GATEWAY_API_KEY>`
- `X-Ethio-Session: <opaque per-user/per-task id>` — jobs are namespaced by
  this value; asking for another session's job returns 404.

| Method | Path                    | Body                                              | Returns |
|--------|-------------------------|---------------------------------------------------|---------|
| GET    | `/health`               | —                                                 | `{"ok": true, "version": "1.0.0"}` (no auth) |
| POST   | `/tasks`                | `{"goal": str, "inputs": {str: str}, "session_id": str}` | `{"job_id": str}` (HTTP 202) |
| GET    | `/tasks/status/{id}`    | —                                                 | `{"state": str, "log": [str]}` |
| POST   | `/tasks/pause/{id}`     | `{"checkpoint"?: str, "session_id": str}`          | `{"ok": true}` |
| POST   | `/tasks/resume/{id}`    | `{"session_id": str}`                             | `{"ok": true}` |
| POST   | `/tasks/cancel/{id}`    | `{"session_id": str}`                             | `{"ok": true}` |
| GET    | `/tasks/evidence/{id}`  | —                                                 | `{"final_result": str\|null, "artifacts": [], "extracted": {}}` |

State vocabulary: `queued`, `running`, `paused`, `awaiting_human`,
`succeeded`, `failed`, `cancelled`, `timed_out`. Only terminal states
(`succeeded`, `failed`, `cancelled`, `timed_out`) expose evidence —
`GET /tasks/evidence/{id}` returns 404 before that, so the gateway never
invents an outcome for a running job.

Pausing with a `checkpoint` name (e.g. `"otp"`, `"captcha"`, `"payment"`,
`"legal"`) puts the job in `awaiting_human`: the agent stops and waits
while the human completes the step in the ETHIO app; `resume` continues it.

## Flutter wiring

Configure the app's `WebUiHttpAdapter` (in `mobile/lib/integrations/`)
with:

- `baseUrl` → this gateway, e.g. `http://localhost:8000`
- `healthPath: /health`, `runTaskPath: /tasks`,
  `statusPath: /tasks/status`, `pausePath: /tasks/pause`,
  `resumePath: /tasks/resume`, `cancelPath: /tasks/cancel`,
  `evidencePath: /tasks/evidence`
- `apiKey` → the `GATEWAY_API_KEY` value, loaded from secure storage at
  runtime (never hard-coded)

## Tests

```bash
pytest api/test_gateway.py -q
```

The contract tests use FastAPI's `TestClient` with a **mocked**
`browser_use.Agent` — no real browser or LLM key needed. They cover auth
rejection, fail-closed misconfiguration, session isolation, the full
start → pause → resume → cancel lifecycle, checkpoint pauses,
idempotent cancel, evidence gating, timeouts, and agent failures.

## Honest status

- **Not yet live-tested**: this environment has no browser and no LLM key,
  so the gateway has only been exercised against the mocked agent. Before
  pointing it at anything real, run one task against the mock portal with a
  valid `OPENAI_API_KEY` and confirm pause/resume/evidence behave.
- Single-process in-memory job store: don't run multiple uvicorn workers
  against it (use `--workers 1`); a shared store would be needed to scale.
- The gateway enforces *transport-level* checkpoints (pause/resume). The
  legal meaning of each checkpoint (who authorized what, when) is enforced
  by the ETHIO backend's checkpoint records, not here.
