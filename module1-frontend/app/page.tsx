'use client'

/**
 * SAIV Student Frontend — auth gate + session selection (Milestone 3B)
 *
 * Shell flow:
 *
 *   unauthenticated -> LoginForm <-> RegisterForm
 *   authenticated    -> SessionSelector -> CheckInFlow
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
 * Once authenticated, SessionSelector fetches and displays the user's
 * active session(s) via the existing `api.getMySessions()`; picking one
 * hands a `Session` object to this page's state, which then renders the
 * previously-relocated consent -> camera -> liveness -> complete
 * prototype (components/CheckInFlow.tsx) below it. CheckInFlow itself
 * stays unmodified/prop-less this milestone — it still doesn't call the
 * backend, request permissions on its own, or know which session is
 * active; the selected session is only tracked here, ready for a future
 * milestone that actually submits `POST /checkins/`.
 */

import { useCallback, useEffect, useState } from 'react'
import * as auth from '@/lib/auth'
import * as api from '@/lib/api'
import LoginForm from '@/components/LoginForm'
import RegisterForm from '@/components/RegisterForm'
import SessionSelector from '@/components/SessionSelector'
import CheckInFlow from '@/components/CheckInFlow'
import type { Session } from '@/types/api'

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'
type AuthView = 'login' | 'register'
type PostAuthView = 'session-select' | 'check-in'

export default function Home() {
  const [authStatus, setAuthStatus] = useState<AuthStatus>('loading')
  const [authView, setAuthView] = useState<AuthView>('login')
  const [registerNotice, setRegisterNotice] = useState<string | null>(null)
  const [postAuthView, setPostAuthView] = useState<PostAuthView>('session-select')
  const [selectedSession, setSelectedSession] = useState<Session | null>(null)

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
    setPostAuthView('session-select')
    setSelectedSession(null)
  }, [])

  const handleSessionSelected = useCallback((session: Session) => {
    setSelectedSession(session)
    setPostAuthView('check-in')
  }, [])

  const handleChangeSession = useCallback(() => {
    setPostAuthView('session-select')
    setSelectedSession(null)
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
        <>
          <div className="max-w-md mx-auto mb-4 flex items-center justify-between text-sm">
            <span className="text-gray-600">
              {signedInEmail ? `Signed in as ${signedInEmail}` : null}
            </span>
            <button
              type="button"
              onClick={handleLogout}
              className="text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
            >
              Log Out
            </button>
          </div>

          {postAuthView === 'session-select' && (
            <SessionSelector onSessionSelected={handleSessionSelected} />
          )}

          {postAuthView === 'check-in' && selectedSession && (
            <div className="max-w-md mx-auto">
              <div className="mb-4 p-3 rounded border-l-4 border-blue-500 bg-blue-50 text-sm text-blue-700 flex items-center justify-between gap-3">
                <span>
                  Checking in to: <strong>{selectedSession.name}</strong>
                </span>
                <button
                  type="button"
                  onClick={handleChangeSession}
                  className="text-blue-600 hover:underline whitespace-nowrap focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
                >
                  Change Session
                </button>
              </div>
              <CheckInFlow />
            </div>
          )}
        </>
      )}
    </main>
  )
}
