const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const finite = value => typeof value === 'number' && Number.isFinite(value);
const text = value => typeof value === 'string' ? value : '';
const hash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(value);
const exactKeys = (value, keys) => record(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const absentOr = (value, expected) => value === undefined || value === expected;
const metadataFields = ['schema', 'subject_id', 'operator_id', 'task_id', 'protocol_id', 'protocol_version', 'laterality', 'confirmed', 'confirmed_at'];
const matchingFields = ['subject_id', 'task_id', 'protocol_id', 'protocol_version', 'laterality', 'model_sha256', 'calibration_sha256', 'coordinate_system'];
const revisionHashes = ['session_sha256', 'run_sha256', 'motion_sha256', 'model_sha256', 'calibration_sha256', 'trc_sha256', 'mot_sha256'];
const captureRoles = ['cam01_intrinsics', 'cam02_intrinsics', 'cam01_board', 'cam02_board', 'cam01_trial', 'cam02_trial'];
const coordinateFields = ['name', 'unit', 'session_1', 'session_2'];
const FIXTURE_KIND = 'GENERATED_CONTRACT_FIXTURE_ONLY';
const PROVENANCE_LABELS = {
  [FIXTURE_KIND]: 'Generated TEST_ONLY research contract fixture; not a recording',
  PROVENANCE_UNVERIFIED: 'Local research service response; recording provenance not independently verified',
};

export const CAPTURE_ROLE_COUNT = captureRoles.length;

export function hasComparisonSourceObservation(session) {
  const observation = session?.research_source_revision;
  return exactKeys(observation, ['schema', 'status', 'token', 'reason', 'evidence_verified']) &&
    observation.schema === 'kinelab.comparison-source-observation.v1' && observation.status === 'AVAILABLE' &&
    hash(observation.token) && observation.reason === null && observation.evidence_verified === false;
}

export function formatCoordinateValue(value, unit) {
  if (!finite(value) || !['deg', 'rad'].includes(unit)) return 'UNAVAILABLE';
  // Below one unit keep three significant digits; fixed decimals would show small radian values as 0.
  const shown = value !== 0 && Math.abs(value) < 1 ? Number(value.toPrecision(3)) : Number(value.toFixed(2));
  return String(shown) + ' ' + unit;
}

export function formatCoordinateDifference(value, unit) {
  const formatted = formatCoordinateValue(value, unit);
  return formatted !== 'UNAVAILABLE' && value > 0 ? '+' + formatted : formatted;
}

function validSession(source) {
  if (!record(source) || typeof source.session_id !== 'string') return false;
  const { metadata: m, contract: c, source_revision: r } = source;
  if (!exactKeys(m, metadataFields) || m.schema !== 'kinelab.session-metadata.v1' ||
      !/^sub-[0-9a-f]{32}$/.test(m.subject_id) || !/^op-[0-9a-f]{32}$/.test(m.operator_id) ||
      !['task_id', 'protocol_id', 'protocol_version'].every(key => identifier(m[key])) ||
      !['left', 'right', 'bilateral', 'not_applicable'].includes(m.laterality) || m.confirmed !== true ||
      typeof m.confirmed_at !== 'string' || !/[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})$/.test(m.confirmed_at) ||
      !Number.isFinite(Date.parse(m.confirmed_at))) return false;
  if (!exactKeys(c, [...matchingFields, 'units']) ||
      !['subject_id', 'task_id', 'protocol_id', 'protocol_version', 'laterality'].every(key => c[key] === m[key]) ||
      !hash(c.model_sha256) || !hash(c.calibration_sha256) || typeof c.coordinate_system !== 'string' || !c.coordinate_system ||
      !record(c.units) || !Object.keys(c.units).length || !Object.values(c.units).every(unit => ['deg', 'rad'].includes(unit))) return false;
  return exactKeys(r, [...revisionHashes, 'capture_sha256']) && revisionHashes.every(key => hash(r[key])) &&
    r.model_sha256 === c.model_sha256 && r.calibration_sha256 === c.calibration_sha256 &&
    exactKeys(r.capture_sha256, captureRoles) && captureRoles.every(role => hash(r.capture_sha256[role]));
}

