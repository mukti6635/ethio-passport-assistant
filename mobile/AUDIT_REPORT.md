# ETHIO Flutter App — Audit Report

**Date:** 2026-10-12
**Scope:** Mission 1 (E2E flow) + Mission 6 (launch polish)
**Method:** Static code inspection only. No code modified. Flutter tests not run (no Flutter CLI in this environment).

---

## 1. Screen Journey — COMPLETE ✓

**16 screen widgets** (not 17 as previously reported — actual file count):

| # | Screen | File | Route | Status |
|---|--------|------|-------|--------|
| 1 | Home (service catalog) | `home_screen.dart` | `/` (tab) | ✓ → `/intake`, `/task` |
| 2 | Service intake (multi-step Q&A) | `intake_screen.dart` | `/intake` | ✓ → `/task` |
| 3 | Task overview (progress + next action) | `task_overview_screen.dart` | `/task` | ✓ → dynamic `nextAction` |
| 4 | Requirements checklist | `requirements_screen.dart` | `/requirements` | ✓ → `/upload` |
| 5 | Document upload | `upload_screen.dart` | `/upload` | ✓ → `/review` |
| 6 | Review & confirm | `review_screen.dart` | `/review` | ✓ → `/issues` or `/approvals` |
| 7 | Missing info / conflicts | `missing_info_screen.dart` | `/issues` | ✓ → `/ai` (context) |
| 8 | AI activity (agent timeline) | `ai_activity_screen.dart` | `/ai` | ✓ informational |
| 9 | Approval hub (gated checkpoints) | `approval_hub_screen.dart` | `/approvals` | ✓ → `/otp`, `/captcha`, `/payment`, `/legal` |
| 10 | OTP entry | `otp_screen.dart` | `/otp` | ✓ pops back to hub |
| 11 | CAPTCHA | `captcha_screen.dart` | `/captcha` | ✓ pops back to hub |
| 12 | Payment (simulated) | `payment_screen.dart` | `/payment` | ✓ pops back to hub |
| 13 | Legal review & sign | `legal_screen.dart` | `/legal` | ✓ pops back to hub |
| 14 | Appointments | `appointments_screen.dart` | `/appointments` | ✓ → `/` (complete) |
| 15 | Tasks (active list) | `tasks_screen.dart` | `/` (tab) | ✓ → `/task` |
| 16 | History (completed) | `history_screen.dart` | `/` (tab) | ✓ informational |

**Journey chain verified:**
`/` → `/intake` (home_screen.dart:69) → `/task` (intake_screen.dart:84 via pushReplacementNamed)
→ `/requirements` → `/upload` → `/review` → `/issues` → `/approvals`
→ `/otp`|`/captcha`|`/payment`|`/legal` (each pops back) → `/appointments` → `/`

**No dead ends found.** Every screen has forward navigation or a back path. Checkpoint screens (OTP/CAPTCHA/payment/legal) correctly `pop()` to the approval hub. The approval hub's Continue button is disabled until `allApproved` (approval_hub_screen.dart:58-60).

---

## 2. Gateway Contract — MATCHES ✓ (with one wiring gap)

**File:** `lib/integrations/browser_use_client.dart`

| Gateway endpoint | Client path | Match |
|-----------------|-------------|-------|
| `GET /health` | `healthPath = '/health'` | ✓ |
| `POST /tasks` | `runTaskPath = '/tasks'` | ✓ |
| `GET /tasks/status/{job_id}` | `statusPath = '/tasks/status'` | ✓ |
| `POST /tasks/pause/{job_id}` | `pausePath = '/tasks/pause'` | ✓ |
| `POST /tasks/resume/{job_id}` | `resumePath = '/tasks/resume'` | ✓ |
| `POST /tasks/cancel/{job_id}` | `cancelPath = '/tasks/cancel'` | ✓ |
| `GET /tasks/evidence/{job_id}` | `evidencePath = '/tasks/evidence'` | ✓ |

