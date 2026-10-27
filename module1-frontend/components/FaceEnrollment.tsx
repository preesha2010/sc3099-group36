'use client'

/**
 * FaceEnrollment
 *
 * Lets a student enroll their face so later check-ins can be matched against it
 * (`POST /users/me/face/enroll`).
 *
 *   intro  -> explains it, shows whether a face is already enrolled
 *   capture -> ONE photo via the existing CameraCapture
 *   review  -> preview, retake or enroll
 *   done    -> result
 *
 * Camera consent is saved (`PUT /users/me`, camera_consent) when the student
 * agrees on the first screen — BEFORE the camera starts — and the API requires
 * it before it will enroll. The photo is held in React state only and is
 * dropped as soon as the server has answered. Nothing is stored or logged.
 *
 * The backend answers `400` both when consent is missing and when no clear face
 * is found, and `503` when the face service is down; the reason it gives is
 * matched to a friendly message, and the raw text is never shown.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/lib/api'
import { ACCOUNT_LOCKED_MESSAGE, ApiError } from '@/lib/errors'
import { submitFaceEnrollment } from '@/lib/faceEnrollment'
import { useOnlineStatus } from '@/lib/useOnlineStatus'
import CameraCapture from '@/components/CameraCapture'
import type { FaceEnrollResponse, UserResponse } from '@/types/api'

export interface FaceEnrollmentProps {
  /** Leave without enrolling (or after finishing). */
  onBack: () => void
  /** The session is no longer valid — return to Sign In. */
  onAuthExpired: () => void
  /** Label for the leave button, depending on where the student came from. */
  backLabel?: string
}

type Step = 'loading' | 'intro' | 'capture' | 'review' | 'done'
type ProblemAction = 'retry' | 'retake' | 'login' | 'intro'

interface Problem {
  message: string
  action: ProblemAction
}

const PRIMARY_BUTTON =
  'btn btn-primary'
const SECONDARY_BUTTON =
  'btn btn-secondary'

const SESSION_EXPIRED: Problem = {
  message: 'Your session has expired. Please log in again.',
  action: 'login',
}

function describeGeneralProblem(error: unknown): Problem {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'authentication':
        return SESSION_EXPIRED
      case 'network':
        return {
          message: 'Unable to reach the server. Check your connection and try again.',
          action: 'retry',
        }
      case 'account_locked':
        // Retrying cannot help; the only next step offered is logging in again.
        return { message: ACCOUNT_LOCKED_MESSAGE, action: 'login' }
      case 'rate_limit':
        return {
          message: 'Too many requests. Please wait a moment and try again.',
          action: 'retry',
        }
      case 'server':
        return {
          message: 'Something went wrong on our end. Please try again shortly.',
          action: 'retry',
        }
    }
  }
  return { message: 'Something went wrong. Please try again.', action: 'retry' }
}

function describeEnrollProblem(error: unknown): Problem {
  if (error instanceof ApiError) {
    const detail = typeof error.detail === 'string' ? error.detail.toLowerCase() : ''
    if (error.kind === 'server' && error.status === 503) {
      return {
        message: 'The face-recognition service isn’t available right now. Please try again later.',
        action: 'retry',
      }
    }
    if (error.kind === 'client' || error.kind === 'validation') {
      if (detail.includes('consent')) {
        return {
          message: 'Camera consent isn’t recorded yet. Go back and agree first, then try again.',
          action: 'intro',
        }
      }
      return {
        message:
          'We couldn’t find a clear face in that photo (or it couldn’t be used). Face the camera in good light with nothing covering your face, then retake it.',
        action: 'retake',
      }
    }
  }
  return describeGeneralProblem(error)
}

