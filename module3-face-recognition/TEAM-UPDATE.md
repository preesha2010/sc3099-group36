just pushed the latest Module 3 updates to `module3-face-recognition`! 181 module-local tests and 15/15 public face-service tests in each profile are passing.

- face enrolment, 1:1 verification, legacy matching, passive liveness and the risk-assessment API are implemented; yes, `POST /face/*` on port 8001 is handled by Module 3
- checked the actual latest Module 2 FaceClient (`7963b06`): 28/28 live boundary checks + 12/12 real HTTP outcome checks pass; its earlier malformed-response issue is resolved in that revision
- with the user's approval, repaired enhanced similarity scoring using transient query margins, without changing model weights, stored template format, private key/projection or numeric thresholds; existing signed SimHash enrollments do not need re-enrolment for this score-only update, but all instances must restart consistently
- existing correlated samples now show 0/16 identity false accepts and 0/24 false rejects; PAD demos show 0/16 attack accepts and 0/8 genuine rejects. The rejected direct-cosine candidate and all historical failures are retained, not hidden
- important: .70 is normalized agreement (estimated cosine .40), not raw cosine .70 or a match probability. Two identities/three PAD demos are NOT independent accuracy certification; fixed toy-seed sensitivity still finds errors
- completed a ten-minute enhanced soak with three restarts, eight-client 12MP mixed-input stress, transport/privacy checks and repeated 10/50/100-client checks; reports distinguish successful inference from overload rejection
- only Module 3 was changed; Docker remains excluded. Default SHA-256 mode still matches only the same normalized image; enhanced cross-photo mode remains opt-in pending the shared template policy
- remaining joint work: agree template/scorer/risk/failure policies, provide authorized held-out camera/PAD data, and run the full capture -> backend/auth/DB -> attendance -> dashboard/Collector flow. Module 2 still uses its own risk calculation rather than calling `/risk/assess`

Details, limits and reproducible evidence: `VALIDATION-20261023.md`, `STANDALONE-COMPLETION.md` and `MODULE2-INTEGRATION.md`.
