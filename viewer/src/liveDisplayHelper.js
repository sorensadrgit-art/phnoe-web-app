import { EXERCISE_TYPES } from './exerciseStateMachine.js';

export const isKneeAngle = value => Number.isFinite(value) && value >= 0 && value <= 180;

/**
 * Computes the real-time exercise metric according to the exercise definition:
 * - Squats: bilateral average knee flexion ((left + right) / 2)
 * - Lunges: active side knee flexion
 * - Knee Extension: extension excursion from 90° (90 - active knee flexion)
 * - Balance: hold duration in seconds (from trackerState.balanceHoldSeconds)
 *
 * Missing or invalid kinematics must stay UNAVAILABLE (null), NEVER defaulted to 0 or 0°.
 */
export function computeExerciseMetric(kinematics, exerciseType, activeSide = 'left', trackerState = null) {
  if (!kinematics) return null;
  const left = kinematics.leftKneeFlexion;
  const right = kinematics.rightKneeFlexion;

  if (exerciseType === EXERCISE_TYPES.SQUAT) {
    if (!isKneeAngle(left) || !isKneeAngle(right)) return null;
    return (left + right) / 2;
  }

  if (exerciseType === EXERCISE_TYPES.LUNGE) {
    if (!['left', 'right'].includes(activeSide)) return null;
    const active = activeSide === 'left' ? left : right;
    if (!isKneeAngle(active)) return null;
    return active;
  }

  if (exerciseType === EXERCISE_TYPES.KNEE_EXTENSION) {
    if (!['left', 'right'].includes(activeSide)) return null;
    const active = activeSide === 'left' ? left : right;
    if (!isKneeAngle(active)) return null;
    return 90 - active;
  }

  if (exerciseType === EXERCISE_TYPES.BALANCE) {
    if (!Number.isFinite(kinematics.ankleHeightDifference)) return null;
    if (!isKneeAngle(left) || !isKneeAngle(right)) return null;
    const hold = trackerState?.balanceHoldSeconds;
    if (Number.isFinite(hold) && hold >= 0) {
      return hold;
    }
    return null;
  }

  return null;
}

/**
 * Checks if current depth/metric is within the target zone.
 * Must require valid finite currentDepth !== null and match exercise type requirements.
 * Never triggers when metric is UNAVAILABLE (null/non-finite) or mismatching exercise type.
 */
export function isTargetZoneReached(currentDepth, targetROM, exerciseType) {
  if (currentDepth === null || currentDepth === undefined || !Number.isFinite(currentDepth)) {
    return false;
  }
  if (!Number.isFinite(targetROM) || targetROM <= 0) {
    return false;
  }

  if (
    exerciseType === EXERCISE_TYPES.SQUAT ||
    exerciseType === EXERCISE_TYPES.LUNGE ||
    exerciseType === EXERCISE_TYPES.KNEE_EXTENSION
  ) {
    return currentDepth >= (targetROM - 5);
  }

  if (exerciseType === EXERCISE_TYPES.BALANCE) {
    return currentDepth >= targetROM;
  }

  return false;
}
