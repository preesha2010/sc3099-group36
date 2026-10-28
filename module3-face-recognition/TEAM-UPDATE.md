just pushed the M3 integration-contract updates to `module3-face-recognition`! 305 module-local tests and 15/15 public face-service tests in each profile pass.

- added `GET /risk/policy` plus policy ID/hash headers on risk responses; existing numerical weights, thresholds and required response fields are unchanged
- published 45 synthetic risk cases and a fail-closed checker for HTTP services or a future local fallback implementation; the same 45 cases pass through the actual M2 client in both profiles
- risk score inputs now reject booleans/numeric strings with 422; normal JSON numbers and null retain their established behaviour
- enrollment/root now expose matching template mode, format and score-policy metadata; default mode, template bytes, key/projection, model weights and matching formula are unchanged
- important M2 follow-up: `assess_risk` currently returns None for both outages and non-JSON responses, and accepts an empty 200 object as a legacy dictionary. Typed risk outcomes and response validation are needed before enabling fallback
- M2 still owns required-image checks, 503 without creating a check-in, equivalent fallback scoring, final attendance decisions and real DB retry/uniqueness tests. A numerical risk pass alone cannot approve a required failed biometric check
- only M3 was changed; no Docker work. The final template-mode choice and genuine failure review/reject policy still need confirmation

The full release pipeline, real transport/privacy checks and existing correlated classification gate pass. This does not certify M2's local fallback, DB transactions or real-world biometric accuracy.

Contract/reproduction: `INTEGRATION-CONTRACT.md`. Results and remaining work: `VALIDATION-20261028.md`.
