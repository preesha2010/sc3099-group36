'use client'

/**
 * CheckInHistory
 *
 * "My check-ins": the student's own check-in history, a detail view for each
 * one, and — for a flagged or rejected check-in that hasn't been appealed — an
 * appeal form.
 *
 *   list  = GET /checkins/my-checkins        (api.getMyCheckins)
 *   item  = GET /checkins/{id}               (api.getCheckinById)
 *   appeal = POST /checkins/{id}/appeal       (api.appealCheckin) — { appeal_reason }
 *
 * Everything shown comes from the server: the status, the risk factors and any
 * reviewer note are displayed as plain, React-escaped text. The server decides
 * whether an appeal is allowed (status, one appeal per check-in, a time limit),
 * so the button is offered for flagged/rejected check-ins and the server's
 * refusal reasons are shown in friendly words. Nothing here is stored locally.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/lib/api'
import { ACCOUNT_LOCKED_MESSAGE, ApiError } from '@/lib/errors'
import { formatServerDateTime, parseServerDate } from '@/lib/dates'
import {
  describeRiskFactor,
  presentStatus,
  statusBadgeClasses,
  statusLabel,
} from '@/lib/checkinPresentation'
import { useOnlineStatus } from '@/lib/useOnlineStatus'
import { ChevronLeftIcon } from '@/components/icons'
import type { CheckinDetail, CheckinSummary } from '@/types/api'

export interface CheckInHistoryProps {
  /** Return to the session list. */
  onBack: () => void
  /** The session is no longer valid — return to Sign In. */
  onAuthExpired: () => void
}

type LoadStatus = 'loading' | 'error' | 'ready'
type AppealStatus = 'idle' | 'submitting' | 'sent'

const MAX_APPEAL_LENGTH = 1000

// The most the backend returns for one request (`limit` is capped at 100 and
// there is no `offset`), so this is as far back as the history can go.
const HISTORY_LIMIT = 100

const PRIMARY_BUTTON =
  'btn btn-primary'
const SECONDARY_BUTTON =
  'btn btn-secondary'

interface Problem {
  message: string
  sessionExpired: boolean
}

/** Static, friendly messages — never the raw backend or browser error. */
function describeLoadProblem(error: unknown): Problem {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'authentication':
        return { message: 'Your session has expired. Please log in again.', sessionExpired: true }
      case 'network':
        return {
          message: 'Unable to reach the server. Check your connection and try again.',
          sessionExpired: false,
        }
      case 'account_locked':
        return { message: ACCOUNT_LOCKED_MESSAGE, sessionExpired: false }
      case 'rate_limit':
        return {
          message: 'Too many requests. Please wait a moment and try again.',
          sessionExpired: false,
        }
      case 'server':
        return {
          message: 'Something went wrong on our end. Please try again shortly.',
          sessionExpired: false,
        }
      default:
        if (error.status === 404) {
          return { message: 'That check-in could not be found.', sessionExpired: false }
        }
    }
  }
  return {
    message: 'Unable to load your check-ins right now. Please try again.',
    sessionExpired: false,
  }
}

/**
 * The backend gives the reason it refused an appeal as a short sentence in
 * `detail`. Known sentences get a friendly message; anything else is generic.
 */
function describeAppealProblem(error: unknown): Problem {
  if (error instanceof ApiError) {
    const detail = typeof error.detail === 'string' ? error.detail.toLowerCase() : ''
    if (error.kind === 'client' && error.status === 400) {
      if (detail.includes('already appealed')) {
        return { message: 'This check-in has already been appealed.', sessionExpired: false }
      }
      if (detail.includes('window')) {
        return {
          message: 'The time allowed for appealing this check-in has passed.',
          sessionExpired: false,
        }
      }
      if (detail.includes('only appeal') || detail.includes('can only')) {
        return {
          message: 'Only flagged or rejected check-ins can be appealed.',
          sessionExpired: false,
        }
      }
      return { message: 'The server couldn’t accept this appeal.', sessionExpired: false }
    }
    if (error.kind === 'authorization') {
      return { message: 'You can only appeal your own check-ins.', sessionExpired: false }
    }
    if (error.kind === 'validation') {
      return {
        message: 'The appeal couldn’t be accepted. Check what you wrote and try again.',
        sessionExpired: false,
      }
    }
  }
  return describeLoadProblem(error)
}

function Notice({ problem, onLogin }: { problem: Problem; onLogin: () => void }) {
  return (
    <>
      <div
        role="alert"
        className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
      >
        {problem.message}
      </div>
      {problem.sessionExpired && (
        <button type="button" onClick={onLogin} className={`${PRIMARY_BUTTON} mb-4`}>
          Log in again
        </button>
      )}
    </>
  )
}

