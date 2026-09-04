'use client'

/**
 * LivenessChallenge
 *
 * A small instructional component for the check-in flow's liveness
 * step. Per the documented backend contract (docs/API-SPECIFICATION.md's
 * `POST /liveness/check`, which the backend calls internally when
 * processing `POST /checkins/`'s optional `liveness_challenge_response`
 * field — this frontend never calls Module 3 directly), liveness
 * verification here means exactly ONE passive photo, analyzed
 * server-side with no user action required. There is no multi-step
 * challenge sequence to guide the user through.
 *
 * This component does NOT touch the camera, does NOT verify liveness,
 * and does NOT call any API — it only explains what's about to happen
 * and tells the parent when the user is ready via `onRequestCapture`.
 * The parent owns the actual capture (via CameraCapture) and whatever
 * "captured" state exists; this component just reflects that state back
 * (`hasCaptured`) for display purposes.
 */

import { useCallback, useEffect, useState } from 'react'

export interface LivenessChallengeProps {
  /** True once the parent holds a captured liveness photo. */
  hasCaptured: boolean
  /** Called when the user is ready to have the single capture requested. */
  onRequestCapture: () => void
  /**
   * Optional, already-sanitized error message from the parent (e.g. a
   * failed capture attempt) to display. This component never generates
   * or logs error detail itself.
   */
  error?: string | null
}

export default function LivenessChallenge({
  hasCaptured,
  onRequestCapture,
  error = null,
}: LivenessChallengeProps) {
  const [awaitingCapture, setAwaitingCapture] = useState(false)

  // Clears the double-click guard whenever the parent's outcome
  // (captured, or a new/cleared error) changes.
  useEffect(() => {
    setAwaitingCapture(false)
  }, [hasCaptured, error])

  const handleRequestCapture = useCallback(() => {
    if (awaitingCapture || hasCaptured) {
      return
    }
    setAwaitingCapture(true)
    onRequestCapture()
  }, [awaitingCapture, hasCaptured, onRequestCapture])

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Liveness Check</h2>
      <p className="text-gray-600 mb-4" aria-live="polite">
        {hasCaptured
          ? 'Liveness photo captured.'
          : 'Position your face clearly in the camera and stay still. Only one photo is needed — no head movement or other action is required.'}
      </p>

      {error && (
        <div
          role="alert"
          className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
        >
          <p className="font-semibold">Capture failed</p>
          <p>{error}</p>
        </div>
      )}

      {hasCaptured ? (
        <div
          role="status"
          className="p-3 rounded border-l-4 border-green-500 bg-green-50 text-sm text-green-700"
        >
          Liveness photo captured.
        </div>
      ) : (
        <button
          type="button"
          onClick={handleRequestCapture}
          disabled={awaitingCapture}
          aria-busy={awaitingCapture}
          aria-label={
            awaitingCapture ? 'Waiting for capture to finish' : 'Take liveness photo'
          }
          className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700"
        >
          {awaitingCapture ? 'Capturing…' : error ? 'Try Again' : 'Take Photo'}
        </button>
      )}
    </div>
  )
}
