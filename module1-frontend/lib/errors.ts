/**
 * API error abstraction.
 *
 * All errors that escape lib/api.ts (real client) and lib/mockApi.ts
 * (mock client) are normalized into ApiError so callers never need to
 * branch on axios internals or on real-vs-mock error shapes.
 */

import axios from 'axios'
import type { ValidationErrorItem } from '@/types/api'

export type ApiErrorKind =
  | 'network'
  | 'validation'
  | 'authentication'
  | 'authorization'
  | 'rate_limit'
  | 'account_locked'
  | 'client'
  | 'server'
  | 'unknown'

export interface ApiErrorParams {
  kind: ApiErrorKind
  message: string
  status?: number
  detail?: string | ValidationErrorItem[]
  retryAfterSeconds?: number
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number
  readonly detail?: string | ValidationErrorItem[]
  readonly retryAfterSeconds?: number

  constructor(params: ApiErrorParams) {
    super(params.message)
    this.name = 'ApiError'
    this.kind = params.kind
    this.status = params.status
    this.detail = params.detail
    this.retryAfterSeconds = params.retryAfterSeconds
  }
}

/**
 * Shown wherever a locked account is reported. Static text, never the raw
 * backend message. The account is locked after repeated failed sign-ins and the
 * backend clears the lock only through an administrator.
 */
export const ACCOUNT_LOCKED_MESSAGE =
  'Your account is locked after too many failed sign-in attempts. Please contact an administrator to unlock it.'

/** True for the backend's "Account locked" detail (case and surrounding spaces ignored). */
function isAccountLockedDetail(detail: unknown): boolean {
  return typeof detail === 'string' && detail.trim().toLowerCase() === 'account locked'
}

function detailToMessage(detail: unknown): string | undefined {
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === 'object' && 'msg' in item
          ? String((item as ValidationErrorItem).msg)
          : String(item),
      )
      .join('; ')
  }
  return undefined
}

/**
 * Converts any thrown value (an axios error, an already-normalized
 * ApiError, or something unexpected) into an ApiError. Never throws.
 */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }

  if (axios.isAxiosError(error)) {
    const responseData = error.response?.data as
      | { detail?: string | ValidationErrorItem[] }
      | undefined
    const status = error.response?.status
    const detail = responseData?.detail
    const message = detailToMessage(detail)

    if (!error.response) {
      // Request never got a response: offline, timeout, DNS/CORS failure, etc.
      return new ApiError({
        kind: 'network',
        message: message ?? 'Network error: unable to reach the server.',
        detail,
      })
    }

    if (status === 401) {
      return new ApiError({
        kind: 'authentication',
        message: message ?? 'Authentication required.',
        status,
        detail,
      })
    }

    if (status === 403) {
      return new ApiError({
        kind: 'authorization',
        message: message ?? 'You do not have permission to do this.',
        status,
        detail,
      })
    }

    if (status === 422) {
      return new ApiError({
        kind: 'validation',
        message: message ?? 'Invalid request data.',
        status,
        detail,
      })
    }

    // The backend answers 429 for two different reasons: a temporary rate limit
    // ("Rate limit exceeded") and a locked account ("Account locked"). Retrying
    // never helps the second one (only an administrator can unlock it), so it is
    // kept apart from the first by its `detail` text.
    if (status === 429 && isAccountLockedDetail(detail)) {
      return new ApiError({
        kind: 'account_locked',
        message: message ?? 'Account locked.',
        status,
        detail,
      })
    }

    if (status === 429) {
      const retryAfterHeader = error.response.headers?.['retry-after']
      const retryAfterSeconds = retryAfterHeader
        ? Number(retryAfterHeader)
        : undefined
      return new ApiError({
        kind: 'rate_limit',
        message: message ?? 'Too many requests. Please slow down.',
        status,
        detail,
        retryAfterSeconds: Number.isFinite(retryAfterSeconds)
          ? retryAfterSeconds
          : undefined,
      })
    }

    if (status !== undefined && status >= 400 && status < 500) {
      return new ApiError({
        kind: 'client',
        message: message ?? 'Request failed.',
        status,
        detail,
      })
    }

    if (status !== undefined && status >= 500) {
      return new ApiError({
        kind: 'server',
        message: message ?? 'Server error. Please try again later.',
        status,
        detail,
      })
    }
  }

  return new ApiError({
    kind: 'unknown',
    message: error instanceof Error ? error.message : 'An unexpected error occurred.',
  })
}
