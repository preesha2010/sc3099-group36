# SAIV - Secure Attendance & Identity Verification

## NTU Computer Science Capstone Project - Student Package

Welcome to the SAIV capstone project! Your team will build a secure, privacy-preserving attendance system resistant to deepfakes, replay attacks, and remote sign-ins.

---

## Project Overview

### Learning Objectives
- Full-stack development (PWA frontend, REST API, database design)
- Security engineering (liveness detection, device binding, geofencing)
- Privacy-first architecture (PII minimization, encrypted storage)
- ML integration (pre-trained face recognition models)
- DevOps (Docker, observability)

### Project Scope
- **Duration**: 12-14 weeks
- **Team Size**: 4 students (1 per module)
- **Grading**: 130 points total (90 public + 40 hidden)

---

## Architecture

Your team will implement 4 modules:

### Module 1: Student Frontend PWA
**Recommended Tech Stack**: React/Next.js, TypeScript, WebRTC
- Student check-in interface
- Camera access for liveness challenges
- Geolocation with consent
- Device binding (public key rotation)
- Offline-capable PWA

### Module 2: Backend API
**Recommended Tech Stack**: Python FastAPI, PostgreSQL, Redis
- RESTful API with JWT authentication
- Session management (time-boxed check-ins)
- Check-in processing and validation
- Rate limiting and CORS
- Audit logging

### Module 3: Face Recognition & Risk Service
**Recommended Tech Stack**: Python, MediaPipe, OpenCV
- Liveness detection (blink, head pose)
- Face matching (with privacy controls)
- Risk scoring (signal fusion)
- Device attestation
- Anti-spoofing heuristics

### Module 4: Observability & Instructor Dashboard
**Recommended Tech Stack**: Streamlit, Prometheus, Grafana
- Instructor web interface
- Real-time analytics
- Audit log explorer
- Metrics visualization
- CSV export for gradebook

---

## Getting Started

One procedure starts Modules 1–4 plus PostgreSQL and Redis from a fresh clone of `main`. Starting only Postgres, Redis, or Grafana is not enough.

**Verified on a fresh clone of merged `main` (SHA-256 / heuristic), using an isolated Compose overlay** (remapped names, volumes, database, and loopback ports): image build, the four modules plus Postgres and Redis, health endpoints, schema creation including `course_instructors`, and a same-image enrollment / check-in / attendance read. The unmodified `docker-compose.yml` was **not** started on the assignment ports (`saiv-*` / `8000` / `5434` / …); those names and ports were already taken. The commands below are still the stock Compose names and ports.

**Not independently verified:** stock Compose on the assignment ports; enhanced SimHash / MiniFASNet (commands below are copied from [Module 3 README](module3-face-recognition/README.md)); Grafana; the OpenTelemetry collector; `docker compose down -v`; and camera / dashboard UI flows.

**Local development only.** `POST /api/v1/auth/register` accepts privileged roles (`admin`, `instructor`). Compose ships default database credentials, a placeholder API secret, and Grafana `admin`/`admin`. Anyone who can reach the published ports can create an admin and read local data. Do not expose this stack on a public network or treat it as a production deployment.

### Prerequisites

- Docker Desktop (or Docker Engine) with Compose V2 (`docker compose version`)
- Python 3.11+ only if you run the public tests on the host (see Running Tests)
- Node.js 18+ only if you develop Module 1 outside Docker

Default Module 3 does **not** download models. On Windows PowerShell use `docker compose` and `python`. Git Bash / macOS / Linux examples use `curl` and `python3` where that is the local name.

### 1. Check for existing SAIV containers and ports

The default Compose file is a **single-instance** layout. Stock names (`saiv-postgres`, `saiv-redis`, `saiv-backend`, `saiv-face-recognition`, `saiv-frontend`, `saiv-dashboard`, plus Prometheus / Grafana / OTEL) and stock host ports must both be free. A different Compose project name is not enough, because `container_name` is global.

Default ports (primary install): Postgres `5434`, Redis `6380`, backend `8000`, face service `8001`, frontend `3000`, dashboard `8501`, Prometheus `9090`. Grafana `3001` and OTEL `4317`/`4318` start only if you add those services.

```bash
docker ps -a --filter "name=saiv-"
```

```powershell
docker ps -a --filter "name=saiv-"
netstat -ano | findstr "LISTENING" | findstr ":5434 :6380 :8000 :8001 :3000 :8501 :9090"
```

If those names or ports are already in use, **do not** run `docker compose up` or `docker compose down` from a new clone. Compose will reuse the stock names and can stop or replace a stack you did not intend to touch.

