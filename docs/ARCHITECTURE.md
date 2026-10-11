# ETHIO — Architecture

One repository, three runtime components. Each runs separately; each can be
developed, tested, and deployed on its own.

```
ethio-passport-assistant/
├── mobile/          # Flutter app — the user-facing ETHIO assistant
│   ├── lib/         # 17 screens, agent engine, document pipeline,
│   │                #   checkpoint logic, browser-use adapter, l10n (en/am)
│   ├── test/        # 57 widget/unit tests
│   ├── backend/     # Supabase schema + RLS migrations, repository interfaces
│   └── mock-portal/ # self-contained fake portal for safe testing
├── api/             # FastAPI gateway — REST API the mobile app talks to
│   ├── gateway.py   # job lifecycle: start/poll/pause/resume/cancel/evidence
│   └── test_gateway.py
├── src/, webui.py   # Browser Use WebUI (preserved, Gradio) — human-supervised
│                    #   browser automation and debugging
└── docs/            # architecture, deployment, WebUI reference
```

## How the pieces connect

```
┌──────────────┐   HTTPS + Bearer token    ┌──────────────────┐
│  mobile/     │ ────────────────────────▶ │  api/gateway.py  │
│  (Flutter)   │   X-Ethio-Session header  │  (FastAPI)       │
└──────────────┘                           └────────┬─────────┘
                                                   │ drives
                                          ┌────────▼─────────┐
                                          │  browser-use     │
                                          │  Agent (0.1.48)  │
                                          └──────────────────┘
```

- The Flutter app **never talks to the WebUI directly** and never holds the
  LLM key or the gateway's API key in source — keys live in secure storage /
  server env.
- The gateway authenticates every request (`Authorization: Bearer
  $GATEWAY_API_KEY`) and isolates jobs per `X-Ethio-Session` value: one
  user's jobs are invisible to another's.
- The Gradio WebUI (`webui.py`) is preserved for human-supervised runs and
  debugging; it is **not** on the mobile app's request path.
- Human checkpoints (OTP, CAPTCHA, payment, legal, appointment) are enforced
  in the mobile app's agent engine **and** recorded server-side; the gateway
  pauses the browser job (`awaiting_human`) until the user completes the step
  in the app.

## Job lifecycle (gateway)

`queued → running ⇄ paused → succeeded | failed | cancelled | timed_out`
`running → awaiting_human → running` (checkpoint requested via pause)

## Data boundaries

- Raw OCR output and user-confirmed data are separate types/tables; the agent
  acts only on confirmed data.
- Audit events never contain secrets, codes, or identity numbers.
- Document bytes live in private Supabase Storage, never in the repo.

## What is real vs stub (honest status)

| Piece | Status |
|---|---|
| Flutter UI (17 screens) | Real, 57 tests passing |
| Agent engine + checkpoints | Real, enforced in code, tested |
| Document pipeline | Real validation; OCR is a mock until a provider key is configured |
| Gateway REST API | Real implementation; needs a live run with browser + LLM key to verify |
| WebUI (Gradio) | Preserved upstream code; starts per `docs/WEBUI.md` |
| Supabase backend | Schema + RLS written; needs a project + `mobile/backend/README.md` steps |
| Submission/payment | Simulated and labeled; never claims real-world effects |
