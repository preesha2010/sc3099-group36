/**
 * Face enrollment submission.
 *
 * Sends one captured photo to `POST /users/me/face/enroll` through the existing
 * API client. The API wants raw base64 without a `data:` prefix, so the prefix
 * the camera component adds is removed here. The image only ever lives in a
 * local variable for the duration of the call: nothing here stores, logs or
 * caches it.
 */

import * as api from './api'
import { toBase64Payload } from './checkin'
import type { FaceEnrollResponse } from '@/types/api'

export function submitFaceEnrollment(photoDataUrl: string): Promise<FaceEnrollResponse> {
  return api.enrollFace({ image: toBase64Payload(photoDataUrl) })
}
