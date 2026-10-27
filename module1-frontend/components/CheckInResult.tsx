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

import { formatServerDateTime } from '@/lib/dates'
import { describeRiskFactor, presentStatus } from '@/lib/checkinPresentation'
import type { CheckinCreateResponse, CheckinSummary } from '@/types/api'

export type CheckInOutcome =
  | { kind: 'submitted'; checkin: CheckinCreateResponse }
  | { kind: 'already'; checkin: CheckinSummary }

export interface CheckInResultProps {
  outcome: CheckInOutcome
  onDone: () => void
}

const formatDateTime = formatServerDateTime

export default function CheckInResult({ outcome, onDone }: CheckInResultProps) {
  const { checkin } = outcome
  const submitted = outcome.kind === 'submitted' ? outcome.checkin : null
  const presentation = presentStatus(checkin.status, submitted?.risk_factors)

  return (
    <div className="card">
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
        className="btn btn-primary"
      >
        Done
      </button>
    </div>
  )
}
