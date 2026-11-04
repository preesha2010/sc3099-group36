/**
 * The check-in window of a session, judged by this device's clock.
 *
 * Informational only: the backend is the authority and refuses check-ins outside
 * the window ("Check-in window closed"). A device with a wrong clock can be
 * mistaken, which is why callers use this to label sessions and to hold back the
 * Start button, never as a security decision. By default the backend opens the
 * window 15 minutes before a session starts and closes it 30 minutes after.
 */

import { parseServerDate } from '@/lib/dates'

export type WindowState = 'open' | 'not-open-yet' | 'closed'

export function checkinWindowState(
  opensAt: string,
  closesAt: string,
  now: number = Date.now(),
): WindowState {
  const opens = parseServerDate(opensAt).getTime()
  const closes = parseServerDate(closesAt).getTime()
  if (!Number.isNaN(closes) && now > closes) return 'closed'
  if (!Number.isNaN(opens) && now < opens) return 'not-open-yet'
  return 'open'
}

/** "3:30 pm" for today, "Tue 3:30 pm" / "12 Oct, 3:30 pm" otherwise (viewer's local time). */
export function formatWindowTime(value: string, now: number = Date.now()): string {
  const date = parseServerDate(value)
  if (Number.isNaN(date.getTime())) return value
  const time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  const today = new Date(now)
  if (date.toDateString() === today.toDateString()) return time
  const dayMs = 24 * 60 * 60 * 1000
  if (Math.abs(date.getTime() - now) < 6 * dayMs) {
    return `${date.toLocaleDateString([], { weekday: 'short' })} ${time}`
  }
  return `${date.toLocaleDateString([], { day: 'numeric', month: 'short' })}, ${time}`
}

export interface WindowPresentation {
  state: WindowState
  /** Short badge text. */
  badge: string
  /** One line for the card. */
  detail: string
  /** Tailwind classes for the badge. */
  badgeClasses: string
}

export function presentWindow(
  opensAt: string,
  closesAt: string,
  now: number = Date.now(),
): WindowPresentation {
  const state = checkinWindowState(opensAt, closesAt, now)
  switch (state) {
    case 'open':
      return {
        state,
        badge: 'Open now',
        detail: `Check-in open until ${formatWindowTime(closesAt, now)}`,
        badgeClasses: 'bg-emerald-100 text-emerald-800',
      }
    case 'not-open-yet':
      return {
        state,
        badge: 'Not open yet',
        detail: `Check-in opens ${formatWindowTime(opensAt, now)}`,
        badgeClasses: 'bg-amber-100 text-amber-800',
      }
    case 'closed':
      return {
        state,
        badge: 'Closed',
        detail: `Check-in closed ${formatWindowTime(closesAt, now)}`,
        badgeClasses: 'bg-gray-200 text-gray-700',
      }
  }
}

function dayLabel(date: Date, now: number): string {
  const today = new Date(now)
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const diffDays = Math.round((startOfDay(date) - startOfDay(today)) / (24 * 60 * 60 * 1000))
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Tomorrow'
  if (diffDays === -1) return 'Yesterday'
  return date.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}

/** "Today, 11:39 AM - 1:39 PM" for a session inside one day, otherwise both ends with their day. */
export function formatSessionRange(start: string, end: string, now: number = Date.now()): string {
  const from = parseServerDate(start)
  const to = parseServerDate(end)
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return `${start} – ${end}`
  const time = (d: Date) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (from.toDateString() === to.toDateString()) {
    return `${dayLabel(from, now)}, ${time(from)} – ${time(to)}`
  }
  return `${dayLabel(from, now)}, ${time(from)} – ${dayLabel(to, now)}, ${time(to)}`
}
