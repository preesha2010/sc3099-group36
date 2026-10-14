/**
 * Device binding.
 *
 * Implements the architecture decision on Web Crypto ECDSA device
 * binding: a P-256 keypair is generated in-browser with a
 * non-extractable private key, persisted as a CryptoKey object (never
 * as raw/JWK/base64 bytes) via the device-binding store from
 * lib/storage.ts, and only the public key ever leaves the browser —
 * PEM-encoded — via the documented POST /devices/register contract.
 *
 * Explicitly OUT of scope for this milestone (per the current API
 * contract, which has no rotation- or signature-specific fields on
 * `/devices/register` or `/checkins/`, and marks `/device/attest` as
 * optional/untested):
 *   - Key rotation.
 *   - Device attestation / challenge-response signing.
 * The private key is retained so a future milestone can add signing
 * without redesigning storage, but nothing here signs anything yet.
 */

import * as api from './api'
import * as auth from './auth'
import { getDeviceBindingStore } from './storage'
import type {
  DevicePlatform,
  DeviceRegisterRequest,
  DeviceRegisterResponse,
} from '@/types/api'

const KEYPAIR_STORAGE_KEY = 'device-keypair'
const DEVICE_ID_STORAGE_KEY = 'device-id'

// ---------------------------------------------------------------------------
// Environment checks
// ---------------------------------------------------------------------------

function isBrowser(): boolean {
  return typeof window !== 'undefined'
}

/**
 * Throws a clear, actionable error when the required Web Crypto surface
 * isn't available, instead of silently degrading to something insecure.
 * Also guards every exported function against running during Next.js
 * server-side rendering/build, where `window`/`crypto.subtle` don't exist.
 */
function assertDeviceBindingSupported(): void {
  if (!isBrowser()) {
    throw new Error('Device binding is only available in the browser.')
  }
  const cryptoObj = window.crypto
  if (!cryptoObj?.subtle || typeof cryptoObj.randomUUID !== 'function') {
    throw new Error(
      'This browser does not support the Web Crypto APIs required for device binding (SubtleCrypto / crypto.randomUUID).',
    )
  }
}

// ---------------------------------------------------------------------------
// Keypair generation & persistence
// ---------------------------------------------------------------------------

function isStoredKeyPair(value: unknown): value is CryptoKeyPair {
  return (
    typeof value === 'object' &&
    value !== null &&
    'publicKey' in value &&
    'privateKey' in value &&
    (value as CryptoKeyPair).publicKey instanceof CryptoKey &&
    (value as CryptoKeyPair).privateKey instanceof CryptoKey
  )
}

async function generateDeviceKeyPair(): Promise<CryptoKeyPair> {
  const keyPair = await window.crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' },
    false, // private key: non-extractable — see note below.
    ['sign', 'verify'],
  )

  // Per the Web Crypto spec, EC key generation always returns an
  // extractable public key regardless of the flag above, while the
  // private key's extractability follows it. Assert that invariant
  // explicitly rather than trusting it implicitly: if some environment
  // ever returns an extractable private key, refuse to use it instead
  // of silently persisting exportable key material.
  if (keyPair.privateKey.extractable) {
    throw new Error(
      'Generated device private key is unexpectedly extractable; refusing to use it.',
    )
  }

  return keyPair
}

/**
 * Returns the device's ECDSA keypair, generating and persisting one on
 * first use. The private key is never exported, logged, or exposed —
 * only the CryptoKey object itself is stored (structured clone via
 * IndexedDB), and only ever used by reference.
 *
 * If a previously-stored keypair can't be restored (e.g. a browser
 * limitation restoring a non-extractable CryptoKey from IndexedDB), this
 * fails safe: it discards the unusable record and generates a fresh
 * keypair rather than attempting to recover or expose partial key
 * material.
 */
export async function getOrCreateDeviceKeyPair(): Promise<CryptoKeyPair> {
  assertDeviceBindingSupported()

  const store = getDeviceBindingStore<CryptoKeyPair>()

  try {
    const stored = await store.getItem(KEYPAIR_STORAGE_KEY)
    if (isStoredKeyPair(stored)) {
      return stored
    }
  } catch {
    // Fall through to regeneration — see doc comment above.
  }

  const keyPair = await generateDeviceKeyPair()
  await store.setItem(KEYPAIR_STORAGE_KEY, keyPair)
  return keyPair
}

// ---------------------------------------------------------------------------
// Device identifier -> fingerprint
// ---------------------------------------------------------------------------

/**
 * A persisted random UUID, used only as input to the SHA-256 fingerprint
 * below. Never exported from this module and never sent anywhere
 * un-hashed — deliberately not a canvas/browser fingerprint, per the
 * architecture decision to avoid invasive fingerprinting techniques.
 */
