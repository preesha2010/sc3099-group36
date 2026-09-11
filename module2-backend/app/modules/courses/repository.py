from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.core.pagination import clamp_page
from app.core.utils import utcnow_naive
from app.modules.courses.model import Course


def get_by_id(db: Session, course_id: str) -> Optional[Course]:
    return db.query(Course).filter(Course.id == course_id).first()


def get_by_code(db: Session, code: str) -> Optional[Course]:
    return db.query(Course).filter(Course.code == code).first()


def create(db: Session, course: Course) -> Course:
    db.add(course)
    db.flush()
    return course


def save(db: Session, course: Course) -> Course:
    course.updated_at = utcnow_naive()
    db.add(course)
    db.flush()
    return course


def soft_delete(db: Session, course: Course) -> Course:
    course.is_active = False
    return save(db, course)


def list_courses(
    db: Session,
    *,
    is_active: Optional[bool] = True,
    semester: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Course], int, int, int]:
    limit, offset = clamp_page(limit, offset)
    query = db.query(Course)
    if is_active is not None:
        query = query.filter(Course.is_active.is_(is_active))
    if semester:
        query = query.filter(Course.semester == semester)
    total = query.count()
    items = query.order_by(Course.code.asc()).offset(offset).limit(limit).all()
    return items, total, limit, offset
