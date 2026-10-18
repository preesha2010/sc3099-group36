# Module 3 independent validation, 2026-10-18

## Release status: biometric classification gate FAILED

This is an engineering/test branch, not a production security certification.
Operational readiness and public-suite scores do not override the following
observed classification failures. Do not use it to auto-approve attendance
without resolving the policy and conducting independent accuracy validation.

All work stays within Module 3; no Docker, other-module code, backend timeouts,
thresholds, risk weights, key format or default SHA-256 policy was changed.

## Expanded condition diagnostics

`evaluation/robustness-20261018.json` uses existing repo photos (two identities)
and three pinned publisher PAD demos. Eight conditions make 40 identity and 24
PAD comparisons; they are correlated transformations, not new subjects/attacks.

| Diagnostic count at unchanged thresholds | Observed |
| --- | --- |
| Wrong-person acceptances | 5 / 16 impostor comparisons |
| Genuine-person rejections | 0 / 24 genuine comparisons |
| Attack presentations accepted | 2 / 16 attack presentations |
| Bona-fide presentations rejected | 7 / 8 presentations |

The original condition already contains a wrong-person acceptance in the
expanded pairing set; the old smoke suite did not cover that pairing. Attack
acceptances occur under JPEG compression and resize. Poor-quality genuine
inputs are often rejected by the deliberate quality gate. These observations
are useful counterexamples, NOT general FAR/FRR/APCER/BPCER estimates.

The report records both HTTP completion and the separate failed classification
gate. Threshold sweeps are for inspection; fitting a threshold to these same
two people would not establish security. No such runtime tuning was performed.

The separate `mesh-comparison-20261018.json` audit ran all 24 PAD conditions
through both the original attention/478-point implementation and the retained
468-point static-config implementation. All 24 decisions AND final liveness
scores agreed. Thus these particular PAD counterexamples were also present in
the original implementation; they were not introduced by this optimization.
This is a small-sample regression comparison, not a general equivalence proof.

## Completed regression and finite stability checks

- Module regression: **106 passed**, no skipped tests; three dependency
  deprecation warnings remain. `pip check` reports no broken requirements.
- Unchanged public HTTP suite: **15/15** in compatibility and enhanced modes.
- Canonical graph vs stock 468-point graph: all coordinates agree at 1e-7
  tolerance on four repo photos; blank follow-up images return no landmarks.
- Fault checks include closure on graph start/process failure, invalid PAD
  probabilities/logits, invalid config/native paths, slow rebuild isolation,
  cancelled admission and atomic checkpoint failure without losing prior data.

| Default admission policy, four clients per wave | SHA-256 compatibility | Enhanced |
| --- | --- | --- |
| Continuous workload duration | 300.078 s | 600.562 s |
| Successful verification calls | 3292 / 3292 | 3676 / 3676 |
| Successful liveness calls | 3292 / 3292 | 3676 / 3676 |
| Maximum verify/liveness latency | 0.250 / 1.328 s | 0.531 / 1.703 s |
| Health failures | 0 | 0 |
| Restart workflows | 3 passed | 3 passed |
| End-minus-initial RSS | +19.266 MiB | +57.625 MiB |
| Early/late window RSS growth | +27.215 MiB | +32.591 MiB |

The five-minute SHA-256 run overlapped the first part of the ten-minute enhanced
run on this host; limited extra diagnostics also ran concurrently. These are
contention/stability observations, not isolated latency benchmarks. Both stayed
within the unchanged 128 MiB growth budget and recovered after overload. They
do not prove indefinite leak freedom, adversarial maximum-image capacity or
cross-host performance.

Enhanced 100-request overload bursts returned 48 successful/52 rejected verify
calls and 38 successful/62 rejected liveness calls. Rejections were 503 with
Retry-After, not successful inference. Subsequent normal calls and readiness
checks passed. Full aggregate evidence is in `soak-*-20261018.json`.

## Performance experiments

Each experiment used four model slots unless stated otherwise, original model
weights, default 0.70/0.60 thresholds and explicit all-success throughput queue
settings (128 waiters / 30 seconds). These local sequential runs are not a
controlled laboratory benchmark; host contention and run-to-run variation were
not eliminated. Larger thread counts are not presumed faster.