A **second independent instance** needs all of: different `container_name`s, published ports, and volume names; a separate database name; and an M1 image rebuild with `NEXT_PUBLIC_API_URL` pointing at that instance's backend URL (see Module 1 API URL). Keep this README's commands on the assignment ports above unless you are deliberately remapping.

### 2. Start the stack (primary install)

From the repository root (the folder name may differ from `student-starter`):

```bash
docker compose up -d --build postgres redis backend face-recognition frontend dashboard
docker compose ps
```

The same command works in PowerShell. The first build takes a few minutes (Module 1 runs `next build`). Compose also starts **Prometheus** because `dashboard` lists it under `depends_on`. Grafana and the OpenTelemetry collector are not required for attendance and are left off.

Stock Compose publishes these ports on all interfaces (`0.0.0.0`), not loopback-only.

### 3. Health checks and URLs

Wait until `docker compose ps` shows Postgres and Redis as healthy **and** `GET http://localhost:8000/health` returns HTTP 200 before any first-run API calls. The backend has no Compose healthcheck, so database-healthy is not enough.

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8001/ready
curl -o /dev/null -w "%{http_code}\n" http://localhost:3000/
curl http://localhost:8501/_stcore/health
```

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8000/health
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8001/health
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8001/ready
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:3000/
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8501/_stcore/health
```

Expected: backend `{"status":"healthy"}`; face service `healthy` / `ready`; frontend HTTP 200; dashboard `ok`.

The dashboard Overview page looks for a `face_service` field on backend `/health`. That endpoint currently returns only `{"status":"healthy"}`, so Overview may warn that the face service is not answering even when `http://localhost:8001/ready` is 200. Confirm Module 3 with `/ready`; check-ins can still succeed.

| Service | URL |
| --- | --- |
| Frontend (M1) | http://localhost:3000 |
| Backend API (M2) | http://localhost:8000/docs |
| Face recognition (M3) | http://localhost:8001/docs |
| Dashboard (M4) | http://localhost:8501 |
| PostgreSQL | `localhost:5434` (Compose default database/user `saiv`; password is `POSTGRES_PASSWORD` in `docker-compose.yml`) |
| Redis | `localhost:6380` |
| Prometheus | http://localhost:9090 (starts with the dashboard) |

### Dashboard timezone (`SAIV_TZ`)

Module 4 reads `SAIV_TZ` at startup (`os.getenv("SAIV_TZ") or "UTC"`). Create-session times on the dashboard are treated as wall-clock in that zone and converted to UTC for the API. Displayed session times and "today" use the same zone. Stock `docker-compose.yml` does **not** set `SAIV_TZ`, so the dashboard defaults to UTC.

For a Singapore deployment, set `SAIV_TZ=Asia/Singapore` on the **dashboard** service (then recreate that container). Example override file:

```yaml
# compose.tz.yml — not in the stock Compose file
services:
  dashboard:
    environment:
      SAIV_TZ: Asia/Singapore
```

```bash
docker compose -f docker-compose.yml -f compose.tz.yml up -d dashboard
```

Without this, a session typed as 09:30 in the dashboard is stored as 09:30 UTC (17:30 in Singapore).

There is **no migrate command**. The backend creates application tables, including `course_instructors`, on startup:

```bash
docker exec saiv-postgres psql -U saiv -d saiv -c "\dt"
```

### 4. Default Module 3 (SHA-256 / heuristic)

This is the Compose default. You do not set extra environment variables and you do not download models.

- Enroll and check in with the **same photograph** (or the same captured frame). That path was verified on the isolated overlay, not on stock Compose.
- Different photos of the same person will not match. That is SHA-256-of-a-crop, not a failed install.
- Still images can pass heuristic liveness. This is not MiniFASNet anti-spoofing.

This profile boots the four modules and processes a same-image check-in. It is not a live-camera cross-photo identity demo.

### 5. First-run account, course, and check-in

There are no seed users. Use http://localhost:8000/docs or HTTP. Registering as `admin` is for trusted local/eval use only (see the warning above). Send `Content-Type: application/json`. After login, every authenticated request needs `Authorization: Bearer <access_token>`. Password minimum length is 8.

