'use client'

/**
 * SessionSelector
 *
 * Fetches the signed-in user's active session(s) via the existing
 * `api.getMySessions({ status: 'active' })` and lets them pick one
 * before continuing into the check-in flow. This component only reads
 * and displays already-typed API data (`Session[]`) and reports the
 * user's explicit choice via `onSessionSelected` — it does not call
 * `POST /checkins/`, does not request camera/location permissions, and
 * does not persist the selection anywhere (the selected id lives only
 * in this component's React state until Continue is clicked, at which
 * point the parent takes over).
 *
 * All session data is rendered as plain text via normal JSX
 * interpolation (React escapes it) — never via dangerouslySetInnerHTML
 * or any other HTML-injection path. Values (course code, name, venue,
 * dates) are treated as untrusted API response data purely for display;
 * no authorization decision is made client-side based on what's shown
 * here — the backend remains the sole authority when the user actually
 * attempts to check in.
 *
 * Mirrors LoginForm.tsx/RegisterForm.tsx's error/loading pattern and
 * ConsentPrompt.tsx's mount-guard pattern. The mount guard specifically
 * closes the "logout while sessions are loading" race: if the parent
 * unmounts this component (which is exactly what happens on logout —
 * the whole authenticated subtree unmounts) before the fetch settles,
 * every `setState` call below is skipped.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/lib/api'
import { ApiError } from '@/lib/errors'
import type { Session } from '@/types/api'

type FetchStatus = 'loading' | 'error' | 'ready'

export interface SessionSelectorProps {
  /** Called with the user's chosen session once they click Continue. */
  onSessionSelected: (session: Session) => void
}

/** Maps a session-fetch failure to a static, user-friendly message — never the raw error. */
function describeSessionsError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'authentication':
        return 'Your session has expired. Please log in again.'
      case 'authorization':
        return 'You don’t have permission to view sessions.'
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

/** Formats an ISO start/end pair for display; falls back to the raw string if unparsable. */
function formatSessionWindow(start: string, end: string): string {
  const startDate = new Date(start)
  const endDate = new Date(end)
  const startText = Number.isNaN(startDate.getTime()) ? start : startDate.toLocaleString()
  const endText = Number.isNaN(endDate.getTime()) ? end : endDate.toLocaleString()
  return `${startText} – ${endText}`
}

export default function SessionSelector({ onSessionSelected }: SessionSelectorProps) {
  const [status, setStatus] = useState<FetchStatus>('loading')
  const [sessions, setSessions] = useState<Session[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const fetchSessions = useCallback(async () => {
    setStatus('loading')
    setErrorMessage(null)

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

  const handleContinue = useCallback(() => {
    const session = sessions.find((item) => item.id === selectedSessionId)
    if (session) {
      onSessionSelected(session)
    }
  }, [sessions, selectedSessionId, onSessionSelected])

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Select a Session</h2>
      <p className="text-gray-600 mb-4">
        Choose the session you&rsquo;d like to check in to.
      </p>

      {status === 'loading' && (
        <p className="text-sm text-gray-400">Loading your active sessions…</p>
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
            onClick={() => void fetchSessions()}
            className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Retry
          </button>
        </>
      )}

      {status === 'ready' && sessions.length === 0 && (
        <>
          <p className="text-sm text-gray-500 mb-4">No active sessions available.</p>
          <button
            type="button"
            onClick={() => void fetchSessions()}
            className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Refresh
          </button>
        </>
      )}

      {status === 'ready' && sessions.length > 0 && (
        <>
          <fieldset className="mb-6">
            <legend className="text-sm font-medium text-gray-700 mb-2">
              Active sessions
            </legend>
            <div className="space-y-3">
              {sessions.map((session) => (
                <label
                  key={session.id}
                  htmlFor={`session-${session.id}`}
                  className={`flex items-start gap-3 p-4 rounded border cursor-pointer focus-within:ring-2 focus-within:ring-blue-500 ${
                    selectedSessionId === session.id
                      ? 'border-blue-600 bg-blue-50'
                      : 'border-gray-300'
                  }`}
                >
                  <input
                    type="radio"
                    id={`session-${session.id}`}
                    name="session"
                    value={session.id}
                    checked={selectedSessionId === session.id}
                    onChange={() => setSelectedSessionId(session.id)}
                    className="mt-1"
                  />
                  <span>
                    <span className="block font-semibold">
                      {session.course_code} — {session.name}
                    </span>
                    <span className="block text-sm text-gray-600">
                      {session.venue_name}
                    </span>
                    <span className="block text-sm text-gray-500">
                      {formatSessionWindow(session.scheduled_start, session.scheduled_end)}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <button
            type="button"
            onClick={handleContinue}
            disabled={!selectedSessionId}
            className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Continue
          </button>
        </>
      )}
    </div>
  )
}
