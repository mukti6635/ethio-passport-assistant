# ETHIO — Your Ethiopian Government Assistant

ETHIO helps Ethiopian citizens understand government-service requirements,
organize documents, prepare applications, and navigate official online
portals — with a premium, mobile-first experience built for real conditions:
slow internet, small screens, and Amharic-first users.

> **Independent assistant.** ETHIO is not affiliated with any government
> agency and never imitates an official government website.

## Repository layout

| Path | What it is | How to start |
|---|---|---|
| `mobile/` | Flutter app (Android + web). 17 screens, agent engine, checkpoints, Amharic/English | `cd mobile && flutter pub get && flutter run` |
| `api/` | FastAPI gateway — the REST API the app talks to for browser automation | `cd api && uvicorn gateway:app` (see `api/README.md`) |
| `src/`, `webui.py` | Browser Use WebUI (Gradio), preserved for supervised runs | See `docs/WEBUI.md` |
| `mobile/backend/` | Supabase schema + row-level security migrations | See `mobile/backend/README.md` |
| `mobile/mock-portal/` | Self-contained fake portal for safe end-to-end testing | Open `index.html` in a browser |
| `docs/` | Architecture, deployment, WebUI reference | Start with `docs/ARCHITECTURE.md` |

## Quick start

**Mobile app (no backend needed):**
```bash
cd mobile
flutter pub get
flutter run            # Android device/emulator
flutter run -d chrome  # web preview
```

**Browser-automation backend:**
```bash
cd api
pip install -r requirements.txt
export GATEWAY_API_KEY="$(openssl rand -hex 32)"
export OPENAI_API_KEY="..."        # or your provider key
uvicorn gateway:app --host 0.0.0.0 --port 8000
```
Then point the app's browser adapter at `http://<host>:8000` with the API
key in secure storage. Full contract in `api/README.md`.

## Status

- `flutter analyze` clean, 57 Flutter tests passing, gateway contract tests passing.
- Browser automation, OCR, payments, and submissions are clearly labeled
  simulations until live credentials are configured — the app never claims a
  real-world effect without verified evidence.
- See `docs/ARCHITECTURE.md` for the honest real-vs-stub table.

## Credits

Browser automation is built on [browser-use](https://github.com/browser-use/browser-use)
and its [WebUI](https://github.com/browser-use/web-ui) (MIT), preserved in
`src/`/`webui.py` — see `docs/WEBUI.md` for the original documentation.
