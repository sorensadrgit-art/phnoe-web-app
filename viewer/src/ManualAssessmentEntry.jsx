import React, { useEffect, useRef, useState } from 'react';

const HASH = /^[0-9a-f]{64}$/;
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const keys = (value, names) => record(value) && Object.keys(value).sort().join('|') === [...names].sort().join('|');
const integer = (value, upper) => typeof value === 'string' && /^(0|[1-9]\d*)$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) < upper;

function usableContext(value, session, sessionId, metadataHash) {
  if (!record(value) || value.schema !== 'kinelab.manual-assessment-context.v1' || value.status !== 'AVAILABLE' ||
      value.session_id !== sessionId || !HASH.test(metadataHash ?? '') || value.metadata_context_sha256 !== metadataHash ||
      !HASH.test(value.context_sha256 ?? '') || !HASH.test(value.origin_sha256 ?? '') || !HASH.test(value.run_sha256 ?? '') ||
      value.test_only !== true || value.clinical_accuracy_validated !== false ||
      session?.kind !== 'real' || session?.metadata_state?.schema !== 'kinelab.session-metadata-state.v1' || session.metadata_state.status !== 'AVAILABLE' ||
      session.metadata_state.session_id !== sessionId || session.metadata_state.context_sha256 !== metadataHash ||
      session.metadata_state.origin?.sha256 !== value.origin_sha256 ||
      !Array.isArray(value.input_sets) || !value.input_sets.length) return false;
  const ids = new Set();
  return value.input_sets.every(input => {
    if (!record(input) || !HASH.test(input.input_id ?? '') || ids.has(input.input_id) ||
        !['gait', 'squat'].includes(input.kind) || !['cam01_trial', 'cam02_trial'].includes(input.source_role) ||
        !HASH.test(input.source_sha256 ?? '') || !HASH.test(input.trajectory_sha256 ?? '') || !HASH.test(input.candidates_sha256 ?? '') ||
        !Number.isSafeInteger(input.frames) || input.frames < 1 ||
        !Array.isArray(input.image_size) || input.image_size.length !== 2 || !input.image_size.every(n => Number.isSafeInteger(n) && n > 0)) return false;
    ids.add(input.input_id);
    return true;
  });
}

function referenceLabels(input, rows) {
  const limit = input?.kind === 'gait' ? 256 : 128;
  if (!input || !rows.length || rows.length > limit) return null;
  if (input.kind === 'gait') {
    const seen = new Set();
    const labels = rows.map(row => {
      if (!integer(row.frame, input.frames) || !['left', 'right'].includes(row.side) || !['initial_contact', 'toe_off'].includes(row.event)) return null;
      const key = [row.frame, row.side, row.event].join(':');
      if (seen.has(key)) return null;
      seen.add(key);
      return { frame_index: Number(row.frame), side: row.side, event_type: row.event };
    });
    return labels.every(Boolean) ? labels : null;
  }
  let previousEnd = -1;
  const labels = rows.map(row => {
    if (![row.start, row.bottom, row.end].every(value => integer(value, input.frames))) return null;
    const start = Number(row.start), bottom = Number(row.bottom), end = Number(row.end);
    if (!(previousEnd < start && start < bottom && bottom < end)) return null;
    previousEnd = end;
    return { start_frame: start, bottom_frame: bottom, end_frame: end };
  });
  return labels.every(Boolean) ? labels : null;
}

function boundReceipt(value, sessionId, body) {
  return keys(value, ['schema', 'session_id', 'operation_id', 'metadata_context_sha256', 'descriptor', 'test_only', 'clinical_accuracy_validated']) &&
    value.schema === 'kinelab.manual-assessment-entry-receipt.v1' && value.session_id === sessionId &&
    value.operation_id === body.operation_id && value.metadata_context_sha256 === body.metadata_context_sha256 &&
    value.test_only === true && value.clinical_accuracy_validated === false &&
    keys(value.descriptor, ['path', 'sha256']) && HASH.test(value.descriptor.sha256 ?? '') &&
    value.descriptor.path === `exports/manual-entry-${body.operation_id}.manual-assessment.json`;
}

