# ETHIO — Baseline (Stage 1)

Recorded: 2026-10-11 ~19:40 UTC. This is the starting point for the master build.
Nothing here was modified to produce this baseline.

## Repository state

- Location: `~/workspace/ethio/`
- Not a git repository (no history; user was given zip export + GitHub instructions separately).
- 28 Dart files, ~5,318 LOC (`lib/` + `test/`).
- Flutter stable (SDK at `~/sdks/flutter`, installed 2026-10-11).
- Platforms scaffolded: `android/`, `web/`.

## Verification results (executed now)

- `flutter analyze`: **No issues found.**
- `flutter test`: **All tests passed** (1 test: `test/app_smoke_test.dart`
  — full passport task flow end to end: home → intake → overview →
  requirements → upload → review → issues → AI activity → approvals
  (OTP/payment/legal) → appointments → home).

## What exists and works

- Home screen: ETHIO branding, 6 service cards, free-text + Start, language row.
- Generic intake flow (one question/screen, driven by `service_catalog.dart`).
- Task pipeline: overview/progress → requirements → upload (simulated samples,
  preview, removal) → extracted-info review/edit → missing/conflict resolution
  → AI activity (simulated timeline) → approvals hub → OTP (6-box) →
  CAPTCHA (tap tiles) → payment (Telebirr/Chapa/card, simulated) → final legal
  review (Submit disabled in prototype) → appointments → history/resume.
- Data-driven architecture: `ServiceDefinition` catalog; no service-specific
  screens; `TaskStore` (in-memory ChangeNotifier) as single source of truth.
- Localization: English complete; `am`/`om` registered with per-key fallback.
- Browser Use stub: `lib/integrations/browser_use_client.dart` (interface +
  simulator, no real automation).

## Known limitations (to address in later stages)

1. No backend: all state is in-memory; no auth, no persistence, no RLS.
2. No real document processing: uploads are simulated samples; no OCR.
3. No real browser automation: stub only; no actual WebUI inspected yet.
4. Checkpoints are UI-level only; no server-side enforcement exists.
5. English only; `am`/`om` maps are empty.
6. No mock portal for safe end-to-end testing.
7. Release APK could not be built in this sandbox (Gradle daemon's localhost
   TCP is blocked by platform policy); web build compiles fine.
8. Privacy explanations before sensitive actions are minimal.

## Stage plan

See `MASTER_BUILD_PLAN.md` (to be written) — Stages 2–9 build on this baseline
without breaking it: `flutter analyze` and `flutter test` must stay green
throughout.
