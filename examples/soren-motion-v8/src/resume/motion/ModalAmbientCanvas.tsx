import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { ambientVertexShader, ambientFragmentShader } from './modalShaders';

interface Props {
  accentColor?: string;
  reduced?: boolean;
}

export function ModalAmbientCanvas({ accentColor = '#00f5a0', reduced = false }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const uniformsRef = useRef<{
    uTime: { value: number };
    uAccentColor: { value: THREE.Color };
    uMouse: { value: THREE.Vector2 };
    uResolution: { value: THREE.Vector2 };
  }>({
    uTime: { value: 0 },
    uAccentColor: { value: new THREE.Color(accentColor) },
    uMouse: { value: new THREE.Vector2(0.5, 0.5) },
    uResolution: { value: new THREE.Vector2(1, 1) }
  });

  // Update accent color dynamically when section changes
  useEffect(() => {
    try {
      uniformsRef.current.uAccentColor.value.set(accentColor);
    } catch {
      uniformsRef.current.uAccentColor.value.set('#00f5a0');
    }
  }, [accentColor]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || reduced) return;

    let renderer: THREE.WebGLRenderer | null = null;
    let animId = 0;
    let alive = true;

    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: false,
        powerPreference: 'low-power'
      });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    } catch {
      return;
    }

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const geometry = new THREE.PlaneGeometry(2, 2);

    const material = new THREE.ShaderMaterial({
      vertexShader: ambientVertexShader,
      fragmentShader: ambientFragmentShader,
      uniforms: uniformsRef.current,
      transparent: true,
      depthTest: false,
      depthWrite: false
    });

    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);

    const onResize = () => {
      if (!canvas || !renderer) return;
      const width = canvas.parentElement?.clientWidth || window.innerWidth;
      const height = canvas.parentElement?.clientHeight || window.innerHeight;
      renderer.setSize(width, height, false);
      uniformsRef.current.uResolution.value.set(width, height);
    };

    onResize();
    window.addEventListener('resize', onResize, { passive: true });

    const onMouseMove = (e: MouseEvent) => {
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = 1.0 - (e.clientY - rect.top) / rect.height;
      uniformsRef.current.uMouse.value.set(Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y)));
    };

    window.addEventListener('mousemove', onMouseMove, { passive: true });

    let lastTime = performance.now();
    const render = (time: number) => {
      if (!alive || !renderer) return;
      const dt = (time - lastTime) * 0.001;
      lastTime = time;
      uniformsRef.current.uTime.value += Math.min(dt, 0.1);
      renderer.render(scene, camera);
      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);

    return () => {
      alive = false;
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('mousemove', onMouseMove);
      geometry.dispose();
      material.dispose();
      renderer?.dispose();
    };
  }, [reduced]);

  if (reduced) {
    return <div className="ex-modal-ambient-fallback" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', background: 'radial-gradient(circle at 50% 30%, rgba(0, 245, 160, 0.06), transparent 70%)', zIndex: 0 }} />;
  }

  return (
    <canvas
      ref={canvasRef}
      className="ex-modal-ambient-canvas"
      aria-hidden="true"
      tabIndex={-1}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 0,
        opacity: 0.95
      }}
    />
  );
}
