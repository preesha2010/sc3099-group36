/**
 * Generic browser storage layer (IndexedDB via localforage).
 *
 * This module only provides small, strongly-typed key/value stores. It
 * does NOT implement offline-queue behavior (enqueue/dequeue/retry) or
 * device-binding logic (keypair generation/export/rotation) — those are
 * later milestones and will be built on top of the stores exposed here.
 *
 * Two dedicated localforage instances are created, matching the
 * architecture decision on offline storage:
 *   - `checkin_queue`   — not-yet-submitted check-in requests.
 *   - `device_binding`  — device keypair / device-binding client state.
 *
 * Why localforage/IndexedDB here and not localStorage: unlike auth
 * tokens (small strings, handled exclusively by lib/auth.ts), queued
 * check-ins and device-binding material are structured objects — and in
 * the device-binding milestone, a non-extractable Web Crypto `CryptoKey`
 * — which localStorage cannot hold (string-only, ~5-10MB origin cap,
 * synchronous). localforage's IndexedDB driver supports structured
 * clone storage and larger payloads without blocking the main thread.
 *
 * Privacy constraints enforced by callers of this module (not by this
 * file itself, which is intentionally content-agnostic):
 *   - Never store passwords.
 *   - Never store access/refresh tokens — lib/auth.ts remains the only
 *     module responsible for token storage (localStorage).
 *   - Never store raw face images or liveness payloads. The existing
 *     `QueuedCheckin`/`QueuedCheckinPayload` types (types/api.ts) already
 *     omit `liveness_challenge_response` for this reason.
 */

import localforage from 'localforage'
import type { QueuedCheckin } from '@/types/api'

const DATABASE_NAME = 'saiv'

const STORE_NAMES = {
  checkinQueue: 'checkin_queue',
  deviceBinding: 'device_binding',
} as const

/** Minimal, generic key/value store contract — deliberately small. */
export interface TypedStore<T> {
  getItem(key: string): Promise<T | null>
  setItem(key: string, value: T): Promise<void>
  removeItem(key: string): Promise<void>
  keys(): Promise<string[]>
  clear(): Promise<void>
}

function isBrowser(): boolean {
  return typeof window !== 'undefined'
}

/**
 * Lazily creates (and caches) a localforage instance for the given store
 * name. Lazy + browser-gated so importing this module never touches
 * IndexedDB during Next.js server-side rendering or the production build.
 */
function createLazyInstanceFactory(
  storeName: string,
  description: string,
): () => ReturnType<typeof localforage.createInstance> | null {
  let instance: ReturnType<typeof localforage.createInstance> | null = null

  return () => {
    if (!isBrowser()) return null
    if (!instance) {
      instance = localforage.createInstance({
        name: DATABASE_NAME,
        storeName,
        description,
      })
    }
    return instance
  }
}

/**
 * Wraps a lazy localforage instance factory in the small, strongly-typed
 * TypedStore interface. Safe to call during SSR: every method becomes a
 * no-op (or resolves to null/[]) when no browser storage is available.
 */
function createTypedStore<T>(
  getInstance: () => ReturnType<typeof localforage.createInstance> | null,
): TypedStore<T> {
  return {
    async getItem(key) {
      const store = getInstance()
      if (!store) return null
      return store.getItem<T>(key)
    },
    async setItem(key, value) {
      const store = getInstance()
      if (!store) return
      await store.setItem<T>(key, value)
    },
    async removeItem(key) {
      const store = getInstance()
      if (!store) return
      await store.removeItem(key)
    },
    async keys() {
      const store = getInstance()
      if (!store) return []
      return store.keys()
    },
    async clear() {
      const store = getInstance()
      if (!store) return
      await store.clear()
    },
  }
}

const getCheckinQueueInstance = createLazyInstanceFactory(
  STORE_NAMES.checkinQueue,
  'Offline queue of not-yet-submitted check-in requests. Never holds tokens, passwords, or raw face/liveness data.',
)

const getDeviceBindingInstance = createLazyInstanceFactory(
  STORE_NAMES.deviceBinding,
  'Device-binding keypair and related client-only device state.',
)

/**
 * The offline check-in queue store. Typed against the existing
 * `QueuedCheckin` shape (types/api.ts) by default; override the generic
 * if a future milestone needs to store a different shape under the same
 * physical store.
 */
export function getCheckinQueueStore<T = QueuedCheckin>(): TypedStore<T> {
  return createTypedStore<T>(getCheckinQueueInstance)
}

/**
 * The device-binding store (keypair material, device fingerprint, etc.).
 * No canonical type exists yet — that's defined by the device-binding
 * milestone (lib/deviceBinding.ts) — so callers supply their own type
 * argument. The underlying physical store is a singleton regardless of
 * how many times this is called.
 */
export function getDeviceBindingStore<T = unknown>(): TypedStore<T> {
  return createTypedStore<T>(getDeviceBindingInstance)
}
