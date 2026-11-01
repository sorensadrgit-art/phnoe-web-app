import React, { useState } from 'react';
import { roleStatus, shortHash } from './unifiedModel.js';
import { MetadataConfirmationSummary } from './SessionMetadataSetup.jsx';
import { METADATA_FIELDS, buildSessionMetadata, currentMetadataState, metadataFieldsValid, unavailableMetadataReason } from './sessionMetadataSetup.js';

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
  onStopCapture,
  onSaveBoard,
  onRegister,
  onOpenNative,
  onCorrectMetadata
}) {
  const [boardMm, setBoardMm] = useState('');
  const [operator, setOperator] = useState('');
  const emptyFlightCheck = () => ({
    composition: false,
    focusLocked: false,
    boardPrinted: false,
    syncCuesPlanned: false,
  });
  const [flightReport, setFlightReport] = useState({ key: null, checks: emptyFlightCheck() });
  const [deviceList, setDeviceList] = useState(null);
  const [probingDevices, setProbingDevices] = useState(false);
  const [correction, setCorrection] = useState({ key: '', fields: {}, confirmed: false, error: '' });
  const current = detail && detail.id === selectedSession ? currentMetadataState(detail, selectedSession) : null;
  const unavailableReason = current ? '' : unavailableMetadataReason(detail, selectedSession);
  // The draft is bound to the session and metadata context it was prefilled from;
  // a new context discards it instead of rebinding it to different current metadata.
  const correctionKey = current ? selectedSession + ':' + current.context : '';
  const flightCheckKey = current ? JSON.stringify([
    selectedSession, current.context, current.metadata.protocol_id, current.metadata.protocol_version,
  ]) : '';
  // Discard the prior report immediately, including on A -> B -> A transitions.
  // These are operator reports, never calibration or permission to record.
  if (flightReport.key !== flightCheckKey) {
    setFlightReport({ key: flightCheckKey, checks: emptyFlightCheck() });
  }
  const flightCheck = flightReport.key === flightCheckKey ? flightReport.checks : emptyFlightCheck();
  const draft = correction.key === correctionKey ? correction : {
    key: correctionKey, confirmed: false, error: '',
    fields: current ? Object.fromEntries(METADATA_FIELDS.map(name => [name, current.metadata[name]])) : {},
  };
  const correctionChanged = !!current && METADATA_FIELDS.some(name => draft.fields[name] !== current.metadata[name]);
  const canCorrect = !!current && !busy && typeof onCorrectMetadata === 'function'
    && metadataFieldsValid(draft.fields) && correctionChanged && draft.confirmed === true;
  const updateCorrection = (name, value) => {
    if (busy || !current) return;
    setCorrection(prev => {
      const base = prev.key === correctionKey ? prev : draft;
      return { ...base, fields: { ...base.fields, [name]: value }, confirmed: false, error: '' };
    });
  };
  const confirmCorrection = checked => {
    if (busy || !current) return;
    setCorrection(prev => ({ ...(prev.key === correctionKey ? prev : draft), confirmed: checked === true }));
  };
  const submitCorrection = event => {
    event.preventDefault();
    if (!canCorrect) return;
    try { return onCorrectMetadata(buildSessionMetadata(draft.fields, true)); }
    catch (failure) { setCorrection(prev => ({ ...(prev.key === correctionKey ? prev : draft), error: failure.message })); }
  };

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
  const readyToRegister = detail?.ready_to_register === true && roles.length === 6 && issues.length === 0;

  const toggleCheck = key => {
    if (!current) return;
    setFlightReport(prev => {
      const checks = prev.key === flightCheckKey ? prev.checks : emptyFlightCheck();
      return { key: flightCheckKey, checks: { ...checks, [key]: !checks[key] } };
    });
  };

  const handleSaveBoard = () => {
    const mm = Number(boardMm);
    if (!Number.isFinite(mm) || mm <= 0 || !operator.trim()) return;
    onSaveBoard(mm, operator.trim());
  };

  return (
    <div className="uw-capture-wizard">
      <p role="status" className="uw-help">PARTICIPANT_RECORDING_BLOCKED: recording requires an independently approved privacy, consent, physical-validation and clinical-use protocol.</p>
      <MetadataConfirmationSummary sessionId={selectedSession}
        confirmation={detail && detail.id === selectedSession ? detail.metadata_confirmation : null}/>
      <section className="uw-card" aria-label="Current effective session metadata">
        {current ? <>
          <p role="status">Current effective metadata: AVAILABLE · operator reported</p>
          <dl>
            <dt>Subject ID</dt><dd>{current.metadata.subject_id}</dd><dt>Operator ID</dt><dd>{current.metadata.operator_id}</dd>
            <dt>Task ID</dt><dd>{current.metadata.task_id}</dd><dt>Protocol</dt><dd>{current.metadata.protocol_id} · {current.metadata.protocol_version}</dd>
            <dt>Laterality</dt><dd>{current.metadata.laterality}</dd><dt>Confirmed at</dt><dd>{current.metadata.confirmed_at}</dd>
          </dl>
          <p className="uw-help">Metadata context SHA-256 {current.context} · {current.state.head
            ? 'Revision head SHA-256 ' + current.state.head.sha256 : 'No published revision; the initial metadata is current'} ·
            Origin session.json SHA-256 {current.state.origin.sha256}.</p>
          <p className="uw-help">The persisted initial confirmation above stays unchanged. Operator corrections do not establish identity authentication, protocol approval, physical validity or permission to record.</p>
        </> : <p role="status" className="uw-help">
          Current effective metadata: UNAVAILABLE. No verified current metadata is available for this session, so no value is shown as current and the initial confirmation is not used as a fallback. Corrections are disabled. {unavailableReason}
        </p>}
      </section>
      {current && <form onSubmit={submitCorrection} aria-label="Operator metadata correction" className="uw-card uw-form-inline">
        <p className="uw-help">Correct the current opaque identifiers only. Do not enter names, contact details or medical record numbers.
          A correction is an operator report, publishes a new audited revision and never rewrites the original session file.</p>
        {[
          ['subject_id', 'Corrected subject ID'], ['operator_id', 'Corrected operator ID'], ['task_id', 'Corrected task ID'],
          ['protocol_id', 'Corrected protocol ID'], ['protocol_version', 'Corrected protocol version'],
        ].map(([name, label]) => <label key={name} className="uw-field"><span>{label}</span>
          <input name={'correction_' + name} value={draft.fields[name] ?? ''} disabled={!!busy} maxLength={100} autoComplete="off"
            onChange={event => updateCorrection(name, event.target.value)}/></label>)}
        <label className="uw-field"><span>Corrected laterality</span><select name="correction_laterality"
          value={draft.fields.laterality ?? ''} disabled={!!busy} onChange={event => updateCorrection('laterality', event.target.value)}>
          <option value="">Select laterality</option><option value="left">Left</option><option value="right">Right</option>
          <option value="bilateral">Bilateral</option><option value="not_applicable">Not applicable</option>
        </select></label>
        <label><input type="checkbox" name="metadata_correction_confirmed" checked={draft.confirmed === true} disabled={!!busy}
          onChange={event => confirmCorrection(event.target.checked)}/>
          I checked these corrected opaque identifiers for this session and its current metadata context.</label>
        {!correctionChanged && <p className="uw-help">Change at least one identifier to submit a correction.</p>}
        {draft.error && <p role="alert">{draft.error}</p>}
        <button type="submit" className="uw-btn primary" disabled={!canCorrect}>Publish metadata correction</button>
      </form>}
      {/* Flight Check Pre-Capture Bar */}
      <div className="uw-card uw-flight-check-card">
        <div className="uw-card-header">
          <div>
            <div className="uw-overline">FLIGHT CHECK · PRE-RECORDING CHECKLIST</div>
            <h3>Physical Dual-Camera Setup & Protocol</h3>
            <p>Ensure authentic optical conditions before recording or importing videos.</p>
          </div>
          <span className={`uw-pill ${allFlightChecksPass ? 'uw-pill-present' : 'uw-pill-warning'}`}>
            {allFlightChecksPass ? 'Operator checklist reported' : 'Checklist Incomplete'}
          </span>
        </div>

        <div className="uw-checklist-grid">
          <label className="uw-checkbox-item">
            <input
              type="checkbox"
              checked={flightCheck.composition}
              disabled={!current}
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
              disabled={!current}
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
              disabled={!current}
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
              disabled={!current}
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
                <button type="button" className="uw-btn" disabled>
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
                        disabled
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
            ) : readyToRegister ? (
              <p className="uw-help uw-text-present">All 6 role files probed and valid. Ready to register.</p>
            ) : (
              <p role="status" className="uw-help">{detail ? 'Registration pending: six verified source files and all registration requirements are needed.' : 'Session verification unavailable. Select a session and wait for its details to load.'}</p>
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
