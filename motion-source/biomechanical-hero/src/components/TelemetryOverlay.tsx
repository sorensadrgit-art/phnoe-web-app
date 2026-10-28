import React from 'react';

export interface TelemetryOverlayProps {
  frame: number;
  jointAngleDeg: number;
  angularVelocity: number;
  torqueNm: number;
  shotName: string;
}

export const TelemetryOverlay: React.FC<TelemetryOverlayProps> = ({
  frame,
  jointAngleDeg,
  angularVelocity,
  torqueNm,
  shotName
}) => {
  return (
    <div className="absolute inset-0 pointer-events-none p-16 flex flex-col justify-between font-mono text-white select-none">
      {/* Top Header Bar */}
      <header className="flex justify-between items-start border-b border-white/10 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <span className="w-2.5 h-2.5 rounded-full bg-sky-400 animate-pulse" />
            <span className="text-sm tracking-widest font-bold uppercase text-sky-400">
              KineLab Biomechanical Observatory
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">Arcadia University DPT · Digital Twin Simulation</p>
        </div>

        <div className="text-right text-xs text-slate-400 tabular-nums">
          <p>SEQUENCE // TC 00:{Math.floor(frame / 60).toString().padStart(2, '0')}:{(frame % 60).toString().padStart(2, '0')}</p>
          <p className="text-sky-300 font-semibold mt-0.5">{shotName}</p>
        </div>
      </header>

      {/* Grid Coordinates & Center Reticle */}
      <div className="flex items-center justify-center">
        <div className="relative w-48 h-48 border border-white/10 rounded-full flex items-center justify-center">
          <div className="w-2 h-2 rounded-full bg-sky-400" />
          <div className="absolute top-0 w-px h-4 bg-sky-400/60" />
          <div className="absolute bottom-0 w-px h-4 bg-sky-400/60" />
          <div className="absolute left-0 h-px w-4 bg-sky-400/60" />
          <div className="absolute right-0 h-px w-4 bg-sky-400/60" />
        </div>
      </div>

      {/* Bottom Telemetry HUD */}
      <footer className="flex justify-between items-end border-t border-white/10 pt-6">
        <div className="grid grid-cols-3 gap-8 text-xs tabular-nums">
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">Joint Flexion</p>
            <p className="text-xl font-bold text-white mt-1">{jointAngleDeg.toFixed(1)}°</p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">Angular Velocity</p>
            <p className="text-xl font-bold text-sky-400 mt-1">{angularVelocity.toFixed(2)} <span className="text-xs font-normal text-slate-400">rad/s</span></p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">Torque Loading</p>
            <p className="text-xl font-bold text-amber-400 mt-1">{torqueNm.toFixed(1)} <span className="text-xs font-normal text-slate-400">N·m</span></p>
          </div>
        </div>

        <div className="text-right text-xs text-slate-500">
          <p>MODELS: NVIDIA SimReady & BodyParts3D</p>
          <p>LICENSE: CC BY 4.0 INTERNATIONAL</p>
        </div>
      </footer>
    </div>
  );
};

export default TelemetryOverlay;
