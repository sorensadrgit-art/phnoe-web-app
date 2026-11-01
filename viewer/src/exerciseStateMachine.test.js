import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createExerciseTracker,
  EXERCISE_TYPES,
  PHASES,
  FAULT_CODES,
} from './exerciseStateMachine.js';

// Explicit complete synthetic observations for the historical protocol tests.
function createTestTracker(...args) {
  const tracker=createExerciseTracker(...args); const update=tracker.update;
  tracker.update=(sample,time)=>update({trunkLean:0,leftValgus:0,rightValgus:0,kneeSymmetry:100,ankleHeightDifference:0,...sample},time);
  return tracker;
}

test('Squat tracker transitions through full valid rep cycle and increments counts', () => {
  const tracker = createTestTracker(EXERCISE_TYPES.SQUAT, {
    targetROM: 80,
    minDurationMs: 100, // lower for test timing
    smoothingWindow: 1,
  });

  let state = tracker.getState();
  assert.equal(state.phase, PHASES.IDLE);
  assert.equal(state.repCount, 0);

  let time = 1000;

  // 1. Stand upright (< 20 deg) -> triggers READY
  state = tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);
  assert.equal(state.phase, PHASES.READY);

  // 2. Start descending (> 25 deg)
  time += 200;
  state = tracker.update({ leftKneeFlexion: 35, rightKneeFlexion: 35 }, time);
  assert.equal(state.phase, PHASES.DESCENDING);

  // 3. Continue descending to target ROM (80 deg)
  time += 300;
  state = tracker.update({ leftKneeFlexion: 85, rightKneeFlexion: 85 }, time);
  assert.equal(state.phase, PHASES.BOTTOM_HOLD);

  // 4. Begin ascent (flexion decreases below peak)
  time += 200;
  state = tracker.update({ leftKneeFlexion: 60, rightKneeFlexion: 60 }, time);
  assert.equal(state.phase, PHASES.ASCENDING);

  // 5. Return to upright (< 20 deg) -> finishes rep
  time += 300;
  state = tracker.update({ leftKneeFlexion: 12, rightKneeFlexion: 12 }, time);
  assert.equal(state.phase, PHASES.REP_COMPLETED);
  assert.equal(state.repCount, 1);
  assert.equal(state.validRepCount, 1);
  assert.equal(state.reps.length, 1);
  assert.equal(state.reps[0].valid, true);
  assert.equal(state.reps[0].faults.length, 0);
  assert.ok(state.reps[0].peakDepth >= 70);

  // Next frame transitions to READY for rep 2
  time += 50;
  state = tracker.update({ leftKneeFlexion: 12, rightKneeFlexion: 12 }, time);
  assert.equal(state.phase, PHASES.READY);
});

test('Squat tracker detects INSUFFICIENT_DEPTH when reversing prematurely', () => {
  const tracker = createTestTracker(EXERCISE_TYPES.SQUAT, {
    targetROM: 90,
    minDurationMs: 50,
    smoothingWindow: 1,
  });

  let time = 1000;
  // Calibrate standing
  tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);

  // Descend to only 45 degrees
  time += 200;
  tracker.update({ leftKneeFlexion: 45, rightKneeFlexion: 45 }, time);

  // User reverses back up before reaching 90
  time += 150;
  tracker.update({ leftKneeFlexion: 32, rightKneeFlexion: 32 }, time);

  // Return to top
  time += 200;
  const state = tracker.update({ leftKneeFlexion: 12, rightKneeFlexion: 12 }, time);

  assert.equal(state.repCount, 1);
  assert.equal(state.validRepCount, 0, 'Shallow rep should be invalid');
  assert.ok(state.reps[0].faults.includes(FAULT_CODES.INSUFFICIENT_DEPTH));
});

test('Squat tracker flags KNEE_VALGUS and EXCESSIVE_TRUNK_LEAN faults', () => {
  const tracker = createTestTracker(EXERCISE_TYPES.SQUAT, {
    targetROM: 80,
    maxValgus: 8,
    maxTrunkLean: 30,
    minDurationMs: 50,
    smoothingWindow: 1,
  });

  let time = 1000;
  tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);

  // Descend with severe knee valgus (14 deg) and excessive trunk lean (42 deg)
  time += 200;
  tracker.update({
    leftKneeFlexion: 50,
    rightKneeFlexion: 50,
    leftValgus: 14,
    trunkLean: 42,
  }, time);

  // Reach depth
  time += 200;
  tracker.update({
    leftKneeFlexion: 85,
    rightKneeFlexion: 85,
    leftValgus: 12,
    trunkLean: 38,
  }, time);

  // Ascent and finish
  time += 200;
  tracker.update({ leftKneeFlexion: 50, rightKneeFlexion: 50 }, time);
  time += 200;
  const state = tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);

  assert.equal(state.repCount, 1);
  assert.equal(state.validRepCount, 0);
  const rep = state.reps[0];
  assert.ok(rep.faults.includes(FAULT_CODES.KNEE_VALGUS));
  assert.ok(rep.faults.includes(FAULT_CODES.EXCESSIVE_TRUNK_LEAN));
});

