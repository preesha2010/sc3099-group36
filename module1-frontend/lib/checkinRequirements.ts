/**
 * What a session asks of the student at check-in: whether a photo is needed and
 * whether the student has to enroll their face first.
 *
 * The check-in flow takes ONE photo. The server analyses that same photo for
 * liveness (`require_liveness_check`) and compares it with the enrolled face
 * (`require_face_match`), so a photo is needed when either is required. A face
 * match also needs a reference to compare with, so a student who has not
 * enrolled a face cannot check in to a session that requires one.
 *
 * Kept free of imports and React so it can be unit-tested directly
 * (tests/checkinRequirements.test.mjs). Erasable TypeScript only.
 */

/** The two session flags that decide what the check-in needs (a subset of SessionDetail). */
export interface SessionRequirementFlags {
  require_liveness_check: boolean
  require_face_match: boolean
}

/** True when the check-in must include a photo: liveness and/or a face match is required. */
export function sessionNeedsPhoto(session: SessionRequirementFlags): boolean {
  return session.require_liveness_check || session.require_face_match
}

/**
 * True when the session requires a face match but the student has no enrolled face,
 * so they must enroll before checking in. Only `require_face_match` triggers this:
 * a liveness-only session never needs an enrolled face.
 */
export function mustEnrollFaceFirst(
  session: SessionRequirementFlags,
  user: { face_enrolled: boolean },
): boolean {
  return session.require_face_match && !user.face_enrolled
}

/** The "Photo:" line on the pre-check screen, matching what the check-in will actually ask for. */
export function describePhotoRequirement(session: SessionRequirementFlags): string {
  if (session.require_liveness_check && session.require_face_match) {
    return 'a live photo is required, and it is matched against your enrolled face.'
  }
  if (session.require_face_match) {
    return 'a photo is required, to match against your enrolled face.'
  }
  if (session.require_liveness_check) {
    return 'a live photo is required.'
  }
  return 'no photo is required for this session.'
}
