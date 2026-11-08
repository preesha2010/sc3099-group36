# Default cross-photo mode and network-risk validation

On 2026-11-08 a fresh local Git clone of commit 8fc2b8a was run on Windows
with Python 3.12 and MediaPipe 0.10.18. With no mode or key environment
variables, the service selected SimHash and created a local private key.
An Obama enrollment matched the same photo (0.896154) and obama2.jpg (0.787897);
biden.jpg did not match (0.559459). The key and enrollment worked after a
service restart. The fresh clone and key were isolated and not used for demo
or deployment. Results depend on the generated key and sample images; they
are not population accuracy or attack-resistance estimates.

With v2 risk policy, 10.0.0.1 alone produced 0.105 weighted network risk;
NordVPN and SecureTunnel user agents each produced 0.12. Each response included
`Disable VPN for check-in`. Substring matching follows the course reference,
and may flag unrelated user agents; these signals are not proof of VPN use.

The module-local suite passed 316 tests in the new default mode (the next
small test-only update ensures key-path isolation). The public face suite
passed 15/15 with SimHash and heuristic liveness. The actual M2 client from
main 1af3c57 passed 14 boundary checks in each profile, as well as the risk
corpus and HTTP fault probes; see `evaluation/backend-contract-v2-20261108.json`.
This does not test backend attendance decisions or the full stack.

Docker Desktop was unavailable; image build, persistent-volume configuration,
and multi-module end-to-end behavior were not verified here. A durable key
mount must be configured for deployments; losing a key requires re-enrollment.
