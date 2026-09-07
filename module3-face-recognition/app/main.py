"""
SAIV Face Recognition & Risk Service - Module 3

This is the skeleton implementation for the Face Recognition module.
Students must implement face enrollment, verification, liveness detection,
and risk scoring.

Privacy Requirements:
- NO raw face images should be stored
- Process images in-memory only
- Store only SHA-256 hashes of face embeddings

Recommended Libraries:
- MediaPipe: Face detection and 468-landmark face mesh
- OpenCV: Image processing
- Pillow: Image loading from base64
- NumPy: Numerical operations
"""

import base64
import hashlib
import ipaddress
import re
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

app = FastAPI(
    title="SAIV Face Recognition Service",
    description="Face enrollment, verification, liveness detection, and risk scoring service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class FaceEnrollRequest(BaseModel):
    """Request model for face enrollment."""
    user_id: str
    image: str  # Base64 encoded image
    camera_consent: bool = False


class FaceEnrollResponse(BaseModel):
    """Response model for face enrollment."""
    enrollment_successful: bool
    face_template_hash: str  # 64-char SHA-256 hex string
    quality_score: float  # 0.0 to 1.0
    details: Dict[str, Any]


class FaceVerifyRequest(BaseModel):
    """Request model for face verification."""
    image: str  # Base64 encoded image
    reference_template_hash: str  # Hash from enrollment


class FaceVerifyResponse(BaseModel):
    """Response model for face verification."""
    match_passed: bool
    match_score: float  # 0.0 to 1.0
    match_threshold: float  # Default: 0.70
    face_detected: bool
    current_template_hash: str


class FaceMatchRequest(BaseModel):
    """Legacy request model retained for the documented /face/match endpoint."""
    image: str
    reference_hash: str


class LivenessRequest(BaseModel):
    """Request model for liveness check."""
    challenge_response: str  # Base64 encoded image
    challenge_type: str = "blink"  # blink, head_turn, passive


class LivenessResponse(BaseModel):
    """Response model for liveness check."""
    liveness_passed: bool
    liveness_score: float  # 0.0 to 1.0
    liveness_threshold: float  # Default: 0.60
    challenge_type: str
    face_embedding_hash: str
    details: Dict[str, Any]


class GeolocationData(BaseModel):
    """Geolocation data for risk assessment."""
    latitude: float
    longitude: float
    accuracy: float


class RiskAssessRequest(BaseModel):
    """Request model for risk assessment."""
    liveness_score: Optional[float] = None
    face_match_score: Optional[float] = None
    device_signature: Optional[str] = None
    device_public_key: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    geolocation: Optional[GeolocationData] = None


class RiskAssessResponse(BaseModel):
    """Response model for risk assessment."""
    risk_score: float  # 0.0 to 1.0
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    pass_threshold: bool
    risk_threshold: float  # Default: 0.50
    signal_breakdown: Dict[str, float]
    recommendations: List[str]


# =============================================================================
# HEALTH & ROOT ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": "face-recognition"
    }


@app.get("/")
async def root():
    """List available endpoints."""
    return {
        "service": "SAIV Face Recognition & Risk Service",
        "version": "1.0.0",
        "endpoints": [
            "/health",
            "/face/enroll",
            "/face/verify",
            "/face/match",
            "/liveness/check",
            "/risk/assess"
        ]
    }


# =============================================================================
# FACE ENROLLMENT ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
async def enroll_face(request: FaceEnrollRequest):
    """
    Enroll a user's face for future verification.

    TODO: Implement the following:
    1. Validate camera_consent is True (return 400 if False)
    2. Decode base64 image to numpy array
    3. Detect face using MediaPipe FaceDetection
    4. If no face detected, return 400 with "No face detected"
    5. Extract face features/embedding
    6. Generate SHA-256 hash of embedding (64 hex chars)
    7. Calculate quality score based on:
       - Face detection confidence
       - Image resolution
       - Face size relative to image
    8. Return enrollment response

    Success Criteria:
    - Face detected with confidence >= 0.7
    - Quality score >= 0.5
    - Returns 64-char SHA-256 hex hash
    """
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
    confidence = float(detection["confidence"])

    # Image and embedding are intentionally local-only and are never persisted.
    del image_array, embedding
    return FaceEnrollResponse(
        enrollment_successful=True,
        face_template_hash=face_template_hash,
        quality_score=quality_score,
        details={
            "face_detected": True,
            "face_detection_confidence": confidence,
            "image_quality": image_quality,
        },
    )


