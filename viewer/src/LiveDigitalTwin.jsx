import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Grid, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { isTargetZoneReached } from './liveDisplayHelper.js';
import { EXERCISE_TYPES } from './exerciseStateMachine.js';
import {
  AVATAR_REQUIRED_DISCLAIMER,
  AVATAR_COLLAPSED_NOTICE,
  AVATAR_CONTEXT_LOST_NOTICE,
  AVATAR_UNAVAILABLE_WEBGL_NOTICE,
  AVATAR_UNMEASURED_KINEMATICS_NOTICE,
  createContextLossManager,
  isWebGLSupported,
} from './avatarLifecycle.js';

// Major MediaPipe joints used by the HUD and 3D avatar.
const MAJOR_JOINTS = new Set([11, 12, 23, 24, 25, 26, 27, 28]);

const MP_CONNECTIONS = [
  [11, 12], // LShoulder - RShoulder
  [11, 23], // LShoulder - LHip
  [12, 24], // RShoulder - RHip
  [23, 24], // LHip - RHip
  [11, 13], [13, 15], // Left arm
  [12, 14], [14, 16], // Right arm
  [23, 25], [25, 27], [27, 31], // Left leg
  [24, 26], [26, 28], [28, 32], // Right leg
];

function getNeutralPositions() {
  const pts = Array.from({ length: 33 }, () => new THREE.Vector3(0, 0, 0));
  pts[0].set(0, 1.45, 0);
  pts[11].set(-0.18, 1.25, 0); pts[12].set(0.18, 1.25, 0);
  pts[13].set(-0.24, 0.95, 0); pts[14].set(0.24, 0.95, 0);
  pts[15].set(-0.26, 0.68, 0); pts[16].set(0.26, 0.68, 0);
  pts[23].set(-0.10, 0.85, 0); pts[24].set(0.10, 0.85, 0);
  pts[25].set(-0.11, 0.44, 0); pts[26].set(0.11, 0.44, 0);
  pts[27].set(-0.11, 0.05, 0); pts[28].set(0.11, 0.05, 0);
  pts[29].set(-0.11, 0.05, 0); pts[30].set(0.11, 0.05, 0);
  pts[31].set(-0.11, 0.02, 0.12); pts[32].set(0.11, 0.02, 0.12);
  return pts;
}

function AvatarRig({ landmarks, mirrored = true, targetROM = 80, currentDepth = null, exerciseType = EXERCISE_TYPES.SQUAT, contextLost = false }) {
  const { gl } = useThree();
  const jointsRef = useRef([]);
  const bonesRef = useRef([]);
  const up = useMemo(() => new THREE.Vector3(0, 1, 0), []);
  const vecA = useMemo(() => new THREE.Vector3(), []);
  const vecB = useMemo(() => new THREE.Vector3(), []);
  const dir = useMemo(() => new THREE.Vector3(), []);

  // Smooth lerp coordinates starting from neutral standing posture
  const currentPositions = useRef(getNeutralPositions());

  useFrame((_, delta) => {
    // If WebGL context is lost or document is hidden, halt RAF computation immediately
    if (contextLost || gl?.getContext?.()?.isContextLost?.()) return;
    if (typeof document !== 'undefined' && document.hidden) return;

    const lerpFactor = Math.min(1.0, delta * 25); // Responsive 60fps tracking

    if (landmarks && landmarks.length > 0) {
      // Map landmarks to 3D coordinate space
      for (let i = 0; i < 33; i++) {
        const p = landmarks[i];
        if (!p) continue;

        const rawX = (p.x - 0.5) * 1.8;
        const targetX = mirrored ? -rawX : rawX;
        // Invert Y so 0 is ground / hips at ~0.9m
        const targetY = (1.0 - p.y) * 1.8 - 0.1;
        const targetZ = -(p.z || 0) * 1.5;

        const curr = currentPositions.current[i];
        curr.x += (targetX - curr.x) * lerpFactor;
        curr.y += (targetY - curr.y) * lerpFactor;
        curr.z += (targetZ - curr.z) * lerpFactor;
      }
    }

    // Always update mesh positions
    for (let i = 0; i < 33; i++) {
      const jointMesh = jointsRef.current[i];
      if (jointMesh) {
        jointMesh.position.copy(currentPositions.current[i]);
      }
    }

    // Update Bone Cylinders
    MP_CONNECTIONS.forEach(([i1, i2], idx) => {
      const boneMesh = bonesRef.current[idx];
      if (!boneMesh) return;

      const pos1 = currentPositions.current[i1];
      const pos2 = currentPositions.current[i2];
      if (!pos1 || !pos2) return;

      vecA.copy(pos1);
      vecB.copy(pos2);
      dir.subVectors(vecB, vecA);
      const len = dir.length();

      if (len > 0.01) {
        boneMesh.visible = true;
        boneMesh.position.copy(vecA).add(vecB).multiplyScalar(0.5);
        boneMesh.scale.set(1, len, 1);
        boneMesh.quaternion.setFromUnitVectors(up, dir.normalize());
      } else {
        boneMesh.visible = false;
      }
    });
  });

  const inTargetZone = isTargetZoneReached(currentDepth, targetROM, exerciseType);

  return (
    <group>
      {/* 33 Joint Nodes */}
      {Array.from({ length: 33 }).map((_, i) => {
        const isMajor = MAJOR_JOINTS.has(i);
        const radius = isMajor ? 0.032 : 0.018;
        return (
          <mesh key={`joint-${i}`} ref={(el) => (jointsRef.current[i] = el)}>
            <sphereGeometry args={[radius, 16, 12]} />
            <meshStandardMaterial
              color={inTargetZone ? '#10b981' : isMajor ? '#00f3ff' : '#38bdf8'}
              emissive={inTargetZone ? '#059669' : '#0284c7'}
              emissiveIntensity={0.6}
              roughness={0.25}
              metalness={0.5}
            />
          </mesh>
        );
      })}

      {/* Bones */}
      {MP_CONNECTIONS.map(([i1, i2], idx) => (
        <mesh key={`bone-${idx}`} ref={(el) => (bonesRef.current[idx] = el)}>
          <cylinderGeometry args={[0.014, 0.014, 1, 12]} />
          <meshStandardMaterial
            color={inTargetZone ? '#34d399' : '#f59e0b'}
            metalness={0.4}
            roughness={0.3}
            emissive={inTargetZone ? '#10b981' : '#b45309'}
            emissiveIntensity={0.3}
          />
        </mesh>
      ))}
    </group>
  );
}

