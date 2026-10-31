# Isolated M2/M3 backend integration tests

Shareable HTTP tests for Module 2 talking to a **working** Module 3. They are opt-in and refuse the shared `saiv` database.

These scripts seed and assert **isolated backend fixture data** (`e2e.*@saiv.edu.sg`). They are **not** full M1 → M2 → M3 → M4 UI tests, camera tests, or biometric-accuracy tests.

Previous passing runs lived in `%TEMP%\saiv_m2_m3_e2e` and `%TEMP%\saiv_docker_e2e`. Those scripts hardcoded Windows paths, ports `8002`/`8015`/`8010`/`8016`, passwords, and `saiv_m2_m3_e2e` / `saiv_e2e`. Do not reuse them. The Docker compose file also built a temp M3 extract and must not be pointed at the repo `docker-compose.yml`.

## What is covered

| Test | Behaviour |
|---|---|
| Face enrollment | `POST /users/me/face/enroll` through M2 → M3; `users.face_enrolled` and hash stored |
| Verification + liveness | Same-person photo check-in is `approved`, `liveness_passed` and `face_match_passed` |
| Risk assessment | Successful biometric check-in stores a risk score; also probes M3 `POST /risk/assess` |
| Failed face match | Obama enroll + Biden check-in → `flagged`, `face_match_passed=false` |
| Failed liveness | Gray PNG check-in → `rejected`, `liveness_passed=false` |
| Required M3 outage | Optional: 503 and **no** new check-in row |
| Retry after outage | Optional: later check-in creates a row |
| Instructor assignment | Assigned instructor can read course roster; unassigned instructor gets 403 |

Same-person match, mismatch, and gray-image liveness results depend on Module 3's template and liveness mode. The assertions above match a working M3 using `FACE_TEMPLATE_MODE=sha256` and `LIVENESS_BACKEND=heuristic`. A different embedding model may not treat `obama.jpg` / `biden.jpg` / gray PNG the same way.

## What is not covered

- Full M1 → M2 → M3 → M4 UI testing
- Real mobile camera compatibility
- M3 cross-photo biometric accuracy
- Starting, stopping, or wiping the shared Docker project / `saiv` volume

## Dependencies

Install Module 2's Python deps, then Pillow (used only by this suite):

```text
pip install -r module2-backend/requirements.txt
pip install Pillow
```

Also required:

- Isolated Postgres database whose **name is not** `saiv`
- Isolated Module 2 already running against that database
- Isolated Module 3 already running, with `/health`, `/ready`, `/face/enroll`, `/face/verify`, `/liveness/check`, and `/risk/assess`
- Repo `sample_images/obama.jpg` and `sample_images/biden.jpg`

The `module3-face-recognition` folder in this starter tree is a **stub**. Point `E2E_FACE_URL` at a working M3, not Docker `:8001` if that container 501s `/risk/assess`.

Module 2 fail-closes advisory risk: a biometric check-in (image present, liveness/face required) needs Module 3 `POST /risk/assess` to return **HTTP 200** with a typed `risk_score` in `[0.0, 1.0]`. If `/risk/assess` is 501 or malformed, enrollment may succeed and check-in will 503.

## Environment variables

All of these are required except the optional flags. There is **no** default to `localhost:8000` or database `saiv`.

| Variable | Purpose |
|---|---|
| `SAIV_E2E_ISOLATED=1` | Required opt-in. Without it, pytest skips **this folder only**. |
| `E2E_DATABASE_URL` | Isolated Postgres URL. Database name `saiv` is rejected. |
| `E2E_M2_URL` | Isolated Module 2 base URL, for example `http://127.0.0.1:8002` |
| `E2E_FACE_URL` | Isolated Module 3 base URL, for example `http://127.0.0.1:8015` |
| `E2E_PASSWORD` | Fixture password (default `E2ePass123!`) |
| `E2E_SAMPLE_DIR` | Optional image directory (default repo `sample_images`) |
| `E2E_RUN_OUTAGE=1` | Run the 503 outage test. Stop **only** isolated M3 first. Keep this set for retry. |
| `E2E_RUN_RETRY=1` | Run the recovery test after isolated M3 is healthy again. |

## Setup

