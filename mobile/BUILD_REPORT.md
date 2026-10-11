# ETHIO — Master Build Report

Completed: 2026-10-11 ~20:00 UTC. Built on `BASELINE.md` (all preserved).

## Verification (executed)

- `flutter analyze`: **No issues found.**
- `flutter test`: **57/57 passed** — 1 pre-existing e2e (`app_smoke_test`,
  untouched), 56 new across 5 files.
- `flutter build web --release`: compiles (verified earlier; rerun after
  `flutter build web` if you need a fresh `build/`).

## What was built, by stage

**Stage 1 — Baseline.** Inspected repo (28 files, ~5.3k LOC, no git history),
re-ran analyze + e2e test, recorded `BASELINE.md`.

**Stage 2 — Frontend polish.**
- New `PrivacyNotice` widget (inline acknowledgement, not a blocking dialog)
  on upload, payment, and final legal review screens — plain-language
  explanations that nothing leaves the device and nothing is submitted.
- Fixed a real narrow-screen bug: 6 home service cards overflowed 41–64px
  at 360px width (card line-clamp + grid aspect-ratio fix).
- States audit: empty/loading/error coverage verified on all screens.

**Stage 3 — Backend foundation** (`backend/`).
- `migrations/001_initial_schema.sql`: profiles, tasks, requirements,
  documents (metadata only), extractions (raw OCR), confirmed_fields,
  issues, checkpoints, browser_sessions, audit_events.
- `migrations/002_rls_policies.sql`: row-level security on every table;
  users touch only their own rows; clients can request/cancel checkpoints
  but never authorize them (server-side only); private `documents` bucket.
- `lib/backend/repository.dart`: app-facing interfaces (auth, tasks,
  storage). `lib/backend/supabase_adapter.dart`: Supabase skeleton —
  compiles, throws `UnimplementedError` until configured, refuses to log
  sensitive keys. `backend/README.md`: exact setup steps.

**Stage 4 — Document intelligence** (`lib/pipeline/document_pipeline.dart`).
- Typed validation (PDF/JPG/PNG, 10 MB, magic-byte checks).
- `DocumentExtractor` interface + deterministic `MockOcrExtractor`.
- Hard type separation: `RawExtraction` (untrusted) vs `ConfirmedField`
  (human-verified); `confirmField()` is the only bridge.
- `detectIdentityConflicts()` surfaces conflicts as issues; never
  auto-resolves.

**Stage 5 — Universal agent** (`lib/agent/agent_engine.dart`).
- Deterministic OBSERVE → UNDERSTAND → REASON → ACT → VERIFY planner over
  `TaskStage`; transition table, no service-specific classes.
- **Double-gated checkpoints**: `planNext` won't plan past an unauthorized
  checkpoint; `verifyPlan` independently re-checks and downgrades forged
  plans. Tests prove all 5 checkpoint kinds block without authorization.

**Stage 6 — Browser Use** (`lib/integrations/browser_use_client.dart`,
`mock-portal/`).
- Research: official `browser-use/web-ui` is **Gradio-only, no REST API**
  (see `mock-portal/INTEGRATION_NOTES.md`).
- `WebUiHttpAdapter` skeleton: auth headers, per-user session isolation,
  start/poll/pause/resume/cancel + timeouts + evidence; endpoint paths are
  loud `<SET-...-PATH>` placeholders; not wired as default.
- `mock-portal/index.html`: self-contained fake portal (dynamic labels,
  conditional fields, OTP/CAPTCHA/payment/appointment simulation,
  network-failure toggle) for safe agent testing.

**Stage 7/8 — Tests.** 13 browser-adapter tests (state machine, timeouts,
session isolation, simulator honesty); checkpoint-bypass tests;
pipeline validation/conflict tests; frontend polish tests.

**Stage 9 — Deployment** (`docs/DEPLOYMENT.md`): component separation,
dev/staging/prod, secret handling (never in chat/git), scaling notes,
backup/rollback, pre-pilot checklist.

**Stage 10 — Localization.**
- Amharic: **~98% of UI strings** (220 keys), including the entire service
  catalog (questions, options, requirements, AI steps) now routed through
  `S.t()` via `catalogLabel(S, ...)`. Language switcher on Home toggles
  English ⇄ Amharic live; Afaan Oromo honestly marked "coming soon".
- Backend field names stay language-independent (by design).

## Genuine blockers needing the user

1. **Supabase project**: create at supabase.com, run the two migrations +
   storage bucket SQL, paste Project URL + anon key into the app's local
   config (never chat). Service-role key stays server-side.
2. **Browser Use WebUI**: which build is deployed (official Gradio needs an
   API shim; a fork may have endpoints), base URL, exact endpoint
   paths/schemas, API key scheme, concurrency model, server-side LLM key.
3. **Real OCR provider**: pick + API key when ready (interface is stable;
   mock works until then).
4. **Release APK**: this sandbox blocks Gradle's localhost TCP, so
   `flutter build apk` must run on your machine (one command).

## What was NOT done (honestly)

- No real backend is running; the app still uses its in-memory store.
- No real browser automation is connected (simulator is the default).
- No real OCR, payment, or government submission — all simulated and
  labeled as such, per the original constraints.
- Afaan Oromo translations not started (architecture ready).
- 2,000/day capacity not claimed or tested.
