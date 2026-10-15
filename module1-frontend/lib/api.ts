/**
 * API client.
 *
 * Exposes one function per frontend-relevant backend endpoint
 * (docs/API-SPECIFICATION.md). Each exported function transparently
 * routes to either the real axios-backed implementation or the mock
 * adapter in lib/mockApi.ts, based on NEXT_PUBLIC_USE_MOCKS — callers
 * (components) never need to know which mode is active.
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ApiError, toApiError } from './errors'
import * as auth from './auth'
import * as mockApi from './mockApi'
import type {
  RegisterRequest,
  RegisterResponse,
  LoginRequest,
  LoginResponse,
  TokenPair,
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
} from '@/types/api'

const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === 'true'
// NEXT_PUBLIC_API_URL is the backend ORIGIN ONLY (e.g. http://localhost:8000),
// matching .env.local and docker-compose.yml. The "/api/v1" prefix from
// docs/API-SPECIFICATION.md's base URL is appended exactly once here; every
// endpoint function below then uses only its path (e.g. '/auth/login').
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
// Matches the documented Frontend -> Backend timeout in
// docs/recommended_design/INTEGRATION-GUIDE.md's "Service Communication Summary".
const REQUEST_TIMEOUT_MS = 30_000

const httpClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  timeout: REQUEST_TIMEOUT_MS,
})

const REFRESH_PATH = '/auth/refresh'

/**
 * Identifies the signed-in SESSION in this tab, independent of what the tokens
 * currently are. It changes only when a session ends or a new one begins —
 * logout, login, a definitively rejected refresh (see `endSession`/`startSession`)
 * — and deliberately NOT when a refresh swaps the tokens, so it works the same
 * whether or not the backend rotates refresh tokens.
 *
 * It exists so that a response which arrives late can tell whether the session
 * it was started for is still the current one. A late refresh result for an
 * ended or replaced session must not restore a logged-out session, overwrite a
 * newer login's tokens, or clear them; and a request sent under one session must
 * not be refreshed and replayed under another. This api.ts is the only
 * non-mock code that writes or clears tokens, so every change is counted here.
 * Limit: it is per tab — another tab signing in or out is not seen (see
 * `isSessionStale` for the part that can be detected).
 */
let sessionEpoch = 0

function startSession(tokens: TokenPair): void {
  sessionEpoch += 1
  auth.setTokens(tokens)
}

function endSession(): void {
  sessionEpoch += 1
  auth.clearTokens()
}

/**
 * True if the session a refresh was started for is no longer the current one:
 * this tab ended or replaced it, or the stored tokens were cleared meanwhile
 * (for example by signing out in another tab).
 */
function isSessionStale(startedInEpoch: number): boolean {
  return startedInEpoch !== sessionEpoch || auth.getRefreshToken() === null
}

