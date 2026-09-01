"""
enums.py should hold values reused across modules, for example:
- UserRole: student, ta, instructor, admin
- SessionStatus: scheduled, active, closed, cancelled
- SessionType: lecture, tutorial, lab, exam
- CheckinStatus: pending, approved, flagged, rejected
- RiskLevel: low, medium, high, critical
Then import them in your models and Pydantic schemas:
"""

import enum


class UserRole(str, enum.Enum):
    student = "student"
    instructor = "instructor"
    ta = "ta"
    admin = "admin"


class SessionStatus(str, enum.Enum):
    scheduled = "scheduled"
    active = "active"
    closed = "closed"
    cancelled = "cancelled"


class CheckinStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    flagged = "flagged"
    rejected = "rejected"
    appealed = "appealed"


class RiskSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RiskSignalType(str, enum.Enum):
    # Geo signal types
    geo_out_of_bounds = "geo_out_of_bounds"
    impossible_travel = "impossible_travel"
    geo_accuracy_low = "geo_accuracy_low"

    # Network signal types
    vpn_detected = "vpn_detected"
    proxy_detected = "proxy_detected"
    tor_detected = "tor_detected"
    suspicious_ip = "suspicious_ip"

    # Device signal types
    device_unknown = "device_unknown"
    device_emulator = "device_emulator"
    device_rooted = "device_rooted"
    attestation_failed = "attestation_failed"

    # Behavioral signal types
    rapid_succession = "rapid_succession"
    unusual_time = "unusual_time"
    pattern_anomaly = "pattern_anomaly"

    # Liveness signal types
    liveness_failed = "liveness_failed"
    liveness_low_confidence = "liveness_low_confidence"
    deepfake_suspected = "deepfake_suspected"
    replay_suspected = "replay_suspected"

    # Face signal types
    face_match_failed = "face_match_failed"
    face_match_low_confidence = "face_match_low_confidence"


class AuditAction(str, enum.Enum):
    login_success = "login_success"
    login_failed = "login_failed"
    logout = "logout"
    user_created = "user_created"

    checkin_attempted = "checkin_attempted"
    checkin_approved = "checkin_approved"
    checkin_flagged = "checkin_flagged"
    checkin_rejected = "checkin_rejected"

    face_enrolled = "face_enrolled"
    device_registered = "device_registered"
    data_exported = "data_exported"
    security_violation = "security_violation"