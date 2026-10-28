import React, { useState } from 'react';
import { roleStatus, shortHash } from './unifiedModel.js';

const ROLE_META = {
  cam01_intrinsics: { title: 'Phone · Intrinsic Calibration', camera: 'Phone (Cam 1)', roleType: 'intrinsics', desc: 'Hold printed 20mm checkerboard at diverse tilts and distances across the entire frame.' },
  cam02_intrinsics: { title: 'Webcam · Intrinsic Calibration', camera: 'Webcam (Cam 2)', roleType: 'intrinsics', desc: 'Wave printed 20mm checkerboard in front of webcam covering all quadrants.' },
  cam01_board: { title: 'Phone · Extrinsics Board View', camera: 'Phone (Cam 1)', roleType: 'board', desc: 'Place board flat on movement plane, visible simultaneously in both cameras.' },
  cam02_board: { title: 'Webcam · Extrinsics Board View', camera: 'Webcam (Cam 2)', roleType: 'board', desc: 'Stationary board captured from webcam at the exact same location and orientation.' },
  cam01_trial: { title: 'Phone · Synchronized Trial', camera: 'Phone (Cam 1)', roleType: 'trial', desc: 'Record subject movement trial. Include sharp clapping / heel strike at start and end.' },
  cam02_trial: { title: 'Webcam · Synchronized Trial', camera: 'Webcam (Cam 2)', roleType: 'trial', desc: 'Simultaneous webcam recording of the trial with the same start and end visual cues.' },
};

