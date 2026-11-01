import React, { useEffect, useRef, useState } from 'react';
import { parseComparisonTimings, TIMING_LABELS, timingUnavailable } from './reconstructionTimingModel.js';
import { formatBytes, formatSession } from './unifiedModel.js';
import ManualAssessmentEntry from './ManualAssessmentEntry.jsx';
import BackupScheduleStatus, { parseBackupScheduleStatus } from './BackupScheduleStatus.jsx';
import EvidenceExportPanel, {evidenceMetadataIdentity} from './EvidenceExportPanel.jsx';
import {
  CAPTURE_ROLE_COUNT,
  formatCoordinateDifference,
  formatCoordinateValue,
  hasComparisonSourceObservation,
  parseComparisonResponse,
} from './reportComparisonHelper.js';

const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
// Value-based so a poll that returns equal rows in new objects does not clear a valid comparison.
const stableJson = value => JSON.stringify(value, (key, item) =>
  isRecord(item) ? Object.fromEntries(Object.keys(item).sort().map(name => [name, item[name]])) : item);
const shortHash = value => value.slice(0, 12) + '…';
const rangeText = (value, unit) => [value.min, value.max, value.excursion].map(item => formatCoordinateValue(item, unit)).join(' / ');
const differenceText = (value, unit) => [value.min, value.max, value.excursion].map(item => formatCoordinateDifference(item, unit)).join(' / ');

