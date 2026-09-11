from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.enrollments.schemas import EnrollmentCreate
from app.modules.sessions.schemas import SessionStatusUpdate
from app.modules.users.model import User
from app.modules.users.schemas import BulkUsersRequest


def deactivate_user(db: Session, user_id: str, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("PATCH /admin/users/{user_id}/deactivate")


def activate_user(db: Session, user_id: str, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("PATCH /admin/users/{user_id}/activate")


def bulk_create_users(db: Session, payload: BulkUsersRequest, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("POST /admin/users/bulk")


def update_session_status(
    db: Session, session_id: str, payload: SessionStatusUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    not_implemented("PATCH /admin/sessions/{session_id}/status")


def create_enrollment(
    db: Session, payload: EnrollmentCreate, current_user: User, request: Request
) -> dict[str, Any]:
    not_implemented("POST /admin/enrollments/")
