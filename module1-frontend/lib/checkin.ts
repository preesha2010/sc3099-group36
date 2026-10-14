/**
 * Check-in submission.
 *
 * Builds and sends `POST /checkins/` (docs/API-SPECIFICATION.md) through the
 * existing API client. Everything the request needs is gathered here, in a
 * single awaited sequence per attempt: the device fingerprint, then a fresh
 * location fix, then the request — so one submission can never mix values
 * from different moments or different device ids.
 *
 * Privacy: the liveness image and the location only ever live in local
 * variables for the duration of the call. Nothing here stores, logs or caches
 * them, and the request is made only through `api.createCheckin`.
 */

import * as api from './api'
import { getDeviceFingerprint } from './deviceBinding'
import { getCurrentLocation } from './geolocation'
import type {
  CheckinCreateRequest,
  CheckinCreateResponse,
  CheckinSummary,
} from '@/types/api'

/** The device fingerprint couldn't be produced (e.g. Web Crypto unavailable). */
export class DeviceIdentityError extends Error {
  constructor() {
    super('Device identity is unavailable.')
    this.name = 'DeviceIdentityError'
  }
}

export type SubmitPhase = 'locating' | 'sending'

export interface SubmitCheckinInput {
  sessionId: string
  /** The captured image as produced by CameraCapture (a data URL), or null when no photo is needed. */
  livenessImage: string | null
  /** Reports progress so the UI can show what the submission is doing. */
  onPhase?: (phase: SubmitPhase) => void
}

const DATA_URL_PREFIX = /^data:image\/[a-zA-Z0-9.+-]+;base64,/

/**
 * The API documents image fields as raw base64 — the enroll endpoint says
 * "without data URL prefix" explicitly; the check-in endpoint only says
 * "base64_encoded_image", and the backend forwards it to a service that
 * base64-decodes it. So the `data:image/...;base64,` prefix is stripped.
 */
export function toBase64Payload(dataUrl: string): string {
  return dataUrl.replace(DATA_URL_PREFIX, '')
}

/**
 * Submits a check-in. Resolves with the server's response only when the API
 * returned success; rejects with a `GeolocationRequestError`,
 * `DeviceIdentityError` or `ApiError` otherwise.
 */
export async function submitCheckin(
  input: SubmitCheckinInput,
): Promise<CheckinCreateResponse> {
  input.onPhase?.('locating')

  let deviceFingerprint: string
  try {
    deviceFingerprint = await getDeviceFingerprint()
  } catch {
    throw new DeviceIdentityError()
  }

  const location = await getCurrentLocation()

  const payload: CheckinCreateRequest = {
    session_id: input.sessionId,
    latitude: location.latitude,
    longitude: location.longitude,
    device_fingerprint: deviceFingerprint,
  }
  if (Number.isFinite(location.accuracyMeters)) {
    payload.location_accuracy_meters = location.accuracyMeters
  }
  if (input.livenessImage) {
    payload.liveness_challenge_response = toBase64Payload(input.livenessImage)
  }

  input.onPhase?.('sending')
  return api.createCheckin(payload)
}

/**
 * Looks the session up in the student's own check-in history
 * (`GET /checkins/my-checkins`). Used after a 400 to tell "you are already
 * checked in" apart from other business-rule rejections without relying on
 * the wording of the backend's error message. The documented `course_id` filter
 * keeps the result well inside the endpoint's default page size (`limit`, 50),
 * so the session's entry can't be pushed off the page by other courses.
 */
export async function findExistingCheckin(
  sessionId: string,
  courseId: string,
): Promise<CheckinSummary | null> {
  const history = await api.getMyCheckins({ course_id: courseId })
  return history.find((entry) => entry.session_id === sessionId) ?? null
}
