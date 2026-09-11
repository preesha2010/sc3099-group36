from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_current_user_optional, require_roles
from app.db.session import get_db
from app.modules.sessions import service
from app.modules.sessions.schemas import SessionCreate, SessionUpdate
from app.modules.users.model import User

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/")
def list_sessions(
    status: Optional[str] = None,
    course_id: Optional[str] = None,
    instructor_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin", "ta")),
):
    return service.list_sessions(
        db,
        current_user,
        status=status,
        course_id=course_id,
        instructor_id=instructor_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@router.get("/active")
def list_active(db: Session = Depends(get_db)):
    return service.list_active(db)


@router.get("/my-sessions")
def my_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.my_sessions(db, current_user)


@router.get("/{session_id}")
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    return service.get_session(db, session_id, current_user)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin")),
):
    return service.create_session(db, payload, current_user, request)


@router.patch("/{session_id}")
def update_session(
    session_id: str,
    payload: SessionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin", "ta")),
):
    return service.update_session(db, session_id, payload, current_user, request)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin")),
):
    service.delete_session(db, session_id, current_user, request)
