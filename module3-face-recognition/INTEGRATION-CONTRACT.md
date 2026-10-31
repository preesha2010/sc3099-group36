# M2/M3 integration contract, 2026-10-28

**2026-10-31 update:** M2 revision `f1dfd77` now returns typed risk outcomes;
its client removes `risk_threshold`, so the M3 boundary checker validates
the full raw M3 response separately from the retained client fields. The old
`7963b06` risk-client observations later in this document are historical.
Current M2 still treats M3 risk as advisory and accepts some contradictory
synthetic score/level/pass/breakdown responses. Required-liveness image-less
behaviour and real enhanced-mode E2E remain open. See `VALIDATION-20261031.md`.

This records the recent team discussion and the M3-side implementation. It is
not a claim that M2 has implemented these rules, that a local fallback is already
equivalent, or that the remaining template/review choices have been approved.
Scope is Module 3 only; no database, other-module or Docker changes.

## Ownership and request outcomes

| Scenario | M3 behaviour / available contract | M2 responsibility |
| --- | --- | --- |
| Required liveness, missing check-in image | A requested `/liveness/check` without challenge_response returns 422 | Enforce session.require_liveness_check before calling M3; reject missing image with a clear validation error |
| Liveness disabled, no image | No liveness operation needs to be requested | Allow the image-less path according to course/session rules; distinguish disabled from unavailable |
| Valid visual request, no face/negative decision | 200, passed=false, score=0 for no face | Apply the final failure/review policy; HTTP success alone cannot approve attendance |
| Bad/corrupt image or invalid request | 400/422 (413 for size limits) | Correct input; do not turn validation failures into scoring fallback |
| Visual models unavailable/overload | Redacted 503; no successful biometric evidence | When required, return retryable 503 without inserting a check-in; preserve ability to retry |
| Only risk endpoint unavailable after successful biometric verification | No successful remote risk result | Local fallback is conditional on equivalent rules/version and validated required evidence |
| Risk endpoint malformed/incomplete output | Invalid remote evidence, not a valid low score | Classify separately; do not silently treat every None as an eligible outage |
| Risk output passes .50 | Numerical indicator only; no attendance status returned | Apply actual course/session threshold plus hard requirements and critical signals |

The exact outward M2 validation status and review-vs-reject rule for a genuine
failed match still need team confirmation. The decision for required biometric
outages is retryable 503 with **no check-in insertion**, not a flagged record
that consumes the student's unique session/student check-in slot.

M3 has no attendance database. Its recovery tests prove the next visual request
can run after a model error and admission is released. They do NOT prove M2
transaction rollback, uniqueness, duplicate handling or UI retry behaviour.
M2 needs integration tests for those using its actual database/application.

Existing public tests allowing image-less check-ins with liveness explicitly
required conflict with that rule. Keep the conflict visible; do not silently
bypass the requirement or modify shared fixtures from this branch.

## Versioned risk semantics

`GET /risk/policy` returns:

- `policy_id`: `weighted_signals_v1`.
- `policy_sha256`: SHA-256 of sorted compact UTF-8 JSON of its `manifest`.
- `manifest`: current weights, missing-input semantics, classifiers, boundaries,
  arithmetic, comparison tolerance and limitations.

`GET /` also advertises the risk policy ID/hash. Successful `POST /risk/assess`
responses add `X-Risk-Policy-ID` and `X-Risk-Policy-SHA256` headers. Its required
JSON response fields and default threshold remain unchanged. This is an additive
discovery contract, not authentication or proof of implementation equivalence.
Changing an advertised manifest requires a new reviewed contract/hash; pin the
deployment version before an outage rather than discovering it only afterward.

The canonical definition is packaged inside `app/contracts/risk-v1.json`.
The existing weights (.25/.25/.20/.15/.15), .30/.50/.70 risk levels and strict
`risk_score < .50` default pass rule are unchanged. Missing/null biometric risk
remains .5 per raw signal, not zero. Decimal arithmetic and weighted breakdown
sum semantics are preserved. Face/liveness request scores now require actual
finite JSON numbers: booleans/numeric strings return 422 instead of coercing to
numbers. Integer 0/1 and ordinary fractional numbers remain valid.

This publishes the current M3 baseline; it does NOT assert team approval of all
existing heuristics. In particular:

- A private IP/client keyword is only a heuristic, not VPN detection proof.
- Device key/signature fields lack a signed challenge, so even parseable evidence
  is unverified. M2 retains actual device-binding/challenge checks.
- Geolocation here measures accuracy/validity, not distance to the course venue.
  M2 retains venue-distance/geofence checks.
- The current request schema has no disabled/unavailable state flags. Passing
  null means missing/uncertain input, not authenticated success or zero risk.
  Any future reweighting/disabled-signal extension needs a shared policy update.
