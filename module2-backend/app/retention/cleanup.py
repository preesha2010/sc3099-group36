"""Remove check-ins whose scheduled_deletion_at has passed.

SECURITY-REQUIREMENTS.md:
- Check-in records: 30 days via scheduled_deletion_at
- Audit logs: indefinite, immutable, never deleted here
- User PII: 30 days after account deletion — not implemented here (see report)

Risk signals reference checkins.id without ON DELETE CASCADE, so they are
removed in the same transaction before the parent check-in.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.utils import utcnow_naive
from app.modules.checkins.model import CheckIn
from app.modules.checkins.risk_signal import RiskSignal

logger = logging.getLogger("saiv.retention")


def purge_expired_checkins(db: Session, *, now: Optional[datetime] = None) -> dict[str, int]:
    """Delete expired check-ins and their risk signals. Idempotent. Does not touch audit logs or users."""
    cutoff = now or utcnow_naive()
    expired_ids = [
        checkin_id
        for (checkin_id,) in db.query(CheckIn.id)
        .filter(
            CheckIn.scheduled_deletion_at.isnot(None),
            CheckIn.scheduled_deletion_at <= cutoff,
        )
        .all()
    ]
    if not expired_ids:
        logger.info("retention cleanup: no expired check-ins")
        return {"checkins_deleted": 0, "risk_signals_deleted": 0}

    try:
        signals_deleted = (
            db.query(RiskSignal)
            .filter(RiskSignal.checkin_id.in_(expired_ids))
            .delete(synchronize_session=False)
        )
        checkins_deleted = (
            db.query(CheckIn)
            .filter(CheckIn.id.in_(expired_ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        db.expire_all()
    except Exception:
        db.rollback()
        logger.exception("retention cleanup rolled back after failure")
        raise

    result = {
        "checkins_deleted": int(checkins_deleted or 0),
        "risk_signals_deleted": int(signals_deleted or 0),
    }
    logger.info(
        "retention cleanup: checkins_deleted=%s risk_signals_deleted=%s",
        result["checkins_deleted"],
        result["risk_signals_deleted"],
    )
    return result
