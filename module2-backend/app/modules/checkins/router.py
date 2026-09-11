from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.middleware.rate_limit import rate_limit_checkin
from app.modules.checkins import service
from app.modules.checkins.schemas import AppealRequest, CheckinCreate, ReviewRequest
from app.modules.users.model import User

router = APIRouter(prefix="/checkins", tags=["checkins"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def submit_checkin(
    payload: CheckinCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("student")),
):
    rate_limit_checkin(current_user.id)
    return service.submit_checkin(db, payload, current_user, request)


@router.get("/")
def list_checkins(
    session_id: Optional[str] = None,
    course_id: Optional[str] = None,
    student_id: Optional[str] = None,
    status: Optional[str] = None,
    min_risk_score: Optional[float] = None,
    max_risk_score: Optional[float] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "ta", "admin")),
):
    return service.list_checkins(
        db,
        current_user,
        session_id=session_id,
        course_id=course_id,
        student_id=student_id,
        status=status,
        min_risk_score=min_risk_score,
        max_risk_score=max_risk_score,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@router.get("/my-checkins")
def my_checkins(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.my_checkins(db, current_user)


@router.get("/session/{session_id}")
def session_checkins(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("ta", "instructor", "admin")),
):
    return service.session_checkins(db, session_id, current_user)


@router.get("/flagged")
def flagged_checkins(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("ta", "instructor", "admin")),
):
    return service.flagged_checkins(db, current_user)


@router.get("/{checkin_id}")
def get_checkin(
    checkin_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.get_checkin(db, checkin_id, current_user)


@router.post("/{checkin_id}/appeal")
def appeal(
    checkin_id: str,
    payload: AppealRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("student")),
):
    return service.appeal(db, checkin_id, payload, current_user, request)


@router.post("/{checkin_id}/review")
def review(
    checkin_id: str,
    payload: ReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("ta", "instructor", "admin")),
):
    return service.review(db, checkin_id, payload, current_user, request)
