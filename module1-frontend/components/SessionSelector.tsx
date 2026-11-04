'use client'

/**
 * SessionSelector
 *
 * Fetches the signed-in user's active session(s) via the existing
 * `api.getMySessions({ status: 'active' })` and lets them pick one
 * before continuing into the check-in flow. This component only reads
 * and displays already-typed API data and reports the user's explicit
 * choice via `onSessionSelected` — it does not call `POST /checkins/`, does
 * not request camera/location permissions, and does not persist the
 * selection anywhere (the selected id lives only in this component's React
 * state until Continue is clicked, at which point the parent takes over).
 *
 * Besides the sessions it makes two best-effort reads, in parallel and never
 * blocking the list: the student's own check-ins (`api.getMyCheckins`), so a
 * session they have already checked in to is labelled and opens its result
 * instead of the whole flow again, and their profile (`api.getCurrentUser`), so
 * a student with no enrolled face is offered enrollment. If either read fails the
 * list still works as before (the server still refuses a duplicate check-in).
 *
 * Each session also shows whether its check-in window is open, judged by this
 * device's clock (see lib/sessionWindow.ts). That is a hint: the backend decides.
 * A session outside its window cannot be continued from here.
 *
 * All session data is rendered as plain text via normal JSX
 * interpolation (React escapes it) — never via dangerouslySetInnerHTML
 * or any other HTML-injection path. Values (course code, name, venue,
 * dates) are treated as untrusted API response data purely for display;
 * no authorization decision is made client-side based on what's shown
 * here — the backend remains the sole authority when the user actually
 * attempts to check in.
 *
 * The mount guard closes the "logout while sessions are loading" race: if
 * the parent unmounts this component (which is exactly what happens on
 * logout) before a fetch settles, every `setState` call below is skipped.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/lib/api'
import { ACCOUNT_LOCKED_MESSAGE, ApiError } from '@/lib/errors'
import { checkinWindowState, formatSessionRange, presentWindow } from '@/lib/sessionWindow'
import { statusBadgeClasses, statusLabel } from '@/lib/checkinPresentation'
import { useNow } from '@/lib/useNow'
import { CheckIcon, FaceIcon } from '@/components/icons'
import type { CheckinSummary, Session } from '@/types/api'

type FetchStatus = 'loading' | 'error' | 'ready'

export interface SessionSelectorProps {
  /**
   * Called with the user's chosen session once they click Continue. `existing` is
   * the student's own check-in for that session, when they already have one.
   */
  onSessionSelected: (session: Session, existing?: CheckinSummary | null) => void
  /** If given, a student with no enrolled face is offered an "Enroll now" button. */
  onEnrollFace?: () => void
}

/** Maps a session-fetch failure to a static, user-friendly message — never the raw error. */
function describeSessionsError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'authentication':
        return 'Your session has expired. Please log in again.'
      case 'authorization':
        return 'You don’t have permission to view sessions.'
      case 'account_locked':
        return ACCOUNT_LOCKED_MESSAGE
      case 'rate_limit':
        return 'Too many requests. Please wait a moment and try again.'
      case 'network':
        return 'Unable to reach the server. Check your connection and try again.'
      case 'server':
        return 'Something went wrong on our end. Please try again shortly.'
      default:
        return error.message || 'Unable to load your sessions right now. Please try again.'
    }
  }
  return 'Unable to load your sessions right now. Please try again.'
}

