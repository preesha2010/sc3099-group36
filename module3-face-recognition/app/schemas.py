"""Pydantic request and response contracts for the face recognition service."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class FaceEnrollRequest(BaseModel):
    user_id: str
    image: str
    camera_consent: bool = False


class FaceEnrollResponse(BaseModel):
    enrollment_successful: bool
    face_template_hash: str
    quality_score: float
    details: Dict[str, Any]


class FaceVerifyRequest(BaseModel):
    image: str
    reference_template_hash: str


class FaceVerifyResponse(BaseModel):
    match_passed: bool
    match_score: float
    match_threshold: float
    face_detected: bool
    current_template_hash: str


class FaceMatchRequest(BaseModel):
    image: str
    reference_hash: str


class LivenessRequest(BaseModel):
    challenge_response: str
    challenge_type: str = "blink"


class LivenessResponse(BaseModel):
    liveness_passed: bool
    liveness_score: float
    liveness_threshold: float
    challenge_type: str
    face_embedding_hash: str
    details: Dict[str, Any]


class GeolocationData(BaseModel):
    latitude: float
    longitude: float
    accuracy: float


class RiskAssessRequest(BaseModel):
    liveness_score: Optional[float] = None
    face_match_score: Optional[float] = None
    device_signature: Optional[str] = None
    device_public_key: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    geolocation: Optional[GeolocationData] = None


class RiskAssessResponse(BaseModel):
    risk_score: float
    risk_level: str
    pass_threshold: bool
    risk_threshold: float
    signal_breakdown: Dict[str, float]
    recommendations: List[str]
