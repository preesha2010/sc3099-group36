'use client'

/**
 * CheckInPreflight
 *
 * Runs before the consent/camera/liveness steps. For the selected session
 * it (1) fetches the full session details (`api.getSessionById`) and the
 * signed-in user's profile (`api.getCurrentUser`) so the requirement flags
 * and `face_enrolled` come from the server — never from decoded JWT claims
 * — (2) kicks off a best-effort device registration in the background, and
 * (3) shows an informational summary of what the check-in will need.
 *
 * Everything shown here is INFORMATIONAL except one thing: "Start check-in" is
 * held back while the session's check-in window is closed or not yet open (by this
 * device's clock, see lib/sessionWindow.ts). The backend remains the sole authority
 * on whether a check-in is accepted, so other notices, such as "face match required
 * but not enrolled", warn the user but never stop them from continuing.
 *
 * Device registration never blocks this screen or the user: it starts only
 * after the details load, its outcome only updates one line of text, and any
 * failure is non-fatal (see `ensureDeviceRegistered`).
 *
 * This component requests no camera or location permission, makes no
 * check-in request, and stores nothing itself.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/lib/api'
import { ACCOUNT_LOCKED_MESSAGE, ApiError } from '@/lib/errors'
import {
  ensureDeviceRegistered,
  type DeviceRegistrationStatus,
} from '@/lib/deviceBinding'
import { useOnlineStatus } from '@/lib/useOnlineStatus'
import { formatServerDateTime } from '@/lib/dates'
import { formatSessionRange, presentWindow } from '@/lib/sessionWindow'
import { useNow } from '@/lib/useNow'
import type { Session, SessionDetail, UserResponse } from '@/types/api'

type PreflightStatus = 'loading' | 'error' | 'ready'
type DeviceStatus = 'checking' | DeviceRegistrationStatus

export interface CheckInPreflightResult {
  sessionDetail: SessionDetail
  user: UserResponse
}

export interface CheckInPreflightProps {
  session: Session
  /** Called when the user clicks "Start check-in" on the ready screen. */
  onReady: (result: CheckInPreflightResult) => void
  /** If given, the face-match warning offers an "Enroll now" button that calls this. */
  onEnrollFace?: () => void
}

/** Maps a preflight failure to a static, user-friendly message — never raw backend text. */
function describePreflightError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'authentication':
        return 'Your session has expired. Please log in again.'
      case 'authorization':
        return 'You don’t have permission to check in to this session.'
      case 'account_locked':
        return ACCOUNT_LOCKED_MESSAGE
      case 'rate_limit':
        return 'Too many requests. Please wait a moment and try again.'
      case 'network':
        return 'Unable to reach the server. Check your connection and try again.'
      case 'server':
        return 'Something went wrong on our end. Please try again shortly.'
      default:
        return error.status === 404
          ? 'This session could not be found. Go back and choose another.'
          : 'Unable to load this session right now. Please try again.'
    }
  }
  return 'Unable to load this session right now. Please try again.'
}

const formatDateTime = formatServerDateTime

function describeDeviceStatus(status: DeviceStatus): string {
  switch (status) {
    case 'checking':
      return 'Checking this device’s registration…'
    case 'registered':
      return 'This device is registered.'
    case 'previously-registered':
      // Based on a local marker only — not re-verified with the server.
      return 'This device was registered earlier on this browser.'
    case 'not-registered':
      return 'This device isn’t registered, so your check-in may be reviewed more closely.'
  }
}

const NOTICE_CLASSES =
  'p-3 rounded border-l-4 border-amber-500 bg-amber-50 text-sm text-amber-800'

