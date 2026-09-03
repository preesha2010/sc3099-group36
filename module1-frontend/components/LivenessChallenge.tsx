'use client'

/**
 * LivenessChallenge
 *
 * Guides the user through a fixed sequence of simple prompts (look
 * straight, turn left, turn right) and collects one capture per prompt
 * for later backend verification. This component does NOT verify
 * liveness itself — no computer vision, no head-pose estimation, no
 * timers or randomness intended to prove anything. It only manages the
 * challenge/progress UI and tells the parent when to capture.
 *
 * Camera access stays entirely with CameraCapture: this component never
 * calls getUserMedia and never touches a MediaStream. It's a controlled
 * component — `captures` and `currentChallengeIndex` are owned and
 * advanced by the parent (presumably by wiring CameraCapture's
 * `onCapture` to append to `captures` and advance the index once
 * `onRequestCapture` fires here).
 *
 * Captures exist only as props passed straight through to `onComplete`
 * once collection is done — this component never uploads, persists,
 * logs, or otherwise touches localStorage/the network with them; it
 * also has no dependency on auth, tokens, geolocation, or check-in
 * submission. It has no browser-only API usage at all, so it's
 * inherently SSR-safe.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

const CHALLENGES: readonly string[] = [
  'Look straight at the camera',
  'Turn your head slightly to the left',
  'Turn your head slightly to the right',
]

const TOTAL_CHALLENGES = CHALLENGES.length

export interface LivenessChallengeProps {
  /** Captures collected so far (one data URL per completed challenge, in order). Owned by the parent. */
  captures: string[]
  /** Index (0-based) of the challenge currently being attempted. Owned by the parent. */
  currentChallengeIndex: number
  /**
   * Called when the user explicitly requests a capture for the current
   * challenge. This component does not capture anything itself — the
   * parent is expected to trigger CameraCapture and, on success, append
   * to `captures` and advance `currentChallengeIndex`.
   */
  onRequestCapture: () => void
  /**
   * Called exactly once, with all collected captures, once every
   * challenge has a capture. This only signals that data collection is
   * complete — no verification is performed here, and nothing is sent
   * to any API.
   */
  onComplete: (captures: string[]) => void
  /**
   * Optional, already-sanitized error message from the parent (e.g. a
   * failed capture attempt) to display. This component never generates
   * or logs error detail itself.
   */
  error?: string | null
}

function clampChallengeIndex(index: number): number {
  if (!Number.isFinite(index)) return 0
  if (index < 0) return 0
  if (index > TOTAL_CHALLENGES - 1) return TOTAL_CHALLENGES - 1
  return index
}

export default function LivenessChallenge({
  captures,
  currentChallengeIndex,
  onRequestCapture,
  onComplete,
  error = null,
}: LivenessChallengeProps) {
  const safeCaptures = Array.isArray(captures) ? captures : []
  const safeIndex = clampChallengeIndex(currentChallengeIndex)
  const isComplete = safeCaptures.length >= TOTAL_CHALLENGES
  const currentChallengeText = CHALLENGES[safeIndex] ?? ''

  const [awaitingCapture, setAwaitingCapture] = useState(false)
  const hasCompletedRef = useRef(false)

  // Whenever the parent moves the flow forward (progress or capture
  // count changed) or reports a new/cleared error, this challenge's
  // "waiting for a capture" latch is stale — clear it so the button
  // becomes clickable again.
  useEffect(() => {
    setAwaitingCapture(false)
  }, [currentChallengeIndex, safeCaptures.length, error])

  // Fires onComplete exactly once when enough captures have arrived.
  useEffect(() => {
    if (safeCaptures.length >= TOTAL_CHALLENGES) {
      if (!hasCompletedRef.current) {
        hasCompletedRef.current = true
        onComplete(safeCaptures)
      }
    } else {
      hasCompletedRef.current = false
    }
  }, [safeCaptures, onComplete])

  const handleCaptureClick = useCallback(() => {
    // Guards against accidental double-clicks: once a request is in
    // flight, further clicks are ignored until the parent's response
    // changes progress/captures/error (see the effect above).
    if (awaitingCapture || isComplete) {
      return
    }
    setAwaitingCapture(true)
    onRequestCapture()
  }, [awaitingCapture, isComplete, onRequestCapture])

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Liveness Check</h2>
      <p className="text-gray-600 mb-4">
        Follow each prompt below and capture a photo for it. These photos will be used
        to verify your check-in.
      </p>

      <p className="text-sm text-gray-500 mb-2" aria-live="polite">
        {isComplete
          ? `All ${TOTAL_CHALLENGES} challenges complete`
          : `Challenge ${safeIndex + 1} of ${TOTAL_CHALLENGES}`}
      </p>

      {!isComplete && (
        <div className="mb-4 p-4 rounded border border-gray-200 bg-gray-50">
          <p className="text-lg font-semibold" aria-live="polite">
            {currentChallengeText}
          </p>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
        >
          <p className="font-semibold">Capture failed</p>
          <p>{error}</p>
        </div>
      )}

      {isComplete ? (
        <div
          role="status"
          className="p-3 rounded border-l-4 border-green-500 bg-green-50 text-sm text-green-700"
        >
          All challenges complete. Continuing…
        </div>
      ) : (
        <button
          type="button"
          onClick={handleCaptureClick}
          disabled={awaitingCapture}
          aria-busy={awaitingCapture}
          aria-label={
            awaitingCapture
              ? 'Waiting for capture to finish'
              : `Capture photo for challenge ${safeIndex + 1} of ${TOTAL_CHALLENGES}`
          }
          className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700"
        >
          {awaitingCapture ? 'Capturing…' : error ? 'Try Again' : 'Capture'}
        </button>
      )}
    </div>
  )
}
