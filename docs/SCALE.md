# ETHIO — Scale Design (3,000 applicants/day target)

> **Status: design only.** Do not claim 3,000/day is supported until load
> tests demonstrate it. All numbers below are estimates to be validated
> once the live agent test (Phase 3) provides real task durations.

## Demand model

| Metric | Estimate | Notes |
|---|---|---|
| Daily applicants | 3,000 | target to validate |
| Active window | ~12h (8am–8pm EAT) | applicants are humans, not uniform |
| Avg arrival (active) | ~4.2/min | 3,000 ÷ 720 min |
| Peak burst | ~12–15/min | 3× average during busy periods |
| Avg agent task | 2–10 min | **unknown until live test measures it** |
| Human checkpoint wait | minutes–hours | OTP/payment/legal; agent is paused, browser held or released |

**Concurrency estimate:** at 4.2 arrivals/min × 5 min avg task = **~21 concurrent
browsers** sustained, **50–100** at peak burst. Each headless Chromium uses
~200–400 MB RAM → 10–40 GB for browsers alone at peak.

## Architecture for scale

```
mobile/ ──HTTPS──▶ API (FastAPI, stateless, horizontal)
                        │ enqueue
                        ▼
              Durable queue (Redis + RQ, or Postgres SKIP LOCKED)
                        │ dequeue
                        ▼
              Workers (N processes × M browsers each)
                 │            │
            browser-use   Supabase (state, evidence, audit)
            Agent         (RLS, private storage)
```

### Why the current design doesn't scale yet

- `_JOBS` is an in-memory dict: a restart loses all jobs; multiple API
  workers can't share state.
- `asyncio.create_task` runs agents in-process: one slow/hung agent can
  starve the event loop; no backpressure.
- No per-user concurrency limit: one user could spawn unbounded browsers.
- No browser pool: each job launches a fresh Chromium (slow, memory-heavy).

### Required changes (in order)

1. **Persist jobs in Supabase** (tables already exist in
   `mobile/backend/migrations/`): `browser_sessions` + a new `jobs` table
   with state, timestamps, and a `locked_by`/`locked_at` for worker claims.
2. **Durable queue**: Redis + RQ (simplest) or Postgres `FOR UPDATE SKIP
   LOCKED`. Job payload: `{job_id, goal, inputs, session_id}` — never
   credentials or document bytes.
3. **Worker processes**: separate from the API. Each worker:
   - claims one job (atomic),
   - launches **one** browser-use Agent with **one** browser,
   - heartbeats progress to Supabase,
   - releases the claim on completion/failure (with retry + backoff).
4. **Concurrency limits**:
   - Global: `MAX_CONCURRENT_BROWSERS` (env, e.g. 20 per worker host).
   - Per session: 1 active browser task (a second `POST /tasks` while one
     runs returns 409 with the existing `job_id`).
5. **Browser lifecycle**: reuse via persistent contexts where safe; hard
   kill + cleanup on timeout/cancel; `finally: await browser.close()`
   (already in gateway — keep it).
6. **Idempotency**: natural keys on job creation (`Idempotency-Key` header
   → return existing `job_id`); retries never re-trigger payment/legal
   checkpoints (those remain human-gated).
7. **Rate limiting**: per-IP and per-session token bucket on `POST /tasks`
   (e.g. 5/min/IP, 1 concurrent/session).

### What NOT to parallelize

- Never run parallel browser actions inside one applicant's session:
  two agents driving one application can corrupt form state or double-submit.
- Checkpoints (OTP/CAPTCHA/payment/legal) stay strictly human-gated at any
  scale — speed never overrides them.

## Load test plan (synthetic only, mock portal)

1. Seed N synthetic sessions against `mobile/mock-portal`.
2. Ramp: 1 → 5 → 20 → 50 concurrent jobs.
3. Measure: throughput (tasks/min), p50/p95/p99 task duration, queue wait,
   error rate, browser crashes, peak RSS per worker, $/task (tokens × price).
4. Soak: sustain peak for 30 min; watch for memory leaks and zombie browsers.
5. Report the maximum **sustained** throughput and the bottleneck found.

## Cost sketch (to validate with real measurements)

- `gemini-3.8-flash`: ~$0.75–$1.50 / 1M input tokens (intro pricing through
  2026-12-31).
- If a task uses ~50k tokens: ~$0.04–$0.08/task → 3,000/day ≈ **$120–$240/day**.
- Browser compute (Hetzner/DO): ~$50–$200/mo per worker host.
- **Measure first**: token usage per task is currently unknown.

## Remaining blockers for scale validation

- Live agent test must pass (Phase 3) to get real task durations.
- Redis/Postgres queue + worker supervisor not yet implemented.
- Supabase project not yet created (user action).
