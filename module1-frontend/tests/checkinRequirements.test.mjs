// Run with: npm test   (Node's built-in test runner; no extra dependencies)
//
// Covers lib/checkinRequirements.ts: when a check-in needs a photo, when the student
// must enroll their face first, and the "Photo:" wording on the pre-check screen.

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  describePhotoRequirement,
  mustEnrollFaceFirst,
  sessionNeedsPhoto,
} from '../lib/checkinRequirements.ts'

const session = (liveness, faceMatch) => ({
  require_liveness_check: liveness,
  require_face_match: faceMatch,
})
const enrolled = { face_enrolled: true }
const notEnrolled = { face_enrolled: false }

test('liveness required, face match disabled: photo needed, no enrollment needed', () => {
  const s = session(true, false)
  assert.equal(sessionNeedsPhoto(s), true)
  assert.equal(mustEnrollFaceFirst(s, enrolled), false)
  // A liveness-only session must keep working for a student who never enrolled a face.
  assert.equal(mustEnrollFaceFirst(s, notEnrolled), false)
  assert.equal(describePhotoRequirement(s), 'a live photo is required.')
})

test('face match required, liveness disabled: a photo is still needed', () => {
  const s = session(false, true)
  assert.equal(sessionNeedsPhoto(s), true)
  assert.equal(mustEnrollFaceFirst(s, enrolled), false)
  assert.equal(
    describePhotoRequirement(s),
    'a photo is required, to match against your enrolled face.',
  )
})

test('both required: photo needed, wording mentions both', () => {
  const s = session(true, true)
  assert.equal(sessionNeedsPhoto(s), true)
  assert.equal(mustEnrollFaceFirst(s, enrolled), false)
  assert.equal(
    describePhotoRequirement(s),
    'a live photo is required, and it is matched against your enrolled face.',
  )
})

test('neither required: no photo and no enrollment, whatever the student has done', () => {
  const s = session(false, false)
  assert.equal(sessionNeedsPhoto(s), false)
  assert.equal(mustEnrollFaceFirst(s, enrolled), false)
  assert.equal(mustEnrollFaceFirst(s, notEnrolled), false)
  assert.equal(describePhotoRequirement(s), 'no photo is required for this session.')
})

test('face match required but no face enrolled: the student must enroll first', () => {
  assert.equal(mustEnrollFaceFirst(session(false, true), notEnrolled), true)
  assert.equal(mustEnrollFaceFirst(session(true, true), notEnrolled), true)
})

test('once a face is enrolled, a face-match session no longer blocks', () => {
  assert.equal(mustEnrollFaceFirst(session(false, true), enrolled), false)
  assert.equal(mustEnrollFaceFirst(session(true, true), enrolled), false)
})

test('only require_face_match can block on enrollment', () => {
  // Every combination without a face-match requirement is never blocked.
  for (const liveness of [true, false]) {
    for (const user of [enrolled, notEnrolled]) {
      assert.equal(mustEnrollFaceFirst(session(liveness, false), user), false)
    }
  }
})

test('a photo is needed exactly when liveness or face match is required', () => {
  for (const liveness of [true, false]) {
    for (const faceMatch of [true, false]) {
      assert.equal(sessionNeedsPhoto(session(liveness, faceMatch)), liveness || faceMatch)
    }
  }
})
