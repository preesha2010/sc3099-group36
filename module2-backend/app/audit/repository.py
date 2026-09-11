import json
from datetime import datetime
from typing import Any, Optional, Sequence

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.model import AuditLog
from app.core.pagination import clamp_page
from app.core.utils import client_ip, utcnow_naive


def append_audit(
    db: Session,
    action: str,
    *,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    success: bool = True,
    details: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
    ip_address: Optional[str] = None,
    device_id: Optional[str] = None,
) -> AuditLog:
    ip = ip_address
    ua = None
    if request is not None:
        ip = ip or client_ip(request)
        ua = request.headers.get("user-agent")
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip,
        user_agent=ua[:500] if ua else None,
        device_id=device_id,
        details=json.dumps(details) if details else None,
        success=success,
        timestamp=utcnow_naive(),
    )
    db.add(log)
    db.flush()
    return log


def list_logs(
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
) -> tuple[Sequence[AuditLog], int, int, int]:
    """Append-only read. Never update or delete rows from Python."""
    limit, offset = clamp_page(limit, offset, default=100, max_limit=1000)
    query = db.query(AuditLog)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if success is not None:
        query = query.filter(AuditLog.success.is_(success))
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)
    total = query.count()
    items = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    return items, total, limit, offset
