/**
 * Photo preparation shared by check-in and face enrollment.
 *
 * Both flows take their photo from CameraCapture, which calls
 * `captureVideoFrame` here. The backend (M2) refuses any image over 1 MiB of
 * decoded bytes with HTTP 413, and a phone camera frame encoded at full size
 * can come close to or pass that. So the photo is made to fit before it is ever
 * sent:
 *
 *   1. scaled down (never up) so its longest side is at most MAX_IMAGE_SIDE,
 *      keeping the aspect ratio;
 *   2. encoded as JPEG at quality 0.90, and the real encoded size is measured;
 *   3. if that is over TARGET_IMAGE_BYTES, the quality is lowered in small
 *      steps (down to 0.70, no further, to keep the face detail the face
 *      service relies on);
 *   4. only if even 0.70 is still over target is the picture scaled down in
 *      small steps (never below MIN_IMAGE_SIDE on its long side), repeating 2-3;
 *   5. if nothing fits under MAX_IMAGE_BYTES the capture fails with an
 *      ImageProcessingError. An oversized original is never passed on.
 *
 * `toUploadPayload` is the second line of defence at submit time: it strips the
 * `data:` prefix and refuses an image over MAX_IMAGE_BYTES, whatever produced it.
 *
 * The encoding logic takes a `render` function instead of touching the DOM, so
 * it can be tested without a browser. Nothing here stores, logs or sends the image.
 *
 * (Written with erasable TypeScript only, so Node can run the tests directly.)
 */

/** Longest side of the photo that is sent, in pixels. Larger frames are scaled down to this. */
export const MAX_IMAGE_SIDE = 1280
/** The long side is never reduced below this while trying to fit the size budget. */
export const MIN_IMAGE_SIDE = 800
/** Encoded JPEG size, in bytes, that the photo is brought under. */
export const TARGET_IMAGE_BYTES = 900_000
/** Hard ceiling on what may be sent, in bytes. M2 allows 1 MiB = 1_048_576 decoded bytes. */
export const MAX_IMAGE_BYTES = 1_000_000
/** JPEG qualities tried in order; the first result at or under the target wins. */
export const JPEG_QUALITIES: readonly number[] = [0.9, 0.85, 0.8, 0.75, 0.7]
/** Each fallback scale-down multiplies the long side by this. */
const SCALE_STEP = 0.85

export type ImageProcessingReason =
  | 'invalid_source'
  | 'unsupported'
  | 'render_failed'
  | 'encode_failed'
  | 'too_large'

/** The photo could not be prepared, or is too big to send. Carries only a reason code, never image data. */
export class ImageProcessingError extends Error {
  readonly reason: ImageProcessingReason

  constructor(reason: ImageProcessingReason) {
    super(`Image processing failed: ${reason}`)
    this.name = 'ImageProcessingError'
    this.reason = reason
  }
}

/** Draws the frame at width x height and returns it as a JPEG data URL at the given quality. */
export type RenderJpeg = (width: number, height: number, quality: number) => string

export interface EncodedImage {
  dataUrl: string
  width: number
  height: number
  quality: number
  /** Decoded size of the JPEG in bytes. */
  bytes: number
}

/** Shown wherever the app or the server finds the photo too large. */
export const PHOTO_TOO_LARGE_MESSAGE =
  'That photo is too large to upload. Please retake it.'

/** True when the server answered 413 (payload too large), for any error object that carries a `status`. */
export function isPayloadTooLargeError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { status?: unknown }).status === 413
  )
}

