'use client'

/**
 * CheckInFlow
 *
 * The consent -> camera -> liveness -> complete prototype that
 * previously lived directly in app/page.tsx. Relocated here, UNCHANGED,
 * as part of Milestone 3A (Login + Registration UI) so it can be
 * preserved rather than deleted while app/page.tsx becomes a minimal
 * auth gate. Not currently rendered anywhere — a future milestone will
 * render this behind the authenticated placeholder, once session
 * selection exists to feed it a real session to check into.
 *
 * Composes the three existing step components:
 *
 *   ConsentPrompt -> CameraCapture -> LivenessChallenge -> complete
 *
 * This component ONLY orchestrates state between the existing
 * components. It does not call the backend, does not touch auth/tokens,
 * does not perform any verification, and does not persist anything.
 * Every captured image lives in React state only, for the lifetime of
 * this component, and is discarded on unmount/restart.
 *
 * The liveness step captures exactly ONE photo (matching the documented
 * backend contract — see LivenessChallenge's own doc comment): this
 * component only mounts CameraCapture for that step once a capture has
 * been explicitly requested via LivenessChallenge's `onRequestCapture`,
 * and hides it again immediately once `onCapture` fires. CameraCapture
 * already stops its own MediaStream before calling `onCapture`, and
 * stops it again on unmount, so this never leaves a camera running.
 */

import { useCallback, useState } from 'react'
import ConsentPrompt from '@/components/ConsentPrompt'
import CameraCapture from '@/components/CameraCapture'
import LivenessChallenge from '@/components/LivenessChallenge'

type FlowStep = 'consent' | 'camera' | 'liveness' | 'complete'

const STEP_ORDER: FlowStep[] = ['consent', 'camera', 'liveness']
const STEP_LABELS: Record<FlowStep, string> = {
  consent: 'Consent',
  camera: 'Camera',
  liveness: 'Liveness Check',
  complete: 'Complete',
}

export default function CheckInFlow() {
  const [step, setStep] = useState<FlowStep>('consent')

  // Step 2's single photo.
  const [capturedImage, setCapturedImage] = useState<string | null>(null)

  // Step 3's single liveness photo. Kept separate from capturedImage —
  // the two steps collect distinct images.
  const [livenessImage, setLivenessImage] = useState<string | null>(null)
  const [isLivenessCaptureRequested, setIsLivenessCaptureRequested] = useState(false)

  const handleConsentGranted = useCallback(() => {
    setStep('camera')
  }, [])

  const handleCameraCapture = useCallback((imageData: string) => {
    setCapturedImage(imageData)
    setStep('liveness')
  }, [])

  const handleLivenessRequestCapture = useCallback(() => {
    setIsLivenessCaptureRequested(true)
  }, [])

  const handleLivenessCameraCapture = useCallback((imageData: string) => {
    setLivenessImage(imageData)
    setIsLivenessCaptureRequested(false)
    setStep('complete')
  }, [])

  const handleRestart = useCallback(() => {
    setStep('consent')
    setCapturedImage(null)
    setLivenessImage(null)
    setIsLivenessCaptureRequested(false)
  }, [])

  const stepNumber = STEP_ORDER.indexOf(step) + 1

  return (
    <div>
      <p className="text-center text-sm font-medium text-gray-500 mb-8">
        {step === 'complete'
          ? 'All steps complete'
          : `Step ${stepNumber} of ${STEP_ORDER.length}: ${STEP_LABELS[step]}`}
      </p>

      {step === 'consent' && <ConsentPrompt onConsentGranted={handleConsentGranted} />}

      {step === 'camera' && <CameraCapture onCapture={handleCameraCapture} />}

      {step === 'liveness' && (
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

      {step === 'complete' && (
        <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow text-center">
          {capturedImage && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={capturedImage}
              alt="Captured verification photo"
              className="w-24 h-24 object-cover rounded-full mx-auto mb-4"
            />
          )}
          <h2 className="text-2xl font-bold mb-2">Ready</h2>
          <p className="text-gray-600 mb-1">Camera photo and liveness photo captured.</p>
          <p className="text-gray-500 text-sm mb-6">
            These images are held in memory for this session only and haven&rsquo;t
            been sent anywhere.
          </p>
          <button
            type="button"
            onClick={handleRestart}
            className="py-2 px-4 rounded bg-blue-600 text-white font-medium hover:bg-blue-700"
          >
            Start Over
          </button>
        </div>
      )}
    </div>
  )
}
