# ETHIO — Build the Android APK on a normal Windows computer

The development sandbox cannot build the APK (its network layer blocks
the local connections Gradle needs). This guide is the reliable path:
build on an ordinary Windows PC, install on your phone, and run the
six-step device test against the live DEVELOPMENT Supabase project and
the mock portal only. Nothing here touches a real government service.

Every version and flag below was verified against the project code on
2026-10-13 (Flutter app in `mobile/`, gateway in `api/`).

You need about 6–8 GB of free disk space and an hour for first-time
downloads. All commands are PowerShell unless noted.

---

## 1. Install JDK 17

The project's Android build uses AGP 9.1.0 + Gradle 9.3.1 (see
`mobile/android/settings.gradle.kts` and
`mobile/android/gradle/wrapper/gradle-wrapper.properties`), which
require **JDK 17**.

1. Download **Temurin JDK 17 (x64, .msi)** from https://adoptium.net
   (choose version 17, Windows, x64, JDK).
2. Run the installer. On the options screen, enable
   **"Set JAVA_HOME variable"** (shown with a red X by default — click
   it and choose "Will be installed on local hard drive").
3. Verify in a NEW PowerShell window:
   ```powershell
   java -version
   ```
   → must say `openjdk version "17...`.

## 2. Install the Android SDK (via Android Studio)

1. Install **Android Studio** from https://developer.android.com/studio
   (default options).
2. Open it once → **More Actions → SDK Manager** (or Settings →
   Languages & Frameworks → Android SDK):
   - **SDK Platforms** tab: check **Android 15.0 (API 35)** — the
     compile level Flutter 3.27 uses for this project.
   - **SDK Tools** tab: check **Android SDK Build-Tools**,
     **Android SDK Command-line Tools (latest)**, and
     **Android SDK Platform-Tools**.
   - Apply → accept the licenses → let downloads finish.
3. You do NOT need an emulator or Android Studio afterwards; it only
   provides the SDK. Note its location (default:
   `C:\Users\<you>\AppData\Local\Android\Sdk`).

## 3. Install Flutter SDK 3.27.4 (the verified version)

This code was built and tested with **Flutter 3.27.4** (the project's
`pubspec.yaml` requires Dart SDK ^3.5.0, which 3.27.4 satisfies).

1. Download `flutter_windows_3.27.4-stable.zip` from
   https://docs.flutter.dev/install/archive (Windows section).
2. Extract to `C:\src\flutter` (avoid `C:\Program Files` — spaces and
   admin permissions cause build failures).
3. Add `C:\src\flutter\bin` to your **user PATH**:
   Settings → search "environment variables" → Environment Variables →
   under *User variables* select `Path` → Edit → New →
   `C:\src\flutter\bin` → OK.
4. In a NEW PowerShell window:
   ```powershell
   flutter --version     # → Flutter 3.27.4
   flutter doctor
   ```
5. Fix what `flutter doctor` flags, typically:
   ```powershell
   flutter doctor --android-licenses   # answer y to each
   ```
   A green check for **Flutter** and **Android toolchain** is enough
   for this build. (Chrome / Visual Studio rows are not needed.)

## 4. Unzip the project and fetch dependencies