export default function GuidedCaptureWizard({
  detail,
  selectedSession,
  activeSession,
  cameraState,
  busy,
  onImportPhone,
  onStartCapture,
  onStopCapture,
  onSaveBoard,
  onRegister,
  onOpenNative
}) {
  const [boardMm, setBoardMm] = useState('');
  const [operator, setOperator] = useState('');
  const [flightCheck, setFlightCheck] = useState({
    composition: false,
    focusLocked: false,
    boardPrinted: false,
    syncCuesPlanned: false,
  });
  const [deviceList, setDeviceList] = useState(null);
  const [probingDevices, setProbingDevices] = useState(false);

  const probeDevices = async () => {
    setProbingDevices(true);
    try {
      if (!navigator.mediaDevices?.enumerateDevices) {
        setDeviceList([{ label: 'Browser media device query unsupported', kind: 'videoinput' }]);
        return;
      }
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevs = devices.filter(d => d.kind === 'videoinput');
      setDeviceList(videoDevs.length > 0 ? videoDevs : [{ label: 'No video cameras detected by browser', kind: 'videoinput' }]);
    } catch (e) {
      setDeviceList([{ label: `Device query error: ${e.message}`, kind: 'videoinput' }]);
    } finally {
      setProbingDevices(false);
    }
  };

  const allFlightChecksPass = Object.values(flightCheck).every(Boolean);
  const isRealDraft = activeSession?.kind === 'real' && activeSession?.status === 'draft';
  const roles = detail?.roles || [];
  const issues = detail?.issues || [];
  const readyToRegister = detail?.ready_to_register;

  const toggleCheck = key => {
    setFlightCheck(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSaveBoard = () => {
    const mm = Number(boardMm);
    if (!Number.isFinite(mm) || mm <= 0 || !operator.trim()) return;
    onSaveBoard(mm, operator.trim());
  };

  return (
    <div className="uw-capture-wizard">
      {/* Flight Check Pre-Capture Bar */}
      <div className="uw-card uw-flight-check-card">
        <div className="uw-card-header">
          <div>
            <div className="uw-overline">FLIGHT CHECK · PRE-RECORDING CHECKLIST</div>
            <h3>Physical Dual-Camera Setup & Protocol</h3>
            <p>Ensure authentic optical conditions before recording or importing videos.</p>
          </div>
          <span className={`uw-pill ${allFlightChecksPass ? 'uw-pill-present' : 'uw-pill-warning'}`}>
            {allFlightChecksPass ? 'Checklist Verified' : 'Checklist Incomplete'}
          </span>
        </div>

        <div className="uw-checklist-grid">
          <label className="uw-checkbox-item">
            <input
              type="checkbox"
              checked={flightCheck.composition}
              onChange={() => toggleCheck('composition')}
            />
            <div>
              <strong>Side-by-Side Composition Guide</strong>
              <small>Cameras angled ~60° to 90° apart, capturing the full 3D calibration and walking volume.</small>
            </div>
          </label>

          <label className="uw-checkbox-item">
            <input
              type="checkbox"
              checked={flightCheck.focusLocked}
              onChange={() => toggleCheck('focusLocked')}
            />
            <div>
              <strong>Focus & Exposure Locked</strong>
              <small>Disable auto-focus breathing and dynamic zoom on both devices.</small>
            </div>
          </label>

          <label className="uw-checkbox-item">
            <input
              type="checkbox"
              checked={flightCheck.boardPrinted}
              onChange={() => toggleCheck('boardPrinted')}
            />
            <div>
              <strong>7x9 Checkerboard Printed at 100%</strong>
              <small>Verified on rigid flat surface (no paper curl); measured with a physical ruler in mm.</small>
            </div>
          </label>

          <label className="uw-checkbox-item">
            <input
              type="checkbox"
              checked={flightCheck.syncCuesPlanned}
              onChange={() => toggleCheck('syncCuesPlanned')}
            />
            <div>
              <strong>Synchronized Visual Cue Protocol</strong>
              <small>Visible, sharp hand clap or heel impact performed at start and end of trial.</small>
            </div>
          </label>
        </div>

        <div style={{ marginTop: 14, borderTop: '1px solid #1a323d', paddingTop: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: '#85a6b0' }}>Hardware Device Verification</span>
            <button
              type="button"
              className="uw-btn"
              style={{ fontSize: 11, padding: '4px 10px' }}
              disabled={probingDevices}
              onClick={probeDevices}
            >
              {probingDevices ? 'Probing Devices...' : 'Test Video Devices'}
            </button>
          </div>
          {deviceList && (
            <div className="uw-device-probe-box">
              <strong>Detected Camera Hardware:</strong>
              <ul className="uw-device-list">
                {deviceList.map((dev, idx) => (
                  <li key={idx}>{dev.label || `Camera ${idx + 1} (${dev.deviceId ? dev.deviceId.slice(0, 8) + '...' : 'Available'})`}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Six Roles Interactive Deck */}
      <div className="uw-card">
        <div className="uw-card-header">
          <div>
            <div className="uw-overline">SIX INDEPENDENT CAMERA SLOTS</div>
            <h3>Role Recordings & Status</h3>
            <p>Cam01 (Phone MP4 Import) · Cam02 (Webcam Direct Recording)</p>
          </div>
          <div className="uw-actions">
            {onOpenNative && (
              <>
                <button type="button" className="uw-btn" onClick={() => onOpenNative('capture')} disabled={!selectedSession}>
                  Open Capture Station GUI
                </button>
                <button type="button" className="uw-btn" onClick={() => onOpenNative('board')} disabled={!selectedSession}>
                  Print 20mm Checkerboard
                </button>
              </>
            )}
          </div>
        </div>

        <div className="uw-role-grid">
          {roles.map(role => {
            const meta = ROLE_META[role.role] || {};
            const isPhone = role.camera === 'phone';
            return (
              <div key={role.role} className={`uw-role-card ${role.file_present ? 'is-present' : 'is-missing'}`}>
                <div className="uw-role-card-header">
                  <span className="uw-role-device">{meta.camera || role.camera}</span>
                  <span className={`uw-pill ${role.file_present ? 'uw-pill-present' : 'uw-pill-neutral'}`}>
                    {roleStatus(role).label}
                  </span>
                </div>

                <h4>{meta.title || role.role}</h4>
                <p className="uw-role-desc">{meta.desc || role.instruction}</p>

                <div className="uw-role-file-info">
                  <code>{role.role}.mp4</code>
                  {role.file_present ? (
                    <span className="uw-tag-verified">Stored in raw/</span>
                  ) : (
                    <span className="uw-tag-pending">Awaiting file</span>
                  )}
                </div>

                {isRealDraft && (
                  <div className="uw-role-actions">
                    {isPhone ? (
                      <label className="uw-btn primary uw-upload-btn">
                        Import Phone MP4
                        <input
                          type="file"
                          accept=".mp4,video/mp4"
                          disabled={!!busy || role.file_present}
                          onChange={e => {
                            const file = e.target.files?.[0];
                            e.target.value = '';
                            if (file) onImportPhone(role.role, file);
                          }}
                        />
                      </label>
                    ) : (
                      <button
                        type="button"
                        className="uw-btn primary"
                        disabled={!!busy || role.file_present || cameraState?.state === 'recording'}
                        onClick={() => onStartCapture(role.role, role.record_seconds || 15)}
                      >
                        Record {role.record_seconds || 15}s Webcam
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Live Camera Recording Status Bar */}
        <div className="uw-capture-status-bar">
          <div className="uw-camera-pill">
            <span className={`uw-status-dot ${cameraState?.state === 'recording' ? 'is-recording' : ''}`} />
            <strong>WEBCAM: {cameraState?.state ? cameraState.state.toUpperCase() : 'IDLE'}</strong>
          </div>
          <span className="uw-camera-msg">{cameraState?.message || 'No camera recording in progress.'}</span>
          {cameraState?.state === 'recording' && (
            <button type="button" className="uw-btn danger" disabled={!!busy} onClick={onStopCapture}>
              Stop Recording Now
            </button>
          )}
        </div>
      </div>

      {/* Board Measurement & Registration Section */}
      <div className="uw-two">
        <div className="uw-card">
          <div className="uw-card-header">
            <div>
              <div className="uw-overline">PHYSICAL SCALE VALIDATION</div>
              <h3>Physical Ruler Measurement</h3>
              <p>Measure a printed square side with a physical ruler (expected: 20.0 mm).</p>
            </div>
          </div>

          <div className="uw-form-vertical">
            <label className="uw-field">
              <span>Measured Square Side (mm)</span>
              <input
                type="number"
                step="0.1"
                min="0.1"
                value={boardMm}
                onChange={e => setBoardMm(e.target.value)}
                placeholder="e.g. 20.1"
              />
            </label>

            <label className="uw-field">
              <span>Operator Initials / Identifier</span>
              <input
                type="text"
                value={operator}
                onChange={e => setOperator(e.target.value)}
                placeholder="e.g. SR"
                maxLength={90}
              />
            </label>

            <button
              type="button"
              className="uw-btn"
              disabled={!!busy || !boardMm || !operator.trim() || !isRealDraft}
              onClick={handleSaveBoard}
            >
              Save Operator Measurement
            </button>
            <small className="uw-help">
              This self-reported measurement calibrates physical scale. It does not certify clinical accuracy.
            </small>
          </div>
        </div>

        <div className="uw-card">
          <div className="uw-card-header">
            <div>
              <div className="uw-overline">SOURCE IMMUTABILITY GATE</div>
              <h3>Register Verified Originals</h3>
              <p>Locks and computes immutable SHA-256 hashes of all 6 source files.</p>
            </div>
          </div>

          <div className="uw-registration-body">
            {issues.length > 0 ? (
              <div className="uw-issues-box">
                <strong>Pending Requirements:</strong>
                <ul>
                  {issues.map((iss, i) => (
                    <li key={i}>{iss}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="uw-help uw-text-present">All 6 role files probed and valid. Ready to register.</p>
            )}

            <button
              type="button"
              className="uw-btn primary"
              disabled={!!busy || !readyToRegister || !isRealDraft}
              onClick={onRegister}
            >
              Register 6 Source Hashes
            </button>

            <small className="uw-help" style={{ marginTop: '12px', display: 'block' }}>
              Registration permanently binds the recordings. Retakes must be staged as new sessions to preserve original media integrity.
            </small>
          </div>
        </div>
      </div>
    </div>
  );
}
