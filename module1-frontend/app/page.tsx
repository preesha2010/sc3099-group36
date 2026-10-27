'use client'

/**
 * SAIV Student Frontend — the app shell: auth gate and the signed-in views
 *
 * Shell flow:
 *
 *   unauthenticated -> LoginForm <-> RegisterForm
 *   authenticated    -> SessionSelector -> CheckInFlow
 *                    -> CheckInHistory   (history + appeals; the "My check-ins" tab)
 *                    -> FaceEnrollment   (the "Face enrollment" tab, the "Enroll
 *                                         now" prompt on the session list, or
 *                                         "Enroll now" from a check-in preflight,
 *                                         which returns to that same session)
 *
 * The three main screens (sessions, history, face enrollment) share a tab bar
 * under the header; it is hidden while a session is being checked in to. A
 * session the student has already checked in to opens its existing result
 * (`existingCheckin`) instead of the flow.
 *
 * Auth status is resolved by `api.restoreSession()` — never by touching
 * localStorage directly — and only inside a `useEffect`, so the very
 * first render (both server-rendered and the client's first hydration
 * pass) always shows the same neutral 'loading' state. The real,
 * localStorage-derived status is only known after mount, client-side,
 * which avoids a hydration mismatch between server and client output.
 * If the access token has expired but a refresh token exists,
 * `restoreSession()` silently refreshes before deciding, so the status
 * stays 'loading' (no Sign In flash) until that settles.
 *
 * Login/registration themselves are fully handled by LoginForm/
 * RegisterForm, which call the existing `api.login()`/`api.register()`
 * — token persistence happens entirely inside those calls (via
 * lib/auth.ts). This page only reacts to their success callbacks to
 * flip its own status state; it never touches tokens directly.
 *
 * Once authenticated, SessionSelector fetches and displays the user's
 * active session(s) via the existing `api.getMySessions()`; picking one
 * hands a `Session` object to this page's state, which is then passed to
 * components/CheckInFlow.tsx. That flow runs a preflight, consent, a single
 * photo (when the session needs one), and then submits the check-in and shows
 * its result. It can hand control back here to leave the flow (`onExit`) or to
 * sign out when the session has expired (`onAuthExpired`).
 */

import { useCallback, useEffect, useState } from 'react'
import * as auth from '@/lib/auth'
import * as api from '@/lib/api'
import LoginForm from '@/components/LoginForm'
import RegisterForm from '@/components/RegisterForm'
import SessionSelector from '@/components/SessionSelector'
import CheckInFlow from '@/components/CheckInFlow'
import CheckInHistory from '@/components/CheckInHistory'
import FaceEnrollment from '@/components/FaceEnrollment'
import OfflineBanner from '@/components/OfflineBanner'
import { LogoMark } from '@/components/icons'
import { useOnlineStatus } from '@/lib/useOnlineStatus'
import { ACCOUNT_LOCKED_MESSAGE } from '@/lib/errors'
import type { CheckinSummary, Session } from '@/types/api'

// 'unavailable': the session couldn't be restored because the server couldn't
// be reached (offline, timeout, 5xx). Tokens were kept, so this is a "try again"
// state, not a signed-out one.
type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'unavailable'
type AuthView = 'login' | 'register'
type PostAuthView = 'session-select' | 'check-in' | 'history' | 'face-enroll'

