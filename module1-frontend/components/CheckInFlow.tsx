'use client'

/**
 * CheckInFlow
 *
 * The check-in flow for the session chosen in app/page.tsx:
 *
 *   CheckInPreflight -> ConsentPrompt -> photo -> review & submit -> result
 *
 * - Preflight loads the session details / profile and best-effort registers
 *   the device (see CheckInPreflight).
 * - Consent: when the student clicks "Allow & Continue", consent is recorded with
 *   `PUT /users/me` (camera_consent / geolocation_consent) FIRST, via
 *   ConsentPrompt's `onBeforeRequest`; only then does ConsentPrompt ask the
 *   browser for the camera / location. If recording fails nothing is requested
 *   and the student can retry — we never collect data without consent on record.
 *   Skipped if the profile already has the needed flags set.
 * - Photo: the existing LivenessChallenge (instructions) + CameraCapture take
 *   exactly ONE photo, matching the single `liveness_challenge_response` field
 *   in the API. Skipped entirely when the session needs no liveness photo.
 * - Review & submit: the student explicitly submits. Submission goes through
 *   lib/checkin.ts -> `POST /checkins/`. Success is only shown once the API has
 *   actually answered, and the outcome shown follows the server's `status`.
 *
 * Captured images live in React state only, and are dropped as soon as the
 * check-in has a result. Nothing is persisted or logged here.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/lib/api'
import { ACCOUNT_LOCKED_MESSAGE, ApiError } from '@/lib/errors'
import { GeolocationRequestError } from '@/lib/geolocation'
import {
  DeviceIdentityError,
  findExistingCheckin,
  submitCheckin,
  type SubmitPhase,
} from '@/lib/checkin'
import ConsentPrompt from '@/components/ConsentPrompt'
import CameraCapture from '@/components/CameraCapture'
import LivenessChallenge from '@/components/LivenessChallenge'
import CheckInPreflight, {
  type CheckInPreflightResult,
} from '@/components/CheckInPreflight'
import CheckInResult, { type CheckInOutcome } from '@/components/CheckInResult'
import { useOnlineStatus } from '@/lib/useOnlineStatus'
import type { Session } from '@/types/api'

export interface CheckInFlowProps {
  session: Session
  /** Leave the flow and return to session selection. */
  onExit: () => void
  /** The session is no longer valid (token refresh failed) — return to Sign In. */
  onAuthExpired: () => void
  /** Open face enrollment (offered when the session needs a face match and none is enrolled). */
  onEnrollFace?: () => void
}

type FlowStep = 'consent' | 'photo' | 'review' | 'result'
type FailureAction = 'retry' | 'login' | 'back'

interface Failure {
  message: string
  action: FailureAction
}

const STEP_LABELS: Record<'consent' | 'photo' | 'review', string> = {
  consent: 'Consent',
  photo: 'Photo',
  review: 'Review & Submit',
}

const PRIMARY_BUTTON =
  'w-full py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2'
const SECONDARY_BUTTON =
  'w-full py-2 px-4 rounded border border-gray-300 text-gray-700 font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2'

const SESSION_EXPIRED: Failure = {
  message: 'Your session has expired. Please log in again.',
  action: 'login',
}

/**
 * The backend gives the reason for refusing a check-in as a short, fixed
 * sentence in `detail` ("Session not active", "Check-in window closed", …).
 * Those exact sentences are matched here to show a specific, friendly message;
 * the raw text itself is never displayed, and anything unrecognised falls back
 * to a generic message.
 */
function describeCheckinRefusal(error: ApiError): string | null {
  const detail = typeof error.detail === 'string' ? error.detail.toLowerCase() : ''
  if (detail.includes('window closed')) {
    return 'This session isn’t open for check-in right now: its check-in window has closed or hasn’t opened yet.'
  }
  if (detail.includes('not active')) {
    return 'This session isn’t active, so it can’t accept check-ins.'
  }
  if (detail.includes('not enrolled')) {
    return 'You aren’t enrolled in this course, so you can’t check in to this session.'
  }
  if (detail.includes('qr')) {
    return 'This session needs a QR code, which this app can’t scan yet. Ask your instructor for help.'
  }
  if (detail.includes('already checked in')) {
    return 'The server reports that you’ve already checked in to this session.'
  }
  if (detail.includes('location')) {
    return 'Check-in isn’t allowed from your current location or network. It is only available from within Singapore (check you aren’t using a VPN).'
  }
  return null
}