function validRange(value) {
  if (!exactKeys(value, ['min', 'max', 'excursion']) || !Object.values(value).every(finite) || value.min > value.max) return false;
  const excursion = value.max - value.min;
  return Number.isFinite(excursion) && value.excursion >= 0 &&
    Math.abs(value.excursion - excursion) <= Number.EPSILON * Math.max(1, excursion, value.excursion) * 8;
}

// undefined means malformed; null means the producer did not report a count.
function captureCount(value) {
  if (value === undefined) return null;
  return Number.isSafeInteger(value) && value >= 0 && value <= CAPTURE_ROLE_COUNT ? value : undefined;
}

const stateLabel = value => typeof value === 'string' && /^[A-Z0-9_]{1,64}$/.test(value) ? value : 'UNAVAILABLE';

function passportSummary(passport, sessionId) {
  if (!record(passport) || passport.session_id !== sessionId || passport.clinically_validated !== false ||
      passport.physical_accuracy_verified !== false || typeof passport.is_test_only !== 'boolean') return null;
  const captured = captureCount(passport.captured_count);
  if (captured === undefined) return null;
  return { session_id: sessionId, state: stateLabel(passport.state), is_test_only: passport.is_test_only, captured_count: captured };
}

const range = value => ({ min: value.min, max: value.max, excursion: value.excursion });

function coordinateView(coordinate) {
  const delta = key => {
    const value = coordinate.session_2[key] - coordinate.session_1[key];
    return Number.isFinite(value) ? value : null;
  };
  return {
    name: coordinate.name,
    unit: coordinate.unit,
    available: true,
    uncertainty: 'UNAVAILABLE',
    session_1: range(coordinate.session_1),
    session_2: range(coordinate.session_2),
    difference: { direction: 'session_2_minus_session_1', min: delta('min'), max: delta('max'), excursion: delta('excursion') },
  };
}

