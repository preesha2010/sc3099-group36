from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.schemas import SanitizedStr
from app.db.enums import UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: SanitizedStr
    role: UserRole = UserRole.STUDENT


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool = True
    camera_consent: bool = False
    geolocation_consent: bool = False
    face_enrolled: bool = False
    created_at: datetime
    scheduled_deletion_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: Optional[UserPublic] = None
