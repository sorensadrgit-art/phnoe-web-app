import test from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizePoint,
  midpoint,
  calculateAngle2D,
  calculateAngle3D,
  calculateKneeFlexion,
  calculateHipAngle,
  calculateTrunkLean,
  calculateKneeValgus,
  calculateBilateralSymmetry,
  computePoseKinematics,
} from './liveKinematics.js';

test('normalizePoint parses objects, arrays and rejects invalid values', () => {
  assert.deepEqual(normalizePoint({ x: 10, y: 20 }), { x: 10, y: 20, z: 0 });
  assert.deepEqual(normalizePoint({ x: 10, y: 20, z: -5 }), { x: 10, y: 20, z: -5 });
  assert.deepEqual(normalizePoint([1.5, 2.5, 3.5]), { x: 1.5, y: 2.5, z: 3.5 });
  assert.deepEqual(normalizePoint([1.5, 2.5]), { x: 1.5, y: 2.5, z: 0 });
  assert.equal(normalizePoint(null), null);
  assert.equal(normalizePoint(undefined), null);
  assert.equal(normalizePoint({ x: 'bad', y: 1 }), null);
  assert.equal(normalizePoint([NaN, 1]), null);
});

test('midpoint correctly calculates coordinate averages in 3D', () => {
  const p1 = { x: 0, y: 10, z: 2 };
  const p2 = { x: 10, y: 20, z: 4 };
  assert.deepEqual(midpoint(p1, p2), { x: 5, y: 15, z: 3 });
  assert.equal(midpoint(null, p2), null);
});

test('calculateAngle2D verifies right angles, straight limbs, and acute angles', () => {
  // Right angle: B at (0, 0), A at (0, 1), C at (1, 0)
  const angle90 = calculateAngle2D({ x: 0, y: 1 }, { x: 0, y: 0 }, { x: 1, y: 0 });
  assert.equal(angle90, 90);

  // Straight line: 180 degrees
  const angle180 = calculateAngle2D({ x: -1, y: 0 }, { x: 0, y: 0 }, { x: 1, y: 0 });
  assert.equal(angle180, 180);

  // Coincident line: 0 degrees
  const angle0 = calculateAngle2D({ x: 1, y: 0 }, { x: 0, y: 0 }, { x: 1, y: 0 });
  assert.equal(angle0, 0);

  // 45 degrees
  const angle45 = calculateAngle2D({ x: 1, y: 1 }, { x: 0, y: 0 }, { x: 1, y: 0 });
  assert.equal(angle45, 45);

  // Degenerate inputs (coincident vertex)
  assert.equal(calculateAngle2D({ x: 0, y: 0 }, { x: 0, y: 0 }, { x: 1, y: 0 }), 0);
  assert.equal(calculateAngle2D(null, { x: 0, y: 0 }, { x: 1, y: 0 }), null);
});

test('calculateAngle3D handles diagonal and orthogonal 3D vectors', () => {
  const a = { x: 0, y: 1, z: 0 };
  const b = { x: 0, y: 0, z: 0 };
  const c = { x: 0, y: 0, z: 1 };
  assert.equal(calculateAngle3D(a, b, c), 90);
});

test('calculateKneeFlexion follows clinical convention (0 deg = straight, 90 deg = right angle)', () => {
  // Straight vertical leg: Hip at (0, 0), Knee at (0, 50), Ankle at (0, 100)
  const hip = { x: 0, y: 0 };
  const knee = { x: 0, y: 50 };
  const ankle = { x: 0, y: 100 };
  assert.equal(calculateKneeFlexion(hip, knee, ankle), 0);

  // 90 degree knee bend: Hip at (0, 0), Knee at (0, 50), Ankle at (50, 50)
  const ankleBent = { x: 50, y: 50 };
  assert.equal(calculateKneeFlexion(hip, knee, ankleBent), 90);

  // Deep squat: 130 degrees flexion
  // If knee is deeply bent, angle between femur and tibia is acute (50 deg -> 130 deg flexion)
  const deepAnkle = { x: 50 * Math.sin(50 * Math.PI / 180), y: 50 - 50 * Math.cos(50 * Math.PI / 180) };
  const deepFlexion = calculateKneeFlexion(hip, knee, deepAnkle);
  assert.ok(Math.abs(deepFlexion - 130) < 0.5);

  // Missing landmark
  assert.equal(calculateKneeFlexion(null, knee, ankle), null);
});

test('calculateHipAngle computes trunk-to-thigh flexion angle', () => {
  const shoulder = { x: 0, y: 0 };
  const hip = { x: 0, y: 50 };
  const knee = { x: 0, y: 100 };
  // Straight standing: 0 deg flexion
  assert.equal(calculateHipAngle(shoulder, hip, knee), 0);

  // 90 deg hip hinge (torso horizontal, legs vertical)
  const hingedShoulder = { x: 50, y: 50 };
  assert.equal(calculateHipAngle(hingedShoulder, hip, knee), 90);
});

