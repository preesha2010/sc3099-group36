/**
 * Mock API adapter.
 *
 * Exposes exactly the same function signatures as the real client in
 * lib/api.ts, backed by deterministic in-memory fixtures instead of
 * network calls. lib/api.ts delegates to this module when
 * NEXT_PUBLIC_USE_MOCKS=true, so components never need to know which
 * mode is active.
 *
 * All fixture data is clearly fake demo data — no real personal
 * information. State resets on page reload (module-level, in-memory);
 * persistence is out of scope for this milestone.
 */

import { ApiError } from './errors'
import * as auth from './auth'
import type {
  RegisterRequest,
  RegisterResponse,
  LoginRequest,
  LoginResponse,
  RefreshTokenResponse,
  UserResponse,
  UpdateUserRequest,
  SessionSummary,
  Session,
  SessionDetail,
  MySessionsQuery,
  CheckinCreateRequest,
  CheckinCreateResponse,
  CheckinSummary,
  CheckinDetail,
  MyCheckinsQuery,
  CheckinAppealRequest,
  CheckinAppealResponse,
  DeviceRegisterRequest,
  DeviceRegisterResponse,
  DeviceSummary,
  DeviceUpdateRequest,
  Enrollment,
  FaceEnrollRequest,
  FaceEnrollResponse,
  UserRole,
} from '@/types/api'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_LATENCY_MS = 400

function delay<T>(value: T, ms: number = MOCK_LATENCY_MS): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), ms)
  })
}

let mockIdCounter = 0
function nextMockId(prefix: string): string {
  mockIdCounter += 1
  return `mock-${prefix}-${String(mockIdCounter).padStart(4, '0')}`
}

const DEMO_USER_ID = 'mock-user-demo-student'
const DEMO_EMAIL = 'demo.student@example.com'

// Mock login accepts any syntactically-plausible email and any password
// meeting a minimum length — it does not require a fixed demo email or
// password. This mirrors the real backend's "min 8 chars" password rule
// (docs/SECURITY-REQUIREMENTS.md) closely enough for local UI development
// without hardcoding a credential to check against.
const MOCK_EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MOCK_MIN_PASSWORD_LENGTH = 8

let currentUser: UserResponse = {
  id: DEMO_USER_ID,
  email: DEMO_EMAIL,
  full_name: 'Demo Student',
  role: 'student',
  camera_consent: false,
  geolocation_consent: false,
  face_enrolled: false,
  created_at: '2026-01-15T09:00:00Z',
}

const DEMO_COURSE_ID = 'mock-course-cs6101'
const DEMO_SESSION_ID = 'mock-session-lecture-05'

// A rolling window around "now", so the demo session's check-in is open whenever
// the app is used (fixed dates would make it look closed). Real server
// timestamps carry no zone marker; these end in "Z", which is also handled.
const NOW_MS = Date.now()
const fromNow = (minutes: number) => new Date(NOW_MS + minutes * 60_000).toISOString()
const DEMO_START = fromNow(-15)
const DEMO_END = fromNow(105)
const DEMO_CHECKIN_OPENS = fromNow(-30)
const DEMO_CHECKIN_CLOSES = fromNow(240)

const demoSessionSummary: SessionSummary = {
  id: DEMO_SESSION_ID,
  course_id: DEMO_COURSE_ID,
  course_code: 'CS6101',
  name: 'Lecture 5: Neural Networks',
  status: 'active',
  scheduled_start: DEMO_START,
  scheduled_end: DEMO_END,
  checkin_opens_at: DEMO_CHECKIN_OPENS,
  checkin_closes_at: DEMO_CHECKIN_CLOSES,
  venue_name: 'NTU LT1',
}

const demoSession: Session = {
  id: DEMO_SESSION_ID,
  course_id: DEMO_COURSE_ID,
  course_code: 'CS6101',
  course_name: 'Advanced Topics in CS',
  instructor_id: 'mock-user-demo-instructor',
  name: 'Lecture 5: Neural Networks',
  session_type: 'lecture',
  status: 'active',
  scheduled_start: DEMO_START,
  scheduled_end: DEMO_END,
  checkin_opens_at: DEMO_CHECKIN_OPENS,
  checkin_closes_at: DEMO_CHECKIN_CLOSES,
  venue_name: 'NTU LT1',
  total_enrolled: 50,
  checked_in_count: 41,
}

