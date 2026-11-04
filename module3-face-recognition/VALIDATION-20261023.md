# Module 3 standalone closure and score repair, 2026-10-23

## Outcome and scope

The bounded standalone engineering checklist is complete with the available
assets and samples: regression, both public profiles, local classification,
latest Module 2 client boundary, transport/privacy, restart and finite stress
checks pass. This is NOT a production biometric/security certificate or proof
that all full-project requirements are complete. No authorized held-out corpus
is available; real-camera accuracy and joint system policy remain unapproved.

Only `module3-face-recognition/` changed, on the existing branch of that name.
Docker, other modules, root files and shared/public tests were not modified.
The user explicitly authorized scoring changes and required full false-accept
and false-reject reporting. No new people/data were collected. The same existing
private key, 64-plane projection, signed template bytes and model weights remain;
identity .70, liveness .60 and risk .50 numeric thresholds remain unchanged.
Default SHA-256 exact-normalized-image behavior is unchanged, NOT cross-photo
identity recognition. Enhanced mode remains opt-in.

## Score investigation: every candidate, not just the favorable result

The same two repository identities and eight correlated image conditions were
used for all comparisons: 16 impostor and 24 genuine comparisons. Their labels
were inspected during development, so this is regression/development evidence,
NOT blind held-out evaluation, even though the formulas use fixed analytic
coefficients and no threshold/key/weight optimization.
Eight of the 24 genuine comparisons derive from the second person's enrollment
image itself; they are not separate cross-photo captures. The remaining 16
repeat two other photos of the first person across the eight conditions.

| Fixed method, score threshold .70 | False accepts / 16 | False rejects / 24 | Status |
| --- | --- | --- | --- |
| Historical rescaled Hamming cosine | 5 | 0 | Replaced |
| Direct clipped Hamming cosine | 0 | 14 | Rejected, not live |
| Raw-vector clipped cosine | 0 | 2 | Diagnostic only; no reference vectors stored |
| Raw-vector normalized agreement | 0 | 0 | Diagnostic only; no reference vectors stored |
| Direct clipped query-margin estimate | 0 | 16 | Rejected, not live |
| Query-margin normalized agreement | 0 | 0 | Current enhanced scorer |

Evidence: `evaluation/scoring-comparison-20261023.json`. The rejected direct
Hamming-cosine HTTP experiment is retained in
`evaluation/robustness-cosine-20261023.json` with its failed gate. Merely removing
the affine mapping does eliminate these false accepts, but at an unacceptable
14/24 genuine rejects; that candidate was not presented as a completed fix.
Historical failed reports remain in Git and the October 20 report is explicitly
marked superseded, not rewritten to claim it originally passed.

### Current formula and its actual meaning

Policy: `gaussian_query_margin_agreement_v3`, exposed by `GET /` in
`match_score_policy`. The signed template still carries 64 reference sign bits,
not a reference embedding. Let unit query be u, unit reference be v, existing
standard Gaussian projection rows be a_i, and template signs be s_i=sign(a_i.v).
The Gaussian moment identity is:

```text
E[sign(a.v) * (a.u)] = sqrt(2/pi) * dot(u,v)
estimated_cosine = sqrt(pi/2) * mean(s_i * (a_i.u))
score = round(clip((1 + estimated_cosine)/2, 0, 1), 6)
match_passed = score >= 0.70
```

Only transient query features/margins are used. This removes the second
quantization of the query instead of comparing two 64-bit sign strings. No
reference-vector recovery/storage or new random projections are required.
Invalid features or nonfinite output fail 503; a hash-only fallback is explicitly
disabled in SimHash mode. SHA-256 still uses exact digest comparison.

**Important semantic limit:** this remains normalized agreement, NOT raw cosine
.70. Its estimated cosine operating point is .40 (up to output rounding).
The mapping is explicit and preserves the previous normalized-agreement API
scale, not a claim that the documents mandate that mapping or this estimator.
It is a user-authorized scoring extension, not the lecture's literal Hamming
cutoff pseudocode or a calibrated probability. If the team requires raw cosine
.70 or a strict Hamming cutoff, select that policy explicitly and validate its
false rejects; do not silently reinterpret the current result.

For 64 independent Gaussian planes the unclipped cosine estimator has variance
`(pi/2 - cosine^2)/64`. Synthetic, non-biometric tests check the moment and
variance at five fixed cosines; exact-formula, scale, template-authentication,
invalid-feature and no-fallback regressions also pass. This verifies algebra
and code, not face accuracy at a particular deployment operating point.

### Key/projection sensitivity remains real

The scoring comparison also repeats the SAME people/conditions across the
fixed public toy seeds 0..31. No toy key/projection was installed or chosen:

