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
  if (!DEFAULT_PRESETS[exerciseType]) throw new Error('Unknown exercise');
  const config = { ...DEFAULT_PRESETS[exerciseType], activeSide: 'left', smoothingWindow: 3, ...customConfig };
  if (!['left','right'].includes(config.activeSide) || !Number.isFinite(config.targetROM) || config.targetROM <= 0 ||
      !Number.isInteger(config.smoothingWindow) || config.smoothingWindow < 1 || config.smoothingWindow > 15) throw new Error('Invalid exercise configuration');
  const extension = exerciseType === EXERCISE_TYPES.KNEE_EXTENSION;
  const unilateral = extension || exerciseType === EXERCISE_TYPES.LUNGE;
  let phase, reps, faults, peak, minSymmetry, repStart, lastTimestamp, lastSeen, elapsed, holdMs, message, finished;
  const history = [];
  function clearCycle() {
    phase = PHASES.IDLE; faults = new Set(); peak = 0; minSymmetry = null; repStart = null; holdMs = 0; history.length = 0;
  }
  function reset() {
    clearCycle(); reps = []; lastTimestamp = null; lastSeen = null; elapsed = 0; finished = null;
    message = 'Ready for a new test set. Thresholds are not clinically validated.';
  }
  reset();
  function pause() {
    if (!finished) { clearCycle(); lastTimestamp = null; message = 'Paused or unavailable. Incomplete repetition discarded.'; }
    return getState();
  }
  function addRep(duration, timestamp) {
    if (duration < config.minDurationMs) faults.add(FAULT_CODES.RAPID_CADENCE);
    const valid = config.projectionOnly ? null : faults.size === 0;
    reps.push(Object.freeze({repNumber:reps.length+1, durationMs:duration,
      peakDepth:Math.round((exerciseType === EXERCISE_TYPES.BALANCE ? duration/1000 : peak)*10)/10,
      targetDepth:config.targetROM, minSymmetry,
      faults:Object.freeze([...faults]), valid, timestampMs:timestamp}));
  }
  function assess(k) {
    if (config.projectionOnly) return;
    if (![k.trunkLean,k.leftValgus,k.rightValgus,k.kneeSymmetry].every(Number.isFinite)) faults.add('INSUFFICIENT_EVIDENCE');
    if (Number.isFinite(k.kneeSymmetry)) minSymmetry = minSymmetry === null ? k.kneeSymmetry : Math.min(minSymmetry,k.kneeSymmetry);
    if (k.trunkLean > config.maxTrunkLean) faults.add(FAULT_CODES.EXCESSIVE_TRUNK_LEAN);
    if (Math.max(Math.abs(k.leftValgus),Math.abs(k.rightValgus)) > config.maxValgus) faults.add(FAULT_CODES.KNEE_VALGUS);
    if (!unilateral && exerciseType !== EXERCISE_TYPES.BALANCE && k.kneeSymmetry < config.minSymmetry) faults.add(FAULT_CODES.ASYMMETRIC_LOAD);
  }
  function update(k, timestampMs = Date.now()) {
    if (finished) return getState();
    if (!Number.isFinite(timestampMs) || timestampMs < 0 || (lastSeen !== null && timestampMs <= lastSeen)) return pause();
    const gap = lastTimestamp === null ? 0 : timestampMs-lastTimestamp;
    lastSeen = timestampMs;
    const active = config.activeSide === 'left' ? k?.leftKneeFlexion : k?.rightKneeFlexion;
    const required = unilateral ? [active] : [k?.leftKneeFlexion,k?.rightKneeFlexion];
    if (!k || required.some(v=>!Number.isFinite(v)||v<0||v>180) || gap > 500 ||
        (exerciseType === EXERCISE_TYPES.BALANCE && !Number.isFinite(k.ankleHeightDifference))) return pause();
    lastTimestamp = timestampMs; elapsed += gap;
    if (exerciseType === EXERCISE_TYPES.BALANCE) {
      if (k.ankleHeightDifference > .15) {
        if (phase !== PHASES.BOTTOM_HOLD) {
          clearCycle(); phase = PHASES.BOTTOM_HOLD; repStart = timestampMs;
        } else holdMs += gap;
        assess(k); message = 'Visible raised-ankle hold. This does not measure balance ability.';
      } else {
        if (phase === PHASES.BOTTOM_HOLD && holdMs >= 500) addRep(holdMs,timestampMs);
        clearCycle(); phase = PHASES.READY; message = 'Raise one ankle in view to begin the test hold.';
      }
      return getState();
    }
    const value = extension ? 90-active : unilateral ? active : (k.leftKneeFlexion+k.rightKneeFlexion)/2;
    history.push(value); if (history.length > config.smoothingWindow) history.shift();
    const progress = history.reduce((a,b)=>a+b,0)/history.length;
    if (phase === PHASES.IDLE) {
      if (progress < 20) phase = PHASES.READY;
      message = extension ? 'Begin from a flexed knee; test target is extension excursion from 90 degrees.' : 'Begin from the starting pose.';
    } else if (phase === PHASES.READY) {
      if (progress > 25) {
        phase = PHASES.DESCENDING; repStart = timestampMs; peak = progress; faults.clear(); minSymmetry = null; assess(k);
      }
    } else if (phase === PHASES.REP_COMPLETED) {
      phase = PHASES.READY; peak = 0;
    } else {
      peak = Math.max(peak,progress); assess(k);
      if (phase === PHASES.DESCENDING) {
        if (progress >= config.targetROM-5) phase = PHASES.BOTTOM_HOLD;
        else if (peak > 35 && progress < peak-8) { faults.add(FAULT_CODES.INSUFFICIENT_DEPTH); phase = PHASES.ASCENDING; }
      } else if (phase === PHASES.BOTTOM_HOLD && progress < peak-6) phase = PHASES.ASCENDING;
      else if (phase === PHASES.ASCENDING && progress < 20) {
        addRep(timestampMs-repStart,timestampMs); phase = PHASES.REP_COMPLETED;
      }
      message = config.projectionOnly ? 'Image-plane cycle estimate only; form and physical accuracy unverified.' : 'Synthetic protocol test; no clinical form assessment.';
    }
    return getState();
  }
  function getState() {
    return {exerciseType, phase, repCount:reps.length, validRepCount:config.projectionOnly?null:reps.filter(r=>r.valid).length,
      targetROM:config.targetROM, peakDepth:Math.round(peak*10)/10, currentFaults:[...faults], reps:[...reps],
      lastCoachingMessage:message, balanceHoldSeconds:Math.round(holdMs/100)/10,
      durationSeconds:Math.round(elapsed/1000), projectionOnly:Boolean(config.projectionOnly), finished:Boolean(finished)};
  }
  function finishSet() {
    if (finished) return finished;
    if (exerciseType === EXERCISE_TYPES.BALANCE && phase === PHASES.BOTTOM_HOLD && holdMs >= 500) addRep(holdMs,lastTimestamp);
    const counts = {};
    for (const rep of reps) for (const fault of rep.faults) counts[fault]=(counts[fault]||0)+1;
    const mean = values => values.length && values.every(Number.isFinite) ? Math.round(values.reduce((a,b)=>a+b,0)/values.length*10)/10 : null;
    finished = Object.freeze({exerciseType,totalReps:reps.length,validReps:config.projectionOnly?null:reps.filter(r=>r.valid).length,
      averageDepth:mean(reps.map(r=>r.peakDepth)),bestDepth:reps.length?Math.max(...reps.map(r=>r.peakDepth)):null,
      targetDepth:config.targetROM,averageSymmetry:mean(reps.map(r=>r.minSymmetry)),durationSeconds:Math.round(elapsed/1000),
      faultsLog:Object.freeze(Object.entries(counts).map(([fault,count])=>Object.freeze({fault,count,percentage:Math.round(count/reps.length*100)}))),
      reps:Object.freeze([...reps])});
    return finished;
  }
  return {update,getState,finishSet,reset,pause,getConfig:()=>({...config})};
}