httpClient.interceptors.request.use((config) => {
  // POST /auth/refresh is documented without auth ("Requires auth" appears on the
  // protected endpoints but not here): its credential is the refresh token in the
  // body. At startup the stored access token is, by definition, expired — sending
  // it would let a backend that inspects the header reject a valid refresh. Only
  // this one path is exempt; every other request still carries the token.
  if (config.url === REFRESH_PATH) return config

  // Remember which session this request belongs to (first send only, so a retry
  // keeps the original), for the 401 handler below.
  const stamped = config as RetriableConfig
  if (stamped._sessionEpoch === undefined) stamped._sessionEpoch = sessionEpoch

  const token = auth.getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

// Auth endpoints must never trigger the 401-refresh flow on themselves,
// to avoid infinite refresh loops (e.g. a bad refresh token 401-ing and
// re-triggering another refresh attempt).
const AUTH_ENDPOINT_PATHS = ['/auth/login', '/auth/register', REFRESH_PATH]

type RetriableConfig = InternalAxiosRequestConfig & {
  _retried?: boolean
  _sessionEpoch?: number
}

/**
 * How the app reacts when a token refresh fails. One policy, shared by the 401
 * interceptor and the startup restore, so the two can never disagree.
 *
 * `POST /auth/refresh` documents only its 200 response — no error codes
 * (docs/API-SPECIFICATION.md) — and the tests only cover success, so what a
 * rejected refresh looks like is NOT established by the contract. This is a
 * deliberate, conservative reading, not a confirmed one:
 *
 * - `reauthenticate` — 401 (kind `authentication`): the one status whose HTTP
 *   meaning is "credentials rejected". The stored tokens are cleared and the
 *   user is sent to sign in again.
 * - `transient` — no usable answer: network failure, timeout, 5xx, 429, or a
 *   200 whose body isn't a token pair. The session may well still be valid, so
 *   the tokens are kept and the user gets a retry, never a logout.
 * - `other` — any other answer (400, 403, 404, 422, …). Not documented as
 *   meaning "token revoked", so the tokens are NOT cleared, but the session
 *   can't be restored either, so the user is directed to sign in again. These
 *   are never handed to feature screens as if they were that feature's error.
 */
type RefreshFailureHandling = 'reauthenticate' | 'transient' | 'other'

function classifyRefreshFailure(error: ApiError): RefreshFailureHandling {
  switch (error.kind) {
    case 'authentication':
      return 'reauthenticate'
    case 'network':
    case 'server':
    case 'rate_limit':
      return 'transient'
    default:
      return 'other'
  }
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

/**
 * Validates a refresh response body BEFORE anything is written to storage.
 * Both tokens must be non-empty strings; otherwise nothing is stored (so the
 * existing pair survives intact — never `"undefined"`, never half a pair) and a
 * controlled `server`-kind error is thrown. A malformed 200 is typically a proxy
 * or captive-portal page, i.e. a transient problem, so it is handled like one.
 */
function readTokenPair(body: unknown): TokenPair {
  if (typeof body === 'object' && body !== null) {
    const { access_token, refresh_token } = body as Record<string, unknown>
    if (isNonEmptyString(access_token) && isNonEmptyString(refresh_token)) {
      return { access_token, refresh_token }
    }
  }
  throw new ApiError({
    kind: 'server',
    message: 'The server sent an unexpected response.',
  })
}

// `stale`: the session this refresh was started for ended or was replaced while
// it was in flight, so the result — success or failure — was discarded without
// touching the stored tokens.
type RefreshResult = { accessToken: string } | { error: ApiError } | { stale: true }
const STALE_REFRESH: RefreshResult = { stale: true }

// De-duplicates concurrent refresh attempts: if several requests 401 at once,
// only one refresh call is made and the rest await its result. An entry is only
// shared within ONE session: a request from a newer session never joins (and so
// never waits on or inherits the result of) an older session's refresh.
let inFlightRefresh: { epoch: number; promise: Promise<RefreshResult> } | null = null

function refreshSession(): Promise<RefreshResult> {
  if (inFlightRefresh && inFlightRefresh.epoch === sessionEpoch) {
    return inFlightRefresh.promise
  }
  const entry = { epoch: sessionEpoch, promise: performRefresh(sessionEpoch) }
  inFlightRefresh = entry
  // performRefresh never rejects, so this derived promise can't go unhandled.
  void entry.promise.finally(() => {
    if (inFlightRefresh === entry) inFlightRefresh = null
  })
  return entry.promise
}

async function performRefresh(startedInEpoch: number): Promise<RefreshResult> {
  const refreshTokenValue = auth.getRefreshToken()
  if (!refreshTokenValue) {
    return { error: new ApiError({ kind: 'authentication', message: 'No refresh token.' }) }
  }

  try {
    // Plain axios (not httpClient): no interceptors, so no Authorization header
    // and no way to re-enter the 401 handler.
    const response = await axios.post<unknown>(
      `${API_BASE_URL}/api/v1${REFRESH_PATH}`,
      { refresh_token: refreshTokenValue },
      { timeout: REQUEST_TIMEOUT_MS },
    )
    // The check and the write below run in the same synchronous block, so
    // nothing can slip in between them within this tab.
    if (isSessionStale(startedInEpoch)) return STALE_REFRESH
    const tokens = readTokenPair(response.data)
    auth.setTokens(tokens)
    return { accessToken: tokens.access_token }
  } catch (caught) {
    // A late failure for an old session must not clear a newer session's tokens.
    if (isSessionStale(startedInEpoch)) return STALE_REFRESH
    const error = toApiError(caught)
    if (classifyRefreshFailure(error) === 'reauthenticate') {
      endSession()
    }
    return { error }
  }
}

httpClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetriableConfig | undefined
    const status = error.response?.status
    const requestUrl = originalRequest?.url ?? ''
    const isAuthEndpoint = AUTH_ENDPOINT_PATHS.some((path) =>
      requestUrl.includes(path),
    )

    if (status === 401 && originalRequest && !originalRequest._retried && !isAuthEndpoint) {
      originalRequest._retried = true

      // This request was sent under a session that has since ended or been
      // replaced (logout, a new login, a rejected refresh). Refreshing now would
      // act on a different session, and retrying would replay the request under
      // someone else's identity — so report the 401 as it is.
      if (originalRequest._sessionEpoch !== sessionEpoch) {
        return Promise.reject(toApiError(error))
      }

      const refreshed = await refreshSession()

      // Same reasoning if the session changed while the refresh was in flight:
      // that refresh's result was discarded and nothing may be retried.
      if ('stale' in refreshed || originalRequest._sessionEpoch !== sessionEpoch) {
        return Promise.reject(toApiError(error))
      }

      if ('accessToken' in refreshed) {
        originalRequest.headers.set('Authorization', `Bearer ${refreshed.accessToken}`)
        return httpClient(originalRequest)
      }

      // The refresh itself failed (see classifyRefreshFailure). Only a transient
      // failure surfaces the refresh's own error (network, server, rate limit), so
      // the screen offers a retry instead of signing the user out. Every other
      // outcome — a definitive 401 or an undocumented refresh 4xx — keeps the
      // ORIGINAL 401, which every screen already maps to "log in again"; the
      // refresh endpoint's own 4xx never reaches a feature as that feature's error.
      // This request is not retried again (`_retried`), and /auth/refresh never
      // re-enters this branch, so a failing refresh cannot loop.
      if (classifyRefreshFailure(refreshed.error) === 'transient') {
        return Promise.reject(refreshed.error)
      }
    }

    return Promise.reject(toApiError(error))
  },
)

// ---------------------------------------------------------------------------
// Real implementations (never called directly by components — see the
// exported wrappers at the bottom of this file)
// ---------------------------------------------------------------------------

async function realRegister(data: RegisterRequest): Promise<RegisterResponse> {
  const { data: body } = await httpClient.post<RegisterResponse>('/auth/register', data)
  return body
}

async function realLogin(data: LoginRequest): Promise<LoginResponse> {
  const { data: body } = await httpClient.post<LoginResponse>('/auth/login', data)
  // A new login is a new session: anything still in flight for the old one is
  // now stale (see sessionEpoch).
  startSession({ access_token: body.access_token, refresh_token: body.refresh_token })
  return body
}

async function realRefreshToken(
  refreshTokenValue: string,
): Promise<RefreshTokenResponse> {
  const startedInEpoch = sessionEpoch
  const { data: body } = await httpClient.post<unknown>(REFRESH_PATH, {
    refresh_token: refreshTokenValue,
  })
  // Discard the result if the session ended or was replaced while it was in
  // flight (the caller checks the same condition and reports the current state).
  if (isSessionStale(startedInEpoch)) {
    throw new ApiError({ kind: 'unknown', message: 'The session changed during refresh.' })
  }
  // Validated before anything is stored: a malformed body leaves the current
  // token pair untouched and surfaces a controlled error (see readTokenPair).
  const tokens = readTokenPair(body)
  auth.setTokens(tokens)
  return { ...tokens, token_type: 'bearer' }
}

async function realGetCurrentUser(): Promise<UserResponse> {
  const { data } = await httpClient.get<UserResponse>('/users/me')
  return data
}

async function realUpdateCurrentUser(
  update: UpdateUserRequest,
): Promise<UserResponse> {
  const { data } = await httpClient.put<UserResponse>('/users/me', update)
  return data
}

async function realGetActiveSessions(): Promise<SessionSummary[]> {
  const { data } = await httpClient.get<SessionSummary[]>('/sessions/active')
  return data
}

async function realGetMySessions(query?: MySessionsQuery): Promise<Session[]> {
  const { data } = await httpClient.get<Session[]>('/sessions/my-sessions', {
    params: query,
  })
  return data
}

async function realGetSessionById(sessionId: string): Promise<SessionDetail> {
  const { data } = await httpClient.get<SessionDetail>(`/sessions/${sessionId}`)
  return data
}

async function realCreateCheckin(
  payload: CheckinCreateRequest,
): Promise<CheckinCreateResponse> {
  const { data } = await httpClient.post<CheckinCreateResponse>('/checkins/', payload)
  return data
}

async function realGetMyCheckins(
  query?: MyCheckinsQuery,
): Promise<CheckinSummary[]> {
  const { data } = await httpClient.get<CheckinSummary[]>('/checkins/my-checkins', {
    params: query,
  })
  return data
}

async function realGetCheckinById(checkinId: string): Promise<CheckinDetail> {
  const { data } = await httpClient.get<CheckinDetail>(`/checkins/${checkinId}`)
  return data
}

async function realAppealCheckin(
  checkinId: string,
  payload: CheckinAppealRequest,
): Promise<CheckinAppealResponse> {
  const { data } = await httpClient.post<CheckinAppealResponse>(
    `/checkins/${checkinId}/appeal`,
    payload,
  )
  return data
}

async function realRegisterDevice(
  payload: DeviceRegisterRequest,
): Promise<DeviceRegisterResponse> {
  const { data } = await httpClient.post<DeviceRegisterResponse>(
    '/devices/register',
    payload,
  )
  return data
}

async function realGetMyDevices(): Promise<DeviceSummary[]> {
  const { data } = await httpClient.get<DeviceSummary[]>('/devices/my-devices')
  return data
}

async function realUpdateDevice(
  deviceId: string,
  payload: DeviceUpdateRequest,
): Promise<DeviceSummary> {
  const { data } = await httpClient.patch<DeviceSummary>(
    `/devices/${deviceId}`,
    payload,
  )
  return data
}

async function realDeleteDevice(deviceId: string): Promise<void> {
  await httpClient.delete(`/devices/${deviceId}`)
}

async function realGetMyEnrollments(): Promise<Enrollment[]> {
  const { data } = await httpClient.get<Enrollment[]>('/enrollments/my-enrollments')
  return data
}

// ---------------------------------------------------------------------------
// Public API surface — components import only these. Each one transparently
// picks the real or mock implementation based on NEXT_PUBLIC_USE_MOCKS.
// ---------------------------------------------------------------------------

export const register = (data: RegisterRequest): Promise<RegisterResponse> =>
  USE_MOCKS ? mockApi.register(data) : realRegister(data)

export const login = (data: LoginRequest): Promise<LoginResponse> =>
  USE_MOCKS ? mockApi.login(data) : realLogin(data)

export const refreshToken = (
  refreshTokenValue: string,
): Promise<RefreshTokenResponse> =>
  USE_MOCKS ? mockApi.refreshToken(refreshTokenValue) : realRefreshToken(refreshTokenValue)

export const getCurrentUser = (): Promise<UserResponse> =>
  USE_MOCKS ? mockApi.getCurrentUser() : realGetCurrentUser()

export const updateCurrentUser = (
  update: UpdateUserRequest,
): Promise<UserResponse> =>
  USE_MOCKS ? mockApi.updateCurrentUser(update) : realUpdateCurrentUser(update)

export const getActiveSessions = (): Promise<SessionSummary[]> =>
  USE_MOCKS ? mockApi.getActiveSessions() : realGetActiveSessions()

export const getMySessions = (query?: MySessionsQuery): Promise<Session[]> =>
  USE_MOCKS ? mockApi.getMySessions(query) : realGetMySessions(query)

export const getSessionById = (sessionId: string): Promise<SessionDetail> =>
  USE_MOCKS ? mockApi.getSessionById(sessionId) : realGetSessionById(sessionId)

export const createCheckin = (
  payload: CheckinCreateRequest,
): Promise<CheckinCreateResponse> =>
  USE_MOCKS ? mockApi.createCheckin(payload) : realCreateCheckin(payload)

export const getMyCheckins = (
  query?: MyCheckinsQuery,
): Promise<CheckinSummary[]> =>
  USE_MOCKS ? mockApi.getMyCheckins(query) : realGetMyCheckins(query)

export const getCheckinById = (checkinId: string): Promise<CheckinDetail> =>
  USE_MOCKS ? mockApi.getCheckinById(checkinId) : realGetCheckinById(checkinId)

export const appealCheckin = (
  checkinId: string,
  payload: CheckinAppealRequest,
): Promise<CheckinAppealResponse> =>
  USE_MOCKS
    ? mockApi.appealCheckin(checkinId, payload)
    : realAppealCheckin(checkinId, payload)

export const registerDevice = (
  payload: DeviceRegisterRequest,
): Promise<DeviceRegisterResponse> =>
  USE_MOCKS ? mockApi.registerDevice(payload) : realRegisterDevice(payload)

export const getMyDevices = (): Promise<DeviceSummary[]> =>
  USE_MOCKS ? mockApi.getMyDevices() : realGetMyDevices()

export const updateDevice = (
  deviceId: string,
  payload: DeviceUpdateRequest,
): Promise<DeviceSummary> =>
  USE_MOCKS ? mockApi.updateDevice(deviceId, payload) : realUpdateDevice(deviceId, payload)

export const deleteDevice = (deviceId: string): Promise<void> =>
  USE_MOCKS ? mockApi.deleteDevice(deviceId) : realDeleteDevice(deviceId)

export const getMyEnrollments = (): Promise<Enrollment[]> =>
  USE_MOCKS ? mockApi.getMyEnrollments() : realGetMyEnrollments()

// ---------------------------------------------------------------------------
// Startup session restore
// ---------------------------------------------------------------------------

// Shared so concurrent callers (e.g. React Strict Mode running the startup
// effect twice in dev) trigger ONE refresh request, not two — the backend may
// rotate refresh tokens, so a second concurrent call could invalidate the first.
let inFlightRestore: Promise<SessionRestoreResult> | null = null

/**
 * - `authenticated`: the user is (or has just been silently made) signed in.
 * - `unauthenticated`: there is no usable session; show Sign In.
 * - `unavailable`: the server couldn't be reached or answered (offline,
 *   timeout, 5xx, 429). The stored tokens were kept, so retrying later may
 *   still restore the session — don't show Sign In as if the user were out.
 */
export type SessionRestoreResult = 'authenticated' | 'unauthenticated' | 'unavailable'

async function doRestoreSession(): Promise<SessionRestoreResult> {
  // Access token still valid: nothing to do, no network call.
  if (auth.isAuthenticated()) return 'authenticated'

  const storedRefreshToken = auth.getRefreshToken()
  if (!storedRefreshToken) {
    // Nothing to refresh with; drop any stale (expired) access token.
    endSession()
    return 'unauthenticated'
  }

  const startedInEpoch = sessionEpoch
  try {
    // Goes through the existing refresh path (mock or real), which also
    // persists the new tokens via lib/auth.ts on success.
    await refreshToken(storedRefreshToken)
    return 'authenticated'
  } catch (caught) {
    // The session ended or was replaced while this was in flight: its outcome
    // (success or failure) no longer matters and nothing may be cleared. Report
    // whatever the current state is.
    if (isSessionStale(startedInEpoch)) {
      return auth.isAuthenticated() ? 'authenticated' : 'unauthenticated'
    }

    // Same policy as the 401 interceptor (see classifyRefreshFailure).
    switch (classifyRefreshFailure(toApiError(caught))) {
      case 'reauthenticate':
        endSession()
        return 'unauthenticated'
      case 'transient':
        // No usable answer from the server: keep the tokens and offer a retry.
        return 'unavailable'
      default:
        // An undocumented refresh rejection (400, 403, 404, 422, …): not proof
        // the token is dead, so it isn't cleared — but the session can't be
        // restored, so the user signs in again (which overwrites the tokens).
        return 'unauthenticated'
    }
  }
}

/**
 * Restores the signed-in state at app startup. Never rejects, so callers can't
 * get stuck waiting on it.
 */
export function restoreSession(): Promise<SessionRestoreResult> {
  if (!inFlightRestore) {
    inFlightRestore = doRestoreSession()
      .catch((): SessionRestoreResult => 'unauthenticated')
      .finally(() => {
        inFlightRestore = null
      })
  }
  return inFlightRestore
}

/** Clears the local session. No backend logout endpoint is documented in the API spec. */
export function logout(): void {
  // Ends the session for everything still in flight: a refresh that returns
  // after this will be discarded rather than signing the user back in.
  endSession()
}