const demoSessionDetail: SessionDetail = {
  id: DEMO_SESSION_ID,
  course_id: DEMO_COURSE_ID,
  instructor_id: 'mock-user-demo-instructor',
  name: 'Lecture 5: Neural Networks',
  session_type: 'lecture',
  status: 'active',
  scheduled_start: DEMO_START,
  scheduled_end: DEMO_END,
  checkin_opens_at: DEMO_CHECKIN_OPENS,
  checkin_closes_at: DEMO_CHECKIN_CLOSES,
  venue_latitude: 1.3483,
  venue_longitude: 103.6831,
  venue_name: 'NTU LT1',
  geofence_radius_meters: 100.0,
  require_liveness_check: true,
  require_face_match: false,
  risk_threshold: 0.5,
  qr_code_enabled: false,
  created_at: '2026-02-20T10:00:00Z',
}

const demoEnrollments: Enrollment[] = [
  {
    id: nextMockId('enrollment'),
    course_id: DEMO_COURSE_ID,
    course_code: 'CS6101',
    course_name: 'Advanced Topics in CS',
    semester: 'AY2025-26 Sem 2',
    instructor_name: 'Dr. Tan',
    enrolled_at: '2026-01-10T10:00:00Z',
    is_active: true,
  },
]

const checkinStore = new Map<string, CheckinDetail>()
const checkinSummaries: CheckinSummary[] = []

// A little past history so the history and appeal screens can be tried in mock
// mode (new mock check-ins are always approved, which can't be appealed). These
// belong to other sessions, so they never block checking in to the demo session.
;(function seedPastCheckins() {
  const daysAgo = (days: number) => new Date(NOW_MS - days * 86_400_000).toISOString()
  const past: Array<{
    id: string
    sessionId: string
    name: string
    status: CheckinSummary['status']
    days: number
    risk: number
    distance: number
    factors: CheckinDetail['risk_factors']
    livenessPassed: boolean | null
  }> = [
    {
      id: 'mock-checkin-past-flagged',
      sessionId: 'mock-session-lecture-03',
      name: 'Lecture 3: Convolutional Networks',
      status: 'flagged',
      days: 2,
      risk: 0.62,
      distance: 180,
      factors: [
        { type: 'geo_out_of_bounds', weight: 0.4 },
        { type: 'device_unknown', weight: 0.15 },
      ],
      livenessPassed: true,
    },
    {
      id: 'mock-checkin-past-rejected',
      sessionId: 'mock-session-lecture-02',
      name: 'Lecture 2: Optimisation',
      status: 'rejected',
      days: 6,
      risk: 0.9,
      distance: 12,
      factors: [{ type: 'liveness_failed', weight: 0.5 }],
      livenessPassed: false,
    },
    {
      id: 'mock-checkin-past-approved',
      sessionId: 'mock-session-lecture-01',
      name: 'Lecture 1: Introduction',
      status: 'approved',
      days: 9,
      risk: 0.1,
      distance: 20,
      factors: [],
      livenessPassed: true,
    },
  ]
  for (const item of past) {
    const checkedInAt = daysAgo(item.days)
    checkinStore.set(item.id, {
      id: item.id,
      session_id: item.sessionId,
      student_id: DEMO_USER_ID,
      device_id: null,
      status: item.status,
      checked_in_at: checkedInAt,
      verified_at: checkedInAt,
      latitude: 1.3483,
      longitude: 103.6831,
      location_accuracy_meters: 10,
      distance_from_venue_meters: item.distance,
      liveness_passed: item.livenessPassed,
      liveness_score: item.livenessPassed === null ? null : item.livenessPassed ? 0.9 : 0.2,
      liveness_challenge_type: 'passive',
      face_match_passed: null,
      face_match_score: null,
      risk_score: item.risk,
      risk_factors: item.factors,
      qr_code_verified: false,
      reviewed_by_id: null,
      reviewed_at: null,
      review_notes: null,
      appeal_reason: null,
      appealed_at: null,
    })
    checkinSummaries.push({
      id: item.id,
      session_id: item.sessionId,
      session_name: item.name,
      course_code: 'CS6101',
      status: item.status,
      checked_in_at: checkedInAt,
      risk_score: item.risk,
    })
  }
})()
const deviceStore = new Map<string, DeviceRegisterResponse>()

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function requireMockAuth(): void {
  if (!auth.isAuthenticated()) {
    throw new ApiError({
      kind: 'authentication',
      message: 'Could not validate credentials',
      status: 401,
    })
  }
}