**Headers:** `Authorization: Bearer $apiKey` (line 367) + `X-Ethio-Session: $sessionId` (line 368) — matches gateway's `require_auth`.

**State vocabulary:** `_parseJobState` (lines 207-227) handles all 8 gateway states (`queued`, `running`, `paused`, `awaiting_human`, `succeeded`, `failed`, `cancelled`, `timed_out`) plus aliases. ✓

**⚠️ CRITICAL GAP — Simulated client still active:**
- Line 18: `static BrowserUseClient instance = SimulatedBrowserUseClient();`
- `HttpBrowserUseClient` (line 98) is **abstract** — the real HTTP implementation is not written.
- The AI activity screen shows a simulated timeline, not real agent events.
- **For Mission 1:** implement `HttpBrowserUseClient` with real HTTP calls and swap the instance. The interface is stable; no UI changes needed.

---

## 3. Localization — 98.6% ✓

**File:** `lib/l10n/strings.dart`

| Locale | Keys | Status |
|--------|------|--------|
| English (`en`) | 220 | ✓ Complete — all 114 keys used in code present |
| Amharic (`am`) | 217 | ✓ 98.6% — missing only `lang_am`, `lang_en`, `lang_om` (language names, fall back to English) |
| Afaan Oromo (`om`) | 0 | Honestly labeled "coming soon" in UI |

Per-key English fallback prevents crashes on missing translations. ✓

---

## 4. Secrets & URLs — CLEAN ✓

- **No hardcoded API keys, secrets, or credentials** in `lib/`.
- `browser_use_client.dart:338`: documents that `apiKey` "MUST come from secure storage at runtime; never a literal."
- URLs in code are documentation examples only (`supabase_adapter.dart:25`, `browser_use_client.dart:87,114`).
- No secrets in test files.

---

## 5. Accessibility — GOOD with gaps

**✓ What's fine:**
- `EthioButton` uses Material `ElevatedButton`/`OutlinedButton` (48px minimum touch target per Material spec).
- Color contrast: primary `#0B6B4F` on bg `#F5F8F6` ≈ 5.8:1 ✓; ink `#122019` on bg ≈ 15:1 ✓; muted `#5C6C64` on bg ≈ 5.2:1 ✓ (all pass WCAG AA 4.5:1).
- Bottom nav uses labeled `NavigationDestination`s.

**⚠️ Gaps:**
- **Zero `Semantics` widgets** in `lib/` — no custom semantic labels for screen readers on custom widgets (cards, progress indicators).
- Two sub-48px touch targets: `cards.dart:110` (46px height), `progress_header.dart:75` (40px height). Minor.
- No `tooltip` on icon-only buttons (though none found without text labels either).

---

## 6. Error Handling — ADEQUATE

- **No empty catch blocks** found.
- Intake uses `_canContinue` to disable Continue until valid input (intake_screen.dart:133) — proper inline validation.
- Approval hub gates Continue on `allApproved`.
- 12/16 screens have no explicit `SnackBar`/error UI, but most use disabled-button patterns or empty states instead. This is acceptable for a prototype but production should add:
  - Network error handling for the future HTTP client
  - Upload failure feedback (upload_screen.dart has no error path)
  - Session expiry handling

---

## Summary: What's Blocking Mission 1

| Priority | Issue | File |
|----------|-------|------|
| **P0** | `HttpBrowserUseClient` not implemented; app uses `SimulatedBrowserUseClient` | `lib/integrations/browser_use_client.dart:18,98` |
| P1 | Amharic missing 3 language-name keys | `lib/l10n/strings.dart` |
| P2 | No `Semantics` for screen readers | `lib/widgets/`, `lib/screens/` |
| P2 | Two sub-48px touch targets | `lib/widgets/cards.dart:110`, `lib/widgets/progress_header.dart:75` |
| P3 | No network error UI (needed when HTTP client lands) | Various |

**The UI journey, contract, localization, and security are solid. The single P0 is wiring the real HTTP client — everything else is polish.**
