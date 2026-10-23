"""SAIV Module 3 HTTP API: face enrollment, verification, liveness, and risk."""

import os
import asyncio
import cv2
from contextlib import asynccontextmanager

import anyio.to_thread

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.middleware import BodySizeLimitMiddleware, ServiceMiddleware, TelemetryMiddleware
from app.config import Settings
from app.observability import metrics
from app.runtime import Runtime
from app.telemetry import Telemetry

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
from app.services.templates import match_templates, template_mode, validate_reference, SCORE_POLICY, match_query_to_template


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Bound the whole synchronous pipeline, not just individual neural models:
    # queued callers must not all decode and hold full-sized images in memory.
    settings = Settings.load()
    runtime = Runtime(settings)
    await anyio.to_thread.run_sync(runtime.start)
    application.state.settings = settings
    application.state.runtime = runtime
    application.state.inference_slots = asyncio.Semaphore(settings.concurrency)
    application.state.admitted = 0
    application.state.telemetry = Telemetry(settings.otel_endpoint, failed=metrics.trace_failed)
    limiter = anyio.to_thread.current_default_thread_limiter()
    previous = limiter.total_tokens
    limiter.total_tokens = settings.concurrency

    async def recovery_loop():
        while True:
            await asyncio.sleep(2)
            await anyio.to_thread.run_sync(runtime.recover)

    recovery = asyncio.create_task(recovery_loop())
    try:
        yield
    finally:
        recovery.cancel()
        try:
            await recovery
        except asyncio.CancelledError:
            pass
        limiter.total_tokens = previous
        await anyio.to_thread.run_sync(application.state.telemetry.close)


app = FastAPI(
    title="SAIV Face Recognition Service",
    description="Face enrollment, verification, liveness detection, and risk assessment service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:8501"
    ).split(",") if origin.strip() and origin.strip() != "*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(ServiceMiddleware)
app.add_middleware(TelemetryMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    # Pydantic normally echoes the rejected input, which may contain biometric
    # base64 or a public key. Return only field locations and safe error metadata.
    errors = [{key: error[key] for key in ("loc", "msg", "type")}
              for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(cv2.error)
async def inference_error_handler(_: Request, exc: cv2.error):
    return JSONResponse(status_code=503, content={"detail": "Local model inference is unavailable"})


@app.get("/health")
async def health_check():
    """Return the minimal service-health contract used by Docker and public tests."""
    return {"status": "healthy", "service": "face-recognition"}


@app.get("/ready")
async def readiness():
    ready = app.state.runtime.ready()
    return JSONResponse({"status": "ready" if ready else "not_ready", "service": "face-recognition"},
                        status_code=200 if ready else 503)


@app.get("/metrics", response_class=PlainTextResponse)
async def service_metrics():
    text = metrics.render() + "# TYPE module3_model_degraded_slots gauge\n# TYPE module3_model_slots gauge\n"
    for name, instance in app.state.runtime.pool_names.items():
        text += f'module3_model_degraded_slots{{model="{name}"}} {instance.degraded_slots}\n'
        text += f'module3_model_slots{{model="{name}"}} {instance.count}\n'
    return PlainTextResponse(text, media_type="text/plain; version=0.0.4")


@app.get("/")
async def root():
    """List the public endpoints exposed by this internal microservice."""
    return {
        "service": "SAIV Face Recognition & Risk Service",
        "version": "1.0.0",
        "template_mode": template_mode(),
        "match_score_policy": SCORE_POLICY if template_mode() == "simhash" else "exact_sha256_v1",
        "endpoints": [
            "/health",
            "/ready",
            "/metrics",
            "/face/enroll",
            "/face/verify",
            "/face/match",
            "/liveness/check",
            "/risk/assess",
        ],
    }


@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
def enroll_face(request: FaceEnrollRequest):
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
            "template_mode": template_mode(),
        },
    )


@app.post("/face/verify", response_model=FaceVerifyResponse)
def verify_face(request: FaceVerifyRequest):
    """Compare a submitted image against the hash previously returned at enrollment."""
    validate_reference(request.reference_template_hash)
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
    match_score = (match_query_to_template(embedding, request.reference_template_hash) if template_mode() == "simhash"
                   else match_templates(current_template_hash, request.reference_template_hash))
    del image_array, embedding
    return FaceVerifyResponse(
        match_passed=match_score >= 0.70,
        match_score=match_score,
        match_threshold=0.70,
        face_detected=True,
        current_template_hash=current_template_hash,
    )


@app.post("/face/match")
def match_face(request: FaceMatchRequest):
    """Preserve the documented legacy request and response format."""
    result = verify_face(
        FaceVerifyRequest(image=request.image, reference_template_hash=request.reference_hash)
    )
    return {
        "match_passed": result.match_passed,
        "match_score": result.match_score,
        "face_embedding_hash": result.current_template_hash,
    }


@app.post("/liveness/check", response_model=LivenessResponse)
def check_liveness(request: LivenessRequest):
    """Perform the documented single-image passive liveness check."""
    if request.challenge_type != "passive":
        raise HTTPException(
            status_code=400,
            detail="Motion challenges require multiple frames; this endpoint supports passive single-image checks only",
        )

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
def assess_checkin_risk(request: RiskAssessRequest):
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