test('calculateTrunkLean measures spinal tilt from vertical in screen coordinates', () => {
  const hipMid = { x: 100, y: 200 };

  // Perfectly vertical upright (shoulder directly above hip, y is smaller)
  const shoulderUpright = { x: 100, y: 100 };
  assert.equal(calculateTrunkLean(shoulderUpright, hipMid), 0);

  // 45 degree lateral lean (dx=100, dy=-100)
  const shoulder45 = { x: 200, y: 100 };
  assert.equal(calculateTrunkLean(shoulder45, hipMid), 45);

  // 45 degree 3D sagittal forward lean (dx=0, dy=-100, dz=-100)
  const shoulder3D45 = { x: 100, y: 100, z: -100 };
  const hip3D = { x: 100, y: 200, z: 0 };
  assert.equal(calculateTrunkLean(shoulder3D45, hip3D), 45);

  // Missing input
  assert.equal(calculateTrunkLean(null, hipMid), null);
});

test('calculateKneeValgus measures medial knee deviation in frontal plane', () => {
  // Neutral alignment: hip (100, 0), knee (100, 50), ankle (100, 100)
  const hip = { x: 100, y: 0 };
  const kneeNeutral = { x: 100, y: 50 };
  const ankle = { x: 100, y: 100 };
  assert.equal(calculateKneeValgus(hip, kneeNeutral, ankle, 'left'), 0);

  // Inward knee collapse for Left leg (knee shifts inward towards body midline)
  const kneeValgus = { x: 110, y: 50 };
  const valgusDeg = calculateKneeValgus(hip, kneeValgus, ankle, 'left');
  assert.ok(valgusDeg > 0, 'Left knee valgus should be positive');

  // Bow-legged (varus)
  const kneeVarus = { x: 90, y: 50 };
  const varusDeg = calculateKneeValgus(hip, kneeVarus, ankle, 'left');
  assert.ok(varusDeg < 0, 'Left knee varus should be negative');

  // Midline-aware valgus: bilateral hips at x=45 and x=55 (midline at 50)
  // Left hip at 45, knee collapses medial to 49 -> valgus > 0
  const lValgusMid = calculateKneeValgus({ x: 45, y: 50 }, { x: 49, y: 70 }, { x: 45, y: 90 }, 'left', 50);
  assert.ok(lValgusMid > 0, 'Midline-aware left knee collapse must be positive valgus');

  // Right hip at 55, knee collapses medial to 51 -> valgus > 0
  const rValgusMid = calculateKneeValgus({ x: 55, y: 50 }, { x: 51, y: 70 }, { x: 55, y: 90 }, 'right', 50);
  assert.ok(rValgusMid > 0, 'Midline-aware right knee collapse must be positive valgus');
});

test('calculateBilateralSymmetry outputs accurate percentages and handles boundary cases', () => {
  // Identical values
  assert.equal(calculateBilateralSymmetry(90, 90), 100);
  assert.equal(calculateBilateralSymmetry(0, 0), 100);

  // 10% discrepancy (90 vs 81) -> 90% symmetry
  assert.equal(calculateBilateralSymmetry(90, 81), 90);

  // Extreme asymmetry (100 vs 0) -> 0%
  assert.equal(calculateBilateralSymmetry(100, 0), 0);

  // Missing values
  assert.equal(calculateBilateralSymmetry(null, 90), null);
  assert.equal(calculateBilateralSymmetry(90, NaN), null);
});

test('computePoseKinematics handles both MediaPipe array and named marker objects', () => {
  // MediaPipe array (at least 29 landmarks)
  const mpArray = new Array(33).fill(null);
  mpArray[11] = { x: 45, y: 20, z: 0 }; // LShoulder
  mpArray[12] = { x: 55, y: 20, z: 0 }; // RShoulder
  mpArray[23] = { x: 45, y: 50, z: 0 }; // LHip
  mpArray[24] = { x: 55, y: 50, z: 0 }; // RHip
  mpArray[25] = { x: 45, y: 75, z: 0 }; // LKnee (straight)
  mpArray[26] = { x: 55, y: 75, z: 0 }; // RKnee (straight)
  mpArray[27] = { x: 45, y: 100, z: 0 }; // LAnkle
  mpArray[28] = { x: 55, y: 100, z: 0 }; // RAnkle

  const result = computePoseKinematics(mpArray);
  assert.ok(result);
  assert.equal(result.leftKneeFlexion, 0);
  assert.equal(result.rightKneeFlexion, 0);
  assert.equal(result.leftHipAngle, 0);
  assert.equal(result.rightHipAngle, 0);
  assert.equal(result.trunkLean, 0);
  assert.equal(result.kneeSymmetry, 100);

  // Named dictionary
  const namedDict = {
    LShoulder: { x: 45, y: 20 },
    RShoulder: { x: 55, y: 20 },
    LHip: { x: 45, y: 50 },
    RHip: { x: 55, y: 50 },
    LKnee: { x: 45, y: 75 },
    RKnee: { x: 55, y: 75 },
    LAnkle: { x: 45, y: 100 },
    RAnkle: { x: 55, y: 100 },
  };
  const resultNamed = computePoseKinematics(namedDict);
  assert.ok(resultNamed);
  assert.equal(resultNamed.leftKneeFlexion, 0);
  assert.equal(resultNamed.kneeSymmetry, 100);

  assert.equal(computePoseKinematics(null), null);
});
