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
 *   - Consent is not persisted here. The parent can pass `onBeforeRequest`
 *     to record it; it runs on the click, BEFORE any camera or location
 *     request, and a rejection stops the flow before any data is collected.
 *   - Nothing here touches auth tokens or localStorage directly.
 *
 * All browser APIs (`navigator.mediaDevices`, `lib/geolocation.ts`) are
 * only ever invoked from the click handler below — never at module load,
 * during render, or in an effect — so this component is safe to import
 * during Next.js server-side rendering/build.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { getCurrentLocation } from '@/lib/geolocation'
import { CameraIcon, PinIcon } from '@/components/icons'

type ConsentStatus = 'idle' | 'requesting' | 'error' | 'granted'
type ConsentStep = 'consent' | 'camera' | 'location'

interface ConsentFailure {
  step: ConsentStep
  message: string
}

const FAILURE_TITLES: Record<ConsentStep, string> = {
  consent: 'Consent could not be saved',
  camera: 'Camera access failed',
  location: 'Location access failed',
}

export interface ConsentPromptProps {
  /** Called once the needed permissions (camera, if required, and location) have been granted. */
  onConsentGranted: () => void
  /**
   * Runs when the user clicks "Allow & Continue", before the camera or location
   * is requested — used to record consent first. If it rejects, nothing is
   * requested and the rejection's `message` (which must be safe to display) is
   * shown with a retry.
   */
  onBeforeRequest?: () => Promise<void>
  /**
   * Whether this check-in needs the camera. Defaults to true. When false (the
   * session needs no photo), camera permission is neither explained nor
   * requested — only location — so we don't ask for access we won't use.
   */
  requireCamera?: boolean
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

export default function ConsentPrompt({
  onConsentGranted,
  onBeforeRequest,
  requireCamera = true,
}: ConsentPromptProps) {
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

    if (onBeforeRequest) {
      try {
        await onBeforeRequest()
      } catch (error) {
        if (isMountedRef.current) {
          setFailure({
            step: 'consent',
            message:
              error instanceof Error ? error.message : 'We couldn’t save your consent. Please try again.',
          })
          setStatus('error')
        }
        return
      }
    }

    if (requireCamera) {
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
  }, [onBeforeRequest, onConsentGranted, requireCamera])

  const isRequesting = status === 'requesting'
  const isGranted = status === 'granted'

  return (
    <div className="card">
      <h2 className="mb-1 text-2xl font-bold">
        {requireCamera ? 'Camera & Location Access' : 'Location Access'}
      </h2>
      <p className="mb-5 text-gray-600">
        {requireCamera
          ? 'To check in, SAIV needs permission to use your camera and location for this session.'
          : 'To check in, SAIV needs permission to use your location for this session.'}
      </p>

      <ul className="mb-6 space-y-3 text-sm text-gray-700">
        {requireCamera && (
          <li className="flex items-start gap-3 rounded-2xl bg-gray-50 p-3 ring-1 ring-gray-200">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-100 text-brand-700">
              <CameraIcon />
            </span>
            <span className="pt-0.5">
              <strong>Camera</strong> — used to verify it&rsquo;s really you (face
              verification).
            </span>
          </li>
        )}
        <li className="flex items-start gap-3 rounded-2xl bg-gray-50 p-3 ring-1 ring-gray-200">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-100 text-brand-700">
            <PinIcon />
          </span>
          <span className="pt-0.5">
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
          <p className="font-semibold">{FAILURE_TITLES[failure.step]}</p>
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
        className="btn btn-primary"
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
