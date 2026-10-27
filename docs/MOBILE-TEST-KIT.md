# Mobile Test Kit — SAIV student app on iPhone (mock mode)

Purpose: find phone-specific problems (HTTPS, install, permissions, device key, offline, updates) without needing a backend. Everything here runs in **mock mode**: the app uses its built-in fake API, no backend is involved, and no real student data is used. (The real backend has since been tested from a desktop browser — see `docs/FRONTEND-INTEGRATION-NOTES.md`, section 0 — and only partly from a phone, through temporary tunnels: sign-in, the wrong-password error, the session list and the photo step were seen; check-in submission, history, appeals and the offline error screens were not reported; see section 5.)

> **Documentation only.** Nothing here changes the project's code or config. All builds happen in a **separate copy of the frontend** (`D:\saiv-mobile-test`), served on **port 3100**. Your project's `.next` folder and your dev server on port 3000 are never touched.

## 0. Read first

- **A phone needs HTTPS.** Camera, location, Web Crypto (the device key) and service workers do not work on plain `http://192.168…`. The tunnel in section 1 gives you an HTTPS address.
- **Mock mode facts** (so you know what to expect):
  - Sign in with **any valid-looking email and a password of 8+ characters**, e.g. `test@example.com` / `testtest1`. A shorter password shows "Incorrect email or password."
  - There is **one** fake session: **Lecture 5: Neural Networks — CS6101 — NTU LT1**. It requires a live photo.
  - There are also **three fake past check-ins** (Lecture 3 flagged, Lecture 2 rejected, Lecture 1 approved) so that check-in history and appeals can be tried (optional section 4.8). They belong to other sessions and never block checking in to the one above.
  - Check-in **always succeeds** ("approved", risk 0.15, distance 45 m). Your real location and the photo are **not checked or sent anywhere**.
  - Mock data lives in memory: **reloading the page resets it** (a finished check-in is forgotten).
- **Privacy:** use only fake credentials. When the camera asks for a photo, **point it at a wall or object**, not at a person. The photo stays in the page's memory and is discarded.
- **The tunnel URL is public** (anyone who has the link can open it). It only serves the mock app, but stop the tunnel when you finish.

## 1. Setup (PowerShell, on your PC)

> **If `npm` is blocked:** in Windows PowerShell a bare `npm` can fail with "running scripts is disabled on this system". Type **`npm.cmd`** instead, with the same arguments (for example `npm.cmd run build` and `npm.cmd run start -- -p 3100`). This works without changing anything on the PC. **Do not change PowerShell's execution policy** for this test.

**1.1 Install the tunnel tool once** (Cloudflare "quick tunnel": no account needed):
```powershell
winget install --id Cloudflare.cloudflared
```
Close and reopen PowerShell afterwards. If `cloudflared --version` already prints a version number, it is installed and you can skip this step. *(Not tested here — I did not install it. Fallback: ngrok, which needs a free account.)*

**1.2 Copy the frontend to a separate folder.** The **source goes first, the destination second**. `/MIR` makes the destination match the source and deletes anything extra *in the destination*, so never swap the two. `/XD .next` skips your existing build folder.
```powershell
robocopy D:\sc3099-group36\module1-frontend D:\saiv-mobile-test /MIR /XD .next /NFL /NDL /NJH /NJS /NP
```
Exit codes 0–7 mean success (1 = files copied). This takes a few minutes because `node_modules` is copied.

**1.3 Remove the copy's env file** so nothing can override the settings below (this deletes only the copy's file):
```powershell
Remove-Item D:\saiv-mobile-test\.env.local -ErrorAction SilentlyContinue
```

**1.4 Build the copy in mock mode.** The API URL is set to a dead address on purpose, so even by mistake the app cannot reach a real backend.
```powershell
cd D:\saiv-mobile-test
$env:NEXT_PUBLIC_USE_MOCKS = 'true'
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:9'
npm run build
```
The build must finish without errors (it shows a route table ending in "○ (Static)").

**1.5 Start the copy on port 3100** (leave this window open):
```powershell
npm run start -- -p 3100
```

**1.6 In a second PowerShell window, start the tunnel** (leave it open):
```powershell
cloudflared tunnel --url http://localhost:3100
```
It prints an address like `https://something-random.trycloudflare.com`. **Do not restart the tunnel during testing** — a new run gives a new address, which the phone treats as a brand-new app with separate storage.