export default function FaceEnrollment({
  onBack,
  onAuthExpired,
  backLabel = 'Back to sessions',
}: FaceEnrollmentProps) {
  const isOnline = useOnlineStatus()
  const isMountedRef = useRef(true)
  // A ref (not just state) so two quick taps can't send two enrollments.
  const isEnrollingRef = useRef(false)

  const [step, setStep] = useState<Step>('loading')
  const [user, setUser] = useState<UserResponse | null>(null)
  const [photo, setPhoto] = useState<string | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<FaceEnrollResponse | null>(null)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const loadUser = useCallback(async () => {
    setStep('loading')
    setProblem(null)
    try {
      const me = await api.getCurrentUser()
      if (!isMountedRef.current) return
      setUser(me)
      setStep('intro')
    } catch (error) {
      if (!isMountedRef.current) return
      setProblem(describeGeneralProblem(error))
      setStep('intro')
    }
  }, [])

  useEffect(() => {
    void loadUser()
  }, [loadUser])

  // Agree: record camera consent FIRST, and only then let the camera start.
  const handleAgree = useCallback(async () => {
    if (!user) return
    setProblem(null)
    if (!user.camera_consent) {
      setBusy(true)
      try {
        const updated = await api.updateCurrentUser({ camera_consent: true })
        if (!isMountedRef.current) return
        setUser(updated)
      } catch (error) {
        if (!isMountedRef.current) return
        setProblem({
          ...describeGeneralProblem(error),
          message:
            error instanceof ApiError && error.kind === 'authentication'
              ? SESSION_EXPIRED.message
              : 'We couldn’t save your consent, so the camera hasn’t been started. Please try again.',
        })
        return
      } finally {
        if (isMountedRef.current) setBusy(false)
      }
    }
    setStep('capture')
  }, [user])

  const handleCaptured = useCallback((imageData: string) => {
    setPhoto(imageData)
    setProblem(null)
    setStep('review')
  }, [])

  const handleRetake = useCallback(() => {
    setPhoto(null)
    setProblem(null)
    setStep('capture')
  }, [])

  const handleEnroll = useCallback(async () => {
    if (!photo || isEnrollingRef.current) return
    isEnrollingRef.current = true
    setBusy(true)
    setProblem(null)
    try {
      const response = await submitFaceEnrollment(photo)
      if (!isMountedRef.current) return
      setResult(response)
      setPhoto(null) // the photo is no longer needed
      setUser((current) => (current ? { ...current, face_enrolled: true } : current))
      setStep('done')
    } catch (error) {
      if (!isMountedRef.current) return
      setProblem(describeEnrollProblem(error))
    } finally {
      isEnrollingRef.current = false
      if (isMountedRef.current) setBusy(false)
    }
  }, [photo])

  const offlineBlocked = !isOnline && !busy

  const notice = problem && (
    <div
      role="alert"
      className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
    >
      {problem.message}
    </div>
  )

  return (
    <div className="card">
      <h2 className="mb-1 text-2xl font-bold">Face enrollment</h2>

      {step === 'loading' && (
        <>
          <p role="status" className="mb-4 text-sm text-gray-400">
            Loading…
          </p>
          <button type="button" onClick={onBack} className={SECONDARY_BUTTON}>
            {backLabel}
          </button>
        </>
      )}

      {step === 'intro' && (
        <>
          <p className="mb-5 text-gray-600">
            Enrolling your face lets SAIV check that it’s really you when you check in. You take
            one photo now; the server keeps a face template made from it, and this app does not
            keep the photo.
          </p>

          {user && (
            <p
              role="status"
              className={`mb-4 p-3 rounded text-sm ${
                user.face_enrolled ? 'bg-green-50 text-green-800' : 'bg-gray-50 text-gray-700'
              }`}
            >
              {user.face_enrolled
                ? 'Your face is already enrolled. You can enroll again to replace it.'
                : 'No face is enrolled on your account yet.'}
            </p>
          )}

          {notice}
          {problem?.action === 'login' && (
            <button type="button" onClick={onAuthExpired} className={`${PRIMARY_BUTTON} mb-2`}>
              Log in again
            </button>
          )}

          <div className="space-y-2">
            {user ? (
              <>
                <p className="text-xs text-gray-500">
                  By continuing you agree to SAIV using your camera to enroll your face.
                </p>
                <button
                  type="button"
                  onClick={() => void handleAgree()}
                  disabled={busy}
                  className={PRIMARY_BUTTON}
                >
                  {busy ? 'Saving your consent…' : user.face_enrolled ? 'Agree and re-enroll' : 'Agree and continue'}
                </button>
              </>
            ) : (
              <button type="button" onClick={() => void loadUser()} className={PRIMARY_BUTTON}>
                Retry
              </button>
            )}
            <button type="button" onClick={onBack} className={SECONDARY_BUTTON}>
              {backLabel}
            </button>
          </div>
        </>
      )}

      {step === 'capture' && (
        <>
          <p className="mb-5 text-gray-600">
            Face the camera in good light, with nothing covering your face, then capture one photo.
          </p>
          <CameraCapture onCapture={handleCaptured} />
          <button type="button" onClick={onBack} className={`${SECONDARY_BUTTON} mt-4`}>
            Cancel
          </button>
        </>
      )}

      {step === 'review' && photo && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={photo} alt="Your captured photo" className="w-full rounded mb-4" />

          {notice}
          {problem?.action === 'login' && (
            <button type="button" onClick={onAuthExpired} className={`${PRIMARY_BUTTON} mb-2`}>
              Log in again
            </button>
          )}
          {offlineBlocked && (
            <p role="status" className="mb-4 text-sm text-amber-800">
              You’re offline. Reconnect to enroll — keep this page open, your photo isn’t saved
              anywhere else.
            </p>
          )}

          <div className="space-y-2">
            {problem?.action !== 'login' && problem?.action !== 'intro' && (
              <button
                type="button"
                onClick={() => void handleEnroll()}
                disabled={busy || offlineBlocked}
                aria-busy={busy}
                className={PRIMARY_BUTTON}
              >
                {busy ? 'Enrolling…' : problem?.action === 'retry' ? 'Try again' : 'Enroll this photo'}
              </button>
            )}
            {problem?.action === 'intro' && (
              <button
                type="button"
                onClick={() => {
                  setPhoto(null)
                  setProblem(null)
                  setStep('intro')
                }}
                className={PRIMARY_BUTTON}
              >
                Back to consent
              </button>
            )}
            <button type="button" onClick={handleRetake} disabled={busy} className={SECONDARY_BUTTON}>
              Retake photo
            </button>
            <button type="button" onClick={onBack} disabled={busy} className={SECONDARY_BUTTON}>
              Cancel
            </button>
          </div>
        </>
      )}

      {step === 'done' && (
        <>
          <div
            role="status"
            className="mb-4 p-4 rounded border-l-4 border-green-500 bg-green-50 text-green-800"
          >
            <h3 className="text-xl font-bold mb-1">Face enrolled</h3>
            <p className="text-sm">
              Your face is enrolled, so your check-ins can now be matched against it.
              {result && result.quality_score !== null
                ? ` Photo quality: ${result.quality_score.toFixed(2)}.`
                : ''}
            </p>
          </div>
          <button type="button" onClick={onBack} className={PRIMARY_BUTTON}>
            {backLabel}
          </button>
        </>
      )}
    </div>
  )
}
