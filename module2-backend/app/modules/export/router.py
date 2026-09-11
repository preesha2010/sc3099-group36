from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.export import service
from app.modules.users.model import User

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/attendance/{course_id}")
def attendance_export(
    course_id: str,
    request: Request,
    format: str = Query(default="csv", alias="format"),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin")),
):
    return service.attendance_export(
        db, course_id, current_user, request, fmt=format, start_date=start_date, end_date=end_date
    )


@router.get("/session/{session_id}")
def session_export(
    session_id: str,
    request: Request,
    format: str = Query(default="csv", alias="format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin", "ta")),
):
    return service.session_export(db, session_id, current_user, request, fmt=format)
