# Module 3: Face Recognition and Risk Service

Internal FastAPI service on port 8001. No backend, database or Redis is needed
to run its endpoints or standalone tests. Only files in this module are modified.

## Run locally

Use Python 3.11 (Docker runtime) or 3.12 (locally tested).

```powershell
cd module3-face-recognition
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open `http://localhost:8001/docs` for executable API examples. In Docker,
the existing backend URL is `http://face-recognition:8001`.

## Build this service independently

```powershell
docker build -t saiv-module3 .
docker run --rm --name saiv-module3-local -p 127.0.0.1:8001:8001 saiv-module3
```

The image runs as a non-root user and includes a health check. This command
does not start or require any other module. Docker engine must be running.

## Reproduce verification

```powershell
python scripts/verify.py
```

The script runs module-local tests, starts a temporary service on a free
loopback port, runs the unchanged shared `test_face_recognition.py`, reports
cross-photo matching behavior, measures ten simultaneous same-image verifications,
and stops its own server even on failure.
Keep the repository's `sample_images/` and `tests/` available for these checks.
Tests generate temporary image payloads in memory; they do not write face files.

## HTTP contracts

| Endpoint | Request fields | Result |
| --- | --- | --- |
| `GET /health` | None | `status`, `service` |
| `GET /` | None | `service`, `version`, endpoint paths |
| `POST /face/enroll` | `user_id`, `image`, `camera_consent: true` | 201; template hash, quality, details |
| `POST /face/verify` | `image`, `reference_template_hash` | 200; match boolean/score, threshold, current hash |
| `POST /face/match` | `image`, `reference_hash` | Legacy match fields |
| `POST /liveness/check` | `challenge_response`, optional `challenge_type` | 200 for passive; liveness score, hash, details |
| `POST /risk/assess` | Optional face/liveness scores, device fields, IP, user agent, geolocation | Risk score, level, threshold, weighted contributions, recommendations |

Images are base64 PNG/JPEG strings, optionally with a data-URL prefix.
Enrollment requires an actual boolean consent value, exactly one detected face,
detection confidence >= 0.7 and quality score >= 0.5. Reference hashes must
be 64 lowercase hexadecimal characters. Scores and coordinates must be finite.
Risk weights remain 25% liveness, 25% match, 20% device, 15% network, 15% location.
`signal_breakdown` contains weighted contributions whose sum is `risk_score`.
Risk levels: LOW < 0.3, MEDIUM < 0.5, HIGH < 0.7, CRITICAL >= 0.7.

### Errors and privacy

- 400: invalid/corrupt/unsupported image, missing enrollment consent, multiple
  faces, image smaller than 32 pixels per side, or an unsupported motion check.
- 413: JSON request > 10 MiB, decoded image > 6 MiB, side > 4096 pixels,
  or total image pixels > 12 million. Bounds are checked before full decoding.
- 422: invalid/missing request fields, invalid template hash, invalid score,
  invalid coordinates or unsupported challenge enum.
- Verification with no detected face returns 200 with `match_passed: false`,
  `face_detected: false`, score 0 and an empty current hash.

No input image, crop or embedding is persisted, cached or returned. Validation
errors omit rejected inputs, including base64 and device evidence. Camera data
is processed locally; no third-party recognition API is called. CORS allows
localhost ports 3000/8501 by default; `CORS_ORIGINS` accepts comma-separated
explicit origins. It does not use cookies or wildcard credentialed access.

## Current limitations and specification conflict

1. **Cross-photo identity verification is not solved.** The current face template
   is a SHA-256 digest of a normalized grayscale crop. It verifies identical
   representations, not identity under different photos, angles or lighting.
   `obama2.jpg` and `obama3.jpg` fail against an `obama.jpg` enrollment. The public
   matching test uses the exact same image, so passing it does not resolve this.
   The repository's security requirements mandate SHA-256-only storage while
   the Module 3 slides explain SimHash/similarity-preserving templates. A normal
   SHA-256 digest does not preserve distances. The template policy must be
   resolved before replacing the current format; raw embeddings must not be
   secretly retained as a workaround.
2. **Passive liveness is a heuristic.** Mesh depth, completeness, sharpness and
   color variation use the documented 30/25/25/20 weights with a quality gate.
   Predicted mesh depth is not measured sensor depth. A sharp photo or screen
   replay can pass; these cues do not establish strong anti-spoofing protection.
   Metadata explicitly reports `method: single_image_heuristic` and
   `motion_verified: false`.
3. **Motion challenges are not implemented.** Default mode is `passive`.
   `blink` and `head_turn` return 400 instead of passing an unrelated still image.
   Actual motion verification needs an agreed multi-frame/challenge protocol.
4. **Device trust is unverified.** Malformed PEM/signature fields get high risk.
   Even syntactically valid evidence cannot get zero device risk: the request
   has no signed message or expected server challenge. Signature presence is
   not proof of device ownership. Private IP/client labels are also only risk
   hints, not reliable evidence of VPN use.
5. **Final attendance status is external.** This service returns scores and
   signals. It has no course/session history, geofence center, enrollment or
   attendance database; the calling backend owns those decisions.

Blocking visual handlers run in FastAPI's thread pool; health/root remain async.
Each detector/mesh has request-local state, avoiding shared mutable inference
objects. Container build and load testing must be reported separately from
local functional test results.

## Verification record (2026-10-09)

Fresh Windows Python 3.12 environment installed from this module's
`requirements.txt`; `pip check` reported no broken requirements.

- Module-local regression tests: 36 passed.
- Unchanged public face-recognition suite over real HTTP: 15 passed, 15/15 points.
- Ten concurrent same-image verifications: 10/10 succeeded, maximum observed
  latency 0.281 seconds; concurrent health request 0.078 seconds. These are local
  measurements, not a promise about other machines or the full system.
- Cross-photo identity diagnostics: `obama2.jpg` and `obama3.jpg` still fail
  against `obama.jpg`. This remains a known functional limitation.
- Docker image build remains unverified: `docker desktop start --timeout 30`
  exceeded its deadline and the engine did not become available. Changes to
  the Dockerfile were inspected, but are not claimed as a successful build.
