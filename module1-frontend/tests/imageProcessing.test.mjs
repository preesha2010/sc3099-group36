// Run with: npm test   (Node's built-in test runner; no extra dependencies)
//
// Covers lib/imageProcessing.ts (resizing, JPEG size budget, failures, upload guard)
// and the 413 classification the check-in and enrollment screens rely on.
// A fake `render` stands in for the canvas: it returns a JPEG-looking data URL whose
// decoded size follows a simple model, bytes = pixels * density * quality.

import test from 'node:test'
import assert from 'node:assert/strict'
import axios from 'axios'

import {
  ImageProcessingError,
  JPEG_QUALITIES,
  MAX_IMAGE_BYTES,
  MAX_IMAGE_SIDE,
  MIN_IMAGE_SIDE,
  TARGET_IMAGE_BYTES,
  PHOTO_TOO_LARGE_MESSAGE,
  base64ByteLength,
  encodeJpegWithinBudget,
  fitWithin,
  isPayloadTooLargeError,
  toUploadPayload,
} from '../lib/imageProcessing.ts'
import { toApiError } from '../lib/errors.ts'

const M2_LIMIT_BYTES = 1_048_576
const M2_LIMIT_BASE64_CHARS = ((M2_LIMIT_BYTES + 2) / 3 | 0) * 4

/** A fake canvas export: decoded size = pixels * density * quality, rounded down to a multiple of 3. */
function fakeRenderer(density, calls = []) {
  return (width, height, quality) => {
    calls.push({ width, height, quality })
    const bytes = Math.floor((width * height * density * quality) / 3) * 3
    return 'data:image/jpeg;base64,' + 'A'.repeat((bytes / 3) * 4)
  }
}

const aspect = (w, h) => w / h

// ---------------------------------------------------------------- resizing

test('fitWithin scales the longest side down to the limit and keeps the aspect ratio', () => {
  assert.deepEqual(fitWithin(1920, 1080, 1280), { width: 1280, height: 720 })
  assert.deepEqual(fitWithin(4032, 3024, 1280), { width: 1280, height: 960 })
  // Portrait (phone front camera): the HEIGHT is the long side.
  assert.deepEqual(fitWithin(1080, 1920, 1280), { width: 720, height: 1280 })
  const { width, height } = fitWithin(1920, 1440, 1280)
  assert.ok(Math.abs(aspect(width, height) - 1920 / 1440) < 0.01)
})

test('fitWithin never scales up and never returns a zero side', () => {
  assert.deepEqual(fitWithin(640, 480, 1280), { width: 640, height: 480 })
  assert.deepEqual(fitWithin(1280, 720, 1280), { width: 1280, height: 720 })
  assert.deepEqual(fitWithin(10000, 1, 1280), { width: 1280, height: 1 })
})

test('a frame larger than the limit is rendered at the reduced size, not at full size', () => {
  const calls = []
  const result = encodeJpegWithinBudget(1920, 1440, fakeRenderer(0.3, calls))
  assert.deepEqual([calls[0].width, calls[0].height], [1280, 960])
  assert.ok(calls.every((c) => Math.max(c.width, c.height) <= MAX_IMAGE_SIDE))
  assert.equal(result.width, 1280)
  assert.equal(result.height, 960)
})

// ---------------------------------------------------- already small enough

test('an image already under the target is encoded once, at the top quality, unchanged in size', () => {
  const calls = []
  const result = encodeJpegWithinBudget(640, 480, fakeRenderer(0.3, calls))
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0], { width: 640, height: 480, quality: 0.9 })
  assert.equal(result.quality, 0.9)
  assert.ok(result.bytes <= TARGET_IMAGE_BYTES)
})

test('a large frame that fits at 1280 wide still starts at quality 0.90 and stops there', () => {
  const calls = []
  const result = encodeJpegWithinBudget(1920, 1080, fakeRenderer(0.5, calls)) // 1280x720 -> ~415 KB
  assert.equal(calls.length, 1)
  assert.equal(result.quality, 0.9)
})

// ------------------------------------------------------ quality reduction

