import React, { useEffect, useRef } from 'react';
import { PHASES } from './exerciseStateMachine.js';

/**
 * Standard MediaPipe skeleton bone connections.
 */
const POSE_CONNECTIONS = [
  // Torso
  [11, 12], // LShoulder - RShoulder
  [11, 23], // LShoulder - LHip
  [12, 24], // RShoulder - RHip
  [23, 24], // LHip - RHip
  // Left arm
  [11, 13], [13, 15],
  // Right arm
  [12, 14], [14, 16],
  // Left leg
  [23, 25], // LHip - LKnee
  [25, 27], // LKnee - LAnkle
  [27, 29], [29, 31], [27, 31], // Foot
  // Right leg
  [24, 26], // RHip - RKnee
  [26, 28], // RKnee - RAnkle
  [28, 30], [30, 32], [28, 32], // Foot
];

export default function LiveHUDOverlay({
  landmarks,
  kinematics,
  trackerState,
  mirrored = true,
  width = 640,
  height = 480,
}) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, width, height);

    if (!landmarks || landmarks.length === 0) {
      // Draw idle calibration crosshairs
      ctx.save();
      ctx.strokeStyle = 'rgba(0, 243, 255, 0.2)';
      ctx.setLineDash([6, 6]);
      ctx.strokeRect(width * 0.15, height * 0.1, width * 0.7, height * 0.8);
      ctx.restore();
      return;
    }

    ctx.save();
    // Support mirroring coordinates horizontally if video is mirrored
    const mapX = (x) => {
      // If coordinates are normalized [0, 1]
      const rawX = x <= 1.0 ? x * width : x;
      return mirrored ? width - rawX : rawX;
    };
    const mapY = (y) => (y <= 1.0 ? y * height : y);

    // 1. Draw Skeleton Bones
    ctx.lineWidth = 4;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (const [i1, i2] of POSE_CONNECTIONS) {
      const p1 = landmarks[i1];
      const p2 = landmarks[i2];
      if (!p1 || !p2) continue;
      // Skip if visibility is low
      if (p1.visibility !== undefined && p1.visibility < 0.4) continue;
      if (p2.visibility !== undefined && p2.visibility < 0.4) continue;

      const x1 = mapX(p1.x);
      const y1 = mapY(p1.y);
      const x2 = mapX(p2.x);
      const y2 = mapY(p2.y);

      const grad = ctx.createLinearGradient(x1, y1, x2, y2);
      grad.addColorStop(0, '#00f3ff');
      grad.addColorStop(1, '#10b981');

      ctx.strokeStyle = grad;
      ctx.shadowColor = '#00f3ff';
      ctx.shadowBlur = 6;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
    ctx.shadowBlur = 0; // reset shadow

    // 2. Draw Landmark Joints
    for (let i = 0; i < landmarks.length; i++) {
      const p = landmarks[i];
      if (!p || (p.visibility !== undefined && p.visibility < 0.4)) continue;
      const x = mapX(p.x);
      const y = mapY(p.y);

      // Primary joints (shoulders, hips, knees, ankles) are highlighted
      const isMajor = [11, 12, 23, 24, 25, 26, 27, 28].includes(i);
      const radius = isMajor ? 6 : 4;

      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = isMajor ? '#10b981' : '#00f3ff';
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#ffffff';
      ctx.stroke();
    }

    // 3. Draw Real-Time Joint Angle Badges
    const drawBadge = (text, x, y, tone = 'neutral') => {
      ctx.save();
      ctx.font = 'bold 13px system-ui, -apple-system, sans-serif';
      const textWidth = ctx.measureText(text).width;
      const padX = 8;
      const padY = 5;
      const boxW = textWidth + padX * 2;
      const boxH = 22;

      ctx.fillStyle = 'rgba(10, 15, 29, 0.85)';
      ctx.strokeStyle = tone === 'success' ? '#10b981' : tone === 'warning' ? '#f59e0b' : '#00f3ff';
      ctx.lineWidth = 1.5;

      const badgeX = Math.max(5, Math.min(width - boxW - 5, x - boxW / 2));
      const badgeY = Math.max(5, Math.min(height - boxH - 5, y - 28));

      ctx.beginPath();
      ctx.roundRect(badgeX, badgeY, boxW, boxH, 4);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = tone === 'success' ? '#34d399' : tone === 'warning' ? '#fbbf24' : '#e0f2fe';
      ctx.fillText(text, badgeX + padX, badgeY + 16);
      ctx.restore();
    };

    if (kinematics) {
      // Left knee badge (landmark 25)
      const lKnee = landmarks[25];
      if (lKnee && kinematics.leftKneeFlexion !== null) {
        const tone = kinematics.leftKneeFlexion >= (trackerState?.targetROM || 80) ? 'success' : 'neutral';
        drawBadge(`L: ${kinematics.leftKneeFlexion}°`, mapX(lKnee.x), mapY(lKnee.y), tone);
      }
      // Right knee badge (landmark 26)
      const rKnee = landmarks[26];
      if (rKnee && kinematics.rightKneeFlexion !== null) {
        const tone = kinematics.rightKneeFlexion >= (trackerState?.targetROM || 80) ? 'success' : 'neutral';
        drawBadge(`R: ${kinematics.rightKneeFlexion}°`, mapX(rKnee.x), mapY(rKnee.y), tone);
      }
      // Trunk lean badge at midpoint of shoulders
      if (landmarks[11] && landmarks[12] && kinematics.trunkLean !== null) {
        const sMidX = (landmarks[11].x + landmarks[12].x) / 2;
        const sMidY = (landmarks[11].y + landmarks[12].y) / 2;
        const tone = kinematics.trunkLean > 30 ? 'warning' : 'neutral';
        drawBadge(`Trunk: ${kinematics.trunkLean}°`, mapX(sMidX), mapY(sMidY) - 10, tone);
      }
    }

    // 4. Target Depth Arc Gauge (Top Right)
    const targetROM = trackerState?.targetROM || 80;
    const currentDepth = Math.max(
      kinematics?.leftKneeFlexion ?? 0,
      kinematics?.rightKneeFlexion ?? 0
    );
    const progress = Math.min(1.0, currentDepth / Math.max(1, targetROM));

    const gaugeX = width - 60;
    const gaugeY = 60;
    const gaugeR = 34;

    ctx.save();
    // Background track
    ctx.lineWidth = 6;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.beginPath();
    ctx.arc(gaugeX, gaugeY, gaugeR, 0, Math.PI * 2);
    ctx.stroke();

    // Fill arc
    const startAngle = -Math.PI / 2;
    const endAngle = startAngle + progress * Math.PI * 2;
    ctx.strokeStyle = progress >= 0.95 ? '#10b981' : progress >= 0.5 ? '#00f3ff' : '#64748b';
    ctx.shadowColor = progress >= 0.95 ? '#10b981' : '#00f3ff';
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.arc(gaugeX, gaugeY, gaugeR, startAngle, endAngle);
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Center text
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 15px system-ui';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${Math.round(currentDepth)}°`, gaugeX, gaugeY - 4);
    ctx.font = '10px system-ui';
    ctx.fillStyle = '#94a3b8';
    ctx.fillText(`/${targetROM}°`, gaugeX, gaugeY + 12);
    ctx.restore();

    ctx.restore();
  }, [landmarks, kinematics, trackerState, mirrored, width, height]);

  // Phase colors
  const phaseColors = {
    [PHASES.IDLE]: '#64748b',
    [PHASES.READY]: '#38bdf8',
    [PHASES.DESCENDING]: '#f59e0b',
    [PHASES.BOTTOM_HOLD]: '#10b981',
    [PHASES.ASCENDING]: '#00f3ff',
    [PHASES.REP_COMPLETED]: '#34d399',
  };

  const currentPhase = trackerState?.phase || PHASES.IDLE;
  const phaseColor = phaseColors[currentPhase] || '#64748b';

  return (
    <div className="uw-live-hud-container" style={{ position: 'relative', width, height }}>
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className="uw-hud-canvas"
        style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none', zIndex: 10 }}
      />

      {/* HTML HUD Controls & Readouts */}
      <div className="uw-hud-ui" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 12 }}>
        {/* Top-Left: Jumbo Rep Counter & Phase Pill */}
        <div style={{ position: 'absolute', top: 16, left: 20, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div className="uw-hud-jumbo-rep" style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <span style={{ fontSize: '3rem', fontWeight: 900, lineHeight: 1, color: '#ffffff', textShadow: '0 2px 10px rgba(0,0,0,0.8)' }}>
              {trackerState?.repCount ?? 0}
            </span>
            <span style={{ fontSize: '1.1rem', fontWeight: 700, letterSpacing: '0.1em', color: '#38bdf8', textTransform: 'uppercase' }}>
              REPS
            </span>
            {trackerState?.validRepCount !== undefined && (
              <span style={{ fontSize: '0.9rem', color: '#94a3b8', marginLeft: 8 }}>
                ({trackerState.validRepCount} valid)
              </span>
            )}
          </div>

          <div
            className="uw-hud-phase-pill"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: 'rgba(15, 23, 42, 0.85)',
              border: `1.5px solid ${phaseColor}`,
              borderRadius: 999,
              padding: '4px 12px',
              width: 'fit-content',
              backdropFilter: 'blur(4px)',
            }}
          >
            <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: phaseColor, boxShadow: `0 0 8px ${phaseColor}` }} />
            <span style={{ color: '#ffffff', fontSize: '0.8rem', fontWeight: 700, letterSpacing: '0.05em' }}>
              {currentPhase.replace('_', ' ')}
            </span>
          </div>
        </div>

        {/* Bottom Banner: Real-Time Form Coaching */}
        <div
          className="uw-hud-coaching-banner"
          style={{
            position: 'absolute',
            bottom: 20,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(15, 23, 42, 0.88)',
            border: '1px solid rgba(0, 243, 255, 0.3)',
            borderRadius: 8,
            padding: '10px 24px',
            maxWidth: '85%',
            textAlign: 'center',
            backdropFilter: 'blur(6px)',
            boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
          }}
        >
          <div style={{ color: '#00f3ff', fontSize: '0.75rem', fontWeight: 800, letterSpacing: '0.1em', marginBottom: 2, textTransform: 'uppercase' }}>
            BIOFEEDBACK COACH
          </div>
          <div style={{ color: '#f8fafc', fontSize: '1.05rem', fontWeight: 600 }}>
            {trackerState?.lastCoachingMessage || 'Get in position to begin'}
          </div>
          {trackerState?.currentFaults && trackerState.currentFaults.length > 0 && (
            <div style={{ marginTop: 4, display: 'flex', gap: 6, justifyContent: 'center' }}>
              {trackerState.currentFaults.map((fault) => (
                <span
                  key={fault}
                  style={{
                    backgroundColor: 'rgba(239, 68, 68, 0.25)',
                    color: '#f87171',
                    border: '1px solid #ef4444',
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    borderRadius: 4,
                    padding: '2px 8px',
                  }}
                >
                  ⚠ {fault.replace('_', ' ')}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
