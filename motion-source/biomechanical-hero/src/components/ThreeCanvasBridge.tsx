import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

export interface ThreeCanvasBridgeProps {
  frame: number;
  width?: number;
  height?: number;
}

export const ThreeCanvasBridge: React.FC<ThreeCanvasBridgeProps> = ({
  frame,
  width = 2560,
  height = 1440
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const jointGroupRef = useRef<THREE.Group | null>(null);
  const tibiaMeshRef = useRef<THREE.Mesh | null>(null);

  // Initialize Three.js scene once
  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: true,
        powerPreference: 'high-performance'
      });
      renderer.setPixelRatio(1);
      renderer.setSize(width, height);
      rendererRef.current = renderer;
    } catch {
      return;
    }

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(35, width / height, 0.1, 100);
    camera.position.set(0, 0.45, 1.4);
    camera.lookAt(0, 0.45, 0);
    cameraRef.current = camera;

    // Ambient and directional lighting for cybernetic titanium materials
    const ambientLight = new THREE.AmbientLight(0x0e1726, 2.5);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0x00f5a0, 3.2);
    keyLight.position.set(2, 3, 2);
    scene.add(keyLight);

    const rimLight = new THREE.DirectionalLight(0x38ef7d, 2.0);
    rimLight.position.set(-2, 1, -2);
    scene.add(rimLight);

    // Build Biomechanical Knee Joint Architecture
    const jointGroup = new THREE.Group();
    jointGroup.position.set(0, 0.4, 0);
    jointGroupRef.current = jointGroup;
    scene.add(jointGroup);

    const titaniumMat = new THREE.MeshStandardMaterial({
      color: 0x1a2332,
      metalness: 0.92,
      roughness: 0.18,
      wireframe: false
    });

    const phosphorGlowMat = new THREE.MeshStandardMaterial({
      color: 0x00f5a0,
      emissive: 0x00f5a0,
      emissiveIntensity: 0.6,
      metalness: 0.8,
      roughness: 0.2
    });

    // Femoral Shaft
    const femurGeo = new THREE.CylinderGeometry(0.04, 0.05, 0.45, 24);
    const femurMesh = new THREE.Mesh(femurGeo, titaniumMat);
    femurMesh.position.set(0, 0.25, 0);
    jointGroup.add(femurMesh);

    // Condylar Pivot
    const condyleGeo = new THREE.SphereGeometry(0.07, 24, 24);
    const condyleMesh = new THREE.Mesh(condyleGeo, phosphorGlowMat);
    condyleMesh.position.set(0, 0, 0);
    jointGroup.add(condyleMesh);

    // Tibial Shaft (Rotates with flexion/extension)
    const tibiaGeo = new THREE.CylinderGeometry(0.045, 0.035, 0.45, 24);
    const tibiaMesh = new THREE.Mesh(tibiaGeo, titaniumMat);
    tibiaMesh.position.set(0, -0.25, 0);
    tibiaMeshRef.current = tibiaMesh;
    jointGroup.add(tibiaMesh);

    return () => {
      femurGeo.dispose();
      condyleGeo.dispose();
      tibiaGeo.dispose();
      titaniumMat.dispose();
      phosphorGlowMat.dispose();
      renderer.dispose();
    };
  }, [width, height]);

  // Deterministic per-frame update driven by Remotion frame clock (NO RAF loop!)
  useEffect(() => {
    const renderer = rendererRef.current;
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    const jointGroup = jointGroupRef.current;
    const tibiaMesh = tibiaMeshRef.current;

    if (!renderer || !scene || !camera || !jointGroup) return;

    // Shot timing calculations based on 900-frame (15s @ 60fps) timeline
    const progress = Math.max(0, Math.min(1, frame / 900));
    const flexionAngle = (Math.sin(progress * Math.PI) * 98.4 * Math.PI) / 180;

    // Rotate joint components deterministically
    jointGroup.rotation.y = progress * Math.PI * 1.5;
    if (tibiaMesh) {
      tibiaMesh.rotation.x = -flexionAngle;
    }

    // Dynamic Camera Shot Interpolation
    if (frame < 180) {
      // Shot 01: Macro Bevel
      const p = frame / 180;
      camera.position.set(0, 0.45 + p * 0.05, 1.2 - p * 0.1);
      camera.fov = 32;
    } else if (frame < 450) {
      // Shot 02: Kinetic Arc
      const p = (frame - 180) / 270;
      camera.position.set(Math.sin(p * Math.PI * 0.5) * 1.0, 0.5 + p * 0.1, 1.1);
      camera.fov = 38;
    } else if (frame < 720) {
      // Shot 03: Exploded View
      const p = (frame - 450) / 270;
      camera.position.set(0, 0.7 + p * 0.15, 1.6 - p * 0.1);
      camera.fov = 42;
    } else {
      // Shot 04: Isometric Lock
      camera.position.set(1.2, 1.0, 1.2);
      camera.fov = 30;
    }

    camera.updateProjectionMatrix();
    camera.lookAt(0, 0.4, 0);

    // Deterministic single-frame execution
    renderer.render(scene, camera);
  }, [frame]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="absolute inset-0 w-full h-full object-cover pointer-events-none"
    />
  );
};
