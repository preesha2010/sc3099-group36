from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.core.pagination import page_of
from app.modules.courses import repository as courses_repo
from app.modules.courses.model import Course
from app.modules.courses.schemas import CourseCreate, CourseResponse, CourseUpdate
from app.modules.users.model import User


def to_course_response(course: Course) -> dict[str, Any]:
    return CourseResponse.model_validate(course).model_dump()


def list_courses(
    db: Session,
    *,
    is_active: Optional[bool],
    semester: Optional[str],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    items, total, limit, offset = courses_repo.list_courses(
        db, is_active=is_active, semester=semester, limit=limit, offset=offset
    )
    return page_of([to_course_response(c) for c in items], total, limit, offset)


def get_course(db: Session, course_id: str) -> dict[str, Any]:
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found()
    return to_course_response(course)


def create_course(db: Session, payload: CourseCreate, current_user: User, request: Request) -> dict[str, Any]:
    if courses_repo.get_by_code(db, payload.code):
        raise bad_request("Course code already exists")
    course = courses_repo.create(db, Course(**payload.model_dump()))
    db.commit()
    db.refresh(course)
    return to_course_response(course)


def update_course(
    db: Session, course_id: str, payload: CourseUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found()
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    courses_repo.save(db, course)
    db.commit()
    db.refresh(course)
    return to_course_response(course)


def delete_course(db: Session, course_id: str, current_user: User, request: Request) -> None:
    course = courses_repo.get_by_id(db, course_id)
    if course is None:
        raise not_found()
    courses_repo.soft_delete(db, course)
    db.commit()
