import React, { useState } from 'react';
import { formatBytes, formatSession } from './unifiedModel.js';

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
  onRestoreBackup,
  onOpenFolder
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterKind, setFilterKind] = useState('all');
  const [compareTarget, setCompareTarget] = useState('');
  const [compareResult, setCompareResult] = useState(null);
  const [backupRestoreName, setBackupRestoreName] = useState('');

  const filteredSessions = sessions.filter(s => {
    const matchesSearch = s.id.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesKind = filterKind === 'all' || s.kind === filterKind;
    return matchesSearch && matchesKind;
  });

  const handleCompare = async () => {
    if (!selectedSession || !compareTarget || selectedSession === compareTarget) return;
    try {
      const res = await onCompareSessions(selectedSession, compareTarget);
      setCompareResult(res);
    } catch {
      setCompareResult(null);
    }
  };

  return (
    <div className="uw-report-studio">
      {/* Top Controls: Search, Filter, Generate */}
      <div className="uw-card">
        <div className="uw-card-header">
          <div>
            <div className="uw-overline">T7 LOCAL RESEARCH REPORTING STUDIO</div>
            <h3>Reports, Session History & Offline Backups</h3>
            <p>Export truthful vector PDF, JSON provenance summary, and CSV data. Offline-first.</p>
          </div>
          <div className="uw-actions">
            <button
              type="button"
              className="uw-btn primary"
              disabled={!!busy || !selectedSession}
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
              <option value="test-only">Test-Only Samples</option>
              <option value="demo">Demo Sessions</option>
            </select>
          </label>
        </div>
      </div>

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
                      disabled={!!busy}
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
                <p>Compares capture geometry, calibration status, and quality.</p>
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
                disabled={!selectedSession || !compareTarget || !!busy}
                onClick={handleCompare}
              >
                Compare
              </button>
            </div>

            {compareResult && (
              <div className={`uw-compare-result ${compareResult.compatible ? 'is-compatible' : 'is-incompatible'}`}>
                <div className="uw-compare-header">
                  <strong>Compatibility Verdict:</strong>
                  <span className={`uw-pill ${compareResult.compatible ? 'uw-pill-present' : 'uw-pill-warning'}`}>
                    {compareResult.compatible ? 'COMPATIBLE' : 'INCOMPATIBLE'}
                  </span>
                </div>
                <p className="uw-compare-reason">{compareResult.reason}</p>
                <div className="uw-stat-grid" style={{ marginTop: '12px' }}>
                  <div className="uw-stat">
                    <span>{compareResult.session_1}</span>
                    <strong>{compareResult.metrics.state_1}</strong>
                    <small>{compareResult.metrics.captured_1}/6 sources</small>
                  </div>
                  <div className="uw-stat">
                    <span>{compareResult.session_2}</span>
                    <strong>{compareResult.metrics.state_2}</strong>
                    <small>{compareResult.metrics.captured_2}/6 sources</small>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Offline Backup & Restore Card */}
          <div className="uw-card">
            <div className="uw-card-header">
              <div>
                <div className="uw-overline">OFFLINE DISASTER RECOVERY</div>
                <h3>Backup & Restore</h3>
                <p>Self-contained ZIP archive with SQLite DB and SHA-256 manifest.</p>
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
              Restores to isolated staging first, verifies 100% of file hashes, and previews conflicts.
            </small>
          </div>
        </div>
      </div>
    </div>
  );
}
