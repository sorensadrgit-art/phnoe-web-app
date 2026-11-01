import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import LiveHUDOverlay from './LiveHUDOverlay.jsx';
import LiveDigitalTwin from './LiveDigitalTwin.jsx';
import LiveSetSummaryModal from './LiveSetSummaryModal.jsx';
import { computePoseKinematics } from './liveKinematics.js';
import { generateSimulatedPose } from './syntheticPose.js';
import SyntheticRecordingPanel from './SyntheticRecordingPanel.jsx';
import { createPoseClient } from './poseClient.js';
import { createExerciseTracker, DEFAULT_PRESETS, EXERCISE_TYPES, PHASES } from './exerciseStateMachine.js';
import { computeExerciseMetric } from './liveDisplayHelper.js';
import { AVATAR_COLLAPSED_NOTICE } from './avatarLifecycle.js';

export function appendPreviewFrame(frames, frame) {
  frames.push(frame);
  if (frames.length > 600) { frames.shift(); return 1; }
  return 0;
}

// Synthesized Web Audio Biofeedback Chimes
function playChime(type = 'success', contexts) {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    contexts?.add(ctx);

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
      osc2.onended=()=>{contexts?.delete(ctx);void ctx.close().catch(()=>{});};
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
      osc.onended=()=>{contexts?.delete(ctx);void ctx.close().catch(()=>{});};
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
  demoMode = false,
  onRecordingBusy,
  initialAvatarVisible = true,
}) {
  const [cameras, setCameras] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('');
  const [mirrored, setMirrored] = useState(true);
  const [avatarVisible, setAvatarVisible] = useState(initialAvatarVisible);
  const [documentHidden, setDocumentHidden] = useState(
    typeof document !== 'undefined' ? document.hidden : false
  );
  const [layout, setLayout] = useState('split'); // 'full', 'split', 'pip'
  const [exerciseType, setExerciseType] = useState(EXERCISE_TYPES.SQUAT);
  const [targetROM, setTargetROM] = useState(80);
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [isTracking, setIsTracking] = useState(true);
  const [isSimulated, setIsSimulated] = useState(demoMode);
  const [cameraStarted,setCameraStarted] = useState(false);
  const [activeSide,setActiveSide] = useState('left');
  const [poseStatus,setPoseStatus] = useState({status:'UNAVAILABLE',reason:'CAMERA_NOT_STARTED'});
  const [cameraError, setCameraError] = useState(null);
  const [recordingBusy,setRecordingBusy]=useState(false);
  const [activityStopped,setActivityStopped]=useState(false);
  const [stopCleanupError,setStopCleanupError]=useState(false);
  const stopSignal=useRef(false), stopRecordingRef=useRef(null), poseClientRef=useRef(null), audioContextsRef=useRef(new Set());
  const avatarRenderingVisible = avatarVisible && !recordingBusy;
  const observationRef=useRef(null);
  const recordingChanged=useCallback(value=>{setRecordingBusy(value);onRecordingBusy?.(value);},[onRecordingBusy]);

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

  // Document visibility change listener
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const onVisibility = () => setDocumentHidden(document.hidden);
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  const videoRef = useRef(null);
  const cameraViewportRef = useRef(null);
  const streamRef = useRef(null);
  const trackerRef = useRef(null);
  const animFrameRef = useRef(null);
  const simulationStepRef = useRef(0);
  const lastRepCountRef = useRef(0);
  const recordedFramesRef = useRef([]);
  const omittedPreviewFramesRef = useRef(0);
  const lastFrameSampleTimeRef = useRef(0);
  const setStartTimeRef = useRef(Date.now());
  const opticalMotionCanvasRef = useRef(null);
  const prevFramePixelsRef = useRef(null);
  const liveDescentOffsetRef = useRef(0);

  const stopActivity = useCallback(()=>{
    stopSignal.current=true; observationRef.current=null;
    setActivityStopped(true); setIsTracking(false); setCameraStarted(false); setAudioEnabled(false);
    setLiveLandmarks(null); setLiveKinematics(null); setTrackerState(trackerRef.current?.pause());
    setPoseStatus({status:'UNAVAILABLE',reason:'ACTIVITY_STOPPED'});
    try{stopRecordingRef.current?.();}catch{setStopCleanupError(true);}
    try{poseClientRef.current?.close();}catch{setStopCleanupError(true);}
    try{if(animFrameRef.current)cancelAnimationFrame(animFrameRef.current);}catch{setStopCleanupError(true);}
    let tracksStopped=true;
    try{for(const track of streamRef.current?.getTracks()||[]) { try{track.stop();}catch{tracksStopped=false;setStopCleanupError(true);} }}catch{tracksStopped=false;setStopCleanupError(true);}
    if(tracksStopped)streamRef.current=null;
    try{if(videoRef.current)videoRef.current.srcObject=null;}catch{setStopCleanupError(true);}
    for(const context of audioContextsRef.current) { try{void context.close().then(()=>audioContextsRef.current.delete(context)).catch(()=>setStopCleanupError(true));}catch{setStopCleanupError(true);} }
  },[]);
  useEffect(()=>()=>{
    for(const context of audioContextsRef.current) { try{void context.close().catch(()=>{});}catch{} }
    audioContextsRef.current.clear();
  },[]);

  // Initialize Exercise State Machine Tracker
  useEffect(() => {
    trackerRef.current = createExerciseTracker(exerciseType, {
      targetROM: Number(targetROM),
      activeSide, projectionOnly:!isSimulated && !demoMode,
    });
    setTrackerState(trackerRef.current.getState());
    lastRepCountRef.current = 0;
    recordedFramesRef.current=[];observationRef.current=null;setLiveLandmarks(null);setLiveKinematics(null);
  }, [exerciseType, targetROM, activeSide, isSimulated, demoMode]);

  // Enumerate Camera Devices
  useEffect(() => {
    if (demoMode) return;
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
  }, [selectedCamera, demoMode]);

  // Start Camera Stream
  useEffect(() => {
    let cancelled = false;

    async function startCamera() {
      if (stopSignal.current || isSimulated || demoMode || !cameraStarted) return;
      setCameraError(null);

      // Stop existing tracks
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }

      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error('Webcam API unavailable');
        }

        const constraints = {
          video: selectedCamera
            ? { deviceId: { exact: selectedCamera }, width: { ideal: 1280 }, height: { ideal: 720 } }
            : { width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        };

        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        if (cancelled || stopSignal.current) {
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
          // Keep camera-preview mode without inferred metrics; never silently substitute synthetic data.
        }
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current=null;
      }
    };
  }, [selectedCamera, isSimulated, demoMode, cameraStarted]);

  useEffect(()=>{
    if(stopSignal.current||isSimulated||demoMode)return;
    let active=true,timer,expiry;
    const client=createPoseClient({token,apiPrefix});poseClientRef.current=client;
    const canvas=document.createElement('canvas');let lastTime=-1,lastResultAt=0,processed=0;
    const unavailable=reason=>{setPoseStatus({status:'UNAVAILABLE',reason});setLiveLandmarks(null);setLiveKinematics(null);setTrackerState(trackerRef.current?.pause());};
    unavailable(cameraStarted?(isTracking?'WAITING_FOR_FRAME':'PAUSED'):'CAMERA_NOT_STARTED');
    async function sample(){
      const video=videoRef.current;
      if(!active||stopSignal.current)return;
      if(!cameraStarted||!isTracking||document.hidden){timer=setTimeout(sample,150);return;}
      if(video?.readyState>=2&&video.videoWidth&&video.currentTime!==lastTime){
        lastTime=video.currentTime;
        const capturedAtMs=Date.now();
        const scale=Math.min(1,640/video.videoWidth,640/video.videoHeight);
        canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
        const ctx=canvas.getContext('2d');ctx.drawImage(video,0,0,canvas.width,canvas.height);
        let jpegBase64='';
        for(const quality of [.75,.5,.3]){jpegBase64=canvas.toDataURL('image/jpeg',quality).split(',')[1];if(jpegBase64.length<=60000)break;}
        try {
          const result=await client.infer({jpegBase64,width:canvas.width,height:canvas.height,capturedAtMs});
          if(!active||stopSignal.current)return;
          if(document.hidden)unavailable('HIDDEN');
          else if(!result||result.status!=='AVAILABLE')unavailable(result?.reason||'STALE_FRAME');
          else {
            const kine=computePoseKinematics(result.landmarks,{width:result.width,height:result.height,minConfidence:result.min_confidence});
            lastResultAt=capturedAtMs;processed++;
            setLiveLandmarks(result.landmarks);setLiveKinematics(kine);
            setTrackerState(trackerRef.current?.update(kine,capturedAtMs));
            const quality=video.getVideoPlaybackQuality?.();
            setPoseStatus({...result,processed,dropped:quality?.droppedVideoFrames??null});
          }
        }catch{if(active&&!stopSignal.current)unavailable('INFERENCE_FAILED');}
      }
      timer=setTimeout(sample,30);
    }
    const hidden=()=>{if(document.hidden)unavailable('HIDDEN');};document.addEventListener('visibilitychange',hidden);
    expiry=setInterval(()=>{if(lastResultAt&&Date.now()-lastResultAt>1500){lastResultAt=0;unavailable('STALE_FRAME');}},200);
    sample();
    return()=>{active=false;clearTimeout(timer);clearInterval(expiry);client.close();if(poseClientRef.current===client)poseClientRef.current=null;document.removeEventListener('visibilitychange',hidden);};
  },[isSimulated,demoMode,cameraStarted,isTracking,selectedCamera,exerciseType,targetROM,activeSide,token,apiPrefix]);

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
    // Synthetic generation is confined to the explicitly selected test mode.
    if (!isSimulated && !demoMode) {
      observationRef.current=null;
      return;
    }
    let active = true;

    function loop() {
      if (!active || stopSignal.current) return;

      if (isTracking && !document.hidden && trackerRef.current) {
        simulationStepRef.current += 1;
        const landmarks = generateSimulatedPose(simulationStepRef.current, exerciseType);
        observationRef.current={capturedAt:performance.now(),landmarks:landmarks.map(p=>p?[p.x,p.y,p.z,p.visibility]:null)};

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
              omittedPreviewFramesRef.current += appendPreviewFrame(recordedFramesRef.current,
                { t: Math.round(t * 1000) / 1000, xyz: osimXYZ });
            }
          }
        }

        // Sound chime on rep completion
        if (audioEnabled && nextState.repCount > lastRepCountRef.current) {
          lastRepCountRef.current = nextState.repCount;
          playChime('success', audioContextsRef.current);
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
    const summary = {...trackerRef.current.finishSet()};
    summary.frames = [...recordedFramesRef.current];
    summary.frames_omitted = omittedPreviewFramesRef.current;
    summary.coordinate_basis = 'Illustrative avatar coordinates; no measured physical scale';
    summary.source_type = 'SYNTHETIC_TEST_ONLY';
    summary.clinical_accuracy_verified = false;
    setSetSummary(summary);
    setShowSummary(true);
    setSaveResult(null);
    setIsTracking(false);
  }, []);

  const handleStartNewSet = useCallback(() => {
    if(stopSignal.current)return;
    if (trackerRef.current) {
      trackerRef.current.reset();
      setTrackerState(trackerRef.current.getState());
      lastRepCountRef.current = 0;
      recordedFramesRef.current = [];
      omittedPreviewFramesRef.current = 0;
      lastFrameSampleTimeRef.current = 0;
      setStartTimeRef.current = Date.now();
    }
    setShowSummary(false);
    setSaveResult(null);
    setIsTracking(true);
  }, []);

  // Live persistence is intentionally unavailable until real acquisition
  // provenance and incremental durable recording pass acceptance.

  const handleExportJSON = useCallback(() => {
    if (!setSummary) return;
    const blob = new Blob([JSON.stringify(setSummary, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `kinelab-SYNTHETIC-TEST-${exerciseType}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [setSummary, exerciseType]);

  const currentDepth = computeExerciseMetric(
    liveKinematics,
    exerciseType,
    activeSide,
    trackerState
  );

  return (
    <div className="uw-live-studio" data-activity-stopped={activityStopped}>
      {/* Top Studio Control Bar */}
      <div className="uw-live-controls-bar">
        <div className="uw-live-control-group">
          <label className="uw-live-label">
            <span>EXERCISE</span>
            <select
              value={exerciseType}
              disabled={recordingBusy}
              onChange={(e) => {setExerciseType(e.target.value);setTargetROM(DEFAULT_PRESETS[e.target.value].targetROM);}}
              className="uw-live-select"
            >
              <option value={EXERCISE_TYPES.SQUAT}>Squats</option>
              <option value={EXERCISE_TYPES.LUNGE}>Lunges</option>
              <option value={EXERCISE_TYPES.KNEE_EXTENSION}>Knee Extension</option>
              <option value={EXERCISE_TYPES.BALANCE}>Single-Leg Balance</option>
            </select>
          </label>

          <label className="uw-live-label">
            <span>{exerciseType==='balance'?'TEST HOLD (SECONDS)':'TEST TARGET (DEGREES)'}</span>
            <select
              value={targetROM}
              disabled={recordingBusy}
              onChange={(e) => setTargetROM(Number(e.target.value))}
              className="uw-live-select"
            >
              {(exerciseType==='balance'?[10,20,30]:[60,75,80,90]).map(value=><option key={value} value={value}>{value}{exerciseType==='balance'?' s':'°'}</option>)}
            </select>
          </label>
          {['lunges','knee-extension'].includes(exerciseType)&&<label className="uw-live-label"><span>ACTIVE SIDE</span>
            <select aria-label="Active exercise side" value={activeSide} disabled={recordingBusy} onChange={e=>setActiveSide(e.target.value)}><option value="left">Left</option><option value="right">Right</option></select></label>}
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
            disabled={recordingBusy}
            title="Mirror camera preview horizontally"
            aria-pressed={mirrored ? 'true' : 'false'}
          >
            Mirror {mirrored ? 'ON' : 'OFF'}
          </button>

          <button
            type="button"
              className={`uw-live-btn-toggle ${avatarRenderingVisible ? 'is-active' : ''}`}
              onClick={() => {if(!recordingBusy)setAvatarVisible(!avatarVisible);}}
              disabled={recordingBusy}
            title="Toggle 3D Digital Twin avatar rendering"
            aria-label="Toggle 3D Digital Twin avatar"
              aria-pressed={avatarRenderingVisible ? 'true' : 'false'}
          >
              3D Avatar: {recordingBusy && avatarVisible ? 'PAUSED' : avatarRenderingVisible ? 'ON' : 'OFF'}
          </button>

          <button
            type="button"
            className={`uw-live-btn-toggle ${audioEnabled ? 'is-active' : ''}`}
            onClick={() => setAudioEnabled(!audioEnabled)}
            title="Audio rep chime"
            aria-pressed={audioEnabled ? 'true' : 'false'}
          >
            Chimes {audioEnabled ? 'ON' : 'OFF'}
          </button>

          {demoMode ? (
            <span className="uw-live-btn-toggle is-active" role="status">Feed: Synthetic demo only</span>
          ) : (
            <button
              type="button"
              className={`uw-live-btn-toggle ${isSimulated ? 'is-active' : ''}`}
              onClick={() => {setIsSimulated(!isSimulated);setCameraStarted(false);setCameraError(null);setIsTracking(true);}}
              disabled={recordingBusy}
              title="Switch local camera inference and synthetic test animation"
            >
              Feed: {isSimulated ? 'SYNTHETIC TEST' : 'REAL CAMERA'}
            </button>
          )}
        </div>

        <div className="uw-live-control-group">
          {!isSimulated&&!demoMode&&<button type="button" disabled={activityStopped} onClick={()=>{if(!stopSignal.current)setCameraStarted(!cameraStarted);}}>{cameraStarted?'Stop camera':'Start local camera'}</button>}
          <button type="button" onClick={stopActivity}>Stop activity</button>
          <button type="button" disabled={activityStopped||recordingBusy||showSummary} onClick={()=>{if(!stopSignal.current){trackerRef.current?.pause();setIsTracking(!isTracking);}}}>{isTracking?'Pause tracking':'Resume tracking'}</button>
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
            disabled={recordingBusy||(!isSimulated && !demoMode)}
            title={!isSimulated && !demoMode ? "No measured set data is available" : "Finish synthetic test set"}
          >
            Finish Synthetic Set
          </button>
        </div>
      </div>

      {stopCleanupError&&<p role="alert">Stop cleanup could not be confirmed. Retain the recording draft and contact the runtime owner.</p>}
      {activityStopped&&<p role="status">Activity stopped. Follow the owner-approved protocol; clinical next-step approval is PENDING. Recording saved/pending status is shown separately. Start a separate reviewed activity to resume.</p>}
      {cameraError && (
        <div className="uw-live-banner-alert">
          <span>Camera stream notification: {cameraError}. No measurements available. Switch to Synthetic Test explicitly to view a demonstration.</span>
        </div>
      )}

      <div role="status" className="uw-live-banner-alert">
        {isSimulated || demoMode
          ? 'SYNTHETIC TEST ONLY — simulated angles, reps and avatar; not measured movement. Measured-session saving is disabled.'
          : 'REAL CAMERA — local image-plane inference; physical accuracy UNVERIFIED. Measured-session saving is disabled. 3D depth UNAVAILABLE; muscle activity NOT MEASURED.'}
      </div>
      {!isSimulated&&!demoMode&&<div className="uw-pose-status" role="status">
        <strong>{poseStatus.status}</strong> {poseStatus.reason||'2D image-plane estimates'}
        {poseStatus.status==='AVAILABLE'&&<span> · Visible landmarks {poseStatus.visible_landmarks}/17 · Confidence filter ≥0.6 (not an accuracy probability) · Inference {poseStatus.inference_ms} ms · Frames processed {poseStatus.processed} · Playback dropped frames {poseStatus.dropped??'UNAVAILABLE'}</span>}
        <div>Left knee {liveKinematics?.leftKneeFlexion??'UNAVAILABLE'} · Right knee {liveKinematics?.rightKneeFlexion??'UNAVAILABLE'} · Trunk projection {liveKinematics?.trunkLean??'UNAVAILABLE'} (degrees)</div>
      </div>}

      {isSimulated&&!demoMode&&<SyntheticRecordingPanel token={token} apiPrefix={apiPrefix}
        observationRef={observationRef} exerciseType={exerciseType} targetROM={targetROM}
        mirrored={mirrored} onBusy={recordingChanged} stopSignal={stopSignal} stopRecordingRef={stopRecordingRef}/>}

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
                SYNTHETIC {exerciseType.toUpperCase()} ANIMATION
              </div>
            </div>
          )}

          {(isSimulated || demoMode || poseStatus.status==='AVAILABLE') && (
            <LiveHUDOverlay
              landmarks={liveLandmarks}
              kinematics={liveKinematics}
              trackerState={trackerState}
              activeSide={activeSide}
              exerciseType={exerciseType}
              mirrored={mirrored}
              width={viewportSize.width}
              height={viewportSize.height}
              sourceSize={!isSimulated&&poseStatus.status==='AVAILABLE'?{width:poseStatus.width,height:poseStatus.height}:null}
            />
          )}
        </div>

        {/* 3D Digital Twin (Split or PiP) */}
        {(layout === 'split' || layout === 'pip') && (
          <div className={`uw-twin-viewport ${layout === 'pip' ? 'is-pip' : ''}`}>
            {!avatarRenderingVisible ? (
              <div
                className="uw-twin-collapsed-placeholder"
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
                <div>
                  {recordingBusy && avatarVisible && <div>3D avatar PAUSED — recording has priority.</div>}
                  {AVATAR_COLLAPSED_NOTICE}
                </div>
              </div>
            ) : (isSimulated || demoMode) ? (
              <LiveDigitalTwin
                landmarks={liveLandmarks}
                kinematics={liveKinematics}
                mirrored={mirrored}
                targetROM={targetROM}
                currentDepth={currentDepth}
                exerciseType={exerciseType}
                documentHidden={documentHidden}
                avatarVisible={avatarRenderingVisible}
              />
            ) : (
              <div role="status">3D motion UNAVAILABLE — camera inference provides 2D points without measured depth.</div>
            )}
          </div>
        )}
      </div>

      {/* Completed Set Summary Modal */}
      {showSummary && (
        <LiveSetSummaryModal
          summary={setSummary}
          onSaveToSessions={undefined}
          demoMode={demoMode}
          onExportJSON={handleExportJSON}
          onClose={() => setShowSummary(false)}
          onStartNewSet={handleStartNewSet}
          onStopActivity={stopActivity} activityStopped={activityStopped}
          isSaving={isSaving}
          saveResult={saveResult}
        />
      )}
    </div>
  );
}
