'use client'

/**
 * CheckInResult
 *
 * Shows the outcome of a check-in, derived ONLY from what the server
 * returned. A `201 Created` does not mean "approved": per the API spec the
 * response `status` can be `approved`, `pending`, `flagged` or `rejected`
 * (a failed liveness check or a location far outside the geofence is
 * reported as `rejected` in a normal response), so the headline and colour
 * follow `status`, never the HTTP success alone.
 *
 * Also handles the case where the student turned out to already be checked
 * in (found via their own check-in history), which is reported from that
 * history's `status`.
 *
 * Presentational only: no requests, no storage. Risk-factor `type` values are
 * rendered as plain text (React-escaped) with friendly labels for the types
 * documented in DATABASE-SCHEMA.md.
 */

import type { CheckinCreateResponse, CheckinStatus, CheckinSummary } from '@/types/api'

export type CheckInOutcome =
  | { kind: 'submitted'; checkin: CheckinCreateResponse }
  | { kind: 'already'; checkin: CheckinSummary }

export interface CheckInResultProps {
  outcome: CheckInOutcome
  onDone: () => void
}

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

function describeRiskFactor(type: string): string {
  const known = RISK_FACTOR_LABELS[type]
  if (known) return known
  const spaced = type.replace(/_/g, ' ').trim()
  return spaced.length > 0 ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : 'Unspecified factor'
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

interface StatusPresentation {
  headline: string
  detail: string
  boxClasses: string
}

function presentStatus(status: CheckinStatus | string): StatusPresentation {
  switch (status) {
    case 'approved':
      return {
        headline: 'You’re checked in',
        detail: 'Your attendance has been recorded.',
        boxClasses: 'border-green-500 bg-green-50 text-green-800',
      }
    case 'pending':
      return {
        headline: 'Check-in received',
        detail: 'Your check-in is pending verification.',
        boxClasses: 'border-blue-500 bg-blue-50 text-blue-800',
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
        boxClasses: 'border-blue-500 bg-blue-50 text-blue-800',
      }
    default:
      return {
        headline: 'Check-in recorded',
        detail: `Current status: ${status}.`,
        boxClasses: 'border-gray-400 bg-gray-50 text-gray-800',
      }
  }
}

export default function CheckInResult({ outcome, onDone }: CheckInResultProps) {
  const { checkin } = outcome
  const presentation = presentStatus(checkin.status)
  const submitted = outcome.kind === 'submitted' ? outcome.checkin : null

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      {outcome.kind === 'already' && (
        <p className="text-sm text-gray-600 mb-3">
          You’ve already checked in to this session.
        </p>
      )}

      <div
        role="status"
        className={`mb-4 p-4 rounded border-l-4 ${presentation.boxClasses}`}
      >
        <h2 className="text-xl font-bold mb-1">{presentation.headline}</h2>
        <p className="text-sm">{presentation.detail}</p>
      </div>

      <dl className="mb-4 space-y-1 text-sm text-gray-700">
        <div className="flex justify-between gap-4">
          <dt className="text-gray-500">Checked in at</dt>
          <dd>{formatDateTime(checkin.checked_in_at)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-gray-500">Risk score</dt>
          <dd>{checkin.risk_score.toFixed(2)}</dd>
        </div>
        {submitted && (
          <div className="flex justify-between gap-4">
            <dt className="text-gray-500">Distance from venue</dt>
            <dd>{Math.round(submitted.distance_from_venue_meters)} m</dd>
          </div>
        )}
        {submitted && submitted.liveness_passed !== null && (
          <div className="flex justify-between gap-4">
            <dt className="text-gray-500">Live photo check</dt>
            <dd>{submitted.liveness_passed ? 'Passed' : 'Did not pass'}</dd>
          </div>
        )}
      </dl>

      {submitted && submitted.risk_factors.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-1">Contributing factors</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 space-y-1">
            {submitted.risk_factors.map((factor, index) => (
              <li key={`${factor.type}-${index}`}>{describeRiskFactor(factor.type)}</li>
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        onClick={onDone}
        className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
      >
        Done
      </button>
    </div>
  )
}