export default function SessionSelector({ onSessionSelected, onEnrollFace }: SessionSelectorProps) {
  const [status, setStatus] = useState<FetchStatus>('loading')
  const [sessions, setSessions] = useState<Session[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  // Best-effort extras (see the file header): empty/null until loaded, and left
  // that way if the read fails.
  const [checkinsBySession, setCheckinsBySession] = useState<Map<string, CheckinSummary>>(
    () => new Map(),
  )
  const [faceEnrolled, setFaceEnrolled] = useState<boolean | null>(null)
  const isMountedRef = useRef(true)
  const now = useNow()

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const fetchSessions = useCallback(async () => {
    setStatus('loading')
    setErrorMessage(null)

    // Not awaited together with the sessions: they must never delay or fail the list.
    void api
      .getMyCheckins({ limit: 100 })
      .then((history) => {
        if (!isMountedRef.current) return
        const map = new Map<string, CheckinSummary>()
        for (const entry of history) {
          if (!map.has(entry.session_id)) map.set(entry.session_id, entry)
        }
        setCheckinsBySession(map)
      })
      .catch(() => undefined)
    void api
      .getCurrentUser()
      .then((user) => {
        if (isMountedRef.current) setFaceEnrolled(user.face_enrolled)
      })
      .catch(() => undefined)

    try {
      const data = await api.getMySessions({ status: 'active' })
      if (!isMountedRef.current) return

      setSessions(data)
      setStatus('ready')
      // Exactly one session: pre-select it, but the user still has to
      // click Continue explicitly — no auto-advance.
      if (data.length === 1) {
        setSelectedSessionId(data[0].id)
      }
    } catch (error) {
      if (!isMountedRef.current) return
      setErrorMessage(describeSessionsError(error))
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    void fetchSessions()
  }, [fetchSessions])

  // Sessions open for check-in first, then those not open yet, then closed ones.
  const windowRank = { open: 0, 'not-open-yet': 1, closed: 2 } as const
  const orderedSessions = [...sessions].sort(
    (a, b) =>
      windowRank[checkinWindowState(a.checkin_opens_at, a.checkin_closes_at, now)] -
      windowRank[checkinWindowState(b.checkin_opens_at, b.checkin_closes_at, now)],
  )

  const selectedSession = sessions.find((item) => item.id === selectedSessionId) ?? null
  const selectedExisting = selectedSession ? checkinsBySession.get(selectedSession.id) ?? null : null
  const selectedWindow = selectedSession
    ? presentWindow(selectedSession.checkin_opens_at, selectedSession.checkin_closes_at, now)
    : null
  // A session that already has a check-in opens its result; otherwise it must be inside its window.
  const canContinue =
    selectedSession !== null && (selectedExisting !== null || selectedWindow?.state === 'open')

  const handleContinue = useCallback(() => {
    if (selectedSession && canContinue) {
      onSessionSelected(selectedSession, selectedExisting)
    }
  }, [selectedSession, selectedExisting, canContinue, onSessionSelected])

  let continueLabel = 'Continue'
  if (selectedExisting) continueLabel = 'View check-in'
  else if (selectedWindow?.state === 'closed') continueLabel = 'Check-in closed'
  else if (selectedWindow?.state === 'not-open-yet') continueLabel = 'Check-in not open yet'

  return (
    <div className="card">
      <h2 className="mb-1 text-2xl font-bold">Select a Session</h2>
      <p className="mb-5 text-gray-600">
        Choose the session you&rsquo;d like to check in to.
      </p>

      {status === 'loading' && (
        <p className="text-sm text-gray-500">Loading your active sessions…</p>
      )}

      {status === 'error' && (
        <>
          <div
            role="alert"
            className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
          >
            {errorMessage}
          </div>
          <button type="button" onClick={() => void fetchSessions()} className="btn btn-primary">
            Retry
          </button>
        </>
      )}

      {status === 'ready' && sessions.length === 0 && (
        <>
          <p className="mb-4 text-sm text-gray-500">No active sessions available.</p>
          <button type="button" onClick={() => void fetchSessions()} className="btn btn-primary">
            Refresh
          </button>
        </>
      )}

      {status === 'ready' && sessions.length > 0 && (
        <>
          {faceEnrolled === false && onEnrollFace && (
            <div className="mb-5 flex items-start gap-3 rounded-2xl bg-amber-50 p-4 ring-1 ring-amber-200">
              <FaceIcon className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
              <div>
                <p className="text-sm font-semibold text-amber-900">Enroll your face once</p>
                <p className="text-sm text-amber-800">
                  Enrolling lets your check-in photos be verified against your face. It takes
                  a few seconds and you only do it once.
                </p>
                <button type="button" onClick={onEnrollFace} className="link mt-2 text-sm">
                  Enroll now
                </button>
              </div>
            </div>
          )}

          <fieldset className="mb-5">
            <legend className="mb-2 text-sm font-medium text-gray-700">Active sessions</legend>
            <div className="space-y-3">
              {orderedSessions.map((session) => {
                const windowInfo = presentWindow(
                  session.checkin_opens_at,
                  session.checkin_closes_at,
                  now,
                )
                const existing = checkinsBySession.get(session.id)
                const selected = selectedSessionId === session.id
                return (
                  <label
                    key={session.id}
                    htmlFor={`session-${session.id}`}
                    className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition focus-within:ring-2 focus-within:ring-brand-500 ${
                      selected
                        ? 'border-brand-500 bg-brand-50/60'
                        : 'border-gray-200 bg-white hover:border-brand-300'
                    }`}
                  >
                    <input
                      type="radio"
                      id={`session-${session.id}`}
                      name="session"
                      value={session.id}
                      checked={selected}
                      onChange={() => setSelectedSessionId(session.id)}
                      className="mt-1.5 h-4 w-4 shrink-0 accent-brand-600"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start justify-between gap-2">
                        <span className="font-semibold leading-snug">
                          {session.course_code ? `${session.course_code} — ` : ''}
                          {session.name}
                        </span>
                        <span className={`pill ${windowInfo.badgeClasses}`}>{windowInfo.badge}</span>
                      </span>
                      <span className="mt-0.5 block text-sm text-gray-600">
                        {session.venue_name}
                      </span>
                      <span className="block text-sm text-gray-500">
                        {formatSessionRange(session.scheduled_start, session.scheduled_end, now)}
                      </span>
                      <span className="mt-1.5 block text-xs font-medium text-gray-500">
                        {windowInfo.detail}
                      </span>
                      {existing && (
                        <span
                          className={`pill mt-2 gap-1 ${statusBadgeClasses(existing.status)}`}
                        >
                          <CheckIcon className="h-3 w-3" />
                          Checked in · {statusLabel(existing.status)}
                        </span>
                      )}
                    </span>
                  </label>
                )
              })}
            </div>
          </fieldset>

          <button
            type="button"
            onClick={handleContinue}
            disabled={!canContinue}
            className="btn btn-primary"
          >
            {continueLabel}
          </button>
          {selectedSession && !canContinue && selectedWindow && (
            <p className="mt-2 text-center text-xs text-gray-500">{selectedWindow.detail}</p>
          )}
        </>
      )}
    </div>
  )
}
