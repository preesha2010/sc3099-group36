'use client'

/**
 * OfflineBanner
 *
 * Shown at the top of the app while the browser reports no network. The app
 * itself keeps loading offline (service worker), but anything that talks to
 * the server — signing in, loading sessions, checking in — needs a connection,
 * and nothing is queued for later. Presentational: no requests, no storage.
 */

import { useOnlineStatus } from '@/lib/useOnlineStatus'

export default function OfflineBanner() {
  const isOnline = useOnlineStatus()
  if (isOnline) return null

  return (
    <div
      role="status"
      className="max-w-md mx-auto mb-4 p-3 rounded border-l-4 border-amber-500 bg-amber-50 text-sm text-amber-800"
    >
      <p className="font-semibold">You’re offline</p>
      <p>
        Checking in needs an internet connection. Nothing is saved for later, so
        reconnect before you submit.
      </p>
    </div>
  )
}