test('finishSet produces aggregated telemetry with averages and fault breakdown', () => {
  const tracker = createTestTracker(EXERCISE_TYPES.SQUAT, {
    targetROM: 80,
    minDurationMs: 50,
    smoothingWindow: 1,
  });

  // Perform 2 reps (one valid, one with valgus)
  let time = 1000;
  tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);

  // Rep 1: clean (peak ~85)
  time += 200; tracker.update({ leftKneeFlexion: 40, rightKneeFlexion: 40, kneeSymmetry: 95 }, time);
  time += 200; tracker.update({ leftKneeFlexion: 85, rightKneeFlexion: 85, kneeSymmetry: 95 }, time);
  time += 200; tracker.update({ leftKneeFlexion: 50, rightKneeFlexion: 50, kneeSymmetry: 95 }, time);
  time += 200; tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10, kneeSymmetry: 95 }, time);

  // Rep 2: with valgus (peak ~95)
  time += 100; tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);
  time += 200; tracker.update({ leftKneeFlexion: 40, rightKneeFlexion: 40, leftValgus: 15, kneeSymmetry: 85 }, time);
  time += 200; tracker.update({ leftKneeFlexion: 95, rightKneeFlexion: 95, leftValgus: 15, kneeSymmetry: 85 }, time);
  time += 200; tracker.update({ leftKneeFlexion: 50, rightKneeFlexion: 50, kneeSymmetry: 85 }, time);
  time += 200; tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10, kneeSymmetry: 85 }, time);

  const summary = tracker.finishSet();
  assert.equal(summary.totalReps, 2);
  assert.equal(summary.validReps, 1);
  assert.ok(summary.averageDepth > 80);
  assert.ok(summary.bestDepth >= 90);
  assert.equal(summary.faultsLog.length, 1);
  assert.equal(summary.faultsLog[0].fault, FAULT_CODES.KNEE_VALGUS);
  assert.equal(summary.faultsLog[0].count, 1);
  assert.equal(summary.faultsLog[0].percentage, 50);
});

test('Single-Leg Balance tracking accumulates hold duration and detects trunk sway', () => {
  const tracker = createTestTracker(EXERCISE_TYPES.BALANCE, {
    maxTrunkLean: 20,
  });

  let time = 1000;
  // Upright standing both feet on ground
  let state = tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);
  assert.equal(state.phase, PHASES.READY);

  // Lift right leg (flexion discrepancy > 25)
  time += 100;
  state = tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 50, ankleHeightDifference: .3, trunkLean: 5 }, time);
  assert.equal(state.phase, PHASES.BOTTOM_HOLD);

  // Maintain hold with good posture
  time += 200;
  state = tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 50, ankleHeightDifference: .3, trunkLean: 8 }, time);
  assert.ok(state.balanceHoldSeconds > 0);

  // Excessive trunk sway
  time += 100;
  state = tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 50, ankleHeightDifference: .3, trunkLean: 32 }, time);
  assert.ok(state.currentFaults.includes(FAULT_CODES.EXCESSIVE_TRUNK_LEAN));

  // Foot placed down -> completes hold rep
  for(let i=0;i<20;i++){time+=200;tracker.update({leftKneeFlexion:10,rightKneeFlexion:50,ankleHeightDifference:.3,trunkLean:32},time);}
  time += 100; // Continuous observed hold; gaps are not counted.
  state = tracker.update({ leftKneeFlexion: 10, rightKneeFlexion: 10 }, time);
  assert.equal(state.phase, PHASES.READY);
  assert.equal(state.repCount, 1);
  assert.equal(state.reps.length, 1);
  assert.ok(state.reps[0].durationMs >= 4000);

  // Finishing set accumulates balance summary
  const summary = tracker.finishSet();
  assert.equal(summary.totalReps, 1);
  assert.ok(summary.averageDepth > 0);
});
