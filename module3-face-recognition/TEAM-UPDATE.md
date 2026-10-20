just pushed the latest Module 3 updates to `module3-face-recognition`! 15/15 public face-service tests pass in both profiles, plus 160 module-local tests.

- face enrolment, 1:1 verification, legacy matching, passive liveness and the risk-assessment API are implemented
- yes, the `POST /face/*` endpoints on port 8001 are handled by Module 3; the actual Module 2 client passed 28 boundary checks plus 4 HTTP fault checks
- added whole-upload deadlines and optional privacy-safe OTLP tracing; real slow/chunked-upload, trace-delivery and Collector-failure checks pass
- completed a 15-minute enhanced soak, three restarts and an eight-client mixed-input test including real detected faces at 12MP; these are local checks, not deployment certification
- only Module 3 was changed; Docker remains outside this work phase
- important limitation: default SHA-256 mode only matches the same normalized image. Cross-photo SimHash mode is opt-in pending agreement on the template policy
- correction: the old transformed PAD failures came from EXIF orientation loss in the evaluator. After fixing it, all 24 PAD demo checks pass; that is not real-camera anti-spoof certification
- identity security is still blocked by 5/16 wrong-person accepts in the correlated demo comparisons. They were traced to 64-bit projection threshold crossings; an orthogonal-projection experiment was worse and was not shipped. No authorized calibration dataset is available
- remaining joint work: agree template/risk/failure policies and run the full capture -> backend/DB -> attendance -> dashboard flow. Module 2 currently uses its own risk calculation rather than calling `/risk/assess`

Details and reproducible evidence: `VALIDATION-20261020.md` and `MODULE2-INTEGRATION.md`.
