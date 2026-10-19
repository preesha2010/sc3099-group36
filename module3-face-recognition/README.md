# Module 3: Face Recognition and Risk Service

Internal FastAPI service on port 8001. No backend, database or Redis is needed
to run its endpoints or standalone tests. Only files in this module are modified.

**Latest handoff (2026-10-19):** see `VALIDATION-20261019.md`,
`MODULE2-INTEGRATION.md` and `TEAM-UPDATE.md`. Engineering/API checks pass;
the separate biometric classification gate still FAILS. Do not interpret test
counts or operational readiness as permission for automatic attendance approval.

## Run locally

Use Python 3.11 (Docker runtime) or 3.12 (locally tested).

```powershell
cd module3-face-recognition
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
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

Every launch method now validates configuration and preloads/warmups required
model assets in the app lifespan before accepting requests. The enhanced launcher sets
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
| `GET /ready` | None | 200 ready / 503 not ready; no paths, keys or model internals |
| `GET /metrics` | None | Process-local Prometheus text metrics; internal use only |
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
Only model weights, the private key, projection matrices and validated static
Mesh graph configuration are cached. Each Mesh execution graph is fresh and
closed after its image; no graph that processed a face is returned to a pool. The
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

## Standalone hardening and handoff (2026-10-16)

See `HANDOFF.md` for operational checks and the remaining team decisions. Docker
and every other module remain out of scope for this phase. Existing business
endpoints, thresholds, risk weights and the default SHA-256 profile are unchanged.

### Configuration, readiness and overload

| Variable | Default | Allowed range / meaning |
| --- | --- | --- |
| `FACE_TEMPLATE_MODE` | `sha256` | `sha256` or explicit `simhash` |
| `LIVENESS_BACKEND` | `heuristic` | `heuristic` or explicit `minifasnet` |
| `FACE_MODEL_WORKERS` | `4` | 1-8 model slots, not server processes |
| `INFERENCE_CONCURRENCY` | `8` | 1-16 admitted visual pipelines |
| `INFERENCE_PENDING` | `32` | 0-128 additional waiting requests |
| `INFERENCE_QUEUE_SECONDS` | `2` | 0.01-30 seconds of admission wait |

Invalid configuration, missing/wrong-sized keys, bad checksums or model warmup
failure prevent startup. `/health` retains its original process-health response;
`/ready` additionally checks startup configuration, immutable asset fingerprints,
the key and degraded model pools. Replacing files/configuration in a running
process marks it not ready; stop traffic and restart to re-verify checksums.
Readiness is not per-request rehashing or continuous tamper-proof attestation.

Admission runs before request-body buffering and JSON/image decoding. Overflow
or admission timeout returns 503 with `Retry-After: 1`. A running native inference
is NOT forcibly cancelled when its caller disconnects. Request bodies still have
the original 10 MiB cap. Queue deadlines do not guarantee end-to-end deadlines:
upload time, inference and network time also matter. Upstream proxy/server body
timeouts and fleet-wide connection limits belong to deployment configuration.

Failed inference/blank-buffer cleanup discards the instance. Reconstruction is
retried using the same capacity token; failures cannot silently shrink the pool
or overwrite the original inference error. A two-second background recovery loop
also retries degraded slots, so recovery does not depend on user traffic. Asset
or key changes are not repaired in place. Persistent recovery failure keeps the
pool not ready and requires operator attention; `/health` alone is insufficient.

Image preparation now resizes before detector color conversion and converts
only an original-resolution face neighborhood for SFace alignment. Landmark
translation preserves geometry; regression tests retain cross-photo results.
Blank inference cleanup and the prohibition on caching biometric inputs remain.

### Internal monitoring

`/metrics` exposes fixed-label request status counters, cumulative stage latency
histograms, admitted/waiting counts, overload rejections and current resident
memory on supported Windows/Linux hosts. Stages include decode, face detection,
embedding, cleanup, mesh, PAD, template generation and queue wait. Stage durations
are nested, so they must NOT all be summed as exclusive CPU time. Metrics reset
on restart and are process-local, not fleet aggregates or distributed traces.

Every response gets a newly generated `X-Request-ID`. Client-supplied IDs and
unknown URL segments are never metric labels. No photos, image base64, identity,
template, key, IP or user-agent is logged/exported by this instrumentation. Keep
this internal unauthenticated service and `/metrics` off the public internet;
Module 4 can scrape it later without any Module 4 configuration change here.

### Repeatable independent acceptance

```powershell
# Each starts and stops its OWN ephemeral loopback server, with no backend/DB.
python scripts/acceptance.py --profile sha256 --soak-seconds 120 --report evaluation/acceptance-sha256.json
python scripts/acceptance.py --profile enhanced --soak-seconds 120 --report evaluation/acceptance-enhanced.json

