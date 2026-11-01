/**
 * KineLab PT - Live Biomechanical Kinematics Engine
 * Pure geometry. Image-plane projections do not establish anatomical accuracy.
 * Zero external dependencies, robust against missing or degenerate landmarks.
 */

const RAD2DEG = 180 / Math.PI;

/**
 * Missing depth remains null.
 * Accepts {x, y, z?} or [x, y, z?].
 */
export function normalizePoint(p) {
  if (!p) return null;
  if (Array.isArray(p)) {
    if (typeof p[0] !== 'number' || typeof p[1] !== 'number' || !Number.isFinite(p[0]) || !Number.isFinite(p[1])) {
      return null;
    }
    if (p[2] != null && !Number.isFinite(p[2])) return null;
    return { x: p[0], y: p[1], z: p[2] ?? null };
  }
  if (typeof p.x !== 'number' || typeof p.y !== 'number' || !Number.isFinite(p.x) || !Number.isFinite(p.y)) {
    return null;
  }
  if (p.z != null && !Number.isFinite(p.z)) return null;
  return { x: p.x, y: p.y, z: p.z ?? null };
}

/**
 * Midpoint between two landmarks.
 */
export function midpoint(p1, p2) {
  const a = normalizePoint(p1);
  const b = normalizePoint(p2);
  if (!a || !b) return null;
  return {
    x: (a.x + b.x) / 2,
    y: (a.y + b.y) / 2,
    z: a.z !== null && b.z !== null ? (a.z + b.z) / 2 : null,
  };
}

/**
 * Calculate 2D angle (in degrees) at vertex B formed by points A, B, and C.
 * Formula: theta = arccos( (BA . BC) / (|BA| * |BC|) )
 * Range: [0, 180] degrees.
 */
export function calculateAngle2D(a, b, c) {
  const pA = normalizePoint(a);
  const pB = normalizePoint(b);
  const pC = normalizePoint(c);
  if (!pA || !pB || !pC) return null;

  const vBAx = pA.x - pB.x;
  const vBAy = pA.y - pB.y;
  const vBCx = pC.x - pB.x;
  const vBCy = pC.y - pB.y;

  const magBA = Math.hypot(vBAx, vBAy);
  const magBC = Math.hypot(vBCx, vBCy);

  if (magBA < 1e-9 || magBC < 1e-9) return null;

  const dot = vBAx * vBCx + vBAy * vBCy;
  const cosTheta = Math.max(-1, Math.min(1, dot / (magBA * magBC)));
  return Math.round(Math.acos(cosTheta) * RAD2DEG * 10) / 10;
}

/**
 * Calculate 3D angle (in degrees) at vertex B formed by points A, B, and C.
 */
export function calculateAngle3D(a, b, c) {
  const pA = normalizePoint(a);
  const pB = normalizePoint(b);
  const pC = normalizePoint(c);
  if (!pA || !pB || !pC || [pA.z,pB.z,pC.z].some(v=>v===null)) return null;

  const vBAx = pA.x - pB.x;
  const vBAy = pA.y - pB.y;
  const vBAz = pA.z - pB.z;

  const vBCx = pC.x - pB.x;
  const vBCy = pC.y - pB.y;
  const vBCz = pC.z - pB.z;

  const magBA = Math.sqrt(vBAx * vBAx + vBAy * vBAy + vBAz * vBAz);
  const magBC = Math.sqrt(vBCx * vBCx + vBCy * vBCy + vBCz * vBCz);

  if (magBA < 1e-9 || magBC < 1e-9) return null;

  const dot = vBAx * vBCx + vBAy * vBCy + vBAz * vBCz;
  const cosTheta = Math.max(-1, Math.min(1, dot / (magBA * magBC)));
  return Math.round(Math.acos(cosTheta) * RAD2DEG * 10) / 10;
}

/**
 * Calculate knee flexion angle (degrees).
 * By standard clinical convention:
 * - Straight standing knee (180 deg anatomical included angle) = 0 deg flexion.
 * - Right angle bend = 90 deg flexion.
 * - Deep squat (e.g. 50 deg included angle) = 130 deg flexion.
 * Returns flexion degrees [0, 180] or null if landmarks are missing.
 */
