# Module 3 independent follow-up, 2026-10-20

**Historical report, superseded by `VALIDATION-20261023.md`:** the user subsequently
authorized a scoring change. The existing-sample identity gate now passes with
0/16 false accepts and 0/24 false rejects. This does not erase these historical
failures or establish independent accuracy; toy-seed sensitivity still finds
errors. Weights/key/template encoding/numeric thresholds remain unchanged.

## Current outcome

Engineering regression, upload transport/privacy checks and finite stability
checks pass. The corrected PAD demo checks pass. **Biometric release is still
BLOCKED by five identity false accepts** in 16 correlated impostor comparisons.
No independent authorized accuracy corpus is available.

Only Module 3 files changed. Docker/other modules/root files/shared tests are
untouched. Production model weights, template key/format/projections, thresholds,
risk weights and default exact-image SHA-256 policy are unchanged. No new faces
were collected, and no feature vectors/images/templates are persisted by the
new diagnostics. Do not claim all biometric/security objectives are complete.

## Correction to previously reported PAD failures

All three pinned publisher demos carry EXIF Orientation=6. The API decoder has
always normalized this orientation. The evaluation helper, however, converted
raw pixels and re-encoded JPEG without first applying that orientation. Modified
conditions therefore turned the image sideways instead of merely changing its
brightness/compression. The original condition retained its EXIF and was decoded
correctly. This was a **test-input construction bug**, not a production-model fix.

Transform version 2 applies `ImageOps.exif_transpose` before any modification.
A synthetic asymmetric-image regression tests displayed orientation in every
condition. The corrected report explicitly records transform version 2.

| Corrected correlated demo comparisons | Errors / comparisons |
| --- | --- |
| Wrong-person accepted | 5 / 16 |
| Genuine identity rejected | 0 / 24 |
| Attack accepted as live | 0 / 16 |
| Bona-fide presentation rejected | 0 / 8 |

Evidence: `evaluation/robustness-v2-20261020.json`. Earlier claims of two attack
accepts/seven genuine rejects must NOT be used as current model-error evidence.
Historical reports remain, and the October 18/19 human reports now carry this
correction. These 24 PAD checks are still just three publisher examples with
correlated transformations, NOT independent real-camera anti-spoof certification.

## Identity false-accept attribution and rejected experiment

`evaluation/classification-diagnosis-v2-20261020.json` compares raw normalized
SFace cosine to the current 64-bit SimHash estimate at the SAME score mapping:
API threshold .70 corresponds to raw cosine .40. It does not silently compare
API .70 to a different raw-cosine .70 threshold.

All five current template false accepts have raw-equivalent rejection. On these
specific comparisons, the 64-bit projection's approximation crosses the operating
threshold. Raw-comparison errors were zero on this tiny corpus; that is NOT a
proposal to persist embeddings or a claim of general raw-feature accuracy.

The optional `--projection-study` compares an orthogonalized-plane candidate:

| Diagnostic projection family | Impostor errors | Genuine errors |
| --- | --- | --- |
| Current private-key random 64-bit | 5 / 16 | 0 / 24 |
| Same-key orthogonalized 64-bit candidate | 8 / 16 | 0 / 24 |
| 32 fixed toy random seeds, repeated comparisons | 69 / 512 | 2 / 768 |
| 32 fixed toy orthogonalized seeds, repeated comparisons | 72 / 512 | 1 / 768 |

Evidence: `evaluation/projection-study-20261020.json`. The candidate is worse
here and was REJECTED, not shipped. Repeated seeds do not add independent people
or justify a population error rate. No favorable private key/seed was selected,
no key was regenerated, and no threshold was fitted to hide failures. Deploying
a different projection/policy would invalidate current templates and needs an
explicit migration/calibration decision; it is not done in this branch.

The PAD layer diagnosis reconstructs the existing quality/PAD score combination;
all 24 corrected scores agree within 1e-6. It adds explanation, not new model
accuracy evidence. Temporary vectors/projection-study matrices stay in this
standalone process's RAM, are cleared when finished and are never exported.

## Upload protection and private optional OTLP

- `REQUEST_BODY_SECONDS=3` is a startup-validated absolute whole-body deadline
  (0.01-30 seconds), after inference admission. Stalled/trickling uploads cannot
  keep renewing it. HTTP **408 / Connection: close** frees the slot.
- Disconnect/cancellation also releases capacity. Native inference is never
  cancelled by this deadline; a completed upload can proceed beyond its timer.
- Optional `OTEL_EXPORTER_OTLP_ENDPOINT` enables a provider owned by the app
  lifespan. Default empty disables it. No process-global provider is installed.
- Fixed route/method/status/stage/service attributes only; unknown paths are
  `other`. No images, scores, identities, templates, headers, URLs/queries,
  peer IPs, exceptions or stack traces. Baggage/tracestate are ignored.
