// Deterministic synthetic test landmarks. No camera inference or physical scale.
export function generateSimulatedPose(step, type = 'squats') {
  const cycle = (step % 120) / 120.0; // 4 second full rep cycle at 30fps
  const marks = new Array(33).fill(null);

  let leftFlexDeg = 10;
  let rightFlexDeg = 10;
  let trunkLeanDeg = 0;
  let squatDepthPct = 0;

  if (type === 'balance') {
    // Stance leg (Right): straight, left leg lifted & bent
    leftFlexDeg = 55 + Math.sin(cycle * 4 * Math.PI) * 4;
    rightFlexDeg = 8 + Math.cos(cycle * 2 * Math.PI) * 2;
    trunkLeanDeg = 6 + Math.sin(cycle * 2 * Math.PI) * 4; // Subtle natural postural sway
  } else if (type === 'lunges') {
    // Lead leg (Left) steps forward and bends deep; trail leg follows
    squatDepthPct = (1.0 - Math.cos(cycle * 2 * Math.PI)) / 2.0;
    leftFlexDeg = 15 + squatDepthPct * 75; // 15 to 90 deg
    rightFlexDeg = 10 + squatDepthPct * 45; // trail knee
    trunkLeanDeg = squatDepthPct * 12;
  } else if (type === 'knee-extension') {
    // Active leg (Left) extends from bent (85 deg) to straight (10 deg)
    const extendPct = (1.0 - Math.cos(cycle * 2 * Math.PI)) / 2.0;
    leftFlexDeg = 85 - extendPct * 75;
    rightFlexDeg = 80;
    trunkLeanDeg = 5;
  } else {
    // Squat: bilateral symmetrical knee flexion
    squatDepthPct = (1.0 - Math.cos(cycle * 2 * Math.PI)) / 2.0;
    leftFlexDeg = 10 + squatDepthPct * 75; // 10 to 85 deg
    rightFlexDeg = 10 + squatDepthPct * 75;
    trunkLeanDeg = squatDepthPct * 18;
  }

  // Depth ratios
  const lDepthRatio = Math.max(0, (leftFlexDeg - 10) / 80);
  const rDepthRatio = Math.max(0, (rightFlexDeg - 10) / 80);
  const avgDepthRatio = (lDepthRatio + rDepthRatio) / 2;

  const hipY = 0.50 + avgDepthRatio * 0.18;
  const shoulderY = 0.25 + avgDepthRatio * 0.18;
  const trunkSwayX = (trunkLeanDeg / 45) * 0.04;
  const trunkLeanZ = -(trunkLeanDeg / 45) * 0.15; // 3D sagittal depth

  // Hips, Shoulders
  marks[11] = { x: 0.44 + trunkSwayX, y: shoulderY, z: -0.05 + trunkLeanZ, visibility: 0.99 }; // LShoulder
  marks[12] = { x: 0.56 + trunkSwayX, y: shoulderY, z: -0.05 + trunkLeanZ, visibility: 0.99 }; // RShoulder
  marks[23] = { x: 0.45, y: hipY, z: 0, visibility: 0.99 }; // LHip
  marks[24] = { x: 0.55, y: hipY, z: 0, visibility: 0.99 }; // RHip

  // Knees
  const lKneeY = 0.68 + (type === 'balance' ? -0.08 : lDepthRatio * 0.08);
  const rKneeY = 0.68 + rDepthRatio * 0.08;
  marks[25] = { x: 0.43, y: lKneeY, z: 0.08, visibility: 0.99 }; // LKnee
  marks[26] = { x: 0.57, y: rKneeY, z: 0.08, visibility: 0.99 }; // RKnee

  // Ankles
  const lAnkleY = type === 'balance' ? 0.78 : 0.88;
  marks[27] = { x: 0.44, y: lAnkleY, z: 0.05, visibility: 0.99 }; // LAnkle
  marks[28] = { x: 0.56, y: 0.88, z: 0.05, visibility: 0.99 }; // RAnkle

  // Feet
  marks[29] = { x: 0.44, y: lAnkleY + 0.02, z: 0.05, visibility: 0.95 };
  marks[30] = { x: 0.56, y: 0.90, z: 0.05, visibility: 0.95 };
  marks[31] = { x: 0.43, y: lAnkleY + 0.04, z: 0.18, visibility: 0.95 };
  marks[32] = { x: 0.57, y: 0.92, z: 0.18, visibility: 0.95 };

  // Head
  marks[0] = { x: 0.50 + trunkSwayX, y: shoulderY - 0.12, z: -0.08 + trunkLeanZ, visibility: 0.99 };

  // Arms
  marks[13] = { x: 0.40, y: shoulderY + 0.15, z: 0.05, visibility: 0.95 };
  marks[14] = { x: 0.60, y: shoulderY + 0.15, z: 0.05, visibility: 0.95 };
  marks[15] = { x: 0.46, y: shoulderY + 0.20, z: 0.15, visibility: 0.95 };
  marks[16] = { x: 0.54, y: shoulderY + 0.20, z: 0.15, visibility: 0.95 };

  return marks;
}