1. `POST /api/v1/auth/register` - body includes `email`, `password`, `full_name`, and `role` (`admin`, `instructor`, or `student`). Then `POST /api/v1/auth/login` with `email` and `password`. Use a normal email domain such as `@saiv.edu.sg`. Reserved suffixes like `.test` are rejected.
2. Admin: `POST /api/v1/courses/` with `code`, `name`, and `semester`. Then assign the instructor: `POST /api/v1/admin/courses/{course_id}/instructors` with `{"instructor_id": "<instructor user id>"}`. Session APIs return 403 until that row exists.
3. Admin: `POST /api/v1/admin/enrollments/` with `{"student_id": "<id>", "course_id": "<id>"}`.
4. Instructor: `POST /api/v1/sessions/` with `course_id`, `name`, `scheduled_start`, `scheduled_end`, an open check-in window, `venue_latitude`, and `venue_longitude`. For a SHA-256 **match** demo set `"require_face_match": true` (the schema default is `false`) and keep `"require_liveness_check": true`. Admin: `PATCH /api/v1/admin/sessions/{session_id}/status` with `{"status": "active"}`.
5. Student: `PUT /api/v1/users/me` with `camera_consent` and `geolocation_consent` set true. Face enroll: `POST /api/v1/users/me/face/enroll` with `{"image": "<base64 jpeg or png>"}`. `sample_images/obama.jpg` works for a same-photo smoke test.
6. Student: `POST /api/v1/checkins/` from inside the geofence, with `session_id`, `latitude`, `longitude`, and `liveness_challenge_response` set to the **same** base64 image used at enroll. Instructor: `GET /api/v1/checkins/session/{session_id}`. Student: `GET /api/v1/checkins/my-checkins`.

On the default SHA-256 profile, a different photograph of the same person will not match.

### Module 1 API URL is a build-time setting

Next.js inlines `NEXT_PUBLIC_*` into the browser bundle at **image build** time. The Module 1 Dockerfile ARG defaults to `http://localhost:8000`, which matches the default Compose backend port. Runtime `environment:` on the `frontend` service does **not** change the URL the browser calls.

Keep backend host port `8000` for the primary install. If you remap the backend to another host port (second instance), rebuild M1 so the ARG matches that URL:

```powershell
docker compose build --build-arg NEXT_PUBLIC_API_URL="http://localhost:YOUR_PORT" frontend
docker compose up -d frontend
```

The quoted `--build-arg` form on unmodified `docker-compose.yml` was not separately tested. Compose `build.args` is the mechanism that was used when the backend was not on port `8000`.

### Optional enhanced Module 3 (not tested in the fresh-install check)

SimHash / MiniFASNet is **opt-in** and was **not** run for this README. Copy the procedure and claims from [module3-face-recognition/README.md](module3-face-recognition/README.md). In short, that file asks for:

1. A one-time `python scripts/bootstrap_models.py` in the Module 3 API environment (YuNet/SFace weights and `models/template.key`; needs internet).
2. Optional PAD: a **separate** tools environment with the pinned CPU PyTorch / ONNX / numpy / httpx versions listed there, then `python scripts/bootstrap_models.py --pad`.
3. Do not commit `models/template.key` or weights. Do not mix SHA-256 and SimHash templates (re-enroll after a switch). Missing enhanced assets fail closed.

After bootstrap, that README starts the overlay with:

```bash
docker compose -f docker-compose.yml -f module3-face-recognition/compose.enhanced.yml up --build
```

### Stop the stack

From the **same directory** you used to start it:

```bash
docker compose down
```

The same command works in PowerShell. This stops containers and **keeps** the Postgres volume. `docker compose down -v` also deletes database data; do not run it unless you intend to wipe the local database. Never run `down` / `down -v` from this repo if the running `saiv-*` containers belong to another project you still need.

---

## Running Tests

You have access to the public test suite (75% of your grade).

**IMPORTANT:** Tests send HTTP requests to your running services. Your services MUST be running before you run tests.

### Step 1: Install Test Dependencies

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-test.txt
```

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-test.txt
```

### Step 2: Start Your Services

Complete **Getting Started** (the primary `docker compose up` command) and confirm the health checks there. Do not start a second Compose project against the same `saiv-*` names.

### Step 3: Run Tests

```bash
export TEST_BACKEND_URL=http://localhost:8000
export TEST_FACE_URL=http://localhost:8001
python3 -m pytest tests/public/ -v

# Run specific test category
python3 -m pytest tests/public/test_api_functional.py -v
python3 -m pytest tests/public/test_security_basic.py -v
python3 -m pytest tests/public/test_privacy_basic.py -v
python3 -m pytest tests/public/test_face_recognition.py -v
python3 -m pytest tests/public/test_observability.py -v
python3 -m pytest tests/public/test_integration.py -v

# The scoring plugin shows a summary at the end:
# TOTAL SCORE: 90.0/90.0 (100.0%)
# LETTER GRADE: A
```

```powershell
$env:TEST_BACKEND_URL = "http://localhost:8000"
$env:TEST_FACE_URL = "http://localhost:8001"
python -m pytest tests/public/ -v
```

### Step 4: Stop Services

Use **Stop the stack** in Getting Started (`docker compose down` without `-v`).

### Troubleshooting

**Tests skipping with "Backend service not running":** finish Getting Started and confirm `http://localhost:8000/health`.

