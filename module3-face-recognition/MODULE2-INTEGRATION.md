# Module 2 / Module 3 boundary handoff (2026-10-19)

2026-10-20 additions: incomplete uploads can now return **408**; this is not an
identity decision. Optional OTLP traces preserve `traceparent` but discard
baggage/tracestate and all input/score data. Module 3-side delivery to a local
test receiver is verified, not the real backend/Module 4 trace chain. See the
latest validation record for the EXIF evaluation correction and remaining
identity classification block.

Read-only comparison target: `module2-backend` at
`601b3813f481ff05c344cfcddea6b191b9230038`.
No Module 2 files or branch were modified, merged or copied into this module.

## Ownership and compatible calls

Yes: Module 3 owns port **8001**, including `POST /face/enroll`,
`POST /face/verify` and legacy `POST /face/match`. It also implements
`POST /liveness/check` and `POST /risk/assess` on that service.

| Backend client method | Module 3 request | Success consumed by caller |
| --- | --- | --- |
| `enroll` | user_id, image, camera_consent=true | 201; enrollment_successful, face_template_hash, quality_score |
| `verify` | image, reference_template_hash | 200; match_passed, match_score, current_template_hash |
| `liveness` | challenge_response, challenge_type=passive | 200; liveness_passed, liveness_score, face_embedding_hash |
| `assess_risk` | documented risk signals | 200; risk_score, risk_level, pass_threshold, signal_breakdown |

Templates remain 64 lowercase hexadecimal characters in both profiles. That
does **not** mean their policies are interchangeable. Default SHA-256 is an
exact normalized-image compatibility mode and fails cross-photo recognition.
Opt-in SimHash provides cross-photo similarity but is NOT SHA-256-only storage,
and its observed misclassifications still block biometric security approval.
Do not change modes/keys between enrollment and verification. Agree the final
policy and re-enrollment/migration plan first; retain the chosen private key.

The browser uses Module 2's authenticated `/api/v1/users/me/face/enroll` route.
Module 2 checks/stores consent and stores Module 3's returned template. Module 3
is stateless: it has no user/session database and needs the stored reference on
each verification. It does not issue JWTs or decide final attendance status.
Keep its unauthenticated internal API/metrics off the public network.

## What was actually exercised

`evaluation/backend-contract.json` records the resolved backend commit and
SHA-256 of the **unmodified** upstream FaceClient source. The harness executes
that source, stubbing only `app.core.config.get_settings`; all client method
logic and HTTP requests remain real. It starts its own loopback Module 3
subprocess and uses the client's existing five-second timeout.

- Fourteen checks passed in each profile: 28/28 service-boundary checks.
- Four additional real-HTTP fault checks passed: 500, 503, 422 and timeout.
- No backend app, database, Redis, JWT or complete attendance flow is exercised.
- No images, templates, private keys or response bodies enter the report.
- No new people/data were collected; the existing repository sample was used.

Reproduce from this module after bootstrapping the enhanced model assets:

```powershell
git fetch origin refs/heads/module2-backend:refs/remotes/origin/module2-backend
python scripts/check_backend_contract.py --backend-ref origin/module2-backend
```

For immutable reproduction use the full backend commit above as `--backend-ref`.
The command reads a local Git ref; it does not fetch or change branches itself.
Only run this harness against trusted project code: the client source is executed,
not sandboxed. Its settings are test-only, with no deployment credentials.

## Shared decisions that are not solved by this boundary pass

1. **Risk policy:** the current backend check-in flow invokes its own
   `checkins.risk_service.assess`; it does not call `FaceClient.assess_risk`.
   Module 3's endpoint is available and tested, but that is not proof it is used
   for final attendance. Align missing-signal handling, rejection/review policy
   and ownership with Module 2. No weighting or timeout was changed here.
2. **Unavailable is not verified:** FaceClient returns None on 5xx/timeout.
   `_face_signals` leaves values missing, while the current backend risk code
   initializes missing face/liveness risk to zero. Failed matching alone adds
   only its weighted risk contribution and does not force rejection. Decide the
   intended review/rejection behavior jointly; never call this fail-closed
   attendance authorization based on the Module 3 tests.
3. **Malformed upstream responses:** the actual client's `is_success` reports
   true for a non-JSON HTTP 200 represented only as `{"_status": 200}`. This
   diagnostic observation is explicitly recorded, not counted as biometric
   success. Validate required booleans, finite scores and templates at the
   backend boundary. No other module was patched to change that behavior.
4. **Capacity:** default admission is eight active plus 32 queued, with a
   two-second queue deadline. 503/Retry-After means rejected work, not a match.
   The relaxed 128-waiter/30-second throughput experiment is NOT production
   capacity. Agree resources/arrival rate and fail/review behavior before rollout.
5. **Accuracy and camera integration:** identity false accepts remain. Version 2
   fixes EXIF loss in transformed PAD evaluation: its 24 checks pass, superseding
   old PAD failure counts, but not certifying real camera security. No authorized held-out corpus is
   available. Full capture -> auth/DB -> face signals -> attendance -> dashboard
   validation needs the other owners. Active challenges and signed device
   attestation need multi-frame/server-challenge protocols, not a still-image
   workaround. Docker remains excluded by the user's instruction.
