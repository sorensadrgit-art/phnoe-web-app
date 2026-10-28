/**
 * Hero Film Composition Configuration & Shot Sequencer
 * 2560x1440 (1440p) @ 60fps — 15 seconds (900 frames)
 */

export const BIOMECH_HERO_CONFIG = {
  id: 'BiomechHeroFilm',
  fps: 60,
  durationInFrames: 900,
  width: 2560,
  height: 1440,
  colorSpace: 'srgb',
  codec: 'h264'
};

export const FILM_SHOTS = [
  {
    id: 'shot-01-macro-bevel',
    name: 'Macro Bevel & Telemetry Awake',
    startFrame: 0,
    endFrame: 180,
    durationFrames: 180,
    camera: {
      type: 'dolly-macro',
      fov: 28,
      startPos: [0.12, 0.45, 0.35],
      endPos: [0.22, 0.48, 0.42],
      lookAt: [0.05, 0.42, 0.10],
      aperture: 2.8 // Shallow depth of field
    },
    lighting: {
      keyIntensity: 1.8,
      cyanRimIntensity: 5.5
    }
  },
  {
    id: 'shot-02-kinetic-arc',
    name: 'Synchronized Kinetic Arc',
    startFrame: 180,
    endFrame: 480,
    durationFrames: 300,
    camera: {
      type: 'orbit-tracking',
      fov: 35,
      startPos: [2.5, 1.8, 3.2],
      endPos: [3.2, 2.2, 1.8],
      lookAt: [0, 0.45, 0],
      aperture: 5.6
    },
    lighting: {
      keyIntensity: 2.4,
      cyanRimIntensity: 4.2
    }
  },
  {
    id: 'shot-03-exploded-view',
    name: 'Diagnostic Exploded View',
    startFrame: 480,
    endFrame: 720,
    durationFrames: 240,
    camera: {
      type: 'radial-pan',
      fov: 40,
      startPos: [0, 3.5, 3.5],
      endPos: [-1.8, 2.5, 3.2],
      lookAt: [0, 0.5, 0],
      aperture: 8.0 // Deep focus across exploded layers
    },
    lighting: {
      keyIntensity: 2.8,
      cyanRimIntensity: 6.0
    }
  },
  {
    id: 'shot-04-isometric-lock',
    name: 'Isometric Lock & Title Resolution',
    startFrame: 720,
    endFrame: 900,
    durationFrames: 180,
    camera: {
      type: 'isometric-hero-lock',
      fov: 32,
      startPos: [2.8, 2.1, 3.4],
      endPos: [2.8, 2.1, 3.4],
      lookAt: [0, 0.45, 0],
      aperture: 4.0
    },
    lighting: {
      keyIntensity: 2.2,
      cyanRimIntensity: 4.5
    }
  }
];

export function getActiveShot(frame) {
  return FILM_SHOTS.find(s => frame >= s.startFrame && frame < s.endFrame) || FILM_SHOTS[FILM_SHOTS.length - 1];
}