- One golden case has failed face score 0, total risk .35 and pass=true. This is
  intentional evidence that M2 MUST enforce required biometric results separately.
- M3's default .50 threshold does not override course/session-specific thresholds.
  M2 must compare the score to its effective threshold and apply hard gates.

## Shared corpus and conformance tool

`contracts/risk-v1-cases.json` has **45 synthetic cases**: 32 valid expected
responses and 13 input rejections. Expected values are independently specified
constants, never generated from the production engine. No faces, identities,
templates or private keys are used. The PEM fixture is a public test key only.

Coverage includes omitted/null signals, failed-face/low-total distinction,
boundaries just below/at/above .30/.50/.70, geolocation accuracy cutoffs,
IPv4/IPv6/invalid IP/keyword handling, unverified/malformed device inputs and
invalid score types/ranges. These are numerical/API cases, not biometric trials.

Run inside Module 3 with its existing dependencies:

```powershell
# Own local HTTP process; no backend/database/private template key required.
python scripts/check_risk_contract.py --report evaluation/risk-contract.json

# Same HTTP contract on the explicitly opted-in enhanced profile.
python scripts/check_risk_contract.py --profile enhanced

# Reference JSON-callable mode, same implementation/schema as the HTTP endpoint.
python scripts/check_risk_contract.py --candidate app.risk_policy:assess_payload

# Explicit stateless test service, using synthetic inputs only.
python scripts/check_risk_contract.py --base-url http://127.0.0.1:8001
```

For a future M2 fallback, M2 supplies a trusted importable callable accepting a
raw JSON dictionary and returning the five semantic fields in the manifest.
Invalid input must raise ValueError (including Pydantic ValidationError).
Its module declares `RISK_POLICY_ID` and `RISK_POLICY_SHA256`. Run the checker
in that candidate's dependency environment, with its own import root:

```text
python <module3>/scripts/check_risk_contract.py --candidate-root <module2> --candidate <actual.module>:<actual_function>
```

Those placeholders are an adapter contract, not an existing M2 function claim.
The checker executes trusted candidate code; it is not a sandbox. It does not
replace/patch the candidate with M3's implementation. Avoid importing both
projects' different `app` packages into the same long-lived Python process.

Checks reject wrong advertised policy/hash, bool-as-number, nonfinite/out-of-range
results, different score/level/threshold/decision, missing/extra contributions
and inconsistent contribution sums. Numeric tolerance is 1e-9. Reports retain
fixed case IDs and failure types, not payloads/response bodies/exception text.
Any failure produces exit 1; the release wrapper propagates failures.

Passing a finite corpus is necessary evidence, not a mathematical proof of
fallback equivalence or runtime authorization. Review the implementation,
deployed policy/version, input trust and missing-state handling as well.
No automatic fallback is enabled anywhere in M3 by this change.

## Actual M2 boundary and remaining work

The unchanged M2 client at `7963b06641dc5ed5f3f4f5df8a843b61b068f53c` forwards
all 45 risk cases correctly to M3 in each profile. This tests HTTP forwarding,
NOT its existing local risk calculator.

Additional real HTTP observations find that `FaceClient.assess_risk` still
returns None for both 503 and a non-JSON 200, and accepts an empty 200 object as
a legacy status dictionary. Its visual methods already have typed outcomes,
but that does not apply to risk. M2 must add classified risk outcomes and
required-field validation before deciding which failures qualify for fallback.
These pending items are explicit in the report; a boundary pass does not certify
production fallback, final attendance or DB retry correctness.

M2 still needs: required-image/registered-template gates, no-insert-on-outage,
typed risk errors, equivalent local scoring, source/version audit metadata,
final status/threshold rules and real DB retry/duplicate tests. The agreed
outage policy must also be exercised through the frontend's retry UI.

## Template handoff

Default mode remains SHA-256 compatibility; enhanced mode remains explicit
opt-in. No model weights, scoring formula, private key/projection or template
bytes changed in this phase. Enrollment details and `GET /` now expose the same
`template_mode`, `template_format` and `match_score_policy` metadata.

| Mode | Format ID | Score policy |
| --- | --- | --- |
| sha256 | sha256_normalized_face_pixels_v1 | exact_sha256_v1 |
| simhash | sface_simhash64_signed_v1 | gaussian_query_margin_agreement_v3 |

M2 stores the returned 64-hex template unchanged and treats it as opaque. Never
rehash it or choose a policy from its length. Retain enrollment/deployment policy
metadata; reject mismatched modes/keys and follow the agreed migration plan.
M2 never needs the private template key. Team confirmation is still required
before choosing enhanced mode as the deployment default. .70 enhanced matching
is normalized agreement, not raw cosine .70 or a calibrated probability.

Final default-mode selection and genuine failure review/reject remain pending.
This work does not claim new accuracy data or remove the October 23 key-sensitivity
limitations. No Docker, other-module or root/shared-test modifications.
