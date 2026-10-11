# ETHIO Mock Portal

A single self-contained fake portal (`index.html` — no build step, no
dependencies) for safely testing the ETHIO browser agent. It is **not** a
government website, is not affiliated with any government, and submits
nothing anywhere: every "server" call is a `setTimeout` in the page.

## Run it

```bash
cd ~/workspace/ethio/mock-portal
python3 -m http.server 8901
# open http://localhost:8901/
```

It also works opened directly as a file (`file:///.../index.html`).

## What it exercises

| Feature | How to trigger |
|---|---|
| Dynamic labels | Toolbar → **Rename field labels** renames every field (agent must cope) |
| Conditional requirements | Service = Passport → previous passport no. required; ID card → place of birth; Business license → trade name |
| Required / optional | `*` markers; Address / Notes / upload are optional |
| File upload (fake) | Choose any file → chip shows name; file never leaves the browser |
| Missing info | Submit with empty required fields → inline errors + banner |
| Conflict state | National ID starting with **9** → simulated record-mismatch panel (keep / edit) |
| OTP (simulated) | Verification step → Send code → **any 6 digits** accepted; code shown on screen |
| CAPTCHA (simulated) | Single checkbox |
| Payment (simulated) | Telebirr / Chapa / Card → fake 200 ETB charge, fake receipt |
| Appointment slots | Radio list generated for upcoming weekdays |
| Final review + reference | Confirm → fake `MOCK-REF-XXXXXX` confirmation |
| Network failure | Toolbar → **Simulate network failure** → fake server calls fail until toggled off |
| Reset | Toolbar → **Reset portal**, or Start over on the confirmation screen |

## For automation

- Steps: `<section data-step="form|review|checkpoints|appointment|final|done">`
- `document.title` updates per step ("Mock Portal — Step N of 6: …")
- Stable selectors: `data-testid="…"` on all key controls (see the comment
  block at the top of `index.html` for the full list)
- Progress stepper mirrors the current step; every banner is prefixed
  "SIMULATED portal message"