# =============================================================================
# FACE VERIFICATION ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/verify", response_model=FaceVerifyResponse)
async def verify_face(request: FaceVerifyRequest):
    """
    Verify a face against an enrolled template.

    TODO: Implement the following:
    1. Decode base64 image to numpy array
    2. Detect face using MediaPipe FaceDetection
    3. If no face detected, return with face_detected=False
    4. Extract face features/embedding
    5. Generate SHA-256 hash of current face
    6. Compare hashes or embeddings (choose your approach)
    7. Calculate match_score (0.0 to 1.0)
    8. match_passed = (match_score >= 0.70)

    Note: Hash comparison alone gives binary match. For continuous
    scores, consider perceptual hashing or embedding similarity.
    """
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
    """
    Legacy face matching endpoint. Redirects to /face/verify.
    Kept for backwards compatibility.
    """
    result = await verify_face(
        FaceVerifyRequest(image=request.image, reference_template_hash=request.reference_hash)
    )
    return {
        "match_passed": result.match_passed,
        "match_score": result.match_score,
        "face_embedding_hash": result.current_template_hash,
    }


# =============================================================================
# LIVENESS DETECTION ENDPOINT (REQUIRED - partial; BONUS for advanced)
# =============================================================================

@app.post("/liveness/check", response_model=LivenessResponse)
async def check_liveness(request: LivenessRequest):
    """
    Perform liveness detection on submitted image.

    TODO: Implement the following:
    1. Decode base64 image to numpy array
    2. Detect face using MediaPipe FaceDetection
    3. If no face detected, return with liveness_passed=False
    4. Analyze face for liveness signals:

    REQUIRED (for partial credit):
    - Basic face detection confidence
    - Image quality assessment
    - Face size validation

    BONUS (for extra credit - see API-SPECIFICATION.md):
    - MediaPipe Face Mesh 3D analysis (468 landmarks)
    - Depth cue analysis (nose_tip_z coordinate)
    - Face mesh completeness check
    - Challenge-response detection (blink, head movement)

    Challenge Types:
    - "passive": No user action required (depth/texture analysis)
    - "blink": Detect eye blink (compare eye aspect ratios)
    - "head_turn": Detect head rotation (face mesh landmarks)

    5. Calculate liveness_score (0.0 to 1.0)
    6. liveness_passed = (liveness_score >= 0.60)
    7. Generate face embedding hash

    Depth Analysis Hints (BONUS):
    - Use MediaPipe FaceMesh to get 3D landmarks
    - nose_tip_z (landmark 1, z-coordinate) indicates depth
    - Real faces: |nose_tip_z| > 0.03 (significant depth)
    - Flat images: |nose_tip_z| < 0.01 (minimal depth)
    """
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

    quality_score, image_quality = calculate_quality_score(image_array, detection)
    mesh_details = analyze_face_mesh(image_array)
    # Passive liveness is deliberately conservative: it combines image quality,
    # a complete face mesh, and detectable landmark depth without retaining images.
    depth_score = 1.0 if mesh_details["depth_quality"] == "good" else 0.5 if mesh_details["depth_quality"] == "moderate" else 0.0
    mesh_score = 1.0 if mesh_details["face_mesh_complete"] else 0.0
    liveness_score = round(0.45 * quality_score + 0.30 * mesh_score + 0.25 * depth_score, 3)
    embedding = extract_face_embedding(image_array, detection)
    face_embedding_hash = generate_face_hash(embedding)
    del image_array, embedding
    return LivenessResponse(
        liveness_passed=liveness_score >= 0.60,
        liveness_score=liveness_score,
        liveness_threshold=0.60,
        challenge_type=request.challenge_type,
        face_embedding_hash=face_embedding_hash,
        details={
            "face_detected": True,
            "face_detection_confidence": float(detection["confidence"]),
            "image_quality": image_quality,
            "challenge_type": request.challenge_type,
            **mesh_details,
        },
    )


