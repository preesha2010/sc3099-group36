from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.enrollments.schemas import BulkEnrollmentCreate, EnrollmentCreate
from app.modules.users.model import User


def my_enrollments(db: Session, current_user: User) -> Any:
    not_implemented("GET /enrollments/my-enrollments")


def list_course_enrollments(db: Session, course_id: str, current_user: User) -> Any:
    not_implemented("GET /enrollments/course/{course_id}")


def create_enrollment(
    db: Session, payload: EnrollmentCreate, current_user: User, request: Request
) -> dict[str, Any]:
    not_implemented("POST /enrollments/")


def bulk_enroll(
    db: Session, payload: BulkEnrollmentCreate, current_user: User, request: Request
) -> dict[str, Any]:
    not_implemented("POST /enrollments/bulk")


def drop_enrollment(db: Session, enrollment_id: str, current_user: User, request: Request) -> None:
    not_implemented("DELETE /enrollments/{enrollment_id}")
