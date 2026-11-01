import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parseComparisonResponse, formatCoordinateValue, formatCoordinateDifference } from './reportComparisonHelper.js';

const fixture = JSON.parse(fs.readFileSync(new URL('./fixtures/researchComparison.generated.json', import.meta.url), 'utf8'));
const fresh = () => structuredClone(fixture);

test('the generated backend contract retains exact source-bound angular values', () => {
  const parsed = parseComparisonResponse(fresh(), 'a', 'b');
  assert.equal(parsed.valid, true);
  assert.equal(parsed.research_measurements.status, 'AVAILABLE');
  assert.equal(parsed.isFixtureOnly, true);
  assert.equal(parsed.clinical_accuracy_verified, false);
  assert.equal(parsed.research_measurements.coordinates[0].session_1.min, 0.2);
});

const malformed = [
  ['truthy compatibility string', p => { p.compatible = 'false'; }],
  ['incompatible outer result', p => { p.compatible = false; }],
  ['wrong research schema', p => { p.research_measurements.schema = 'unknown'; }],
  ['wrong research scope', p => { p.research_measurements.scope = 'clinical'; }],
  ['missing session binding', p => { p.research_measurements.sessions.pop(); }],
  ['null session binding', p => { p.research_measurements.sessions[0] = null; }],
  ['reversed source pair', p => { p.research_measurements.sessions.reverse(); }],
  ['truthy metadata confirmation', p => { p.research_measurements.sessions[0].metadata.confirmed = 'false'; }],
  ['missing metadata schema', p => { delete p.research_measurements.sessions[0].metadata.schema; }],
  ['unconfirmed subject binding', p => { p.research_measurements.sessions[0].contract.subject_id = 'sub-' + 'f'.repeat(32); }],
  ['different task contracts', p => { p.research_measurements.sessions[1].contract.task_id = 'another-task'; }],
  ['missing revision', p => { delete p.research_measurements.sessions[0].source_revision; }],
  ['invalid hash', p => { p.research_measurements.sessions[0].source_revision.run_sha256 = 'unknown'; }],
  ['unbound model digest', p => { p.research_measurements.sessions[0].source_revision.model_sha256 = 'f'.repeat(64); }],
  ['missing capture binding', p => { delete p.research_measurements.sessions[0].source_revision.capture_sha256.cam01_trial; }],
  ['missing coordinate unit', p => { delete p.research_measurements.coordinates[0].unit; }],
  ['different coordinate unit', p => { p.research_measurements.coordinates[0].unit = 'rad'; }],
  ['duplicate coordinate', p => { p.research_measurements.coordinates.push(structuredClone(p.research_measurements.coordinates[0])); }],
  ['empty coordinate set', p => { p.research_measurements.coordinates = []; }],
  ['reversed minimum maximum', p => { p.research_measurements.coordinates[0].session_1.min = 5; }],
  ['contradictory excursion', p => { p.research_measurements.coordinates[0].session_1.excursion = 100; }],
  ['nonfinite angular value', p => { p.research_measurements.coordinates[0].session_1.min = NaN; }],
  ['unexpected coordinate', p => { p.research_measurements.coordinates[0].name = 'unbound-coordinate'; }],
  ['fabricated uncertainty availability', p => { p.research_measurements.uncertainty.status = 'AVAILABLE'; }],
  ['fabricated meaningful change', p => { p.research_measurements.meaningful_change.status = 'AVAILABLE'; }],
  ['clinical claim', p => { p.clinical_accuracy_verified = true; }],
  ['malformed clinical claim', p => { p.clinical_accuracy_verified = 'false'; }],
];

for (const [name, mutate] of malformed) {
  test(`comparison rejects ${name} without exposing measurements`, () => {
    const raw = fresh();
    mutate(raw.comparison);
    let parsed;
    assert.doesNotThrow(() => { parsed = parseComparisonResponse(raw, 'a', 'b'); });
    assert.equal(parsed.valid, false);
    assert.equal(parsed.research_measurements, undefined);
  });
}

test('unavailable results cannot expose stale coordinates or invent missing capture counts', () => {
  const raw = fresh();
  raw.comparison.compatible = false;
  raw.comparison.research_measurements.status = 'UNAVAILABLE';
  delete raw.comparison.metrics.captured_1;
  const parsed = parseComparisonResponse(raw, 'a', 'b');
  assert.equal(parsed.valid, true);
  assert.equal(parsed.research_measurements.status, 'UNAVAILABLE');
  assert.deepEqual(parsed.research_measurements.coordinates, []);
  assert.equal(parsed.metrics.captured_1, null);
});

test('invalid wrappers and self comparisons fail without throwing', () => {
  for (const raw of [[], { comparison: [] }, { comparison: null }, { comparison: 'bad' }]) {
    assert.equal(parseComparisonResponse(raw, 'a', 'b').valid, false);
  }
  const raw = fresh();
  raw.comparison.session_2 = 'a';
  assert.equal(parseComparisonResponse(raw, 'a', 'a').valid, false);
});

