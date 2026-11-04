from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.modules.users import service
from app.modules.users.model import User
from app.modules.users.schemas import AdminUserUpdate, FaceEnrollRequest, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_me(db, current_user)


@router.put("/me")
def update_me(
    payload: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.update_me(db, current_user, payload, request)


@router.post("/me/face/enroll")
def enroll_face(
    payload: FaceEnrollRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.enroll_face(db, current_user, payload, request)


@router.get("/")
def list_users(
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    return service.list_users(db, role=role, is_active=is_active, search=search, limit=limit, offset=offset)


@router.get("/{user_id}")
def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.get_user(db, user_id, current_user)


@router.patch("/{user_id}")
def patch_user(
    user_id: str,
    payload: AdminUserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    return service.admin_update_user(db, user_id, payload, request)
