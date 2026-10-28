import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { getKinematicFrame } from './telemetry-data';
import { KinematicArcShader } from './KinematicShader';

export interface KinematicCanvasProps {
  active?: boolean;
  reducedMotion?: boolean;
  onContextLost?: () => void;
  className?: string;
}

export const KinematicCanvas: React.FC<KinematicCanvasProps> = ({
  active = true,
  reducedMotion = false,
  onContextLost,
  className = ''
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hasContextLoss, setHasContextLoss] = useState(false);
  const [currentProgress, setCurrentProgress] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let renderer: THREE.WebGLRenderer | null = null;
    let scene: THREE.Scene | null = null;
    let camera: THREE.PerspectiveCamera | null = null;
    let animId: number | null = null;

    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance'
      });

      // Strict color science & tonemapping requirements
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.05;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

      scene = new THREE.Scene();

      camera = new THREE.PerspectiveCamera(
        35, // 35 deg FOV avoids anatomy distortion
        canvas.clientWidth / canvas.clientHeight,
        0.1,
        20
      );
      camera.position.set(2.8, 2.1, 3.4);
      camera.lookAt(0, 0.45, 0);

      // Studio 3-point lighting setup
      const keyLight = new THREE.DirectionalLight(0xf8fafc, 2.2);
      keyLight.position.set(4, 6, 4);
      scene.add(keyLight);

      const fillLight = new THREE.DirectionalLight(0x334155, 0.6);
      fillLight.position.set(-4, 2, -2);
      scene.add(fillLight);

      const rimLight = new THREE.DirectionalLight(0x38bdf8, 4.5);
      rimLight.position.set(0, -2, -5);
      scene.add(rimLight);

      // Grid helper for clinical reference staging
      const grid = new THREE.GridHelper(4, 20, 0x38bdf8, 0x1e293b);
      grid.position.y = -0.01;
      scene.add(grid);

      // WebGL Context Loss safety trap
      const handleContextLost = (e: Event) => {
        e.preventDefault();
        setHasContextLoss(true);
        if (animId) cancelAnimationFrame(animId);
        onContextLost?.();
      };

      const handleContextRestored = () => {
        setHasContextLoss(false);
      };

      canvas.addEventListener('webglcontextlost', handleContextLost, false);
      canvas.addEventListener('webglcontextrestored', handleContextRestored, false);

      let startTime = performance.now();

      const animate = () => {
        if (!active) return;
        const now = performance.now();
        const elapsed = (now - startTime) / 1000;

        if (!reducedMotion) {
          const progress = (Math.sin(elapsed * 0.8) + 1) / 2;
          setCurrentProgress(progress);
        }

        renderer?.render(scene!, camera!);
        animId = requestAnimationFrame(animate);
      };

      animate();

      return () => {
        if (animId) cancelAnimationFrame(animId);
        canvas.removeEventListener('webglcontextlost', handleContextLost);
        canvas.removeEventListener('webglcontextrestored', handleContextRestored);
        renderer?.dispose();
      };
    } catch {
      setHasContextLoss(true);
    }
  }, [active, reducedMotion, onContextLost]);

  const frameData = getKinematicFrame(currentProgress);

  return (
    <div
      ref={containerRef}
      role="region"
      aria-label="Biomechanical Kinematic Viewport"
      className={`relative w-full h-full overflow-hidden bg-[#0c1017] ${className}`}
    >
      {hasContextLoss ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center text-slate-300">
          <svg className="w-16 h-16 mb-4 text-sky-400 stroke-current" fill="none" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <p className="text-sm font-mono tracking-wider uppercase text-sky-400">WebGL Hardware Fallback Mode</p>
          <p className="text-xs text-slate-500 mt-1 max-w-sm">Kinematic telemetry stream active via 2D vector instrumentation.</p>
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          role="img"
          aria-label="Biomechanical Kinematic Viewport 3D Canvas"
          className="w-full h-full block cursor-grab active:cursor-grabbing"
        />
      )}

      {/* Synchronized Heads-Up Telemetry Display */}
      <aside
        aria-label="Real-time Biomechanical Telemetry Readout"
        className="absolute bottom-4 left-4 p-3 rounded-lg border border-white/10 bg-slate-950/80 backdrop-blur-md font-mono text-xs text-slate-200 pointer-events-none"
      >
        <div className="flex items-center gap-2 mb-1.5 text-sky-400 font-semibold uppercase tracking-wider text-[10px]">
          <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
          <span>{frameData.phase}</span>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-400 tabular-nums">
          <span>Joint Angle:</span>
          <span className="text-slate-100 font-bold">{frameData.jointAngleDeg}°</span>
          <span>Angular Vel:</span>
          <span className="text-slate-100">{frameData.angularVelocity} rad/s</span>
          <span>Joint Torque:</span>
          <span className="text-slate-100">{frameData.torqueNm} N·m</span>
        </div>
      </aside>
    </div>
  );
};

export default KinematicCanvas;
