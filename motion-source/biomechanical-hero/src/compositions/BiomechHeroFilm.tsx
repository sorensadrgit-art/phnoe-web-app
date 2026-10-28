import React from 'react';
import { useCurrentFrame, useVideoConfig } from 'remotion';
import { getActiveShot, BIOMECH_HERO_CONFIG } from './BiomechHeroFilm.mjs';
import { TelemetryOverlay } from '../components/TelemetryOverlay';
import { ThreeCanvasBridge } from '../components/ThreeCanvasBridge';

export const BiomechHeroComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const progress = frame / durationInFrames;
  const currentShot = getActiveShot(frame);

  const jointAngleDeg = Math.sin(progress * Math.PI) * 98.4;
  const angularVelocity = Math.cos(progress * Math.PI) * Math.PI * (98.4 * (Math.PI / 180));
  const torqueNm = Math.sin(progress * Math.PI * 2) * 38.6 + Math.sin(progress * Math.PI) * 16.4;

  return (
    <div className="relative w-full h-full bg-[#0a0d14] overflow-hidden">
      {/* Cinematic Viewport Canvas Backdrop */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="w-full h-full bg-gradient-to-tr from-black via-slate-950 to-slate-900" />
      </div>

      {/* Deterministic Three.js WebGL 3D Mesh Engine */}
      <ThreeCanvasBridge frame={frame} />

      {/* Synchronized Telemetry Graphic Overlay */}
      <TelemetryOverlay
        frame={frame}
        jointAngleDeg={jointAngleDeg}
        angularVelocity={angularVelocity}
        torqueNm={torqueNm}
        shotName={currentShot.name}
      />
    </div>
  );
};

export default BiomechHeroComposition;