function CameraController({ preset, controlsRef }) {
  const { camera } = useThree();

  useEffect(() => {
    if (!preset) return;
    if (preset === 'front') {
      camera.position.set(0, 0.9, 2.8);
      controlsRef.current?.target?.set(0, 0.8, 0);
    } else if (preset === 'side') {
      camera.position.set(2.8, 0.9, 0);
      controlsRef.current?.target?.set(0, 0.8, 0);
    } else if (preset === 'iso') {
      camera.position.set(2.0, 1.4, 2.2);
      controlsRef.current?.target?.set(0, 0.8, 0);
    }
    controlsRef.current?.update();
  }, [preset, camera, controlsRef]);

  return null;
}

class TwinCanvasErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error) {
    console.warn('3D Digital Twin WebGL Canvas failed to mount:', error);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div
          className="uw-twin-unavailable-banner"
          role="status"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            minHeight: 280,
            padding: 24,
            textAlign: 'center',
            background: '#080c18',
            color: '#94a3b8',
            fontSize: '0.85rem',
            lineHeight: 1.5,
          }}
        >
          {AVATAR_UNAVAILABLE_WEBGL_NOTICE}
        </div>
      );
    }
    return this.props.children;
  }
}

export default function LiveDigitalTwin({
  landmarks,
  kinematics = null,
  mirrored = true,
  targetROM = 80,
  currentDepth = null,
  exerciseType = EXERCISE_TYPES.SQUAT,
  documentHidden = false,
  initialContextLost = false,
  webglSupported: webglSupportedProp,
  avatarVisible = true,
}) {
  const [viewAngle, setViewAngle] = useState('front');
  const [contextLost, setContextLost] = useState(initialContextLost);
  const [sceneKey, setSceneKey] = useState(0);
  const [isDocumentHidden, setIsDocumentHidden] = useState(
    typeof document !== 'undefined' ? document.hidden : Boolean(documentHidden)
  );
  const [isSupported, setIsSupported] = useState(() =>
    webglSupportedProp !== undefined ? Boolean(webglSupportedProp) : isWebGLSupported()
  );
  const controlsRef = useRef(null);
  const glRef = useRef(null);
  const canvasElementRef = useRef(null);
  const releaseListenersRef = useRef(null);

  // Sync WebGL support prop override
  useEffect(() => {
    if (webglSupportedProp !== undefined) {
      setIsSupported(Boolean(webglSupportedProp));
    }
  }, [webglSupportedProp]);

  // Sync prop changes for document visibility
  useEffect(() => {
    if (documentHidden !== undefined) {
      setIsDocumentHidden(Boolean(documentHidden));
    }
  }, [documentHidden]);

  // Sync initial context lost prop changes
  useEffect(() => {
    if (initialContextLost !== undefined) {
      setContextLost(Boolean(initialContextLost));
    }
  }, [initialContextLost]);

  // Document visibility listener to suspend RAF loop when tab is hidden
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const onVisibilityChange = () => {
      setIsDocumentHidden(document.hidden);
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  const releaseCanvas = () => {
    // Release only component-owned listeners; R3F owns renderer disposal.
    releaseListenersRef.current?.();
    releaseListenersRef.current = null;
    canvasElementRef.current = null;
    glRef.current = null;
  };

  const handleRestoreView = () => {
    // A remount request is not evidence of a healthy replacement context.
    setContextLost(true);
    releaseCanvas();
    setSceneKey(k => k + 1);
  };

  const handleCreated = ({ gl }) => {
    releaseCanvas();
    const canvas = gl?.domElement;
    if (!canvas) return;
    glRef.current = gl;
    canvasElementRef.current = canvas;
    const isCurrentCanvas = () => canvasElementRef.current === canvas && glRef.current === gl;
    const isHealthy = () => gl.getContext?.()?.isContextLost?.() === false;
    const contextManager = createContextLossManager({
      onContextLost: () => {
        if (isCurrentCanvas()) setContextLost(true);
      },
      onContextRestored: () => {
        if (isCurrentCanvas() && isHealthy()) setContextLost(false);
      },
    });
    canvas.addEventListener('webglcontextlost', contextManager.handleContextLost);
    canvas.addEventListener('webglcontextrestored', contextManager.handleContextRestored);
    releaseListenersRef.current = () => {
      canvas.removeEventListener('webglcontextlost', contextManager.handleContextLost);
      canvas.removeEventListener('webglcontextrestored', contextManager.handleContextRestored);
    };
    setContextLost(!isHealthy());
  };

  useEffect(() => {
    // No dependency cleanup: reopening may create Canvas before passive effects run.
    if (!avatarVisible || !isSupported) releaseCanvas();
  }, [avatarVisible, isSupported]);

  useEffect(() => {
    return () => releaseCanvas();
  }, []);

  const isSuspended = isDocumentHidden || documentHidden || contextLost;
  const frameloop = isSuspended ? 'never' : 'always';
  const isKinematicsMissing = currentDepth === null || kinematics === null || !landmarks || landmarks.length === 0;

  if (!avatarVisible) {
    return (
      <div
        className="uw-twin-collapsed-placeholder uw-twin-unmeasured-disclaimer-banner"
        role="status"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          minHeight: 200,
          padding: 16,
          textAlign: 'center',
          background: '#0a0f1d',
          borderRadius: 8,
          color: '#94a3b8',
          fontSize: '0.85rem',
          lineHeight: 1.5,
          border: '1px dashed rgba(255, 255, 255, 0.15)',
        }}
      >
        <div>{AVATAR_COLLAPSED_NOTICE}</div>
      </div>
    );
  }

  return (
    <div className="uw-live-twin-container" style={{ position: 'relative', width: '100%', height: '100%', minHeight: 320, background: '#0a0f1d', borderRadius: 8, overflow: 'hidden' }}>
      {isKinematicsMissing && (
        <div
          className="uw-twin-unmeasured-banner"
          role="status"
          style={{
            position: 'absolute',
            top: 12,
            left: 12,
            zIndex: 15,
            background: 'rgba(15, 23, 42, 0.85)',
            color: '#fbbf24',
            padding: '4px 10px',
            borderRadius: 6,
            border: '1px solid rgba(251, 191, 36, 0.3)',
            fontSize: '0.75rem',
            pointerEvents: 'none',
          }}
        >
          {AVATAR_UNMEASURED_KINEMATICS_NOTICE}
        </div>
      )}
      {/* 3D Viewport Controls */}
      <div
        className="uw-twin-toolbar"
        style={{
          position: 'absolute',
          top: 12,
          right: 12,
          zIndex: 15,
          display: 'flex',
          gap: 6,
          background: 'rgba(15, 23, 42, 0.85)',
          padding: '4px 8px',
          borderRadius: 6,
          border: '1px solid rgba(255, 255, 255, 0.1)',
        }}
      >
        <button
          type="button"
          className={`uw-twin-btn ${viewAngle === 'front' ? 'is-active' : ''}`}
          onClick={() => setViewAngle('front')}
          style={{
            background: viewAngle === 'front' ? '#0284c7' : 'transparent',
            color: '#ffffff',
            border: 'none',
            borderRadius: 4,
            padding: '3px 8px',
            fontSize: '0.75rem',
            cursor: 'pointer',
          }}
        >
          Front
        </button>
        <button
          type="button"
          className={`uw-twin-btn ${viewAngle === 'side' ? 'is-active' : ''}`}
          onClick={() => setViewAngle('side')}
          style={{
            background: viewAngle === 'side' ? '#0284c7' : 'transparent',
            color: '#ffffff',
            border: 'none',
            borderRadius: 4,
            padding: '3px 8px',
            fontSize: '0.75rem',
            cursor: 'pointer',
          }}
        >
          Side (Sagittal)
        </button>
        <button
          type="button"
          className={`uw-twin-btn ${viewAngle === 'iso' ? 'is-active' : ''}`}
          onClick={() => setViewAngle('iso')}
          style={{
            background: viewAngle === 'iso' ? '#0284c7' : 'transparent',
            color: '#ffffff',
            border: 'none',
            borderRadius: 4,
            padding: '3px 8px',
            fontSize: '0.75rem',
            cursor: 'pointer',
          }}
        >
          3D Orbit
        </button>
      </div>

      {!isSupported ? (
        <div
          className="uw-twin-unavailable-banner"
          role="status"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            minHeight: 280,
            padding: 24,
            textAlign: 'center',
            background: '#080c18',
            color: '#94a3b8',
            fontSize: '0.85rem',
            lineHeight: 1.5,
          }}
        >
          {AVATAR_UNAVAILABLE_WEBGL_NOTICE}
        </div>
      ) : (
        <TwinCanvasErrorBoundary>
          <Canvas
            key={`twin-canvas-${sceneKey}`}
            frameloop={frameloop}
            onCreated={handleCreated}
            camera={{ position: [0, 0.9, 2.8], fov: 45 }}
            gl={{ antialias: true, alpha: false }}
            style={{ width: '100%', height: '100%' }}
          >
            {!contextLost && (
              <>
                <color attach="background" args={['#080c18']} />
                <ambientLight intensity={0.7} />
                <directionalLight position={[5, 8, 5]} intensity={1.2} />
                <directionalLight position={[-5, 5, -5]} intensity={0.5} />

                <Grid
                  position={[0, -0.15, 0]}
                  args={[6, 6]}
                  cellSize={0.2}
                  cellThickness={0.8}
                  cellColor="#1e293b"
                  sectionSize={1.0}
                  sectionThickness={1.2}
                  sectionColor="#334155"
                  fadeDistance={5}
                />

                <AvatarRig
                  landmarks={landmarks}
                  mirrored={mirrored}
                  targetROM={targetROM}
                  currentDepth={currentDepth}
                  exerciseType={exerciseType}
                  contextLost={contextLost}
                />

                <OrbitControls
                  ref={controlsRef}
                  target={[0, 0.8, 0]}
                  minDistance={1.0}
                  maxDistance={6.0}
                  enablePan={true}
                />

                <CameraController preset={viewAngle} controlsRef={controlsRef} />
              </>
            )}
          </Canvas>

          {contextLost && (
            <div
              className="uw-twin-context-lost-overlay"
              role="status"
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(8, 12, 24, 0.92)',
                color: '#f59e0b',
                padding: 24,
                textAlign: 'center',
                fontSize: '0.85rem',
                lineHeight: 1.5,
                zIndex: 20,
              }}
            >
              <div style={{ marginBottom: 12 }}>
                {AVATAR_CONTEXT_LOST_NOTICE}
              </div>
              <button
                type="button"
                className="uw-twin-btn-restore"
                onClick={handleRestoreView}
                style={{
                  background: '#0284c7',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: 4,
                  padding: '6px 14px',
                  fontSize: '0.8rem',
                  cursor: 'pointer',
                }}
              >
                Restore 3D View
              </button>
            </div>
          )}
        </TwinCanvasErrorBoundary>
      )}

      <div
        style={{
          position: 'absolute',
          bottom: 10,
          left: 12,
          color: '#64748b',
          fontSize: '0.75rem',
          pointerEvents: 'none',
        }}
      >
        {AVATAR_REQUIRED_DISCLAIMER}
      </div>
    </div>
  );
}
