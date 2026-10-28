/**
 * KineLab PT - Exercise Finite State Machine & Rep Counter
 * Handles real-time phase transitions, hysteresis filtering, form fault detection,
 * and comprehensive set telemetry accumulation.
 */

export const EXERCISE_TYPES = {
  SQUAT: 'squats',
  LUNGE: 'lunges',
  KNEE_EXTENSION: 'knee-extension',
  BALANCE: 'balance',
};

export const PHASES = {
  IDLE: 'IDLE',
  READY: 'READY',
  DESCENDING: 'DESCENDING',
  BOTTOM_HOLD: 'BOTTOM_HOLD',
  ASCENDING: 'ASCENDING',
  REP_COMPLETED: 'REP_COMPLETED',
};

export const FAULT_CODES = {
  INSUFFICIENT_DEPTH: 'INSUFFICIENT_DEPTH',
  KNEE_VALGUS: 'KNEE_VALGUS',
  EXCESSIVE_TRUNK_LEAN: 'EXCESSIVE_TRUNK_LEAN',
  ASYMMETRIC_LOAD: 'ASYMMETRIC_LOAD',
  RAPID_CADENCE: 'RAPID_CADENCE',
  POOR_STABILITY: 'POOR_STABILITY',
};

export const DEFAULT_PRESETS = {
  squats: {
    name: 'Squat',
    targetROM: 80, // Target knee flexion in degrees
    depthTolerance: 10,
    maxTrunkLean: 35,
    maxValgus: 8,
    minSymmetry: 75,
    minDurationMs: 800,
  },
  lunges: {
    name: 'Lunge',
    targetROM: 80,
    depthTolerance: 10,
    maxTrunkLean: 25,
    maxValgus: 10,
    minSymmetry: 60,
    minDurationMs: 900,
  },
  'knee-extension': {
    name: 'Knee Extension',
    targetROM: 75,
    depthTolerance: 8,
    maxTrunkLean: 30,
    maxValgus: 12,
    minSymmetry: 70,
    minDurationMs: 600,
  },
  balance: {
    name: 'Single-Leg Balance',
    targetROM: 30, // Hold duration in seconds
    maxTrunkLean: 20,
    maxSway: 15,
    minDurationMs: 5000,
  },
};

