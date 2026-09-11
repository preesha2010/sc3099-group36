from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.schemas import OptionalSanitizedStr, SanitizedStr
from app.db.enums import SessionStatus


class SessionCreate(BaseModel):
    course_id: str
    name: SanitizedStr
    session_type: str = "lecture"
    description: OptionalSanitizedStr = None
    scheduled_start: datetime
    scheduled_end: datetime
    checkin_opens_at: Optional[datetime] = None
    checkin_closes_at: Optional[datetime] = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    venue_name: OptionalSanitizedStr = None
    geofence_radius_meters: Optional[float] = None
    require_liveness_check: bool = True
    require_face_match: bool = False
    risk_threshold: Optional[float] = None


class SessionUpdate(BaseModel):
    name: OptionalSanitizedStr = None
    status: Optional[SessionStatus] = None
    checkin_closes_at: Optional[datetime] = None
    checkin_opens_at: Optional[datetime] = None
    venue_name: OptionalSanitizedStr = None
    venue_latitude: Optional[float] = None
    venue_longitude: Optional[float] = None
    geofence_radius_meters: Optional[float] = None
    require_liveness_check: Optional[bool] = None
    require_face_match: Optional[bool] = None
    risk_threshold: Optional[float] = None


class SessionStatusUpdate(BaseModel):
    status: SessionStatus
