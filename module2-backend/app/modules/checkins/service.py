from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.checkins.schemas import AppealRequest, CheckinCreate, ReviewRequest
from app.modules.users.model import User


def submit_checkin(db: Session, payload: CheckinCreate, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("POST /checkins/")


def list_checkins(
    db: Session,
    current_user: User,
    *,
    session_id: Optional[str],
    course_id: Optional[str],
    student_id: Optional[str],
    status: Optional[str],
    min_risk_score: Optional[float],
    max_risk_score: Optional[float],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    not_implemented("GET /checkins/")


def my_checkins(db: Session, current_user: User) -> Any:
    not_implemented("GET /checkins/my-checkins")


def session_checkins(db: Session, session_id: str, current_user: User) -> Any:
    not_implemented("GET /checkins/session/{session_id}")


def flagged_checkins(db: Session, current_user: User) -> Any:
    not_implemented("GET /checkins/flagged")


def get_checkin(db: Session, checkin_id: str, current_user: User) -> dict[str, Any]:
    not_implemented("GET /checkins/{checkin_id}")


def appeal(db: Session, checkin_id: str, payload: AppealRequest, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("POST /checkins/{checkin_id}/appeal")


def review(db: Session, checkin_id: str, payload: ReviewRequest, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("POST /checkins/{checkin_id}/review")
