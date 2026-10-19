# Module 3 engineering and integration validation (2026-10-19)

## Summary: engineering PASS, biometric classification release gate FAIL

All changes are restricted to `module3-face-recognition/` on the existing branch.
No Docker, Module 2/frontend/dashboard/root/shared-test changes or merges were
made. No model weights, keys, template format, default profile, thresholds or
risk weights were changed. No new dataset or classmates' face data was obtained.

The standalone API, boundary test tooling, malformed-model failure handling and
handoff work in this phase are complete and reproducible. This does NOT mean
the biometric identity/security objective is complete. The known classification
failures remain explicit release blockers; unavailable independent data and
policy decisions are not fixed by increasing the unit-test count.

## Newly completed work

- Check the actual unmodified Module 2 FaceClient at commit
  `601b3813f481ff05c344cfcddea6b191b9230038` against both local service profiles.
  Only its settings import is stubbed; database/auth/backend app are not loaded.
  The report pins both commit and source checksum, not a copied client rewrite.
- Exercise 28 real service-boundary checks and four real local HTTP fault checks.
  Keep malformed-200 caller behavior as an explicit warning, not biometric success.
- Validate SFace vector dimension, finite values and nonzero finite norm INSIDE
  the model borrow. Malformed output evicts the instance after blank cleanup;
  it is now a 503 service failure, not a 400 student image error or reusable model.
- Reject incomplete/nonfinite Mesh output, redact native RuntimeError/ValueError
  as a 503, and test semaphore release after repeated failures. Empty no-face
  results remain legitimate negative observations. The shipped graph stays 468
  points; diagnostic comparison with the old 478-point graph remains supported.
- Add separate all-success and five-second maximum-latency gates to throughput
  reports. A slow tail, 503, failed decision or timeout cannot hide behind P95.
  Reports use atomic replacement and redact exceptional response bodies.
- Optionally run the actual backend-client boundary check in `release_check.py`
  before classification. Failure stops the command and propagates a nonzero exit.
- Document concrete shared ownership/policy gaps in `MODULE2-INTEGRATION.md`
  without editing another owner's code. A pasteable update is in `TEAM-UPDATE.md`.

## Regression and boundary results

- **128 module-local tests passed**, no skips; three existing dependency
  deprecation warnings. `pip check`: no broken requirements.
- **15/15 unchanged public face tests passed in each profile**: compatibility
  via verify.py; enhanced via the real HTTP throughput runner.
- **28/28 live boundary checks + 4/4 HTTP fault checks passed**. Actual
  client 500/503/timeout become None; 422 is preserved as an error.
- Actual client observation: non-JSON HTTP 200 is considered `is_success=True`
  by status alone. Required-field validation is a backend-owner follow-up, NOT
  a security claim established by the passing boundary tests.

Evidence: `evaluation/backend-contract.json`. The harness runs only loopback
test services and uses a five-second client timeout. No production server,
backend persistence, JWT authorization or final attendance decision is tested.

## Fresh local throughput observations

`evaluation/throughput-20261019.json` runs 10/50/100 clients three times for each
endpoint in enhanced mode. All **480/480 requests per endpoint** returned the
expected positive 200 result within five seconds, with no health failures.

| Endpoint / 100 clients | P95, three rounds (seconds) | Maximum, three rounds (seconds) |
| --- | --- | --- |
| Verify | 1.687 / 1.625 / 1.593 | 1.750 / 1.766 / 1.703 |
| Liveness | 2.578 / 3.360 / 3.250 | 2.719 / 3.469 / 3.390 |

The new functional and local latency gates both passed for THIS run. Like prior
comparison runs, it explicitly uses **128 waiters / 30-second queue**; runtime
defaults remain eight active / 32 waiters / two seconds. This is not a promise
that the default service will process 100 simultaneous calls successfully.