1. Create a dedicated database, for example `saiv_m2_m3_e2e`. Do not use `saiv`.
2. Start isolated Module 2 with `DATABASE_URL` set to that database and `FACE_SERVICE_URL` set to isolated Module 3. Do not restart `saiv-backend`.
3. Start isolated Module 3 on a **different port** from shared `:8001` if the shared face container is in use.
4. Confirm the seed nonce check: tests login as the E2E admin and `GET /courses/{id}`. If Module 2 is attached to `saiv`, the run aborts before creating HTTP traffic that would stick.

Seed only upserts `e2e.*@saiv.edu.sg` fixtures and deletes **those students'** check-ins. It does not `DROP` tables, run Alembic, or call `docker compose down`. With `E2E_RUN_OUTAGE=1` or `E2E_RUN_RETRY=1`, seed keeps the outage user's enrolled face template.

PowerShell:

```powershell
$env:SAIV_E2E_ISOLATED="1"
$env:E2E_DATABASE_URL="postgresql://saiv:saiv_password@127.0.0.1:5434/saiv_m2_m3_e2e"
$env:E2E_M2_URL="http://127.0.0.1:8002"
$env:E2E_FACE_URL="http://127.0.0.1:8015"
python tests/integration/m2_m3/seed.py
```

Bash:

```bash
export SAIV_E2E_ISOLATED=1
export E2E_DATABASE_URL="postgresql://saiv:saiv_password@127.0.0.1:5434/saiv_m2_m3_e2e"
export E2E_M2_URL="http://127.0.0.1:8002"
export E2E_FACE_URL="http://127.0.0.1:8015"
python tests/integration/m2_m3/seed.py
```

## Execution

Keep the same `SAIV_E2E_ISOLATED`, `E2E_DATABASE_URL`, `E2E_M2_URL`, and `E2E_FACE_URL` for every command in a run.

Default suite (isolated M3 up):

```powershell
$env:SAIV_E2E_ISOLATED="1"
$env:E2E_DATABASE_URL="postgresql://saiv:saiv_password@127.0.0.1:5434/saiv_m2_m3_e2e"
$env:E2E_M2_URL="http://127.0.0.1:8002"
$env:E2E_FACE_URL="http://127.0.0.1:8015"
python -m pytest tests/integration/m2_m3 -v
```

Outage (after the default suite enrolled `e2e.outage@saiv.edu.sg`). Stop only the isolated M3 process — never `saiv-face-recognition`. Keep the same `E2E_*` URLs:

```powershell
$env:SAIV_E2E_ISOLATED="1"
$env:E2E_DATABASE_URL="postgresql://saiv:saiv_password@127.0.0.1:5434/saiv_m2_m3_e2e"
$env:E2E_M2_URL="http://127.0.0.1:8002"
$env:E2E_FACE_URL="http://127.0.0.1:8015"
$env:E2E_RUN_OUTAGE="1"
python -m pytest tests/integration/m2_m3/test_m2_m3_backend_e2e.py::test_required_m3_outage_returns_503_without_row -v
```

Retry: start isolated M3 again, keep the same URLs, and leave `E2E_RUN_OUTAGE=1` on so seed does not wipe the outage user's face template:

```powershell
$env:SAIV_E2E_ISOLATED="1"
$env:E2E_DATABASE_URL="postgresql://saiv:saiv_password@127.0.0.1:5434/saiv_m2_m3_e2e"
$env:E2E_M2_URL="http://127.0.0.1:8002"
$env:E2E_FACE_URL="http://127.0.0.1:8015"
$env:E2E_RUN_OUTAGE="1"
$env:E2E_RUN_RETRY="1"
python -m pytest tests/integration/m2_m3/test_m2_m3_backend_e2e.py::test_m3_recovery_retry_creates_checkin -v
```

## Expected results

Default suite (M3 up): enrollment 200, success check-in 201 `approved`, mismatch 201 `flagged`, gray image 201 `rejected`, duplicate 400, roster 200 / unassigned 403, direct `/risk/assess` 200 with `risk_score` in `[0.0, 1.0]`. Outage and retry skip unless their flags are set.

## Safety safeguards

- Opt-in `SAIV_E2E_ISOLATED=1`
- Exact database name `saiv` / `postgres` / `template0` / `template1` is refused
- `current_database()` is checked on every SQL connection
- Seed will not `create_all` or migrate
- HTTP writes start only after Module 2 returns the isolated course **nonce**
- Without the opt-in, pytest skips only `tests/integration/m2_m3/` — not `tests/public/` or `tests/local/`
- No Docker start/stop/delete commands
- Do not run `docker compose down -v` from the repo root; that targets shared `postgres_data`