export default function CheckInHistory({ onBack, onAuthExpired }: CheckInHistoryProps) {
  const isOnline = useOnlineStatus()
  const isMountedRef = useRef(true)
  // A ref (not just state) so two quick taps can't both send an appeal.
  const isAppealingRef = useRef(false)

  const [listStatus, setListStatus] = useState<LoadStatus>('loading')
  const [listProblem, setListProblem] = useState<Problem | null>(null)
  const [entries, setEntries] = useState<CheckinSummary[]>([])

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailStatus, setDetailStatus] = useState<LoadStatus>('loading')
  const [detailProblem, setDetailProblem] = useState<Problem | null>(null)
  const [detail, setDetail] = useState<CheckinDetail | null>(null)

  const [appealOpen, setAppealOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [appealStatus, setAppealStatus] = useState<AppealStatus>('idle')
  const [appealProblem, setAppealProblem] = useState<Problem | null>(null)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const loadList = useCallback(async () => {
    setListStatus('loading')
    setListProblem(null)
    try {
      const data = await api.getMyCheckins({ limit: HISTORY_LIMIT })
      if (!isMountedRef.current) return
      // Newest first.
      const sorted = [...data].sort(
        (a, b) =>
          parseServerDate(b.checked_in_at).getTime() - parseServerDate(a.checked_in_at).getTime(),
      )
      setEntries(sorted)
      setListStatus('ready')
    } catch (error) {
      if (!isMountedRef.current) return
      setListProblem(describeLoadProblem(error))
      setListStatus('error')
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id)
    setDetail(null)
    setDetailStatus('loading')
    setDetailProblem(null)
    setAppealOpen(false)
    setReason('')
    setAppealStatus('idle')
    setAppealProblem(null)
    try {
      const data = await api.getCheckinById(id)
      if (!isMountedRef.current) return
      setDetail(data)
      setDetailStatus('ready')
    } catch (error) {
      if (!isMountedRef.current) return
      setDetailProblem(describeLoadProblem(error))
      setDetailStatus('error')
    }
  }, [])

  const closeDetail = useCallback(() => {
    setSelectedId(null)
    setDetail(null)
  }, [])

  const submitAppeal = useCallback(async () => {
    if (!detail || isAppealingRef.current) return
    const trimmed = reason.trim()
    if (trimmed.length === 0) return
    isAppealingRef.current = true
    setAppealStatus('submitting')
    setAppealProblem(null)
    try {
      const result = await api.appealCheckin(detail.id, { appeal_reason: trimmed })
      if (!isMountedRef.current) return
      setDetail({
        ...detail,
        status: result.status,
        appeal_reason: result.appeal_reason,
        appealed_at: result.appealed_at,
      })
      setEntries((current) =>
        current.map((entry) => (entry.id === detail.id ? { ...entry, status: result.status } : entry)),
      )
      setAppealOpen(false)
      setReason('')
      setAppealStatus('sent')
    } catch (error) {
      if (!isMountedRef.current) return
      setAppealProblem(describeAppealProblem(error))
      setAppealStatus('idle')
    } finally {
      isAppealingRef.current = false
    }
  }, [detail, reason])

  // ---------------------------------------------------------------- detail view
  if (selectedId) {
    const canAppeal =
      detail !== null &&
      (detail.status === 'flagged' || detail.status === 'rejected') &&
      !detail.appealed_at
    const submitting = appealStatus === 'submitting'
    const offlineBlocked = !isOnline && !submitting

    return (
      <div className="card">
        <button
          type="button"
          onClick={closeDetail}
          className="link mb-4 inline-flex items-center gap-1 text-sm"
        >
          <ChevronLeftIcon />
          All check-ins
        </button>

        {detailStatus === 'loading' && (
          <p role="status" className="text-sm text-gray-400">
            Loading check-in…
          </p>
        )}

        {detailStatus === 'error' && detailProblem && (
          <>
            <Notice problem={detailProblem} onLogin={onAuthExpired} />
            <button type="button" onClick={() => void openDetail(selectedId)} className={PRIMARY_BUTTON}>
              Retry
            </button>
          </>
        )}

        {detailStatus === 'ready' && detail && (
          <>
            {(() => {
              const presentation = presentStatus(detail.status, detail.risk_factors)
              return (
                <div
                  role="status"
                  className={`mb-4 p-4 rounded border-l-4 ${presentation.boxClasses}`}
                >
                  <h2 className="text-xl font-bold mb-1">{presentation.headline}</h2>
                  <p className="text-sm">{presentation.detail}</p>
                </div>
              )
            })()}

            <dl className="mb-4 space-y-1 text-sm text-gray-700">
              <div className="flex justify-between gap-4">
                <dt className="text-gray-500">Checked in at</dt>
                <dd>{formatServerDateTime(detail.checked_in_at)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-gray-500">Risk score</dt>
                <dd>{detail.risk_score.toFixed(2)}</dd>
              </div>
              {detail.distance_from_venue_meters !== null && (
                <div className="flex justify-between gap-4">
                  <dt className="text-gray-500">Distance from venue</dt>
                  <dd>{Math.round(detail.distance_from_venue_meters)} m</dd>
                </div>
              )}
              {detail.liveness_passed !== null && (
                <div className="flex justify-between gap-4">
                  <dt className="text-gray-500">Live photo check</dt>
                  <dd>{detail.liveness_passed ? 'Passed' : 'Did not pass'}</dd>
                </div>
              )}
              {detail.face_match_passed !== null && (
                <div className="flex justify-between gap-4">
                  <dt className="text-gray-500">Face match</dt>
                  <dd>{detail.face_match_passed ? 'Matched' : 'Did not match'}</dd>
                </div>
              )}
            </dl>

            {detail.risk_factors.length > 0 && (
              <div className="mb-4">
                <h3 className="text-sm font-medium text-gray-700 mb-1">Contributing factors</h3>
                <ul className="list-disc pl-5 text-sm text-gray-700 space-y-1">
                  {detail.risk_factors.map((factor, index) => (
                    <li key={`${factor.type}-${index}`}>{describeRiskFactor(factor.type)}</li>
                  ))}
                </ul>
              </div>
            )}

            {detail.reviewed_at && (
              <div className="mb-4 p-3 rounded bg-gray-50 text-sm text-gray-700">
                <p className="font-medium">
                  Reviewed on {formatServerDateTime(detail.reviewed_at)}
                </p>
                {detail.review_notes && <p className="mt-1">Note: {detail.review_notes}</p>}
              </div>
            )}

            {detail.appealed_at && (
              <div className="mb-4 p-3 rounded bg-brand-50 text-sm text-brand-800">
                <p className="font-medium">
                  Appeal sent on {formatServerDateTime(detail.appealed_at)}
                </p>
                {detail.appeal_reason && <p className="mt-1">Your reason: {detail.appeal_reason}</p>}
              </div>
            )}

            {appealStatus === 'sent' && (
              <div
                role="status"
                className="mb-4 p-3 rounded border-l-4 border-green-500 bg-green-50 text-sm text-green-800"
              >
                Your appeal has been sent. Your instructor will review it.
              </div>
            )}

            {appealProblem && <Notice problem={appealProblem} onLogin={onAuthExpired} />}

            {canAppeal && !appealOpen && (
              <button type="button" onClick={() => setAppealOpen(true)} className={`${PRIMARY_BUTTON} mb-2`}>
                Appeal this decision
              </button>
            )}

            {canAppeal && appealOpen && (
              <form
                className="mb-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  void submitAppeal()
                }}
              >
                <label htmlFor="appeal-reason" className="block text-sm font-medium text-gray-700 mb-1">
                  Why should this check-in be reviewed?
                </label>
                <textarea
                  id="appeal-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={MAX_APPEAL_LENGTH}
                  rows={4}
                  disabled={submitting}
                  className="field text-sm"
                />
                <p className="mt-1 mb-3 text-xs text-gray-400">
                  {reason.length}/{MAX_APPEAL_LENGTH}
                </p>
                {offlineBlocked && (
                  <p role="status" className="mb-3 text-sm text-amber-800">
                    You’re offline. Reconnect to send your appeal.
                  </p>
                )}
                <div className="space-y-2">
                  <button
                    type="submit"
                    disabled={submitting || offlineBlocked || reason.trim().length === 0}
                    aria-busy={submitting}
                    className={PRIMARY_BUTTON}
                  >
                    {submitting ? 'Sending…' : 'Send appeal'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setAppealOpen(false)}
                    disabled={submitting}
                    className={SECONDARY_BUTTON}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    )
  }

  // ------------------------------------------------------------------ list view
  return (
    <div className="card">
      <h2 className="mb-1 text-2xl font-bold">My check-ins</h2>
      <p className="mb-5 text-gray-600">Your attendance history, newest first.</p>

      {listStatus === 'loading' && (
        <p role="status" className="text-sm text-gray-400">
          Loading your check-ins…
        </p>
      )}

      {listStatus === 'error' && listProblem && (
        <>
          <Notice problem={listProblem} onLogin={onAuthExpired} />
          <button type="button" onClick={() => void loadList()} className={`${PRIMARY_BUTTON} mb-2`}>
            Retry
          </button>
        </>
      )}

      {listStatus === 'ready' && entries.length === 0 && (
        <p className="text-sm text-gray-500 mb-4">You haven’t checked in to any sessions yet.</p>
      )}

      {listStatus === 'ready' && entries.length >= HISTORY_LIMIT && (
        <p role="status" className="text-sm text-gray-500 mb-2">
          Showing your {HISTORY_LIMIT} most recent check-ins.
        </p>
      )}

      {listStatus === 'ready' && entries.length > 0 && (
        <ul className="mb-4 space-y-2">
          {entries.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                onClick={() => void openDetail(entry.id)}
                className="row-btn"
              >
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block font-semibold">
                      {entry.course_code ? `${entry.course_code} — ` : ''}
                      {entry.session_name}
                    </span>
                    <span className="block text-sm text-gray-500">
                      {formatServerDateTime(entry.checked_in_at)}
                    </span>
                  </span>
                  <span
                    className={`pill ${statusBadgeClasses(entry.status)}`}
                  >
                    {statusLabel(entry.status)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="space-y-2">
        {listStatus === 'ready' && (
          <button type="button" onClick={() => void loadList()} className={SECONDARY_BUTTON}>
            Refresh
          </button>
        )}
        <button type="button" onClick={onBack} className={SECONDARY_BUTTON}>
          Back to sessions
        </button>
      </div>
    </div>
  )
}
