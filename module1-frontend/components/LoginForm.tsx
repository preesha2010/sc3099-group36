'use client'

/**
 * LoginForm
 *
 * A self-contained login form. Calls the existing `api.login()` —
 * token persistence happens entirely inside that call (via lib/auth.ts);
 * this component never touches localStorage or tokens directly. On
 * success it only notifies the parent (`onLoginSuccess`) so the parent
 * can flip its own auth-status state; it doesn't decide what happens
 * next itself.
 *
 * Password is kept in local component state only for the duration of
 * the form interaction — never logged, never persisted anywhere.
 */

import { useCallback, useState, type FormEvent } from 'react'
import * as api from '@/lib/api'
import { ApiError } from '@/lib/errors'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export interface LoginFormProps {
  onLoginSuccess: () => void
  onSwitchToRegister: () => void
  /** Optional banner (e.g. "Account created — please log in") from a prior step. */
  notice?: string | null
}

/** Maps a login failure to a static, user-friendly message — never the raw error. */
function describeLoginError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'authentication':
        return 'Incorrect email or password.'
      case 'rate_limit':
        return 'Too many attempts. Please wait a moment and try again.'
      case 'network':
        return 'Unable to reach the server. Check your connection and try again.'
      case 'server':
        return 'Something went wrong on our end. Please try again shortly.'
      default:
        return error.message || 'Unable to sign in right now. Please try again.'
    }
  }
  return 'Unable to sign in right now. Please try again.'
}

export default function LoginForm({
  onLoginSuccess,
  onSwitchToRegister,
  notice = null,
}: LoginFormProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      if (isSubmitting) return

      const trimmedEmail = email.trim()
      if (!EMAIL_PATTERN.test(trimmedEmail)) {
        setErrorMessage('Enter a valid email address.')
        return
      }
      if (password.length === 0) {
        setErrorMessage('Enter your password.')
        return
      }

      setErrorMessage(null)
      setIsSubmitting(true)
      try {
        await api.login({ email: trimmedEmail, password })
        onLoginSuccess()
      } catch (error) {
        setErrorMessage(describeLoginError(error))
      } finally {
        setIsSubmitting(false)
      }
    },
    [email, password, isSubmitting, onLoginSuccess],
  )

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Sign In</h2>
      <p className="text-gray-600 mb-4">Sign in to start your check-in.</p>

      {notice && (
        <div
          role="status"
          className="mb-4 p-3 rounded border-l-4 border-green-500 bg-green-50 text-sm text-green-700"
        >
          {notice}
        </div>
      )}

      {errorMessage && (
        <div
          role="alert"
          className="mb-4 p-3 rounded border-l-4 border-red-500 bg-red-50 text-sm text-red-700"
        >
          {errorMessage}
        </div>
      )}

      <form onSubmit={handleSubmit} noValidate>
        <div className="mb-4">
          <label
            htmlFor="login-email"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Email
          </label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isSubmitting}
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
        </div>

        <div className="mb-6">
          <label
            htmlFor="login-password"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Password
          </label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={isSubmitting}
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          aria-busy={isSubmitting}
          className="w-full py-2 px-4 rounded bg-blue-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          {isSubmitting ? 'Signing in…' : 'Log In'}
        </button>
      </form>

      <button
        type="button"
        onClick={onSwitchToRegister}
        disabled={isSubmitting}
        className="mt-4 w-full text-sm text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 rounded disabled:opacity-50"
      >
        Need an account? Register
      </button>
    </div>
  )
}
