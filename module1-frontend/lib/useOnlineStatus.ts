'use client'

import { useSyncExternalStore } from 'react'

/**
 * Whether the browser currently believes it is online.
 *
 * `navigator.onLine` is only a hint: `false` reliably means "no network", but
 * `true` can still mean a connection with no internet behind it. So this is
 * used to explain and pre-empt failures (e.g. disable a button that needs the
 * network), never as proof the server is reachable — real request failures are
 * still handled where the request is made.
 *
 * The server snapshot is `true`, so the first server-rendered and hydrating
 * render always agree; the real value is applied right after hydration.
 */
function subscribe(onChange: () => void): () => void {
  window.addEventListener('online', onChange)
  window.addEventListener('offline', onChange)
  return () => {
    window.removeEventListener('online', onChange)
    window.removeEventListener('offline', onChange)
  }
}

const getSnapshot = (): boolean => navigator.onLine
const getServerSnapshot = (): boolean => true

export function useOnlineStatus(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
