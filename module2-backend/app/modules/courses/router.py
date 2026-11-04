from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.modules.courses import service
from app.modules.courses.schemas import CourseCreate, CourseUpdate
from app.modules.users.model import User

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/")
def list_courses(
    is_active: Optional[bool] = True,
    semester: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return service.list_courses(db, is_active=is_active, semester=semester, limit=limit, offset=offset)


@router.get("/{course_id}")
def get_course(
    course_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return service.get_course(db, course_id)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    return service.create_course(db, payload, current_user, request)


@router.put("/{course_id}")
def update_course(
    course_id: str,
    payload: CourseUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    return service.update_course(db, course_id, payload, current_user, request)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    service.delete_course(db, course_id, current_user, request)