// The parent keys this subtree by session and verified metadata context. A new
// selection therefore starts blank during render, before request cleanup effects.
export default function ManualAssessmentEntry({ sessionId, session, metadataHash, busy, onLoadContext, onPublish }) {
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);
  const [inputId, setInputId] = useState('');
  const [rows, setRows] = useState([]);
  const [reviewer, setReviewer] = useState('');
  const [tolerance, setTolerance] = useState('');
  const [human, setHuman] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [posting, setPosting] = useState(false);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState(null);
  const alive = useRef(true);
  const flight = useRef(false);
  const retry = useRef(null);
  const epoch = useRef(0);
  const identity = useRef({ sessionId, metadataHash, onLoadContext, onPublish });
  identity.current = { sessionId, metadataHash, onLoadContext, onPublish };
  const labelId = React.useId();

  useEffect(() => {
    alive.current = true;
    epoch.current += 1;
    let active = true;
    const controller = new AbortController();
    setContext(null); setLoading(true); setError('');
    if (!sessionId || typeof onLoadContext !== 'function' || typeof onPublish !== 'function' || !HASH.test(metadataHash ?? '')) {
      setLoading(false);
      setError('MANUAL_ASSESSMENT_UNAVAILABLE: current context and publication callbacks are required.');
    } else {
      Promise.resolve().then(() => onLoadContext(sessionId, { signal: controller.signal })).then(value => {
        if (!active || !alive.current) return;
        if (!usableContext(value, session, sessionId, metadataHash)) {
          setError('MANUAL_ASSESSMENT_UNAVAILABLE: context does not match this session and metadata.');
        } else setContext(value);
        setLoading(false);
      }, reason => {
        if (!active || !alive.current) return;
        setError(String(reason?.message || 'MANUAL_ASSESSMENT_UNAVAILABLE'));
        setLoading(false);
      });
    }
    return () => { active = false; alive.current = false; controller.abort(); };
  }, [sessionId, metadataHash, onLoadContext, onPublish]);

  const available = usableContext(context, session, sessionId, metadataHash);
  const input = available ? context.input_sets.find(item => item.input_id === inputId) : null;
  const labels = referenceLabels(input, rows);
  const reviewerValid = reviewer.length >= 2 && reviewer.length <= 90 && reviewer.trim() === reviewer && !/[\x00-\x1f\x7f]/.test(reviewer);
  const valid = available && labels !== null && reviewerValid && integer(tolerance, 16) && human && confirmed;
  const disabled = Boolean(busy) || posting || loading || !available || stale;
  const changed = () => { setConfirmed(false); setReceipt(null); setError(''); retry.current = null; };
  const changeRow = (index, field, value) => {
    if (disabled || flight.current) return;
    changed(); setRows(current => current.map((row, i) => i === index ? { ...row, [field]: value } : row));
  };
  const edit = (setter, value) => {
    if (disabled || flight.current) return;
    changed(); setter(value);
  };
  const publish = async event => {
    event.preventDefault();
    if (disabled || flight.current || !valid) return;
    let body = retry.current;
    if (!body) {
      if (typeof globalThis.crypto?.randomUUID !== 'function') {
        setError('MANUAL_ASSESSMENT_UNAVAILABLE: secure operation identifiers are unavailable.'); return;
      }
      body = { operation_id: globalThis.crypto.randomUUID().replaceAll('-', ''), context_sha256: context.context_sha256,
        metadata_context_sha256: metadataHash, input_id: input.input_id, source_sha256: input.source_sha256,
        reviewer, annotation_origin: 'human_observed_video_frames', labels, tolerance_frames: Number(tolerance), confirm: true };
      const serialized = JSON.stringify(body);
      if (new TextEncoder().encode(serialized).byteLength > 65536) { setError('MANUAL_ASSESSMENT_INVALID: request exceeds the input limit.'); return; }
      retry.current = JSON.parse(serialized);
    }
    const request = JSON.parse(JSON.stringify(retry.current));
    const requestEpoch = epoch.current;
    const current = () => alive.current && epoch.current === requestEpoch && identity.current.sessionId === sessionId &&
      identity.current.metadataHash === metadataHash && identity.current.onLoadContext === onLoadContext && identity.current.onPublish === onPublish;
    flight.current = true; setPosting(true); setError(''); setReceipt(null);
    try {
      const result = await onPublish(sessionId, request);
      if (!current()) return;
      if (!boundReceipt(result, sessionId, request)) {
        setStale(true); setConfirmed(false);
        setError('MANUAL_ASSESSMENT_UNAVAILABLE: publication receipt binding is invalid.'); return;
      }
      setReceipt(result);
      setConfirmed(false);
      retry.current = null;
    } catch (reason) {
      if (!current()) return;
      const message = String(reason?.message || 'MANUAL_ASSESSMENT_UNAVAILABLE');
      setError(message);
      // An explicit retry retains the exact operation and body. Changes require
      // a new declaration; stale or unavailable context cannot be rebound.
      if (message !== 'MANUAL_ASSESSMENT_BUSY') { setStale(true); setConfirmed(false); }
    } finally {
      flight.current = false;
      if (current()) setPosting(false);
    }
  };

  return <form aria-label="Manual reference entry" className="uw-card" onSubmit={publish}>
    <h2 id={`${labelId}-heading`}>Manual reference entry</h2>
    <p>TEST_ONLY human reference. Physical validity: UNVERIFIED. Clinical accuracy: UNVERIFIED.</p>
    <p>Enter only frames you personally reviewed in the source video. Candidate events and predictions do not fill these observations. Reviewer identity is a declaration, not authentication.</p>
    {loading && <p role="status">Loading manual reference context…</p>}
    {!loading && !available && <p role="status">Manual reference entry UNAVAILABLE.</p>}
    {error && <p role="alert">{error}</p>}
    {stale && <p role="status">Publication unavailable for this context. Preserve your notes separately and reload the current session before a new declaration.</p>}
    {available && <ul aria-label="Bound input sources">{context.input_sets.map(item => <li key={item.input_id}>
      {item.kind} — {item.source_role} — {item.frames} source frames — SHA-256 {item.source_sha256}
    </li>)}</ul>}
    <fieldset disabled={disabled} aria-describedby={`${labelId}-limits`}>
      <legend>Human observations</legend>
      <label>Bound input <select name="manual_input_id" value={inputId} disabled={disabled} onChange={event => {
        if (disabled || flight.current) return;
        changed(); setInputId(event.target.value); setRows([]);
      }}><option value="">Select a verified source</option>{available && context.input_sets.map(item => <option key={item.input_id} value={item.input_id}>{item.kind} / {item.source_role} / {item.frames} frames</option>)}</select></label>
      <p id={`${labelId}-limits`}>Frame indices start at 0 and must be below the source frame count. Gait: at most 256 distinct events. Squat: at most 128 ordered, non-overlapping intervals. Matching tolerance is an explicit reference input (0–15 frames), not a clinical threshold.</p>
      {rows.map((row, index) => <fieldset key={index} disabled={disabled}>
        <legend>Annotation {index + 1}</legend>
        {input?.kind === 'gait' ? <>
          <label>Frame index <input name={`manual_frame_${index}`} inputMode="numeric" value={row.frame} disabled={disabled} onChange={event => changeRow(index, 'frame', event.target.value)} /></label>
          <label>Side <select name={`manual_side_${index}`} value={row.side} disabled={disabled} onChange={event => changeRow(index, 'side', event.target.value)}><option value="">Select side</option><option value="left">Left</option><option value="right">Right</option></select></label>
          <label>Observed event <select name={`manual_event_${index}`} value={row.event} disabled={disabled} onChange={event => changeRow(index, 'event', event.target.value)}><option value="">Select event</option><option value="initial_contact">Initial contact</option><option value="toe_off">Toe off</option></select></label>
        </> : <>{['start', 'bottom', 'end'].map(field => <label key={field}>{field} frame <input name={`manual_${field}_${index}`} inputMode="numeric" value={row[field]} disabled={disabled} onChange={event => changeRow(index, field, event.target.value)} /></label>)}</>}
        <button type="button" disabled={disabled} onClick={() => {
          if (disabled || flight.current) return;
          changed(); setRows(current => current.filter((_, i) => i !== index));
        }}>Remove annotation {index + 1}</button>
      </fieldset>)}
      <button type="button" disabled={disabled || !input || rows.length >= (input.kind === 'gait' ? 256 : 128)} onClick={() => {
        if (disabled || flight.current || !input || rows.length >= (input.kind === 'gait' ? 256 : 128)) return;
        changed(); setRows(current => [...current, input.kind === 'gait' ? { frame: '', side: '', event: '' } : { start: '', bottom: '', end: '' }]);
      }}>Add annotation</button>
      <label>Reviewer declaration <input name="manual_reviewer" value={reviewer} maxLength={90} disabled={disabled} onChange={event => edit(setReviewer, event.target.value)} /></label>
      <label>Matching tolerance in frames <input name="manual_tolerance_frames" inputMode="numeric" value={tolerance} disabled={disabled} onChange={event => edit(setTolerance, event.target.value)} /></label>
      <label><input type="checkbox" name="manual_human_observed" checked={human} disabled={disabled} onChange={event => edit(setHuman, event.target.checked)} /> I personally observed these source video frames; these annotations are not generated predictions.</label>
      <label><input type="checkbox" name="manual_confirmed" checked={confirmed} disabled={disabled} onChange={event => {
        if (disabled || flight.current) return;
        setConfirmed(event.target.checked); setReceipt(null); setError('');
      }} /> I confirm this exact reference and its current session, source and metadata binding.</label>
    </fieldset>
    <button type="submit" disabled={disabled || !valid}>{posting ? 'Publishing reference…' : retry.current ? 'Retry exact reference publication' : 'Publish manual reference'}</button>
    {receipt && <p role="status">TEST_ONLY server publication receipt: {receipt.descriptor.path} — SHA-256 {receipt.descriptor.sha256}. Physical and clinical validity remain UNVERIFIED.</p>}
  </form>;
}
