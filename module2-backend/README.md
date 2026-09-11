module2-backend/
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
└── app/
    ├── main.py                 # CORS, rate limit, /health, mount /api/v1
    ├── api_router.py           # includes every module router
    │
    ├── core/
    │   ├── config.py
    │   ├── security.py         # bcrypt + JWT
    │   ├── dependencies.py     # get_current_user, require_roles
    │   ├── redis.py
    │   ├── pagination.py       # {items, total, limit, offset}
    │   ├── exceptions.py       # 400/401/403/404 + not_implemented(501)
    │   ├── schemas.py
    │   └── utils.py
    │
    ├── db/
    │   ├── base.py
    │   ├── enums.py
    │   ├── models.py           # imports all ORM tables for Alembic/create_all
    │   └── session.py          # get_db  (alias — not modules.sessions)
    │
    ├── modules/
    │   ├── auth/               # no model.py — uses users
    │   │   ├── router.py
    │   │   ├── schemas.py
    │   │   └── service.py      # implemented
    │   │
    │   ├── users/
    │   │   ├── router.py
    │   │   ├── schemas.py
    │   │   ├── model.py
    │   │   ├── repository.py   # implemented
    │   │   └── service.py      # get_me done; rest is yours
    │   │
    │   ├── courses/            # router, schemas, model, repository, service
    │   ├── enrollments/
    │   ├── sessions/           # model class is ClassSession (table: sessions)
    │   ├── devices/
    │   ├── checkins/
    │   │   ├── router.py
    │   │   ├── schemas.py
    │   │   ├── model.py        # CheckIn
    │   │   ├── risk_signal.py  # RiskSignal table
    │   │   ├── repository.py
    │   │   ├── risk_service.py # fill GPS/device/liveness scoring
    │   │   └── service.py      # check-in workflow
    │   │
    │   ├── stats/              # no table
    │   ├── export/             # HTTP prefix /export (singular, matches spec)
    │   └── admin/              # testing façade; calls other repos
    │
    ├── audit/                  # cross-cutting, append-only
    │   ├── router.py           # GET /audit/  (implemented)
    │   ├── schemas.py
    │   ├── model.py
    │   ├── repository.py       # append + list; never update/delete
    │   └── service.py
    │
    ├── integrations/
    │   └── face_client.py
    │
    └── middleware/
        └── rate_limit.py