# =============================================================================
# RISK ASSESSMENT ENDPOINT (REQUIRED - 3 points in public tests)
# =============================================================================

@app.post("/risk/assess", response_model=RiskAssessResponse)
async def assess_risk(request: RiskAssessRequest):
    """
    Perform multi-signal risk assessment.

    TODO: Implement the following:
    1. Collect all available signals from request
    2. Calculate individual signal scores (0.0 = safe, 1.0 = risky)
    3. Apply weighted fusion:
       - Liveness: 25%
       - Face match: 25%
       - Device attestation: 20%
       - Network/VPN: 15%
       - Geolocation: 15%
    4. Calculate combined risk_score
    5. Determine risk_level:
       - LOW: risk_score < 0.3
       - MEDIUM: 0.3 <= risk_score < 0.5
       - HIGH: 0.5 <= risk_score < 0.7
       - CRITICAL: risk_score >= 0.7
    6. pass_threshold = (risk_score < 0.50)
    7. Generate recommendations for low-scoring signals

    Signal Analysis:
    - Liveness: Invert score (low liveness = high risk)
    - Face match: Invert score (low match = high risk)
    - Device: Check signature validity, public key format
    - Network: Detect VPN/proxy (private IPs, Tor exit nodes)
    - Geolocation: Check accuracy, validate coordinates

    VPN/Proxy Detection Hints:
    - Private IP ranges: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
    - Check user_agent for VPN indicators
    - High geolocation accuracy (< 10m) might be spoofed
    - Very low accuracy (> 5000m) indicates issues
    """
    signal_breakdown, recommendations = calculate_risk_signals(request)
    weights = {
        "liveness": 0.25,
        "face_match": 0.25,
        "device": 0.20,
        "network": 0.15,
        "geolocation": 0.15,
    }
    risk_score = round(sum(signal_breakdown[name] * weights[name] for name in weights), 3)
    if risk_score < 0.3:
        risk_level = "LOW"
    elif risk_score < 0.5:
        risk_level = "MEDIUM"
    elif risk_score < 0.7:
        risk_level = "HIGH"
    else:
        risk_level = "CRITICAL"

    return RiskAssessResponse(
        risk_score=risk_score,
        risk_level=risk_level,
        pass_threshold=risk_score < 0.50,
        risk_threshold=0.50,
        signal_breakdown=signal_breakdown,
        recommendations=recommendations,
    )


# =============================================================================
# HELPER FUNCTIONS (Implement these to support your endpoints)
# =============================================================================

def decode_base64_image(base64_string: str):
    """
    Decode a base64 encoded image to a numpy array.

    TODO: Implement using:
    - base64.b64decode()
    - PIL.Image.open(BytesIO(...))
    - numpy.array()

    Handle errors gracefully (invalid base64, corrupt image, etc.)
    """
    if not isinstance(base64_string, str) or not base64_string.strip():
        raise HTTPException(status_code=400, detail="Image must be a non-empty base64 string")
    encoded = re.sub(r"^data:image/[^;]+;base64,", "", base64_string.strip(), flags=re.IGNORECASE)
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            if image.width < 32 or image.height < 32:
                raise HTTPException(status_code=400, detail="Image resolution is too small")
            return np.asarray(image)
    except (ValueError, UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or corrupt image") from exc


def detect_face(image_array):
    """
    Detect faces in an image using MediaPipe.

    TODO: Implement using:
    - mediapipe.solutions.face_detection.FaceDetection
    - Return detection results with confidence scores

    Consider setting min_detection_confidence=0.5
    """
    with mp.solutions.face_detection.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.5,
    ) as detector:
        result = detector.process(image_array)
    if not result.detections:
        return None

    detection = max(result.detections, key=lambda item: item.score[0])
    confidence = float(detection.score[0])
    if confidence < 0.7:
        return None
    box = detection.location_data.relative_bounding_box
    height, width = image_array.shape[:2]
    x1 = max(0, int(box.xmin * width))
    y1 = max(0, int(box.ymin * height))
    x2 = min(width, int((box.xmin + box.width) * width))
    y2 = min(height, int((box.ymin + box.height) * height))
    if x2 <= x1 or y2 <= y1:
        return None
    return {"confidence": confidence, "bbox": (x1, y1, x2, y2)}


