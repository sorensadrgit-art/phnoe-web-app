const METADATA_SCHEMA = 'kinelab.session-metadata.v1';
const FIELDS = ['subject_id', 'operator_id', 'task_id', 'protocol_id', 'protocol_version', 'laterality'];
const KEYS = ['schema', ...FIELDS, 'confirmed', 'confirmed_at'];
const SLUG = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;
const SIDES = ['left', 'right', 'bilateral', 'not_applicable'];

export function metadataFieldsValid(value) {
  return value !== null && typeof value === 'object'
    && typeof value.subject_id === 'string' && /^sub-[0-9a-f]{32}$/.test(value.subject_id)
    && typeof value.operator_id === 'string' && /^op-[0-9a-f]{32}$/.test(value.operator_id)
    && ['task_id', 'protocol_id', 'protocol_version'].every(key => typeof value[key] === 'string' && SLUG.test(value[key]))
    && SIDES.includes(value.laterality);
}

export function isValidSessionMetadata(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === KEYS.length && KEYS.every(key => Object.hasOwn(value, key))
    && value.schema === METADATA_SCHEMA && metadataFieldsValid(value) && value.confirmed === true
    && typeof value.confirmed_at === 'string'
    && /(?:Z|[+-]\d{2}:\d{2})$/.test(value.confirmed_at) && Number.isFinite(Date.parse(value.confirmed_at));
}

export function buildSessionMetadata(fields, confirmed, confirmedAt = new Date().toISOString()) {
  const value = { schema: METADATA_SCHEMA,
    ...Object.fromEntries(FIELDS.map(key => [key, fields[key]])), confirmed, confirmed_at: confirmedAt };
  if (!isValidSessionMetadata(value)) throw Error('Explicit valid opaque metadata and confirmation are required.');
  return Object.freeze(value);
}

export function newOpaqueId(prefix, source = globalThis.crypto) {
  if (!['sub-', 'op-'].includes(prefix) || typeof source?.randomUUID !== 'function')
    throw Error('Secure ID generation is unavailable. Enter an existing approved opaque ID.');
  const value = source.randomUUID().replaceAll('-', '').toLowerCase();
  if (!/^[0-9a-f]{32}$/.test(value)) throw Error('Secure ID generation returned an invalid identifier.');
  return prefix + value;
}

export function metadataConfirmationMatches(value, sessionId, expected) {
  if (!sessionId || value?.schema !== 'kinelab.session-metadata-readback.v1'
      || value.session_id !== sessionId || value.status !== 'AVAILABLE'
      || !isValidSessionMetadata(value.metadata)
      || !['session.json', 'session-template.json'].includes(value.source?.path)
      || typeof value.source?.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.source.sha256)) return false;
  return expected === undefined || (isValidSessionMetadata(expected)
    && KEYS.every(key => value.metadata[key] === expected[key]));
}

const STATE_KEYS = ['schema', 'session_id', 'status', 'metadata', 'initial_metadata', 'origin', 'head', 'context_sha256', 'reason'];
const DIGEST = /^[0-9a-f]{64}$/;
const HEAD_PATH = /^metadata-revisions\/revision-[0-9a-f]{32}\/revision\.json$/;
const exactKeys = (value, keys) => value !== null && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const digest = value => typeof value === 'string' && DIGEST.test(value);
const sameMetadata = (a, b) => isValidSessionMetadata(a) && isValidSessionMetadata(b) && KEYS.every(key => a[key] === b[key]);

export const METADATA_FIELDS = Object.freeze([...FIELDS]);

// Null unless the full resolver state, its outer list/detail projection and the
// requested session all agree. The initial confirmation is never a fallback.
export function currentMetadataState(record, sessionId) {
  const state = record?.metadata_state;
  if (!sessionId || record?.id !== sessionId || !exactKeys(state, STATE_KEYS)
      || state.schema !== 'kinelab.session-metadata-state.v1' || state.session_id !== sessionId
      || state.status !== 'AVAILABLE' || typeof state.reason !== 'string'
      || !isValidSessionMetadata(state.metadata) || !isValidSessionMetadata(state.initial_metadata)
      || !exactKeys(state.origin, ['path', 'sha256']) || state.origin.path !== 'session.json' || !digest(state.origin.sha256)
      || !(state.head === null || (exactKeys(state.head, ['path', 'sha256'])
        && typeof state.head.path === 'string' && HEAD_PATH.test(state.head.path) && digest(state.head.sha256)))
      || !digest(state.context_sha256)
      || !sameMetadata(record.effective_metadata, state.metadata)
      || record.metadata_context_sha256 !== state.context_sha256) return null;
  return { state, metadata: state.metadata, context: state.context_sha256 };
}

export function unavailableMetadataReason(record, sessionId) {
  const state = record?.metadata_state;
  return sessionId && record?.id === sessionId && state?.schema === 'kinelab.session-metadata-state.v1'
    && state.session_id === sessionId && state.status === 'UNAVAILABLE' && typeof state.reason === 'string' ? state.reason : '';
}

export function newOperationId(source = globalThis.crypto) {
  if (typeof source?.randomUUID !== 'function') throw Error('Secure operation ID generation is unavailable. No correction was sent.');
  const value = source.randomUUID().replaceAll('-', '').toLowerCase();
  if (!/^[0-9a-f]{32}$/.test(value)) throw Error('Secure operation ID generation returned an invalid identifier. No correction was sent.');
  return value;
}

// Binds the service receipt to this submitted operation and Python's canonical
// content-only metadata context; this does not authenticate descriptor bytes.
export async function metadataRevisionReceiptMatches(value, sessionId, request) {
  if (typeof sessionId !== 'string' || !sessionId
      || !exactKeys(value, ['schema', 'session_id', 'operation_id', 'revision_id', 'descriptor', 'context_sha256'])
      || value.schema !== 'kinelab.session-metadata-revision-receipt.v1' || value.session_id !== sessionId
      || typeof request?.operation_id !== 'string' || !/^[0-9a-f]{32}$/.test(request.operation_id)
      || value.operation_id !== request.operation_id
      || typeof value.revision_id !== 'string' || !/^[0-9a-f]{32}$/.test(value.revision_id)
      || !exactKeys(value.descriptor, ['path', 'sha256'])
      || value.descriptor.path !== 'metadata-revisions/revision-' + value.revision_id + '/revision.json'
      || !digest(value.descriptor.sha256) || !digest(value.context_sha256)
      || !digest(request.expected_origin_sha256)) return false;
  try {
    // Explicit key order matches sort_keys=True; ASCII escaping also matches
    // ensure_ascii=True (including surrogate pairs), with compact separators.
    const canonical = JSON.stringify({
      head: { path: value.descriptor.path, sha256: value.descriptor.sha256 },
      origin: { path: 'session.json', sha256: request.expected_origin_sha256 },
      schema: 'kinelab.session-metadata-context.v1', session_id: sessionId,
    }).replace(/[\u007f-\uffff]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'));
    const bytes = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
    const computed = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
    return computed === value.context_sha256;
  } catch {
    return false;
  }
}