| Experiment report | 100-client liveness P95, seconds | Decision |
| --- | --- | --- |
| baseline-20261018.json | 5.829, 5.438 | Same-environment baseline |
| mesh468-native1-20261018.json | 5.828, 5.156, 5.500 | Standard 468-point mesh retained |
| mesh468-native2-20261018.json | 5.532, 5.484, 5.032 | No reliable five-second result |
| mesh468-native4-20261018.json | 5.515, 5.703, 5.610 | Default remains one native thread |
| mesh512-native1-20261018.json | 5.688, 5.297, 6.078 | Mesh downscale experiment reverted |
| onnxruntime-native1-20261018.json | 5.906, 5.718, 5.844 | Temporary engine experiment rejected/uninstalled |
| concurrency16-20261018.json | 3.859, 5.500, 6.015 | Default whole-pipeline concurrency remains eight |
| static-mesh-20261018.json | 5.094, 4.938, 5.016 | Static-config cache retained; per-image graphs still closed |
| static-mesh-native2-20261018.json | 5.157, 5.828, 5.453 | Default remains one native thread |

Historical experiment reports are retained even when the experimental source
option was rejected. ONNX Runtime was a temporary standalone investigation, not
a supported/shipped service backend or new project dependency. Its public smoke
decisions agreed, but this was not a complete numerical-equivalence certification.

The final static-config approach improves this measurement but still does NOT
provide a reliable universal five-second guarantee for 100 simultaneous full
inferences. Explicit 503 overload rejection is not successful processing.
Evaluate the actual host/resources and required arrival rate before agreeing
deployment capacity. Do not increase the backend timeout here to conceal this.

The final independent 10/50/100-client rerun is recorded in
`final-throughput-20261018.json`. All 320 requests per endpoint completed with
200 in that relaxed-queue experiment, with no health failures:

| Endpoint / simultaneous clients | First P95 | Second P95 |
| --- | --- | --- |
| Verify / 50 | 1.360 s | 1.296 s |
| Verify / 100 | 2.406 s | 3.391 s |
| Liveness / 50 | 2.516 s | 3.187 s |
| Liveness / 100 | 5.094 s | 5.235 s |

Thus 50-client runs met the observed five-second target; 100-client liveness
still did not reliably meet it. Maximum 100-client liveness latencies were
5.390/5.360 seconds. No claim is made that every possible 50-client workload or
deployment will meet this target.

`python scripts/release_check.py` runs regression/public checks and then the
classification gate, stopping and propagating any nonzero exit. The final run
passed 106 tests and the compatibility public suite, then correctly BLOCKED at
the robustness gate (child status 2). The separately run enhanced public suite
also passed 15/15. This overall failed release result is intentional evidence,
not an issue hidden by the successful operational acceptance runs.

## Environment/provenance

The former temporary checkout/runtime was incomplete locally. A fresh copy of
the existing `module3-face-recognition` branch was recovered from GitHub without
overwriting the old partial files. Packages were installed from the module's
requirements into an isolated Python 3.12.10 environment; pinned model assets
were re-verified and PAD re-exported using the documented CPU Torch 2.5.1 tools.

Chinese-path Windows native resource/model reads failed during initial setup.
The newly created working copy and test environments were relocated to ASCII
paths, after which the tests passed. New startup checks explain this constraint.
This was not fixed by changing model weights or disabling tests.

The fresh checkout creates a new ignored **test** template key; no enrolled-user
database exists in these standalone checks. Old and new cross-photo scores are
therefore not directly interchangeable. No production key was restored,
overwritten, uploaded or committed. Preserve the real deployment key separately.

## What remains external or unverified

- A legitimate, diverse, labeled corpus and subject-disjoint calibration/test
  design are needed to choose/validate a secure operating point or replacement
  model. No classmates' faces were collected and no new data permission inferred.
- Resolve SHA-256-only storage versus similarity-preserving templates jointly.
  The default exact-image compatibility mode does not solve cross-photo identity.
- Real camera capture, backend persistence/decision logic and dashboard monitoring
  still require the other module owners. Module 3 test callers do not own them.
- Fleet/host capacity, Docker, long-duration production load and key custody are
  not certified by local smoke, throughput or finite soak runs.