async function loadOrCreateDeviceId(): Promise<string> {
  const store = getDeviceBindingStore<string>()

  const existing = await store.getItem(DEVICE_ID_STORAGE_KEY)
  if (typeof existing === 'string' && existing.length > 0) {
    return existing
  }

  const id = window.crypto.randomUUID()
  await store.setItem(DEVICE_ID_STORAGE_KEY, id)
  return id
}

// Shared so concurrent first-time callers (background device registration and
// a check-in submission, say) all get the SAME id. Without this, two callers
// could each find no stored id and each generate a different one.
let deviceIdPromise: Promise<string> | null = null

function getOrCreateDeviceId(): Promise<string> {
  if (!deviceIdPromise) {
    deviceIdPromise = loadOrCreateDeviceId().catch((error: unknown) => {
      deviceIdPromise = null
      throw error
    })
  }
  return deviceIdPromise
}

function bufferToHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * Returns the device fingerprint: SHA-256(persisted random UUID), as a
 * 64-character lowercase hex string — matching `devices.device_fingerprint
 * VARCHAR(64)` in DATABASE-SCHEMA.md.
 */
export async function getDeviceFingerprint(): Promise<string> {
  assertDeviceBindingSupported()
  const deviceId = await getOrCreateDeviceId()
  const digest = await window.crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(deviceId),
  )
  return bufferToHex(digest)
}

// ---------------------------------------------------------------------------
// Public key export (PEM)
// ---------------------------------------------------------------------------

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i += 1) {
    binary += String.fromCharCode(bytes[i])
  }
  return typeof btoa === 'function' ? btoa(binary) : Buffer.from(bytes).toString('base64')
}

/** Wraps base64-encoded DER (SPKI) bytes into standard 64-char-wrapped PEM. */
function derToPem(der: ArrayBuffer): string {
  const base64 = arrayBufferToBase64(der)
  const lines = base64.match(/.{1,64}/g) ?? [base64]
  return ['-----BEGIN PUBLIC KEY-----', ...lines, '-----END PUBLIC KEY-----'].join('\n')
}

/**
 * Returns the device's public key, exported as SPKI and PEM-encoded —
 * the format `/devices/register`'s `public_key` field documents
 * (matches `devices.public_key TEXT` in DATABASE-SCHEMA.md). The private
 * key is never touched by this function.
 */
export async function getDevicePublicKeyPem(): Promise<string> {
  assertDeviceBindingSupported()
  const { publicKey } = await getOrCreateDeviceKeyPair()
  const spki = await window.crypto.subtle.exportKey('spki', publicKey)
  return derToPem(spki)
}

// ---------------------------------------------------------------------------
// Device registration
// ---------------------------------------------------------------------------

export interface RegisterDeviceOptions {
  deviceName?: string
  platform?: DevicePlatform
}

/**
 * Registers this device with the backend via the existing
 * `/devices/register` API function (lib/api.ts) — no raw HTTP calls are
 * made here. Sends only the fields the documented contract defines:
 * fingerprint, PEM public key, and the optional name/platform.
 */
export async function registerDevice(
  options: RegisterDeviceOptions = {},
): Promise<DeviceRegisterResponse> {
  const [deviceFingerprint, publicKeyPem] = await Promise.all([
    getDeviceFingerprint(),
    getDevicePublicKeyPem(),
  ])

  const payload: DeviceRegisterRequest = {
    device_fingerprint: deviceFingerprint,
    public_key: publicKeyPem,
    device_name: options.deviceName,
    platform: options.platform,
  }

  return api.registerDevice(payload)
}

// ---------------------------------------------------------------------------
// Best-effort, per-user registration
// ---------------------------------------------------------------------------

/**
 * `registered`           — this call registered the device successfully.
 * `previously-registered` — a local success marker for this user already exists
 *                          and matches this device's current fingerprint and key.
 * `not-registered`       — registration failed, was already attempted during
 *                          this page load, or isn't possible here. Never fatal.
 */
export type DeviceRegistrationStatus =
  | 'registered'
  | 'previously-registered'
  | 'not-registered'

/**
 * Records which device identity was registered for one user on this browser.
 * Contains no secrets: the fingerprint is already sent to the server, and the
 * key digest is a SHA-256 hash of the PEM *public* key. Binding the marker to
 * both means it can never make a different fingerprint or a regenerated
 * keypair skip registration.
 *
 * No key rotation is implemented and the backend is NOT assumed to support
 * updating a registered public key (PATCH /devices has no `public_key`). If
 * the key was regenerated, the fingerprint is unchanged and registration is
 * attempted again; the backend will likely reject that (fingerprint is UNIQUE
 * and re-registration behaviour is undocumented), which simply surfaces as
 * `not-registered`. Resolving that needs a rotation contract from the backend.
 */