1. Extract `ethio-windows-build.zip` to `C:\src\ethio` so the project
   root is `C:\src\ethio` (it contains `mobile\`, `api\`, `docs\`).
2. ```powershell
   cd C:\src\ethio\mobile
   flutter pub get
   ```

## 5. Build the debug APK

Two values are yours to supply:

- `<ANON_KEY>` — the project's **anon / publishable key**: Supabase
  dashboard → project **ethio** → Settings → API → "anon public" /
  publishable key. This key is safe inside the app (row-level security
  protects the data). **Never** use the `service_role` key here.
- `<PC-LAN-IP>` — this computer's Wi-Fi/LAN address (the phone must
  reach the gateway on it): run `ipconfig` and use the IPv4 address,
  e.g. `192.168.1.20`. Phone and PC must be on the same Wi-Fi.

```powershell
cd C:\src\ethio\mobile
flutter build apk --debug `
  --dart-define=ETHIO_SUPABASE_URL=https://zvkkhojqwnsuggeslhga.supabase.co `
  --dart-define=ETHIO_SUPABASE_ANON_KEY=<ANON_KEY> `
  --dart-define=ETHIO_GATEWAY_URL=http://<PC-LAN-IP>:8000 `
  --dart-define=ETHIO_GATEWAY_AUTH_MODE=jwt `
  --dart-define=ETHIO_SESSION_ID=pilot
```

These are ALL the configuration values the app reads (verified:
`lib/backend/supabase_adapter.dart` and `lib/backend/gateway_client.dart`
read exactly these defines; `ETHIO_GATEWAY_CREDENTIAL` exists only for
the development-key mode and is not used here).

**Expected output on success:**
```
C:\src\ethio\mobile\build\app\outputs\flutter-apk\app-debug.apk
```
(The debug build is signed with the debug key automatically and its
manifest allows plain-HTTP calls to your PC on the local network —
that is debug-only; a release build stays HTTPS-only.)

## 6. Run the gateway + mock portal on this PC (needed for the device test)

The phone app talks to the ETHIO gateway; the gateway runs the mock
task against the mock portal. Python **3.12** (the version the backend
was verified with) — install from https://www.python.org if needed,
checking "Add python.exe to PATH".

```powershell
cd C:\src\ethio\api
py -3.12 -m venv C:\src\ethio-gw-venv
C:\src\ethio-gw-venv\Scripts\Activate.ps1
pip install fastapi==0.143.0 uvicorn==0.54.0 pydantic==2.10.6 httpx==0.28.1 requests==2.34.2 playwright==1.63.0 cryptography==50.0.2
playwright install chromium
```
(If PowerShell refuses `Activate.ps1`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.)

> Do NOT `pip install -r ..\requirements.txt` — that root file belongs
> to the upstream browser-use template and pins an old browser-use.
> The pinned list above is what the gateway was actually verified
> with. (The browser-use LLM "agent" runner is not part of the device
> test; the verified "worker" runner below is.)

Create the pilot env file **outside** the project folder, with an
editor (Notepad). It must never be committed, zipped, or shared:

```powershell
notepad C:\src\ethio-pilot.env
```
Contents (replace the one placeholder — the service-role key from the
dashboard → Settings → API → `service_role`; server-side only):
```
GATEWAY_API_KEY=pilot-dev-key
ETHIO_AUTH_MODE=jwt
ETHIO_TASK_STORE=supabase
SUPABASE_URL=https://zvkkhojqwnsuggeslhga.supabase.co
SUPABASE_SERVICE_KEY=<SERVICE_ROLE_KEY>
```

Then start the two servers, each in its own PowerShell window:

Window A — mock portal (from the project root):
```powershell
cd C:\src\ethio
py -3.12 -m http.server 8901 --directory mobile\mock-portal
```

Window B — gateway (it must start **from inside `api\`**):
```powershell
cd C:\src\ethio\api
C:\src\ethio-gw-venv\Scripts\Activate.ps1
Get-Content C:\src\ethio-pilot.env | ForEach-Object {
  if ($_ -match '^\s*([^#=]+)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
  }
}
python -m uvicorn gateway:app --host 0.0.0.0 --port 8000
```
Windows Firewall will ask — allow Python on **Private** networks.

Verify from the PC: open `http://127.0.0.1:8000/health` → `{"ok": true...}`.
Verify from the **phone's browser**: `http://<PC-LAN-IP>:8000/health`
must show the same. If the phone cannot reach it, the app cannot
either — fix Wi-Fi/firewall first.

## 7. Install the APK on your phone

Option A — USB (recommended):
1. On the phone: Settings → About phone → tap **Build number** 7
   times → back → System → Developer options → enable
   **USB debugging**.
2. Connect USB, accept the phone's "Allow USB debugging" prompt.
3. ```powershell
   cd C:\src\ethio\mobile
   flutter install
   ```
   (or `& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r build\app\outputs\flutter-apk\app-debug.apk`)

Option B — file transfer: copy `app-debug.apk` to the phone, open it
in Files, and allow "install unknown apps" for Files when prompted.

## 8. The six-step device test

You will create the mock tasks from the PC (this mirrors exactly how
the pilot was verified automatically). Keep the gateway + portal
windows from §6 running, and the app open on the phone.

**Step 1 — Sign in.** In the app, open the approval hub (any task →
Approvals) → the *Server approvals* section shows a sign-in form.
Sign in as **pilot-a** (`mukti12gpt+pilot-a@gmail.com`, password from
your password manager). → The section now shows "Signed in as …" and
"No pending server approvals."

**Step 2 — A task reaches the hub.** In PowerShell (PC), sign in via
the API and start one mock task — you will be prompted for pilot-a's
password; it is not stored:

```powershell
$pw = Read-Host "pilot-a password" -AsSecureString
$pwText = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
$anon = "<ANON_KEY>"
$auth = Invoke-RestMethod -Method Post `
  -Uri "https://zvkkhojqwnsuggeslhga.supabase.co/auth/v1/token?grant_type=password" `
  -Headers @{ apikey = $anon } -ContentType "application/json" `
  -Body (@{ email = "mukti12gpt+pilot-a@gmail.com"; password = $pwText } | ConvertTo-Json)
$body = @{
  goal = "Prepare my ID renewal (live pilot)"; runner = "worker"; session_id = "pilot"
  inputs = @{ fullName = "Test User"; dob = "1990-01-01"; phone = "0911123456";
              nationalId = "12345678"; serviceType = "idcard"; birthPlace = "Addis Ababa" }
} | ConvertTo-Json -Depth 4
$job = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/tasks" `
  -Headers @{ Authorization = "Bearer $($auth.access_token)" } `
  -ContentType "application/json" -Body $body
$job.job_id
```
Wait ~15 seconds (watch the gateway window: the worker drives the
mock portal in Chromium), then tap **Refresh** in the app's Server
approvals section. → A payment approval card appears ("Pay ETB
200.00 (SIMULATED)").

**Step 3 — Approve → completes.** Tap **Approve** on the card. → The
card shows the server's verified result, and the job finishes. Check
from the PC:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/tasks/status/$($job.job_id)" `
  -Headers @{ Authorization = "Bearer $($auth.access_token)" }
```
→ `state` is `succeeded`.

**Step 4 — Reject → nothing executes.** Repeat Step 2 to create a
second task, wait for the card, tap **Reject**. → Check its status the
same way: `state` is `failed`, and the mock payment never happened
(the gateway window shows no completed payment for that job).

**Step 5 — Sign out.** Tap **Sign out** in the Server approvals
section. → The sign-in form returns and no approvals are visible.

**Step 6 — Session restores.** Sign in again, then fully close the
app (swipe it away) and relaunch it. → Open the approval hub: you are
still signed in (the session is restored from the phone's secure
storage) — no password needed.

Optional seventh check (token rotation): leave the hub open for just
over an hour, create another task (Step 2), and decide it — the
decision must succeed; the app resolves a fresh token when you tap
(this was fixed and unit-tested in Phase 13).

Report the result of each step (pass/fail + anything odd). Any failure
stops the pilot until it is reviewed — do not work around a failed
safety check.

## Troubleshooting

- `flutter doctor` says "cmdline-tools component is missing" → SDK
  Manager (§2) → SDK Tools → Android SDK Command-line Tools.
- "Unable to install" on the phone → uninstall any older ETHIO build
  first (debug signing key differs between PCs).
- App shows a gateway error with the PC's IP → the phone browser test
  in §6 isolates it: Wi-Fi network, firewall, or the gateway window
  was closed.
- Build error mentioning Java/JDK → confirm §1: `java -version` must
  print 17 in the SAME PowerShell window you build from.
