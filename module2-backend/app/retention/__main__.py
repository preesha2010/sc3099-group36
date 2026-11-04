"""One-shot cleanup: python -m app.retention

Does not run on API startup. Refuses PostgreSQL databases named `saiv`.
Schedule externally (cron / Task Scheduler / CronJob) against a non-saiv URL.
"""

from __future__ import annotations

import json
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.retention.cleanup import purge_expired_checkins
from app.retention.safety import is_shared_saiv_database


def main() -> int:
    settings = get_settings()
    if is_shared_saiv_database(settings.DATABASE_URL):
        print("refusing retention cleanup against the shared saiv database", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        result = purge_expired_checkins(db)
    finally:
        db.close()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
