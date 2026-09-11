from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.modules.enrollments import service
from app.modules.enrollments.schemas import BulkEnrollmentCreate, EnrollmentCreate
from app.modules.users.model import User

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("/my-enrollments")
def my_enrollments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.my_enrollments(db, current_user)


@router.get("/course/{course_id}")
def list_course_enrollments(
    course_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "ta", "admin")),
):
    return service.list_course_enrollments(db, course_id, current_user)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_enrollment(
    payload: EnrollmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin")),
):
    return service.create_enrollment(db, payload, current_user, request)


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
def bulk_enroll(
    payload: BulkEnrollmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("instructor", "admin")),
):
    return service.bulk_enroll(db, payload, current_user, request)


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def drop_enrollment(
    enrollment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service.drop_enrollment(db, enrollment_id, current_user, request)