export function calculateKneeFlexion(hip, knee, ankle, use3D = false) {
  const includedAngle = use3D
    ? calculateAngle3D(hip, knee, ankle)
    : calculateAngle2D(hip, knee, ankle);

  if (includedAngle === null) return null;
  const flexion = Math.max(0, Math.min(180, 180 - includedAngle));
  return Math.round(flexion * 10) / 10;
}

/**
 * Calculate hip flexion angle (degrees).
 * Angle between torso (shoulder-hip) and thigh (hip-knee).
 * By clinical convention, standing upright = 0 deg flexion (180 deg straight).
 * Hip hinge / forward flexion = 180 - included angle.
 */
export function calculateHipAngle(shoulder, hip, knee, use3D = false) {
  const includedAngle = use3D
    ? calculateAngle3D(shoulder, hip, knee)
    : calculateAngle2D(shoulder, hip, knee);

  if (includedAngle === null) return null;
  const flexion = Math.max(0, Math.min(180, 180 - includedAngle));
  return Math.round(flexion * 10) / 10;
}

/**
 * Calculate trunk lean (in degrees) relative to vertical.
 * Coordinate convention: Y increases downwards in screen space (typical webcam/canvas).
 * Upright spine: shoulderMid is directly above hipMid (dx = 0, dy < 0, dz = 0).
 * 3D inputs must share a coordinate basis and units. Image-plane callers omit Z.
 */
export function calculateTrunkLean(shoulderMid, hipMid) {
  const s = normalizePoint(shoulderMid);
  const h = normalizePoint(hipMid);
  if (!s || !h) return null;

  const dx = s.x - h.x;
  const dy = s.y - h.y;
  const dz = s.z !== null && h.z !== null ? s.z - h.z : 0;
  const length = Math.sqrt(dx * dx + dy * dy + dz * dz);
  if (length < 1e-9) return null;

  // Inverted Y: vector from hip up to shoulder is (dx, -dy, dz)
  const upwardY = -dy;
  const cosTheta = Math.max(-1, Math.min(1, upwardY / length));
  const angle = Math.acos(cosTheta) * RAD2DEG;
  return Math.round(angle * 10) / 10;
}

/**
 * Calculate knee valgus (degrees of medial deviation).
 * Frontal plane alignment: deviation of the knee medial to the mechanical axis (hip to ankle).
 *
 * Positive value = Valgus (knees caving inward towards body midline).
 * Zero = Neutral alignment (straight mechanical axis).
 * Negative value = Varus (bow-legged).
 *
 * @param {object} hip
 * @param {object} knee
 * @param {object} ankle
 * @param {string} side - 'left' or 'right'
 * @param {number|null} midlineX - Optional X coordinate of central body axis (midpoint of hips).
 */
export function calculateKneeValgus(hip, knee, ankle, side = 'left', midlineX = null) {
  const h = normalizePoint(hip);
  const k = normalizePoint(knee);
  const a = normalizePoint(ankle);
  if (!h || !k || !a) return null;

  // Expected knee X on straight line between hip and ankle at knee's Y position
  const totalY = a.y - h.y;
  if (Math.abs(totalY) < 1e-6) return null;

  const ratio = (k.y - h.y) / totalY;
  const expectedKneeX = h.x + ratio * (a.x - h.x);
  const deviationX = k.x - expectedKneeX;

  // Thigh length for angular conversion
  const thighLen = Math.hypot(k.x - h.x, k.y - h.y);
  if (thighLen < 1e-6) return null;

  // Angle of deviation: approx arcsin(deviationX / thighLen)
  const angleDeg = Math.asin(Math.max(-1, Math.min(1, Math.abs(deviationX) / thighLen))) * RAD2DEG;

  // Determine medial direction:
  // If midlineX is known, moving toward midline is medial (valgus)
  let isMedial = false;
  if (midlineX !== null && Number.isFinite(midlineX)) {
    if (h.x < midlineX) {
      isMedial = deviationX > 0;
    } else {
      isMedial = deviationX < 0;
    }
  } else {
    // Fallback based on side convention
    const isLeft = String(side).toLowerCase().startsWith('l');
    isMedial = isLeft ? deviationX > 0 : deviationX < 0;
  }

  const signedValgus = angleDeg < 1e-6 ? 0 : (isMedial ? angleDeg : -angleDeg);
  return Math.round(signedValgus * 10) / 10;
}

