from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.schemas import OptionalSanitizedStr, SanitizedStr


class CourseCreate(BaseModel):
    code: SanitizedStr
    name: SanitizedStr
    semester: SanitizedStr
    description: OptionalSanitizedStr = None
    venue_name: OptionalSanitizedStr = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: float = 100.0
    require_face_recognition: bool = False
    require_device_binding: bool = True
    risk_threshold: float = 0.5


class CourseUpdate(BaseModel):
    name: OptionalSanitizedStr = None
    description: OptionalSanitizedStr = None
    semester: OptionalSanitizedStr = None
    venue_name: OptionalSanitizedStr = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: Optional[float] = None
    require_face_recognition: Optional[bool] = None
    require_device_binding: Optional[bool] = None
    risk_threshold: Optional[float] = None
    is_active: Optional[bool] = None


class CourseResponse(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str] = None
    semester: str
    is_active: bool
    venue_latitude: Optional[float] = None
    venue_longitude: Optional[float] = None
    venue_name: Optional[str] = None
    geofence_radius_meters: Optional[float] = None
    require_face_recognition: bool = False
    require_device_binding: bool = True
    risk_threshold: float = 0.5
    created_at: datetime

    model_config = {"from_attributes": True}
