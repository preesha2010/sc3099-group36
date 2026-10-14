# Module 1 Frontend — Backend Integration Notes

What the Next.js student frontend (`module1-frontend/`) relies on from the backend,
and where the available contract (`API-SPECIFICATION.md`, `DATABASE-SCHEMA.md`,
`INTEGRATION-GUIDE.md`, `tests/public/`) is silent. Items are things the backend
should confirm or provide; the frontend does not wait on them (it runs against mocks
by default: `NEXT_PUBLIC_USE_MOCKS`).

Status key: **Required** = the frontend's behaviour depends on it. **Confirm** = the
contract is silent/ambiguous and the frontend made a safe assumption.

## 1. Check-in (`POST /checkins/`)

| # | Item | Status | Detail |
|---|------|--------|--------|
| 1.1 | **Duplicate protection** | Required | One check-in per `(session_id, student_id)` must be enforced by the backend. Contract: spec lists `400` for "already checked in"; `DATABASE-SCHEMA.md` has `UNIQUE(session_id, student_id)`; `test_duplicate_checkin_fails` asserts `400`. The `INTEGRATION-GUIDE.md` handler is check-then-insert, which is not atomic: two concurrent requests can both pass the check, and the loser then hits the UNIQUE constraint. **Please make the loser return the same `400`, not a `500`.** The frontend recovers from a lost response by looking the session up in `my-checkins` after a `400` (see 1.2), so it relies on the first attempt's row being committed. |
| 1.2 | **`my-checkins` carries `session_id` and honours `course_id`** | Required | `GET /checkins/my-checkins` items must include `session_id` (the spec example does) and the `course_id` query filter must work. The frontend calls `?course_id=<session's course>` and matches on `session_id`; the default page size is 50 so an unfiltered lookup could miss the entry. |
| 1.3 | **Image encoding** | Confirm | `liveness_challenge_response` is sent as **raw base64 JPEG, with no `data:image/...;base64,` prefix**. The check-in spec only says `base64_encoded_image`; the enroll endpoint says "without data URL prefix" and the face service decodes with `base64.b64decode`, which rejects a prefixed string. If the backend wants something else, say so. |
| 1.4 | Rejected outcomes are `201` | Confirm | Per the status table, a failed liveness or GPS > 2× geofence yields `201` with `status: "rejected"` (not a 4xx). The UI shows the outcome from `status`, never from HTTP success alone. |
| 1.5 | Unknown `device_fingerprint` | Confirm | Tests show unregistered fingerprints are accepted (`201`). The frontend registers the device best-effort beforehand and will submit regardless of the registration result. |
| 1.6 | Consent not enforced at check-in | Confirm | Tests show check-in succeeds without `camera_consent`/`geolocation_consent`. The frontend records consent first (item 2.1) but treats server-side enforcement as the backend's decision. |
| 1.7 | `qr_code` | Confirm | Not sent yet. Sessions with `qr_code_enabled` show a notice only; a QR scan flow is not built. Needs a decision on the QR payload/validation. |
| 1.8 | Client-side retries | Info | The frontend never retries a check-in POST automatically. See "Duplicate submissions" below for why this matters. |

### Duplicate submissions — what the frontend does and what was verified

Frontend guard: a ref-based in-flight lock plus a disabled button means one user action
produces at most one submission call (`CheckInFlow.handleSubmit`). Any failure is surfaced
for the student to retry explicitly.

Why the backend still must be idempotent, demonstrated in Chromium (the in-app browser,
same-origin `fetch` and `XMLHttpRequest`, against a throwaway Node server on localhost
that reads the full POST then destroys the socket, counting what it received):

* A **single** `fetch(POST)` / `XHR POST` call, sent on a **reused keep-alive connection**
  that the server then reset, arrived at the server **twice** (the second on a fresh
  connection), although the page code called it once. The page saw one failure.
* The same POST on a **fresh connection** (no pooled socket) arrived **once**.

So the browser's network stack can replay a POST when a pooled connection dies, and the
first copy may already have been processed. That is a lost-response scenario the frontend
cannot prevent, which is why duplicate protection belongs on the backend (item 1.1). This
was observed on one browser engine only; do not read it as a guarantee about every browser.

## 2. User profile and consent

| # | Item | Status | Detail |
|---|------|--------|--------|
| 2.1 | Consent persistence | Required | The frontend sends `PUT /users/me` with `geolocation_consent: true` (+ `camera_consent: true` when the session needs a photo) **when the student clicks "Allow & Continue", before any camera or location request**. Skipped if the profile already has the flags. Test-proven: partial update of just these fields. If it fails the flow stops before collecting anything. |
| 2.2 | `GET /users/me` consent fields | Required | `camera_consent`, `geolocation_consent` and `face_enrolled` must be returned (used to skip re-consent and to warn when face matching is required but not enrolled). |

## 3. Device registration (`POST /devices/register`)

| # | Item | Status | Detail |
|---|------|--------|--------|
| 3.1 | Duplicate registration | Confirm | The spec lists no error codes and `device_fingerprint` is globally `UNIQUE`. The frontend does **not** assume idempotence: a failed/duplicate registration is treated as non-fatal, a local marker (bound to the fingerprint and key digest) avoids repeat attempts, and check-in proceeds. Please document the duplicate response (`409`? `200`?) and whether a different user registering the same fingerprint is rejected. |
| 3.2 | Fields | Confirm | Sends `device_fingerprint`, `public_key` (SPKI PEM, ECDSA P-256), `platform: "web"`, `device_name`. The conftest fixture omits `public_key`; confirm it is accepted/required. |
| 3.3 | Key rotation | Confirm | Not supported by the contract and not implemented. A browser that loses its key gets a new fingerprint and registers anew. |
| 3.4 | `GET /devices/my-devices` | Info | Does not return the fingerprint, so the frontend cannot show "this device" in a list. |

## 4. Auth

| # | Item | Status | Detail |
|---|------|--------|--------|
| 4.1 | Refresh | Confirm | `POST /auth/refresh` with the refresh token; on failure the user is sent to Sign In. Whether refresh tokens rotate is unspecified; the frontend stores whatever the response returns. |
| 4.2 | CORS / origin | Required | `NEXT_PUBLIC_API_URL` is origin-only (`/api/v1` is appended once). The backend must allow the frontend origin, and `localhost`/HTTPS is needed for camera, geolocation and Web Crypto on real devices. |

## 5. Not yet built (frontend milestones still to come)

* **Face enrollment** — `POST /users/me/face/enroll` is a separate flow from check-in (needs `camera_consent`, image without data-URL prefix). Required when a session has `require_face_match`; the check-in flow currently only warns.
* Offline queue, PWA shell, check-in history, appeals (`POST /checkins/{id}/appeal`).
* `Enrollment.instructor_name` type mismatch between the frontend type and the spec (to be settled).
