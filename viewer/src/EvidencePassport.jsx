import React from 'react';
import { PASSPORT_GATES, isGatePassed, shortHash } from './unifiedModel.js';

export default function EvidencePassport({ passport, onOpenNative }) {
  if (!passport) {
    return (
      <div className="uw-empty">
        <span aria-hidden="true">◇</span>
        <strong>No Evidence Passport Available</strong>
        <p>Select or create a local session to inspect its physical and computational evidence chain.</p>
      </div>
    );
  }

  const state = passport.state || 'EMPTY';
  const isTestOnly = passport.is_test_only;
  const sources = passport.sources || {};
  const board = passport.board_measurement;
  const runs = passport.runs || {};

  return (
    <div className="uw-passport">
      {/* Banner */}
      {isTestOnly ? (
        <div className="uw-passport-alert uw-alert-warning" role="alert">
          <span className="uw-alert-badge">TEST ONLY</span>
          <strong>External Calibration Sample</strong>
          <p>
            This session is derived from online Caliscope / synthetic test clips.
            It cannot be registered as an authentic dual-camera capture, and does not establish physical or clinical measurement accuracy.
          </p>
        </div>
      ) : (
        <div className="uw-passport-alert uw-alert-info" role="status">
          <span className="uw-alert-badge">LOCAL FIRST</span>
          <strong>Local Research Capture</strong>
          <p>
            Immutable originals stored in <code>projects/{passport.session_id}/raw/</code>.
            Physical ruler measurement and camera synchronization are strictly verified before 3D reconstruction.
          </p>
        </div>
      )}

      {/* State Machine Gate Progression */}
      <div className="uw-card">
        <div className="uw-card-header">
          <div>
            <div className="uw-overline">AUDITABLE QUALITY CHAIN</div>
            <h3>Evidence State Progression</h3>
            <p>Append-only quality state machine. No stage passes by file existence alone.</p>
          </div>
          <span className={`uw-pill ${isTestOnly ? 'uw-pill-warning' : 'uw-pill-present'}`}>
            {passport.badge || state}
          </span>
        </div>

        <div className="uw-gates-timeline">
          {PASSPORT_GATES.map((gate, idx) => {
            const passed = isGatePassed(state, gate.id);
            const isCurrent = state === gate.id;
            return (
              <div
                key={gate.id}
                className={`uw-gate-step ${passed ? 'is-passed' : 'is-pending'} ${isCurrent ? 'is-current' : ''}`}
              >
                <div className="uw-gate-node">
                  <span>{passed ? '✓' : idx + 1}</span>
                </div>
                <div className="uw-gate-body">
                  <strong>{gate.label}</strong>
                  <small>{gate.desc}</small>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Sources & Physical Integrity */}
      <div className="uw-two">
        <div className="uw-card">
          <div className="uw-card-header">
            <div>
              <div className="uw-overline">SIX-ROLE CAMERA MANIFEST</div>
              <h3>Source Media Integrity</h3>
              <p>Original files are immutable. SHA-256 hashes registered locally.</p>
            </div>
          </div>

          <div className="uw-checklist">
            {['cam01_intrinsics', 'cam02_intrinsics', 'cam01_board', 'cam02_board', 'cam01_trial', 'cam02_trial'].map(role => {
              const src = sources[role];
              return (
                <div key={role} className="uw-passport-source-row">
                  <div>
                    <strong>{role}.mp4</strong>
                    {src ? (
                      <small>
                        {src.width}x{src.height} · {src.fps ? src.fps.toFixed(1) : '-'} fps · {src.duration ? src.duration.toFixed(1) : '-'}s · SHA: {shortHash(src.sha256)}
                      </small>
                    ) : (
                      <small className="uw-text-missing">File absent from raw/ folder</small>
                    )}
                  </div>
                  <span className={`uw-pill ${src ? 'uw-pill-present' : 'uw-pill-neutral'}`}>
                    {src ? 'Present' : 'Missing'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="uw-card">
          <div className="uw-card-header">
            <div>
              <div className="uw-overline">PHYSICAL CALIBRATION EVIDENCE</div>
              <h3>Board Measurement & Gates</h3>
              <p>Self-reported ruler entry, not an auto-inferred physical scale.</p>
            </div>
          </div>

          <div className="uw-checklist">
            <div>
              <span>Checkerboard Target</span>
              <strong>7x9 inner corners (20.0 mm expected)</strong>
            </div>
            <div>
              <span>Operator Measurement</span>
              {board ? (
                <strong className="uw-text-present">{board.measured_square_mm} mm ({board.measured_by})</strong>
              ) : (
                <strong className="uw-text-missing">Not measured yet</strong>
              )}
            </div>
            <div>
              <span>Camera Calibration</span>
              <span className={`uw-pill ${runs.calibration?.passed ? 'uw-pill-present' : 'uw-pill-neutral'}`}>
                {runs.calibration?.passed ? 'Passed' : 'Pending / Unverified'}
              </span>
            </div>
            <div>
              <span>DualCam Synchronization</span>
              <span className={`uw-pill ${runs.synchronization?.passed ? 'uw-pill-present' : 'uw-pill-neutral'}`}>
                {runs.synchronization?.passed ? 'Passed' : 'Pending / Unverified'}
              </span>
            </div>
            <div>
              <span>3D Reconstruction</span>
              <span className={`uw-pill ${runs.triangulation?.passed ? 'uw-pill-present' : 'uw-pill-neutral'}`}>
                {runs.triangulation?.passed ? 'Passed' : 'Pending / Unverified'}
              </span>
            </div>
          </div>

          <div className="uw-actions" style={{ marginTop: '16px' }}>
            {onOpenNative && (
              <>
                <button type="button" className="uw-btn" onClick={() => onOpenNative('board')}>
                  Print 20mm Checkerboard
                </button>
                <button type="button" className="uw-btn" onClick={() => onOpenNative('sync')}>
                  Exact-Frame Cue Review
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
