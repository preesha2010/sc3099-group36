just pushed the M3 compatibility update to `module3-face-recognition`!

- aligned the M3 boundary checker with the latest M2 typed FaceCall response while separately validating M3’s complete raw risk response, including `risk_threshold`
- against M2 `f1dfd77`, both profiles pass 28/28 named boundary checks, 12/12 visual outcome probes and all 45 risk vectors per profile
- the full M3 release checks pass: 310 local tests and 15/15 public face tests in each profile
- enhanced mode passed the existing cross-photo and PAD smoke checks using a fixed, non-production test key and checked public models. The old temporary test key was unavailable, so previously enrolled templates were not tested against that key
- note for risk integration: M2 now distinguishes 503, non-JSON and empty risk responses, but still accepts some synthetic responses with inconsistent score/breakdown, pass flag or level. M3’s score remains advisory; this needs checking before it drives attendance
- required-liveness without an image and the final risk/template policies remain joint decisions; no M2 database, Docker or frontend E2E was run in this phase
- only M3 files changed. Existing weights, thresholds, template format and deployment keys were not changed

Details and reproducible evidence: `VALIDATION-20261031.md` and `MODULE2-INTEGRATION.md`.
