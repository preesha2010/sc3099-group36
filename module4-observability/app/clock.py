"""
One clock for the whole dashboard.

The API stores and returns UTC. The container also runs on UTC, so before
this module every "local" time in the dashboard was really UTC: a session
typed in as 00:15 on the Create form was saved as 00:15 UTC (07:15 in
Jakarta), and "today" rolled over at 07:00 local time.

Everything the dashboard shows or accepts now goes through SAIV_TZ, set in
docker-compose.yml. It is read with zoneinfo plus the tzdata package, so it
does not depend on what the container image happens to have installed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ZONE_NAME = os.getenv("SAIV_TZ") or "UTC"
try:
    LOCAL = ZoneInfo(ZONE_NAME)
except (ZoneInfoNotFoundError, ValueError):
    ZONE_NAME, LOCAL = "UTC", ZoneInfo("UTC")


def now() -> datetime:
    return datetime.now(LOCAL)


def parse(stamp: Optional[str]) -> Optional[datetime]:
    """API timestamp (UTC, with or without Z) -> aware local datetime."""
    if not stamp:
        return None
    parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL)


def fmt(stamp: Optional[str], pattern: str = "%Y-%m-%d %H:%M") -> str:
    parsed = parse(stamp)
    return parsed.strftime(pattern) if parsed else ""


def to_api(local_wall_clock: datetime) -> str:
    """
    A naive datetime typed in by the user, read as local time, sent as UTC.
    An aware datetime is converted as-is.
    """
    if local_wall_clock.tzinfo is None:
        local_wall_clock = local_wall_clock.replace(tzinfo=LOCAL)
    utc = local_wall_clock.astimezone(timezone.utc).replace(tzinfo=None)
    return utc.isoformat() + "Z"
