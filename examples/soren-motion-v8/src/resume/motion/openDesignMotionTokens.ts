/**
 * OpenDesign Motion Token Bridge
 * Synchronizes Remotion frame clocks, GSAP cubic-bezier easings,
 * and Hyperframes camera shot transitions.
 */

export interface BezierCurve {
  css: string;
  params: [number, number, number, number];
  spring: {
    mass: number;
    damping: number;
    stiffness: number;
  };
}

export const BEZIER_EXPRESSIVE: BezierCurve = {
  css: 'cubic-bezier(0.16, 1, 0.3, 1)',
  params: [0.16, 1, 0.3, 1],
  spring: {
    mass: 1,
    damping: 18,
    stiffness: 120
  }
};

export const BEZIER_KINETIC: BezierCurve = {
  css: 'cubic-bezier(0.22, 1, 0.36, 1)',
  params: [0.22, 1, 0.36, 1],
  spring: {
    mass: 0.8,
    damping: 22,
    stiffness: 180
  }
};

export const BEZIER_TECHNICAL: BezierCurve = {
  css: 'cubic-bezier(0.4, 0, 0.2, 1)',
  params: [0.4, 0, 0.2, 1],
  spring: {
    mass: 1.2,
    damping: 24,
    stiffness: 150
  }
};

export interface HyperframeShot {
  id: string;
  name: string;
  startFrame: number;
  endFrame: number;
  startTimeSec: number;
  endTimeSec: number;
  cameraPosition: [number, number, number];
  cameraTarget: [number, number, number];
  fov: number;
  easing: 'expressive' | 'kinetic' | 'technical';
}

export const SHOT_SEQUENCE: HyperframeShot[] = [
  {
    id: 'shot-01',
    name: 'Macro Bevel',
    startFrame: 0,
    endFrame: 180,
    startTimeSec: 0.0,
    endTimeSec: 3.0,
    cameraPosition: [0, 0.45, 1.2],
    cameraTarget: [0, 0.45, 0],
    fov: 32,
    easing: 'expressive'
  },
  {
    id: 'shot-02',
    name: 'Kinetic Arc',
    startFrame: 180,
    endFrame: 450,
    startTimeSec: 3.0,
    endTimeSec: 7.5,
    cameraPosition: [0.8, 0.6, 1.4],
    cameraTarget: [0.1, 0.38, 0],
    fov: 38,
    easing: 'kinetic'
  },
  {
    id: 'shot-03',
    name: 'Exploded View',
    startFrame: 450,
    endFrame: 720,
    startTimeSec: 7.5,
    endTimeSec: 12.0,
    cameraPosition: [0, 0.8, 1.8],
    cameraTarget: [0, 0.5, 0.15],
    fov: 42,
    easing: 'expressive'
  },
  {
    id: 'shot-04',
    name: 'Isometric Lock',
    startFrame: 720,
    endFrame: 900,
    startTimeSec: 12.0,
    endTimeSec: 15.0,
    cameraPosition: [1.2, 1.0, 1.2],
    cameraTarget: [0, 0.4, 0],
    fov: 30,
    easing: 'technical'
  }
];

export function secondsToFrames(seconds: number, fps = 60): number {
  return Math.round(seconds * fps);
}

export function framesToSeconds(frames: number, fps = 60): number {
  return frames / fps;
}

export function getShotForFrame(frame: number): HyperframeShot {
  const boundedFrame = Math.max(0, Math.min(900, frame));
  for (const shot of SHOT_SEQUENCE) {
    if (boundedFrame >= shot.startFrame && boundedFrame <= shot.endFrame) {
      return shot;
    }
  }
  return SHOT_SEQUENCE[SHOT_SEQUENCE.length - 1];
}
