just pushed the latest Module 3 updates to `module3-face-recognition`! 15/15 public face-service tests pass in both profiles, plus 128 module-local tests.

- face enrolment, 1:1 verification, legacy matching, passive liveness and the risk-assessment API are implemented
- yes, the `POST /face/*` endpoints on port 8001 are handled by Module 3; the actual Module 2 client passed 28 boundary checks plus 4 HTTP fault checks
- added invalid-model-output handling, privacy-safe errors, model recovery and reproducible validation; local load/restart/overload-recovery checks pass, but deployment capacity is not certified
- only Module 3 was changed; Docker remains outside this work phase
- important limitation: default SHA-256 mode only matches the same normalized image. Cross-photo SimHash mode is opt-in pending agreement on the template policy
- biometric security validation is NOT complete: existing transformed demos still show wrong-person accepts and attack accepts, so the classification release gate remains blocked. No authorized calibration dataset is available
- remaining joint work: agree template/risk/failure policies and run the full capture -> backend/DB -> attendance -> dashboard flow. Module 2 currently uses its own risk calculation rather than calling `/risk/assess`

Details and reproducible evidence: `VALIDATION-20261019.md` and `MODULE2-INTEGRATION.md`.