test('coordinate formatting never invents a unit or overflows finite values', () => {
  for (const unit of [undefined, null, '', 'mm', {}, 0]) {
    assert.equal(formatCoordinateValue(12.5, unit), 'UNAVAILABLE');
  }
  assert.doesNotMatch(formatCoordinateValue(1.1e307, 'deg'), /Infinity|NaN/);
  assert.equal(formatCoordinateValue(0, 'rad'), '0 rad');
});

const asymmetric = () => {
  const raw = fresh();
  raw.comparison.research_measurements.coordinates[0].session_2 = structuredClone(fixture.asymmetric_endpoint_probe.expected_session_2);
  return raw;
};
const incompatible = (reason = 'Comparison mismatch: protocol_version; Comparison mismatch: units') => {
  const payload = fresh().comparison;
  payload.compatible = false;
  payload.reason = payload.research_measurements.reason = reason;
  payload.research_measurements.status = 'UNAVAILABLE';
  payload.research_measurements.coordinates = [];
  return payload;
};

const strictPayload = [
  ['compatible verdict without research measurements', p => { delete p.research_measurements; }],
  ['compatible verdict with unavailable research measurements', p => { p.research_measurements.status = 'UNAVAILABLE'; }],
  ['payload physical accuracy claim', p => { p.physical_accuracy_verified = true; }],
  ['missing payload clinical flag', p => { delete p.clinical_accuracy_verified; }],
  ['missing comparison scope', p => { delete p.comparison_scope; }],
  ['unknown payload evidence kind', p => { p.evidence_kind = 'SYNTHETIC_TEST_ONLY'; }],
  ['passport clinical claim', p => { p.passport_1.clinically_validated = true; }],
  ['passport physical claim string', p => { p.passport_2.physical_accuracy_verified = 'false'; }],
  ['passport test-only string', p => { p.passport_1.is_test_only = 'false'; }],
  ['test-only passport in compatible result', p => { p.passport_2.is_test_only = true; }],
  ['passport bound to another session', p => { p.passport_1.session_id = 'b'; }],
  ['missing passport', p => { delete p.passport_2; }],
  ['missing metrics', p => { delete p.metrics; }],
  ['capture count above role total', p => { p.metrics.captured_1 = 7; }],
  ['negative capture count', p => { p.metrics.captured_2 = -1; }],
  ['fractional capture count', p => { p.metrics.captured_1 = 2.5; }],
  ['string capture count', p => { p.metrics.captured_1 = '6'; }],
  ['capture count contradicting passport', p => { p.metrics.captured_1 = 5; }],
  ['extra coordinate claim key', p => { p.research_measurements.coordinates[0].improvement = true; }],
  ['unavailable result with fabricated uncertainty', p => {
    p.compatible = false; p.research_measurements.status = 'UNAVAILABLE'; p.research_measurements.uncertainty.status = 'AVAILABLE';
  }],
  ['unavailable result with unknown research schema', p => {
    p.compatible = false; p.research_measurements.status = 'UNAVAILABLE'; p.research_measurements.schema = 'unknown';
  }],
];
for (const [name, mutate] of strictPayload) {
  test(`strict envelope rejects ${name}`, () => {
    const raw = fresh();
    mutate(raw.comparison);
    const parsed = parseComparisonResponse(raw, 'a', 'b');
    assert.equal(parsed.valid, false);
    assert.equal(parsed.research_measurements, undefined);
  });
}

const strictWrapper = [
  ['unknown wrapper evidence kind', r => { r.evidence_kind = 'SYNTHETIC_TEST_ONLY'; }],
  ['other wrapper kind over fixture payload', r => { r.evidence_kind = 'OTHER'; r.comparison.evidence_kind = 'GENERATED_CONTRACT_FIXTURE_ONLY'; }],
  ['wrapper clinical claim', r => { r.clinical_accuracy_verified = true; }],
  ['wrapper physical claim string', r => { r.physical_accuracy_verified = 'false'; }],
  ['wrapper clinical validation claim', r => { r.clinical_validation = 'VERIFIED'; }],
  ['wrapper scope claim', r => { r.comparison_scope = 'clinical'; }],
  ['wrapper test-only string', r => { r.test_only = 'true'; }],
];
for (const [name, mutate] of strictWrapper) {
  test(`strict wrapper rejects ${name}`, () => {
    const raw = fresh();
    mutate(raw);
    assert.equal(parseComparisonResponse(raw, 'a', 'b').valid, false);
  });
}

