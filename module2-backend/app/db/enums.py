from enum import Enum


class UserRole(str, Enum):
    STUDENT = "student"
    TA = "ta"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class SessionStatus(str, Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CheckinStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REJECTED = "rejected"
    APPEALED = "appealed"


class SignalType(str, Enum):
    # Geo
    GEO_OUT_OF_BOUNDS = "geo_out_of_bounds"
    IMPOSSIBLE_TRAVEL = "impossible_travel"
    GEO_ACCURACY_LOW = "geo_accuracy_low"
    # Network
    VPN_DETECTED = "vpn_detected"
    PROXY_DETECTED = "proxy_detected"
    TOR_DETECTED = "tor_detected"
    SUSPICIOUS_IP = "suspicious_ip"
    # Device
    DEVICE_UNKNOWN = "device_unknown"
    DEVICE_EMULATOR = "device_emulator"
    DEVICE_ROOTED = "device_rooted"
    ATTESTATION_FAILED = "attestation_failed"
    # Behavioral
    RAPID_SUCCESSION = "rapid_succession"
    UNUSUAL_TIME = "unusual_time"
    PATTERN_ANOMALY = "pattern_anomaly"
    # Liveness
    LIVENESS_FAILED = "liveness_failed"
    LIVENESS_LOW_CONFIDENCE = "liveness_low_confidence"
    DEEPFAKE_SUSPECTED = "deepfake_suspected"
    REPLAY_SUSPECTED = "replay_suspected"
    # Face
    FACE_MATCH_FAILED = "face_match_failed"
    FACE_MATCH_LOW_CONFIDENCE = "face_match_low_confidence"


class SignalSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AuditAction(str, Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    CHECKIN_ATTEMPTED = "checkin_attempted"
    CHECKIN_APPROVED = "checkin_approved"
    CHECKIN_FLAGGED = "checkin_flagged"
    CHECKIN_REJECTED = "checkin_rejected"
    CHECKIN_APPEALED = "checkin_appealed"
    CHECKIN_REVIEWED = "checkin_reviewed"
    SESSION_CREATED = "session_created"
    SESSION_UPDATED = "session_updated"
    SESSION_DELETED = "session_deleted"
    ENROLLMENT_ADDED = "enrollment_added"
    ENROLLMENT_REMOVED = "enrollment_removed"
    DEVICE_REGISTERED = "device_registered"
    FACE_ENROLLED = "face_enrolled"
    DATA_EXPORTED = "data_exported"
    SECURITY_VIOLATION = "security_violation"
