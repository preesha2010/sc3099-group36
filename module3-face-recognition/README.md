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

## Enable cross-photo recognition and pretrained anti-spoofing

The default `uvicorn app.main:app` command remains the repository's SHA-256
compatibility profile. The lecture's SimHash alternative is an explicit opt-in:

```powershell
# Once, in the API environment: download checked YuNet/SFace weights and create
# a private, persistent template key inside this module's ignored models folder.
python scripts/bootstrap_models.py

# Once, in a separate Python 3.11/3.12 tools environment (NOT the API runtime):
python -m pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install onnx==1.17.0 numpy==1.26.4 httpx==0.26.0
python scripts/bootstrap_models.py --pad

# Back in the API environment:
python scripts/run_enhanced.py
```

The enhanced launcher validates and loads the model assets before serving, sets
`FACE_TEMPLATE_MODE=simhash`, `LIVENESS_BACKEND=minifasnet`, four bounded model
slots, and single-thread native kernels. API paths and field names are unchanged.
The entire synchronous pipeline is also limited to eight concurrent handlers
(`INFERENCE_CONCURRENCY`, range 1-16), so waiting requests do not all retain
decoded full-resolution images. Larger model pools are configurable but must
be measured rather than assumed faster.
Only bootstrap needs internet access; request inference is entirely local.
Model weights are not committed. Source commits, original checkpoints and
exported ONNX checksums are verified; licenses and provenance are described in
`THIRD_PARTY.md`. PyTorch is only used for one-time offline conversion.

SimHash mode uses aligned, normalized SFace identity features (128 dimensions)
and 64 fixed private random projections, following the lecture's approach.
The 64-hex result contains version/key ID, eight bytes of SimHash, and a 16-byte
HMAC-SHA256 authentication tag. The API score is `(1 + cos(pi * distance/64))/2`,
with the documented threshold 0.70. It is not a SHA-256 digest of an embedding.
It exposes similarity information and remains sensitive biometric data; this
format does not claim cryptographic non-reconstructability or anonymization.

**Do not mix profiles.** Legacy SHA-256 templates are rejected by SimHash mode;
users must re-enroll. Back up `models/template.key`, keep it out of Git and logs,
and share it securely only between instances of the same Module 3 deployment.
Key rotation requires a service restart and new enrollments. Private projection
configuration affects calibration; thresholds need a larger, consented dataset
before deployment. No image or floating-point feature vector is stored as a
workaround for either profile.

MiniFASNetV2/V1SE score two expanded face crops and combine their real-class
probabilities with the image/mesh quality gate. This is stronger than accepting
an inferred nose depth alone, but it is still a passive classifier whose error
rates depend on the camera and attack domain. It does not verify motion or
prove protection against arbitrary deepfakes, 3D masks, or sophisticated replay.

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

After both model sets are bootstrapped, run the separate enhanced evaluation:

```powershell
python scripts/evaluate.py
```

It starts/stops its own loopback server, runs unchanged public tests in enhanced
mode, tests Obama/Biden identity pairs, fetches three checksum-pinned publisher
PAD examples into memory, and measures 10/50/100 simultaneous requests on both
verification and liveness. `evaluation/latest.json` contains only labels, scores
and timings; the ignored server log does not log request bodies. Failed requests
are counted, never retried to inflate the result. This corpus is small and the
publisher examples are not an independent attack-validation dataset.

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

1. **The two specifications describe different template policies.** The default
   compatibility profile still uses a SHA-256 digest of a normalized grayscale
   crop and cannot match different photos of the same person. Enhanced SimHash
   mode now implements and tests cross-photo identity matching using SFace.
   The repository's security requirements mandate SHA-256-only storage while
   the Module 3 slides explain SimHash/similarity-preserving templates. A normal
   SHA-256 digest does not preserve distances. The separate opt-in profile makes
   this difference explicit rather than silently changing the existing policy.
2. **The compatibility profile's passive liveness is a heuristic.** Mesh depth, completeness, sharpness and
   color variation use the documented 30/25/25/20 weights with a quality gate.
   Predicted mesh depth is not measured sensor depth. A sharp photo or screen
   replay can pass; these cues do not establish strong anti-spoofing protection.
   Metadata explicitly reports `method: single_image_heuristic` and
   `motion_verified: false`. Enhanced mode reports
   `method: minifasnet_ensemble_with_quality_gate`; small-sample results are not
   general anti-spoofing accuracy guarantees.
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
Legacy detectors/meshes are request-local, with at most four simultaneous mesh
graphs. Enhanced inference models are cached in bounded exclusive pools; blank
inputs are forwarded after every inference to overwrite internal pixel/feature
buffers. Models with failed inference/cleanup are discarded and recreated.
Only model weights, the private key, and projection matrices are cached. The
pool does not cache student templates, pixels or features. Container build and
full-system load testing must be reported separately from these local tests.

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

## Enhanced verification record (2026-10-09)

Model-backed regression tests cover cross-photo identity, brightness changes,
template authentication, key mismatch, missing assets and inference-buffer
cleanup. See `evaluation/latest.json` for the full measured report.

- Module-local tests: 52 passed with assets present, no model-backed tests skipped.
- SHA-256 compatibility public tests: 15/15; enhanced public tests: 15/15.

- Obama same/different photographs pass against the original enrollment;
  Biden is rejected. Current scores: 1.0, 0.777785, 0.817197, 0.378510.
- Publisher attack samples F1/F2 are rejected at 0.072331/0.181286; T1 passes
  at 0.993568. These are two attack examples and one genuine example, not a
  validated general-purpose PAD accuracy estimate.
- The unchanged public suite also passes 15/15 in enhanced mode.
- Final four-slot profile: verification and liveness each succeeded on all
  10, 50, and 100 simultaneous requests with no health-check failures.
- At 100 clients, verification P95 was 8.469s and liveness P95 4.500s; health
  maximum was 0.422s/0.125s respectively. High-load verification therefore does
  **not** meet the current backend client's five-second timeout. This remains
  a deployment/performance constraint, not a completed latency target.
- An eight-slot comparison (`evaluation/workers8.json`) passed 100/100 on
  both endpoints but gave P95 7.531s/14.188s. Increasing slots did not solve
  the latency issue, so the safer default remains four.
- A prior failed repeat is preserved as `evaluation/run-with-timeouts.json`:
  90 of 100 verification calls timed out during an abnormal prolonged stall.
  Its cause was not established. Subsequent bounded-pipeline runs passed,
  which is evidence of those runs, not proof that every failure is eliminated.
- Docker was not started, built or tested during this enhancement phase.
