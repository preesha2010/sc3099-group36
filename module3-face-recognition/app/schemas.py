"""Pydantic request and response contracts for the face recognition service."""

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StrictBool


Score = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
TemplateHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FaceEnrollRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    image: str
    camera_consent: StrictBool = False


class FaceEnrollResponse(BaseModel):
    enrollment_successful: bool
    face_template_hash: str
    quality_score: float
    details: Dict[str, Any]


class FaceVerifyRequest(BaseModel):
    image: str
    reference_template_hash: TemplateHash


class FaceVerifyResponse(BaseModel):
    match_passed: bool
    match_score: float
    match_threshold: float
    face_detected: bool
    current_template_hash: str


class FaceMatchRequest(BaseModel):
    image: str
    reference_hash: TemplateHash


class LivenessRequest(BaseModel):
    challenge_response: str
    challenge_type: Literal["passive", "blink", "head_turn"] = "passive"


class LivenessResponse(BaseModel):
    liveness_passed: bool
    liveness_score: float
    liveness_threshold: float
    challenge_type: str
    face_embedding_hash: str
    details: Dict[str, Any]


class GeolocationData(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(ge=0, allow_inf_nan=False)


class RiskAssessRequest(BaseModel):
    liveness_score: Optional[Score] = None
    face_match_score: Optional[Score] = None
    device_signature: Optional[str] = Field(default=None, max_length=8192)
    device_public_key: Optional[str] = Field(default=None, max_length=8192)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, max_length=1024)
    geolocation: Optional[GeolocationData] = None


class RiskAssessResponse(BaseModel):
    risk_score: float
    risk_level: str
    pass_threshold: bool
    risk_threshold: float
    signal_breakdown: Dict[str, float]
    recommendations: List[str]
