from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.core.pagination import clamp_page
from app.core.utils import utcnow_naive
from app.modules.users.model import User


def get_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def get_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower()).first()


def create(
    db: Session,
    *,
    email: str,
    full_name: str,
    hashed_password: str,
    role: str,
    is_active: bool = True,
) -> User:
    user = User(
        email=email.lower(),
        full_name=full_name,
        hashed_password=hashed_password,
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def save(db: Session, user: User) -> User:
    user.updated_at = utcnow_naive()
    db.add(user)
    db.flush()
    return user


def list_users(
    db: Session,
    *,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[User], int, int, int]:
    limit, offset = clamp_page(limit, offset)
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    if search:
        like = f"%{search}%"
        query = query.filter((User.full_name.ilike(like)) | (User.email.ilike(like)))
    total = query.count()
    items = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return items, total, limit, offset
