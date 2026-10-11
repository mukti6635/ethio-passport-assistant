# ETHIO — Your Ethiopian Government Assistant

A premium, mobile-first Flutter prototype of an AI assistant that guides
Ethiopian citizens through government-service tasks (passport, visa, driver's
license, certificates, business services).

> **Prototype.** Demo data only. ETHIO is an independent assistant and is **not
> affiliated with any government agency**. Nothing in this app is submitted to
> any government system, no real identity documents are stored, and no fake
> government integrations are built.

## What's inside

- **Home** — ETHIO brand mark, "What do you need help with?", six service
  cards, free-text box + Start button, language row (English now; Amharic and
  Afaan Oromo registered as "coming soon").
- **Generic intake flow** — one question per screen, rendered from the service
  catalog. No passport-specific (or any service-specific) workflow is hard-coded
  into the architecture.
- **Task pipeline** — overview + progress → requirements checklist → document
  upload (simulated samples with preview & removal) → extracted-info review
  with user correction → missing/conflicting-data resolution → AI activity
  timeline → human approvals (OTP, CAPTCHA, payment, final legal review) →
  appointment booking → history with resume.
- **Data-driven catalog** (`lib/data/service_catalog.dart`) — add a service by
  adding one `ServiceDefinition`. Screens, approvals and AI steps render from it.
- **Localization-ready** (`lib/l10n/strings.dart`) — English ships; `am`/`om`
  maps fall back per key. Add translations, no code changes needed.
- **Browser automation stub** (`lib/integrations/browser_use_client.dart`) —
  interface + simulator for a future Browser Use WebUI backend. Swap
  `BrowserUseClient.instance` when the backend is connected.

## Run it

Prerequisites: [Flutter SDK](https://docs.flutter.dev/get-started/install)
(stable channel).

```bash
cd ethio
flutter pub get

# Android (device or emulator)
flutter run

# Web preview (same code, runs in a browser)
flutter run -d chrome

# Analyze
flutter analyze
```

## Project structure

```
lib/
  main.dart            # entry point
  app.dart             # MaterialApp, tabs, localization setup
  routes.dart          # named-route table
  theme/ethio_theme.dart
  l10n/strings.dart    # English strings + am/om fallback architecture
  models/              # service.dart, task.dart
  data/service_catalog.dart   # all services, questions, requirements
  state/task_store.dart       # in-memory store (ChangeNotifier)
  integrations/browser_use_client.dart  # future automation backend stub
  widgets/             # reusable components
  screens/             # one file per screen
```

## Sync to GitHub

```bash
cd ethio
git init
git add .
git commit -m "ETHIO prototype: Flutter government-services assistant"
git branch -M main
git remote add origin https://github.com/<your-username>/ethio.git
git push -u origin main
```

(Or create the repo first on github.com/new, then add the remote it shows you.)
