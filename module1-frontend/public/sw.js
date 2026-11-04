/* SAIV service worker — app shell only.
 *
 * Purpose: let the installed app open and render with no connection.
 *
 * What it caches (one cache, SHELL_CACHE):
 *   - the shell page "/" (static HTML: no user data, tokens live in
 *     localStorage and the API is a different origin),
 *   - /_next/static/* — content-hashed JS/CSS/media, immutable,
 *   - the manifest and icons.
 *
 * Install fails unless everything the shell needs to render can be fetched:
 * every <script>/<link rel=stylesheet> the shell page loads must be fetched and
 * cacheable, or installation FAILS — the worker never activates and the app
 * keeps working online without it. All of that is checked BEFORE the first
 * cache write, so a failed fetch writes nothing. The writes themselves are not
 * transactional: if one fails (for example the storage quota is hit) install
 * still fails and the worker never activates, but entries written before that
 * point may remain in the cache. They are valid files from the same build, are
 * never served without an active worker, and the next install overwrites them.
 * The manifest, icons and other chunk names are optional: a failure is logged
 * with console.warn and skipped.
 *
 * What it NEVER touches (the fetch handler returns without calling
 * respondWith, so the browser handles the request exactly as if no service
 * worker existed — nothing is cached, replayed or delayed):
 *   - any non-GET request (so check-in POSTs, logins, consent PUTs, ... are
 *     never intercepted, cached or replayed),
 *   - any cross-origin request (the backend API),
 *   - any request carrying an Authorization header,
 *   - /api/ paths, RSC / router-prefetch requests, range requests,
 *   - any response marked Cache-Control: no-store / private, redirected,
 *     opaque or non-200.
 *
 * It holds no tokens and reads no storage. There is no background sync and
 * no queue: nothing is ever sent later on the user's behalf.
 */

