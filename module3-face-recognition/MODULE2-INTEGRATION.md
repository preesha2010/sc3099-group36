# Module 2 / Module 3 boundary handoff (updated 2026-10-31)

**Current M2 target:** `f1dfd77e1744d5f0c6f31066d0c2e658b259dd5b`.
The new risk method returns typed FaceCall data and distinguishes 503,
non-JSON 200 and empty 200. The October 28 observations immediately below are
historical and apply to the old `7963b06` target, not this new revision.

The current client deliberately strips `risk_threshold`. Our checker now
compares its retained fields to a separate M3 raw-wire response and validates
the complete wire result against each golden vector, including its threshold.
This does not imply that M2's local risk calculation matches M3. M2 still uses
M3's risk response as advisory and applies its own local score/status rules.

New controlled probes show that the current M2 parser accepts synthetic
responses with inconsistent score/breakdown, pass flag or risk level. Its
current advisory use does not apply those values to attendance. The inconsistency
must be addressed before using the M3 result as an authoritative decision input.
The service also still allows image-less check-in with required liveness; the
documented API/test conflict remains for the team or teaching staff to resolve.

M2 now implements course assignments, failed-face review and required-visual
outage handling. In the intended integration DB, verify the teaching-assignment
table/schema and active TA assignments; the M3 boundary checks do not inspect
that DB. Its isolated E2E tests use SHA/heuristic and do not prove enhanced
cross-photo or production-camera behaviour. Read `VALIDATION-20261031.md`.

---

**Historical 2026-10-28 update (old M2 revision):**
**Latest:** `INTEGRATION-CONTRACT.md` records the recent required-image,
503/no-insert/retry and conditional risk-fallback discussion.
`GET /risk/policy` + successful risk policy headers now publish
`weighted_signals_v1`. The 45 synthetic risk vectors pass over the actual M2
client in each profile, in addition to the 28 named boundary checks and 12
visual outcome probes. These vectors check forwarding, NOT M2's local fallback.

**New risk-client caveat:** real probes show `FaceClient.assess_risk` still
returns None for both 503 and non-JSON 200; an empty 200 object remains a legacy
status dictionary. M2 needs typed risk outcomes and field validation before
fallback eligibility. The visual-client malformed-response fix described below
remains valid; it does not cover the risk method. Reports mark this explicitly
as `integration_pending`, not completed attendance/fallback work.

Enrollment details/root now include `template_format` alongside mode and score
policy. Default mode, key/format/weights and matching formula are unchanged.
Risk request booleans/numeric strings now return 422; valid JSON numbers/null
retain their established numerical semantics. See `VALIDATION-20261028.md`.

Read-only comparison target: `module2-backend` at
`7963b06641dc5ed5f3f4f5df8a843b61b068f53c`.
No Module 2 files or branch were modified, merged or copied into this module.
Latest evidence: `evaluation/backend-contract-20261023.json` and
`VALIDATION-20261023.md`. Historical October 19/20 client observations are
superseded where explicitly noted below.

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

Latest FaceClient returns typed `FaceCall` outcomes for enroll/verify/liveness,
with `ok`, `kind`, `status`, `data`; risk retains the legacy dictionary return.
Only the diagnostic adapter changed to observe both contracts. Its loader
registers an isolated module for postponed dataclass annotations and stubs ONLY
the settings import; upstream source/methods/requests are unmodified.

The old non-JSON-200-as-success warning is **resolved in this backend revision**.
Real HTTP probes confirm malformed/missing/invalid typed results are not success.
A valid negative decision IS a successful transport result, but NOT a passed
identity/liveness decision. `.ok` alone must never approve attendance.

Templates remain 64 lowercase hexadecimal characters in both profiles, but
their policies are not interchangeable. Default SHA-256 matches only the same
normalized image; opt-in SimHash supports cross-photo similarity and is not
SHA-256-only storage. Changing profile/key/model policy needs a migration plan.

