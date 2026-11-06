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
    ├── retention/              # check-in 30-day cleanup (CLI only, not on API start)
    │   ├── cleanup.py          # purge_expired_checkins
    │   └── safety.py           # refuses PostgreSQL database name `saiv`
    │
    └── middleware/
        └── rate_limit.py

## Data retention cleanup

SECURITY-REQUIREMENTS.md keeps check-ins for 30 days (`scheduled_deletion_at`)
and keeps audit logs forever. `python -m app.retention` deletes expired
check-ins and their `risk_signals` in one transaction. It does **not** delete
users, audit logs, or the shared `saiv` database.

Cleanup is **not** started by the API. There is no in-process scheduler and no
HTTP cleanup endpoint. Nothing is deleted unless an operator runs the CLI
against a non-`saiv` `DATABASE_URL`.

External schedule (cron, Task Scheduler, or a CronJob), daily example:

```
cd module2-backend
DATABASE_URL=postgresql://.../saiv_prod python -m app.retention
```

The CLI exits `2` if `DATABASE_URL` names PostgreSQL database `saiv`. Successful
runs log `checkins_deleted` / `risk_signals_deleted` and print the same JSON.

User PII is documented as “30 days after deletion”, but accounts currently set
`scheduled_deletion_at` at creation and there is no account-deletion API.
User rows are not purged until that policy is decided.

## Client IP and `X-Forwarded-For`

Singapore-only check-ins and IP rate limits use `client_ip()`. By default
`TRUSTED_PROXY_IPS` is empty, so client-supplied `X-Forwarded-For` is ignored
and the TCP peer is used. Local Docker / M1 traffic (private or loopback peer,
no proxy) stays allowed; GPS and the Singapore bounding box are unchanged.

To honour forwarded headers, set `TRUSTED_PROXY_IPS` to the reverse proxy's
IP or CIDR (comma-separated). The header is read only when the connecting peer
matches that list. Walk the chain from the right and skip trusted hops; a
boolean "trust XFF" flag is not supported.

Uvicorn 0.27 defaults `proxy_headers=True` and trusts `127.0.0.1`, which would
rewrite `request.client` from a spoofed header before M2 runs. The Dockerfile
passes `--no-proxy-headers`. Local `uvicorn` must do the same. Do not enable
`--proxy-headers` or `FORWARDED_ALLOW_IPS=*` unless a real reverse proxy is in
front and `TRUSTED_PROXY_IPS` lists it.
