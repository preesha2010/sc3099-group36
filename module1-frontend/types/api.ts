/**
 * Frontend-relevant API contract types for the SAIV backend.
 *
 * Source of truth: docs/API-SPECIFICATION.md (request/response shapes),
 * with docs/recommended_design/DATABASE-SCHEMA.md used only to fill in
 * field nullability/optionality where the API spec doesn't fully
 * enumerate a response (noted inline where this applies).
 *
 * Only endpoints relevant to the student-facing frontend (Module 1) are
 * covered here. Instructor/admin/dashboard-only endpoints (courses
 * management, session management, stats, audit, export, admin/*) belong
 * to Module 4 and are intentionally out of scope.
 */

// ---------------------------------------------------------------------------
// Shared enums
// ---------------------------------------------------------------------------

export type UserRole = 'student' | 'instructor' | 'ta' | 'admin'

export type SessionStatus = 'scheduled' | 'active' | 'closed' | 'cancelled'

export type SessionType = 'lecture' | 'tutorial' | 'lab' | 'exam'

export type CheckinStatus =
  | 'pending'
  | 'approved'
  | 'flagged'
  | 'rejected'
  | 'appealed'

export type DevicePlatform = 'ios' | 'android' | 'web' | 'desktop'

export type TrustScore = 'low' | 'medium' | 'high'

// ---------------------------------------------------------------------------
// Shared error/validation shapes (mirrors FastAPI's default error body)
// ---------------------------------------------------------------------------

export interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
}

export interface ApiErrorBody {
  detail: string | ValidationErrorItem[]
}

// ---------------------------------------------------------------------------
// Auth — POST /auth/register, /auth/login, /auth/refresh
// ---------------------------------------------------------------------------

export interface RegisterRequest {
  email: string
  password: string
  full_name: string
  role: UserRole
}

