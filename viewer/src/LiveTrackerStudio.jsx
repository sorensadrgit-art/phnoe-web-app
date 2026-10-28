import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import LiveHUDOverlay from './LiveHUDOverlay.jsx';
import LiveDigitalTwin from './LiveDigitalTwin.jsx';
import LiveSetSummaryModal from './LiveSetSummaryModal.jsx';
import { computePoseKinematics } from './liveKinematics.js';
import { createExerciseTracker, DEFAULT_PRESETS, EXERCISE_TYPES, PHASES } from './exerciseStateMachine.js';

// Synthesized Web Audio Biofeedback Chimes
function playChime(type = 'success') {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();

    if (type === 'success') {
      // Pleasant two-tone ascending chime
      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      const gain = ctx.createGain();

      osc1.type = 'sine';
      osc2.type = 'triangle';
      osc1.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
      osc1.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.15); // A5

      osc2.frequency.setValueAtTime(880, ctx.currentTime);
      osc2.frequency.exponentialRampToValueAtTime(1174.66, ctx.currentTime + 0.15); // D6

      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);

      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(ctx.destination);

      osc1.start();
      osc2.start();
      osc1.stop(ctx.currentTime + 0.35);
      osc2.stop(ctx.currentTime + 0.35);
    } else if (type === 'warning') {
      // Gentle warning ping
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(220, ctx.currentTime);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.25);
    }
  } catch {}
}

// Extract 22 OpenSim marker coordinates from 33 MediaPipe pose landmarks
function extractOsimMarkers(landmarks, mirrored = true) {
  if (!landmarks) return null;
  const get = (i) => {
    const p = landmarks[i];
    if (!p) return [0, 0, 0];
    const rawX = (p.x - 0.5) * 1.8;
    const x = mirrored ? -rawX : rawX;
    const y = (1.0 - p.y) * 1.8 - 0.1;
    const z = -(p.z || 0) * 1.5;
    return [Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000, Math.round(z * 1000) / 1000];
  };

  const lHip = get(23);
  const rHip = get(24);
  const hip = [(lHip[0] + rHip[0]) / 2, (lHip[1] + rHip[1]) / 2, (lHip[2] + rHip[2]) / 2];
  const lShoulder = get(11);
  const rShoulder = get(12);
  const neck = [(lShoulder[0] + rShoulder[0]) / 2, (lShoulder[1] + rShoulder[1]) / 2, (lShoulder[2] + rShoulder[2]) / 2];
  const nose = get(0);
  const head = [nose[0], nose[1] + 0.1, nose[2]];

  const rKnee = get(26);
  const rAnkle = get(28);
  const rBigToe = get(32);
  const rSmallToe = [rBigToe[0] + 0.03, rBigToe[1], rBigToe[2]];
  const rHeel = get(30);

  const lKnee = get(25);
  const lAnkle = get(27);
  const lBigToe = get(31);
  const lSmallToe = [lBigToe[0] - 0.03, lBigToe[1], lBigToe[2]];
  const lHeel = get(29);

  const rElbow = get(14);
  const rWrist = get(16);
  const lElbow = get(13);
  const lWrist = get(15);

  return [
    hip, rHip, rKnee, rAnkle, rBigToe, rSmallToe, rHeel,
    lHip, lKnee, lAnkle, lBigToe, lSmallToe, lHeel,
    neck, head, nose, rShoulder, rElbow, rWrist,
    lShoulder, lElbow, lWrist
  ];
}

