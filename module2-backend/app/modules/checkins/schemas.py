from typing import Optional

from pydantic import BaseModel, Field

from app.core.schemas import OptionalSanitizedStr, SanitizedStr
from app.db.enums import CheckinStatus


class CheckinCreate(BaseModel):
    session_id: str
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location_accuracy_meters: Optional[float] = None
    device_fingerprint: Optional[str] = None
    liveness_challenge_response: Optional[str] = None
    qr_code: Optional[str] = None


class AppealRequest(BaseModel):
    appeal_reason: SanitizedStr


class ReviewRequest(BaseModel):
    status: CheckinStatus
    review_notes: OptionalSanitizedStr = None