function toBase64Url(json: string): string {
  const base64 =
    typeof btoa === 'function'
      ? btoa(unescape(encodeURIComponent(json)))
      : Buffer.from(json, 'utf-8').toString('base64')
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * Builds a JWT-SHAPED MOCK token (header.payload.signature) purely so
 * jose's `decodeJwt` can structurally parse it the same way it would a
 * real access token. This is NOT a cryptographically signed JWT — the
 * "signature" segment is a placeholder string, not a real signature —
 * and it is for local development only: it is never verified, and the
 * real backend would never accept or issue it.
 */
function createMockAccessToken(claims: {
  sub: string
  email: string
  role: UserRole
}): string {
  const header = toBase64Url(JSON.stringify({ alg: 'none', typ: 'JWT' }))
  const nowSeconds = Math.floor(Date.now() / 1000)
  const payload = toBase64Url(
    JSON.stringify({
      sub: claims.sub,
      email: claims.email,
      role: claims.role,
      iat: nowSeconds,
      exp: nowSeconds + 60 * 60, // 1 hour, matches documented access token TTL
    }),
  )
  return `${header}.${payload}.mock-signature`
}

function createMockRefreshToken(userId: string): string {
  return `mock-refresh.${userId}.${Date.now()}`
}

function issueTokensFor(user: UserResponse): RefreshTokenResponse & {
  access_token: string
  refresh_token: string
} {
  const tokens = {
    access_token: createMockAccessToken({
      sub: user.id,
      email: user.email,
      role: user.role,
    }),
    refresh_token: createMockRefreshToken(user.id),
    token_type: 'bearer' as const,
  }
  auth.setTokens(tokens)
  return tokens
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export async function register(data: RegisterRequest): Promise<RegisterResponse> {
  if (data.email === DEMO_EMAIL) {
    throw new ApiError({
      kind: 'client',
      message: 'Email already registered',
      status: 400,
      detail: 'Email already registered',
    })
  }
  const response: RegisterResponse = {
    id: nextMockId('user'),
    email: data.email,
    full_name: data.full_name,
    role: data.role,
    is_active: true,
    created_at: new Date().toISOString(),
  }
  return delay(response)
}

export async function login(data: LoginRequest): Promise<LoginResponse> {
  const isValidEmail = MOCK_EMAIL_PATTERN.test(data.email)
  const isValidPassword = data.password.length >= MOCK_MIN_PASSWORD_LENGTH
  if (!isValidEmail || !isValidPassword) {
    throw new ApiError({
      kind: 'authentication',
      message: 'Invalid email or password.',
      status: 401,
      detail: 'Could not validate credentials',
    })
  }
  const tokens = issueTokensFor(currentUser)
  const response: LoginResponse = {
    ...tokens,
    user: currentUser,
  }
  return delay(response)
}

export async function refreshToken(
  refreshTokenValue: string,
): Promise<RefreshTokenResponse> {
  if (!refreshTokenValue.startsWith('mock-refresh.')) {
    throw new ApiError({
      kind: 'authentication',
      message: 'Invalid refresh token.',
      status: 401,
    })
  }
  const tokens = issueTokensFor(currentUser)
  return delay(tokens)
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export async function getCurrentUser(): Promise<UserResponse> {
  requireMockAuth()
  return delay(currentUser)
}

export async function updateCurrentUser(
  update: UpdateUserRequest,
): Promise<UserResponse> {
  requireMockAuth()
  currentUser = { ...currentUser, ...update }
  return delay(currentUser)
}

export async function enrollFace(payload: FaceEnrollRequest): Promise<FaceEnrollResponse> {
  requireMockAuth()
  // Same rule as the real backend: enrollment needs camera consent on record.
  if (!currentUser.camera_consent) {
    throw new ApiError({
      kind: 'client',
      message: 'Camera consent not given',
      status: 400,
      detail: 'Camera consent not given',
    })
  }
  if (!payload.image) {
    throw new ApiError({
      kind: 'client',
      message: 'No face detected',
      status: 400,
      detail: 'No face detected',
    })
  }
  currentUser = { ...currentUser, face_enrolled: true }
  return delay({
    success: true,
    message: 'Face enrolled successfully',
    face_enrolled: true,
    quality_score: 0.85,
  })
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export async function getActiveSessions(): Promise<SessionSummary[]> {
  return delay([demoSessionSummary])
}

export async function getMySessions(
  query?: MySessionsQuery,
): Promise<Session[]> {
  requireMockAuth()
  let sessions = [demoSession]
  if (query?.status) {
    sessions = sessions.filter((session) => session.status === query.status)
  }
  if (query?.limit) {
    sessions = sessions.slice(0, query.limit)
  }
  return delay(sessions)
}

export async function getSessionById(
  sessionId: string,
): Promise<SessionDetail> {
  requireMockAuth()
  if (sessionId !== DEMO_SESSION_ID) {
    throw new ApiError({
      kind: 'client',
      message: 'Session not found',
      status: 404,
    })
  }
  return delay(demoSessionDetail)
}

// ---------------------------------------------------------------------------
// Check-ins
// ---------------------------------------------------------------------------

export async function createCheckin(
  payload: CheckinCreateRequest,
): Promise<CheckinCreateResponse> {
  requireMockAuth()

  if (payload.session_id !== DEMO_SESSION_ID) {
    throw new ApiError({
      kind: 'client',
      message: 'Session not found',
      status: 404,
    })
  }

  const alreadyCheckedIn = checkinSummaries.some(
    (summary) => summary.session_id === payload.session_id,
  )
  if (alreadyCheckedIn) {
    throw new ApiError({
      kind: 'client',
      message: 'Already checked in',
      status: 400,
      detail: 'Already checked in',
    })
  }

  const livenessProvided = Boolean(payload.liveness_challenge_response)
  const id = nextMockId('checkin')
  const checkedInAt = new Date().toISOString()
  const riskScore = 0.15

  const detail: CheckinDetail = {
    id,
    session_id: payload.session_id,
    student_id: currentUser.id,
    device_id: null,
    status: 'approved',
    checked_in_at: checkedInAt,
    verified_at: checkedInAt,
    latitude: payload.latitude,
    longitude: payload.longitude,
    location_accuracy_meters: payload.location_accuracy_meters ?? null,
    distance_from_venue_meters: 45.2,
    liveness_passed: livenessProvided ? true : null,
    liveness_score: livenessProvided ? 0.92 : null,
    liveness_challenge_type: livenessProvided ? 'passive' : null,
    face_match_passed: null,
    face_match_score: null,
    risk_score: riskScore,
    risk_factors: [{ type: 'device_unknown', weight: 0.15 }],
    qr_code_verified: Boolean(payload.qr_code),
    reviewed_by_id: null,
    reviewed_at: null,
    review_notes: null,
    appeal_reason: null,
    appealed_at: null,
  }
  checkinStore.set(id, detail)
  checkinSummaries.push({
    id,
    session_id: payload.session_id,
    session_name: demoSession.name,
    course_code: demoSession.course_code,
    status: detail.status,
    checked_in_at: checkedInAt,
    risk_score: riskScore,
  })

  const response: CheckinCreateResponse = {
    id: detail.id,
    session_id: detail.session_id,
    student_id: detail.student_id,
    status: detail.status,
    checked_in_at: detail.checked_in_at,
    latitude: payload.latitude,
    longitude: payload.longitude,
    distance_from_venue_meters: detail.distance_from_venue_meters ?? 0,
    liveness_passed: detail.liveness_passed,
    liveness_score: detail.liveness_score,
    risk_score: detail.risk_score,
    risk_factors: detail.risk_factors,
  }
  return delay(response)
}

export async function getMyCheckins(
  query?: MyCheckinsQuery,
): Promise<CheckinSummary[]> {
  requireMockAuth()
  let results = [...checkinSummaries]
  if (query?.limit) {
    results = results.slice(0, query.limit)
  }
  return delay(results)
}

export async function getCheckinById(checkinId: string): Promise<CheckinDetail> {
  requireMockAuth()
  const detail = checkinStore.get(checkinId)
  if (!detail) {
    throw new ApiError({
      kind: 'client',
      message: 'Check-in not found',
      status: 404,
    })
  }
  return delay(detail)
}

export async function appealCheckin(
  checkinId: string,
  payload: CheckinAppealRequest,
): Promise<CheckinAppealResponse> {
  requireMockAuth()
  const detail = checkinStore.get(checkinId)
  if (!detail) {
    throw new ApiError({
      kind: 'client',
      message: 'Check-in not found',
      status: 404,
    })
  }
  if (detail.status !== 'rejected' && detail.status !== 'flagged') {
    throw new ApiError({
      kind: 'client',
      message: 'Only rejected or flagged check-ins can be appealed.',
      status: 400,
    })
  }
  if (detail.appealed_at) {
    throw new ApiError({
      kind: 'client',
      message: 'Check-in already appealed',
      status: 400,
      detail: 'Check-in already appealed',
    })
  }
  const appealedAt = new Date().toISOString()
  detail.status = 'appealed'
  detail.appeal_reason = payload.appeal_reason
  detail.appealed_at = appealedAt

  const summary = checkinSummaries.find((item) => item.id === checkinId)
  if (summary) {
    summary.status = 'appealed'
  }

  const response: CheckinAppealResponse = {
    id: detail.id,
    status: detail.status,
    appeal_reason: payload.appeal_reason,
    appealed_at: appealedAt,
  }
  return delay(response)
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------

export async function registerDevice(
  payload: DeviceRegisterRequest,
): Promise<DeviceRegisterResponse> {
  requireMockAuth()
  const existing = deviceStore.get(payload.device_fingerprint)
  const response: DeviceRegisterResponse = existing ?? {
    id: nextMockId('device'),
    device_fingerprint: payload.device_fingerprint,
    device_name: payload.device_name ?? null,
    platform: payload.platform ?? null,
    is_trusted: false,
    trust_score: 'low',
    is_active: true,
    first_seen_at: new Date().toISOString(),
  }
  deviceStore.set(payload.device_fingerprint, response)
  return delay(response)
}

export async function getMyDevices(): Promise<DeviceSummary[]> {
  requireMockAuth()
  const summaries: DeviceSummary[] = Array.from(deviceStore.values()).map(
    (device) => ({
      id: device.id,
      device_name: device.device_name,
      platform: device.platform,
      is_trusted: device.is_trusted,
      trust_score: device.trust_score,
      is_active: device.is_active,
      first_seen_at: device.first_seen_at,
      last_seen_at: device.first_seen_at,
      total_checkins: 0,
    }),
  )
  return delay(summaries)
}

export async function updateDevice(
  deviceId: string,
  payload: DeviceUpdateRequest,
): Promise<DeviceSummary> {
  requireMockAuth()
  const device = Array.from(deviceStore.values()).find(
    (item) => item.id === deviceId,
  )
  if (!device) {
    throw new ApiError({
      kind: 'client',
      message: 'Device not found',
      status: 404,
    })
  }
  if (payload.device_name !== undefined) device.device_name = payload.device_name
  if (payload.is_trusted !== undefined) {
    device.is_trusted = payload.is_trusted
    device.trust_score = payload.is_trusted ? 'high' : 'low'
  }
  if (payload.is_active !== undefined) device.is_active = payload.is_active

  const summary: DeviceSummary = {
    id: device.id,
    device_name: device.device_name,
    platform: device.platform,
    is_trusted: device.is_trusted,
    trust_score: device.trust_score,
    is_active: device.is_active,
    first_seen_at: device.first_seen_at,
    last_seen_at: new Date().toISOString(),
    total_checkins: 0,
  }
  return delay(summary)
}

export async function deleteDevice(deviceId: string): Promise<void> {
  requireMockAuth()
  const entry = Array.from(deviceStore.entries()).find(
    ([, device]) => device.id === deviceId,
  )
  if (!entry) {
    throw new ApiError({
      kind: 'client',
      message: 'Device not found',
      status: 404,
    })
  }
  deviceStore.delete(entry[0])
  return delay(undefined)
}

// ---------------------------------------------------------------------------
// Enrollments
// ---------------------------------------------------------------------------

export async function getMyEnrollments(): Promise<Enrollment[]> {
  requireMockAuth()
  return delay(demoEnrollments)
}
