# M3 integration-contract implementation, 2026-10-28

## Delivered within Module 3

- New `GET /risk/policy`, canonical packaged manifest, policy ID/hash discovery
  in the root and policy headers on successful risk assessments.
- `weighted_signals_v1` preserves existing numerical weights, missing-score
  risk .5, level boundaries and default .50 strict pass rule. The version is a
  description of current M3 rules, not retroactive team approval of every rule.
- Face/liveness risk scores now reject bool/string coercion with 422, retaining
  proper finite JSON numbers (including integer 0/1) and explicit null.
- 45 independently specified synthetic vectors (32 valid, 13 invalid),
  conformance runner for real HTTP and trusted JSON-callable candidate modes.
- Fail-closed release integration: risk conformance runs before transport,
  backend-boundary and existing-sample classification gates.
- Explicit template format metadata in deployment root and enrollment details;
  selected mode, signed template bytes/key/projection, scoring formula, native
  model weights and identity/liveness/risk thresholds are unchanged.
- Component tests distinguish missing input, actual negative decisions and
  unavailable models; a subsequent request can retry after capacity is released.
- Extended actual-M2-client probe with the complete risk corpus and three
  outcome observations. M2 source is executed unchanged, with settings isolated.

Only `module3-face-recognition/` changed. No other modules, shared/public tests,
root files or Docker edits. No new facial data or production keys were generated.
The static PEM vector is public synthetic test material, not a private key.

## Verification

- **305 module-local tests pass**, no skips; 13 known pinned-dependency
  deprecation warnings. Existing model-backed identity expectations remain.
- **15/15 unchanged public face tests in each profile**.
- Local HTTP risk checker: **46/46** (policy discovery + 45 corpus cases).
- Enhanced HTTP risk checker: **46/46**, same risk semantics across profiles.
- JSON-callable M3 reference: **46/46** (identity + 45 corpus cases).
  This is the M3 reference, not a verified M2 fallback candidate.
- Actual M2 FaceClient at
  `7963b06641dc5ed5f3f4f5df8a843b61b068f53c`:
  **28/28 named boundary checks, 12/12 visual HTTP outcome probes, 90/90 risk
  corpus checks (45 per profile)**. These counts overlap test coverage; they are
  not independent face accuracy samples or a full-system test count.
- Real fixed/chunked TCP upload, OTLP privacy/continuity and Collector-failure
  isolation checks pass; this remains a local test receiver, not Module 4.
- Full release wrapper exits 0, including the existing 40 identity/24 PAD
  correlated classification checks. Identity FA 0/16, FR 0/24; PAD attack accepts
  0/16, genuine rejects 0/8. No new general accuracy claim is made.
- Current enhanced smoke/public evaluation completes with 10/10 visual calls per
  endpoint under its local five-second target. This is a small regression run,
  not a repeat of the October 23 long soak or deployment-capacity certification.
- `pip check` passes; syntax, whitespace and Module-3-only staged-scope checks
  are checked before delivery. Model assets/key/logs remain ignored.

During development the new release stage exposed an old mock expecting only
two subprocesses. Its success sequence was updated to the three-stage default;
new cases still ensure risk or classification failures stop the pipeline.
The initial wrapper failure was not treated as successful verification and no
production assertion/biometric expectation was weakened.

Evidence:

- `evaluation/risk-contract.json`
- `evaluation/risk-http-enhanced-20261028.json`
- `evaluation/risk-reference-20261028.json`
- `evaluation/backend-contract-20261028.json` and final `backend-contract.json`
- `evaluation/release-robustness-20261028.json`
- `evaluation/enhanced-smoke-20261028.json`
- `evaluation/transport.json`

## Important pending M2 finding

Three controlled real HTTP probes exercise the actual `assess_risk` method:

| Upstream response | Current M2 method observation |
| --- | --- |
| 503 | None / unavailable |
| Non-JSON 200 | None / unavailable |
| Empty object 200 | Legacy status dictionary, missing risk score |

Thus risk outage and invalid response are not reliably distinguished, unlike
the typed visual methods. These are recorded as pending integration work,
not passed fallback authorization checks. The 90 corpus results only show that
the caller forwards inputs to a correctly behaving M3 endpoint.

M2 must classify/validate risk responses, implement equivalent local scoring
and prove eligible fallback behaviour before enabling it. Merely returning a
matching policy ID/hash is not a proof of implementation equivalence. Shared
tests, review and pinned runtime/classifier behaviour are required. No M2 local
fallback was imported, modified, silently substituted or certified here.

## Still outside this M3-only implementation

- M2 required-image/registered-template gates; liveness disabled vs unavailable.
- M2 503 without check-in insertion and real DB uniqueness/retry/rollback tests.
- M2 fallback implementation/equivalence and source/version audit metadata.
- Team confirmation of deployment template mode and actual failure review/reject.
- Effective course/session thresholds and hard geofence/device/biometric gates.
- Real frontend/auth/DB/attendance/dashboard/Collector integration and deployment.
- Authorized held-out identity/attack data. October 23 projection-sensitivity
  findings remain; small correlated sample success is not security approval.
- Docker remains excluded.

The detailed caller contract and reproduction commands are in
`INTEGRATION-CONTRACT.md`. This closes the currently actionable M3-side
integration-contract work without claiming completion of those external tasks.
