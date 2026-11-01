import React, { useEffect, useState } from 'react';
import { buildSessionMetadata, metadataConfirmationMatches, metadataFieldsValid, newOpaqueId } from './sessionMetadataSetup.js';

const EMPTY = { subject_id: '', operator_id: '', task_id: '', protocol_id: '', protocol_version: '', laterality: '' };

export function MetadataConfirmationSummary({ confirmation, sessionId }) {
  if (!metadataConfirmationMatches(confirmation, sessionId)) {
    const reason = confirmation?.schema === 'kinelab.session-metadata-readback.v1'
      && confirmation.session_id === sessionId && typeof confirmation.reason === 'string' ? confirmation.reason : '';
    return <p role="status" className="uw-help">
      Metadata confirmation: UNAVAILABLE. This session has no verified persisted metadata readback. {reason}
      Existing source files are preserved. Inspect the local session before further work.
    </p>;
  }
  const value = confirmation.metadata;
  return <section className="uw-card" aria-label="Persisted session metadata">
    <p role="status">Metadata confirmation: AVAILABLE · operator reported</p>
    <dl>
      <dt>Subject ID</dt><dd>{value.subject_id}</dd><dt>Operator ID</dt><dd>{value.operator_id}</dd>
      <dt>Task ID</dt><dd>{value.task_id}</dd><dt>Protocol</dt><dd>{value.protocol_id} · {value.protocol_version}</dd>
      <dt>Laterality</dt><dd>{value.laterality}</dd><dt>Confirmed at</dt><dd>{value.confirmed_at}</dd>
    </dl>
    <p className="uw-help">Read from {confirmation.source.path} · SHA-256 {confirmation.source.sha256}.
      Opaque IDs and operator confirmation do not establish identity authentication, protocol approval, physical validity or permission to record.</p>
  </section>;
}

export default function SessionMetadataSetup({ sessionId = '', onSessionIdChange, onCreate, busy = false }) {
  const [fields, setFields] = useState({ ...EMPTY });
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setConfirmed(false); }, [sessionId]);
  const update = (name, value) => {
    if (busy) return;
    setFields(previous => ({ ...previous, [name]: value })); setConfirmed(false); setError('');
  };
  const generate = (name, prefix) => {
    if (busy) return;
    try { update(name, newOpaqueId(prefix)); } catch (failure) { setError(failure.message); }
  };
  const valid = !!sessionId.trim() && metadataFieldsValid(fields) && confirmed;
  const submit = event => {
    event.preventDefault();
    if (busy || !valid) return;
    try { return onCreate(buildSessionMetadata(fields, confirmed)); }
    catch (failure) { setError(failure.message); }
  };
  return <form onSubmit={submit} aria-label="Initial session metadata" className="uw-form-inline">
    <label className="uw-field"><span>Unique session ID</span><input name="session_id" value={sessionId}
      disabled={!!busy} maxLength={100} placeholder="e.g. gait-pilot-01"
      onChange={event => { if (!busy) { setConfirmed(false); onSessionIdChange?.(event.target.value); } }}/></label>
    <p className="uw-help">Use opaque identifiers only. Do not enter names, contact details or medical record numbers.
      Reuse the same approved opaque subject ID for an intended comparison. Generate an ID only when deliberately creating a new identity.</p>
    {[
      ['subject_id', 'Subject ID', 'sub-'], ['operator_id', 'Operator ID', 'op-'],
      ['task_id', 'Task ID'], ['protocol_id', 'Protocol ID'], ['protocol_version', 'Protocol version'],
    ].map(([name, label, prefix]) => <div key={name}>
      <label className="uw-field"><span>{label}</span><input name={name} value={fields[name]} disabled={!!busy}
        maxLength={100} autoComplete="off" onChange={event => update(name, event.target.value)}/></label>
      {prefix && <button type="button" className="uw-btn" disabled={!!busy}
        onClick={() => generate(name, prefix)}>Generate {name === 'subject_id' ? 'subject' : 'operator'} ID</button>}
    </div>)}
    <label className="uw-field"><span>Laterality</span><select name="laterality" value={fields.laterality}
      disabled={!!busy} onChange={event => update('laterality', event.target.value)}>
      <option value="">Select laterality</option><option value="left">Left</option><option value="right">Right</option>
      <option value="bilateral">Bilateral</option><option value="not_applicable">Not applicable</option>
    </select></label>
    <label><input type="checkbox" name="metadata_confirmed" checked={confirmed} disabled={!!busy}
      onChange={event => { if (!busy) setConfirmed(event.target.checked === true); }}/>
      I checked these subject, operator, task, protocol and laterality identifiers for this session.</label>
    <p className="uw-help">This initial operator report is stored with the new session. Identity authentication, protocol approval and physical checks remain unverified. Participant capture stays blocked.</p>
    {error && <p role="alert">{error}</p>}
    <button type="submit" className="uw-btn primary" disabled={!!busy || !valid}>Create session</button>
  </form>;
}
