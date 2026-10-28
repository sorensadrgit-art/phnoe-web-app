import React, { useState } from 'react';

export default function LiveSetSummaryModal({
  summary,
  onSaveToSessions,
  onExportJSON,
  onClose,
  onStartNewSet,
  isSaving = false,
  saveResult = null,
}) {
  const [patientId, setPatientId] = useState('PT-PATIENT-01');

  if (!summary) return null;

  const {
    exerciseType = 'Squat',
    totalReps = 0,
    validReps = 0,
    averageDepth = 0,
    bestDepth = 0,
    targetDepth = 80,
    averageSymmetry = 100,
    durationSeconds = 0,
    faultsLog = [],
  } = summary;

  const validPct = totalReps > 0 ? Math.round((validReps / totalReps) * 100) : 0;
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = durationSeconds % 60;
  const timeFormatted = `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;

  return (
    <div className="uw-modal-backdrop" style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(5, 10, 24, 0.82)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: 16,
    }}>
      <div className="uw-modal-card" style={{
        background: '#0d1527',
        border: '1px solid rgba(0, 243, 255, 0.25)',
        borderRadius: 12,
        width: '100%',
        maxWidth: 620,
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.75)',
        overflow: 'hidden',
        color: '#f8fafc',
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div>
            <div style={{ color: '#00f3ff', fontSize: '0.75rem', fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
              SET COMPLETED · TELEMETRY SUMMARY
            </div>
            <h2 style={{ margin: '4px 0 0', fontSize: '1.4rem', fontWeight: 700 }}>
              {exerciseType.toUpperCase()} PERFORMANCE
            </h2>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              fontSize: '1.5rem',
              cursor: 'pointer',
              lineHeight: 1,
            }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: '20px 24px', maxHeight: '70vh', overflowY: 'auto' }}>
          {/* Key Metrics Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 12,
            marginBottom: 20,
          }}>
            <div style={{ background: '#131e36', padding: '12px 14px', borderRadius: 8, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', textTransform: 'uppercase' }}>Total Reps</span>
              <strong style={{ fontSize: '1.6rem', color: '#ffffff', fontWeight: 800 }}>{totalReps}</strong>
              <small style={{ fontSize: '0.75rem', color: '#10b981', display: 'block' }}>{validReps} clean ({validPct}%)</small>
            </div>

            <div style={{ background: '#131e36', padding: '12px 14px', borderRadius: 8, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', textTransform: 'uppercase' }}>Average Depth</span>
              <strong style={{ fontSize: '1.6rem', color: '#38bdf8', fontWeight: 800 }}>{averageDepth}°</strong>
              <small style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block' }}>Target: {targetDepth}°</small>
            </div>

            <div style={{ background: '#131e36', padding: '12px 14px', borderRadius: 8, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', textTransform: 'uppercase' }}>Best Depth</span>
              <strong style={{ fontSize: '1.6rem', color: '#10b981', fontWeight: 800 }}>{bestDepth}°</strong>
              <small style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block' }}>Peak flexion</small>
            </div>

            <div style={{ background: '#131e36', padding: '12px 14px', borderRadius: 8, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'block', textTransform: 'uppercase' }}>Set Time</span>
              <strong style={{ fontSize: '1.6rem', color: '#f8fafc', fontWeight: 800 }}>{timeFormatted}</strong>
              <small style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block' }}>Active tracking</small>
            </div>
          </div>

          {/* Symmetry Bar */}
          <div style={{ background: '#131e36', padding: '14px 16px', borderRadius: 8, marginBottom: 20, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: '0.85rem' }}>
              <span style={{ fontWeight: 600 }}>Bilateral Movement Symmetry</span>
              <span style={{ color: averageSymmetry >= 80 ? '#10b981' : '#f59e0b', fontWeight: 700 }}>
                {averageSymmetry}% {averageSymmetry >= 85 ? '(Balanced)' : '(Mild Asymmetry)'}
              </span>
            </div>
            <div style={{ width: '100%', height: 8, background: '#1e293b', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{
                width: `${averageSymmetry}%`,
                height: '100%',
                background: averageSymmetry >= 80 ? 'linear-gradient(90deg, #0284c7, #10b981)' : '#f59e0b',
                borderRadius: 4,
                transition: 'width 0.4s ease',
              }} />
            </div>
          </div>

          {/* Form Fault Log */}
          <div style={{ marginBottom: 20 }}>
            <h4 style={{ margin: '0 0 10px', fontSize: '0.9rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Form Fault Diagnostics ({faultsLog.length})
            </h4>
            {faultsLog.length === 0 ? (
              <div style={{ background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', padding: 12, borderRadius: 6, color: '#34d399', fontSize: '0.9rem' }}>
                ✓ Clean form! No compensations or kinematic faults detected.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {faultsLog.map(({ fault, count, percentage }) => (
                  <div key={fault} style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    background: '#131e36',
                    padding: '8px 12px',
                    borderRadius: 6,
                    border: '1px solid rgba(239, 68, 68, 0.2)',
                  }}>
                    <span style={{ color: '#f87171', fontWeight: 600, fontSize: '0.85rem' }}>
                      ⚠ {fault.replace('_', ' ')}
                    </span>
                    <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                      {count} rep{count > 1 ? 's' : ''} ({percentage}%)
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Ingestion & Patient Config */}
          <div style={{ background: '#131e36', padding: '14px 16px', borderRadius: 8, border: '1px solid rgba(0, 243, 255, 0.15)' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: 6 }}>
              PATIENT / SUBJECT RECORD ID
            </label>
            <input
              type="text"
              value={patientId}
              onChange={(e) => setPatientId(e.target.value)}
              placeholder="e.g. PT-PATIENT-01"
              style={{
                width: '100%',
                padding: '8px 12px',
                background: '#0a0f1d',
                border: '1px solid #334155',
                borderRadius: 6,
                color: '#ffffff',
                fontSize: '0.9rem',
                outline: 'none',
              }}
            />
          </div>

          {saveResult && (
            <div style={{
              marginTop: 14,
              padding: 12,
              borderRadius: 6,
              background: saveResult.ok ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
              border: `1px solid ${saveResult.ok ? '#10b981' : '#ef4444'}`,
              color: saveResult.ok ? '#34d399' : '#f87171',
              fontSize: '0.85rem',
            }}>
              {saveResult.message || (saveResult.ok ? 'Successfully saved session!' : 'Failed to save session')}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div style={{
          padding: '16px 24px',
          background: '#090e1c',
          borderTop: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 10,
        }}>
          <button
            type="button"
            onClick={onExportJSON}
            style={{
              background: 'transparent',
              border: '1px solid #475569',
              color: '#94a3b8',
              padding: '8px 14px',
              borderRadius: 6,
              fontSize: '0.85rem',
              cursor: 'pointer',
            }}
          >
            Export JSON
          </button>

          <div style={{ display: 'flex', gap: 10 }}>
            <button
              type="button"
              onClick={onStartNewSet}
              style={{
                background: '#1e293b',
                border: '1px solid #334155',
                color: '#f8fafc',
                padding: '8px 16px',
                borderRadius: 6,
                fontSize: '0.85rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Start New Set
            </button>

            <button
              type="button"
              onClick={() => onSaveToSessions(patientId)}
              disabled={isSaving}
              style={{
                background: isSaving ? '#64748b' : 'linear-gradient(135deg, #0284c7 0%, #00f3ff 100%)',
                border: 'none',
                color: '#0a0f1d',
                padding: '8px 20px',
                borderRadius: 6,
                fontSize: '0.85rem',
                fontWeight: 800,
                cursor: isSaving ? 'wait' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {isSaving ? 'Saving...' : 'Save to KineLab Sessions'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