| 32 toy projections, repeated comparisons | False accepts / 512 | False rejects / 768 |
| --- | --- | --- |
| Historical rescaled Hamming | 69 | 2 |
| New query-margin normalized agreement | 47 | 0 |

This is evidence that the new method is still projection-sensitive, NOT 1,280
independent biometric trials or a population error-rate claim. Zero errors on
the unchanged current local key do not guarantee zero errors on other keys or
people. Deployment still needs authorized independent data and operating-point
approval. No favorable key/seed was selected and no key was regenerated.

### Existing-sample HTTP classification gate

`evaluation/robustness-margin-20261023.json` and the final complete-pipeline
`evaluation/release-robustness-20261023.json` record:

| Current correlated cases | Errors / comparisons |
| --- | --- |
| Identity false acceptance | 0 / 16 |
| Identity false rejection | 0 / 24 |
| Attack accepted as live | 0 / 16 |
| Bona-fide presentation rejected | 0 / 8 |

All eight conditions complete their HTTP checks and local classification gate.
PAD still uses only the three pinned publisher demos, with EXIF-safe transform
version 2. No new real-camera/attack validation was added by transformations.
Reported binomial intervals do not remove this dependence/small-sample limit.
`evaluation/classification-diagnosis-20261023.json` checks equivalent raw
agreement and PAD layer reconstruction; its explicitly historical Hamming error
metric is NOT the new live scorer's approximation error.

### Compatibility, privacy and rollout

The encoding/version/key ID/HMAC/projection derivation are unchanged. Existing
signed SimHash templates can be verified without re-enrollment for this
score-only change. Keep the same assets/key, drain traffic and restart all
instances consistently; do NOT mix old/new scorer versions. Decisions and risk
inputs change even though the template string and numeric threshold do not.
Profile/key/model changes still require their own migration/re-enrollment plan.

Continuous margins reveal finer similarity information than the former 65-level
Hamming score. This does not improve anonymity or prove inversion resistance.
Keep the unauthenticated internal service behind authenticated, rate-controlled
callers and trusted network access. No adaptive score-oracle security claim is
made. Images/vectors/margins are transient; reports contain aggregate counts
(the existing throughput demo report also contains public sample scores), never
private keys, enrollment templates or stored floating-point reference vectors.

## Runtime safety and latest Module 2 contract

Previously `/ready` detected changed assets/config, but visual admission could
still proceed. New visual requests now check runtime consistency both BEFORE
admission and AFTER acquiring a queued slot, before buffering the image body.
A changed observed asset fingerprint/key/config returns redacted 503. Tests
verify no decode/body read and no capacity leak. Existing active inference is
not cancelled; operators must still drain traffic before changes. File stat
checks are not protection against a malicious local administrator. Degraded
pool recovery still permits healthy remaining capacity; no silent model downgrade.

Read-only latest Module 2 target:
`7963b06641dc5ed5f3f4f5df8a843b61b068f53c`.
The real unmodified FaceClient now returns typed FaceCall outcomes for the
visual methods. The harness registers an isolated source module for dataclasses,
stubs only settings and adapts observations, NOT the upstream method behavior.
It passes **28 live boundary checks plus 12 real-HTTP outcome/fault checks**.
Non-JSON/missing/invalid boolean/score/hash data are rejected; the earlier
malformed-response warning is resolved in that revision. Valid negative is
transport success, not attendance permission. No full backend/DB/JWT app was run.

One repeat during parallel host load failed a normal malformed-score probe:
the client returned unavailable instead of the expected HTTP-200/malformed
outcome. All 28 live boundary checks still passed. The full failed report is
retained as `evaluation/backend-contract-contention-20261023.json`; the wrapper
correctly stopped with exit 1. Initial suspicion was the one-second diagnostic
timeout. Normal probes were aligned with the actual five-second caller budget,
but a repeat still failed (`backend-contract-five-second-failure-20261023.json`).
Thus a shorter budget alone did NOT explain it.

The controlled fault server replied/closed WITHOUT consuming the POST body.
On Windows this can reset TCP and hide the response. It now drains the bounded
synthetic request before replying and records body consumption, HTTP status and
timeout in every probe. The intentional timeout still waits .03 seconds against
a delayed server; consumption must be observed even for that case. Normal probes
use the actual five seconds. Assertions are not weakened and no retry is added.
This repairs the test server, NOT Module 2 or the production Module 3 service.
Ten consecutive real-client fault runs (120 probes) then completed without a
failed probe. The final full wrapper also checks exact 5xx status for typed
FaceCall results; only the historical None-returning client has the legacy
status-loss allowance.