function comparisonView(result) {
  const rm = result.research_measurements;
  const endpoints = [result.session_1, result.session_2].map(id => rm.sessions.find(source => source.session_id === id) || null);
  const operator = endpoints.every(Boolean)
    ? (endpoints[0].metadata.operator_id === endpoints[1].metadata.operator_id ? 'SAME' : 'DIFFERENT')
    : 'UNAVAILABLE';
  const captured = count => count === null ? 'Sources: UNAVAILABLE' : `${count}/${CAPTURE_ROLE_COUNT} sources`;
  return (
    <div className={`uw-compare-result ${result.compatible ? 'is-compatible' : 'is-incompatible'}`}>
      {result.isFixtureOnly && (
        <div
          role="alert"
          className="uw-fixture-banner"
          style={{
            background: 'rgba(245, 158, 11, 0.15)',
            border: '1px solid #f59e0b',
            borderRadius: 6,
            padding: '10px 14px',
            color: '#fbbf24',
            fontSize: '0.85rem',
            fontWeight: 600,
            marginBottom: 12,
          }}
        >
          ⚠ GENERATED CONTRACT FIXTURE ONLY · TEST_ONLY research data · Physical accuracy unverified · Clinical validation unverified
        </div>
      )}

      <ul className="uw-evidence-labels" aria-label="Comparison evidence status" style={{ margin: '0 0 12px 0', paddingLeft: 18, fontSize: '0.8rem', color: '#cbd5e1' }}>
        <li>Provenance: {result.provenance.kind} · {result.provenance.label}</li>
        {result.test_only && <li>TEST_ONLY: generated or test-only evidence, never a physical measurement</li>}
        <li>Physical accuracy unverified (PHYSICAL_ACCURACY: UNVERIFIED)</li>
        <li>Clinical validation unverified (CLINICAL_VALIDATION: UNVERIFIED)</li>
        <li>Uncertainty: UNAVAILABLE ({rm.uncertainty.reason})</li>
        <li>Meaningful change / repeatability: UNAVAILABLE ({rm.meaningful_change.reason})</li>
      </ul>

      <div className="uw-compare-header">
        <strong>Compatibility Verdict:</strong>
        <span className={`uw-pill ${result.compatible ? 'uw-pill-present' : 'uw-pill-warning'}`}>
          {result.compatible ? 'COMPATIBLE' : 'INCOMPATIBLE'}
        </span>
      </div>
      {result.compatible ? (
        <p className="uw-compare-reason">{result.reason}</p>
      ) : (
        <div className="uw-compare-reason">
          <strong>Differences or missing evidence preventing comparison:</strong>
          <ul className="uw-compare-reasons">
            {result.reasons.map((reason, index) => <li key={index}>{reason}</li>)}
          </ul>
          <p className="uw-help">No trend or difference is shown for incompatible, missing, or protocol-changed evidence.</p>
        </div>
      )}

      <div className="uw-stat-grid" style={{ marginTop: '12px' }}>
        <div className="uw-stat">
          <span>{result.session_1}</span>
          <strong>{result.metrics.state_1}</strong>
          <small>{captured(result.metrics.captured_1)}</small>
        </div>
        <div className="uw-stat">
          <span>{result.session_2}</span>
          <strong>{result.metrics.state_2}</strong>
          <small>{captured(result.metrics.captured_2)}</small>
        </div>
      </div>

      {rm.status === 'AVAILABLE' ? (
        <div className="uw-research-measurements" style={{ marginTop: 18, borderTop: '1px solid rgba(255, 255, 255, 0.1)', paddingTop: 14 }}>
          <h4 style={{ margin: '0 0 4px 0', fontSize: '1rem', color: '#f8fafc' }}>
            Two-Endpoint Descriptive Angular Difference
          </h4>
          <p className="uw-help" style={{ margin: '0 0 6px 0', color: '#94a3b8', fontSize: '0.8rem' }}>
            Native joint angles only (OpenSim IK / Kinematics) · 2D estimates NOT USED · Clinical thresholds NOT APPLIED
          </p>
          <p className="uw-help" style={{ margin: '0 0 14px 0', color: '#94a3b8', fontSize: '0.8rem' }}>
            Endpoint 1 is the active session ({result.session_1}); Endpoint 2 is the comparison session ({result.session_2}).
            Order follows selection, not capture chronology; capture dates are not available.
            Differences are arithmetic (Endpoint 2 − Endpoint 1) only, not recovery, improvement, or meaningful change.
          </p>
          <div className="uw-coordinates-container" style={{ marginBottom: 14, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8' }}>
                  <th scope="col" style={{ padding: '6px 8px' }}>Coordinate</th>
                  <th scope="col" style={{ padding: '6px 8px' }}>Availability</th>
                  <th scope="col" style={{ padding: '6px 8px' }}>Endpoint 1 · {result.session_1} (Min / Max / Excursion)</th>
                  <th scope="col" style={{ padding: '6px 8px' }}>Endpoint 2 · {result.session_2} (Min / Max / Excursion)</th>
                  <th scope="col" style={{ padding: '6px 8px' }}>Difference, Endpoint 2 − Endpoint 1 (Min / Max / Excursion)</th>
                  <th scope="col" style={{ padding: '6px 8px' }}>Uncertainty</th>
                </tr>
              </thead>
              <tbody>
                {rm.coordinates.map(coord => (
                  <tr key={coord.name} data-coordinate={coord.name} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                    <th scope="row" style={{ padding: '8px', fontWeight: 600, color: '#00f3ff' }}>
                      {coord.name} <span style={{ color: '#64748b', fontSize: '0.75rem' }}>({coord.unit})</span>
                    </th>
                    <td data-cell="availability" style={{ padding: '8px' }}>{coord.available ? 'AVAILABLE' : 'UNAVAILABLE'}</td>
                    <td data-cell="endpoint-1" style={{ padding: '8px' }}>{rangeText(coord.session_1, coord.unit)}</td>
                    <td data-cell="endpoint-2" style={{ padding: '8px' }}>{rangeText(coord.session_2, coord.unit)}</td>
                    <td data-cell="difference" style={{ padding: '8px' }}>{differenceText(coord.difference, coord.unit)}</td>
                    <td data-cell="uncertainty" style={{ padding: '8px' }}>{coord.uncertainty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div
          className="uw-measurements-unavailable"
          style={{
            marginTop: 14,
            padding: '10px 14px',
            background: 'rgba(15, 23, 42, 0.6)',
            border: '1px solid #334155',
            borderRadius: 6,
            fontSize: '0.82rem',
            color: '#94a3b8',
          }}
        >
          <div style={{ color: '#f59e0b', fontWeight: 600, marginBottom: 4 }}>
            Research Measurements: UNAVAILABLE ({rm.reason})
          </div>
          <div>Per-coordinate endpoints: UNAVAILABLE. No coordinate values were produced for this pair.</div>
          <div>
            Measurements absent. Absence must not be interpreted as zero degrees, clinical stability, recovery, or improvement.
          </div>
        </div>
      )}

      <div className="uw-metadata-breakdown" style={{ background: '#0a0f1d', border: '1px solid #1e293b', borderRadius: 6, padding: '10px 14px', marginTop: 12, fontSize: '0.8rem' }}>
        <div style={{ fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Endpoint metadata, protocol and source revision disclosure:</div>
        <div style={{ marginBottom: 6 }}>
          Operator: {operator} across endpoints
          {operator === 'DIFFERENT' && ' (disclosed difference; not a clinical equivalence claim)'}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {endpoints.map((source, index) => source ? (
            <div key={source.session_id}>
              <div style={{ color: '#38bdf8', fontWeight: 600 }}>Endpoint {index + 1} · Session: {source.session_id}</div>
              <div>Subject (pseudonymous): {source.metadata.subject_id}</div>
              <div>Operator (pseudonymous): {source.metadata.operator_id}</div>
              <div>Task: {source.metadata.task_id}</div>
              <div>Protocol: {source.metadata.protocol_id} · version {source.metadata.protocol_version}</div>
              <div>Laterality: {source.metadata.laterality}</div>
              <div style={{ wordBreak: 'break-all' }}>Model SHA-256: {shortHash(source.contract.model_sha256)}</div>
              <div style={{ wordBreak: 'break-all' }}>Calibration SHA-256: {shortHash(source.contract.calibration_sha256)}</div>
              <div style={{ wordBreak: 'break-all' }}>Session revision: {shortHash(source.source_revision.session_sha256)}</div>
              <div style={{ wordBreak: 'break-all' }}>Run revision: {shortHash(source.source_revision.run_sha256)}</div>
              <div style={{ wordBreak: 'break-all' }}>Motion revision: {shortHash(source.source_revision.motion_sha256)}</div>
            </div>
          ) : (
            <div key={'missing-' + index}>
              Endpoint {index + 1} · Session: {index ? result.session_2 : result.session_1}: metadata and source revision UNAVAILABLE
            </div>
          ))}
        </div>
        <div style={{ marginTop: 10 }}>
          {[result.session_1, result.session_2].map((id, index) => (
            <div key={id} role="group" aria-label={`Endpoint ${index + 1} timing and review state`}>
              <div>Endpoint {index + 1} · Session: {id}</div>
              <div>Review state: {(index ? result.passport_2 : result.passport_1).state}</div>
              <ReconstructionTimingView timing={result.timings?.[id] || timingUnavailable('TIMING_NOT_REPORTED')} />
            </div>
          ))}
          <div>Timing partitions adjacent observed endpoints; decoded source extent and physical accuracy remain UNVERIFIED.</div>
        </div>
      </div>
    </div>
  );
}

export function ReconstructionTimingView({ timing }) {
  if (timing?.status !== 'AVAILABLE') {
    return <div>
      <div>Valid duration: UNAVAILABLE</div>
      <div>Rejected duration: UNAVAILABLE</div>
      <div>Gap timeline: UNAVAILABLE</div>
      <div>{timing?.code || 'TIMING_NOT_REPORTED'}</div>
    </div>;
  }
  const seconds = value => `${value.toFixed(6)} s`;
  return <div>
    <div>Observed samples: {timing.sample_counts.observed} · valid: {timing.sample_counts.valid} · rejected: {timing.sample_counts.rejected} · missing interior: {timing.sample_counts.missing_interior}</div>
    {Object.entries(TIMING_LABELS).map(([kind, label]) => <div key={kind}>
      {label}: {seconds(timing.duration_s[kind])}
    </div>)}
    <div>Observed span: {seconds(timing.duration_s.observed_span)} · no endpoint extrapolation</div>
    <div role="list" aria-label="Observed frame segments">
      {timing.segments.map((segment, index) => <div role="listitem" key={index}>
        {segment.classification} frames {segment.first_frame}–{segment.last_frame} · {segment.samples} samples · {seconds(segment.first_time_s)}–{seconds(segment.last_time_s)}
      </div>)}
    </div>
    <div role="list" aria-label="Interior frame gaps">
      {timing.gaps.length === 0 ? <div>No interior frame gaps observed</div> : timing.gaps.map((gap, index) => <div role="listitem" key={index}>
        Unknown gap frames {gap.first_missing_frame}–{gap.last_missing_frame} · {gap.missing_samples} missing samples · adjacent bounds {seconds(gap.left_time_s)}–{seconds(gap.right_time_s)}
      </div>)}
    </div>
    <div>Interval policy: {timing.duration_policy}</div>
    <div>Physical accuracy: UNVERIFIED · Clinical validation: UNVERIFIED · Decoded source extent: UNVERIFIED</div>
    <div>Durations partition adjacent observed endpoints; they do not establish continuous physical validity.</div>
  </div>;
}


export default function ReportStudio({
  sessions,
  selectedSession,
  reports,
  busy,
  onSelectSession,
  onDownloadReport,
  onGenerateReports,
  onCompareSessions,
  onCreateBackup,
  onLoadBackupSchedule,
  onRestoreBackup,
  onOpenFolder,
  onLoadManualAssessmentContext,
  onPublishManualAssessment,
  onEvidenceExportRequest
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterKind, setFilterKind] = useState('all');
  const [compareTarget, setCompareTarget] = useState('');
  const [compareResult, setCompareResult] = useState(null);
  const [compareError, setCompareError] = useState(null);
  const [isComparing, setIsComparing] = useState(false);
  const [backupRestoreName, setBackupRestoreName] = useState('');
  const [scheduleRefresh, setScheduleRefresh] = useState(0);
  const [schedule, setSchedule] = useState(null);
  const [scheduleError, setScheduleError] = useState(null);
  useEffect(() => {
    let current = true;
    setSchedule(null);
    setScheduleError(null);
    if (typeof onLoadBackupSchedule !== 'function') {
      setScheduleError('Backup monitoring is unavailable.');
      return () => { current = false; };
    }
    Promise.resolve().then(() => onLoadBackupSchedule()).then(value => {
      const checked = parseBackupScheduleStatus(value);
      if (current) setSchedule(checked);
    }).catch(() => { if (current) setScheduleError('Backup monitoring is unavailable. No recovery status has been confirmed.'); });
    return () => { current = false; };
  }, [onLoadBackupSchedule, scheduleRefresh]);
  const pairRows = [selectedSession, compareTarget].map(id => sessions.find(s => s.id === id));
  const pairPresent = !!selectedSession && !!compareTarget && selectedSession !== compareTarget && pairRows.every(Boolean);
  const pairObserved = pairPresent && pairRows.every(hasComparisonSourceObservation);
  const pairSource = pairObserved ? stableJson(pairRows) : '';
  const comparisonRequest = useRef(0);
  const comparisonIdentity = useRef({ session_1: selectedSession, session_2: compareTarget, pairSource });
  comparisonIdentity.current = { session_1: selectedSession, session_2: compareTarget, pairSource };
  useEffect(() => {
    comparisonRequest.current++;
    setCompareResult(null);
    setCompareError(null);
    setIsComparing(false);
  }, [selectedSession, compareTarget, pairSource]);
  // Effects run after paint, so stale evidence is also hidden while rendering.
  const boundToPair = item => !!item && pairObserved && item.session_1 === selectedSession &&
    item.session_2 === compareTarget && item.pairSource === pairSource;
  const visibleResult = boundToPair(compareResult) ? compareResult.parsed : null;
  const visibleError = boundToPair(compareError) ? compareError.message : '';
  const selectedIsUnverifiedLive = sessions.some(s => s.id === selectedSession &&
    (s.kind === 'live' || s.evidence_status === 'unverified'));

  const filteredSessions = sessions.filter(s => {
    const matchesSearch = s.id.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesKind = filterKind === 'all' || s.kind === filterKind;
    return matchesSearch && matchesKind;
  });

  const handleCompare = async () => {
    if (!pairObserved) return;
    const sequence = ++comparisonRequest.current;
    const identity = { session_1: selectedSession, session_2: compareTarget, pairSource };
    const current = () => comparisonRequest.current === sequence &&
      Object.keys(identity).every(key => comparisonIdentity.current[key] === identity[key]);
    setCompareError(null);
    setCompareResult(null);
    setIsComparing(true);
    try {
      const res = await onCompareSessions(identity.session_1, identity.session_2);
      if (!current()) return;
      const parsed = parseComparisonResponse(res, identity.session_1, identity.session_2);
      if (!parsed.valid) throw Error(parsed.error);
      const timings = parseComparisonTimings(res, [identity.session_1, identity.session_2], pairRows);
      setCompareResult({ ...identity, parsed: { ...parsed, timings } });
    } catch (error) {
      if (current()) {
        setCompareResult(null);
        setCompareError({ ...identity, message: error instanceof Error ? error.message : 'Comparison unavailable. Try again.' });
      }
    } finally {
      if (current()) setIsComparing(false);
    }
  };
  return (
    <div className="uw-report-studio">
      <EvidenceExportPanel
        key={evidenceMetadataIdentity(sessions.find(item=>item?.id===selectedSession),selectedSession)||'unavailable'}
        sessionId={selectedSession}
        session={sessions.find(item=>item?.id===selectedSession)}
        busy={busy}
        onRequest={onEvidenceExportRequest}
      />
      <ManualAssessmentEntry
        key={`${selectedSession ?? ''}:${sessions.find(session => session.id === selectedSession)?.metadata_context_sha256 ?? 'unavailable'}`}
        sessionId={selectedSession}
        session={sessions.find(session => session.id === selectedSession)}
        metadataHash={sessions.find(session => session.id === selectedSession)?.metadata_context_sha256}
        busy={busy}
        onLoadContext={onLoadManualAssessmentContext}
        onPublish={onPublishManualAssessment}
      />
      {/* Top Controls: Search, Filter, Generate */}
      <div className="uw-card">
        <div className="uw-card-header">
          <div>
            <div className="uw-overline">T7 LOCAL RESEARCH REPORTING STUDIO</div>
            <h3>Reports, Session History & Offline Backups</h3>
            <p>Export research evidence only when source provenance is verified. Archived live telemetry is unverified and cannot generate or download reports.</p>
          </div>
          <div className="uw-actions">
            <button
              type="button"
              className="uw-btn primary"
              disabled={!!busy || !selectedSession || selectedIsUnverifiedLive}
              onClick={() => onGenerateReports(selectedSession)}
            >
              Generate Offline Research Reports
            </button>
            <button
              type="button"
              className="uw-btn"
              disabled={!selectedSession}
              onClick={onOpenFolder}
            >
              Open Session Folder
            </button>
          </div>
        </div>

        <div className="uw-filter-bar">
          <label className="uw-field" style={{ flex: 2 }}>
            <span>Search Sessions</span>
            <input
              type="text"
              placeholder="Filter by session ID..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
            />
          </label>

          <label className="uw-field" style={{ flex: 1 }}>
            <span>Filter Type</span>
            <select value={filterKind} onChange={e => setFilterKind(e.target.value)}>
              <option value="all">All Sessions</option>
              <option value="real">Real Captures</option>
              <option value="live">Live Biofeedback</option>
              <option value="test-only">Test-Only Samples</option>
              <option value="demo">Demo Sessions</option>
            </select>
          </label>
        </div>
      </div>

      <section className="uw-card" aria-label="Session history">
        <div className="uw-card-header"><h3>Session History</h3></div>
        <div className="uw-list">
          {filteredSessions.map(session => {
            const display = formatSession(session);
            return (
              <button
                type="button"
                key={session.id}
                className={'uw-session-row ' + (selectedSession === session.id ? 'chosen' : '')}
                aria-current={selectedSession === session.id ? 'true' : undefined}
                aria-label={'Select session ' + session.id}
                disabled={!!busy || !onSelectSession}
                onClick={() => onSelectSession(session.id)}
              >
                <div><strong>{session.id}</strong><small>{session.kind} · {session.status}</small></div>
                <span>{display.badge}</span><span>{display.count} sources</span>
              </button>
            );
          })}
          {!filteredSessions.length && <p role="status" className="uw-empty">No sessions match these filters.</p>}
        </div>
      </section>

      {selectedIsUnverifiedLive && (
        <p role="alert">
          EVIDENCE_UNVERIFIED: this legacy live session is readable as inventory only. Motion and research report generation/downloads are disabled.
        </p>
      )}

      <div className="uw-two">
        {/* Left Column: Artifacts List */}
        <div className="uw-card">
          <div className="uw-card-header">
            <div>
              <div className="uw-overline">AVAILABLE ARTIFACTS</div>
              <h3>Evidence Documents & Exports</h3>
              <p>For active session: <strong>{selectedSession || 'None'}</strong></p>
            </div>
          </div>

          <div className="uw-list">
            {reports.length > 0 ? (
              reports.map(item => {
                const isPdf = item.filename.endsWith('.pdf');
                const isCsv = item.filename.endsWith('.csv');
                return (
                  <div key={item.key} className="uw-report-row">
                    <div>
                      <strong>{item.filename}</strong>
                      <small>
                        {item.type} · {formatBytes(item.bytes)} · Local
                      </small>
                    </div>
                    <button
                      type="button"
                      className={`uw-btn ${isPdf ? 'primary' : ''}`}
                      disabled={!!busy || selectedIsUnverifiedLive}
                      onClick={() => onDownloadReport(item)}
                    >
                      Download {isPdf ? 'PDF' : (isCsv ? 'CSV' : '')}
                    </button>
                  </div>
                );
              })
            ) : (
              <div className="uw-empty">
                <span aria-hidden="true">▤</span>
                <strong>No Report Artifacts Yet</strong>
                <p>Click "Generate Offline Research Reports" above to produce the PDF, CSV, and JSON bundle.</p>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Compatible Session Comparison & Offline Backup */}
        <div className="uw-column-stack">
          {/* Comparison Studio */}
          <div className="uw-card">
            <div className="uw-card-header">
              <div>
                <div className="uw-overline">SESSION COMPARISON ENGINE</div>
                <h3>Compare Compatible Sessions</h3>
                <p>Compares confirmed subject, task and protocol metadata, model and calibration digests, and native angular ranges.</p>
              </div>
            </div>

            <div className="uw-form-inline">
              <label className="uw-field" style={{ flex: 2 }}>
                <span>Compare Active With:</span>
                <select
                  value={compareTarget}
                  onChange={e => setCompareTarget(e.target.value)}
                  disabled={!selectedSession}
                >
                  <option value="">Select compatible session...</option>
                  {sessions
                    .filter(s => s.id !== selectedSession)
                    .map(s => (
                      <option key={s.id} value={s.id}>
                        {s.id} ({s.kind})
                      </option>
                    ))}
                </select>
              </label>

              <button
                type="button"
                className="uw-btn"
                disabled={!pairObserved || !!busy || isComparing}
                onClick={handleCompare}
              >
                {isComparing ? 'Comparing...' : 'Compare'}
              </button>
            </div>

            {pairPresent && !pairObserved && <p role="status" className="uw-help">
              Comparison unavailable: {pairRows.filter(row => !hasComparisonSourceObservation(row))
                .map(row => `${row.id}: ${row.research_source_revision?.reason || 'COMPARISON_SOURCE_UNKNOWN'}`).join('; ')}.
              A current bounded source observation is required; it does not verify recording evidence.
            </p>}
            {visibleError && <p role="alert" className="uw-help">Comparison unavailable: {visibleError}</p>}
            {visibleResult && comparisonView(visibleResult)}
          </div>

          {/* Offline Backup & Restore Card */}
          <div className="uw-card">
            <div className="uw-card-header">
              <div>
                <div className="uw-overline">OFFLINE DISASTER RECOVERY</div>
                <h3>Backup & Restore</h3>
                <p>Keep sessions, saved synthetic recordings and audit history together in a verified local backup.</p>
              </div>
            </div>

            <div className="uw-actions">
              <button
                type="button"
                className="uw-btn"
                disabled={!!busy}
                onClick={onCreateBackup}
              >
                Create Backup Archive
              </button>
            </div>

            <section aria-label="Backup scheduling status" aria-live="polite">
              <h4>Scheduling and recovery monitoring</h4>
              {scheduleError ? <p role="alert">{scheduleError}</p> : !schedule ? <p>Loading backup status…</p> : <>
                <BackupScheduleStatus schedule={schedule} />
              </>}
              <button type="button" className="uw-btn" onClick={() => setScheduleRefresh(value => value + 1)}>Refresh backup status</button>
            </section>
            <div className="uw-form-inline" style={{ marginTop: '14px' }}>
              <label className="uw-field" style={{ flex: 2 }}>
                <span>Restore From Archive (in projects/backups/)</span>
                <input
                  type="text"
                  placeholder="e.g. kinelab-backup-20261027.zip"
                  value={backupRestoreName}
                  onChange={e => setBackupRestoreName(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="uw-btn danger"
                disabled={!backupRestoreName || !!busy}
                onClick={() => onRestoreBackup(backupRestoreName)}
              >
                Restore
              </button>
            </div>
            <small className="uw-help">
              Complete backups recover to a separate folder, including their database and audit history. Your active workspace stays unchanged. Legacy archives import new sessions only, without their database or audit history. Existing data is never overwritten.
            </small>
          </div>
        </div>
      </div>
    </div>
  );
}
