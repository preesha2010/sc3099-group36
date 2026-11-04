from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, RefreshRequest, RegisterRequest
from app.modules.users.model import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    user = service.register_user(db, payload, request)
    return service.to_user_public(user)


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    return service.authenticate(db, payload, request)


@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    return service.refresh_tokens(db, payload.refresh_token)


@router.post("/logout")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.logout(db, current_user, request)
