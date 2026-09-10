"""SAIV Module 3 HTTP API: face enrollment, verification, liveness, and risk."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import (
    FaceEnrollRequest,
    FaceEnrollResponse,
    FaceMatchRequest,
    FaceVerifyRequest,
    FaceVerifyResponse,
    LivenessRequest,
    LivenessResponse,
    RiskAssessRequest,
    RiskAssessResponse,
)
from app.services.face import detect_face, extract_face_embedding, generate_face_hash
from app.services.image import calculate_quality_score, decode_base64_image
from app.services.liveness import assess_passive_liveness
from app.services.risk import assess_risk


app = FastAPI(
    title="SAIV Face Recognition Service",
    description="Face enrollment, verification, liveness detection, and risk assessment service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Return the minimal service-health contract used by Docker and public tests."""
    return {"status": "healthy", "service": "face-recognition"}


@app.get("/")
async def root():
    """List the public endpoints exposed by this internal microservice."""
    return {
        "service": "SAIV Face Recognition & Risk Service",
        "version": "1.0.0",
        "endpoints": [
            "/health",
            "/face/enroll",
            "/face/verify",
            "/face/match",
            "/liveness/check",
            "/risk/assess",
        ],
    }


@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
async def enroll_face(request: FaceEnrollRequest):
    """Create the privacy-preserving face-template hash for one enrolled user."""
    if not request.camera_consent:
        raise HTTPException(status_code=400, detail="Camera consent is required for face enrollment")

    image_array = decode_base64_image(request.image)
    detection = detect_face(image_array)
    if detection is None:
        raise HTTPException(status_code=400, detail="No face detected")

    quality_score, image_quality = calculate_quality_score(image_array, detection)
    if quality_score < 0.5:
        raise HTTPException(status_code=400, detail="Face image quality is too low")

    embedding = extract_face_embedding(image_array, detection)
    face_template_hash = generate_face_hash(embedding)
    del image_array, embedding
    return FaceEnrollResponse(
        enrollment_successful=True,
        face_template_hash=face_template_hash,
        quality_score=quality_score,
        details={
            "face_detected": True,
            "face_detection_confidence": float(detection["confidence"]),
            "image_quality": image_quality,
        },
    )


@app.post("/face/verify", response_model=FaceVerifyResponse)
async def verify_face(request: FaceVerifyRequest):
    """Compare a submitted image against the hash previously returned at enrollment."""
    image_array = decode_base64_image(request.image)
    detection = detect_face(image_array)
    if detection is None:
        return FaceVerifyResponse(
            match_passed=False,
            match_score=0.0,
            match_threshold=0.70,
            face_detected=False,
            current_template_hash="",
        )

    embedding = extract_face_embedding(image_array, detection)
    current_template_hash = generate_face_hash(embedding)
    match_score = 1.0 if current_template_hash == request.reference_template_hash else 0.0
    del image_array, embedding
    return FaceVerifyResponse(
        match_passed=match_score >= 0.70,
        match_score=match_score,
        match_threshold=0.70,
        face_detected=True,
        current_template_hash=current_template_hash,
    )


@app.post("/face/match")
async def match_face(request: FaceMatchRequest):
    """Preserve the documented legacy request and response format."""
    result = await verify_face(
        FaceVerifyRequest(image=request.image, reference_template_hash=request.reference_hash)
    )
    return {
        "match_passed": result.match_passed,
        "match_score": result.match_score,
        "face_embedding_hash": result.current_template_hash,
    }


@app.post("/liveness/check", response_model=LivenessResponse)
async def check_liveness(request: LivenessRequest):
    """Perform the documented single-image passive liveness check."""
    if request.challenge_type not in {"passive", "blink", "head_turn"}:
        raise HTTPException(status_code=400, detail="Unsupported liveness challenge type")

    image_array = decode_base64_image(request.challenge_response)
    detection = detect_face(image_array)
    if detection is None:
        return LivenessResponse(
            liveness_passed=False,
            liveness_score=0.0,
            liveness_threshold=0.60,
            challenge_type=request.challenge_type,
            face_embedding_hash="",
            details={"face_detected": False, "challenge_type": request.challenge_type},
        )

    liveness_passed, liveness_score, face_embedding_hash, details = assess_passive_liveness(image_array, detection)
    del image_array
    return LivenessResponse(
        liveness_passed=liveness_passed,
        liveness_score=liveness_score,
        liveness_threshold=0.60,
        challenge_type=request.challenge_type,
        face_embedding_hash=face_embedding_hash,
        details={"face_detected": True, "challenge_type": request.challenge_type, **details},
    )


@app.post("/risk/assess", response_model=RiskAssessResponse)
async def assess_checkin_risk(request: RiskAssessRequest):
    """Apply the documented weighted multi-signal risk policy."""
    risk_score, risk_level, signal_breakdown, recommendations = assess_risk(request)
    return RiskAssessResponse(
        risk_score=risk_score,
        risk_level=risk_level,
        pass_threshold=risk_score < 0.50,
        risk_threshold=0.50,
        signal_breakdown=signal_breakdown,
        recommendations=recommendations,
    )