interface DeviceRegistrationMarker {
  registeredAt: string
  deviceFingerprint: string
  publicKeySha256: string
}

type DeviceRegistrationIdentity = Pick<
  DeviceRegistrationMarker,
  'deviceFingerprint' | 'publicKeySha256'
>

const REGISTRATION_MARKER_KEY_PREFIX = 'device-registered:'

// Generic label only — deliberately not derived from the user agent, to avoid
// fingerprinting. The schema allows a NULL name, but the spec's example and the
// only test request body always include one, so we send one.
const DEFAULT_DEVICE_NAME = 'Web Browser'

// One attempt per user per page load, and concurrent callers (e.g. React
// Strict Mode running an effect twice in dev) share one in-flight request.
// The API contract doesn't say whether registering the same fingerprint twice
// is safe, so we never retry in a loop.
const attemptedUserIds = new Set<string>()
const inFlightRegistrations = new Map<string, Promise<DeviceRegistrationStatus>>()

/** The identity (fingerprint + public-key digest) this browser would register right now. */
async function getCurrentRegistrationIdentity(): Promise<DeviceRegistrationIdentity> {
  const [deviceFingerprint, publicKeyPem] = await Promise.all([
    getDeviceFingerprint(),
    getDevicePublicKeyPem(),
  ])
  const digest = await window.crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(publicKeyPem),
  )
  return { deviceFingerprint, publicKeySha256: bufferToHex(digest) }
}

/** True only if the stored marker is well-formed AND matches the current device identity. */
function markerMatchesIdentity(
  value: unknown,
  identity: DeviceRegistrationIdentity,
): boolean {
  if (typeof value !== 'object' || value === null) return false
  const marker = value as Partial<DeviceRegistrationMarker>
  return (
    typeof marker.registeredAt === 'string' &&
    marker.deviceFingerprint === identity.deviceFingerprint &&
    marker.publicKeySha256 === identity.publicKeySha256
  )
}

async function runEnsureDeviceRegistered(
  userId: string,
): Promise<DeviceRegistrationStatus> {
  // Scoped to the server-provided user id (from GET /users/me, never JWT
  // claims), so another account on this browser never inherits this marker.
  // Logout deliberately leaves markers in place: registration belongs to the
  // device + user pair, not to a login session.
  const store = getDeviceBindingStore<DeviceRegistrationMarker>()
  const markerKey = `${REGISTRATION_MARKER_KEY_PREFIX}${userId}`

  // Whose token is in use when we start. The request below reads the token at
  // send time, so if the signed-in user changes while it is in flight we must
  // not record a marker under the user we started with.
  const tokenAtStart = auth.getAccessToken()

  let identity: DeviceRegistrationIdentity
  try {
    identity = await getCurrentRegistrationIdentity()
  } catch {
    // Web Crypto / storage unavailable: nothing we can register.
    return 'not-registered'
  }

  try {
    if (markerMatchesIdentity(await store.getItem(markerKey), identity)) {
      return 'previously-registered'
    }
  } catch {
    // Unreadable marker: treat as absent.
  }

  if (attemptedUserIds.has(userId)) return 'not-registered'
  attemptedUserIds.add(userId)

  try {
    await registerDevice({ platform: 'web', deviceName: DEFAULT_DEVICE_NAME })
  } catch {
    // Best-effort: any failure (unsupported browser, network, backend
    // rejecting a duplicate, ...) is non-fatal and sets no marker.
    return 'not-registered'
  }

  // The user (or just their token, via a refresh) changed mid-flight: we can't
  // be sure which account this registration belongs to, so record nothing. A
  // later load simply attempts again.
  if (auth.getAccessToken() !== tokenAtStart) return 'registered'

  try {
    await store.setItem(markerKey, {
      registeredAt: new Date().toISOString(),
      ...identity,
    })
  } catch {
    // Registered server-side; failing to persist the marker only means a
    // later page load may attempt again.
  }
  return 'registered'
}

/**
 * Registers this device for `userId` at most once per page load, and skips
 * entirely when a success marker for that user already exists. Never throws
 * and never blocks the caller's flow on failure.
 */
export function ensureDeviceRegistered(
  userId: string,
): Promise<DeviceRegistrationStatus> {
  if (typeof userId !== 'string' || userId.length === 0) {
    return Promise.resolve('not-registered')
  }
  const existing = inFlightRegistrations.get(userId)
  if (existing) return existing

  const attempt = runEnsureDeviceRegistered(userId)
    .catch((): DeviceRegistrationStatus => 'not-registered')
    .finally(() => {
      inFlightRegistrations.delete(userId)
    })
  inFlightRegistrations.set(userId, attempt)
  return attempt
}
