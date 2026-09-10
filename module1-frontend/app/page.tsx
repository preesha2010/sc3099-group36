'use client'

/**
 * SAIV Student Frontend — auth gate (Milestone 3A)
 *
 * Minimal authenticated/unauthenticated shell:
 *
 *   unauthenticated -> LoginForm <-> RegisterForm
 *   authenticated    -> simple placeholder (Logout only)
 *
 * Auth status is read through lib/auth.ts's `isAuthenticated()` — never
 * localStorage directly — and only inside a `useEffect`, so the very
 * first render (both server-rendered and the client's first hydration
 * pass) always shows the same neutral 'loading' state. The real,
 * localStorage-derived status is only known after mount, client-side,
 * which avoids a hydration mismatch between server and client output.
 *
 * Login/registration themselves are fully handled by LoginForm/
 * RegisterForm, which call the existing `api.login()`/`api.register()`
 * — token persistence happens entirely inside those calls (via
 * lib/auth.ts). This page only reacts to their success callbacks to
 * flip its own status state; it never touches tokens directly.
 *
 * The previous consent -> camera -> liveness -> complete prototype that
 * used to live here has been relocated, unchanged, to
 * components/CheckInFlow.tsx — preserved for a future milestone to wire
 * back in behind the authenticated placeholder below, once session
 * selection exists to feed it a real session.
 */

import { useCallback, useEffect, useState } from 'react'
import * as auth from '@/lib/auth'
import * as api from '@/lib/api'
import LoginForm from '@/components/LoginForm'
import RegisterForm from '@/components/RegisterForm'

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'
type AuthView = 'login' | 'register'

export default function Home() {
  const [authStatus, setAuthStatus] = useState<AuthStatus>('loading')
  const [authView, setAuthView] = useState<AuthView>('login')
  const [registerNotice, setRegisterNotice] = useState<string | null>(null)

  // Client-only: reads through auth.ts, never localStorage directly.
  // Runs after the first render/hydration, so the initial paint is
  // always the neutral 'loading' state on both server and client.
  useEffect(() => {
    setAuthStatus(auth.isAuthenticated() ? 'authenticated' : 'unauthenticated')
  }, [])

  const handleLoginSuccess = useCallback(() => {
    setAuthStatus('authenticated')
  }, [])

  const handleRegisterSuccess = useCallback((email: string) => {
    setRegisterNotice(`Account created for ${email}. Please log in.`)
    setAuthView('login')
  }, [])

  const handleSwitchToRegister = useCallback(() => {
    setRegisterNotice(null)
    setAuthView('register')
  }, [])

  const handleSwitchToLogin = useCallback(() => {
    setAuthView('login')
  }, [])

  const handleLogout = useCallback(() => {
    api.logout()
    setAuthStatus('unauthenticated')
    setAuthView('login')
    setRegisterNotice(null)
  }, [])

  // Decoded, UNVERIFIED claim used only to display which account is
  // signed in — never used for any authorization decision.
  const signedInEmail =
    authStatus === 'authenticated' ? auth.decodeAccessTokenClaims()?.email ?? null : null

  return (
    <main className="min-h-screen p-8">
      <h1 className="text-3xl font-bold mb-1 text-center">
        SAIV - Secure Attendance System
      </h1>
      <p className="text-gray-600 mb-8 text-center">Student Check-in</p>

      {authStatus === 'loading' && (
        <p className="text-center text-sm text-gray-400">Loading…</p>
      )}

      {authStatus === 'unauthenticated' && authView === 'login' && (
        <LoginForm
          onLoginSuccess={handleLoginSuccess}
          onSwitchToRegister={handleSwitchToRegister}
          notice={registerNotice}
        />
      )}

      {authStatus === 'unauthenticated' && authView === 'register' && (
        <RegisterForm
          onRegisterSuccess={handleRegisterSuccess}
          onSwitchToLogin={handleSwitchToLogin}
        />
      )}

      {authStatus === 'authenticated' && (
        <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow text-center">
          <h2 className="text-2xl font-bold mb-2">You&rsquo;re signed in</h2>
          {signedInEmail && (
            <p className="text-gray-600 mb-4">Signed in as {signedInEmail}</p>
          )}
          <p className="text-gray-500 text-sm mb-6">
            Session selection will be added in the next milestone.
          </p>
          <button
            type="button"
            onClick={handleLogout}
            className="py-2 px-4 rounded bg-blue-600 text-white font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Log Out
          </button>
        </div>
      )}
    </main>
  )
}
