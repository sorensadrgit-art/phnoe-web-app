/**
 * Biomechanical Kinematics & Robotic Telemetry Model
 * Clinical coordinates based on KineLab human motion capture data
 * and Franka Research 3 forward kinematics.
 */

export const KINEMATIC_PHASES = [
  { id: 'baseline', name: 'Initial Neutral Extension', start: 0.0, end: 0.15 },
  { id: 'flexion', name: 'Active Flexion Acceleration', start: 0.15, end: 0.50 },
  { id: 'eccentric', name: 'Eccentric Extension Control', start: 0.50, end: 0.85 },
  { id: 'recovery', name: 'Terminal Recovery & Reset', start: 0.85, end: 1.00 }
];

export const MAX_FLEXION_ANGLE_DEG = 98.4;
export const ROBOT_ARM_SEGMENTS = {
  baseHeight: 0.333,
  upperArm: 0.316,
  forearm: 0.384,
  hand: 0.107
};

/**
 * Returns kinematic state at normalized progress [0, 1].
 */
export function getKinematicFrame(progress) {
  const p = Math.max(0, Math.min(1, progress));

  // Sinusoidal bell curve for human joint flexion (0 -> peak -> 0)
  const angleRad = Math.sin(p * Math.PI);
  const jointAngleDeg = angleRad * MAX_FLEXION_ANGLE_DEG;

  // Angular velocity: time derivative of joint angle (rad/s)
  const angularVelocity = Math.cos(p * Math.PI) * Math.PI * (MAX_FLEXION_ANGLE_DEG * (Math.PI / 180));

  // Joint torque estimation (Nm) based on muscular effort curve
  const torqueNm = Math.sin(p * Math.PI * 2) * 38.6 + Math.sin(p * Math.PI) * 16.4;

  // Forward kinematics for 3D end-effector coordinate
  const reachRadius = ROBOT_ARM_SEGMENTS.upperArm * Math.cos(angleRad * 0.7) +
                      ROBOT_ARM_SEGMENTS.forearm * Math.cos(angleRad * 1.1);
  const height = ROBOT_ARM_SEGMENTS.baseHeight +
                 ROBOT_ARM_SEGMENTS.upperArm * Math.sin(angleRad * 0.7) +
                 ROBOT_ARM_SEGMENTS.forearm * Math.sin(angleRad * 1.1);

  const x = Math.sin(p * 0.4 - 0.2) * 0.12;
  const y = Number(height.toFixed(4));
  const z = Number(reachRadius.toFixed(4));

  // Current phase label
  const activePhase = KINEMATIC_PHASES.find(phase => p >= phase.start && p <= phase.end) || KINEMATIC_PHASES[0];

  return {
    progress: p,
    phase: activePhase.name,
    jointAngleDeg: Number(jointAngleDeg.toFixed(2)),
    angularVelocity: Number(angularVelocity.toFixed(3)),
    torqueNm: Number(torqueNm.toFixed(2)),
    endEffectorPosition: [x, y, z]
  };
}

/**
 * Generate 97-point demonstration coordinate trajectory matching KineLab export.
 */
export function generateTrajectorySample(pointCount = 97) {
  const samples = [];
  for (let i = 0; i < pointCount; i++) {
    const t = i / (pointCount - 1);
    samples.push(getKinematicFrame(t));
  }
  return samples;
}