`evaluation/thread-baseline-20261019.json` records the preceding two-round
baseline: 100-client liveness P95 3.172/2.907 seconds. No new threading/model
optimization was shipped in this phase. Do not attribute the lower timings
versus October 18 to the new safety guards: host/load variation was not controlled.
The October 18 five-second failures are preserved, not superseded as if they had
never happened. Capacity needs deployment-host/arrival-rate validation; a few
passing local runs do not establish a universal latency SLA.

## Default-policy stability, restart and overload recovery

Both fresh acceptance reports reached `state=complete`, `passed=true`, with
four callers per sustained wave, two restart workflows each, zero health
failures, valid overload errors and successful post-overload normal requests.
The unchanged 128 MiB budget passed for both final and windowed RSS growth.

| Observation | SHA-256 compatibility | Enhanced |
| --- | --- | --- |
| Sustained duration | 60.015 s | 120.218 s |
| Successful verify calls | 1552 / 1552 | 1728 / 1728 |
| Successful liveness calls | 1552 / 1552 | 1728 / 1728 |
| Maximum verify / liveness | 0.094 / 0.110 s | 0.157 / 0.312 s |
| End-minus-initial RSS | +29.059 MiB | +47.816 MiB |
| Windowed RSS growth | +26.481 MiB | +26.095 MiB |
| 100-request verify burst, success / 503 | 77 / 23 | 50 / 50 |
| 100-request liveness burst, success / 503 | 50 / 50 | 47 / 53 |

Evidence: `evaluation/acceptance-sha256-20261019.json` and
`evaluation/acceptance-enhanced-20261019.json`. The profiles ran sequentially;
a small harness unit-test run overlapped part of enhanced acceptance. These are
finite stability checks, not isolated performance measurements, indefinite leak
proof or a replacement for the older five-/ten-minute records. 503 responses
were rejected inference, NEVER successful biometric processing.

## Classification gate is still BLOCKED

The complete command

```powershell
python scripts/release_check.py --backend-ref origin/module2-backend --report evaluation/robustness-20261019.json
```

passed regression/public checks and backend-client checks, then correctly
stopped at `evaluate_robustness.py` with child status **2**. All HTTP calls
completed, but classification was not correct for all existing conditions:

| Correlated demo comparisons | Errors / comparisons |
| --- | --- |
| Wrong-person accepted | 5 / 16 |
| Genuine identity rejected | 0 / 24 |
| Attack accepted as live | 2 / 16 |
| Bona-fide presentation rejected | 7 / 8 |

These are the same counterexamples as October 18. The tiny corpus has only two
identities and three original PAD demos with eight correlated transformations;
the counts are NOT independent population FAR/FRR/APCER/BPCER estimates. No
threshold was fitted to them. Existing comparison evidence shows the original
attention mesh also gave these PAD decisions.

The user confirmed there is no authorized labeled local corpus. Existing data
validation is complete; secure operating-point calibration and general accuracy
validation remain unavailable. Do not call the enhanced mode production-ready
or use its engineering test results as automatic-attendance authorization.

## Remaining external/shared work

1. Agree default SHA-256-only storage versus similarity-preserving template
   policy, migration/re-enrollment, private-key custody and the secure operating
   point. Default exact-image mode does not meet cross-photo identity matching.
2. Obtain a legitimate, diverse, labeled held-out corpus and validate identity/PAD
   beyond the existing examples before approving the biometric security gate.
3. Align Module 2's actual risk aggregation, missing/failed evidence behavior and
   invalid-response validation. It currently does not call `/risk/assess` in its
   check-in flow. These are not solved by Module 3's endpoint being available.
4. Validate actual capture, JWT/consent, DB storage, check-in decisions and
   dashboard/monitoring together with their owners; agree host capacity and
   overload/retry policy. Local harnesses do not replace end-to-end validation.
5. Active random challenges and signed device trust need agreed multi-frame and
   server-challenge protocols. Single-image endpoints do not fake those claims.
   Docker remains explicitly excluded, not silently marked as completed.
