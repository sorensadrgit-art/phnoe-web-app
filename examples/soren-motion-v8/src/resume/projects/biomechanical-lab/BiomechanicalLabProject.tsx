import React, { useEffect, useRef, useState } from 'react';
import { KinematicCanvas } from './KinematicCanvas';
import { KINEMATIC_PHASES, getKinematicFrame } from './telemetry-data';
import { SHOT_SEQUENCE } from '../../motion/openDesignMotionTokens';

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
  const [activeTab, setActiveTab] = useState<'viewport' | 'telemetry' | 'folio' | 'attribution'>('viewport');
  const [selectedPlate, setSelectedPlate] = useState(0);
  const [scrubProgress, setScrubProgress] = useState(0.5);

  const plates = [
    {
      id: '01',
      title: 'Plate VIII · Translation Geometry',
      subtitle: 'The Spatial Geometry of Articulated Manifolds',
      image: import.meta.env.BASE_URL + 'assets/art/plate-01-translation-geometry.png',
      caption: 'Unified 7-DOF spatial manifold, harmonic gait epicycloids, and global terrestrial datum.'
    },
    {
      id: '02',
      title: 'Plate IX · Tibiofemoral Kinematics',
      subtitle: 'Instantaneous Helical Axes & Contact Stress Manifolds',
      image: import.meta.env.BASE_URL + 'assets/art/plate-02-tibiofemoral-kinematics.png',
      caption: 'Biological human knee articulation, sagittal ICR evolute J-curve, femoral rollback, and cruciate strain.'
    },
    {
      id: '03',
      title: 'Plate X · Cybernetic Manipulation',
      subtitle: '7-DOF Jacobian Manipulability & Singularity Hulls',
      image: import.meta.env.BASE_URL + 'assets/art/plate-03-cybernetic-manipulation.png',
      caption: 'NVIDIA SimReady Franka serial chain, Yoshikawa dexterity ellipsoids, and Cartesian velocity saturation.'
    }
  ];

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
                onClick={() => setActiveTab('folio')}
                className={`px-3 py-1.5 rounded-md transition-colors ${
                  activeTab === 'folio' ? 'bg-sky-500/20 text-sky-300 font-semibold' : 'text-slate-400 hover:text-white'
                }`}
              >
                Archival Folio
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
                <p className="text-sky-400 font-bold uppercase tracking-wider text-[10px]">Real-Time Joint Telemetry</p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-2">
                  <div>
                    <span className="text-slate-500 block">Current Phase:</span>
                    <span className="text-white font-semibold">{currentFrame.phase}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Joint Flexion:</span>
                    <span className="text-white font-semibold">{currentFrame.jointAngleDeg.toFixed(2)}°</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Angular Velocity:</span>
                    <span className="text-white font-semibold">{currentFrame.angularVelocity.toFixed(2)} rad/s</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Dynamic Torque:</span>
                    <span className="text-white font-semibold">{currentFrame.torqueNm.toFixed(2)} Nm</span>
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                <p className="text-sky-400 font-semibold uppercase tracking-wider text-[10px]">OpenDesign Cinematic Motion Sequence (1440p60)</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {SHOT_SEQUENCE.map((shot) => (
                    <div key={shot.id} className="p-3 rounded-lg border border-white/10 bg-slate-900/60 font-mono">
                      <div className="flex justify-between items-baseline mb-1">
                        <span className="text-white font-bold">{shot.name}</span>
                        <span className="text-[10px] text-sky-400">Frames {shot.startFrame}–{shot.endFrame} ({shot.startTimeSec.toFixed(1)}s–{shot.endTimeSec.toFixed(1)}s)</span>
                      </div>
                      <p className="text-[11px] text-slate-400">FOV: {shot.fov}° · Easing: {shot.easing} · Camera: [{shot.cameraPosition.join(', ')}]</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                <p className="text-slate-400 font-semibold uppercase tracking-wider text-[10px]">Movement Sequence Phases</p>
                {KINEMATIC_PHASES.map((phase) => (
                  <div key={phase.name} className="p-3 rounded-lg border border-white/5 bg-slate-900/40">
                    <p className="text-sky-300 font-bold mb-1">{phase.name}</p>
                    <p className="text-slate-400">Normalized Range: {(phase.start * 100).toFixed(0)}% – {(phase.end * 100).toFixed(0)}%</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'folio' && (
            <div className="p-6 max-w-5xl mx-auto h-full overflow-y-auto flex flex-col space-y-4">
              <div className="flex items-center justify-between pb-2 border-b border-white/10">
                <div className="flex gap-2">
                  {plates.map((p, idx) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setSelectedPlate(idx)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-colors ${
                        selectedPlate === idx
                          ? 'bg-sky-500/20 text-sky-300 border border-sky-400/30 font-semibold'
                          : 'bg-white/5 text-slate-400 hover:text-white'
                      }`}
                    >
                      {p.id} · {p.title.split('·')[1]?.trim()}
                    </button>
                  ))}
                </div>

                <a
                  href={import.meta.env.BASE_URL + 'assets/art/kinematic-monism-trilogy.pdf'}
                  download="kinematic-monism-trilogy.pdf"
                  className="px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 text-xs font-mono transition-colors inline-flex items-center gap-1.5"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download 3-Page Archival Folio (PDF)
                </a>
              </div>

              {/* Active Plate Display */}
              <div className="flex-1 flex flex-col lg:flex-row gap-6 items-center justify-center p-4 rounded-xl border border-white/10 bg-slate-950/60 overflow-hidden">
                <div className="w-full lg:w-3/5 max-h-[56vh] flex items-center justify-center overflow-hidden rounded-lg border border-white/10 bg-black/60 shadow-inner">
                  <img
                    src={plates[selectedPlate].image}
                    alt={plates[selectedPlate].title}
                    className="object-contain max-h-[56vh] w-auto transition-transform hover:scale-105 duration-300"
                  />
                </div>

                <div className="w-full lg:w-2/5 space-y-3 font-mono text-xs">
                  <div className="inline-block px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 text-[10px] font-semibold border border-sky-500/20">
                    FINE ART FOLIO EDITION · 1 OF 3
                  </div>
                  <h3 className="text-base font-bold text-white tracking-wide">
                    {plates[selectedPlate].title}
                  </h3>
                  <p className="text-amber-300/90 text-xs font-semibold">
                    {plates[selectedPlate].subtitle}
                  </p>
                  <p className="text-slate-400 text-xs leading-relaxed">
                    {plates[selectedPlate].caption}
                  </p>
                  <div className="p-3 rounded-lg border border-white/5 bg-white/5 text-[10px] text-slate-400 space-y-1">
                    <p><span className="text-slate-300">Aesthetic Movement:</span> Kinematic Monism</p>
                    <p><span className="text-slate-300">Format:</span> 300 DPI Fine Art Folio (18" × 24" vector & raster)</p>
                    <p><span className="text-slate-300">Licensing:</span> CC BY 4.0 DBCLS & NVIDIA SimReady Central</p>
                  </div>
                </div>
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
                <div className="border-t border-white/10 pt-4">
                  <h4 className="text-sky-400 font-bold mb-1">3. Kinematic Monism Art Trilogy</h4>
                  <p>Original fine art plates and visual philosophy created under Creative Commons Attribution 4.0 International (CC BY 4.0).</p>
                  <p className="text-slate-500">Designed via the Kinematic Monism visual philosophy for the SOREN Living Résumé.</p>
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
