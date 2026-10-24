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
 * Everything shown here is INFORMATIONAL. Nothing is hard-blocked on the
 * client: the backend remains the sole authority on whether a check-in is
 * accepted, so a notice such as "face match required but not enrolled"
 * warns the user but never stops them from continuing.
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
import { formatServerDateTime, parseServerDate } from '@/lib/dates'
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

/**
 * Whether the session's check-in window looks open, going by this device's
 * clock. Informational only: the server decides, and a device with a wrong
 * clock can be mistaken, so this never blocks anything.
 */
function checkinWindowState(opensAt: string, closesAt: string): 'open' | 'not-open-yet' | 'closed' {
  const now = Date.now()
  const opens = parseServerDate(opensAt).getTime()
  const closes = parseServerDate(closesAt).getTime()
  if (!Number.isNaN(closes) && now > closes) return 'closed'
  if (!Number.isNaN(opens) && now < opens) return 'not-open-yet'
  return 'open'
}

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

  const handleStart = useCallback(() => {
    if (result) onReady(result)
  }, [result, onReady])

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Ready to Check In</h2>
      <p className="text-gray-600 mb-4">
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
            className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Retry
          </button>
        </>
      )}

      {status === 'ready' && result && (
        <>
          <div className="mb-4 p-4 rounded border border-gray-200 bg-gray-50">
            <p className="font-semibold">
              {session.course_code} — {result.sessionDetail.name}
            </p>
            <p className="text-sm text-gray-600">{result.sessionDetail.venue_name}</p>
            <p className="text-sm text-gray-500">
              {formatDateTime(result.sessionDetail.scheduled_start)} –{' '}
              {formatDateTime(result.sessionDetail.scheduled_end)}
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
            {checkinWindowState(
              result.sessionDetail.checkin_opens_at,
              result.sessionDetail.checkin_closes_at,
            ) === 'closed' && (
              <div className={NOTICE_CLASSES}>
                The check-in window for this session closed at{' '}
                {formatDateTime(result.sessionDetail.checkin_closes_at)}, so check-in will
                probably be rejected.
              </div>
            )}
            {checkinWindowState(
              result.sessionDetail.checkin_opens_at,
              result.sessionDetail.checkin_closes_at,
            ) === 'not-open-yet' && (
              <div className={NOTICE_CLASSES}>
                Check-in for this session opens at{' '}
                {formatDateTime(result.sessionDetail.checkin_opens_at)}, so check-in will
                probably be rejected until then.
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
            disabled={!isOnline}
            className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Start check-in
          </button>
        </>
      )}
    </div>
  )
}
