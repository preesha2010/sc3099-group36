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
import { toApiError } from './errors'
import * as auth from './auth'
import * as mockApi from './mockApi'
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

httpClient.interceptors.request.use((config) => {
  const token = auth.getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

// Auth endpoints must never trigger the 401-refresh flow on themselves,
// to avoid infinite refresh loops (e.g. a bad refresh token 401-ing and
// re-triggering another refresh attempt).
const AUTH_ENDPOINT_PATHS = ['/auth/login', '/auth/register', '/auth/refresh']

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

// De-duplicates concurrent refresh attempts: if several requests 401 at
// once, only one refresh call is made and the rest await its result.
let inFlightRefresh: Promise<string | null> | null = null

async function performRefresh(): Promise<string | null> {
  const refreshTokenValue = auth.getRefreshToken()
  if (!refreshTokenValue) return null

  try {
    const response = await axios.post<RefreshTokenResponse>(
      `${API_BASE_URL}/api/v1/auth/refresh`,
      { refresh_token: refreshTokenValue },
      { timeout: REQUEST_TIMEOUT_MS },
    )
    auth.setTokens({
      access_token: response.data.access_token,
      refresh_token: response.data.refresh_token,
    })
    return response.data.access_token
  } catch {
    auth.clearTokens()
    return null
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

      if (!inFlightRefresh) {
        inFlightRefresh = performRefresh().finally(() => {
          inFlightRefresh = null
        })
      }
      const newAccessToken = await inFlightRefresh

      if (newAccessToken) {
        originalRequest.headers.set('Authorization', `Bearer ${newAccessToken}`)
        return httpClient(originalRequest)
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
  auth.setTokens({ access_token: body.access_token, refresh_token: body.refresh_token })
  return body
}

async function realRefreshToken(
  refreshTokenValue: string,
): Promise<RefreshTokenResponse> {
  const { data: body } = await httpClient.post<RefreshTokenResponse>('/auth/refresh', {
    refresh_token: refreshTokenValue,
  })
  auth.setTokens({ access_token: body.access_token, refresh_token: body.refresh_token })
  return body
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

/** Clears the local session. No backend logout endpoint is documented in the API spec. */
export function logout(): void {
  auth.clearTokens()
}