/** Scales width x height down (never up) so the longer side is at most maxSide, keeping the aspect ratio. */
export function fitWithin(
  width: number,
  height: number,
  maxSide: number,
): { width: number; height: number } {
  const scale = Math.min(1, maxSide / Math.max(width, height))
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

/** Decoded size in bytes of a base64 string (no data: prefix). */
export function base64ByteLength(base64: string): number {
  const padding = base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0
  return Math.floor((base64.length * 3) / 4) - padding
}

const JPEG_DATA_URL = /^data:image\/jpeg;base64,/
const ANY_IMAGE_DATA_URL = /^data:image\/[a-zA-Z0-9.+-]+;base64,/

/** Decoded size of a JPEG data URL, or an encode_failed error if it is not one (e.g. canvas returned "data:,"). */
function measureJpegDataUrl(dataUrl: unknown): number {
  if (typeof dataUrl !== 'string' || !JPEG_DATA_URL.test(dataUrl)) {
    throw new ImageProcessingError('encode_failed')
  }
  const bytes = base64ByteLength(dataUrl.replace(JPEG_DATA_URL, ''))
  if (bytes <= 0) {
    throw new ImageProcessingError('encode_failed')
  }
  return bytes
}

function renderAndMeasure(
  render: RenderJpeg,
  width: number,
  height: number,
  quality: number,
): EncodedImage {
  let dataUrl: string
  try {
    dataUrl = render(width, height, quality)
  } catch (error) {
    if (error instanceof ImageProcessingError) throw error
    throw new ImageProcessingError('render_failed')
  }
  return { dataUrl, width, height, quality, bytes: measureJpegDataUrl(dataUrl) }
}

/**
 * Finds the best JPEG of the source that fits the size budget (see the file
 * comment for the exact order). Throws ImageProcessingError if none does.
 */
export function encodeJpegWithinBudget(
  sourceWidth: number,
  sourceHeight: number,
  render: RenderJpeg,
): EncodedImage {
  if (
    !Number.isFinite(sourceWidth) ||
    !Number.isFinite(sourceHeight) ||
    sourceWidth <= 0 ||
    sourceHeight <= 0
  ) {
    throw new ImageProcessingError('invalid_source')
  }

  let size = fitWithin(sourceWidth, sourceHeight, MAX_IMAGE_SIDE)
  let smallest: EncodedImage | null = null

  for (;;) {
    for (const quality of JPEG_QUALITIES) {
      const attempt = renderAndMeasure(render, size.width, size.height, quality)
      if (attempt.bytes <= TARGET_IMAGE_BYTES) {
        return attempt
      }
      smallest = attempt
    }

    const longSide = Math.max(size.width, size.height)
    if (longSide <= MIN_IMAGE_SIDE) break
    size = fitWithin(
      size.width,
      size.height,
      Math.max(MIN_IMAGE_SIDE, Math.floor(longSide * SCALE_STEP)),
    )
  }

  // Nothing reached the target. The last attempt is the smallest one (lowest
  // quality at the smallest size); use it only if it is still safely under the hard cap.
  if (smallest && smallest.bytes <= MAX_IMAGE_BYTES) {
    return smallest
  }
  throw new ImageProcessingError('too_large')
}

/**
 * Captures the current frame of a playing video as a JPEG data URL that fits
 * the size budget. Throws ImageProcessingError on any canvas or export failure.
 */
export function captureVideoFrame(video: HTMLVideoElement): string {
  if (typeof document === 'undefined') {
    throw new ImageProcessingError('unsupported')
  }
  const canvas = document.createElement('canvas')
  try {
    const context = canvas.getContext('2d')
    if (!context) {
      throw new ImageProcessingError('unsupported')
    }
    const render: RenderJpeg = (width, height, quality) => {
      canvas.width = width
      canvas.height = height
      // Set after sizing: assigning width/height resets the context's state.
      context.imageSmoothingEnabled = true
      context.imageSmoothingQuality = 'high'
      context.drawImage(video, 0, 0, width, height)
      return canvas.toDataURL('image/jpeg', quality)
    }
    return encodeJpegWithinBudget(video.videoWidth, video.videoHeight, render).dataUrl
  } finally {
    // Release the pixel buffer; some mobile browsers cap total canvas memory.
    canvas.width = 0
    canvas.height = 0
  }
}

/**
 * The raw base64 to send (data: prefix removed), after confirming the image is
 * within MAX_IMAGE_BYTES. Throws ImageProcessingError('too_large') otherwise, so
 * an oversized image is never submitted, whichever component produced it.
 */
export function toUploadPayload(dataUrl: string): string {
  const base64 = dataUrl.replace(ANY_IMAGE_DATA_URL, '')
  if (base64ByteLength(base64) > MAX_IMAGE_BYTES) {
    throw new ImageProcessingError('too_large')
  }
  return base64
}