- W3C traceparent is preserved into server and AnyIO worker-stage spans. A
  bounded SDK background queue exports protobuf in single attempts with network
  timeouts, without response-body logging/redirects/ambient credentials.
- Collector failure is a separate export-failure metric and does not change
  inference, health or readiness. Bounded queues can drop spans; the counter
  counts failed exports, not every dropped/partially accepted span. Delivery is
  not durable and is not an authenticated or fully verified Module 4 deployment.

`evaluation/transport-final-20261020.json` and the complete-pipeline
`evaluation/transport.json` pass real loopback TCP tests for fixed/chunked stalled
and trickling uploads, disconnect/recovery, protobuf receiver delivery, parent
and worker-stage continuity, marker absence and failed-Collector isolation.

The initial `transport-20261020.json` failure is retained: a trace-stage name was
missing from the allowlist. It was corrected to the actual `image_decode` name,
and a regression now checks every production `@timed` decorator is allowlisted.
No raw exception/data capture was enabled to make that check pass.

Header/TCP handshake deadlines and production network access control still need
the upstream server/proxy owner. The test receiver is not the real Collector;
backend -> Module 3 -> Module 4 full-chain tracing remains a joint task.

## Verification results

- **160 module-local tests passed**, no skips; 13 dependency deprecation warnings
  including the pinned OTel SDK timestamp serializer. `pip check` passes.
- **15/15 unchanged public face tests passed in each profile.**
- The actual unchanged backend client again passes **28 live boundary checks and
  four HTTP fault checks** at backend commit `601b381`. No DB/JWT/attendance-flow
  completion is inferred from the boundary result.
- The full `release_check.py --transport --backend-ref origin/module2-backend`
  command passes engineering/transport/client checks and then propagates the
  corrected classification gate's **nonzero child status 2**. It remains blocked.

### Fifteen-minute enhanced stability

`evaluation/soak-enhanced-20261020.json`: 900.157 seconds, four clients per wave,
three successful restart workflows, **11,752 / 11,752 successful calls to EACH
visual endpoint**, zero health failures. Maximum verify/live latencies were
0.219/0.360 seconds. End RSS grew 80.836 MiB, windowed growth 69.978 MiB, both
within the unchanged 128 MiB budget. Post-overload normal requests/readiness
passed. Burst verify processed 50/rejected 50; liveness processed 48/rejected 52.
Rejections were 503, NEVER successful inference.

Other diagnostics, tests, mixed-image and throughput processes overlapped this
soak on the same host. This is finite contention/stability evidence, not an
isolated benchmark or indefinite leak proof. Tracing was disabled in load tests.

### Maximum-image mixed boundary stress

The final `evaluation/boundaries-detected-20261020.json` ran eight concurrent
callers for 120.328 seconds and **2824 measured requests**, covering all eight
input cases on BOTH endpoints. The normal and exactly-12MP face cases must
really detect a face and produce a template; a no-face 200 cannot pass them.
Other cases cover exactly-12MP blank, >12MP, >4096 side, <32 side, corrupt images,
over-limit base64 and an oversized declared body rejected before upload.

There were 1059 expected 200 responses, 706 expected 400 rejections and 1059
expected 413 rejections; no 503/health failures. Maximum measured latency was
0.453 seconds, readiness recovered, and both final/windowed RSS growth checks
passed. All cases were warmed at the selected concurrency before the baseline;
the initial RSS high-watermark then declined. This is not a cold-start memory
limit, camera accuracy test or evidence of indefinite leak freedom.

Earlier boundary reports are retained. The final run supersedes early mixed
coverage that paired only some cases per endpoint and an intermediate run that
did not explicitly require positive face detection. The final source tests both
coverage scheduling and the no-face-cannot-pass-large-face condition.

### Repeated relaxed-queue throughput

`evaluation/throughput-20261020.json` ran 10/50/100 callers twice, with **320/320
successful requests per endpoint**, all within five seconds, no health failures.
100-client verify P95: 2.046/2.187 s; liveness P95: 2.891/2.578 s. The maximum
100-client liveness request took 3.000 seconds.

This explicitly uses 128 waiters/30-second queue, not the default 32/two seconds,
and overlapped other host work. It does not guarantee all 100 requests under
default overload policy, deployment resources or a universal latency SLA.

## Reproduce and remaining boundary

```powershell
python scripts/release_check.py --transport --backend-ref origin/module2-backend
python scripts/diagnose_classification.py --projection-study
python scripts/stress_boundaries.py --clients 8 --seconds 120
python scripts/acceptance.py --profile enhanced --soak-seconds 900 --restarts 3
```

Existing samples and checked model assets are required. Test tools disable
remote telemetry; only the transport probe explicitly enables its own loopback
receiver. Production deployment remains blocked by identity false accepts,
unresolved template/migration/operating-point policy and absent independent
authorized data. Actual camera/auth/DB/attendance/dashboard/risk/failure-policy
integration, operational key custody and deployment capacity need their owners.
Motion challenges/device attestation need agreed protocols; Docker is excluded.