/**
 * Calculate bilateral symmetry score (0 to 100%).
 * Score = 100 * max(0, 1 - |left - right| / max(|left|, |right|, epsilon))
 */
export function calculateBilateralSymmetry(leftMetric, rightMetric) {
  if (leftMetric === null || rightMetric === null ||
      !Number.isFinite(leftMetric) || !Number.isFinite(rightMetric)) {
    return null;
  }
  const l = Math.abs(leftMetric);
  const r = Math.abs(rightMetric);
  if (l === 0 && r === 0) return 100;

  const maxVal = Math.max(l, r);
  const diff = Math.abs(l - r);
  const score = Math.max(0, Math.min(100, 100 * (1 - diff / maxVal)));
  return Math.round(score * 10) / 10;
}

/**
 * Compute full instantaneous kinematics frame from a standard 33-pose or 22-marker landmark set.
 * Supports MediaPipe landmark indexing or named marker dict.
 */
export function computePoseKinematics(landmarks, image = null) {
  if (!landmarks) return null;
  if (image && (![image.width,image.height].every(v=>Number.isFinite(v)&&v>0))) return null;

  // Support both array of landmarks and named keypoint objects
  const get = (idx, name) => {
    const point = Array.isArray(landmarks) ? landmarks[idx] : landmarks[name];
    const p = normalizePoint(point);
    if (!p) return null;
    if (!image) return p;
    if (!Number.isFinite(point.visibility) || point.visibility < (image.minConfidence ?? .6) || point.visibility > 1 ||
        p.x < 0 || p.x > 1 || p.y < 0 || p.y > 1) return null;
    return {x:p.x*image.width,y:p.y*image.height,z:null};
  };

  // MediaPipe Pose landmarks standard indices:
  // 11: left_shoulder, 12: right_shoulder
  // 23: left_hip, 24: right_hip
  // 25: left_knee, 26: right_knee
  // 27: left_ankle, 28: right_ankle
  const lShoulder = get(11, 'LShoulder');
  const rShoulder = get(12, 'RShoulder');
  const lHip = get(23, 'LHip');
  const rHip = get(24, 'RHip');
  const lKnee = get(25, 'LKnee');
  const rKnee = get(26, 'RKnee');
  const lAnkle = get(27, 'LAnkle');
  const rAnkle = get(28, 'RAnkle');

  const shoulderMid = midpoint(lShoulder, rShoulder);
  const hipMid = midpoint(lHip, rHip);

  const leftKneeFlexion = calculateKneeFlexion(lHip, lKnee, lAnkle);
  const rightKneeFlexion = calculateKneeFlexion(rHip, rKnee, rAnkle);
  const leftHipAngle = calculateHipAngle(lShoulder, lHip, lKnee);
  const rightHipAngle = calculateHipAngle(rShoulder, rHip, rKnee);
  const trunkLean = calculateTrunkLean(shoulderMid, hipMid);
  const midlineX = hipMid ? hipMid.x : null;
  const leftValgus = image ? null : calculateKneeValgus(lHip, lKnee, lAnkle, 'left', midlineX);
  const rightValgus = image ? null : calculateKneeValgus(rHip, rKnee, rAnkle, 'right', midlineX);
  const kneeSymmetry = calculateBilateralSymmetry(leftKneeFlexion, rightKneeFlexion);
  const legHeight = hipMid && lAnkle && rAnkle ? Math.abs((lAnkle.y+rAnkle.y)/2-hipMid.y) : null;
  const ankleHeightDifference = legHeight > 1e-6 ? Math.abs(lAnkle.y-rAnkle.y)/legHeight : null;

  return {
    leftKneeFlexion,
    rightKneeFlexion,
    leftHipAngle,
    rightHipAngle,
    trunkLean,
    leftValgus,
    rightValgus,
    kneeSymmetry,
    ankleHeightDifference,
    shoulderMid,
    hipMid,
  };
}
