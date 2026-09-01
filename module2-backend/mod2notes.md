app/
├── main.py
|
├── core/ # shared config, JWT, bcrypt
│   ├── config.py
│   ├── security.py
│   └── dependencies.py
│
├── db/ # engine, session
│   ├── base.py # DeclarativeBase goes here for other models to inherit
│   └── session.py
│
├── modules/ # each feature has one folder
│   ├── auth/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   └── dependencies.py
│   │
│   ├── users/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── model.py
│   │   └── repository.py
│   │
│   ├── courses/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── model.py
│   │   └── repository.py
|   |
│   ├── enrollments/
│   │   └── router.py
│   │   └── schemas.py
│   │   ├── service.py       
│   │   ├── model.py
│   │   └── repository.py
│   │
│   ├── sessions/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── model.py
│   │   └── repository.py
│   │
│   ├── devices/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── model.py 
│   │   ├── service.py
│   │   └── repository.py
│   │
│   ├── stats/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   └── service.py
│   │
│   ├── exports/
│   │   ├── router.py
│   │   └── service.py
│   │
│   ├── admin/
│   │   ├── router.py
│   │   └── service.py
│   │
│   └── checkins/
│       ├── router.py
│       ├── schemas.py
│       ├── model.py # Checkin table
│       ├── service.py
│       ├── risk_signal.py # RiskSignal table
│       ├── risk_service.py
│       └── repository.py
│
├── integrations/    # client for face-recognition service
│   └── face_client.py
│
├── middleware/  # global request concerns
│   └── rate_limit.py
│
└── audit/
    ├── router.py
    ├── schemas.py
    ├── service.py
    ├── model.py
    └── repository.py

router → service → repository / integrations
- router: receives HTTP request and returns response
- service: applies rules such as RBAC and check-in risk decisions
- repository: reads/writes PostgreSQL
- integrations: calls the face service

https://www.osohq.com/learn/rbac-role-based-access-control
The main idea is to build a system where people get permissions through roles, rather than assigning permissions person-by-person.
Key points to use:
- RBAC = User → Role → Permission → Resource.
  Example: a Viewer can read project records; an Editor can update them; an Admin/Owner can create, delete, and manage users.
- Use least privilege.
  Give each role only the access needed to do its work. This reduces accidental deletions, data exposure, and misuse.
- Separate authentication from authorization.
  Authentication answers “Who are you?” (login/JWT). Authorization answers “Are you allowed to do this action on this item?” Your capstone should do both.
- Enforce permissions in the backend/API.
  Hiding an Edit or Delete button is helpful for usability, but it is not security. Every protected API request must check permission and return 403 Forbidden if denied.
- Create a permission matrix.  
  Role	View	Create	Edit	Delete
  Viewer	✓	✗	✗	✗
  Editor	✓	✗	✓	✗
  Admin	✓	✓	✓	✓
- Keep authorization rules centralized.
  Avoid scattered if user.role === "admin" checks in every route. Put rules in one authorization module/policy so they are consistent, easier to change, test, and audit.
- Add resource-level rules for a more impressive project.
  For example: an Editor may edit only records in their own department, or may delete only comments they created. This shows that permissions can depend on both role and context.
- Log sensitive actions.
  Record who tried to create, edit, delete, or access sensitive data, when it happened, and whether it was allowed. This provides an audit trail.


create:
app/main.py
app/core/config.py
app/core/security.py
app/db/session.py
app/modules/auth/router.py
app/modules/auth/schemas.py
app/modules/auth/service.py
app/modules/users/model.py
app/modules/users/repository.py

Then get these working in order:
GET  /health
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/users/me

create db models in dependency order:
1. users
2. courses
3. enrollments
4. sessions
5. devices
6. checkins
7. risk_signals
8. audit_logs

Then run:
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
pytest tests/public/test_privacy_basic.py -v

| Part | What it contains | What it should not contain |
|---|---|---|
| `model.py` | SQLAlchemy table class: columns, foreign keys, constraints, relationships | HTTP request/response code |
| `schemas.py` | Pydantic models for incoming/outgoing API data | Database queries |
| `repository.py` | Database operations: create, get, update, list | Business/security decisions |
| `service.py` | Business rules: hashing, RBAC, checks, orchestration | Raw SQL or route decorators |
| `router.py` | FastAPI endpoints, status codes, request parsing, calling services | Complex business logic |