Backend check-in still uses its own risk calculator, not `/risk/assess`. Missing
face/liveness signals can remain None while the risk calculator starts their
contribution at zero; face false alone is weighted rather than critical reject.
Those are joint policy decisions, not fixed by this Module 3-only branch.
See `MODULE2-INTEGRATION.md` for all eight joint integration/operations areas.

## Verification and operational measurements

- **181 module-local tests pass**, no skips, 13 pinned-dependency deprecation
  warnings. Existing six real neural identity sample cases were not weakened.
- **15/15 unchanged public face tests pass in EACH profile.**
- `release_check.py --transport --backend-ref <pinned revision>` now exits 0:
  regression/public, real TCP upload/OTLP privacy, client boundary and the local
  existing-sample classification gate all pass. No child failure was swallowed.
- `pip check` reports no broken requirements; diff whitespace/scope checks pass.
- Optional tracing remains disabled in all loads. The transport probe enables
  its own loopback receiver to verify delivery/continuity/allowlisted data and
  failed-Collector isolation; this is not the real Module 4 Collector.

### Ten-minute enhanced stability and three restarts

`evaluation/soak-enhanced-20261023.json`: **600.187 seconds**, four clients per
wave, three successful restart workflows. EACH visual endpoint completed
**5,480/5,480** sustained requests, zero health failures. Maximum verify/live
latencies: .453/.750 seconds. End RSS growth 23.484 MiB, window growth 29.066 MiB,
within the unchanged 128 MiB budget. Post-overload work/readiness recover.

The default-policy 100-client burst processed 50/rejected 50 verify requests and
32/rejected 68 liveness requests. Rejections are 503, not successful inference.
They demonstrate bounded admission/recovery, not universal 100-client success.
The soak overlapped diagnostics, mixed stress and throughput on the same host;
it is finite contention evidence, not an isolated benchmark or leak-freedom proof.
The current SHA-256 profile also has a separate finite restart/soak report:
`evaluation/soak-sha256-20261023.json`.
It passes three restarts and 60.360 seconds, 564/564 calls per endpoint with zero
health failures. Max verify/live .204/.375 seconds; end/window RSS growth
11.082/9.807 MiB within budget. Its default burst processes/rejects 72/28 verify
and 49/51 liveness requests, then recovers.

### Maximum-image mixed boundary stress

`evaluation/boundaries-20261023.json`: eight clients, **120.156 seconds**,
**1,968/1,968** valid measured responses. All eight input cases occur on BOTH
endpoints, 123 calls per case per endpoint. Real normal/12MP face cases require
detection and template output; a no-face 200 cannot pass them. Also covers 12MP
blank, oversized pixels/side/base64, undersized/corrupt image and oversized
declared body. Totals: 738 expected 200s, 492 expected 400s, 738 expected 413s.
Zero health failures; max request 1.156 seconds, readiness recovers. Both RSS
growth checks pass after case/concurrency warmup; this is not a cold-start RAM
limit, identity-accuracy measurement or indefinite memory guarantee.

### Repeated relaxed-queue throughput

`evaluation/throughput-20261023.json`: 10/50/100 clients twice, **320/320**
successful requests per endpoint, all within the local five-second target,
no health failures. 100-client verify P95: 2.407/2.765 seconds; liveness P95:
4.609/4.625 seconds. Worst liveness request: 4.750 seconds.
This explicitly uses 128 waiters/30-second queue, NOT default 32/two seconds.
It overlapped other host work; no deployment resource or universal SLA claim.

## Reproduction and remaining boundary

```powershell
python scripts/release_check.py --transport --backend-ref 7963b06641dc5ed5f3f4f5df8a843b61b068f53c --report evaluation/release-robustness-20261023.json
python scripts/compare_scoring.py --report evaluation/scoring-comparison-20261023.json
python scripts/diagnose_classification.py --report evaluation/classification-diagnosis-20261023.json
python scripts/acceptance.py --profile enhanced --soak-seconds 600 --restarts 3
python scripts/acceptance.py --profile sha256 --soak-seconds 60 --restarts 3
python scripts/stress_boundaries.py --clients 8 --seconds 120
python scripts/evaluate.py --clients 10 50 100 --repeat 2
```

Requires pinned dependencies/assets and existing repository photos; publisher
PAD demos are checked by pinned checksums. Model assets/key are deliberately
not in Git. Exact key-dependent numbers require the same securely retained
local test key, not a newly bootstrapped or favorably selected replacement.

`STANDALONE-COMPLETION.md` inventories the completed in-scope engineering work
and the external input for each remaining deliverable. Remaining work is real:
authorized held-out data/targets, team template/scorer/risk/failure policy,
actual camera/auth/DB/attendance/dashboard flow, active/device protocols, trusted
network/Collector/key operations and deployed sustained capacity. No other module
was patched to make the boundary pass, and Docker remains explicitly excluded.
