/**
 * Geolocation.
 *
 * A thin, explicit-call-only wrapper around the browser's standard
 * `navigator.geolocation` API, used to obtain the coordinates the
 * check-in flow needs for `POST /checkins/`'s `latitude` / `longitude` /
 * `location_accuracy_meters` fields (docs/API-SPECIFICATION.md).
 *
 * Deliberately does NOT:
 *   - Request location on import or module load — only when a caller
 *     explicitly calls `getCurrentLocation()`.
 *   - Continuously track the user (`watchPosition`) — `getCurrentPosition`
 *     only, a single one-shot read per call.
 *   - Persist any location data — that's the caller's concern, if any
 *     (e.g. a future offline-queue milestone), not this module's.
 *   - Log latitude/longitude/accuracy or raw browser error details.
 */

const DEFAULT_TIMEOUT_MS = 10_000

export type GeolocationErrorKind =
  | 'unsupported'
  | 'permission_denied'
  | 'position_unavailable'
  | 'timeout'
  | 'unknown'

export class GeolocationRequestError extends Error {
  readonly kind: GeolocationErrorKind

  constructor(kind: GeolocationErrorKind, message: string) {
    super(message)
    this.name = 'GeolocationRequestError'
    this.kind = kind
  }
}

export interface DeviceLocation {
  latitude: number
  longitude: number
  accuracyMeters: number
  /** Epoch milliseconds the browser captured this fix at (`GeolocationPosition.timestamp`). */
  timestamp: number
}

export interface GetCurrentLocationOptions {
  /** Milliseconds to wait before giving up. Defaults to 10s — never waits indefinitely. */
  timeoutMs?: number
}

/**
 * Feature-detects the Geolocation API. SSR-safe: `navigator` doesn't
 * exist (or doesn't expose `geolocation`) outside a real browser, so
 * this returns `false` during Next.js server rendering/build without
 * touching any browser-only API.
 */
export function isGeolocationSupported(): boolean {
  return typeof navigator !== 'undefined' && 'geolocation' in navigator
}

function mapPositionError(error: GeolocationPositionError): GeolocationRequestError {
  switch (error.code) {
    case error.PERMISSION_DENIED:
      return new GeolocationRequestError(
        'permission_denied',
        'Location permission was denied.',
      )
    case error.POSITION_UNAVAILABLE:
      return new GeolocationRequestError(
        'position_unavailable',
        'Location is currently unavailable.',
      )
    case error.TIMEOUT:
      return new GeolocationRequestError(
        'timeout',
        'Timed out while requesting location.',
      )
    default:
      // Intentionally not including `error.message` here — see the
      // module-level note on never logging/propagating raw browser
      // location error details.
      return new GeolocationRequestError(
        'unknown',
        'An unknown error occurred while requesting location.',
      )
  }
}

/**
 * Requests the user's current location once (`getCurrentPosition`, not
 * `watchPosition`). Only called when a caller explicitly invokes this —
 * never automatically. Rejects with a `GeolocationRequestError` if the
 * browser doesn't support geolocation, the user denies permission, the
 * position is unavailable, or the request times out.
 */
export function getCurrentLocation(
  options: GetCurrentLocationOptions = {},
): Promise<DeviceLocation> {
  if (!isGeolocationSupported()) {
    return Promise.reject(
      new GeolocationRequestError(
        'unsupported',
        'Geolocation is not supported in this browser.',
      ),
    )
  }

  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS

  return new Promise<DeviceLocation>((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracyMeters: position.coords.accuracy,
          timestamp: position.timestamp,
        })
      },
      (error) => {
        reject(mapPositionError(error))
      },
      {
        enableHighAccuracy: true,
        timeout: timeoutMs,
        maximumAge: 0,
      },
    )
  })
}
