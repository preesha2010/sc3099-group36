from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.modules.stats import service
from app.modules.users.model import User

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview")
def overview(
    course_id: Optional[str] = None,
    days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin", "ta")),
):
    return service.overview(db, current_user, course_id=course_id, days=days)


@router.get("/sessions/{session_id}")
def session_stats(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "ta", "admin")),
):
    return service.session_stats(db, session_id, current_user)


@router.get("/courses/{course_id}")
def course_stats(
    course_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin")),
):
    return service.course_stats(db, course_id, current_user, start_date=start_date, end_date=end_date)


@router.get("/students/{student_id}")
def student_stats(
    student_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin", "ta")),
):
    return service.student_stats(db, student_id, current_user)