const CACHE_PREFIX = 'saiv-shell-'
const CACHE_VERSION = 'v1'
const SHELL_CACHE = CACHE_PREFIX + CACHE_VERSION
const SHELL_URL = '/'
// Cached at install on a best-effort basis (a failure is logged and skipped —
// the app renders without them) and also the only non-hashed files served from
// the cache. Everything the shell NEEDS TO RENDER is "required" instead: see
// extractRequiredAssets / precache.
const OPTIONAL_ASSET_URLS = ['/manifest.json', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/apple-touch-icon.png']
const STATIC_PREFIX = '/_next/static/'
// Upper bound on cached hashed assets, so old builds can't accumulate forever.
const MAX_STATIC_ENTRIES = 150

function isCacheable(response) {
  if (!response || response.status !== 200 || response.type !== 'basic' || response.redirected) {
    return false
  }
  const cacheControl = (response.headers.get('Cache-Control') || '').toLowerCase()
  return !cacheControl.includes('no-store') && !cacheControl.includes('private')
}

/** Attributes of one HTML start tag, keyed by lower-cased name. */
function parseAttributes(tag) {
  const attributes = {}
  const pattern = /\s([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g
  for (const match of tag.matchAll(pattern)) {
    attributes[match[1].toLowerCase()] = match[2] ?? match[3] ?? match[4] ?? ''
  }
  return attributes
}

/**
 * The JS and CSS the shell page itself loads: the same-origin /_next/static/
 * paths in its <script src>, <link rel="stylesheet"> and <link as="script" /
 * rel="modulepreload"> tags. Without every one of these the cached page cannot
 * render, so install must fail if any of them can't be fetched and cached.
 */
function extractRequiredAssets(html) {
  const required = new Set()
  for (const match of html.matchAll(/<(script|link)\b[^>]*>/gi)) {
    const tagName = match[1].toLowerCase()
    const attributes = parseAttributes(match[0])
    const reference = tagName === 'script' ? attributes.src : attributes.href
    if (!reference || !reference.startsWith(STATIC_PREFIX)) continue

    const rel = (attributes.rel || '').toLowerCase()
    const as = (attributes.as || '').toLowerCase()
    const isStylesheet = tagName === 'link' && rel === 'stylesheet'
    const isScriptPreload = tagName === 'link' && (as === 'script' || rel === 'modulepreload')
    if (tagName === 'script' || isStylesheet || isScriptPreload) required.add(reference)
  }
  return [...required]
}

/**
 * Other same-origin /_next/static/ files mentioned anywhere in the HTML (for
 * example chunk names Next inlines in its flight data, written there as
 * "static/chunks/..."). They may be loaded later rather than at render, and
 * the pattern can over-match, so they are warmed best-effort only.
 */
function extractExtraStaticUrls(html, requiredUrls) {
  const found = new Set()
  const pattern = /(?:\/_next\/)?static\/[A-Za-z0-9_\-./~%@+]+\.(?:js|css|woff2?|png|jpg|jpeg|svg|webp|avif|ico)/g
  for (const match of html.matchAll(pattern)) {
    const path = match[0].startsWith('/_next/') ? match[0] : '/_next/' + match[0]
    if (!requiredUrls.includes(path)) found.add(path)
  }
  return [...found]
}

async function trimStaticEntries(cache) {
  const keys = await cache.keys()
  const staticKeys = keys.filter((request) => new URL(request.url).pathname.startsWith(STATIC_PREFIX))
  const excess = staticKeys.length - MAX_STATIC_ENTRIES
  for (let i = 0; i < excess; i++) {
    await cache.delete(staticKeys[i])
  }
}

/** Fetches a REQUIRED asset; anything but a cacheable 200 throws, which fails the install. */
async function fetchRequired(url) {
  const response = await fetch(url, { cache: 'reload' })
  if (!isCacheable(response)) {
    throw new Error('Required shell asset is not cacheable: ' + url + ' (status ' + response.status + ')')
  }
  return response
}

/** Best-effort: a failure is logged and skipped, never thrown. */
async function cacheOptional(cache, url) {
  try {
    const response = await fetch(url, { cache: 'reload' })
    if (!isCacheable(response)) {
      console.warn('[sw] optional asset skipped (not cacheable):', url, response.status)
      return
    }
    await cache.put(url, response)
  } catch (error) {
    console.warn('[sw] optional asset skipped (fetch failed):', url, error && error.message)
  }
}

async function precache() {
  // The shell page, fetched fresh (bypassing the HTTP cache).
  const shellResponse = await fetch(SHELL_URL, { cache: 'reload' })
  if (!isCacheable(shellResponse)) {
    // Don't install a worker that can't serve a shell offline.
    throw new Error('Shell page is not cacheable')
  }
  const html = await shellResponse.clone().text()

  // Every script/stylesheet the shell loads is REQUIRED: if any can't be
  // fetched, install fails before anything is written (and the worker never
  // activates) rather than activating with a shell that can't render offline.
  // Once the fetches have succeeded the cache writes below run; a failing write
  // also fails the install but may leave earlier entries behind (see header).
  const requiredUrls = extractRequiredAssets(html)
  if (requiredUrls.length === 0) {
    throw new Error('Shell page references no static assets')
  }
  const requiredResponses = await Promise.all(requiredUrls.map(fetchRequired))

  const cache = await caches.open(SHELL_CACHE)
  await Promise.all(requiredUrls.map((url, index) => cache.put(url, requiredResponses[index])))
  await cache.put(SHELL_URL, shellResponse)

  // Optional extras: the manifest, icons, and other chunk names found in the
  // HTML. Logged and skipped on failure; none of them is needed to render.
  const optionalUrls = [...OPTIONAL_ASSET_URLS, ...extractExtraStaticUrls(html, requiredUrls)]
  await Promise.all(optionalUrls.map((url) => cacheOptional(cache, url)))
}

self.addEventListener('install', (event) => {
  event.waitUntil(precache().then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Only delete OUR older caches; anything else on this origin is left alone.
      const names = await caches.keys()
      await Promise.all(
        names
          .filter((name) => name.startsWith(CACHE_PREFIX) && name !== SHELL_CACHE)
          .map((name) => caches.delete(name)),
      )
      await self.clients.claim()
    })(),
  )
})

/** Requests this worker must leave completely alone. */
function shouldBypass(request, url) {
  if (request.method !== 'GET') return true
  if (url.origin !== self.location.origin) return true
  if (request.headers.has('Authorization')) return true
  if (url.pathname.startsWith('/api/')) return true
  if (url.pathname === '/sw.js') return true
  // Next.js App Router data / prefetch requests (React Server Component payloads).
  if (request.headers.has('RSC') || request.headers.has('Next-Router-State-Tree')) return true
  if (request.headers.has('Next-Router-Prefetch') || url.searchParams.has('_rsc')) return true
  if (request.headers.has('Range')) return true
  return false
}

async function cacheFirst(request, event) {
  const cache = await caches.open(SHELL_CACHE)
  const cached = await cache.match(request)
  if (cached) return cached

  const response = await fetch(request)
  if (isCacheable(response)) {
    event.waitUntil(
      cache.put(request, response.clone()).then(() => trimStaticEntries(cache)),
    )
  }
  return response
}

async function shellNetworkFirst(request, event) {
  const cache = await caches.open(SHELL_CACHE)
  try {
    const response = await fetch(request)
    // Keep the shell fresh, but never store a response for a URL with a query
    // string or one that isn't plain cacheable HTML.
    const contentType = response.headers.get('Content-Type') || ''
    if (isCacheable(response) && contentType.includes('text/html') && !new URL(request.url).search) {
      event.waitUntil(cache.put(SHELL_URL, response.clone()))
    }
    return response
  } catch {
    const cached = await cache.match(SHELL_URL)
    return cached || Response.error()
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (shouldBypass(request, url)) return

  if (url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(cacheFirst(request, event))
    return
  }

  if (OPTIONAL_ASSET_URLS.includes(url.pathname)) {
    event.respondWith(cacheFirst(request, event))
    return
  }

  if (request.mode === 'navigate' && url.pathname === SHELL_URL) {
    event.respondWith(shellNetworkFirst(request, event))
  }
  // Everything else: not handled.
})