def extract_face_embedding(image_array, detection):
    """
    Extract face embedding/features for hashing.

    TODO: Choose your approach:
    - Simple: Crop face region, resize to standard size, flatten
    - Advanced: Use MediaPipe Face Mesh landmarks
    - Even more advanced: Use face recognition model (dlib, etc.)

    Return numpy array that can be hashed.
    """
    x1, y1, x2, y2 = detection["bbox"]
    face_crop = image_array[y1:y2, x1:x2]
    if face_crop.size == 0:
        raise HTTPException(status_code=400, detail="Could not extract face features")
    normalized = cv2.resize(face_crop, (128, 128), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY).astype(np.uint8)


def generate_face_hash(embedding) -> str:
    """
    Generate SHA-256 hash of face embedding.

    TODO: Implement using:
    - hashlib.sha256()
    - embedding.tobytes() or embedding.tostring()
    - Return 64-character hex string
    """
    return hashlib.sha256(embedding.tobytes()).hexdigest()


def analyze_face_mesh(image_array):
    """
    Analyze face using MediaPipe Face Mesh (BONUS).

    TODO: Implement using:
    - mediapipe.solutions.face_mesh.FaceMesh
    - Extract 468 landmarks
    - Calculate depth from nose_tip_z (landmark index 1)
    - Check mesh completeness

    Return dict with:
    - face_mesh_complete: bool
    - landmark_count: int
    - nose_tip_z: float
    - depth_quality: "good" | "moderate" | "poor"
    """
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    ) as face_mesh:
        result = face_mesh.process(image_array)
    if not result.multi_face_landmarks:
        return {
            "face_mesh_complete": False,
            "landmark_count": 0,
            "nose_tip_z": 0.0,
            "depth_quality": "poor",
        }
    landmarks = result.multi_face_landmarks[0].landmark
    nose_tip_z = float(landmarks[1].z)
    landmark_count = len(landmarks)
    absolute_depth = abs(nose_tip_z)
    if landmark_count >= 468 and absolute_depth > 0.03:
        depth_quality = "good"
    elif landmark_count >= 468 and absolute_depth > 0.01:
        depth_quality = "moderate"
    else:
        depth_quality = "poor"
    return {
        "face_mesh_complete": landmark_count >= 468,
        "landmark_count": landmark_count,
        "nose_tip_z": round(nose_tip_z, 5),
        "depth_quality": depth_quality,
    }


def detect_blink(face_mesh_landmarks):
    """
    Detect eye blink from face mesh landmarks (BONUS).

    TODO: Implement using:
    - Eye landmark indices (see MediaPipe docs)
    - Calculate Eye Aspect Ratio (EAR)
    - EAR < threshold indicates closed eye
    """
    # Blink detection needs two or more frames; a single image cannot prove motion.
    return False


def detect_vpn_proxy(ip_address: str, user_agent: str) -> tuple:
    """
    Detect VPN/proxy usage.

    TODO: Check for:
    - Private IP ranges (10.x, 172.16-31.x, 192.168.x)
    - Localhost (127.x, ::1)
    - VPN keywords in user_agent
    - Known proxy headers (not available here, but could extend)

    Return (is_vpn: bool, confidence: float)
    """
    reasons = []
    try:
        if ip_address and (ipaddress.ip_address(ip_address).is_private or ipaddress.ip_address(ip_address).is_loopback):
            reasons.append("private_or_loopback_ip")
    except ValueError:
        reasons.append("invalid_ip")
    if user_agent and any(keyword in user_agent.lower() for keyword in ("vpn", "proxy", "tor")):
        reasons.append("vpn_or_proxy_user_agent")
    return bool(reasons), min(1.0, 0.5 * len(reasons))