export default function Home() {
  const [authStatus, setAuthStatus] = useState<AuthStatus>('loading')
  const [authView, setAuthView] = useState<AuthView>('login')
  const [registerNotice, setRegisterNotice] = useState<string | null>(null)
  // Shown on Sign In when the session could not be restored because the account
  // is locked (the stored tokens were cleared). Cleared by a successful sign-in.
  const [loginWarning, setLoginWarning] = useState<string | null>(null)
  const [postAuthView, setPostAuthView] = useState<PostAuthView>('session-select')
  const [selectedSession, setSelectedSession] = useState<Session | null>(null)
  // Set when the chosen session already has a check-in of the student's own: the
  // check-in screen then shows that result instead of running the flow again.
  const [existingCheckin, setExistingCheckin] = useState<CheckinSummary | null>(null)

  const isOnline = useOnlineStatus()

  // Client-only: restores the session through lib/api.ts (which reads tokens
  // via auth.ts, never localStorage directly). If the access token has
  // expired but a refresh token exists, it silently refreshes first. Runs
  // after the first render/hydration, and the status stays 'loading' until
  // it settles, so there is no premature flash of the Sign In screen. If the
  // server can't be reached the status becomes 'unavailable' (not
  // 'unauthenticated'), and the user can retry once they're back online.
  const restore = useCallback(() => {
    setAuthStatus('loading')
    setLoginWarning(null)
    let cancelled = false
    void api.restoreSession().then((restored) => {
      if (cancelled) return
      if (restored === 'locked') {
        // The locked account cannot sign in; say so on Sign In straight away.
        setLoginWarning(ACCOUNT_LOCKED_MESSAGE)
        setAuthView('login')
        setAuthStatus('unauthenticated')
        return
      }
      setAuthStatus(restored)
    })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => restore(), [restore])

  // The backend locked the account while the student was signed in (api.ts has
  // already cleared both tokens): leave every signed-in screen and say so on
  // Sign In. Safe to run more than once — it only sets state — and it
  // unsubscribes on cleanup.
  const handleAccountLocked = useCallback(() => {
    setLoginWarning(ACCOUNT_LOCKED_MESSAGE)
    setRegisterNotice(null)
    setAuthView('login')
    setPostAuthView('session-select')
    setSelectedSession(null)
    setAuthStatus('unauthenticated')
  }, [])

  useEffect(() => api.onAccountLocked(handleAccountLocked), [handleAccountLocked])

  const handleLoginSuccess = useCallback(() => {
    setLoginWarning(null)
    setAuthStatus('authenticated')
  }, [])

  const handleRegisterSuccess = useCallback((email: string) => {
    setRegisterNotice(`Account created for ${email}. Please log in.`)
    setAuthView('login')
  }, [])

  const handleSwitchToRegister = useCallback(() => {
    setRegisterNotice(null)
    setLoginWarning(null)
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
    setLoginWarning(null)
    setPostAuthView('session-select')
    setSelectedSession(null)
    setExistingCheckin(null)
  }, [])

  const handleSessionSelected = useCallback((session: Session, existing?: CheckinSummary | null) => {
    setSelectedSession(session)
    setExistingCheckin(existing ?? null)
    setPostAuthView('check-in')
  }, [])

  const handleChangeSession = useCallback(() => {
    setPostAuthView('session-select')
    setSelectedSession(null)
    setExistingCheckin(null)
  }, [])

  const handleOpenHistory = useCallback(() => {
    setPostAuthView('history')
    setSelectedSession(null)
    setExistingCheckin(null)
  }, [])

  // From the signed-in bar: enrollment is not tied to any session.
  const handleOpenFaceEnrollment = useCallback(() => {
    setPostAuthView('face-enroll')
    setSelectedSession(null)
    setExistingCheckin(null)
  }, [])

  // From a session's preflight: the chosen session is kept, so leaving
  // enrollment returns to that session's preflight (which reloads, so the new
  // enrolled status is picked up).
  const handleEnrollFromPreflight = useCallback(() => {
    setPostAuthView('face-enroll')
  }, [])

  const handleLeaveFaceEnrollment = useCallback(() => {
    setPostAuthView(selectedSession ? 'check-in' : 'session-select')
  }, [selectedSession])

  // Decoded, UNVERIFIED claim used only to display which account is
  // signed in — never used for any authorization decision.
  const signedInEmail =
    authStatus === 'authenticated' ? auth.decodeAccessTokenClaims()?.email ?? null : null
  const initial = (signedInEmail ?? '?').charAt(0).toUpperCase()

  // The three main screens share one tab bar. It is hidden while a session is
  // being checked in to, so that flow stays focused.
  const showTabs = authStatus === 'authenticated' && !selectedSession && postAuthView !== 'check-in'
  const tabs: Array<{ view: PostAuthView; label: string; onSelect: () => void }> = [
    { view: 'session-select', label: 'Check in', onSelect: handleChangeSession },
    { view: 'history', label: 'My check-ins', onSelect: handleOpenHistory },
    { view: 'face-enroll', label: 'Face enrollment', onSelect: handleOpenFaceEnrollment },
  ]

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-brand-900/10 bg-white/85 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-md items-center justify-between gap-3 px-4">
          <div className="flex min-w-0 items-center gap-3">
            <LogoMark className="h-9 w-9 shrink-0" />
            <div className="min-w-0 leading-tight">
              <h1 className="text-base font-bold">SAIV</h1>
              <p className="truncate text-xs text-gray-500">Student Check-in</p>
            </div>
          </div>
          {authStatus === 'authenticated' && (
            <div className="flex shrink-0 items-center gap-2">
              <span
                aria-hidden="true"
                title={signedInEmail ?? undefined}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-bold text-brand-800"
              >
                {initial}
              </span>
              <button
                type="button"
                onClick={handleLogout}
                className="rounded-xl border border-gray-300 bg-white px-3.5 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
              >
                Log Out
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-md px-4 pb-16 pt-6">
        <OfflineBanner />

        {authStatus === 'loading' && (
          <p className="text-center text-sm text-gray-500">Loading…</p>
        )}

        {authStatus === 'unavailable' && (
          <div className="card text-center">
            <h2 className="mb-2 text-xl font-bold">Can’t reach the server</h2>
            <p className="mb-4 text-sm text-gray-600">
              {isOnline
                ? 'We couldn’t reach the server to restore your session. You’re still signed in — please try again.'
                : 'You’re offline, so we can’t restore your session yet. You’re still signed in — reconnect and try again.'}
            </p>
            <button type="button" onClick={restore} className="btn btn-primary">
              Try again
            </button>
          </div>
        )}

        {authStatus === 'unauthenticated' && (
          <div className="mx-auto mb-6 max-w-md text-center">
            <p className="text-sm font-semibold uppercase tracking-wider text-brand-700">
              Secure Attendance System
            </p>
            <p className="mt-1 text-sm text-gray-600">
              Check in to your class in a minute: location, a quick photo, done.
            </p>
          </div>
        )}

        {authStatus === 'unauthenticated' && authView === 'login' && (
          <LoginForm
            onLoginSuccess={handleLoginSuccess}
            onSwitchToRegister={handleSwitchToRegister}
            notice={registerNotice}
            warning={loginWarning}
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
            {signedInEmail && (
              <p className="mb-3 truncate text-center text-xs text-gray-500">
                Signed in as {signedInEmail}
              </p>
            )}

            {showTabs && (
              <nav
                aria-label="Main"
                className="mb-5 grid grid-cols-3 gap-1 rounded-2xl bg-gray-200/70 p-1"
              >
                {tabs.map((tab) => {
                  const active = postAuthView === tab.view
                  return (
                    <button
                      key={tab.view}
                      type="button"
                      onClick={tab.onSelect}
                      aria-current={active ? 'page' : undefined}
                      className={`flex min-h-[44px] items-center justify-center rounded-xl px-1.5 text-center text-[13px] font-semibold leading-tight transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
                        active
                          ? 'bg-white text-brand-800 shadow-sm'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      {tab.label}
                    </button>
                  )
                })}
              </nav>
            )}

            {postAuthView === 'session-select' && (
              <SessionSelector
                onSessionSelected={handleSessionSelected}
                onEnrollFace={handleOpenFaceEnrollment}
              />
            )}

            {postAuthView === 'history' && (
              <CheckInHistory onBack={handleChangeSession} onAuthExpired={handleLogout} />
            )}

            {postAuthView === 'face-enroll' && (
              <FaceEnrollment
                onBack={handleLeaveFaceEnrollment}
                onAuthExpired={handleLogout}
                backLabel={selectedSession ? 'Back to check-in' : 'Back to sessions'}
              />
            )}

            {postAuthView === 'check-in' && selectedSession && (
              <div className="mx-auto w-full max-w-md">
                <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl bg-brand-50 px-4 py-3 text-sm text-brand-800 ring-1 ring-brand-200">
                  <span className="min-w-0">
                    Checking in to: <strong className="break-words">{selectedSession.name}</strong>
                  </span>
                  <button type="button" onClick={handleChangeSession} className="link whitespace-nowrap">
                    Change Session
                  </button>
                </div>
                <CheckInFlow
                  session={selectedSession}
                  existingCheckin={existingCheckin}
                  onExit={handleChangeSession}
                  onAuthExpired={handleLogout}
                  onEnrollFace={handleEnrollFromPreflight}
                />
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
