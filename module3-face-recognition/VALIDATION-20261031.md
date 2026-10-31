# M3 integration update against M2 f1dfd77, 2026-10-31

## Changes

M2 now returns typed `FaceCall` risk data and intentionally omits
`risk_threshold`. The Module 3 boundary harness compares every retained
client field to the matching raw M3 response, and checks the complete raw M3
response—including the .50 threshold—against the existing 45 golden cases.
For each case it makes one request through the real unchanged M2 client and a
separate direct request with the same synthetic input. No threshold is invented
from an expected value, and legacy client-returned thresholds are still checked.

Added regression coverage for missing typed fields and mismatched score, level,
pass flag, contributions and threshold. The controlled M2 HTTP fault server
also sends three synthetic but structurally valid inconsistent risk responses
and records whether the M2 client accepts them. It does not alter M2 code or
make attendance decisions.

Only Module 3 files changed. The risk engine, face/template code, policy,
weights and thresholds were not changed. No new faces were collected. No Docker,
M2, shared test, database or project-root files were modified.

## Verification

M2 source target: `f1dfd77e1744d5f0c6f31066d0c2e658b259dd5b`.

- 310 module-local tests passed, no skips; 13 dependency deprecation warnings.
- The unchanged public face tests passed 15/15 in each profile.
- The unchanged real M2 client passed 14/14 named boundary checks in each
  profile, 12/12 visual HTTP outcome checks and all 45/45 risk cases per profile.
  Raw M3 threshold and each field retained by M2 were both checked.
- Risk reference corpus: 46/46 checks including policy identity.
- Full release wrapper passed: local regressions, public SHA tests, risk corpus,
  TCP upload/OTLP transport checks, M2 client boundary and existing correlated
  face/PAD classification gate. Reports:
  `evaluation/backend-contract.json`,
  `evaluation/backend-contract-sha256-20261031.json` and
  `evaluation/release-robustness-20261031.json`.
- Enhanced smoke/public run: `evaluation/enhanced-smoke-20261031.json`.
  The two other photos of the enrolled public sample matched, and the different
  person was rejected. Publisher PAD demos produced the expected two attack
  rejections and one genuine pass. Existing repository photo also returned
  liveness_passed=true, score .998836 in a separate local check.

The historical local runtime and test key were absent from their old temporary
path. This run used freshly verified pinned public models and **one fixed,
public, non-production test-only key** in the ignored models directory.
This key did not replace a deployment key and must not be used for a real
deployment. The result does not prove compatibility with templates created
using the missing prior key or with a different demo key.
After verification this temporary checkout's test key is retained only as the
ignored `models/template.test-only.key`, so it is not automatically loaded as
a deployment key.

The corrected existing-sample gate reports identity false accepts 0/16, false
rejects 0/24; PAD attack accepts 0/16, genuine rejects 0/8. These are correlated
transformations of two identities/three publisher demos. In the separate
enhanced smoke run the different-person score was **.697629**, close to the .70
threshold. The score is key-dependent normalized agreement, not a calibrated
probability; neither this small sample nor the test key certifies accuracy.
Do not select/re-generate deployment keys to optimize these demo comparisons.

## Current M2 observations and joint work

The real M2 risk client now distinguishes 503 from non-JSON 200 and rejects an
empty 200. It still accepted all three controlled, internally inconsistent risk
responses: wrong contribution sum, wrong pass flag and wrong level. Results
are recorded as pending in `evaluation/backend-contract.json`. This is a
boundary diagnostic, not a change to M2. Its current code uses the M3 risk
result as advisory and its own local risk score for final status.

Before using M3's score for attendance, the team still needs agreement on the
signal mapping, thresholds and hard biometric/geofence/device rules, and M2
needs to validate consistency and implement any approved equivalent fallback.
The current image-less required-liveness exception remains in M2. M2 source and
tests describe 503 without a check-in row for required M3 outages and a
flagged failed face match; these DB/transaction tests were not independently
rerun here.

The teammate reported an isolated Docker M2/M3 E2E pass; no Docker, backend
database, frontend, dashboard or real camera test was run in this M3 phase.
Demo enhanced mode requires verified models, a securely retained deployment
key, fresh enrollments after changing from SHA mode and an actual E2E rerun.
`course_instructors` schema/active TA assignment verification belongs to the
integration DB owners. See `MODULE2-INTEGRATION.md` for the boundary details.
