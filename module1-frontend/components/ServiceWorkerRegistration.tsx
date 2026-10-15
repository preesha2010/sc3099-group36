'use client'

/**
 * ServiceWorkerRegistration
 *
 * Registers /sw.js (the app-shell service worker — see public/sw.js for exactly
 * what it caches and what it never touches). Renders nothing.
 *
 * Production builds only. In development a service worker would cache dev
 * chunks and fight hot reloading, so there it does the opposite: it removes any
 * SAIV worker a previous production run left registered on this origin.
 *
 * Service workers need a secure context (HTTPS or localhost); elsewhere
 * `navigator.serviceWorker` is undefined and the app simply runs without one.
 */

import { useEffect } from 'react'

const SW_PATH = '/sw.js'

export default function ServiceWorkerRegistration() {
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return

    if (process.env.NODE_ENV !== 'production') {
      void navigator.serviceWorker
        .getRegistrations()
        .then((registrations) =>
          Promise.all(
            registrations
              .filter((registration) =>
                registration.active?.scriptURL.endsWith(SW_PATH),
              )
              .map((registration) => registration.unregister()),
          ),
        )
        .catch(() => undefined)
      return
    }

    navigator.serviceWorker.register(SW_PATH, { scope: '/' }).catch(() => {
      // The app works without it; there's nothing useful to tell the user.
    })
  }, [])

  return null
}
