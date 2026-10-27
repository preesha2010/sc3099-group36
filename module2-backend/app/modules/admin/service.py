from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.exceptions import bad_request, not_found
from app.core.security import hash_password
from app.core.utils import sanitize_text, utcnow_naive
from app.db.enums import AuditAction, SessionStatus, UserRole
from app.modules.courses import repository as courses_repo
from app.modules.courses.instructor_model import CourseInstructor
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


def _assignment_payload(row: CourseInstructor, instructor: Optional[User] = None) -> dict[str, Any]:
    person = instructor if instructor is not None else row.instructor
    return {
        "id": row.id,
        "course_id": row.course_id,
        "instructor_id": row.instructor_id,
        "instructor_email": person.email if person is not None else None,
        "instructor_name": person.full_name if person is not None else None,
        "is_active": row.is_active,
        "assigned_at": row.assigned_at,
    }


def assign_course_instructor(
    db: Session, course_id: str, instructor_id: str, current_user: User, request: Request
) -> dict[str, Any]:
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found("Course not found")
    instructor = users_repo.get_by_id(db, instructor_id)
    if instructor is None:
        raise not_found("Instructor not found")
    if instructor.role != UserRole.INSTRUCTOR.value:
        raise bad_request("User is not an instructor")
    row = courses_repo.get_assignment(db, course_id, instructor_id)
    created = False
    if row is None:
        row = CourseInstructor(
            course_id=course_id,
            instructor_id=instructor_id,
            is_active=True,
            assigned_by_id=current_user.id,
        )
        created = True
    else:
        row.is_active = True
        row.assigned_by_id = current_user.id
        row.assigned_at = utcnow_naive()
    courses_repo.save_assignment(db, row)
    append_audit(
        db,
        AuditAction.COURSE_INSTRUCTOR_ASSIGNED.value,
        user_id=current_user.id,
        resource_type="course",
        resource_id=course_id,
        details={"instructor_id": instructor_id},
        request=request,
    )
    db.commit()
    db.refresh(row)
    payload = _assignment_payload(row, instructor)
    payload["created"] = created
    payload["message"] = "Instructor assigned to course"
    return payload


def revoke_course_instructor(
    db: Session, course_id: str, instructor_id: str, current_user: User, request: Request
) -> dict[str, Any]:
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found("Course not found")
    row = courses_repo.get_assignment(db, course_id, instructor_id)
    if row is None:
        raise not_found("Assignment not found")
    row.is_active = False
    courses_repo.save_assignment(db, row)
    append_audit(
        db,
        AuditAction.COURSE_INSTRUCTOR_REVOKED.value,
        user_id=current_user.id,
        resource_type="course",
        resource_id=course_id,
        details={"instructor_id": instructor_id},
        request=request,
    )
    db.commit()
    db.refresh(row)
    instructor = users_repo.get_by_id(db, instructor_id)
    payload = _assignment_payload(row, instructor)
    payload["message"] = "Instructor revoked from course"
    return payload


def list_course_instructors(db: Session, course_id: str) -> dict[str, Any]:
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found("Course not found")
    rows = courses_repo.list_assignments(db, course_id)
    return {
        "course_id": course_id,
        "instructors": [_assignment_payload(row) for row in rows],
    }
