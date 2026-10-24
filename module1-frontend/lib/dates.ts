/**
 * Server timestamps.
 *
 * The backend sends timestamps as UTC but WITHOUT a time-zone marker
 * (e.g. "2026-10-22T10:08:35.163000"). `new Date()` reads such a string as the
 * viewer's LOCAL time, which would shift every displayed time by their UTC
 * offset (8 hours in Singapore). Strings that already carry a zone ("…Z" or
 * "+08:00"), such as the mock API's, are left as they are.
 */

const HAS_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i
const HAS_TIME = /T\d{2}:\d{2}/

export function parseServerDate(value: string): Date {
  const trimmed = value.trim()
  const normalised = HAS_TIME.test(trimmed) && !HAS_ZONE.test(trimmed) ? `${trimmed}Z` : trimmed
  return new Date(normalised)
}

/** Formats a server timestamp in the viewer's local time; falls back to the raw text if unparsable. */
export function formatServerDateTime(value: string): string {
  const date = parseServerDate(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
