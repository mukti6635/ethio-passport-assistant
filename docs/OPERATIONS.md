# ETHIO Gateway — Operations Guide

How to run, monitor, back up, and recover the `api/` gateway. Beginner-friendly:
every command is copy-pasteable.

## 1. First-time setup (one machine)

```bash
# Python 3.11+
python3 -m venv .venv && source .venv/bin/activate

# Dependencies: browser-use first (root), then the gateway
pip install -r requirements.txt
pip install -r api/requirements.txt

# Chromium for the agent (headless)
playwright install chromium
# If the download stalls, fetch directly:
# curl -L -o /tmp/chrome.zip https://cdn.playwright.dev/builds/cft/153.0.8010.12/linux64/chrome-linux64.zip
```

## 2. Required environment variables

```bash
# Generate once, keep secret. The Flutter app sends this as
# "Authorization: Bearer <key>". It is DIFFERENT from the Gemini key.
export GATEWAY_API_KEY="$(openssl rand -hex 32)"

# The agent's brain. Get one free at https://aistudio.google.com/apikey
export GEMINI_API_KEY="your-key-here"

# Optional tuning
export ETHIO_LLM_MODEL="gemini-3.8-flash"  # default; change only if needed
export ETHIO_HEADLESS="true"               # "false" to watch the browser
export ETHIO_MAX_STEPS="50"                # max agent steps per task
export ETHIO_JOB_TIMEOUT_S="1200"          # 20 min default
```

**Rules:** keys live in the shell environment (or an untracked `.env` file —
`.gitignore` covers `.env`). Never in git, never in the Flutter app, never in
chat logs. `GATEWAY_API_KEY` ≠ `GEMINI_API_KEY`: one guards your API, the other
pays Google for tokens.

## 3. Running

```bash
# Development (auto-reload off for agent stability)
uvicorn gateway:app --host 127.0.0.1 --port 8000 --workers 1  # run from api/
# NOTE: --workers 1. The job store is in-memory; multiple workers would
# each have their own empty store. See docs/SCALE.md for the multi-worker plan.

# Smoke test
curl http://127.0.0.1:8000/health
# {"ok":true,"version":"1.0.0"}
curl http://127.0.0.1:8000/metrics \
  -H "Authorization: Bearer $GATEWAY_API_KEY" -H "X-Ethio-Session: ops"
```

## 4. Monitoring

- `GET /metrics` (auth required): `counters` (created/succeeded/failed/
  cancelled/timed_out, checkpoints requested), `jobs_by_state`, `jobs_tracked`.
- Logs: `job <id> ended: state=... duration_s=... steps=...` on every terminal
  job. No keys, OTPs, or document contents are ever logged.
- Alert on: rising `jobs_failed`, `jobs_timed_out`, or `jobs_tracked` growing
  without bound (leaked jobs — restart clears the in-memory store).

## 5. Backup & recovery

- **Jobs are in-memory**: a restart or crash loses running jobs. Clients
  should re-`POST /tasks` (idempotency: same `X-Ethio-Session` + goal dedupes
  on the client side until Supabase persistence lands).
- **Config to back up**: the two env vars (in your secret manager, not git).
- **Rollback**: `git log --oneline -- api/` → `git revert <sha>` → restart
  uvicorn. The gateway is stateless apart from the in-memory jobs.

## 6. Costs (validate with real measurements)

- `gemini-3.8-flash`: ~$0.75–$1.50 / 1M input tokens (intro pricing to 2026-12-31).
- At ~50k tokens/task: **~$0.04–$0.08 per task**.
- Set a billing alert in Google Cloud Console on day one.

## 7. What is still a stub (honest list)

- OCR: `MockOcrExtractor` in the Flutter app (labeled).
- Payments / legal submissions: simulated in-app, never executed.
- Job persistence: in-memory (Supabase tables exist in migrations, not wired).
- Durable queue / multi-worker: designed in `docs/SCALE.md`, not implemented.
