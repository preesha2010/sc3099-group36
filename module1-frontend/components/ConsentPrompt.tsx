'use client'

/**
 * ConsentPrompt
 *
 * The consent step shown before the check-in flow's camera/liveness and
 * location steps. Explains why camera and location access are needed,
 * then — only when the user explicitly clicks through — requests both
 * permissions and reports success via `onConsentGranted()`.
 *
 * This milestone is permission-gating only:
 *   - No persistent camera stream is kept — a stream is opened purely to
 *     trigger/confirm the permission prompt, then every track is stopped
 *     immediately.
 *   - No face image is captured, stored, or uploaded here.
 *   - No location coordinates are stored or displayed — `getCurrentLocation()`
 *     (lib/geolocation.ts) is used only to confirm the permission was
 *     granted; its result is discarded.
 *   - Consent is not persisted (no `PUT /users/me` call) — that's an
 *     explicit non-goal for this milestone.
 *   - Nothing here touches auth tokens or localStorage directly.
 *
 * All browser APIs (`navigator.mediaDevices`, `lib/geolocation.ts`) are
 * only ever invoked from the click handler below — never at module load,
 * during render, or in an effect — so this component is safe to import
 * during Next.js server-side rendering/build.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { getCurrentLocation } from '@/lib/geolocation'

type ConsentStatus = 'idle' | 'requesting' | 'error' | 'granted'
type ConsentStep = 'camera' | 'location'

interface ConsentFailure {
  step: ConsentStep
  message: string
}

export interface ConsentPromptProps {
  /** Called once camera and location permissions have both been granted. */
  onConsentGranted: () => void
}

function isCameraSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function'
  )
}

/** Maps a getUserMedia failure to a static, non-sensitive message — never echoes browser/device details. */
function describeCameraError(error: unknown): string {
  if (error instanceof DOMException) {
    switch (error.name) {
      case 'NotAllowedError':
      case 'PermissionDeniedError':
        return 'Camera permission was denied.'
      case 'NotFoundError':
      case 'DevicesNotFoundError':
        return 'No camera was found on this device.'
      case 'NotReadableError':
      case 'TrackStartError':
        return 'The camera is unavailable — it may be in use by another application.'
      case 'OverconstrainedError':
        return 'No camera on this device meets the required constraints.'
      case 'SecurityError':
        return 'Camera access is blocked by this browser’s security settings.'
      default:
        return 'Unable to access the camera.'
    }
  }
  return 'Unable to access the camera.'
}

/**
 * Requests camera permission only — no stream is kept. A stream is
 * briefly opened to trigger the permission prompt, then every track is
 * stopped immediately (in the `finally` block, so this happens whether
 * the request succeeds or fails partway through).
 */
async function requestCameraPermission(): Promise<void> {
  if (!isCameraSupported()) {
    throw new Error('Camera is not supported in this browser.')
  }

  let stream: MediaStream | null = null
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user' },
    })
  } catch (error) {
    throw new Error(describeCameraError(error))
  } finally {
    stream?.getTracks().forEach((track) => track.stop())
  }
}

export default function ConsentPrompt({ onConsentGranted }: ConsentPromptProps) {
  const [status, setStatus] = useState<ConsentStatus>('idle')
  const [failure, setFailure] = useState<ConsentFailure | null>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const handleAllowAndContinue = useCallback(async () => {
    setStatus('requesting')
    setFailure(null)

    try {
      await requestCameraPermission()
    } catch (error) {
      if (isMountedRef.current) {
        setFailure({
          step: 'camera',
          message: error instanceof Error ? error.message : 'Unable to access the camera.',
        })
        setStatus('error')
      }
      return
    }

    try {
      // Result intentionally discarded — this call exists only to
      // confirm location permission; the actual check-in flow will
      // request a fresh fix of its own later.
      await getCurrentLocation()
    } catch (error) {
      if (isMountedRef.current) {
        setFailure({
          step: 'location',
          // GeolocationRequestError messages are already safe, static
          // strings (see lib/geolocation.ts) — never raw browser output.
          message: error instanceof Error ? error.message : 'Unable to access your location.',
        })
        setStatus('error')
      }
      return
    }

    if (isMountedRef.current) {
      setStatus('granted')
    }
    onConsentGranted()
  }, [onConsentGranted])

  const isRequesting = status === 'requesting'
  const isGranted = status === 'granted'

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Camera &amp; Location Access</h2>
      <p className="text-gray-600 mb-4">
        To check in, SAIV needs permission to use your camera and location for this
        session.
      </p>

      <ul className="mb-6 space-y-3 text-sm text-gray-700">
        <li className="flex gap-2">
          <span aria-hidden="true">📷</span>
          <span>
            <strong>Camera</strong> — used to verify it&rsquo;s really you (face
            verification).
          </span>
        </li>
        <li className="flex gap-2">
          <span aria-hidden="true">📍</span>
          <span>
            <strong>Location</strong> — used to confirm you&rsquo;re checking in from
            the venue.
          </span>
        </li>
      </ul>

      {status === 'error' && failure && (
        <div
          role="alert"
          className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
        >
          <p className="font-semibold capitalize">{failure.step} access failed</p>
          <p>{failure.message}</p>
        </div>
      )}

      {isGranted && (
        <div className="mb-4 p-3 rounded border-l-4 border-green-500 bg-green-50 text-sm text-green-700">
          Permissions granted.
        </div>
      )}

      <button
        type="button"
        onClick={handleAllowAndContinue}
        disabled={isRequesting || isGranted}
        className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700"
      >
        {isRequesting
          ? 'Requesting permissions…'
          : status === 'error'
            ? 'Try Again'
            : 'Allow & Continue'}
      </button>

      <p className="mt-3 text-xs text-gray-400">
        You can change these permissions later in your browser settings.
      </p>
    </div>
  )
}