The user-authorized October 23 scorer is
`gaussian_query_margin_agreement_v3` (`GET /: match_score_policy`). It preserves
signed SimHash bytes/key/projection/weights and needs **no re-enrollment for this
score-only update**. Restart all instances consistently; do not mix old/new
scorers. Score .70 is normalized agreement, estimated cosine .40, not raw cosine
.70 or a probability. The backend already receives/uses these changed scores;
final risk interpretation needs joint approval. Keep the continuous-score API
internal and apply caller authentication/rate controls upstream.

Module 2 owns browser authentication, consent persistence and storing the
returned template through `/api/v1/users/me/face/enroll`. Module 3 has no user or
session database: verification needs the stored reference supplied by Module 2.
It does not issue JWTs or decide final attendance. Keep internal API/metrics off
the public network.

## What was actually exercised

The JSON report records the resolved backend commit and SHA-256 of its unmodified
FaceClient source. It starts loopback Module 3 subprocesses, retaining the actual
client's five-second timeout except the intentional short-timeout fault probe.

- Fourteen checks per profile: **28/28 live client/service boundary checks**.
- **12/12 real HTTP outcome checks:** 503, 500, 422, 408, timeout, non-JSON 200,
  empty object, boolean score, string boolean, NaN score, bad hash, valid negative.
- Root mode and raw wire threshold/passive metadata are also checked: the new
  client deliberately strips some metadata from its validated data result.
- No backend app, DB, Redis, JWT or complete attendance flow was exercised.
- No images, templates, private keys or response bodies enter this aggregate
  report. Existing repository samples only; no new people/data were collected.

```powershell
git fetch origin refs/heads/module2-backend:refs/remotes/origin/module2-backend
python scripts/check_backend_contract.py --backend-ref 7963b06641dc5ed5f3f4f5df8a843b61b068f53c
```

The harness reads a local Git ref, not a fetch/checkout itself. Only execute it
against trusted project code: the client source is executed, not sandboxed.
Settings are test-only; no deployment credentials are supplied.

## Remaining joint decisions and integration (not Module 3 edits)

1. **Template/scorer policy:** agree default exact-image compatibility versus
   enhanced similarity, key custody/backup, existing enrollment migration and
   one consistent scorer version. Equal hash lengths do not prove compatibility.
2. **Final risk ownership:** backend check-in still calls its own
   `checkins.risk_service.assess`, not `FaceClient.assess_risk`. Align formulas,
   signals, score semantics and approve/review/reject policy; the Module 3 risk
   endpoint being tested does not prove it is used for attendance.
3. **Missing signals/failure policy:** `_face_signals` leaves unavailable outcomes
   as None; the current risk calculator initializes missing face/liveness risk
   to zero. Liveness false explicitly rejects, but face false alone contributes
   weighted risk rather than forcing rejection. Decide intended behavior for
   missing image/reference, timeout, 408, overload, malformed result and false
   decisions. Client validation fixes do not prove fail-closed authorization.
4. **Real capture/auth/DB flow:** test consent -> enrollment persistence -> new
   photo check-in -> stored face/liveness signals -> attendance/review/export ->
   Module 4 dashboard. Include expired JWT, unavailable service and negative
   decisions. This needs the other owners and their services/test environment.
5. **Accuracy/PAD:** the existing correlated sample gate now passes, not a held-out
   security evaluation. Supply authorized labeled identity and print/screen/replay
   data across real cameras/lighting; agree operating point/target FAR/FRR and
   APCER/BPCER. Toy-seed sensitivity still finds identity errors.
6. **Active/device protocols:** passive single-frame liveness cannot verify
   blink/head-turn or signed device identity. These require multi-frame random
   server challenges, anti-replay/expiry and frontend/backend protocol agreement.
7. **Observability/network/deployment:** configure trusted network, upstream
   header/TCP deadlines, caller auth/rate control, metrics scraping and the real
   backend -> Module 3 -> Collector -> dashboard trace chain. Local OTLP receiver
   delivery is verified, not an authenticated/durable production Collector.
8. **Capacity/operations:** default eight active/32 pending/two-second queue can
   legitimately reject with 503/Retry-After. Agree retry/review behavior and host
   resources. Relaxed 128-waiter/30-second throughput is not default capacity;
   fleet/key distribution, real long-duration load and deployment need owners.
   Docker remains explicitly excluded from this phase.
