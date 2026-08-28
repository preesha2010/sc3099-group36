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
async function getOrCreateDeviceId(): Promise<string> {
  const store = getDeviceBindingStore<string>()

  const existing = await store.getItem(DEVICE_ID_STORAGE_KEY)
  if (typeof existing === 'string' && existing.length > 0) {
    return existing
  }

  const id = window.crypto.randomUUID()
  await store.setItem(DEVICE_ID_STORAGE_KEY, id)
  return id
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