export default function CheckInPreflight({
  session,
  onReady,
  onEnrollFace,
}: CheckInPreflightProps) {
  const [status, setStatus] = useState<PreflightStatus>('loading')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [result, setResult] = useState<CheckInPreflightResult | null>(null)
  const [deviceStatus, setDeviceStatus] = useState<DeviceStatus>('checking')
  const isOnline = useOnlineStatus()
  const now = useNow()
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const runPreflight = useCallback(async () => {
    setStatus('loading')
    setErrorMessage(null)
    setResult(null)
    setDeviceStatus('checking')

    try {
      const [sessionDetail, user] = await Promise.all([
        api.getSessionById(session.id),
        api.getCurrentUser(),
      ])
      if (!isMountedRef.current) return

      setResult({ sessionDetail, user })
      setStatus('ready')

      // Fire-and-forget: registration must never delay or block the user.
      void ensureDeviceRegistered(user.id).then((registration) => {
        if (isMountedRef.current) setDeviceStatus(registration)
      })
    } catch (error) {
      if (!isMountedRef.current) return
      setErrorMessage(describePreflightError(error))
      setStatus('error')
    }
  }, [session.id])

  useEffect(() => {
    void runPreflight()
  }, [runPreflight])

  // By this device's clock (a hint; the server decides). Start is held back outside the window.
  const windowInfo = result
    ? presentWindow(
        result.sessionDetail.checkin_opens_at,
        result.sessionDetail.checkin_closes_at,
        now,
      )
    : null
  const windowOpen = windowInfo?.state === 'open'

  const handleStart = useCallback(() => {
    if (result && windowOpen) onReady(result)
  }, [result, windowOpen, onReady])

  return (
    <div className="card">
      <h2 className="mb-1 text-2xl font-bold">Ready to Check In</h2>
      <p className="mb-5 text-gray-600">
        Review what this check-in needs, then start when you&rsquo;re ready.
      </p>

      {status === 'loading' && (
        <p role="status" className="text-sm text-gray-400">
          Loading session details…
        </p>
      )}

      {status === 'error' && (
        <>
          <div
            role="alert"
            className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
          >
            {errorMessage}
          </div>
          <button
            type="button"
            onClick={() => void runPreflight()}
            className="btn btn-primary"
          >
            Retry
          </button>
        </>
      )}

      {status === 'ready' && result && (
        <>
          <div className="mb-5 rounded-2xl bg-gray-50 p-4 ring-1 ring-gray-200">
            <div className="flex items-start justify-between gap-2">
              <p className="font-semibold leading-snug">
                {session.course_code} — {result.sessionDetail.name}
              </p>
              {windowInfo && <span className={`pill ${windowInfo.badgeClasses}`}>{windowInfo.badge}</span>}
            </div>
            <p className="text-sm text-gray-600">{result.sessionDetail.venue_name}</p>
            <p className="text-sm text-gray-500">
              {formatSessionRange(
                result.sessionDetail.scheduled_start,
                result.sessionDetail.scheduled_end,
                now,
              )}
            </p>
            <p className="text-sm text-gray-500">
              Check-in closes: {formatDateTime(result.sessionDetail.checkin_closes_at)}
            </p>
          </div>

          <h3 className="text-sm font-medium text-gray-700 mb-2">
            What this check-in needs
          </h3>
          <ul className="mb-4 space-y-2 text-sm text-gray-700">
            <li>Location: your position is checked against the venue.</li>
            <li>
              Photo:{' '}
              {result.sessionDetail.require_liveness_check
                ? 'a live photo is required.'
                : 'no photo is required for this session.'}
            </li>
            {result.sessionDetail.require_face_match && (
              <li>
                Face match: required
                {result.user.face_enrolled
                  ? ' — your face is enrolled.'
                  : ' — no face is enrolled on your account yet.'}
              </li>
            )}
            <li aria-live="polite">Device: {describeDeviceStatus(deviceStatus)}</li>
          </ul>

          <div className="mb-4 space-y-2">
            {result.sessionDetail.status !== 'active' && (
              <div className={NOTICE_CLASSES}>
                This session is currently {result.sessionDetail.status}, so check-in may
                not be accepted.
              </div>
            )}
            {windowInfo?.state === 'closed' && (
              <div className={NOTICE_CLASSES}>
                The check-in window for this session closed at{' '}
                {formatDateTime(result.sessionDetail.checkin_closes_at)}, so you can no
                longer check in to it.
              </div>
            )}
            {windowInfo?.state === 'not-open-yet' && (
              <div className={NOTICE_CLASSES}>
                Check-in for this session opens at{' '}
                {formatDateTime(result.sessionDetail.checkin_opens_at)}. You can start then.
              </div>
            )}
            {result.sessionDetail.require_face_match && !result.user.face_enrolled && (
              <div className={NOTICE_CLASSES}>
                This session requires a face match, but no face is enrolled on your
                account. Your check-in may be rejected.
                {onEnrollFace && (
                  <button
                    type="button"
                    onClick={onEnrollFace}
                    className="mt-2 block font-medium underline focus:outline-none focus:ring-2 focus:ring-amber-600 rounded"
                  >
                    Enroll now
                  </button>
                )}
              </div>
            )}
            {result.sessionDetail.qr_code_enabled && (
              <div className={NOTICE_CLASSES}>
                This session uses a QR code, which this app can&rsquo;t provide yet. Your
                check-in may be rejected.
              </div>
            )}
          </div>

          {!isOnline && (
            <p role="status" className="mb-2 text-sm text-amber-800">
              You’re offline. Reconnect to start checking in.
            </p>
          )}
          <button
            type="button"
            onClick={handleStart}
            disabled={!isOnline || !windowOpen}
            className="btn btn-primary"
          >
            {windowInfo?.state === 'closed'
              ? 'Check-in closed'
              : windowInfo?.state === 'not-open-yet'
                ? 'Check-in not open yet'
                : 'Start check-in'}
          </button>
        </>
      )}
    </div>
  )
}