# Separate all-success throughput comparison, deliberately NOT production queue settings.
python scripts/evaluate.py --pending 128 --queue-seconds 30 --report evaluation/throughput.json
```

Acceptance checks real HTTP enrollment -> verification -> liveness -> risk score
propagation, legacy matching, invalid inputs, blank images, process restarts with
the same key, repeated mixed workloads, health responsiveness, overload/retry
semantics and recovery after the burst. Default client HTTP timeout is 5 seconds.
Successful inference, 503 rejection and transport errors are reported separately.
A two-minute soak is a finite observation, not proof of long-term leak freedom.
The memory check defaults to a 128 MiB end-minus-warm-baseline budget, configurable
with `--max-rss-growth-mib`; it is not a guaranteed fleet memory envelope.

`evaluate.py` deliberately allows a 128-request queue and 30-second queue wait
for all-success 10/50/100-client throughput comparisons. Its results MUST NOT be
presented as measurements of the default 32-waiter/2-second overload policy.
It still fetches only the original pinned publisher demos to RAM. Rerun on the
actual deployment host; older and newer runs are not controlled benchmarks.

### Authorized corpus evaluation

```powershell
python scripts/evaluate_corpus.py C:\private-dataset\manifest.json --report evaluation/corpus.json
```

Use `evaluation/corpus.example.json` as a format reference. Keep real manifests
and images OUT of Git. Use an authorized existing local dataset; the tool never
collects camera footage, downloads images or writes copies. Only acknowledge
`authorized: true` after verifying permission. Each JPEG/PNG must be inside the
manifest's directory. Labels must be real JSON booleans. The example is disabled
and intentionally has no images. Do not change its authorization flag in Git.

Reports contain aggregate counts/rates and Wilson 95% intervals, never per-person
scores, paths, templates or identities. FAR/FRR use impostor/genuine comparisons;
APCER/BPCER use attack/bona-fide presentations. HTTP/quality failures are reported
separately with requested/evaluated counts, not scored as correct rejections.
An absent denominator produces null, NOT zero error. Same-file identity pairs are
counted so they cannot be mistaken for cross-photo validation. Threshold sweeps
are descriptive and do not change the API's 0.70/0.60 decision thresholds.

Use distinct subjects for calibration and held-out evaluation, varied cameras,
lighting/poses and separately designed print/screen/replay attacks. Repeated
comparisons of one subject are correlated; the simple binomial intervals do not
correct that dependence. The existing two identities and three publisher demos
remain smoke tests, not a representative security evaluation. Larger authorized
data and a final template-policy decision are still external dependencies.

### Measured verification record (2026-10-16)

- Module-local regression: **81 passed**, model-backed tests included, no skips.
- Unchanged public HTTP suite: **15/15 in each profile**; `pip check` passed.
- Existing enhanced cross-photo and publisher PAD smoke decisions/scores stayed
  unchanged after the image-preparation optimization.
- Both acceptance profiles passed two process restarts, score propagation,
  negative inputs, two-minute repeated workloads and recovery after overload.

| Profile, four simultaneous callers per wave | Successful sustained requests per endpoint | Verify maximum | Liveness maximum | End-minus-baseline RSS |
| --- | --- | --- | --- | --- |
| SHA-256 | 1020 / 1020 | 0.157 s | 0.422 s | +23.137 MiB |
| Enhanced | 660 / 660 | 0.313 s | 0.609 s | -48.250 MiB |

These two-minute RSS observations do not prove leak freedom. Under the default
admission policy, enhanced 100-request bursts produced **48 successful + 52
rejected** verifications and **39 successful + 61 rejected** liveness calls.
Rejections were explicit 503/Retry-After responses, not successful inferences;
health checks and subsequent normal requests succeeded. Counts depend on timing.

A separate final enhanced throughput run with 128 waiters / 30-second queue
deadline processed all 10/50/100 requests successfully on each endpoint:

| Concurrent requests | Verify P95 | Liveness P95 |
| --- | --- | --- |
| 10 | 0.641 s | 0.984 s |
| 50 | 2.125 s | 3.187 s |
| 100 | 4.125 s | 6.313 s |

At 100 requests, maximum verify/liveness latency was 4.469/6.625 seconds.
**100-client liveness still exceeds the current backend's five-second timeout.**
No universal five-second guarantee is claimed, and overload rejection is not a
substitute for successful processing. These are local observations, not a
controlled before/after comparison or a deployment capacity certification.
Raw aggregate records: `evaluation/acceptance-sha256-20261016.json`,
`evaluation/acceptance-enhanced-20261016.json`, and
`evaluation/throughput-20261016.json`. Older reports, including the unresolved
prolonged-stall failure, are retained as historical evidence.

## Independent validation follow-up (2026-10-18)

Read `VALIDATION-20261018.md` before treating this branch as production-ready.
Expanded diagnostics found **identity false accepts and transformed attack
acceptances**. Passing unit/public tests and operational readiness does NOT
certify biometric accuracy. Existing thresholds/policies are unchanged; no
parameter was fitted to the two demo identities to hide these failures.

Implementation updates:

- Cache only MediaPipe's immutable validated topology/options. Execute every
  image in a new, closed graph with `use_prev_landmarks=false`, 468 landmarks and
  no iris refinement. Real-image tests compare all coordinates to stock
  MediaPipe at 1e-7 tolerance; separate tests cover closure on failures.
- Reject non-finite/wrong-shaped neural outputs and invalid PAD probabilities
  with 503. Invalid PAD values cannot fall back to a heuristic pass. Blank-buffer
  cleanup still runs on inference failure.
- Slow model reconstruction no longer holds healthy slots while loading a failed
  slot. Test coverage includes continued borrowing during a blocked rebuild.
- Pinned Windows native readers require ASCII-only runtime/resource/model paths.
  Startup now explains this failure before serving. The Python source directory
  itself may contain Unicode if the runtime and `FACE_MODEL_DIR` use ASCII paths.
- `FACE_NATIVE_THREADS` is validated in 1-4, default **1**. Bigger thread counts
  were measured and did not consistently improve the full liveness pipeline.
  No inference engine or model-weight change is shipped by this phase.

Repeat the additional checks from this module in an ASCII-path environment:

```powershell
python scripts/verify.py
python scripts/evaluate.py --clients 100 --repeat 3 --report evaluation/repeated-throughput.json
python scripts/evaluate_robustness.py --report evaluation/robustness.json
python scripts/acceptance.py --profile enhanced --soak-seconds 600 --restarts 3 --report evaluation/soak-enhanced.json
python scripts/acceptance.py --profile sha256 --soak-seconds 300 --restarts 3 --report evaluation/soak-sha256.json
```

`evaluate.py` additionally accepts `--concurrency` (1-16), `--native-threads`
(1-4) and `--workers` (1-8). The throughput experiment still uses the explicitly
relaxed 128-waiter/30-second queue, not default overload settings. `verify.py`
explicitly selects its compatibility baseline rather than inheriting a caller's
enhanced-mode variables.

`evaluate_robustness.py` makes 40 identity comparisons and 24 PAD checks over
eight conditions: original, dark/bright, low contrast, +/-10 degree rotation,
JPEG quality 40 and resize-to-512. It uses ONLY existing repository photos and
three checksum-pinned publisher demos. Transformations happen in RAM. One genuine
identity pair per condition derives from its enrollment image; it is explicitly
counted, not described as an independent capture. Reports contain aggregate
counts/sweeps, not per-person paths, scores, images or templates.

Exit status is nonzero for a failed classification gate even if every HTTP call
succeeded. Correlated transformations of two identities/three PAD images do not
constitute an independent population accuracy estimate. Threshold sweeps are
descriptive only, never an automatic policy/calibration change.

Acceptance report format version 2 stores aggregate counts for **all** waves,
periodic memory samples, peak/end RSS and early/late window averages. It checks
both final growth and windowed growth against the original 128 MiB budget; a
single low final sample cannot conceal sustained growth. Every 30 seconds an
atomic checkpoint replaces the previous valid report and progress is printed.
`state=soaking` or `passed=false` is not a completed acceptance run. Finite tests
do not prove long-term leak freedom or cross-host capacity.

Completed follow-up evidence: 106 module tests passed without skips, both public
profiles passed 15/15, SHA-256 ran five minutes (3292 successful calls per visual
endpoint) and enhanced ran ten minutes (3676 per endpoint). Both passed three
restart workflows and overload recovery; windowed RSS growth remained below
the unchanged 128 MiB budget. These runs overlapped on one host and are finite
stability observations, not isolated performance or security certification.

The ASGI audit `python scripts/compare_mesh.py` compares the original attention
mesh against the optimized graph on all 24 PAD conditions. All decisions and
final liveness scores agreed in `evaluation/mesh-comparison-20261018.json`:
the discovered counterexamples are not explained away as a new cache regression.
The failed robustness classification gate remains an explicit release blocker.

For fail-closed local gating, run `python scripts/release_check.py`. It executes
regression/public checks then the robustness gate, stops on the first failure
and propagates its exit code. A later successful soak cannot mask a prior failed
classification gate. Even an eventual zero exit is only a smoke result, not
permission to deploy without the external data/policy/integration approvals.

## Backend boundary and stricter latency gating (2026-10-19)

The backend's actual unmodified FaceClient at commit `601b381` passed 28 live
service-boundary checks (14 per profile) and four HTTP fault checks. Only its
settings import is stubbed; no backend app/DB/attendance workflow is claimed.
`MODULE2-INTEGRATION.md` records risk-policy and invalid-response handling that
still require the backend owner. This work does not alter their branch.

```powershell
git fetch origin refs/heads/module2-backend:refs/remotes/origin/module2-backend
python scripts/check_backend_contract.py --backend-ref origin/module2-backend
python scripts/release_check.py --backend-ref origin/module2-backend
```

The second command tests the client/service boundary; the last also runs
regression/public tests and then the independent classification gate. It stops
and propagates the failed gate rather than declaring the release complete.

Module regression now has **128 passing tests**, without skips. Additional
checks cover corrupt SFace outputs evicting the borrowed model after blank
cleanup, invalid Mesh output, redacted native Mesh failures and released slots.
No model weights, templates, thresholds, risk weights or default policies changed.

`evaluate.py` now records `successful_within_target`, all-success functional
checks and a **separate maximum-latency** gate. P95 alone cannot hide a slow
tail; neither a 503 nor an HTTP timeout is a successful inference. Exit 1 means
functional/infrastructure failure; exit 2 means functional checks completed but
the local five-second latency gate failed; exit 0 requires both. Atomic reports
retain failed state without exception bodies. The classification security gate
is still a separate required check, not overridden by this command.
