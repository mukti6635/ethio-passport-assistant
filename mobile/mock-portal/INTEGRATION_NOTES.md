# Browser Use WebUI — Integration Notes

Research date: 2026-10-11. Sources: the public `browser-use/web-ui` repository
and community forks, read via GitHub (no endpoints invented — anything not
verified below is marked as such).

## 1. What exists

**Official repo: `browser-use/web-ui`** (github.com/browser-use/web-ui,
~16.6k stars, MIT license).

- It is a **Gradio app**, not an API server. Launched with
  `python webui.py --ip 127.0.0.1 --port 7788`; the UI is served at
  `http://127.0.0.1:7788` (Docker variant also exposes VNC at `:6080` for
  watching the browser).
- The agent run is wired to **Gradio UI events**
  (`src/webui/components/browser_use_agent_tab.py`, `run_agent_task`).
  There is **no documented REST API** for submitting a task, polling status,
  pausing, or cancelling.
- LLM keys (OpenAI, Gemini, Anthropic, DeepSeek, Ollama, …) are configured
  server-side in `.env`. There is **no inbound API key / auth model** for
  programmatic callers — Gradio supports optional password auth at launch,
  but the WebUI does not enable it by default.
- Browser sessions are **persistent and shared**: "keep the browser window
  open between AI tasks". There is no multi-user / multi-session isolation —
  effectively **one agent task at a time per WebUI instance**.

**Gradio protocol note.** Every Gradio app technically exposes internal
`/gradio_api/` endpoints (event submission, queue SSE). These are Gradio's
own machinery, not a stable task API for the WebUI: driving the agent
through them would mean reverse-engineering UI event wiring that changes
between releases. Treat as a last resort, not an integration surface.

**Community fork: `mgh9/browser-use-web-ui`** advertises "simple API to use
on your server as self-hosted: run-task, status, cancel". This is the
closest thing to a REST surface found. **Exact paths, methods, and payload
schemas were NOT verified** from public documentation — verify against the
deployed instance before using. (Unrelated project with a similar name,
`reputable-dev/browser-use-web-ui`, is a separate FastAPI+Vue codebase —
do not confuse the two.)

## 2. What an adapter needs

`lib/integrations/browser_use_client.dart` now contains a
`WebUiHttpAdapter` skeleton implementing the existing `BrowserUseClient`
interface. To make it real, each item below must be supplied from the
**deployed** WebUI instance's own documentation:

1. **Base URL** — where the WebUI (or its API wrapper) is reachable.
2. **Auth scheme + API key** — the official build has none; either put it
   behind an auth gateway / reverse proxy, or use a wrapper build that
   issues keys. The key is loaded from secure storage at runtime
   (`flutter_secure_storage`), never hard-coded, never in chat or client
   source.
3. **Endpoint paths + request/response schemas** for: submit task
   (goal + inputs), poll status (state vocabulary + log/events shape),
   pause, resume, cancel, health check, and evidence/result retrieval.
   The adapter's defaults are loud `<SET-...-PATH>` placeholders.
4. **Concurrency model** — one WebUI instance per concurrent task (Docker
   per task), or a queue in front of a single instance. The adapter sends
   `X-Ethio-Session` (unique per user + task) on every request so a future
   multi-session backend can route correctly.
5. **Human checkpoints** (OTP / CAPTCHA / payment / legal submission): the
   WebUI has **no checkpoint API**. Working pattern: pause the agent, keep
   the persistent browser open, let the human complete the step in the
   ETHIO app (or via the WebUI VNC view), then resume with a follow-up
   task. Checkpoints must additionally be enforced server-side (Stage 7) —
   pausing the agent is cooperation, not enforcement.
6. **Evidence**: the agent's final text result plus whatever artifacts
   (screenshots, extracted fields) the backend exposes. The adapter
   normalizes these into `WebUiEvidence` and **never invents fields** —
   absent data stays null/empty.

## 3. Blocked — needs the user's WebUI details

- [ ] Which build is deployed: official Gradio-only, an API fork/wrapper,
      or a custom gateway in front of it?
- [ ] Base URL of the deployment.
- [ ] Exact endpoint paths + schemas (verify live; do not guess).
- [ ] API key / auth scheme, and how the key is issued/rotated.
- [ ] Concurrency: single shared instance or per-task instances?
- [ ] LLM provider key configured server-side (the WebUI needs its own).

Until these are answered, `BrowserUseClient.instance` stays on the
simulator, and all adapter tests run against a fake transport (no network).

## 4. Safe testing without a backend

- `mock-portal/index.html` — self-contained fake portal exercising dynamic
  labels, conditional requirements, missing-info and conflict states,
  simulated OTP/CAPTCHA/payment, slot picker, final review, fake
  confirmation reference, and a network-failure toggle. See
  `mock-portal/README.md`.
- `test/browser_adapter_test.dart` — adapter state machine
  (start→poll→pause→resume→cancel), timeout handling, session isolation,
  and simulator-honesty checks (the simulator never claims a submission).
