from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.exceptions import bad_request, forbidden, not_found
from app.core.security import hash_password
from app.core.utils import utcnow_naive
from app.db.enums import AuditAction, UserRole
from app.modules.courses import repository as courses_repo
from app.modules.enrollments import repository as enrollments_repo
from app.modules.enrollments.model import Enrollment
from app.modules.enrollments.schemas import BulkEnrollmentCreate, EnrollmentCreate, EnrollmentResponse
from app.modules.users import repository as users_repo
from app.modules.users.model import User


def to_enrollment_response(enrollment: Enrollment) -> dict[str, Any]:
    return EnrollmentResponse.model_validate(enrollment).model_dump()


def my_enrollments(db: Session, current_user: User) -> Any:
    rows = enrollments_repo.list_for_student(db, current_user.id, active_only=False)
    items = []
    for row in rows:
        course = row.course or courses_repo.get_by_id(db, row.course_id)
        items.append(
            {
                "id": row.id,
                "course_id": row.course_id,
                "course_code": course.code if course else None,
                "course_name": course.name if course else None,
                "semester": course.semester if course else None,
                "enrolled_at": row.enrolled_at,
                "is_active": row.is_active,
            }
        )
    return items


def list_course_enrollments(db: Session, course_id: str, current_user: User) -> Any:
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found("Course not found")
    rows = enrollments_repo.list_for_course(db, course_id, active_only=True)
    students = []
    for row in rows:
        student = row.student or users_repo.get_by_id(db, row.student_id)
        students.append(
            {
                "id": row.id,
                "student_id": row.student_id,
                "student_email": student.email if student else None,
                "student_name": student.full_name if student else None,
                "enrolled_at": row.enrolled_at,
                "is_active": row.is_active,
                "face_enrolled": bool(student.face_enrolled) if student else False,
            }
        )
    return {
        "course_id": course.id,
        "course_code": course.code,
        "total_enrolled": len(students),
        "students": students,
    }


def create_enrollment(
    db: Session, payload: EnrollmentCreate, current_user: User, request: Request
) -> dict[str, Any]:
    student = users_repo.get_by_id(db, payload.student_id)
    if student is None:
        raise not_found("Student not found")
    course = courses_repo.get_by_id(db, payload.course_id)
    if course is None:
        raise not_found("Course not found")
    existing = enrollments_repo.get_by_student_course(db, payload.student_id, payload.course_id)
    if existing and existing.is_active:
        raise bad_request("Student already enrolled")
    if existing:
        existing.is_active = True
        existing.dropped_at = None
        enrollment = enrollments_repo.save(db, existing)
    else:
        enrollment = enrollments_repo.create(
            db,
            Enrollment(student_id=payload.student_id, course_id=payload.course_id, is_active=True),
        )
    append_audit(
        db,
        AuditAction.ENROLLMENT_ADDED.value,
        user_id=current_user.id,
        resource_type="enrollment",
        resource_id=enrollment.id,
        request=request,
    )
    db.commit()
    db.refresh(enrollment)
    return to_enrollment_response(enrollment)


def bulk_enroll(
    db: Session, payload: BulkEnrollmentCreate, current_user: User, request: Request
) -> dict[str, Any]:
    course = courses_repo.get_by_id(db, payload.course_id)
    if course is None:
        raise not_found("Course not found")
    enrolled = already_enrolled = not_found_count = created = 0
    details = []
    for email in payload.student_emails:
        address = str(email).lower()
        student = users_repo.get_by_email(db, address)
        if student is None and payload.create_accounts:
            student = users_repo.create(
                db,
                email=address,
                full_name=address.split("@")[0],
                hashed_password=hash_password("Changeme123"),
                role=UserRole.STUDENT.value,
            )
            created += 1
        if student is None:
            not_found_count += 1
            details.append({"email": address, "status": "not_found"})
            continue
        existing = enrollments_repo.get_by_student_course(db, student.id, payload.course_id)
        if existing and existing.is_active:
            already_enrolled += 1
            details.append({"email": address, "status": "already_enrolled"})
            continue
        if existing:
            existing.is_active = True
            existing.dropped_at = None
            enrollments_repo.save(db, existing)
        else:
            enrollments_repo.create(db, Enrollment(student_id=student.id, course_id=payload.course_id))
        enrolled += 1
        details.append({"email": address, "status": "enrolled"})
    append_audit(
        db,
        AuditAction.ENROLLMENT_ADDED.value,
        user_id=current_user.id,
        resource_type="course",
        resource_id=payload.course_id,
        details={"bulk": True},
        request=request,
    )
    db.commit()
    return {
        "enrolled": enrolled,
        "already_enrolled": already_enrolled,
        "not_found": not_found_count,
        "created": created,
        "details": details,
    }


def drop_enrollment(db: Session, enrollment_id: str, current_user: User, request: Request) -> None:
    enrollment = enrollments_repo.get_by_id(db, enrollment_id)
    if enrollment is None:
        raise not_found()
    if current_user.role not in {UserRole.ADMIN.value, UserRole.INSTRUCTOR.value, UserRole.TA.value}:
        if enrollment.student_id != current_user.id:
            raise forbidden()
    enrollment.is_active = False
    enrollment.dropped_at = utcnow_naive()
    enrollments_repo.save(db, enrollment)
    append_audit(
        db,
        AuditAction.ENROLLMENT_REMOVED.value,
        user_id=current_user.id,
        resource_type="enrollment",
        resource_id=enrollment.id,
        request=request,
    )
    db.commit()
