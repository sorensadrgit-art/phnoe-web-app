import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformSync } from 'esbuild';
import { parseReconstructionTiming, parseComparisonTimings, TIMING_LABELS } from './reconstructionTimingModel.js';

// Parser fixtures only; actual producer compatibility is separately tested by Python API fixtures.
const sha = character => character.repeat(64);
const expected = {session_id: 'a', session_sha256: sha('1'), run_sha256: sha('2'),
  calibration_sha256: sha('3'), metadata_context_sha256: sha('4'), token: sha('5')};
function fixture() {
  const trc = {path: 'pose-3d/fixture.trc', sha256: sha('6')};
  const calibration = {path: 'calibration/fixture.toml', sha256: sha('3')};
  return {
    schema: 'kinelab.reconstruction-timing.v1', status: 'AVAILABLE', session_id: 'a',
    source_trc: trc, calibration, sample_counts: {observed: 4, valid: 3, rejected: 1, missing_interior: 1},
    segments: [
      {classification: 'valid', first_frame: 0, last_frame: 1, first_time_s: 0, last_time_s: 1 / 30, samples: 2},
      {classification: 'rejected', first_frame: 2, last_frame: 2, first_time_s: 2 / 30, last_time_s: 2 / 30, samples: 1},
      {classification: 'valid', first_frame: 4, last_frame: 4, first_time_s: 4 / 30, last_time_s: 4 / 30, samples: 1},
    ],
    gaps: [{first_missing_frame: 3, last_missing_frame: 3, missing_samples: 1, left_time_s: 2 / 30, right_time_s: 4 / 30}],
    intervals: [
      {left_frame: 0, right_frame: 1, start_time_s: 0, end_time_s: 1 / 30, category: 'valid_adjacent'},
      {left_frame: 1, right_frame: 2, start_time_s: 1 / 30, end_time_s: 2 / 30, category: 'rejected_or_transition_adjacent'},
      {left_frame: 2, right_frame: 4, start_time_s: 2 / 30, end_time_s: 4 / 30, category: 'unknown_gap'},
    ],
    duration_s: {valid_adjacent: 1 / 30, rejected_or_transition_adjacent: 1 / 30, unknown_gap: 2 / 30, observed_span: 4 / 30},
    duration_policy: 'adjacent_observed_endpoints_v1; [start,end) partition; rejected includes transitions; no endpoint extrapolation',
    source_extent: 'leading/trailing and decoded source video extent UNVERIFIED',
    physical_accuracy_verified: false, clinical_accuracy_verified: false, clinical_validation: 'UNVERIFIED',
    bindings: {session_id: 'a', session_sha256: sha('1'), run_sha256: sha('2'), source_trc: trc, calibration,
      frame_diagnostics: {path: 'diagnostics/reconstruction-frames.' + sha('7') + '.json', sha256: sha('7')},
      metadata_context_sha256: sha('4'), comparison_source_observation: {token: sha('5'), evidence_verified: false}},
  };
}
const parse = value => parseReconstructionTiming(value, expected);
const refuse = value => {const parsed = parse(value); assert.equal(parsed.status, 'UNAVAILABLE'); assert.equal(parsed.duration_s, null); assert.deepEqual(parsed.intervals, []);};