/** Static, user-friendly messages — never the raw backend or browser error. */
function describeSubmitFailure(error: unknown): Failure {
  if (error instanceof GeolocationRequestError) {
    switch (error.kind) {
      case 'permission_denied':
        return {
          message:
            'Location permission was denied. Allow location access for this site in your browser settings, then try again.',
          action: 'retry',
        }
      case 'unsupported':
        return {
          message: 'This browser doesn’t support location, which check-in requires.',
          action: 'back',
        }
      case 'position_unavailable':
        return {
          message:
            'Your location is currently unavailable. Move somewhere with a better signal and try again.',
          action: 'retry',
        }
      case 'timeout':
        return {
          message: 'Getting your location timed out. Please try again.',
          action: 'retry',
        }
      default:
        return { message: 'We couldn’t get your location. Please try again.', action: 'retry' }
    }
  }

  if (error instanceof DeviceIdentityError) {
    return {
      message:
        'This browser can’t identify your device, which check-in requires. A secure (HTTPS) connection may be needed.',
      action: 'back',
    }
  }

  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'authentication':
        return SESSION_EXPIRED
      case 'authorization':
        return {
          message:
            describeCheckinRefusal(error) ??
            'You don’t have permission to check in to this session.',
          action: 'back',
        }
      case 'account_locked':
        // Retrying cannot help, so the only next step offered is going back.
        return { message: ACCOUNT_LOCKED_MESSAGE, action: 'back' }
      case 'rate_limit':
        return {
          message: 'Too many attempts. Please wait a moment and try again.',
          action: 'retry',
        }
      case 'network':
        return {
          message: 'Unable to reach the server. Check your connection and try again.',
          action: 'retry',
        }
      case 'server':
        return {
          message: 'Something went wrong on our end. Please try again shortly.',
          action: 'retry',
        }
      case 'validation':
        return {
          message:
            'The server couldn’t accept the check-in details. Try again, or retake your photo.',
          action: 'retry',
        }
      case 'client':
        if (error.status === 400) {
          return {
            message:
              describeCheckinRefusal(error) ??
              'This check-in couldn’t be accepted. The session may not be open, its check-in window may have closed, or you may already be checked in.',
            action: 'back',
          }
        }
        if (error.status === 404) {
          return { message: 'This session could not be found.', action: 'back' }
        }
        return { message: 'Your check-in couldn’t be completed.', action: 'back' }
    }
  }

  return {
    message: 'Something went wrong preparing your check-in. Please try again.',
    action: 'retry',
  }
}

function describeConsentFailure(error: unknown): Failure {
  if (error instanceof ApiError) {
    if (error.kind === 'authentication') return SESSION_EXPIRED
    if (error.kind === 'account_locked') return { message: ACCOUNT_LOCKED_MESSAGE, action: 'back' }
    if (error.kind === 'network') {
      return {
        message: 'Unable to reach the server to save your consent. Check your connection and try again.',
        action: 'retry',
      }
    }
  }
  return {
    message: 'We couldn’t save your consent, so we can’t continue yet. Please try again.',
    action: 'retry',
  }
}

interface FailureNoticeProps {
  failure: Failure
  disabled?: boolean
  /** Disables only the retry button (e.g. while offline); going back stays available. */
  retryDisabled?: boolean
  retryLabel: string
  onRetry: () => void
  onLogin: () => void
  onBack: () => void
}

/** The error alert plus the single sensible next action (retry, log in again, or go back). */
function FailureNotice({
  failure,
  disabled = false,
  retryDisabled = false,
  retryLabel,
  onRetry,
  onLogin,
  onBack,
}: FailureNoticeProps) {
  return (
    <>
      <div
        role="alert"
        className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
      >
        {failure.message}
      </div>
      <div className="space-y-2">
        {failure.action === 'retry' && (
          <button
            type="button"
            onClick={onRetry}
            disabled={disabled || retryDisabled}
            className={PRIMARY_BUTTON}
          >
            {retryLabel}
          </button>
        )}
        {failure.action === 'login' && (
          <button type="button" onClick={onLogin} className={PRIMARY_BUTTON}>
            Log in again
          </button>
        )}
        {failure.action !== 'login' && (
          <button type="button" onClick={onBack} disabled={disabled} className={SECONDARY_BUTTON}>
            Back to sessions
          </button>
        )}
      </div>
    </>
  )
}

