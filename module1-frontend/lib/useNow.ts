'use client'

import { useEffect, useState } from 'react'

/**
 * The current time, refreshed every `intervalMs` (default 30 s) so labels such as
 * "Open now" / "Closed" follow the clock while a screen stays open. The first
 * render uses the time of mounting, so server-rendered markup never depends on it
 * (the screens that use this only render after sign-in, client-side).
 */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])

  return now
}
