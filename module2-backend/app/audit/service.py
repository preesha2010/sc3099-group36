import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.audit import repository
from app.core.pagination import page_of


def list_audit_logs(
    db: Session,
    *,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    success: Optional[bool] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    items, total, limit, offset = repository.list_logs(
        db,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        success=success,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    payload = []
    for row in items:
        details = None
        if row.details:
            try:
                details = json.loads(row.details)
            except json.JSONDecodeError:
                details = row.details
        payload.append(
            {
                "id": row.id,
                "user_id": row.user_id,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
                "device_id": row.device_id,
                "details": details,
                "success": row.success,
                "timestamp": row.timestamp,
            }
        )
    return page_of(payload, total, limit, offset)