export function parseComparisonResponse(raw, requestedS1, requestedS2) {
  const invalid = error => ({ valid: false, error });
  if (!record(raw)) return invalid('Comparison response is invalid or empty');
  const wrapped = Object.hasOwn(raw, 'comparison');
  const payload = wrapped ? raw.comparison : raw;
  if (!record(payload)) return invalid('Comparison response is invalid or empty');
  if (typeof requestedS1 !== 'string' || !requestedS1 || typeof requestedS2 !== 'string' || !requestedS2 ||
      requestedS1 === requestedS2 || payload.session_1 !== requestedS1 || payload.session_2 !== requestedS2) {
    return invalid('Comparison identity mismatch: requested pair does not match returned pair');
  }
  const wrapperSafe = !wrapped || (absentOr(raw.physical_accuracy_verified, false) && absentOr(raw.clinical_accuracy_verified, false) &&
    absentOr(raw.clinical_validation, 'UNVERIFIED') && absentOr(raw.comparison_scope, 'research_only') &&
    (raw.test_only === undefined || typeof raw.test_only === 'boolean'));
  if (!wrapperSafe || typeof payload.compatible !== 'boolean' || payload.clinical_accuracy_verified !== false ||
      payload.comparison_scope !== 'research_only' || !absentOr(payload.physical_accuracy_verified, false)) {
    return invalid('Comparison safety flags are invalid or unsupported');
  }
  const kinds = [wrapped ? raw.evidence_kind : undefined, payload.evidence_kind].filter(kind => kind !== undefined);
  if (kinds.some(kind => kind !== FIXTURE_KIND)) return invalid('Comparison evidence provenance is unsupported or conflicting');
  const provenanceKind = kinds.length ? FIXTURE_KIND : 'PROVENANCE_UNVERIFIED';

  const passport_1 = passportSummary(payload.passport_1, requestedS1);
  const passport_2 = passportSummary(payload.passport_2, requestedS2);
  if (!passport_1 || !passport_2) return invalid('Comparison passports are invalid or unbound');
  const testOnlyPassport = passport_1.is_test_only || passport_2.is_test_only;
  if (testOnlyPassport && payload.compatible) return invalid('Test-only sessions cannot form a compatible comparison');

  const m = payload.metrics;
  const captured_1 = record(m) ? captureCount(m.captured_1) : undefined;
  const captured_2 = record(m) ? captureCount(m.captured_2) : undefined;
  const contradicts = (count, passport) => count !== null && passport.captured_count !== null && count !== passport.captured_count;
  if (captured_1 === undefined || captured_2 === undefined || contradicts(captured_1, passport_1) || contradicts(captured_2, passport_2)) {
    return invalid('Comparison capture counts are invalid or unbounded');
  }

  const rm = payload.research_measurements;
  if (!record(rm) || rm.schema !== 'kinelab.research-comparison.v1' || rm.scope !== 'descriptive_angular_only' ||
      !['AVAILABLE', 'UNAVAILABLE'].includes(rm.status) || rm.uncertainty?.status !== 'UNAVAILABLE' ||
      rm.meaningful_change?.status !== 'UNAVAILABLE') {
    return invalid('Research comparison status is invalid');
  }
  const available = rm.status === 'AVAILABLE';
  if (payload.compatible !== available) return invalid('Compatibility verdict must match research measurement availability');
  const sourceList = Array.isArray(rm.sessions) ? rm.sessions : [];
  const sessions = [requestedS1, requestedS2]
    .map(id => sourceList.filter(source => record(source) && source.session_id === id))
    .flatMap(found => found.length === 1 && validSession(found[0]) ? found : []);
  if (available) {
    if (sessions.length !== 2 || sourceList.length !== 2 || sourceList[0] !== sessions[0] || sourceList[1] !== sessions[1] ||
        !matchingFields.every(key => sessions[0].contract[key] === sessions[1].contract[key])) {
      return invalid('Available research measurements require matching confirmed source bindings');
    }
    const units1 = sessions[0].contract.units;
    const units2 = sessions[1].contract.units;
    const names = Object.keys(units1);
    if (!exactKeys(units2, names) || !names.every(name => units1[name] === units2[name]) ||
        !Array.isArray(rm.coordinates) || rm.coordinates.length !== names.length ||
        new Set(rm.coordinates.map(coordinate => coordinate?.name)).size !== names.length ||
        !rm.coordinates.every(coordinate => exactKeys(coordinate, coordinateFields) && names.includes(coordinate.name) &&
          coordinate.unit === units1[coordinate.name] && validRange(coordinate.session_1) && validRange(coordinate.session_2))) {
      return invalid('Research coordinates or uncertainty are invalid or unbound');
    }
  }
  const reason = text(payload.reason);
  return {
    valid: true,
    session_1: requestedS1,
    session_2: requestedS2,
    evidence_kind: provenanceKind === FIXTURE_KIND ? FIXTURE_KIND : null,
    isFixtureOnly: provenanceKind === FIXTURE_KIND,
    provenance: { kind: provenanceKind, label: PROVENANCE_LABELS[provenanceKind] },
    test_only: provenanceKind === FIXTURE_KIND || raw.test_only === true || testOnlyPassport,
    compatible: payload.compatible,
    reason,
    reasons: reason.split('; ').filter(Boolean),
    metrics: { captured_1, captured_2, state_1: stateLabel(m.state_1), state_2: stateLabel(m.state_2) },
    passport_1,
    passport_2,
    physical_accuracy_verified: false,
    clinical_accuracy_verified: false,
    clinical_validation: 'UNVERIFIED',
    comparison_scope: 'research_only',
    research_measurements: {
      status: available ? 'AVAILABLE' : 'UNAVAILABLE',
      reason: text(rm.reason) || 'No research measurements in comparison payload',
      scope: 'descriptive_angular_only',
      coordinates: available ? rm.coordinates.map(coordinateView) : [],
      unavailable_coordinates: [],
      sessions,
      uncertainty: { status: 'UNAVAILABLE', reason: text(rm.uncertainty.reason) || 'No approved uncertainty model bound to these sources' },
      meaningful_change: { status: 'UNAVAILABLE', reason: text(rm.meaningful_change.reason) || 'No approved repeatability threshold' },
    },
  };
}
