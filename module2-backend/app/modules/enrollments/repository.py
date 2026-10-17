from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.modules.enrollments.model import Enrollment


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


def list_for_course(db: Session, course_id: str, *, active_only: bool = True) -> Sequence[Enrollment]:
    query = db.query(Enrollment).filter(Enrollment.course_id == course_id)
    if active_only:
        query = query.filter(Enrollment.is_active.is_(True))
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