def calculate_quality_score(image_array: np.ndarray, detection: Dict[str, Any]) -> Tuple[float, str]:
    """Return a bounded quality score using documented confidence, resolution, and face size."""
    height, width = image_array.shape[:2]
    x1, y1, x2, y2 = detection["bbox"]
    face_ratio = ((x2 - x1) * (y2 - y1)) / float(width * height)
    resolution_score = min(1.0, (width * height) / float(640 * 480))
    face_size_score = min(1.0, face_ratio / 0.15)
    quality_score = round(
        0.50 * float(detection["confidence"]) + 0.25 * resolution_score + 0.25 * face_size_score,
        3,
    )
    image_quality = "good" if quality_score >= 0.75 else "acceptable" if quality_score >= 0.5 else "poor"
    return quality_score, image_quality


def calculate_risk_signals(request: RiskAssessRequest) -> Tuple[Dict[str, float], List[str]]:
    """Convert documented security signals into bounded per-signal risk scores."""
    recommendations: List[str] = []

    def inverted_score(score: Optional[float], name: str, recommendation: str) -> float:
        if score is None:
            return 0.5
        if not 0.0 <= score <= 1.0:
            raise HTTPException(status_code=400, detail=f"{name} must be between 0 and 1")
        risk = round(1.0 - score, 3)
        if risk >= 0.5:
            recommendations.append(recommendation)
        return risk

    liveness_risk = inverted_score(request.liveness_score, "liveness_score", "Improve lighting and face visibility")
    face_risk = inverted_score(request.face_match_score, "face_match_score", "Re-enroll face or improve image quality")
    device_risk = 0.0 if request.device_signature and request.device_public_key else 0.5
    if device_risk:
        recommendations.append("Use a registered and trusted device")
    is_vpn, network_risk = detect_vpn_proxy(request.ip_address or "", request.user_agent or "")
    if is_vpn:
        recommendations.append("Disable VPN or proxy for check-in")

    geolocation_risk = 0.5
    if request.geolocation is not None:
        geo = request.geolocation
        if not -90 <= geo.latitude <= 90 or not -180 <= geo.longitude <= 180 or geo.accuracy < 0:
            raise HTTPException(status_code=400, detail="Invalid geolocation values")
        if geo.accuracy > 5000:
            geolocation_risk = 1.0
            recommendations.append("Enable precise location services")
        elif geo.accuracy > 100:
            geolocation_risk = 0.5
            recommendations.append("Improve location accuracy")
        else:
            geolocation_risk = 0.0

    return {
        "liveness": liveness_risk,
        "face_match": face_risk,
        "device": device_risk,
        "network": network_risk,
        "geolocation": geolocation_risk,
    }, recommendations


# =============================================================================
# PRIVACY REQUIREMENTS (IMPORTANT!)
# =============================================================================
"""
Your implementation MUST follow these privacy requirements:

1. NO RAW IMAGES STORED
   - Process images in-memory only
   - Do not write images to disk
   - Do not send images to external APIs

2. HASH-ONLY STORAGE
   - Store only SHA-256 hashes (64 hex characters)
   - Hashes are one-way - cannot reconstruct face
   - Different faces must produce different hashes

3. EPHEMERAL PROCESSING
   - Clear image data after processing
   - No caching of raw biometric data
   - Use Python's memory management (del, gc.collect)

4. CONSENT TRACKING
   - Require camera_consent=True for enrollment
   - Log consent in audit trail (backend responsibility)

5. RESPONSE HYGIENE
   - Never include base64 image data in responses
   - Only return hashes, scores, and metadata
"""