export function createExerciseTracker(exerciseType = EXERCISE_TYPES.SQUAT, customConfig = {}) {
  const baseConfig = DEFAULT_PRESETS[exerciseType] || DEFAULT_PRESETS.squats;
  const config = { ...baseConfig, ...customConfig };

  let phase = PHASES.IDLE;
  let repCount = 0;
  let validRepCount = 0;
  let reps = [];
  let setStartTime = null;
  let currentRepStartTime = null;
  let currentRepFaults = new Set();
  let peakFlexionCurrentRep = 0;
  let minSymmetryCurrentRep = 100;
  let bottomHoldStartTime = null;
  let lastCoachingMessage = 'Get ready to begin';
  let balanceHoldDurationMs = 0;
  let lastTimestampMs = null;

  // Smoothing buffer for noise reduction
  const HISTORY_SIZE = config.smoothingWindow !== undefined ? config.smoothingWindow : 3;
  const flexionHistory = [];

  function smoothFlexion(val) {
    if (val === null || !Number.isFinite(val)) return 0;
    if (HISTORY_SIZE <= 1) return val;
    flexionHistory.push(val);
    if (flexionHistory.length > HISTORY_SIZE) flexionHistory.shift();
    const sum = flexionHistory.reduce((a, b) => a + b, 0);
    return sum / flexionHistory.length;
  }

  function reset() {
    phase = PHASES.IDLE;
    repCount = 0;
    validRepCount = 0;
    reps = [];
    setStartTime = null;
    currentRepStartTime = null;
    lastTimestampMs = null;
    currentRepFaults.clear();
    peakFlexionCurrentRep = 0;
    minSymmetryCurrentRep = 100;
    bottomHoldStartTime = null;
    lastCoachingMessage = 'Ready. Stand in view.';
    balanceHoldDurationMs = 0;
    flexionHistory.length = 0;
  }

  function update(kinematics, timestampMs = Date.now()) {
    if (!kinematics) {
      return getState();
    }

    if (!setStartTime) setStartTime = timestampMs;
    const dt = lastTimestampMs !== null ? Math.max(0, timestampMs - lastTimestampMs) : 50;
    lastTimestampMs = timestampMs;

    const leftFlex = kinematics.leftKneeFlexion ?? 0;
    const rightFlex = kinematics.rightKneeFlexion ?? 0;
    // Primary active flexion (unilateral for lunges and knee extension)
    const activeFlexion = (exerciseType === EXERCISE_TYPES.LUNGE || exerciseType === EXERCISE_TYPES.KNEE_EXTENSION)
      ? Math.max(leftFlex, rightFlex)
      : (leftFlex + rightFlex) / 2;

    const smoothedFlex = smoothFlexion(activeFlexion);
    const trunkLean = kinematics.trunkLean ?? 0;
    const maxValgus = Math.max(Math.abs(kinematics.leftValgus ?? 0), Math.abs(kinematics.rightValgus ?? 0));
    const symmetry = kinematics.kneeSymmetry ?? 100;

    // Track minimum symmetry during active rep
    if (symmetry < minSymmetryCurrentRep) {
      minSymmetryCurrentRep = symmetry;
    }

    // State machine logic
    if (exerciseType === EXERCISE_TYPES.BALANCE) {
      // Balance mode tracks hold time and sway stability
      const isOneLegOff = Math.abs(leftFlex - rightFlex) > 20;
      if (isOneLegOff) {
        if (phase === PHASES.IDLE || phase === PHASES.READY) {
          phase = PHASES.BOTTOM_HOLD;
          bottomHoldStartTime = timestampMs;
          currentRepStartTime = timestampMs;
          currentRepFaults.clear();
          lastCoachingMessage = 'Holding balance. Keep chest upright.';
        } else if (phase === PHASES.BOTTOM_HOLD) {
          balanceHoldDurationMs += dt;
          if (trunkLean > config.maxTrunkLean) {
            currentRepFaults.add(FAULT_CODES.EXCESSIVE_TRUNK_LEAN);
            lastCoachingMessage = 'Excessive sway - steady your core';
          } else {
            const holdSec = Math.round(balanceHoldDurationMs / 1000);
            if (holdSec >= config.targetROM) {
              lastCoachingMessage = `Target ${config.targetROM}s hold achieved! Outstanding balance.`;
            } else {
              lastCoachingMessage = `Holding steady: ${holdSec}s / ${config.targetROM}s`;
            }
          }
        }
      } else {
        if (phase === PHASES.BOTTOM_HOLD) {
          // Foot placed down - finalize hold rep
          const duration = currentRepStartTime ? (timestampMs - currentRepStartTime) : balanceHoldDurationMs;
          const minDur = config.minDurationMs || 3000;
          const hasFaults = currentRepFaults.has(FAULT_CODES.EXCESSIVE_TRUNK_LEAN);
          const isValid = duration >= minDur && !hasFaults;

          if (duration >= 500) {
            repCount++;
            if (isValid) validRepCount++;
            reps.push({
              repNumber: repCount,
              durationMs: duration,
              peakDepth: Math.round(duration / 100) / 10,
              targetDepth: config.targetROM,
              minSymmetry: Math.round(symmetry * 10) / 10,
              faults: Array.from(currentRepFaults),
              valid: isValid,
              timestampMs,
            });
          }
          phase = PHASES.READY;
          lastCoachingMessage = 'Foot down. Resume when ready.';
          currentRepStartTime = null;
        } else {
          phase = PHASES.READY;
          lastCoachingMessage = 'Lift one foot to begin balance test';
        }
      }
      return getState();
    }

    // Standard cyclic movement (Squats, Lunges, Knee Extension)
    switch (phase) {
      case PHASES.IDLE:
        // Transition to READY if user is standing upright
        if (smoothedFlex < 20) {
          phase = PHASES.READY;
          lastCoachingMessage = 'Ready! Begin descending when ready.';
        } else {
          lastCoachingMessage = 'Stand upright to calibrate start posture.';
        }
        break;

      case PHASES.READY:
        if (smoothedFlex > 25) {
          phase = PHASES.DESCENDING;
          currentRepStartTime = timestampMs;
          currentRepFaults.clear();
          peakFlexionCurrentRep = smoothedFlex;
          minSymmetryCurrentRep = symmetry;
          lastCoachingMessage = 'Descending... aim for ' + config.targetROM + '°';
        }
        break;

      case PHASES.DESCENDING:
        if (smoothedFlex > peakFlexionCurrentRep) {
          peakFlexionCurrentRep = smoothedFlex;
        }

        // Live fault checks during descent
        if (trunkLean > config.maxTrunkLean) {
          currentRepFaults.add(FAULT_CODES.EXCESSIVE_TRUNK_LEAN);
          lastCoachingMessage = 'Keep your chest up!';
        }
        if (maxValgus > config.maxValgus) {
          currentRepFaults.add(FAULT_CODES.KNEE_VALGUS);
          lastCoachingMessage = 'Push knees outwards!';
        }

        // Target depth reached
        if (smoothedFlex >= (config.targetROM - 5)) {
          phase = PHASES.BOTTOM_HOLD;
          bottomHoldStartTime = timestampMs;
          lastCoachingMessage = 'Target depth reached! Stand up smoothly.';
        } else if (peakFlexionCurrentRep > 35 && smoothedFlex < (peakFlexionCurrentRep - 8)) {
          // Reversing early without reaching target
          currentRepFaults.add(FAULT_CODES.INSUFFICIENT_DEPTH);
          phase = PHASES.ASCENDING;
          lastCoachingMessage = 'Shallow depth - push deeper next rep.';
        }
        break;

      case PHASES.BOTTOM_HOLD:
        if (smoothedFlex > peakFlexionCurrentRep) {
          peakFlexionCurrentRep = smoothedFlex;
        }

        // User starts ascending
        if (smoothedFlex < (peakFlexionCurrentRep - 6)) {
          phase = PHASES.ASCENDING;
          lastCoachingMessage = 'Press upward through your heels!';
        }
        break;

      case PHASES.ASCENDING:
        // Check symmetry during ascent
        if (symmetry < config.minSymmetry) {
          currentRepFaults.add(FAULT_CODES.ASYMMETRIC_LOAD);
        }

        // Return to start position (< 20 deg flexion)
        if (smoothedFlex < 20) {
          repCount++;
          const duration = currentRepStartTime ? (timestampMs - currentRepStartTime) : 0;
          if (duration < config.minDurationMs) {
            currentRepFaults.add(FAULT_CODES.RAPID_CADENCE);
          }

          const hasFaults = currentRepFaults.size > 0;
          if (!hasFaults) validRepCount++;

          const completedRep = {
            repNumber: repCount,
            durationMs: duration,
            peakDepth: Math.round(peakFlexionCurrentRep * 10) / 10,
            targetDepth: config.targetROM,
            minSymmetry: Math.round(minSymmetryCurrentRep * 10) / 10,
            faults: Array.from(currentRepFaults),
            valid: !hasFaults,
            timestampMs,
          };
          reps.push(completedRep);

          phase = PHASES.REP_COMPLETED;
          lastCoachingMessage = hasFaults
            ? 'Rep ' + repCount + ' completed with notes (' + Array.from(currentRepFaults).join(', ') + ')'
            : 'Excellent rep ' + repCount + '! Perfect form.';
        }
        break;

      case PHASES.REP_COMPLETED:
        // Automatic brief reset back to READY for next rep
        phase = PHASES.READY;
        peakFlexionCurrentRep = 0;
        break;

      default:
        phase = PHASES.IDLE;
        break;
    }

    return getState();
  }

  function getState() {
    const totalDurationMs = setStartTime ? (Date.now() - setStartTime) : 0;
    return {
      exerciseType,
      phase,
      repCount,
      validRepCount,
      targetROM: config.targetROM,
      peakDepth: Math.round(peakFlexionCurrentRep * 10) / 10,
      currentFaults: Array.from(currentRepFaults),
      reps: [...reps],
      lastCoachingMessage,
      balanceHoldSeconds: Math.round(balanceHoldDurationMs / 100) / 10,
      durationSeconds: Math.round(totalDurationMs / 1000),
    };
  }

  function finishSet() {
    // If finishing during an active balance hold, finalize the hold
    if (exerciseType === EXERCISE_TYPES.BALANCE && phase === PHASES.BOTTOM_HOLD && currentRepStartTime) {
      const duration = balanceHoldDurationMs;
      const minDur = config.minDurationMs || 3000;
      const hasFaults = currentRepFaults.has(FAULT_CODES.EXCESSIVE_TRUNK_LEAN);
      const isValid = duration >= minDur && !hasFaults;
      if (duration >= 500) {
        repCount++;
        if (isValid) validRepCount++;
        reps.push({
          repNumber: repCount,
          durationMs: duration,
          peakDepth: Math.round(duration / 100) / 10,
          targetDepth: config.targetROM,
          minSymmetry: Math.round(minSymmetryCurrentRep * 10) / 10,
          faults: Array.from(currentRepFaults),
          valid: isValid,
          timestampMs: Date.now(),
        });
      }
    }

    const totalReps = reps.length;
    const validCount = reps.filter(r => r.valid).length;

    let avgDepth = 0;
    let bestDepth = 0;
    let avgSymmetry = 0;
    const faultCounts = {};

    if (totalReps > 0) {
      avgDepth = Math.round((reps.reduce((acc, r) => acc + r.peakDepth, 0) / totalReps) * 10) / 10;
      bestDepth = Math.max(...reps.map(r => r.peakDepth));
      avgSymmetry = Math.round((reps.reduce((acc, r) => acc + r.minSymmetry, 0) / totalReps) * 10) / 10;

      for (const rep of reps) {
        for (const f of rep.faults) {
          faultCounts[f] = (faultCounts[f] || 0) + 1;
        }
      }
    }

    const faultsLog = Object.entries(faultCounts).map(([fault, count]) => ({
      fault,
      count,
      percentage: totalReps > 0 ? Math.round((count / totalReps) * 100) : 0,
    }));

    return {
      exerciseType,
      totalReps,
      validReps: validCount,
      averageDepth: avgDepth,
      bestDepth,
      targetDepth: config.targetROM,
      averageSymmetry: avgSymmetry || 100,
      durationSeconds: Math.round((setStartTime ? (Date.now() - setStartTime) : 0) / 1000),
      faultsLog,
      reps: [...reps],
    };
  }

  return {
    update,
    getState,
    finishSet,
    reset,
    getConfig: () => ({ ...config }),
    setTargetROM: (newROM) => { config.targetROM = Number(newROM) || config.targetROM; },
  };
}