export default function CheckInFlow({
  session,
  onExit,
  onAuthExpired,
  onEnrollFace,
}: CheckInFlowProps) {
  // Set once the preflight completes: session details + the user's profile.
  const [preflightResult, setPreflightResult] = useState<CheckInPreflightResult | null>(
    null,
  )

  const [step, setStep] = useState<FlowStep>('consent')
  const [consentFailure, setConsentFailure] = useState<Failure | null>(null)

  // The single liveness photo (a data URL), kept in memory only.
  const [livenessImage, setLivenessImage] = useState<string | null>(null)
  const [isLivenessCaptureRequested, setIsLivenessCaptureRequested] = useState(false)

  const [submitPhase, setSubmitPhase] = useState<SubmitPhase | null>(null)
  const [submitFailure, setSubmitFailure] = useState<Failure | null>(null)
  const [outcome, setOutcome] = useState<CheckInOutcome | null>(null)

  const isOnline = useOnlineStatus()
  const isMountedRef = useRef(true)
  // A ref (not just state) so two rapid clicks can't both start a submission
  // before React has re-rendered the disabled button.
  const isSubmittingRef = useRef(false)
  // Consent only needs recording once per flow, even if the permission step is retried.
  const consentSavedRef = useRef(false)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  // Runs when the student clicks "Allow & Continue", BEFORE ConsentPrompt asks
  // the browser for the camera or location — so consent is on record before any
  // data is collected. A rejection stops ConsentPrompt before it requests anything.
  const saveConsent = useCallback(async () => {
    if (!preflightResult || consentSavedRef.current) return
    const { sessionDetail, user } = preflightResult
    const needsPhoto = sessionDetail.require_liveness_check

    // Only record consent for what this check-in actually uses, and only if the
    // profile doesn't already have it recorded.
    if (user.geolocation_consent && (!needsPhoto || user.camera_consent)) {
      consentSavedRef.current = true
      return
    }

    setConsentFailure(null)
    try {
      await api.updateCurrentUser({
        geolocation_consent: true,
        ...(needsPhoto ? { camera_consent: true } : {}),
      })
      consentSavedRef.current = true
    } catch (error) {
      const failure = describeConsentFailure(error)
      if (isMountedRef.current) setConsentFailure(failure)
      // ConsentPrompt shows this static message; never the raw backend error.
      throw new Error(failure.message)
    }
  }, [preflightResult])

  const handleConsentGranted = useCallback(() => {
    if (!preflightResult) return
    setStep(preflightResult.sessionDetail.require_liveness_check ? 'photo' : 'review')
  }, [preflightResult])

  const handleLivenessRequestCapture = useCallback(() => {
    setIsLivenessCaptureRequested(true)
  }, [])

  const handleLivenessCameraCapture = useCallback((imageData: string) => {
    setLivenessImage(imageData)
    setIsLivenessCaptureRequested(false)
    setStep('review')
  }, [])

  const handleRetakePhoto = useCallback(() => {
    setLivenessImage(null)
    setIsLivenessCaptureRequested(false)
    setSubmitFailure(null)
    setStep('photo')
  }, [])

  const handleSubmit = useCallback(async () => {
    if (!preflightResult || isSubmittingRef.current) return
    isSubmittingRef.current = true
    setSubmitFailure(null)
    setSubmitPhase('locating')

    const sessionId = preflightResult.sessionDetail.id
    try {
      const checkin = await submitCheckin({
        sessionId,
        livenessImage,
        onPhase: (phase) => {
          if (isMountedRef.current) setSubmitPhase(phase)
        },
      })
      if (!isMountedRef.current) return
      // Only now — after the API confirmed — do we show a result, and the
      // captured photo is no longer needed.
      setLivenessImage(null)
      setOutcome({ kind: 'submitted', checkin })
      setStep('result')
    } catch (error) {
      if (!isMountedRef.current) return

      // A 400 can mean "already checked in" (including an earlier attempt whose
      // response was lost). Check the student's own history rather than guessing
      // from the backend's message text.
      if (error instanceof ApiError && error.kind === 'client' && error.status === 400) {
        const existing = await findExistingCheckin(
          sessionId,
          preflightResult.sessionDetail.course_id,
        ).catch(() => null)
        if (!isMountedRef.current) return
        if (existing) {
          setLivenessImage(null)
          setOutcome({ kind: 'already', checkin: existing })
          setStep('result')
          return
        }
      }
      setSubmitFailure(describeSubmitFailure(error))
    } finally {
      isSubmittingRef.current = false
      if (isMountedRef.current) setSubmitPhase(null)
    }
  }, [preflightResult, livenessImage])

  if (!preflightResult) {
    return (
      <CheckInPreflight
        session={session}
        onReady={setPreflightResult}
        onEnrollFace={onEnrollFace}
      />
    )
  }

  const needsPhoto = preflightResult.sessionDetail.require_liveness_check
  const stepOrder: Array<'consent' | 'photo' | 'review'> = needsPhoto
    ? ['consent', 'photo', 'review']
    : ['consent', 'review']
  const stepNumber = step === 'result' ? 0 : stepOrder.indexOf(step) + 1
  const isSubmitting = submitPhase !== null
  const canSubmit = !submitFailure || submitFailure.action === 'retry'
  // A hint only (see useOnlineStatus): offline reliably blocks submitting, but
  // "online" never skips the real error handling in handleSubmit. An attempt
  // already in flight is left to finish and report its own result.
  const submitBlockedOffline = !isOnline && !isSubmitting

  return (
    <div>
      {step !== 'result' && stepNumber > 0 && (
        <p className="text-center text-sm font-medium text-gray-500 mb-8">
          {`Step ${stepNumber} of ${stepOrder.length}: ${STEP_LABELS[stepOrder[stepNumber - 1]]}`}
        </p>
      )}

      {step === 'consent' && (
        <>
          <ConsentPrompt
            requireCamera={needsPhoto}
            onBeforeRequest={saveConsent}
            onConsentGranted={handleConsentGranted}
          />
          {consentFailure?.action === 'login' && (
            <div className="max-w-md mx-auto mt-3">
              <button type="button" onClick={onAuthExpired} className={PRIMARY_BUTTON}>
                Log in again
              </button>
            </div>
          )}
        </>
      )}

      {step === 'photo' && (
        <div className="space-y-6">
          <LivenessChallenge
            hasCaptured={livenessImage !== null}
            onRequestCapture={handleLivenessRequestCapture}
          />

          {isLivenessCaptureRequested && (
            <CameraCapture onCapture={handleLivenessCameraCapture} />
          )}
        </div>
      )}

      {step === 'review' && (
        <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
          <h2 className="text-2xl font-bold mb-2">Review &amp; Submit</h2>
          <p className="text-gray-600 mb-4">
            You&rsquo;re about to check in to{' '}
            <strong>{preflightResult.sessionDetail.name}</strong>. Your location will be
            read when you submit.
          </p>

          {livenessImage ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={livenessImage}
              alt="Your captured photo"
              className="w-full rounded mb-4"
            />
          ) : (
            !needsPhoto && (
              <p className="text-sm text-gray-500 mb-4">
                No photo is required for this session.
              </p>
            )
          )}

          {isSubmitting && (
            <p role="status" className="text-sm text-gray-500 mb-4">
              {submitPhase === 'locating' ? 'Getting your location…' : 'Submitting your check-in…'}
            </p>
          )}

          {submitBlockedOffline && (
            <p role="status" className="text-sm text-amber-800 mb-4">
              You’re offline. Check-in needs a connection — reconnect to submit.
              {needsPhoto &&
                ' Keep this page open — your photo isn’t saved anywhere else.'}
            </p>
          )}

          {submitFailure ? (
            <FailureNotice
              failure={submitFailure}
              disabled={isSubmitting}
              retryDisabled={submitBlockedOffline}
              retryLabel={isSubmitting ? 'Submitting…' : 'Try again'}
              onRetry={() => void handleSubmit()}
              onLogin={onAuthExpired}
              onBack={onExit}
            />
          ) : (
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={isSubmitting || submitBlockedOffline}
                aria-busy={isSubmitting}
                className={PRIMARY_BUTTON}
              >
                {isSubmitting ? 'Submitting…' : 'Submit check-in'}
              </button>
              {needsPhoto && (
                <button
                  type="button"
                  onClick={handleRetakePhoto}
                  disabled={isSubmitting}
                  className={SECONDARY_BUTTON}
                >
                  Retake photo
                </button>
              )}
              <button
                type="button"
                onClick={onExit}
                disabled={isSubmitting}
                className={SECONDARY_BUTTON}
              >
                Back to sessions
              </button>
            </div>
          )}

          {submitFailure && canSubmit && needsPhoto && (
            <button
              type="button"
              onClick={handleRetakePhoto}
              disabled={isSubmitting}
              className={`${SECONDARY_BUTTON} mt-2`}
            >
              Retake photo
            </button>
          )}
        </div>
      )}

      {step === 'result' && outcome && <CheckInResult outcome={outcome} onDone={onExit} />}
    </div>
  )
}
