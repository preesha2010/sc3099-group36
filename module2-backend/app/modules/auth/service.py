from typing import Any

from fastapi import HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.utils import sanitize_text, utcnow_naive
from app.db.enums import AuditAction, UserRole
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.users import repository as users_repo
from app.modules.users.model import User
from app.modules.users.service import to_user_response

settings = get_settings()


def to_user_public(user: User) -> dict[str, Any]:
    return to_user_response(user)


def register_user(db: Session, payload: RegisterRequest, request: Request) -> User:
    existing = users_repo.get_by_email(db, str(payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    role = payload.role.value if isinstance(payload.role, UserRole) else str(payload.role)
    user = users_repo.create(
        db,
        email=str(payload.email),
        full_name=sanitize_text(payload.full_name) or payload.full_name,
        hashed_password=hash_password(payload.password),
        role=role,
        is_active=True,
    )
    append_audit(
        db,
        AuditAction.USER_CREATED.value,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
    )
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, payload: LoginRequest, request: Request) -> dict[str, Any]:
    email = str(payload.email).lower()
    user = users_repo.get_by_email(db, email)
    if user and user.is_locked:
        append_audit(
            db,
            AuditAction.LOGIN_FAILED.value,
            user_id=user.id,
            success=False,
            details={"reason": "locked"},
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=429, detail="Account locked")

    if user and not user.is_active:
        append_audit(
            db,
            AuditAction.LOGIN_FAILED.value,
            user_id=user.id,
            success=False,
            details={"reason": "inactive"},
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    if user is None or not verify_password(payload.password, user.hashed_password):
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.ACCOUNT_LOCKOUT_ATTEMPTS:
                user.is_locked = True
            append_audit(
                db,
                AuditAction.LOGIN_FAILED.value,
                user_id=user.id,
                success=False,
                details={"reason": "invalid_password", "attempts": user.failed_login_count},
                request=request,
            )
            db.commit()
            if user.is_locked:
                raise HTTPException(status_code=429, detail="Account locked")
        else:
            append_audit(
                db,
                AuditAction.LOGIN_FAILED.value,
                success=False,
                details={"reason": "unknown_email", "email": email},
                request=request,
            )
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user.failed_login_count = 0
    user.is_locked = False
    user.last_login_at = utcnow_naive()
    append_audit(
        db,
        AuditAction.LOGIN_SUCCESS.value,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
    )
    db.commit()
    access = create_access_token(user.id, user.email, user.role)
    refresh = create_refresh_token(user.id, user.email, user.role)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": to_user_public(user),
    }


def refresh_tokens(db: Session, refresh_token: str) -> dict[str, Any]:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    user = users_repo.get_by_id(db, payload.get("sub"))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    return {
        "access_token": create_access_token(user.id, user.email, user.role),
        "refresh_token": create_refresh_token(user.id, user.email, user.role),
        "token_type": "bearer",
    }


def logout(db: Session, current_user: User, request: Request) -> dict[str, str]:
    append_audit(
        db,
        AuditAction.LOGOUT.value,
        user_id=current_user.id,
        resource_type="user",
        resource_id=current_user.id,
        request=request,
    )
    db.commit()
    return {"message": "logged out"}