test('quality is lowered step by step until the image is under the target', () => {
  const calls = []
  // 1280x960 at density 0.9: q0.90 = 995 KB, q0.85 = 940 KB, q0.80 = 885 KB (first under 900 KB)
  const result = encodeJpegWithinBudget(1920, 1440, fakeRenderer(0.9, calls))
  assert.deepEqual(calls.map((c) => c.quality), [0.9, 0.85, 0.8])
  assert.equal(result.quality, 0.8)
  assert.equal(result.width, 1280) // size untouched while lowering quality is enough
  assert.ok(result.bytes <= TARGET_IMAGE_BYTES)
})

test('the quality never goes below the floor of 0.70 before the size is reduced', () => {
  const calls = []
  encodeJpegWithinBudget(1920, 1440, fakeRenderer(2, calls))
  assert.ok(calls.every((c) => c.quality >= Math.min(...JPEG_QUALITIES)))
  assert.equal(Math.min(...JPEG_QUALITIES), 0.7)
  // The full quality ladder was tried at 1280x960 before any size reduction.
  assert.deepEqual(calls.slice(0, 5).map((c) => [c.width, c.height, c.quality]), [
    [1280, 960, 0.9], [1280, 960, 0.85], [1280, 960, 0.8], [1280, 960, 0.75], [1280, 960, 0.7],
  ])
})

test('when lowering quality is not enough the picture is scaled down, keeping its aspect ratio', () => {
  const result = encodeJpegWithinBudget(1920, 1440, fakeRenderer(2))
  assert.ok(result.bytes <= TARGET_IMAGE_BYTES)
  assert.ok(result.width < 1280)
  assert.ok(Math.max(result.width, result.height) >= MIN_IMAGE_SIDE)
  assert.ok(Math.abs(aspect(result.width, result.height) - 4 / 3) < 0.01)
})

test('the picture is never scaled below the minimum long side', () => {
  const calls = []
  try {
    encodeJpegWithinBudget(1920, 1440, fakeRenderer(50, calls))
  } catch {
    /* expected: cannot fit */
  }
  assert.ok(calls.every((c) => Math.max(c.width, c.height) >= MIN_IMAGE_SIDE))
})

// -------------------------------------------------------------- the limit

test('an image over the target but under the hard cap is accepted only after every option was tried', () => {
  const calls = []
  // 800x600 at density 2.9: q0.70 = 974 KB (over 900 KB target, under the 1,000,000 cap)
  const result = encodeJpegWithinBudget(800, 600, fakeRenderer(2.9, calls))
  assert.equal(calls.length, JPEG_QUALITIES.length)
  assert.equal(result.quality, 0.7)
  assert.ok(result.bytes > TARGET_IMAGE_BYTES && result.bytes <= MAX_IMAGE_BYTES)
})

test('an image that cannot be brought under the hard cap fails instead of being returned', () => {
  assert.throws(
    () => encodeJpegWithinBudget(1920, 1440, fakeRenderer(5)),
    (e) => e instanceof ImageProcessingError && e.reason === 'too_large',
  )
})

test('whatever comes out is always below the backend limit (base64 and decoded), or it throws', () => {
  const sizes = [[640, 480], [1280, 720], [1280, 960], [1920, 1080], [1920, 1440], [2560, 1440], [4032, 3024], [1080, 1920], [3024, 4032]]
  for (const [w, h] of sizes) {
    for (const density of [0.1, 0.3, 0.6, 1, 1.5, 2, 3, 4, 8]) {
      let result
      try {
        result = encodeJpegWithinBudget(w, h, fakeRenderer(density))
      } catch (e) {
        assert.ok(e instanceof ImageProcessingError && e.reason === 'too_large')
        continue
      }
      const payload = result.dataUrl.replace(/^data:image\/jpeg;base64,/, '')
      assert.ok(result.bytes <= MAX_IMAGE_BYTES, `${w}x${h} d=${density}`)
      assert.ok(MAX_IMAGE_BYTES < M2_LIMIT_BYTES)
      assert.ok(base64ByteLength(payload) < M2_LIMIT_BYTES)
      assert.ok(payload.length < M2_LIMIT_BASE64_CHARS)
      assert.ok(Math.max(result.width, result.height) <= MAX_IMAGE_SIDE)
    }
  }
})

// ----------------------------------------------------- processing failures

