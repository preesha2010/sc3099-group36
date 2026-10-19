from typing import Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.modules.enrollments.model import Enrollment
from app.modules.users.model import User


def get_by_id(db: Session, enrollment_id: str) -> Optional[Enrollment]:
    return db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()


def get_by_student_course(db: Session, student_id: str, course_id: str) -> Optional[Enrollment]:
    return (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.course_id == course_id)
        .first()
    )


def list_for_student(db: Session, student_id: str, *, active_only: bool = True) -> Sequence[Enrollment]:
    query = db.query(Enrollment).filter(Enrollment.student_id == student_id)
    if active_only:
        query = query.filter(Enrollment.is_active.is_(True))
    return query.all()


def list_for_course(
    db: Session,
    course_id: str,
    *,
    active_only: bool = True,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
) -> Sequence[Enrollment]:
    query = db.query(Enrollment).filter(Enrollment.course_id == course_id)
    status_filter = is_active if is_active is not None else (True if active_only else None)
    if status_filter is not None:
        query = query.filter(Enrollment.is_active.is_(status_filter))
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        query = query.join(User, User.id == Enrollment.student_id).filter(
            or_(User.full_name.ilike(like), User.email.ilike(like))
        )
    else:
        query = query.options(joinedload(Enrollment.student))
    return query.all()


def create(db: Session, enrollment: Enrollment) -> Enrollment:
    db.add(enrollment)
    db.flush()
    return enrollment


def save(db: Session, enrollment: Enrollment) -> Enrollment:
    db.add(enrollment)
    db.flush()
    return enrollment


def is_enrolled(db: Session, student_id: str, course_id: str) -> bool:
    row = get_by_student_course(db, student_id, course_id)
    return bool(row and row.is_active)


def instructor_teaches_course(db: Session, instructor_id: str, course_id: str) -> bool:
    from app.modules.sessions.model import ClassSession

    row = (
        db.query(ClassSession.id)
        .filter(ClassSession.course_id == course_id, ClassSession.instructor_id == instructor_id)
        .first()
    )
    return row is not None


def user_manages_course(db: Session, user, course_id: str) -> bool:
    """Admin, or instructor who has at least one session on this course.

    Teaching is defined by sessions.instructor_id; there is no course-level
    instructor foreign key in the recommended schema.
    """
    from app.db.enums import UserRole

    if user.role == UserRole.ADMIN.value:
        return True
    if user.role == UserRole.INSTRUCTOR.value:
        return instructor_teaches_course(db, user.id, course_id)
    return False


def user_can_view_course_roster(db: Session, user, course_id: str) -> bool:
    """Roster access: admin, teaching instructor, or TA.

    The spec says instructor/TA for the course. There is no TA–course table, so
    TA is role-level (any TA). Instructors are scoped via sessions.instructor_id.
    """
    from app.db.enums import UserRole

    if user.role == UserRole.TA.value:
        return True
    return user_manages_course(db, user, course_id)


def instructor_teaches_enrolled_student(db: Session, instructor_id: str, student_id: str) -> bool:
    """True when the student has an active enrollment in a course this instructor teaches."""
    from app.modules.sessions.model import ClassSession

    row = (
        db.query(Enrollment.id)
        .join(ClassSession, ClassSession.course_id == Enrollment.course_id)
        .filter(
            Enrollment.student_id == student_id,
            Enrollment.is_active.is_(True),
            ClassSession.instructor_id == instructor_id,
        )
        .first()
    )
    return row is not None
