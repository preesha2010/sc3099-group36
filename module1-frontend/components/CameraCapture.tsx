'use client'

/**
 * CameraCapture
 *
 * A standalone camera-capture primitive: start the camera on explicit
 * user action, show a live preview, capture exactly one frame on
 * demand, and hand it to the parent via `onCapture`. Nothing more.
 *
 * Deliberately does NOT know about:
 *   - the check-in flow, authentication, or consent state,
 *   - liveness detection or face recognition,
 *   - uploading or persisting the captured image — that's entirely the
 *     caller's responsibility once `onCapture` fires.
 *
 * The captured frame is never stored by this component beyond the
 * in-memory preview shown after capture, never logged, and the
 * MediaStream is stopped as soon as it's no longer needed: right after
 * capture, on retake (before requesting a fresh stream), and on
 * unmount. `navigator.mediaDevices.getUserMedia` is only ever called
 * from the "Start Camera" click handler (and its retake equivalent) —
 * never at module load or during render — so this component is safe to
 * import during Next.js server-side rendering/build.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

type CaptureStatus = 'idle' | 'starting' | 'active' | 'captured' | 'error'

export interface CameraCaptureProps {
  /** Called once with a single captured frame as a data URL when the user taps Capture. */
  onCapture: (imageData: string) => void
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
      case 'AbortError':
        return 'Camera access was interrupted. Please try again.'
      default:
        return 'Unable to access the camera.'
    }
  }
  return 'An unexpected camera error occurred.'
}

export default function CameraCapture({ onCapture }: CameraCaptureProps) {
  const [status, setStatus] = useState<CaptureStatus>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [capturedImage, setCapturedImage] = useState<string | null>(null)
  const [isVideoReady, setIsVideoReady] = useState(false)

  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const isMountedRef = useRef(true)

  const stopActiveStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setIsVideoReady(false)
  }, [])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      stopActiveStream()
    }
  }, [stopActiveStream])

  const handleStartCamera = useCallback(async () => {
    if (!isCameraSupported()) {
      setStatus('error')
      setErrorMessage('Camera is not supported in this browser.')
      return
    }

    setStatus('starting')
    setErrorMessage(null)

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user' },
        audio: false,
      })
    } catch (error) {
      if (isMountedRef.current) {
        setStatus('error')
        setErrorMessage(describeCameraError(error))
      }
      return
    }

    if (!isMountedRef.current) {
      // Component unmounted while the permission prompt was pending —
      // don't leave the camera running for a component that's gone.
      stream.getTracks().forEach((track) => track.stop())
      return
    }

    streamRef.current = stream
    if (videoRef.current) {
      videoRef.current.srcObject = stream
    }
    setStatus('active')
  }, [])

  const handleVideoLoadedMetadata = useCallback(() => {
    setIsVideoReady(true)
  }, [])

  const handleCapture = useCallback(() => {
    const video = videoRef.current
    if (status !== 'active' || !video || !isVideoReady) {
      return
    }

    if (video.videoWidth === 0 || video.videoHeight === 0) {
      stopActiveStream()
      setStatus('error')
      setErrorMessage('Camera preview is not ready yet. Please try again.')
      return
    }

    try {
      // Offscreen canvas: never inserted into the DOM, sized to the
      // video's natural resolution — no cropping/scaling/filtering.
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight

      const context = canvas.getContext('2d')
      if (!context) {
        throw new Error('Canvas is not supported.')
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height)

      // JPEG data URL: matches the "base64 PNG/JPEG" image format the
      // backend documents, and stays reasonably small for a webcam frame.
      const dataUrl = canvas.toDataURL('image/jpeg', 0.92)

      stopActiveStream()
      setCapturedImage(dataUrl)
      setStatus('captured')
      onCapture(dataUrl)
    } catch {
      stopActiveStream()
      setStatus('error')
      setErrorMessage('Unable to capture the image. Please try again.')
    }
  }, [status, isVideoReady, stopActiveStream, onCapture])

  const handleRetake = useCallback(() => {
    setCapturedImage(null)
    void handleStartCamera()
  }, [handleStartCamera])

  const showVideo = status === 'starting' || status === 'active'

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Camera Capture</h2>
      <p className="text-gray-600 mb-4">
        Start your camera, then capture a photo when you&rsquo;re ready.
      </p>

      {status === 'error' && errorMessage && (
        <div
          role="alert"
          className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
        >
          <p className="font-semibold">Camera error</p>
          <p>{errorMessage}</p>
        </div>
      )}

      {/* Always mounted (not conditionally rendered) so the ref is
          available before the async getUserMedia call resolves; hidden
          via class when there's no live stream to show. */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        onLoadedMetadata={handleVideoLoadedMetadata}
        aria-label="Live camera preview"
        className={showVideo ? 'w-full rounded mb-4 bg-black' : 'hidden'}
      />

      {status === 'captured' && capturedImage && (
        <img
          src={capturedImage}
          alt="Captured preview"
          className="w-full rounded mb-4"
        />
      )}

      <div className="flex gap-3">
        {(status === 'idle' || status === 'error') && (
          <button
            type="button"
            onClick={handleStartCamera}
            aria-label="Start camera"
            className="flex-1 py-2 px-4 rounded bg-blue-600 text-white font-medium hover:bg-blue-700"
          >
            Start Camera
          </button>
        )}

        {status === 'starting' && (
          <button
            type="button"
            disabled
            aria-busy="true"
            aria-label="Starting camera"
            className="flex-1 py-2 px-4 rounded bg-blue-600 text-white font-medium opacity-50 cursor-not-allowed"
          >
            Starting camera…
          </button>
        )}

        {status === 'active' && (
          <button
            type="button"
            onClick={handleCapture}
            disabled={!isVideoReady}
            aria-label="Capture photo"
            className="flex-1 py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700"
          >
            {isVideoReady ? 'Capture' : 'Preparing…'}
          </button>
        )}

        {status === 'captured' && (
          <button
            type="button"
            onClick={handleRetake}
            aria-label="Retake photo"
            className="flex-1 py-2 px-4 rounded bg-gray-200 text-gray-800 font-medium hover:bg-gray-300"
          >
            Retake
          </button>
        )}
      </div>
    </div>
  )
}
