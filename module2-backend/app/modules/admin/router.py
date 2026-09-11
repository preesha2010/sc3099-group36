from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.admin import service
from app.modules.enrollments.schemas import EnrollmentCreate
from app.modules.sessions.schemas import SessionStatusUpdate
from app.modules.users.model import User
from app.modules.users.schemas import BulkUsersRequest

router = APIRouter(prefix="/admin", tags=["admin"])


@router.patch("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    return service.deactivate_user(db, user_id, current_user, request)


@router.patch("/users/{user_id}/activate")
def activate_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    return service.activate_user(db, user_id, current_user, request)


@router.post("/users/bulk", status_code=status.HTTP_201_CREATED)
def bulk_create_users(
    payload: BulkUsersRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    return service.bulk_create_users(db, payload, current_user, request)


@router.patch("/sessions/{session_id}/status")
def update_session_status(
    session_id: str,
    payload: SessionStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    return service.update_session_status(db, session_id, payload, current_user, request)


@router.post("/enrollments/", status_code=status.HTTP_201_CREATED)
def create_enrollment(
    payload: EnrollmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    return service.create_enrollment(db, payload, current_user, request)
