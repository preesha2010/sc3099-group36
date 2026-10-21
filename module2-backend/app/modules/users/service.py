from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.exceptions import bad_request, forbidden, not_found, service_unavailable
from app.core.pagination import page_of
from app.integrations.face_client import face_client
from app.db.enums import AuditAction, UserRole
from app.modules.enrollments import repository as enrollments_repo
from app.modules.users import repository as users_repo
from app.modules.users.model import User
from app.modules.users.schemas import AdminUserUpdate, FaceEnrollRequest, UserUpdate


def to_user_response(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "camera_consent": user.camera_consent,
        "geolocation_consent": user.geolocation_consent,
        "face_enrolled": user.face_enrolled,
        "created_at": user.created_at,
        "scheduled_deletion_at": user.scheduled_deletion_at,
    }


def get_me(db: Session, current_user: User) -> dict[str, Any]:
    return to_user_response(current_user)


def update_me(db: Session, current_user: User, payload: UserUpdate, request: Request) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    users_repo.save(db, current_user)
    append_audit(
        db,
        AuditAction.USER_UPDATED.value,
        user_id=current_user.id,
        resource_type="user",
        resource_id=current_user.id,
        request=request,
    )
    db.commit()
    db.refresh(current_user)
    return to_user_response(current_user)


def enroll_face(
    db: Session, current_user: User, payload: FaceEnrollRequest, request: Request
) -> dict[str, Any]:
    if not current_user.camera_consent:
        raise bad_request("Camera consent not given")
    result = face_client.enroll(current_user.id, payload.image, True)
    if result.kind in {"unavailable", "malformed"}:
        raise service_unavailable("Face recognition service unavailable")
    if result.kind == "client_error" or not result.data.get("enrollment_successful"):
        raise bad_request("No face detected")
    hash_value = result.data.get("face_template_hash")
    if not hash_value:
        raise service_unavailable("Face recognition service unavailable")
    current_user.face_embedding_hash = str(hash_value)
    current_user.face_enrolled = True
    users_repo.save(db, current_user)
    append_audit(
        db,
        AuditAction.FACE_ENROLLED.value,
        user_id=current_user.id,
        resource_type="user",
        resource_id=current_user.id,
        request=request,
    )
    db.commit()
    db.refresh(current_user)
    quality = result.data.get("quality_score")
    return {
        "success": True,
        "message": "Face enrolled successfully",
        "face_enrolled": True,
        "quality_score": float(quality) if quality is not None else None,
    }


def list_users(
    db: Session,
    *,
    role: Optional[str],
    is_active: Optional[bool],
    search: Optional[str],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    items, total, limit, offset = users_repo.list_users(
        db, role=role, is_active=is_active, search=search, limit=limit, offset=offset
    )
    return page_of([to_user_response(u) for u in items], total, limit, offset)


def get_user(db: Session, user_id: str, current_user: User) -> dict[str, Any]:
    """Admin, or an instructor viewing a student enrolled in a course they teach."""
    user = users_repo.get_by_id(db, user_id)
    if user is None:
        raise not_found()
    if current_user.role == UserRole.ADMIN.value:
        return to_user_response(user)
    if (
        current_user.role == UserRole.INSTRUCTOR.value
        and user.role == UserRole.STUDENT.value
        and enrollments_repo.instructor_teaches_enrolled_student(db, current_user.id, user.id)
    ):
        return to_user_response(user)
    raise forbidden()


def admin_update_user(
    db: Session, user_id: str, payload: AdminUserUpdate, request: Request
) -> dict[str, Any]:
    user = users_repo.get_by_id(db, user_id)
    if user is None:
        raise not_found()
    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"] is not None:
        role = data.pop("role")
        data["role"] = role.value if isinstance(role, UserRole) else role
    for field, value in data.items():
        setattr(user, field, value)
    users_repo.save(db, user)
    append_audit(
        db,
        AuditAction.USER_UPDATED.value,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
    )
    db.commit()
    db.refresh(user)
    return to_user_response(user)