test('a canvas that throws becomes an ImageProcessingError, never an unhandled error', () => {
  assert.throws(
    () => encodeJpegWithinBudget(1280, 720, () => { throw new Error('canvas exploded') }),
    (e) => e instanceof ImageProcessingError && e.reason === 'render_failed',
  )
})

test('an export that produced nothing ("data:,") or not a JPEG is rejected', () => {
  for (const bad of ['data:,', 'data:image/jpeg;base64,', 'data:image/png;base64,AAAA', '', undefined, null]) {
    assert.throws(
      () => encodeJpegWithinBudget(1280, 720, () => bad),
      (e) => e instanceof ImageProcessingError && e.reason === 'encode_failed',
      String(bad),
    )
  }
})

test('a video with no usable size is rejected before anything is drawn', () => {
  let drawn = false
  for (const [w, h] of [[0, 0], [1280, 0], [NaN, 720], [-1, 720], [undefined, 720]]) {
    assert.throws(
      () => encodeJpegWithinBudget(w, h, () => { drawn = true; return 'x' }),
      (e) => e instanceof ImageProcessingError && e.reason === 'invalid_source',
    )
  }
  assert.equal(drawn, false)
})

// ------------------------------------------------- upload guard (submit time)

test('toUploadPayload strips the data: prefix and keeps the base64 unchanged', () => {
  assert.equal(toUploadPayload('data:image/jpeg;base64,QUJDRA=='), 'QUJDRA==')
  assert.equal(toUploadPayload('data:image/png;base64,QUJDRA=='), 'QUJDRA==')
  assert.equal(toUploadPayload('QUJDRA=='), 'QUJDRA==') // already raw
})

test('toUploadPayload refuses an oversized image instead of passing it on', () => {
  const justOver = 'A'.repeat((Math.floor(MAX_IMAGE_BYTES / 3) + 1) * 4)
  assert.ok(base64ByteLength(justOver) > MAX_IMAGE_BYTES)
  assert.throws(
    () => toUploadPayload('data:image/jpeg;base64,' + justOver),
    (e) => e instanceof ImageProcessingError && e.reason === 'too_large',
  )
  // The old behaviour sent whatever the camera produced; an original-size frame is refused.
  assert.throws(() => toUploadPayload('data:image/jpeg;base64,' + 'A'.repeat(4_000_000)), ImageProcessingError)
  const justUnder = 'A'.repeat(Math.floor(MAX_IMAGE_BYTES / 3) * 4)
  assert.equal(toUploadPayload('data:image/jpeg;base64,' + justUnder), justUnder)
})

test('base64ByteLength matches Buffer for padded and unpadded input', () => {
  for (const n of [0, 1, 2, 3, 4, 100, 1001]) {
    const buf = Buffer.alloc(n, 7)
    assert.equal(base64ByteLength(buf.toString('base64')), n)
  }
})

// -------------------------------------------------- 413 classification (UI)

function axiosError(status, detail) {
  const response = { status, statusText: '', headers: {}, config: {}, data: detail === undefined ? {} : { detail } }
  return new axios.AxiosError('failed', 'ERR_BAD_RESPONSE', undefined, undefined, response)
}

test('a 413 from the API is recognised as "photo too large"', () => {
  const error = toApiError(axiosError(413, 'Image payload too large'))
  assert.equal(error.status, 413)
  assert.equal(error.kind, 'client') // this is the kind the screens used to treat as "no clear face"
  assert.equal(isPayloadTooLargeError(error), true)
})

test('other errors are not mistaken for a too-large photo', () => {
  for (const status of [400, 401, 403, 404, 422, 429, 500, 503]) {
    assert.equal(isPayloadTooLargeError(toApiError(axiosError(status, 'Invalid face image'))), false, String(status))
  }
  assert.equal(isPayloadTooLargeError(toApiError(new Error('boom'))), false)
  for (const odd of [null, undefined, 'x', 413, {}, { status: '413' }]) {
    assert.equal(isPayloadTooLargeError(odd), false)
  }
})

test('the message names the problem (size) and the remedy (retake), and does not blame the face', () => {
  assert.match(PHOTO_TOO_LARGE_MESSAGE, /too large/i)
  assert.match(PHOTO_TOO_LARGE_MESSAGE, /retake/i)
  assert.doesNotMatch(PHOTO_TOO_LARGE_MESSAGE, /face|clear|lighting/i)
})
