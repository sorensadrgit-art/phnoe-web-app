import React, { useEffect, useRef, useState } from 'react';
import { KinematicCanvas } from './KinematicCanvas';
import { KINEMATIC_PHASES, getKinematicFrame } from './telemetry-data';

export interface BiomechanicalLabProjectProps {
  isOpen: boolean;
  onClose: () => void;
}

export const BiomechanicalLabProject: React.FC<BiomechanicalLabProjectProps> = ({
  isOpen,
  onClose
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [activeTab, setActiveTab] = useState<'viewport' | 'telemetry' | 'attribution'>('viewport');
  const [scrubProgress, setScrubProgress] = useState(0.5);

  // Focus management and keyboard accessibility
  useEffect(() => {
    if (!isOpen) return;

    closeButtonRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const currentFrame = getKinematicFrame(scrubProgress);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="biomech-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-slate-950/80 backdrop-blur-xl animate-in fade-in duration-200"
    >
      <div
        ref={modalRef}
        className="relative w-full max-w-6xl h-[90vh] flex flex-col rounded-2xl border border-white/10 bg-[#0e131b] shadow-2xl overflow-hidden text-slate-100"
      >
        {/* Modal Header */}
        <header className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-slate-950/60">
          <div className="flex items-center gap-3">
            <span className="w-2.5 h-2.5 rounded-full bg-sky-400 animate-pulse" />
            <div>
              <h2 id="biomech-modal-title" className="text-base font-semibold tracking-wide text-white">
                Biomechanical Cybernetic Lab
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                Arcadia University DPT 2028 · Robotic Kinematics & Digital Twin
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <nav className="flex rounded-lg bg-white/5 p-1 text-xs font-mono">
              <button
                type="button"
                onClick={() => setActiveTab('viewport')}
                className={`px-3 py-1.5 rounded-md transition-colors ${
                  activeTab === 'viewport' ? 'bg-sky-500/20 text-sky-300 font-semibold' : 'text-slate-400 hover:text-white'
                }`}
              >
                3D Viewport
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('telemetry')}
                className={`px-3 py-1.5 rounded-md transition-colors ${
                  activeTab === 'telemetry' ? 'bg-sky-500/20 text-sky-300 font-semibold' : 'text-slate-400 hover:text-white'
                }`}
              >
                Telemetry Matrix
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('attribution')}
                className={`px-3 py-1.5 rounded-md transition-colors ${
                  activeTab === 'attribution' ? 'bg-sky-500/20 text-sky-300 font-semibold' : 'text-slate-400 hover:text-white'
                }`}
              >
                Attribution
              </button>
            </nav>

            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="Close project modal"
              className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </header>

        {/* Modal Body */}
        <div className="flex-1 relative overflow-hidden">
          {activeTab === 'viewport' && (
            <div className="w-full h-full relative">
              <KinematicCanvas active={isOpen} />

              {/* Kinematic Scrub Controller */}
              <div className="absolute top-4 right-4 p-4 rounded-xl border border-white/10 bg-slate-950/80 backdrop-blur-md max-w-xs font-mono text-xs">
                <p className="text-[10px] text-sky-400 uppercase tracking-wider font-semibold mb-2">Kinematic Scrub Control</p>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={scrubProgress}
                  onChange={(e) => setScrubProgress(parseFloat(e.target.value))}
                  aria-label="Kinematic trajectory progress slider"
                  className="w-full accent-sky-400 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                  <span>0% Neutral</span>
                  <span>50% Peak</span>
                  <span>100% Reset</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'telemetry' && (
            <div className="p-8 max-w-4xl mx-auto h-full overflow-y-auto space-y-6 font-mono text-xs">
              <div className="p-4 rounded-xl border border-white/10 bg-white/5 space-y-2">
                <h3 className="text-sm font-semibold text-sky-400">Clinical Movement Phase Architecture</h3>
                <p className="text-slate-400">
                  Calculated from 97-frame KineLab coordinate trajectory. Kinematics represent demonstration data.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {KINEMATIC_PHASES.map((phase) => (
                  <div key={phase.id} className="p-4 rounded-lg border border-white/10 bg-slate-900/60">
                    <p className="text-sky-300 font-bold mb-1">{phase.name}</p>
                    <p className="text-slate-400">Normalized Range: {(phase.start * 100).toFixed(0)}% – {(phase.end * 100).toFixed(0)}%</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'attribution' && (
            <div className="p-8 max-w-3xl mx-auto h-full overflow-y-auto space-y-6 text-sm">
              <h3 className="text-base font-semibold text-white">License & Attribution Statements</h3>
              <div className="p-5 rounded-xl border border-white/10 bg-slate-900/60 space-y-4 text-xs text-slate-300 leading-relaxed font-mono">
                <div>
                  <h4 className="text-sky-400 font-bold mb-1">1. BodyParts3D Joint Assembly</h4>
                  <p>Adapted anatomy geometry licensed under Creative Commons Attribution 4.0 International (CC BY 4.0).</p>
                  <p className="text-slate-500">Credit: Database Center for Life Science (DBCLS), Japan.</p>
                </div>
                <div className="border-t border-white/10 pt-4">
                  <h4 className="text-sky-400 font-bold mb-1">2. NVIDIA SimReady Assets</h4>
                  <p>Simulation-ready robotics and manipulator models licensed under Creative Commons Attribution 4.0 International (CC BY 4.0).</p>
                  <p className="text-slate-500">Credit: NVIDIA Corporation SimReady Central library.</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BiomechanicalLabProject;