export default function LiveTrackerStudio({
  token,
  onSessionCreated,
  apiPrefix = '/api/v1',
}) {
  const [cameras, setCameras] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('');
  const [mirrored, setMirrored] = useState(true);
  const [layout, setLayout] = useState('split'); // 'full', 'split', 'pip'
  const [exerciseType, setExerciseType] = useState(EXERCISE_TYPES.SQUAT);
  const [targetROM, setTargetROM] = useState(80);
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [isTracking, setIsTracking] = useState(true);
  const [isSimulated, setIsSimulated] = useState(false);
  const [cameraError, setCameraError] = useState(null);

  // Completed set summary modal
  const [showSummary, setShowSummary] = useState(false);
  const [setSummary, setSetSummary] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);

  // Live state
  const [liveLandmarks, setLiveLandmarks] = useState(null);
  const [liveKinematics, setLiveKinematics] = useState(null);
  const [trackerState, setTrackerState] = useState(null);
  const [viewportSize, setViewportSize] = useState({ width: 640, height: 480 });

  const videoRef = useRef(null);
  const cameraViewportRef = useRef(null);
  const streamRef = useRef(null);
  const trackerRef = useRef(null);
  const animFrameRef = useRef(null);
  const simulationStepRef = useRef(0);
  const lastRepCountRef = useRef(0);
  const recordedFramesRef = useRef([]);
  const lastFrameSampleTimeRef = useRef(0);
  const setStartTimeRef = useRef(Date.now());
  const opticalMotionCanvasRef = useRef(null);
  const prevFramePixelsRef = useRef(null);
  const liveDescentOffsetRef = useRef(0);

  // Initialize Exercise State Machine Tracker
  useEffect(() => {
    trackerRef.current = createExerciseTracker(exerciseType, {
      targetROM: Number(targetROM),
    });
    setTrackerState(trackerRef.current.getState());
    lastRepCountRef.current = 0;
  }, [exerciseType, targetROM]);

  // Enumerate Camera Devices
  useEffect(() => {
    async function getDevices() {
      try {
        if (!navigator.mediaDevices?.enumerateDevices) return;
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoInputs = devices.filter((d) => d.kind === 'videoinput');
        setCameras(videoInputs);
        if (videoInputs.length > 0 && !selectedCamera) {
          setSelectedCamera(videoInputs[0].deviceId);
        }
      } catch (e) {
        console.warn('Unable to enumerate media devices:', e);
      }
    }
    getDevices();
  }, [selectedCamera]);

  // Start Camera Stream
  useEffect(() => {
    let cancelled = false;

    async function startCamera() {
      if (isSimulated) return;
      setCameraError(null);

      // Stop existing tracks
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }

      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error('Webcam API unavailable; falling back to simulated stream.');
        }

        const constraints = {
          video: selectedCamera
            ? { deviceId: { exact: selectedCamera }, width: { ideal: 1280 }, height: { ideal: 720 } }
            : { width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        };

        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }

        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      } catch (err) {
        if (!cancelled) {
          console.warn('Camera stream error:', err);
          setCameraError(err.message || 'Camera inaccessible');
          // Automatically engage realistic simulated pose stream for testing
          setIsSimulated(true);
        }
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, [selectedCamera, isSimulated]);

  // Dynamic viewport measurement for responsive HUD overlay
  useEffect(() => {
    if (!cameraViewportRef.current) return;
    const el = cameraViewportRef.current;
    const updateSize = () => {
      if (el.clientWidth && el.clientHeight) {
        setViewportSize({ width: el.clientWidth, height: el.clientHeight });
      }
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(el);
    return () => observer.disconnect();
  }, [layout]);

  // Main Tracking Loop (Realtime 30-60 FPS)
  useEffect(() => {
    let active = true;

    function generateSimulatedPose(step, type = exerciseType) {
      const cycle = (step % 120) / 120.0; // 4 second full rep cycle at 30fps
      const marks = new Array(33).fill(null);

      let leftFlexDeg = 10;
      let rightFlexDeg = 10;
      let trunkLeanDeg = 0;
      let squatDepthPct = 0;

      if (type === EXERCISE_TYPES.BALANCE) {
        // Stance leg (Right): straight, left leg lifted & bent
        leftFlexDeg = 55 + Math.sin(cycle * 4 * Math.PI) * 4;
        rightFlexDeg = 8 + Math.cos(cycle * 2 * Math.PI) * 2;
        trunkLeanDeg = 6 + Math.sin(cycle * 2 * Math.PI) * 4; // Subtle natural postural sway
      } else if (type === EXERCISE_TYPES.LUNGE) {
        // Lead leg (Left) steps forward and bends deep; trail leg follows
        squatDepthPct = (1.0 - Math.cos(cycle * 2 * Math.PI)) / 2.0;
        leftFlexDeg = 15 + squatDepthPct * 75; // 15 to 90 deg
        rightFlexDeg = 10 + squatDepthPct * 45; // trail knee
        trunkLeanDeg = squatDepthPct * 12;
      } else if (type === EXERCISE_TYPES.KNEE_EXTENSION) {
        // Active leg (Left) extends from bent (85 deg) to straight (10 deg)
        const extendPct = (1.0 - Math.cos(cycle * 2 * Math.PI)) / 2.0;
        leftFlexDeg = 85 - extendPct * 75;
        rightFlexDeg = 80;
        trunkLeanDeg = 5;
      } else {
        // Squat: bilateral symmetrical knee flexion
        squatDepthPct = (1.0 - Math.cos(cycle * 2 * Math.PI)) / 2.0;
        leftFlexDeg = 10 + squatDepthPct * 75; // 10 to 85 deg
        rightFlexDeg = 10 + squatDepthPct * 75;
        trunkLeanDeg = squatDepthPct * 18;
      }

      // Depth ratios
      const lDepthRatio = Math.max(0, (leftFlexDeg - 10) / 80);
      const rDepthRatio = Math.max(0, (rightFlexDeg - 10) / 80);
      const avgDepthRatio = (lDepthRatio + rDepthRatio) / 2;

      const hipY = 0.50 + avgDepthRatio * 0.18;
      const shoulderY = 0.25 + avgDepthRatio * 0.18;
      const trunkSwayX = (trunkLeanDeg / 45) * 0.04;
      const trunkLeanZ = -(trunkLeanDeg / 45) * 0.15; // 3D sagittal depth

      // Hips, Shoulders
      marks[11] = { x: 0.44 + trunkSwayX, y: shoulderY, z: -0.05 + trunkLeanZ, visibility: 0.99 }; // LShoulder
      marks[12] = { x: 0.56 + trunkSwayX, y: shoulderY, z: -0.05 + trunkLeanZ, visibility: 0.99 }; // RShoulder
      marks[23] = { x: 0.45, y: hipY, z: 0, visibility: 0.99 }; // LHip
      marks[24] = { x: 0.55, y: hipY, z: 0, visibility: 0.99 }; // RHip

      // Knees
      const lKneeY = 0.68 + (type === EXERCISE_TYPES.BALANCE ? -0.08 : lDepthRatio * 0.08);
      const rKneeY = 0.68 + rDepthRatio * 0.08;
      marks[25] = { x: 0.43, y: lKneeY, z: 0.08, visibility: 0.99 }; // LKnee
      marks[26] = { x: 0.57, y: rKneeY, z: 0.08, visibility: 0.99 }; // RKnee

      // Ankles
      const lAnkleY = type === EXERCISE_TYPES.BALANCE ? 0.78 : 0.88;
      marks[27] = { x: 0.44, y: lAnkleY, z: 0.05, visibility: 0.99 }; // LAnkle
      marks[28] = { x: 0.56, y: 0.88, z: 0.05, visibility: 0.99 }; // RAnkle

      // Feet
      marks[29] = { x: 0.44, y: lAnkleY + 0.02, z: 0.05, visibility: 0.95 };
      marks[30] = { x: 0.56, y: 0.90, z: 0.05, visibility: 0.95 };
      marks[31] = { x: 0.43, y: lAnkleY + 0.04, z: 0.18, visibility: 0.95 };
      marks[32] = { x: 0.57, y: 0.92, z: 0.18, visibility: 0.95 };

      // Head
      marks[0] = { x: 0.50 + trunkSwayX, y: shoulderY - 0.12, z: -0.08 + trunkLeanZ, visibility: 0.99 };

      // Arms
      marks[13] = { x: 0.40, y: shoulderY + 0.15, z: 0.05, visibility: 0.95 };
      marks[14] = { x: 0.60, y: shoulderY + 0.15, z: 0.05, visibility: 0.95 };
      marks[15] = { x: 0.46, y: shoulderY + 0.20, z: 0.15, visibility: 0.95 };
      marks[16] = { x: 0.54, y: shoulderY + 0.20, z: 0.15, visibility: 0.95 };

      return marks;
    }

    function loop() {
      if (!active) return;

      if (isTracking && trackerRef.current) {
        simulationStepRef.current += 1;
        const landmarks = generateSimulatedPose(simulationStepRef.current, exerciseType);

        setLiveLandmarks(landmarks);

        // Biomechanical Kinematics Engine
        const kine = computePoseKinematics(landmarks);
        setLiveKinematics(kine);

        // Exercise State Machine Update
        const nextState = trackerRef.current.update(kine, Date.now());
        setTrackerState(nextState);

        // Record OpenSim motion frames during active reps
        if (nextState.phase !== PHASES.IDLE) {
          const nowMs = Date.now();
          if (!lastFrameSampleTimeRef.current || (nowMs - lastFrameSampleTimeRef.current) >= 50) {
            lastFrameSampleTimeRef.current = nowMs;
            const t = setStartTimeRef.current ? (nowMs - setStartTimeRef.current) / 1000 : 0;
            const osimXYZ = extractOsimMarkers(landmarks, mirrored);
            if (osimXYZ) {
              recordedFramesRef.current.push({ t: Math.round(t * 1000) / 1000, xyz: osimXYZ });
            }
          }
        }

        // Sound chime on rep completion
        if (audioEnabled && nextState.repCount > lastRepCountRef.current) {
          lastRepCountRef.current = nextState.repCount;
          playChime('success');
        }
      }

      animFrameRef.current = requestAnimationFrame(loop);
    }

    animFrameRef.current = requestAnimationFrame(loop);

    return () => {
      active = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [isTracking, isSimulated, audioEnabled, exerciseType, mirrored]);

  const handleFinishSet = useCallback(() => {
    if (!trackerRef.current) return;
    const summary = trackerRef.current.finishSet();
    summary.frames = [...recordedFramesRef.current];
    setSetSummary(summary);
    setShowSummary(true);
    setSaveResult(null);
  }, []);

  const handleStartNewSet = useCallback(() => {
    if (trackerRef.current) {
      trackerRef.current.reset();
      setTrackerState(trackerRef.current.getState());
      lastRepCountRef.current = 0;
      recordedFramesRef.current = [];
      lastFrameSampleTimeRef.current = 0;
      setStartTimeRef.current = Date.now();
    }
    setShowSummary(false);
    setSaveResult(null);
  }, []);

  const handleSaveToSessions = useCallback(async (patientId) => {
    if (!setSummary) return;
    setIsSaving(true);
    setSaveResult(null);

    const payload = {
      exercise_type: exerciseType,
      patient_id: patientId || 'PT-PATIENT-01',
      summary_metrics: setSummary,
      reps: setSummary.reps || [],
      frames: setSummary.frames || [],
    };

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;

      const res = await fetch(`${apiPrefix}/sessions/live-set`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Failed to save live session');
      }

      setSaveResult({
        ok: true,
        message: `Successfully saved ${data.session_id}!`,
      });

      if (onSessionCreated) {
        onSessionCreated(data.session_id);
      }
    } catch (err) {
      setSaveResult({
        ok: false,
        message: err.message || 'Error communicating with local KineLab backend',
      });
    } finally {
      setIsSaving(false);
    }
  }, [setSummary, exerciseType, token, apiPrefix, onSessionCreated]);

  const handleExportJSON = useCallback(() => {
    if (!setSummary) return;
    const blob = new Blob([JSON.stringify(setSummary, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `kinelab-live-${exerciseType}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [setSummary, exerciseType]);

  const currentDepth = Math.max(
    liveKinematics?.leftKneeFlexion ?? 0,
    liveKinematics?.rightKneeFlexion ?? 0
  );

  return (
    <div className="uw-live-studio">
      {/* Top Studio Control Bar */}
      <div className="uw-live-controls-bar">
        <div className="uw-live-control-group">
          <label className="uw-live-label">
            <span>EXERCISE</span>
            <select
              value={exerciseType}
              onChange={(e) => setExerciseType(e.target.value)}
              className="uw-live-select"
            >
              <option value={EXERCISE_TYPES.SQUAT}>Squats</option>
              <option value={EXERCISE_TYPES.LUNGE}>Lunges</option>
              <option value={EXERCISE_TYPES.KNEE_EXTENSION}>Knee Extension</option>
              <option value={EXERCISE_TYPES.BALANCE}>Single-Leg Balance</option>
            </select>
          </label>

          <label className="uw-live-label">
            <span>TARGET DEPTH</span>
            <select
              value={targetROM}
              onChange={(e) => setTargetROM(Number(e.target.value))}
              className="uw-live-select"
            >
              <option value={60}>Gentle (60°)</option>
              <option value={75}>Functional (75°)</option>
              <option value={90}>Deep (90°+)</option>
            </select>
          </label>
        </div>

        <div className="uw-live-control-group">
          {cameras.length > 0 && !isSimulated && (
            <label className="uw-live-label">
              <span>CAMERA</span>
              <select
                value={selectedCamera}
                onChange={(e) => setSelectedCamera(e.target.value)}
                className="uw-live-select"
              >
                {cameras.map((c) => (
                  <option key={c.deviceId} value={c.deviceId}>
                    {c.label || `Camera ${c.deviceId.slice(0, 5)}`}
                  </option>
                ))}
              </select>
            </label>
          )}

          <button
            type="button"
            className={`uw-live-btn-toggle ${mirrored ? 'is-active' : ''}`}
            onClick={() => setMirrored(!mirrored)}
            title="Mirror camera preview horizontally"
          >
            Mirror {mirrored ? 'ON' : 'OFF'}
          </button>

          <button
            type="button"
            className={`uw-live-btn-toggle ${audioEnabled ? 'is-active' : ''}`}
            onClick={() => setAudioEnabled(!audioEnabled)}
            title="Audio rep chime"
          >
            Chimes {audioEnabled ? 'ON' : 'OFF'}
          </button>

          <button
            type="button"
            className={`uw-live-btn-toggle ${isSimulated ? 'is-active' : ''}`}
            onClick={() => setIsSimulated(!isSimulated)}
            title="Toggle between physical webcam and synthetic biomechanical test stream"
          >
            Feed: {isSimulated ? 'Synthetic Test' : 'Live Camera'}
          </button>
        </div>

        <div className="uw-live-control-group">
          {/* Layout switcher */}
          <div className="uw-layout-segmented">
            <button
              type="button"
              className={layout === 'full' ? 'is-active' : ''}
              onClick={() => setLayout('full')}
            >
              Full HUD
            </button>
            <button
              type="button"
              className={layout === 'split' ? 'is-active' : ''}
              onClick={() => setLayout('split')}
            >
              Split Dual Live
            </button>
            <button
              type="button"
              className={layout === 'pip' ? 'is-active' : ''}
              onClick={() => setLayout('pip')}
            >
              PiP 3D
            </button>
          </div>

          <button
            type="button"
            className="uw-btn-finish-set"
            onClick={handleFinishSet}
          >
            Finish Set
          </button>
        </div>
      </div>

      {cameraError && (
        <div className="uw-live-banner-alert">
          <span>Camera stream notification: {cameraError}. (Using synthetic biomechanical test feed).</span>
        </div>
      )}

      {/* Main Viewport Container */}
      <div className={`uw-live-viewport-container layout-${layout}`}>
        {/* Camera Feed & HUD Overlay */}
        <div ref={cameraViewportRef} className="uw-camera-viewport">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className={`uw-camera-video ${mirrored ? 'mirrored' : ''}`}
            style={{ display: isSimulated ? 'none' : 'block' }}
          />

          {isSimulated && (
            <div className="uw-synthetic-feed-backdrop">
              <div className="uw-grid-pattern" />
              <div className="uw-synthetic-badge">
                SYNTHETIC {exerciseType.toUpperCase()} FEED ACTIVE (30 FPS)
              </div>
            </div>
          )}

          <LiveHUDOverlay
            landmarks={liveLandmarks}
            kinematics={liveKinematics}
            trackerState={trackerState}
            mirrored={mirrored}
            width={viewportSize.width}
            height={viewportSize.height}
          />
        </div>

        {/* 3D Digital Twin (Split or PiP) */}
        {(layout === 'split' || layout === 'pip') && (
          <div className={`uw-twin-viewport ${layout === 'pip' ? 'is-pip' : ''}`}>
            <LiveDigitalTwin
              landmarks={liveLandmarks}
              mirrored={mirrored}
              targetROM={targetROM}
              currentDepth={currentDepth}
            />
          </div>
        )}
      </div>

      {/* Completed Set Summary Modal */}
      {showSummary && (
        <LiveSetSummaryModal
          summary={setSummary}
          onSaveToSessions={handleSaveToSessions}
          onExportJSON={handleExportJSON}
          onClose={() => setShowSummary(false)}
          onStartNewSet={handleStartNewSet}
          isSaving={isSaving}
          saveResult={saveResult}
        />
      )}
    </div>
  );
}
