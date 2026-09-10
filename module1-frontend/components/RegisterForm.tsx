'use client'

/**
 * RegisterForm
 *
 * A self-contained registration form. Calls the existing `api.register()`
 * using its existing `RegisterRequest` signature, which requires
 * `full_name` and `role` in addition to email/password — so this form
 * collects a Full Name field (not explicitly listed in the milestone's
 * UI bullet points, but required by the existing, unmodified contract;
 * see the milestone report). `role` is hardcoded to `'student'` rather
 * than exposed as a UI choice, since this frontend is the student-facing
 * app and letting a user self-select a role would be a bad idea
 * regardless of what the backend does with it.
 *
 * Per the documented contract, registration does NOT return tokens or
 * sign anyone in — `POST /auth/register` only returns the created user
 * object (`RegisterResponse`, no `access_token`/`refresh_token`). So on
 * success this form does not authenticate anyone; it hands control back
 * to the parent to show the Login form again, matching the existing
 * API's actual behaviour rather than inventing an auto-login flow.
 *
 * Password/confirm-password are kept in local component state only for
 * the duration of the form interaction — never logged, never persisted.
 */

import { useCallback, useState, type FormEvent } from 'react'
import * as api from '@/lib/api'
import { ApiError } from '@/lib/errors'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
// Matches docs/SECURITY-REQUIREMENTS.md's documented minimum password length.
const MIN_PASSWORD_LENGTH = 8

export interface RegisterFormProps {
  onRegisterSuccess: (email: string) => void
  onSwitchToLogin: () => void
}

/** Maps a registration failure to a static, user-friendly message — never the raw error. */
function describeRegisterError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'client':
        return error.message || 'That email is already registered.'
      case 'validation':
        return error.message || 'Please check your details and try again.'
      case 'rate_limit':
        return 'Too many attempts. Please wait a moment and try again.'
      case 'network':
        return 'Unable to reach the server. Check your connection and try again.'
      case 'server':
        return 'Something went wrong on our end. Please try again shortly.'
      default:
        return error.message || 'Unable to register right now. Please try again.'
    }
  }
  return 'Unable to register right now. Please try again.'
}

export default function RegisterForm({
  onRegisterSuccess,
  onSwitchToLogin,
}: RegisterFormProps) {
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      if (isSubmitting) return

      const trimmedEmail = email.trim()
      const trimmedName = fullName.trim()

      if (trimmedName.length === 0) {
        setErrorMessage('Enter your full name.')
        return
      }
      if (!EMAIL_PATTERN.test(trimmedEmail)) {
        setErrorMessage('Enter a valid email address.')
        return
      }
      if (password.length < MIN_PASSWORD_LENGTH) {
        setErrorMessage(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`)
        return
      }
      if (password !== confirmPassword) {
        setErrorMessage('Passwords do not match.')
        return
      }

      setErrorMessage(null)
      setIsSubmitting(true)
      try {
        await api.register({
          email: trimmedEmail,
          password,
          full_name: trimmedName,
          role: 'student',
        })
        onRegisterSuccess(trimmedEmail)
      } catch (error) {
        setErrorMessage(describeRegisterError(error))
      } finally {
        setIsSubmitting(false)
      }
    },
    [fullName, email, password, confirmPassword, isSubmitting, onRegisterSuccess],
  )

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow">
      <h2 className="text-2xl font-bold mb-2">Create Account</h2>
      <p className="text-gray-600 mb-4">Register to start checking in to your sessions.</p>

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
            htmlFor="register-name"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Full Name
          </label>
          <input
            id="register-name"
            name="name"
            type="text"
            autoComplete="name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            disabled={isSubmitting}
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
        </div>

        <div className="mb-4">
          <label
            htmlFor="register-email"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Email
          </label>
          <input
            id="register-email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isSubmitting}
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
        </div>

        <div className="mb-4">
          <label
            htmlFor="register-password"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Password
          </label>
          <input
            id="register-password"
            name="new-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={isSubmitting}
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
          <p className="mt-1 text-xs text-gray-400">
            At least {MIN_PASSWORD_LENGTH} characters.
          </p>
        </div>

        <div className="mb-6">
          <label
            htmlFor="register-confirm-password"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Confirm Password
          </label>
          <input
            id="register-confirm-password"
            name="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
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
          {isSubmitting ? 'Creating account…' : 'Register'}
        </button>
      </form>

      <button
        type="button"
        onClick={onSwitchToLogin}
        disabled={isSubmitting}
        className="mt-4 w-full text-sm text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 rounded disabled:opacity-50"
      >
        Already have an account? Log In
      </button>
    </div>
  )
}