**`Conflict. The container name "/saiv-..." is already in use`:** another stack owns those names. Do not run `docker compose down -v` unless that stack is disposable. See Getting Started step 1.

**Connection refused errors:**
```bash
curl http://localhost:8000/health
```

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8000/health
```

### Note on System Dependencies

Some packages require system-level dependencies:

- **face-recognition**: Requires `dlib` which needs `cmake` and C++ compiler
  - macOS: `brew install cmake`
  - Ubuntu: `sudo apt-get install cmake build-essential`

- **opencv-python**: Usually works out of the box, but may need:
  - Ubuntu: `sudo apt-get install libgl1-mesa-glx`

---

## Grading Breakdown

### Public Tests (90 points) - Available to you

| Test File | Points | Description |
|-----------|--------|-------------|
| test_api_functional.py | 26 | API endpoints, auth, CRUD operations |
| test_face_recognition.py | 15 | Face enrollment, matching, risk assessment |
| test_security_basic.py | 12 | JWT auth, input validation, rate limiting |
| test_privacy_basic.py | 8 | Consent, data minimization, retention |
| test_frontend_dashboard.py | 8 | Frontend/dashboard API contracts |
| test_observability.py | 12 | Stats, session management, export (bonus) |
| test_performance.py | 5 | Latency, concurrent users |
| test_integration.py | 4 | End-to-end check-in flow |

### Hidden Tests (40 points) - Revealed during grading

| Category | Points | Description |
|----------|--------|-------------|
| Advanced Security | 12 | GPS spoofing, replay attacks, VPN detection |
| Privacy Auditing | 8 | Database audit, encryption validation |
| Face Recognition Advanced | 10 | Advanced liveness, anti-spoofing |
| Liveness Bonus | 3 | Advanced liveness features |
| Stress Testing | 7 | Concurrent users, edge cases |

---

## Documentation

Please review these specifications carefully:

- **[API Specification](docs/API-SPECIFICATION.md)** - Complete endpoint documentation
- **[Database Schema](docs/recommended_design/DATABASE-SCHEMA.md)** - All table definitions

---

## Project Structure

```
student-starter/
├── module1-frontend/          # PWA (your implementation)
├── module2-backend/           # API (your implementation)
├── module3-face-recognition/  # ML service (your implementation)
├── module4-observability/     # Dashboard (your implementation)
├── tests/
│   ├── public/                # Public test suite (90 points)
│   └── scoring/               # Pytest scoring plugin
├── docs/
│   ├── API-SPECIFICATION.md
│   └── recommended_design/DATABASE-SCHEMA.md
└── docker-compose.yml
```

---

## Security Requirements

Your implementation must include:

1. **Authentication**
   - JWT tokens (HS256)
   - Bcrypt password hashing (cost >= 10)
   - Role-based access control

2. **Input Validation**
   - Sanitize all user input
   - Prevent SQL injection
   - Prevent XSS attacks

3. **Rate Limiting**
   - Protect against brute force
   - Use Redis for tracking

4. **Geofencing**
   - Validate GPS coordinates
   - Calculate distance to venue

---

## Required Admin Endpoints

Tests require these admin endpoints for test data setup. See [API Specification](docs/API-SPECIFICATION.md) for details.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/admin/users/{id}/deactivate` | PATCH | Deactivate user (for testing inactive login) |
| `/api/v1/admin/users/{id}/activate` | PATCH | Reactivate user |
| `/api/v1/admin/users/bulk` | POST | Bulk create users (for stress tests) |
| `/api/v1/admin/sessions/{id}/status` | PATCH | Update session status |
| `/api/v1/admin/enrollments/` | POST | Create enrollment (admin bypass) |

**Note:** These endpoints require admin authentication and are used by the test suite to set up test scenarios.

---

## Privacy Requirements

Your implementation must:

1. **Never store raw face images** - Process in memory, store only hashes
2. **Track consent** - Camera and geolocation permissions
3. **Implement retention** - 30-day auto-deletion of records
4. **Create audit logs** - Immutable event trail

---

## Tips for Success

1. **Read the specifications thoroughly** before coding
2. **Run tests frequently** to catch issues early
3. **Communicate with your team** - modules must integrate
4. **Don't over-engineer** - focus on requirements
5. **Think about security** from the start
6. **Document your decisions** for the final report

---

## Common Pitfalls

Avoid these mistakes:
- Storing raw face images (automatic privacy test failure)
- Ignoring rate limiting (vulnerable to attacks)
- Missing geofence validation (easy to bypass)
- Poor error handling (crashes under load)
- Incorrect CORS configuration (frontend can't communicate)

---

## Questions?

- Review the API specification and database schema
- Run the public tests to understand requirements
- Check the skeleton code for implementation hints

Good luck with your capstone project!