export interface RegisterResponse {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface LoginRequest {
  email: string
  password: string
}

/** Decoded, UNVERIFIED shape of the access token's JWT claims (see SECURITY-REQUIREMENTS.md). */
export interface AccessTokenClaims {
  sub: string
  email: string
  role: UserRole
  exp: number
  iat: number
}

export interface TokenPair {
  access_token: string
  refresh_token: string
}

export interface LoginResponse extends TokenPair {
  token_type: 'bearer'
  user: UserResponse
}

export interface RefreshTokenRequest {
  refresh_token: string
}

export interface RefreshTokenResponse extends TokenPair {
  token_type: 'bearer'
}

// ---------------------------------------------------------------------------
// Users — GET/PUT /users/me
// ---------------------------------------------------------------------------

export interface UserResponse {
  id: string
  email: string
  full_name: string
  role: UserRole
  camera_consent: boolean
  geolocation_consent: boolean
  face_enrolled: boolean
  created_at: string
}

/**
 * PUT /users/me is documented with all three fields in its example body.
 * Treated as a partial update (all fields optional) since the frontend
 * needs to be able to toggle a single consent flag without resending the
 * user's full profile; the spec doesn't state this endpoint requires the
 * full object.
 */
export interface UpdateUserRequest {
  full_name?: string
  camera_consent?: boolean
  geolocation_consent?: boolean
}

// ---------------------------------------------------------------------------
// Sessions — GET /sessions/active, /sessions/my-sessions, /sessions/{id}
// ---------------------------------------------------------------------------

/** GET /sessions/active response item (public endpoint, no auth). */
export interface SessionSummary {
  id: string
  course_id: string
  course_code: string
  name: string
  status: SessionStatus
  scheduled_start: string
  scheduled_end: string
  checkin_opens_at: string
  checkin_closes_at: string
  venue_name: string
}

/**
 * GET /sessions/my-sessions response item. The API spec does not show an
 * explicit example body for this endpoint ("Returns list of sessions
 * relevant to the user") — this reuses the fuller list-item shape shown
 * for GET /sessions/ (instructor/admin), since it's the most complete
 * documented "session list item" schema. Verify against the real backend
 * once available.
 */
export interface Session {
  id: string
  course_id: string
  course_code: string
  course_name: string
  instructor_id: string
  name: string
  session_type: SessionType
  status: SessionStatus
  scheduled_start: string
  scheduled_end: string
  checkin_opens_at: string
  checkin_closes_at: string
  venue_name: string
  total_enrolled: number
  checked_in_count: number
}

export interface MySessionsQuery {
  status?: SessionStatus
  upcoming?: boolean
  limit?: number
}

/** GET /sessions/{session_id} response. */
export interface SessionDetail {
  id: string
  course_id: string
  instructor_id: string
  name: string
  session_type: SessionType
  status: SessionStatus
  scheduled_start: string
  scheduled_end: string
  checkin_opens_at: string
  checkin_closes_at: string
  venue_latitude: number
  venue_longitude: number
  venue_name: string
  geofence_radius_meters: number
  require_liveness_check: boolean
  require_face_match: boolean
  risk_threshold: number
  qr_code_enabled: boolean
  created_at: string
}

// ---------------------------------------------------------------------------
// Check-ins — POST /checkins/, GET /checkins/my-checkins, /checkins/{id},
// POST /checkins/{id}/appeal
// ---------------------------------------------------------------------------

/**
 * POST /checkins/ request body. `location_accuracy_meters` is confirmed
 * optional by tests/public/test_frontend_dashboard.py, which submits a
 * check-in without it. `liveness_challenge_response` and `qr_code` are
 * explicitly marked optional in the API spec.
 */
export interface CheckinCreateRequest {
  session_id: string
  latitude: number
  longitude: number
  location_accuracy_meters?: number
  device_fingerprint: string
  liveness_challenge_response?: string
  qr_code?: string
}

export interface CheckinRiskFactor {
  type: string
  weight: number
}

/** POST /checkins/ response (201). */
export interface CheckinCreateResponse {
  id: string
  session_id: string
  student_id: string
  status: CheckinStatus
  checked_in_at: string
  latitude: number
  longitude: number
  distance_from_venue_meters: number
  liveness_passed: boolean | null
  liveness_score: number | null
  risk_score: number
  risk_factors: CheckinRiskFactor[]
}

/** GET /checkins/my-checkins response item. */
export interface CheckinSummary {
  id: string
  session_id: string
  session_name: string
  course_code: string
  status: CheckinStatus
  checked_in_at: string
  risk_score: number
}

export interface MyCheckinsQuery {
  course_id?: string
  limit?: number
}

/**
 * GET /checkins/{checkin_id} response ("full check-in object with all
 * risk signals"). The API spec doesn't enumerate this endpoint's full
 * body, so this is derived from the `checkins` table columns in
 * DATABASE-SCHEMA.md. `face_embedding_hash` is intentionally omitted —
 * it's an internal biometric-adjacent reference, not needed by the
 * frontend and not called out by the endpoint's documented purpose.
 */
export interface CheckinDetail {
  id: string
  session_id: string
  student_id: string
  device_id: string | null
  status: CheckinStatus
  checked_in_at: string
  verified_at: string | null
  latitude: number | null
  longitude: number | null
  location_accuracy_meters: number | null
  distance_from_venue_meters: number | null
  liveness_passed: boolean | null
  liveness_score: number | null
  liveness_challenge_type: string | null
  face_match_passed: boolean | null
  face_match_score: number | null
  risk_score: number
  risk_factors: CheckinRiskFactor[]
  qr_code_verified: boolean
  reviewed_by_id: string | null
  reviewed_at: string | null
  review_notes: string | null
  appeal_reason: string | null
  appealed_at: string | null
}

export interface CheckinAppealRequest {
  appeal_reason: string
}

export interface CheckinAppealResponse {
  id: string
  status: CheckinStatus
  appeal_reason: string
  appealed_at: string
}

// ---------------------------------------------------------------------------
// Devices — POST /devices/register, GET /devices/my-devices,
// PATCH /devices/{id}, DELETE /devices/{id}
// ---------------------------------------------------------------------------

/**
 * POST /devices/register request. `device_name` and `platform` are
 * marked optional here per DATABASE-SCHEMA.md's `devices` table, where
 * both columns are NULLABLE (device_fingerprint and public_key are
 * NOT NULL there, and required in the documented example).
 */
export interface DeviceRegisterRequest {
  device_fingerprint: string
  device_name?: string
  platform?: DevicePlatform
  public_key: string
}

export interface DeviceRegisterResponse {
  id: string
  device_fingerprint: string
  device_name: string | null
  platform: DevicePlatform | null
  is_trusted: boolean
  trust_score: TrustScore
  is_active: boolean
  first_seen_at: string
}

/** GET /devices/my-devices response item. */
export interface DeviceSummary {
  id: string
  device_name: string | null
  platform: DevicePlatform | null
  is_trusted: boolean
  trust_score: TrustScore
  is_active: boolean
  first_seen_at: string
  last_seen_at: string
  total_checkins: number
}

export interface DeviceUpdateRequest {
  device_name?: string
  /** Admin only per API-SPECIFICATION.md; harmless for a student client to omit. */
  is_trusted?: boolean
  is_active?: boolean
}

// ---------------------------------------------------------------------------
// Enrollments — GET /enrollments/my-enrollments
// ---------------------------------------------------------------------------

export interface Enrollment {
  id: string
  course_id: string
  course_code: string
  course_name: string
  semester: string
  instructor_name: string
  enrolled_at: string
  is_active: boolean
}

// ---------------------------------------------------------------------------
// Offline check-in queue
//
// This is a CLIENT-ONLY concept (not part of the backend API) used to
// persist not-yet-submitted check-ins for later retry. Per the
// architecture decision on device binding / privacy, this type
// deliberately excludes `liveness_challenge_response` (a base64 face
// image) — it must never hold raw face images, liveness payloads, face
// embeddings, access/refresh tokens, or passwords. The queue implementation
// itself (persistence, retry/flush logic) is out of scope for this
// milestone; only the type is defined here.
// ---------------------------------------------------------------------------

export type QueuedCheckinPayload = Omit<
  CheckinCreateRequest,
  'liveness_challenge_response'
>

export type QueuedCheckinStatus = 'pending' | 'syncing' | 'failed'

export interface QueuedCheckin {
  /** Client-generated id for this queue entry — not a server check-in id. */
  id: string
  payload: QueuedCheckinPayload
  createdAt: string
  retryCount: number
  status: QueuedCheckinStatus
}