## 2. Prove mock mode is on — do this on the PC, before the phone

Open the tunnel address (or `http://localhost:3100`) in desktop Chrome with DevTools open (F12 → **Network** tab, tick *Preserve log*).

| ID | Do | Expected | If it fails |
|---|---|---|---|
| A1 | Sign in with `test@example.com` / `testtest1`. | You reach "Select a Session", with three tabs under the header (**Check in**, **My check-ins**, **Face enrollment**), and see exactly **one** session: *Lecture 5: Neural Networks · CS6101 · NTU LT1*, marked **Open now**. This can only happen in mock mode: no backend is running and the API address is a dead one. | **Stop. Do not open the phone.** Report: what the screen shows (e.g. "Unable to reach the server" means mock mode is OFF — redo 1.4 in a fresh window so the two `$env:` lines apply). |
| A2 | While doing A1 and starting a check-in, watch the Network tab. | **No requests** to any address except the app's own host (only page, script, image and manifest files). | Report a screenshot of the Network tab. |
| A3 | Sign out, enter password `short`, sign in. | "Incorrect email or password." (the mock's 8-character rule). | Report the message you saw. |
| A4 | DevTools → **Application** → *Service Workers* and *Cache Storage*. | Worker status **activated**; cache **`saiv-shell-v1`** exists. | Report a screenshot. |

Strongest extra proof (optional): in DevTools → Network set *Offline*, sign out and sign in again — it still works, because the mock needs no network.

## 3. How to report a failure

For any failing test, send me: **test ID**, **iPhone model + iOS version**, **where it ran** (Safari tab or the Home Screen app), **what you expected vs. what happened** (copy the exact on-screen text), and **a screenshot**. If you have a Mac, Safari → Develop → *your iPhone* → Web Inspector gives console errors — attach them if so. Say whether it is repeatable.

## 4. Phone checklist

Use iOS 16 or newer if you can. Tests marked ⚠ cannot be fully validated in mock mode — see section 5.

### 4.1 Safari access and Add to Home Screen

| ID | Do | Expected | Report with |
|---|---|---|---|
| B1 | In **Safari**, open the tunnel address. | Sign-in page loads, **styled** (not plain text), padlock shown, no certificate warning. First load can be slow. | Screenshot; any warning text. |
| B2 | Share button → **Add to Home Screen** → Add. | The option exists; an icon named "SAIV" appears: a **blue square with a white check mark** (placeholder icon). | Screenshot of the Share sheet and home screen. |

### 4.2 Standalone launch and layout

| ID | Do | Expected | Report with |
|---|---|---|---|
| C1 | Open the app from the **home-screen icon**. | Opens full screen with **no Safari address bar**. | Screenshot. |
| C2 | Look at the first screen. | The sign-in screen. **Expected on iOS:** the installed app has its **own storage**, separate from Safari, so you are signed out even if you signed in inside Safari. *(If you are already signed in, tell me — that would be surprising.)* | What you see. |
| C3 | Sign in (`test@example.com` / `testtest1`), go through every screen in portrait. | No sideways scrolling; text readable; buttons easy to tap; nothing hidden behind the notch or home bar; the camera preview fits the screen. | Screenshot of any cut-off or overlapping area. |
| C4 | Rotate to landscape, then back. | Still usable (iOS ignores the portrait lock); no broken layout. | Screenshot. |

### 4.3 Camera and location permissions

| ID | Do | Expected | Report with |
|---|---|---|---|
| D1 | Select the session → **Start check-in** → **Allow & Continue**. | iOS asks for the **camera**, then for **location**. Tap Allow on both → you reach the photo step. | Which prompts appeared, in what order. |
| D2 | On the **Live photo** screen tap **Start Camera**, then **Capture** (point at a wall). | One card only (no separate "Take Photo" or "Liveness" box). A live **front-camera preview appears inside the page** (it does not jump to a separate full-screen video) with an oval face guide, the button changes to **Capture** and is never left looking pressed, and capturing moves straight to the review screen. **Retake photo** there returns to the camera. | Screenshot; any error text. |
| D3 | Run the flow again but tap **Don't Allow** for the camera. | Message **"Camera permission was denied."** with a **Try Again** button. After allowing the camera in iOS Settings, Try Again works. | The exact message, and exactly what you had to change in Settings to recover. |
| D4 | Run again, allow camera but **deny location**. | A **"Location access failed"** message with a way to retry. | Exact message; what recovered it. |
| D5 | Fully close the app and reopen it; start a check-in again. | Note whether iOS asks for permissions **again** (it may). Not a failure — just report it. | Which prompts re-appeared. |

### 4.4 Device key persistence and device registration ⚠

On the phone you cannot inspect the stored key, so persistence is judged from the wording on the check-in preflight screen.

| ID | Do | Expected | Report with |
|---|---|---|---|
| E1 | First time in the installed app: select session → preflight screen (before "Start check-in"). | The "Device:" line shows "Checking…" then **"This device is registered."** | The exact line shown. |
| E2 | Swipe the app away completely, reopen, sign in, select the session again. | The line now says **"This device was registered earlier on this browser."** This proves the key and its marker survived. | If it says "This device is registered." again, the key/storage did **not** persist — report that and how long since the first run. |
| E3 | Optional: open the same address in a **Safari tab** and repeat E1. | Treated as a *different* device: "This device is registered." again (Safari and the installed app have separate storage). | What you see. |

⚠ Mock mode only proves the **key is created and remembered**. It does **not** test the real server's registration rules (duplicates, public-key checks).

### 4.5 Mock check-in flow ⚠

| ID | Do | Expected | Report with |
|---|---|---|---|
| F1 | Start check-in → consent → photo (a wall) → **Review & Submit** → **Submit check-in**. | Shows **"You're checked in"**, risk score **0.15**, distance **45 m**, "Live photo check: Passed". Works wherever you physically are. | Screenshot; the first wrong step. |
| F2 | On the review screen, **double-tap Submit** quickly (use a fresh check-in after a reload). | One result only; the button shows "Submitting…" and cannot be pressed twice. | What happened. |
| F3 | After **Done**, look at the session list **without reloading the page**, then select the session. | The session card now shows **"Checked in · Approved"** and the button reads **View check-in**. Tapping it shows **"You've already checked in to this session."** straight away: no preflight, no permission prompts, no second photo. | Screenshot. |
| F4 | Reload the app, then check in again. | Works again (mock memory was reset). Not a failure. | — |

⚠ Not testable in mock mode: flagged/rejected results, real distance and risk, real liveness/face match, consent saved on a server.

### 4.6 Offline shell, blocked actions and recovery ⚠

First load the installed app **online** and wait ~10 seconds so the offline copy is saved.

| ID | Do | Expected | Report with |
|---|---|---|---|
| G1 | Turn on **Airplane Mode**, then fully close and reopen the app. | The app opens **fully styled** with an **"You're offline"** banner. (Cellular-only or Wi-Fi-only off while the other is on is *not* offline.) | Screenshot; whether a browser error page appeared instead. |
| G2 | Online: reach the **Review & Submit** step with a photo taken. Turn Airplane Mode **on**. | Within a few seconds: the banner appears, **Submit is disabled**, and the text says "You're offline. Check-in needs a connection — reconnect to submit. Keep this page open — your photo isn't saved anywhere else." | Screenshot; how many seconds iOS took to notice. |
| G3 | Online: on the preflight screen, turn Airplane Mode **on**. | **Start check-in** is disabled with "You're offline. Reconnect to start checking in." | Screenshot. |
| G4 | Turn Airplane Mode **off**. | Banner disappears and Submit / Start become **enabled again** within a few seconds. Submit then completes the check-in. | Seconds it took; whether you had to restart the app. |
| G5 | While offline, tap around (Back to sessions, Retake photo). | The app stays usable; nothing crashes; no half-finished check-in appears. | What broke. |

⚠ Mock data works without any network, so you will **not** see the real-world "Unable to reach the server" screens or retry buttons here. Those need the real backend.

### 4.7 Service worker updates and cache behaviour ⚠

The phone cannot show cache contents. Do the **cache inspection on the PC (A4)** and only the *behaviour* on the phone. These steps change **only the test copy** `D:\saiv-mobile-test`. Keep the tunnel running throughout.

**Make a visible "version 2" in the copy** (PowerShell, in a third window; this edits the copy only):
```powershell
cd D:\saiv-mobile-test
$f='public\sw.js'; $t=[IO.File]::ReadAllText("$PWD\$f"); [IO.File]::WriteAllText("$PWD\$f", $t.Replace("const CACHE_VERSION = 'v1'","const CACHE_VERSION = 'v2'"), (New-Object Text.UTF8Encoding $false))
$f='app\page.tsx'; $t=[IO.File]::ReadAllText("$PWD\$f"); [IO.File]::WriteAllText("$PWD\$f", $t.Replace('Student Check-in</p>','Student Check-in (test build v2)</p>'), (New-Object Text.UTF8Encoding $false))
$env:NEXT_PUBLIC_USE_MOCKS = 'true'
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:9'
npm run build
```
Then stop the window running `npm run start` (Ctrl+C) and start it again (`npm run start -- -p 3100`). **Leave the tunnel window alone.** (Use `npm.cmd` in place of `npm` if it is blocked — see the note at the top of section 1.)

| ID | Do | Expected | Report with |
|---|---|---|---|
| H1 | Phone, online: open the installed app (close and reopen once if needed). | The header now reads **"Student Check-in (test build v2)"**. | Whether it needed one or two launches to update. |
| H2 | Airplane Mode on, close and reopen the app. | Still shows **"(test build v2)"** and the offline banner (the new shell was saved). | What shows. |
| H3 | **PC**, desktop Chrome on the same address → DevTools → Application → Cache Storage. | Only **`saiv-shell-v2`** remains (the old `v1` was removed); no cache entries for any API address. | Screenshot. |
| H4 | *(Known limitation — expect it, don't report it.)* If you stop the **server** window while the tunnel stays up, the phone shows a Cloudflare error page rather than the saved shell. The saved shell is used only when the device is truly offline (H2), not when a gateway answers with an error. | Error page. | — |

⚠ Not testable here: how updates behave on a real deployment (different hosting/CDN headers).

### 4.8 Optional: check-in history, details, appeals and face enrollment ⚠

> **What this checks, and what it does not.** In mock mode these tests check the **screens and the phone behaviour only** (layout, keyboard, camera, offline). The data is fake and lives in memory (a reload resets it). They do **not** test the real backend's rules or the real face service. Those were tested from a desktop browser against the real backend (`docs/FRONTEND-INTEGRATION-NOTES.md`, section 0) and have been only **partly tested on a phone** (see the purpose line above): the 7-day appeal window and the one-appeal rule, real risk scores and reasons, the real face service (photo quality, "no face detected", service unavailable), and the "account locked" handling.

Do these after 4.1–4.3 pass, signed in, on the session list. **Reload the app first** so you start from the fake data below (an appeal or an enrollment you make is forgotten on reload).

| Fake past check-in | Status | When | Risk / distance | Reasons shown |
|---|---|---|---|---|
| Lecture 3: Convolutional Networks | Flagged | 2 days ago | 0.62 / 180 m | location outside the venue area; device not recognised |
| Lecture 2: Optimisation | Rejected | 6 days ago | 0.9 / 12 m | the live photo check did not pass |
| Lecture 1: Introduction | Approved | 9 days ago | 0.1 / 20 m | none |

| ID | Do | Expected | Report with |
|---|---|---|---|
| J1 | Tap the **My check-ins** tab. | "My check-ins — Your attendance history, newest first." with three rows in this order: Lecture 3 (Flagged), Lecture 2 (Rejected), Lecture 1 (Approved), each with the course code CS6101 and a local date and time. Rows are easy to tap; no sideways scrolling. | Screenshot. |
| J2 | Tap the Lecture 3 row. | A detail screen: headline **"Check-in flagged for review"**, risk score 0.62, distance 180 m, a "Contributing factors" list with the two reasons, and an **Appeal this decision** button. **All check-ins** (with a left chevron icon, no arrow character) returns to the list. | Screenshot; anything missing or wrong. |
| J3 | Tap **Appeal this decision**, then tap the text box and start typing a reason. | The keyboard opens without hiding the **Send appeal** button (scroll if needed). **Send appeal** is disabled until you type something, and a character counter is shown. | Screenshot with the keyboard open. |
| J4 | Tap **Send appeal**. | "Your appeal has been sent." (the mock's wording), headline **"Check-in under appeal"**, your reason shown, and **no second Appeal button**. Back on the list the row shows **Appealed**. | Screenshot. |
| J5 | Open Lecture 2 (Rejected), then Lecture 1 (Approved). | Rejected: headline "Check-in rejected", the reason about the live photo check, and an Appeal button. Approved: "You're checked in" and **no** Appeal button. | What you see. |
| J6 | Open Lecture 2, tap **Appeal this decision**, type a reason, then turn **Airplane Mode on**. | **Send appeal** is disabled and the text says "You're offline. Reconnect to send your appeal." Turning Airplane Mode off enables it again within a few seconds. | Screenshot; how many seconds it took. |
| J7 | Tap the **Face enrollment** tab (the amber "Enroll your face once" card on the Check in tab, with its **Enroll now** link, leads to the same screen). | "Face enrollment — No face is enrolled on your account yet.", an **Agree and continue** button and a **Back to sessions** button. | Screenshot. |
| J8 | Tap **Agree and continue**, allow the camera, take a photo of a **wall** with the in-page camera, then tap **Enroll this photo**. | The iOS camera prompt appears; the preview shows inside the page; the review screen offers **Enroll this photo** and **Retake photo**; then "Face enrolled" with "Photo quality: 0.85." (the mock's fake value). | Screenshot of each step; any camera error text. |
| J9 | Tap **Back to sessions**, then **Face enrollment** again. | "Your face is already enrolled. You can enroll again to replace it." and the button now says **Agree and re-enroll**. (A reload resets this.) | What you see. |

⚠ Everything above is the mock. A pass here means the **screens work on your phone**, not that appeals or face enrollment work against the real backend.

### 4.9 UI refresh checks (no backend needed)

| ID | Do | Expected | Report with |
|---|---|---|---|
| K1 | Look at the header and the tab bar on the session list, in portrait. | Logo, round initial badge and **Log Out** sit on one centre line; the three tabs are the same width and height; the header, tab bar and cards share the same left and right edges; no sideways scrolling. | Screenshot of anything misaligned. |
| K2 | Go through every screen (sign in, sessions, preflight, consent, photo, review, result, history, face enrollment). | No emoji anywhere. Icons are simple line icons. | Screenshot of any emoji. |
| K3 | Check the active tab as you switch tabs. | The current tab is highlighted white; the other two are grey. | What you see. |
| K4 | On the consent screen. | Camera and location rows have small line icons in teal squares (not emoji). | Screenshot. |

Session window labels (**Open now**, **Not open yet**, **Closed**, with a disabled **Check-in closed** / **Check-in not open yet** button) and the enrollment prompt need real session data, so mock mode shows only **Open now** and the prompt. Those were checked against the real backend on a desktop browser, not on a phone.

## 5. What mock mode cannot validate (needs the real backend)

- Real network paths from the phone: CORS, HTTPS to the API (an HTTPS page cannot call a plain-HTTP API), timeouts, the "Unable to reach the server" screens and retries.
- Sign-in with real accounts, token refresh over the network, and what happens when tokens expire or are rejected.
- Real device-registration rules, duplicates, and the server's view of the device key.
- Check-in outcomes other than "approved": flagged, rejected, geofence distance, risk factors, time windows, duplicate protection after a lost response.
- Real liveness / face matching and the real face service. The **Face enrollment screen is built** and its screens can be checked in mock mode (optional section 4.8), but only the mock's fake enrollment runs here; the real face service (photo quality, "no face detected", service unavailable) needs the real backend.
- The real appeal rules (the 7-day window, one appeal per check-in) and the real data behind History: mock mode shows fake check-ins only.
- The "account locked" handling.
- Consent being saved on the server.

## 6. Clean up

1. Stop the tunnel and both server windows (Ctrl+C).
2. Delete the test copy (this removes only that folder — check the path first):
```powershell
Remove-Item -Recurse -Force D:\saiv-mobile-test
```
3. On the phone: remove the home-screen icon (long-press → Remove App), and clear the tunnel domain under Settings → Safari → Advanced → Website Data.
4. Your project and port-3000 dev server were never modified.
