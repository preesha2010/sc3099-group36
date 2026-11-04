/**
 * Shared wording for check-in outcomes, used by the result screen and the
 * history screen so a status or risk factor reads the same everywhere.
 *
 * Everything here is derived from what the server returned: a status or factor
 * type is never invented, and unknown values fall back to readable text.
 */

import type { CheckinStatus } from '@/types/api'

/** Friendly labels for the risk-factor types documented in DATABASE-SCHEMA.md. */
const RISK_FACTOR_LABELS: Record<string, string> = {
  geo_out_of_bounds: 'Your location was outside the venue area',
  impossible_travel: 'Your location changed implausibly fast',
  geo_accuracy_low: 'Your location accuracy was low',
  vpn_detected: 'A VPN or proxy was detected',
  proxy_detected: 'A proxy was detected',
  tor_detected: 'Tor network use was detected',
  suspicious_ip: 'Your network address looked suspicious',
  device_unknown: 'This device is not recognised',
  device_emulator: 'This device looks like an emulator',
  device_rooted: 'This device appears to be rooted or jailbroken',
  attestation_failed: 'Device attestation failed',
  rapid_succession: 'Check-ins were attempted in rapid succession',
  unusual_time: 'The check-in time was unusual',
  pattern_anomaly: 'An unusual pattern was detected',
  liveness_failed: 'The live photo check did not pass',
  liveness_low_confidence: 'The live photo check had low confidence',
  deepfake_suspected: 'The photo looked artificially generated',
  replay_suspected: 'The photo looked like a replay',
  face_match_failed: 'Your face did not match the enrolled face',
  face_match_low_confidence: 'The face match had low confidence',
}

export function describeRiskFactor(type: string): string {
  const known = RISK_FACTOR_LABELS[type]
  if (known) return known
  const spaced = type.replace(/_/g, ' ').trim()
  return spaced.length > 0 ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : 'Unspecified factor'
}

export interface StatusPresentation {
  headline: string
  detail: string
  boxClasses: string
}

/**
 * Whether the server reported a face-match problem for a check-in, judged only
 * from the documented risk-factor types. This never changes the check-in's
 * status; it only lets the screen avoid implying that the face was verified.
 */
export function faceMatchConcern(
  riskFactors: ReadonlyArray<{ type: string }> | undefined,
): 'failed' | 'low_confidence' | null {
  if (!riskFactors) return null
  if (riskFactors.some((factor) => factor.type === 'face_match_failed')) return 'failed'
  if (riskFactors.some((factor) => factor.type === 'face_match_low_confidence')) {
    return 'low_confidence'
  }
  return null
}

export function presentStatus(
  status: CheckinStatus | string,
  riskFactors?: ReadonlyArray<{ type: string }>,
): StatusPresentation {
  switch (status) {
    case 'approved': {
      const concern = faceMatchConcern(riskFactors)
      if (concern === 'failed') {
        return {
          headline: 'Checked in, but your face wasn’t confirmed',
          detail:
            'Your attendance was recorded, but the photo you took did not match the face enrolled on your account. If this is a mistake, you can enroll your face again from the sessions screen.',
          boxClasses: 'border-amber-500 bg-amber-50 text-amber-800',
        }
      }
      if (concern === 'low_confidence') {
        return {
          headline: 'Checked in, but your face wasn’t fully confirmed',
          detail:
            'Your attendance was recorded, but the face match had low confidence. You can enroll your face again from the sessions screen.',
          boxClasses: 'border-amber-500 bg-amber-50 text-amber-800',
        }
      }
      return {
        headline: 'You’re checked in',
        detail: 'Your attendance has been recorded.',
        boxClasses: 'border-green-500 bg-green-50 text-green-800',
      }
    }
    case 'pending':
      return {
        headline: 'Check-in received',
        detail: 'Your check-in is pending verification.',
        boxClasses: 'border-brand-500 bg-brand-50 text-brand-800',
      }
    case 'flagged':
      return {
        headline: 'Check-in flagged for review',
        detail:
          'Your check-in was recorded but needs to be reviewed by your instructor before it is confirmed.',
        boxClasses: 'border-amber-500 bg-amber-50 text-amber-800',
      }
    case 'rejected':
      return {
        headline: 'Check-in rejected',
        detail: 'Your check-in was not accepted.',
        boxClasses: 'border-red-500 bg-red-50 text-red-800',
      }
    case 'appealed':
      return {
        headline: 'Check-in under appeal',
        detail: 'Your appeal is waiting for review.',
        boxClasses: 'border-brand-500 bg-brand-50 text-brand-800',
      }
    default:
      return {
        headline: 'Check-in recorded',
        detail: `Current status: ${status}.`,
        boxClasses: 'border-gray-400 bg-gray-50 text-gray-800',
      }
  }
}

/** Short label for a status, for compact lists. */
export function statusLabel(status: CheckinStatus | string): string {
  switch (status) {
    case 'approved':
      return 'Approved'
    case 'pending':
      return 'Pending'
    case 'flagged':
      return 'Flagged'
    case 'rejected':
      return 'Rejected'
    case 'appealed':
      return 'Appealed'
    default:
      return status.charAt(0).toUpperCase() + status.slice(1)
  }
}

/** Colour classes for a compact status badge. */
export function statusBadgeClasses(status: CheckinStatus | string): string {
  switch (status) {
    case 'approved':
      return 'bg-green-100 text-green-800'
    case 'flagged':
      return 'bg-amber-100 text-amber-800'
    case 'rejected':
      return 'bg-red-100 text-red-800'
    case 'pending':
    case 'appealed':
      return 'bg-brand-100 text-brand-800'
    default:
      return 'bg-gray-100 text-gray-800'
  }
}
