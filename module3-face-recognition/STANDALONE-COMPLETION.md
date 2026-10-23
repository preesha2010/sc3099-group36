# Standalone completion boundary, 2026-10-23

Scope: existing branch `module3-face-recognition`, this directory ONLY. No Docker,
other-module/root/shared-test changes, new face collection, new keys, threshold
fitting or external deployment. The user explicitly authorized scoring changes
and required both false accepts and false rejects to be reported.

"Standalone complete" below means implemented and checked with available local
assets/data. It does NOT mean all project objectives/security/deployment are
complete. No percentage is assigned to make missing external evidence disappear.

| Independently executable deliverable | Status / evidence |
| --- | --- |
| Modular service rather than a single main.py | app/schemas.py, services/, runtime, middleware, observability/telemetry; regression suite |
| Port 8001 enroll/verify/legacy match contract | Implemented; both unchanged public profiles 15/15 |
| Enrollment consent/quality and reference authentication | Implemented; unit + real client boundary checks |
| Default exact-image SHA-256 behavior | Preserved and explicitly labeled; not cross-photo recognition |
| Opt-in SFace/YuNet cross-photo pipeline | Implemented; current existing-sample gate passes |
| Authorized score repair, unchanged signed templates/key | Query-margin agreement v3; formula, rejected candidates and all FA/FR in latest validation |
| Passive quality + pretrained PAD | Implemented; existing 24 transformed demo checks pass, not camera certification |
| Unsupported active challenges | Explicitly rejected; cannot fake motion from a still image |
| Risk endpoint/weighted contributions | Implemented and checked; does not own attendance approval |
| Schema/image/base64/dimension/body limits and redaction | Unit, unchanged public, real TCP and mixed 12MP stress checks |
| Absolute upload deadlines/disconnect recovery | Implemented and verified over real fixed/chunked TCP |
| Admission queues/503/recovery | Bounded; overload and post-overload checks, never count 503 as inference success |
| Model/config preflight, immutable runtime, pool repair | Implemented; changed runtime blocks new/queued visual work before body read; slot tests pass |
| No biometric request cache/persistent vectors | Request-local graphs, blank native cleanup; local privacy/concurrency checks |
| Metrics, health, ready and optional allowlisted OTLP | Implemented; local receiver delivery/failure/privacy checks; no real Collector assumed |
| Actual latest Module 2 client compatibility | 28 live + 12 fault/outcome checks pass against 7963b06; no backend edits |
| Independent evaluation tooling | Aggregates, errors/denominators, threshold sweeps, EXIF-safe transforms and fail-closed local gate |
| Rejected candidates and key sensitivity | Retained; toy-seed results are sensitivity, not extra people or key selection |
| Finite stability/restarts, maximum-image stress, burst/load | Current-code reports linked in latest validation; host-local, not fleet guarantees |
| Dependency integrity and delivery handoff | pip check, diff/scope checks, README/runbook/team update; no secrets/models committed |

## Not completed by standalone code, and why

| Remaining deliverable | Required external input/owner |
| --- | --- |
| Credible FAR/FRR, APCER/BPCER and operating-point approval | Authorized, diverse, labeled held-out data + agreed acceptance targets; not available |
| Choose default template policy and rollout | Team resolves SHA-256-only requirement vs enhanced similarity; custody/migration/version policy |
| Decide attendance risk/fail-closed behavior | Module 2 + team; current missing-signal/default-risk semantics cannot be changed here |
| Full capture/enroll/check-in/persistence/attendance/review/export flow | Module 1 + Module 2 services/auth/DB and actual camera environment |
| Dashboard metrics and end-to-end trace evidence | Module 4 + real Collector/network configuration |
| Genuine active liveness/device attestation | Shared random challenge/multi-frame/signed anti-replay protocol, not unilateral still-image code |
| Production access/rate/network, key backup/fleet rollout and sustained capacity | Deployment/operations owners; Docker expressly excluded |

All currently identified in-scope standalone engineering tasks have evidence.
There is no claim that a finite test list proves absence of all bugs, adversarial
attacks, privacy leakage or future work. See `MODULE2-INTEGRATION.md` for the exact
joint checklist and `VALIDATION-20261023.md` for measured results and limitations.
