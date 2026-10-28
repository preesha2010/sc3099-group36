# Module 3 handoff checklist

**2026-10-28 integration continuation:** start with `INTEGRATION-CONTRACT.md`
and `VALIDATION-20261028.md`. New policy discovery, strict numeric inputs,
template metadata and shared conformance tooling support the team's fallback/
retry discussions. No M2 fallback, attendance transaction or final template/
review decision is implemented by this M3-only update.

**Current 2026-10-23 handoff:** read `VALIDATION-20261023.md` and
`STANDALONE-COMPLETION.md` first. Standalone regression, both public profiles,
the existing-sample classification gate, transport and the latest Module 2
client boundary pass. The user-authorized query-margin scorer replaces the
old Hamming scorer; existing signed templates/key/weights are unchanged, so
this score-only update needs consistent restart, not re-enrollment. Its .70
threshold is normalized agreement (estimated cosine .40), NOT raw cosine .70.
Scores/decisions differ; do not mix scorer versions. Independent accuracy,
template/risk/failure policies, deployment and full-system integration remain
external. Historical notes below do not describe the new score policy.

**2026-10-20 superseding evidence:** see `VALIDATION-20261020.md`. Transform
version 2 preserves EXIF display orientation; old transformed PAD failures were
evaluation-construction artifacts, not valid current model-error counts. The
corrected 24 PAD checks pass, but five identity false accepts still block release.
Whole-body upload deadlines and opt-in privacy-allowlisted OTLP are implemented;
actual upstream network/Collector/dashboard integration is still external.

**Latest 2026-10-19 update:** `VALIDATION-20261019.md` records 128 local tests,
both public profiles, real Module 2 client boundary checks and the still-failed
classification gate. Read `MODULE2-INTEGRATION.md` for shared policy decisions;
the backend currently uses its own risk aggregator rather than `/risk/assess`.

**2026-10-18 release warning:** expanded diagnostics found wrong-person
acceptances and transformed attack acceptances. Read `VALIDATION-20261018.md`
and the failed `evaluation/robustness-20261018.json` classification gate before
using this branch for automatic attendance decisions. `/ready` is operational
readiness, not an accuracy/security approval. Thresholds were not tuned to hide
these counterexamples.

Scope: only `module3-face-recognition/`, branch `module3-face-recognition`.
No backend/frontend/Module 4/database/shared test/Compose changes are required by
the standalone scripts. Docker is explicitly excluded from this work phase.

## Run and check

1. Install `requirements.txt` into a clean Python 3.11/3.12 environment.
2. For SHA-256 compatibility: run `python -m uvicorn app.main:app --host 127.0.0.1
   --port 8001 --no-access-log` (one command). This is exact-image compatibility,
   NOT cross-photo identity recognition.
3. For explicit enhanced mode: bootstrap both model sets as in README, securely
   retain `models/template.key`, then run `python scripts/run_enhanced.py`.
   No request requires internet. Never regenerate a key to bypass an error.
4. Verify `/health` and `/ready`. A failed preflight must not be worked around
   by disabling checks or silently falling back to legacy matching.
5. Run `python scripts/verify.py`, then the desired profile's `acceptance.py`.
   For enhanced cross-photo/PAD/throughput smoke tests run `evaluate.py`.
6. Inspect JSON reports: passing correctness does not imply all 100 burst
   requests were processed. Read 200, 503 and timeout counts separately.

## Calling contract (no backend changes made here)

| Step | Method/path | Minimum fields | Expected success |
| --- | --- | --- | --- |
| Enroll | POST `/face/enroll` | user_id, image, camera_consent=true | 201 and face_template_hash |
| Verify | POST `/face/verify` | image, reference_template_hash | 200 and match_passed/match_score |
| Legacy match | POST `/face/match` | image, reference_hash | 200 and face_embedding_hash |
| Passive liveness | POST `/liveness/check` | challenge_response | 200 and liveness_passed/liveness_score |
| Risk | POST `/risk/assess` | scores and available documented signals | 200 and weighted signal_breakdown |

The backend owns authentication, consent persistence, storing the selected
template, sessions/time windows, geofences, database updates and final attendance
status. The Module 3 test caller intentionally owns none of those decisions.

Errors: 400 consent/image/challenge issues, 408 unfinished upload, 413 oversized body/image, 422 schema
violations, 503 unavailable model or admission overload. No-face verification
is a valid 200 with false/zero/empty current hash. Do not approve attendance on
timeout, non-JSON, 503 or a false match/liveness result. Retry is a caller policy
decision; unbounded automatic retries can amplify overload. `Retry-After: 1`
identifies admission rejection, not a successful identity check.

## Internal monitoring and recovery

- Scrape `/metrics` only on the trusted internal network. It has no auth, just
  like the existing internal face API. Do not route it through a public portal.
- `/health` means process responsiveness; `/ready` means startup assets/config
  remain unchanged and no model slot is degraded. Check both independently.
- Inference/cleanup failure evicts the model. Failed reconstruction preserves
  capacity tokens and is retried in the background. Ongoing failures need an
  operator; they are not treated as successful inference or low-risk attendance.
- Stage histograms expose queue, decode, detection, embedding, similarity, cleanup, mesh and
  PAD timings. These are nested wall times, not mutually exclusive CPU profiles.
- All metric labels are fixed; request IDs are random response headers only.
  Never add image/template/student/device data to labels or logs.
- Optional `OTEL_EXPORTER_OTLP_ENDPOINT` sends allowlisted traces only; default
  empty disables it. Collector failure must not be treated as failed biometric
  inference. Check `module3_trace_export_failures_total` independently and read
  the README's privacy, delivery and authentication limitations before enabling.

## Keys, restore and migration

1. Back up the existing 32-byte private key using an access-controlled encrypted
   channel; never commit it or print it. This code does not choose a backup
   destination, upload keys or copy them into reports.
2. Stop routing requests before key/model/config changes. Restore matching
   weights/provenance and the SAME key to the configured model directory.
3. Restart and require `/ready` 200. Run restart acceptance using a non-student
   sample. The script keeps its reference only in memory across subprocesses.
4. Loss/rotation of the key or a change of template policy/model version requires
   re-enrollment. Do not reinterpret old SHA-256 strings as signed SimHash.
5. Multiple service instances require the same selected policy/model/key. This
   phase tests one process, not cross-host key distribution or rolling upgrades.
6. A score-only change preserving key/projection/encoding (October 23) does NOT
   itself require re-enrollment. Drain traffic and restart consistently; inspect
   `GET /`'s `match_score_policy` rather than assuming equal-length hashes imply
   equal decision semantics. New visual work returns 503 if runtime config,
   key or observed asset fingerprints change, including after queue waiting.

## Remaining external decisions/validation

- Resolve repository SHA-256-only storage versus the Module 3 lecture's SimHash
  approach. Default compatibility remains unchanged until that decision.
- Supply a sufficiently diverse, authorized, labeled corpus for held-out FAR/FRR
  and independent print/screen/replay PAD evaluation. Tooling is available, but
  small smoke tests do not certify security or select a deployment threshold.
- Actual frontend capture -> backend persistence -> attendance -> dashboard
  integration requires the owners of those modules. Local HTTP simulation is
  not a substitute for full-system validation.
- Active blink/head-turn needs an agreed multi-frame random-challenge protocol;
  the still-image endpoint correctly rejects it. Device attestation still needs
  the backend's signed server challenge. No new protocol is invented here.
- Docker/fleet deployment, upstream header/TCP deadlines, monitoring scraping config,
  long-duration production load and operational key custody remain unverified.