test('R04 model mixed partition retains genuine counts, segments and gaps', () => {
  const value = fixture(); assert.deepEqual(parse(value), value);
  assert.equal(TIMING_LABELS.valid_adjacent, 'valid adjacent endpoints');
});
test('R04 model absence and explicit unavailable preserve honest missing timing', () => {
  assert.equal(parse(undefined).code, 'TIMING_NOT_REPORTED');
  const value = {schema: fixture().schema, status: 'UNAVAILABLE', code: 'TIMING_DIAGNOSTICS_ABSENT',
    reason: 'TIMING_DIAGNOSTICS_ABSENT', duration_s: null, segments: [], gaps: [], intervals: [],
    physical_accuracy_verified: false, clinical_accuracy_verified: false, clinical_validation: 'UNVERIFIED'};
  assert.equal(parse(value).code, value.code);
  value.duration_s = {}; refuse(value);
});
test('R04 model source, metadata and observation mismatches refuse', () => {
  for (const key of ['session_sha256', 'run_sha256', 'metadata_context_sha256']) {
    const value = fixture(); value.bindings[key] = sha('9'); refuse(value);
  }
  const value = fixture(); value.bindings.comparison_source_observation.token = sha('9'); refuse(value);
  const unbound = fixture(); unbound.bindings.source_trc = {path: 'pose-3d/later_filt.trc', sha256: sha('9')}; refuse(unbound);
});
test('R04 model unsupported version and clinical flags refuse', () => {
  for (const mutate of [value => value.schema += '.future', value => value.physical_accuracy_verified = true,
    value => value.bindings.comparison_source_observation.evidence_verified = true]) {
    const value = fixture(); mutate(value); refuse(value);
  }
});
test('R04 model malformed, boolean, nonfinite and cap counts refuse', () => {
  for (const count of [false, NaN, Infinity, -1, 4097, Number.MAX_SAFE_INTEGER + 1]) {
    const value = fixture(); value.sample_counts.observed = count; refuse(value);
  }
  const value = fixture(); value.segments = []; refuse(value);
});
test('R04 model missing, duplicated, reordered and contradictory intervals refuse', () => {
  for (const mutate of [value => value.intervals.pop(), value => value.intervals.push(value.intervals[0]),
    value => value.intervals.reverse(), value => value.intervals[1].category = 'valid_adjacent',
    value => value.gaps[0].missing_samples++, value => value.duration_s.unknown_gap = 0,
    value => value.sample_counts.valid++, value => value.segments[0].last_time_s += 0.01]) {
    const value = fixture(); mutate(value); refuse(value);
  }
});
test('R04 model singleton has zero intervals and no duration extrapolation', () => {
  const value = fixture(); value.sample_counts = {observed: 1, valid: 1, rejected: 0, missing_interior: 0};
  value.segments = [{classification: 'valid', first_frame: 60, last_frame: 60, first_time_s: 2, last_time_s: 2, samples: 1}];
  value.gaps = []; value.intervals = [];
  value.duration_s = {valid_adjacent: 0, rejected_or_transition_adjacent: 0, unknown_gap: 0, observed_span: 0};
  assert.equal(parse(value).status, 'AVAILABLE');
});
test('R04 comparison timing requires unique endpoint and current row bindings', () => {
  const value = fixture();
  const source = {session_id: 'a', source_revision: expected, timing: value};
  const row = {id: 'a', metadata_context_sha256: expected.metadata_context_sha256,
    research_source_revision: {status: 'AVAILABLE', token: expected.token}};
  const raw = {research_measurements: {sessions: [source]}};
  assert.equal(parseComparisonTimings(raw, ['a'], [row]).a.status, 'AVAILABLE');
  assert.equal(parseComparisonTimings(raw, ['a'], [row, row]).a.status, 'UNAVAILABLE');
  row.metadata_context_sha256 = sha('9');
  assert.equal(parseComparisonTimings(raw, ['a'], [row]).a.status, 'UNAVAILABLE');
});
const directory = path.dirname(fileURLToPath(import.meta.url)), require = createRequire(import.meta.url);
function moduleAt(filename) {
  const file = path.resolve(directory, filename), module = {exports: {}};
  const source = transformSync(fs.readFileSync(file, 'utf8'), {loader: 'jsx', format: 'cjs'}).code;
  new Function('require', 'module', 'exports', source)(name => name.startsWith('.')
    ? moduleAt(path.resolve(path.dirname(file), name)) : require(name), module, module.exports);
  return module.exports;
}
test('R04 timing display shows actual partition, frame gaps and visible caveats', () => {
  const {ReconstructionTimingView} = moduleAt('./ReportStudio.jsx');
  const html = renderToStaticMarkup(React.createElement(ReconstructionTimingView, {timing: parse(fixture())}));
  for (const label of Object.values(TIMING_LABELS)) assert.ok(html.includes(label), label);
  assert.ok(html.includes('missing interior')); assert.ok(html.includes('3–3'));
  assert.ok(html.includes('Physical accuracy: UNVERIFIED'));
  assert.ok(html.includes('no endpoint extrapolation'));
});
test('R04 timing display preserves unavailable instead of invented zero duration', () => {
  const {ReconstructionTimingView} = moduleAt('./ReportStudio.jsx');
  const html = renderToStaticMarkup(React.createElement(ReconstructionTimingView, {timing: parse(undefined)}));
  assert.ok(html.includes('TIMING_NOT_REPORTED')); assert.ok(html.includes('Valid duration: UNAVAILABLE'));
  assert.ok(!html.includes('valid adjacent endpoints: 0'));
});

test('R04 model contradictory segment boundary times refuse exactly', () => {
  for (const field of ['first_time_s', 'last_time_s']) {
    const value = fixture();
    value.segments[1][field] += 1e-8;
    assert.equal(parse(value).status, 'UNAVAILABLE');
  }
});
