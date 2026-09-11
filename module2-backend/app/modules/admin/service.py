from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.exceptions import not_found
from app.core.security import hash_password
from app.core.utils import sanitize_text
from app.db.enums import AuditAction, SessionStatus, UserRole
from app.modules.enrollments.schemas import EnrollmentCreate
from app.modules.enrollments.service import create_enrollment as enroll_student
from app.modules.sessions import repository as sessions_repo
from app.modules.sessions.schemas import SessionStatusUpdate
from app.modules.users import repository as users_repo
from app.modules.users.model import User
from app.modules.users.schemas import BulkUsersRequest
from app.modules.users.service import to_user_response


def deactivate_user(db: Session, user_id: str, current_user: User, request: Request) -> dict[str, Any]:
    user = users_repo.get_by_id(db, user_id)
    if user is None:
        raise not_found()
    user.is_active = False
    users_repo.save(db, user)
    append_audit(
        db,
        AuditAction.USER_UPDATED.value,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        details={"is_active": False},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "message": "User deactivated successfully",
    }


def activate_user(db: Session, user_id: str, current_user: User, request: Request) -> dict[str, Any]:
    user = users_repo.get_by_id(db, user_id)
    if user is None:
        raise not_found()
    user.is_active = True
    user.is_locked = False
    user.failed_login_count = 0
    users_repo.save(db, user)
    append_audit(
        db,
        AuditAction.USER_UPDATED.value,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        details={"is_active": True},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "message": "User activated successfully",
    }


def bulk_create_users(db: Session, payload: BulkUsersRequest, current_user: User, request: Request) -> dict[str, Any]:
    created_users = []
    errors = []
    for raw in payload.users:
        email = str(raw.get("email", "")).lower()
        password = raw.get("password") or ""
        full_name = sanitize_text(raw.get("full_name")) or raw.get("full_name") or email
        role = raw.get("role") or UserRole.STUDENT.value
        if isinstance(role, UserRole):
            role = role.value
        if not email or not password:
            errors.append({"email": email, "error": "email and password are required"})
            continue
        if users_repo.get_by_email(db, email):
            errors.append({"email": email, "error": "Email already registered"})
            continue
        user = users_repo.create(
            db,
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
            role=str(role),
        )
        created_users.append(user)
    append_audit(
        db,
        AuditAction.USER_CREATED.value,
        user_id=current_user.id,
        resource_type="user",
        details={"created": len(created_users), "failed": len(errors)},
        request=request,
    )
    db.commit()
    for user in created_users:
        db.refresh(user)
    return {
        "created": len(created_users),
        "failed": len(errors),
        "users": [to_user_response(user) for user in created_users],
        "errors": errors,
    }


def update_session_status(
    db: Session, session_id: str, payload: SessionStatusUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    session = sessions_repo.get_by_id(db, session_id)
    if session is None:
        raise not_found()
    previous = session.status
    session.status = payload.status.value if isinstance(payload.status, SessionStatus) else str(payload.status)
    sessions_repo.save(db, session)
    append_audit(
        db,
        AuditAction.SESSION_UPDATED.value,
        user_id=current_user.id,
        resource_type="session",
        resource_id=session.id,
        details={"from": previous, "to": session.status},
        request=request,
    )
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "name": session.name,
        "status": session.status,
        "message": f"Session status changed from '{previous}' to '{session.status}'",
    }


def create_enrollment(
    db: Session, payload: EnrollmentCreate, current_user: User, request: Request
) -> dict[str, Any]:
    return enroll_student(db, payload, current_user, request)