test('fixture provenance is explicit and an unlabelled service response is provenance-unverified', () => {
  const fixtureResult = parseComparisonResponse(fresh(), 'a', 'b');
  assert.equal(fixtureResult.provenance.kind, 'GENERATED_CONTRACT_FIXTURE_ONLY');
  assert.equal(fixtureResult.test_only, true);
  const payloadLabelled = fresh();
  delete payloadLabelled.evidence_kind;
  payloadLabelled.comparison.evidence_kind = 'GENERATED_CONTRACT_FIXTURE_ONLY';
  assert.equal(parseComparisonResponse(payloadLabelled, 'a', 'b').isFixtureOnly, true);
  const service = parseComparisonResponse(fresh().comparison, 'a', 'b');
  assert.equal(service.valid, true);
  assert.equal(service.isFixtureOnly, false);
  assert.equal(service.evidence_kind, null);
  assert.equal(service.provenance.kind, 'PROVENANCE_UNVERIFIED');
  assert.equal(service.test_only, false);
  for (const result of [fixtureResult, service]) {
    assert.equal(result.physical_accuracy_verified, false);
    assert.equal(result.clinical_validation, 'UNVERIFIED');
    assert.equal(result.research_measurements.uncertainty.status, 'UNAVAILABLE');
  }
});

test('passports and coordinates are rebuilt from validated fields only', () => {
  const parsed = parseComparisonResponse(fresh(), 'a', 'b');
  assert.deepEqual(parsed.passport_1, { session_id: 'a', state: 'KINEMATICS_PASSED', is_test_only: false, captured_count: 6 });
  assert.deepEqual(Object.keys(parsed.research_measurements.coordinates[0]).sort(),
    ['available', 'difference', 'name', 'session_1', 'session_2', 'uncertainty', 'unit']);
  assert.equal(parsed.research_measurements.coordinates[0].uncertainty, 'UNAVAILABLE');
});

test('asymmetric endpoints keep column order and the arithmetic difference is session 2 minus session 1', () => {
  const coordinate = parseComparisonResponse(asymmetric(), 'a', 'b').research_measurements.coordinates[0];
  assert.deepEqual(coordinate.session_1, { min: 0.2, max: 0.8, excursion: 0.6000000000000001 });
  assert.deepEqual(coordinate.session_2, { min: 0.35, max: 1.45, excursion: 1.1 });
  assert.deepEqual(coordinate.difference, { direction: 'session_2_minus_session_1', min: 0.35 - 0.2, max: 1.45 - 0.8, excursion: 1.1 - 0.6000000000000001 });
  const swapped = asymmetric();
  const raw = swapped.comparison.research_measurements.coordinates[0];
  [raw.session_1, raw.session_2] = [raw.session_2, raw.session_1];
  const reversed = parseComparisonResponse(swapped, 'a', 'b').research_measurements.coordinates[0];
  assert.equal(reversed.session_1.min, 0.35);
  assert.ok(reversed.difference.min < 0 && reversed.difference.max < 0 && reversed.difference.excursion < 0);
});

test('a nonfinite arithmetic difference stays unavailable instead of becoming a value', () => {
  const raw = fresh();
  const coordinate = raw.comparison.research_measurements.coordinates[0];
  coordinate.session_1 = { min: -1e308, max: -1e308, excursion: 0 };
  coordinate.session_2 = { min: 1e308, max: 1e308, excursion: 0 };
  const parsed = parseComparisonResponse(raw, 'a', 'b').research_measurements.coordinates[0];
  assert.equal(parsed.difference.min, null);
  assert.equal(parsed.difference.max, null);
  assert.equal(parsed.difference.excursion, 0);
});

test('incompatible results disclose each difference and keep valid endpoint bindings without coordinates', () => {
  const payload = incompatible();
  payload.research_measurements.sessions[1].metadata.protocol_version = '2';
  payload.research_measurements.sessions[1].contract.protocol_version = '2';
  const parsed = parseComparisonResponse(payload, 'a', 'b');
  assert.equal(parsed.valid, true);
  assert.deepEqual(parsed.reasons, ['Comparison mismatch: protocol_version', 'Comparison mismatch: units']);
  assert.deepEqual(parsed.research_measurements.coordinates, []);
  assert.deepEqual(parsed.research_measurements.sessions.map(s => s.metadata.protocol_version), ['1', '2']);
});

test('small angular values and differences never display as zero', () => {
  assert.equal(formatCoordinateValue(0.004, 'rad'), '0.004 rad');
  assert.equal(formatCoordinateValue(0.004, 'deg'), '0.004 deg');
  assert.equal(formatCoordinateValue(-0.0001234, 'rad'), '-0.000123 rad');
  assert.notEqual(formatCoordinateValue(1e-300, 'rad'), '0 rad');
  assert.equal(formatCoordinateValue(45.678, 'deg'), '45.68 deg');
  assert.equal(formatCoordinateDifference(0.35 - 0.2, 'deg'), '+0.15 deg');
  assert.equal(formatCoordinateDifference(-0.0015, 'rad'), '-0.0015 rad');
  assert.equal(formatCoordinateDifference(0, 'deg'), '0 deg');
  for (const value of [null, NaN, Infinity]) assert.equal(formatCoordinateDifference(value, 'deg'), 'UNAVAILABLE');
  assert.equal(formatCoordinateDifference(0.5, 'mm'), 'UNAVAILABLE');
});
