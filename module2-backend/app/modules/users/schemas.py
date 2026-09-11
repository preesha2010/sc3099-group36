from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.core.schemas import OptionalSanitizedStr
from app.db.enums import UserRole


class UserResponse(BaseModel):
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


class UserUpdate(BaseModel):
    full_name: OptionalSanitizedStr = None
    camera_consent: Optional[bool] = None
    geolocation_consent: Optional[bool] = None


class AdminUserUpdate(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    full_name: OptionalSanitizedStr = None


class FaceEnrollRequest(BaseModel):
    image: str


class FaceEnrollResponse(BaseModel):
    success: bool
    message: str
    face_enrolled: bool
    quality_score: Optional[float] = None


class UserListResponse(BaseModel):
    items: List[dict]
    total: int
    limit: int
    offset: int


class BulkUsersRequest(BaseModel):
    users: List[dict]
