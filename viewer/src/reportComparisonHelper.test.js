import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformSync } from 'esbuild';
import {
  parseComparisonResponse,
  formatCoordinateValue,
} from './reportComparisonHelper.js';

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

function moduleAt(filename, overrides = {}) {
  const file = path.resolve(directory, filename);
  const module = { exports: {} };
  const source = transformSync(fs.readFileSync(file, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(
    name => overrides[name] || (name.startsWith('.') ? moduleAt(path.resolve(path.dirname(file), name), overrides) : require(name)),
    module,
    module.exports
  );
  return module.exports;
}

const ReportStudio = moduleAt('./ReportStudio.jsx').default;

const examplePath = path.resolve(
  directory,
  './fixtures/researchComparison.generated.json'
);

test('formatCoordinateValue enforces fail-closed numeric validation and native units', () => {
  // Valid numeric values
  assert.equal(formatCoordinateValue(0, 'deg'), '0 deg');
  assert.equal(formatCoordinateValue(0.2, 'deg'), '0.2 deg');
  assert.equal(formatCoordinateValue(45.678, 'deg'), '45.68 deg');
  assert.equal(formatCoordinateValue(-12.5, 'rad'), '-12.5 rad');

  // Non-finite / missing values must be UNAVAILABLE, never 0 or fabricated defaults
  assert.equal(formatCoordinateValue(null, 'deg'), 'UNAVAILABLE');
  assert.equal(formatCoordinateValue(undefined, 'deg'), 'UNAVAILABLE');
  assert.equal(formatCoordinateValue(NaN, 'deg'), 'UNAVAILABLE');
  assert.equal(formatCoordinateValue(Infinity, 'deg'), 'UNAVAILABLE');
  assert.equal(formatCoordinateValue(-Infinity, 'deg'), 'UNAVAILABLE');
  assert.equal(formatCoordinateValue('0.5', 'deg'), 'UNAVAILABLE');
});

test('parseComparisonResponse correctly parses wrapped generated example fixture', () => {
  assert.ok(fs.existsSync(examplePath), 'Fixture file must exist');
  const rawFixture = JSON.parse(fs.readFileSync(examplePath, 'utf8'));

  const parsed = parseComparisonResponse(rawFixture, 'a', 'b');
  assert.equal(parsed.valid, true);
  assert.equal(parsed.session_1, 'a');
  assert.equal(parsed.session_2, 'b');
  assert.equal(parsed.evidence_kind, 'GENERATED_CONTRACT_FIXTURE_ONLY');
  assert.equal(parsed.isFixtureOnly, true);
  assert.equal(parsed.compatible, true);
  assert.equal(parsed.reason, 'Matching confirmed metadata and verified native source bindings');

  // Metrics
  assert.ok(parsed.metrics);
  assert.equal(parsed.metrics.captured_1, 6);
  assert.equal(parsed.metrics.captured_2, 6);
  assert.equal(parsed.metrics.state_1, 'KINEMATICS_PASSED');
  assert.equal(parsed.metrics.state_2, 'KINEMATICS_PASSED');

  // Research measurements
  const rm = parsed.research_measurements;
  assert.ok(rm);
  assert.equal(rm.status, 'AVAILABLE');
  assert.equal(rm.scope, 'descriptive_angular_only');

  // Coordinates
  assert.equal(rm.coordinates.length, 1);
  const knee = rm.coordinates[0];
  assert.equal(knee.name, 'knee_angle_r');
  assert.equal(knee.unit, 'deg');
  assert.equal(knee.session_1.min, 0.2);
  assert.equal(knee.session_1.max, 0.8);
  assert.equal(knee.session_1.excursion, 0.6000000000000001);
  assert.equal(knee.session_2.min, 0.2);
  assert.equal(knee.session_2.max, 0.8);
  assert.equal(knee.session_2.excursion, 0.6000000000000001);

  // Uncertainty model must be explicitly UNAVAILABLE
  assert.equal(rm.uncertainty.status, 'UNAVAILABLE');
  assert.equal(rm.uncertainty.reason, 'No approved uncertainty model bound to these sources');

  // Meaningful change must be explicitly UNAVAILABLE
  assert.equal(rm.meaningful_change.status, 'UNAVAILABLE');
  assert.equal(rm.meaningful_change.reason, 'No approved repeatability threshold');

  // Metadata summary
  assert.equal(rm.sessions.length, 2);
  assert.equal(rm.sessions[0].session_id, 'a');
  assert.equal(rm.sessions[0].metadata.subject_id, 'sub-11111111111111111111111111111111');
  assert.equal(rm.sessions[0].contract.model_sha256, '5ff389c66d51891ed1ad1cc89c00bd9537cad311f31c575c89a52f02f4c69d91');
});

test('parseComparisonResponse handles unwrapped comparison payloads', () => {
  const unwrappedPayload = JSON.parse(fs.readFileSync(examplePath, 'utf8')).comparison;
  unwrappedPayload.compatible = false;
  unwrappedPayload.reason = 'Incompatible protocols';
  unwrappedPayload.research_measurements.status = 'UNAVAILABLE';
  unwrappedPayload.research_measurements.reason = 'Session 2 did not produce native kinematics';
  unwrappedPayload.research_measurements.coordinates = [];

  const parsed = parseComparisonResponse(unwrappedPayload, 'a', 'b');
  assert.equal(parsed.valid, true);
  assert.equal(parsed.session_1, 'a');
  assert.equal(parsed.session_2, 'b');
  assert.equal(parsed.compatible, false);
  assert.equal(parsed.isFixtureOnly, false);
  assert.equal(parsed.research_measurements.status, 'UNAVAILABLE');
  assert.equal(parsed.research_measurements.reason, 'Session 2 did not produce native kinematics');
  assert.equal(parsed.research_measurements.coordinates.length, 0);
});

test('parseComparisonResponse rejects stale, mismatched, or invalid session pair responses', () => {
  const payload = {
    session_1: 'sess-A',
    session_2: 'sess-B',
    compatible: true,
  };

  // Mismatched session_1
  const res1 = parseComparisonResponse(payload, 'sess-X', 'sess-B');
  assert.equal(res1.valid, false);
  assert.ok(res1.error.includes('Comparison identity mismatch'));

  // Mismatched session_2
  const res2 = parseComparisonResponse(payload, 'sess-A', 'sess-Y');
  assert.equal(res2.valid, false);
  assert.ok(res2.error.includes('Comparison identity mismatch'));

  // Invalid/null response
  const resNull = parseComparisonResponse(null, 'sess-A', 'sess-B');
  assert.equal(resNull.valid, false);
  assert.equal(resNull.error, 'Comparison response is invalid or empty');

  const resString = parseComparisonResponse('error string', 'sess-A', 'sess-B');
  assert.equal(resString.valid, false);
});

test('parseComparisonResponse rejects non-finite or incomplete values in a source-bound coordinate set', () => {
  for (const invalid of [NaN, Infinity, undefined]) {
    const payload = JSON.parse(fs.readFileSync(examplePath, 'utf8'));
    payload.comparison.research_measurements.coordinates[0].session_1.min = invalid;
    const parsed = parseComparisonResponse(payload, 'a', 'b');
    assert.equal(parsed.valid, false);
    assert.match(parsed.error, /coordinates/);
    assert.equal(parsed.research_measurements, undefined);
  }
});

test('initial ReportStudio render leaks no opaque identifiers and exposes compare controls', () => {
  const html = renderToStaticMarkup(
    React.createElement(ReportStudio, {
      sessions: [{ id: 'a', kind: 'real', status: 'ready' }, { id: 'b', kind: 'real', status: 'ready' }],
      selectedSession: 'a',
      reports: [],
      busy: false,
    })
  );
  assert.ok(!html.includes('sub-11111111111111111111111111111111'), 'Opaque IDs must never be in defaults or placeholders');
  assert.ok(!html.includes('op-22222222222222222222222222222222'), 'Operator IDs must never be in defaults or placeholders');
  assert.ok(html.includes('Compare Active With:'));
  assert.ok(html.includes('Select compatible session...'));
  assert.ok(html.includes('Compare'));
});

// Generated hook/effect fixture (same pattern as phaseFWorkflow.test.js): it runs the actual
// ReportStudio render output, handlers and effects, not a browser or network request.
function mounted(filename, props, overrides = {}) {
  const slots = [], effects = []; let index = 0, pending = [];
  const react = { ...React,
    useState(initial) {
      const i = index++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
    },
    useRef(value) { const i = index++; if (!(i in slots)) slots[i] = { current: value }; return slots[i]; },
    useMemo(fn) { index++; return fn(); },
    useEffect(fn, deps) {
      const i = index++, previous = effects[i];
      if (!previous || !deps || deps.some((value, n) => !Object.is(value, previous.deps?.[n]))) {
        pending.push(() => { previous?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; });
      }
    },
  };
  const Component = moduleAt(filename, { react, ...overrides }).default;
  return {
    render(next = props) { props = next; index = 0; pending = []; return Component(props); },
    effects() { const current = pending; pending = []; for (const effect of current) effect(); },
  };
}
function nodes(tree, predicate, out = []) {
  if (tree && typeof tree === 'object') {
    if (predicate(tree)) out.push(tree);
    React.Children.forEach(tree.props?.children, child => nodes(child, predicate, out));
  }
  return out;
}
function textOf(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  if (!tree || typeof tree !== 'object') return '';
  return React.Children.toArray(tree.props?.children).map(textOf).join('');
}

const fixture = JSON.parse(fs.readFileSync(examplePath, 'utf8'));
const fresh = () => structuredClone(fixture);
const withTarget = (raw, id) => JSON.parse(JSON.stringify(raw).replaceAll('"b"', JSON.stringify(id)));
const entry = id => ({ id, kind: 'real', status: 'registered', evidence_status: 'not_assessed', captured_roles: 6,
  total_roles: 6, can_register: false, has_board_measurement: false,
  research_source_revision: { schema: 'kinelab.comparison-source-observation.v1', status: 'AVAILABLE',
    token: id.repeat(64), reason: null, evidence_verified: false } });
const listing = () => ['a', 'b', 'c'].map(entry);
const compareButton = tree => nodes(tree, x => x.type === 'button' && /^(Compare|Comparing\.\.\.)$/.test(textOf(x).trim()))[0];

function studio(onCompareSessions, sessions = listing()) {
  let props = { sessions, reports: [], selectedSession: 'a', busy: false, onSelectSession: () => {}, onCompareSessions };
  const app = mounted('./ReportStudio.jsx', props);
  const view = {
    tree: null,
    render(next = {}) { props = { ...props, ...next }; view.tree = app.render(props); return view.tree; },
    settle(next) { view.render(next); app.effects(); return view.render(); },
    choose(id) {
      nodes(view.tree, x => x.type === 'select' && /Select compatible session/.test(textOf(x)))[0].props.onChange({ target: { value: id } });
      return view.settle();
    },
    compare() { return compareButton(view.tree).props.onClick(); },
    result() { return nodes(view.tree, x => typeof x.props?.className === 'string' && x.props.className.split(' ').includes('uw-compare-result'))[0]; },
  };
  view.settle();
  return view;
}
async function shown(raw, sessions) {
  const view = studio(async () => raw, sessions);
  view.choose('b');
  await view.compare();
  view.settle();
  return view;
}
const cell = (view, key) => {
  const row = nodes(view.result(), x => x.type === 'tr' && x.props['data-coordinate'] === 'knee_angle_r')[0];
  return textOf(nodes(row, x => x.props?.['data-cell'] === key)[0]).trim();
};
const universalLabels = out => {
  assert.match(out, /Physical accuracy unverified/);
  assert.match(out, /Clinical validation unverified/);
  assert.match(out, /CLINICAL_VALIDATION: UNVERIFIED/);
  assert.match(out, /Uncertainty: UNAVAILABLE/);
  assert.match(out, /Meaningful change \/ repeatability: UNAVAILABLE/);
};

test('mounted ReportStudio labels an unlabelled service result as provenance-unverified and unvalidated', async () => {
  const view = await shown(fresh().comparison);
  const out = textOf(view.result());
  universalLabels(out);
  assert.match(out, /PROVENANCE_UNVERIFIED/);
  assert.doesNotMatch(out, /GENERATED CONTRACT FIXTURE ONLY/);
});

test('mounted ReportStudio shows the fixture banner and TEST_ONLY label with no save action', async () => {
  const view = await shown(fresh());
  const banner = nodes(view.result(), x => x.props?.role === 'alert')[0];
  assert.match(textOf(banner), /GENERATED CONTRACT FIXTURE ONLY/);
  assert.match(textOf(banner), /TEST_ONLY/);
  const out = textOf(view.result());
  universalLabels(out);
  assert.doesNotMatch(renderToStaticMarkup(view.tree), /Save comparison|Save to Sessions/);
});

test('mounted incompatible result lists each difference and renders no trend or difference values', async () => {
  const payload = fresh().comparison;
  payload.compatible = false;
  payload.reason = payload.research_measurements.reason = 'Comparison mismatch: protocol_version; Comparison mismatch: units';
  payload.research_measurements.status = 'UNAVAILABLE';
  payload.research_measurements.coordinates = [];
  for (const key of ['metadata', 'contract']) payload.research_measurements.sessions[1][key].protocol_version = '2';
  const view = await shown(payload);
  const out = textOf(view.result());
  universalLabels(out);
  assert.match(out, /INCOMPATIBLE/);
  assert.deepEqual(nodes(view.result(), x => x.type === 'li' && /^Comparison mismatch/.test(textOf(x))).map(textOf),
    ['Comparison mismatch: protocol_version', 'Comparison mismatch: units']);
  assert.match(out, /No trend or difference is shown/);
  assert.equal(nodes(view.result(), x => x.type === 'table').length, 0);
  assert.match(out, /Protocol: generated-protocol · version 1/);
  assert.match(out, /Protocol: generated-protocol · version 2/);
});

test('mounted result discloses operator, subject, protocol and source revisions from the response only', async () => {
  const same = textOf((await shown(fresh())).result());
  assert.match(same, /Operator: SAME across endpoints/);
  const raw = fresh();
  const rm = raw.comparison.research_measurements;
  rm.sessions[1].metadata.operator_id = 'op-' + '3'.repeat(32);
  for (const s of rm.sessions) for (const key of ['metadata', 'contract']) s[key].protocol_version = '7';
  const out = textOf((await shown(raw)).result());
  assert.match(out, /Operator: DIFFERENT across endpoints/);
  assert.ok(out.includes('op-' + '2'.repeat(32)) && out.includes('op-' + '3'.repeat(32)));
  assert.ok(out.includes('sub-' + '1'.repeat(32)));
  assert.match(out, /Protocol: generated-protocol · version 7/);
  assert.doesNotMatch(out, /version 1\b/);
  for (const s of rm.sessions) {
    for (const key of ['session_sha256', 'run_sha256', 'motion_sha256']) assert.ok(out.includes(s.source_revision[key].slice(0, 12)), key);
  }
});

test('mounted two-endpoint view keeps asymmetric columns, per-coordinate availability and difference direction', async () => {
  const raw = fresh();
  raw.comparison.research_measurements.coordinates[0].session_2 = structuredClone(fixture.asymmetric_endpoint_probe.expected_session_2);
  const view = await shown(raw);
  const headers = nodes(view.result(), x => x.type === 'th' && x.props.scope === 'col').map(x => textOf(x));
  assert.ok(headers.some(h => /Endpoint 1 · a/.test(h)) && headers.some(h => /Endpoint 2 · b/.test(h)));
  assert.ok(headers.some(h => /Endpoint 2 − Endpoint 1/.test(h)));
  assert.equal(cell(view, 'availability'), 'AVAILABLE');
  assert.equal(cell(view, 'endpoint-1'), '0.2 deg / 0.8 deg / 0.6 deg');
  assert.equal(cell(view, 'endpoint-2'), '0.35 deg / 1.45 deg / 1.1 deg');
  assert.equal(cell(view, 'difference'), '+0.15 deg / +0.65 deg / +0.5 deg');
  assert.equal(cell(view, 'uncertainty'), 'UNAVAILABLE');
  const out = textOf(view.result());
  assert.match(out, /not recovery, improvement, or meaningful change/);
  assert.match(out, /not capture chronology/);
  assert.doesNotMatch(out, /\b(improved|recovered|favou?rable|better|worse)\b/i);
  const swapped = raw.comparison.research_measurements.coordinates[0];
  [swapped.session_1, swapped.session_2] = [swapped.session_2, swapped.session_1];
  const reversed = await shown(raw);
  assert.equal(cell(reversed, 'endpoint-1'), '0.35 deg / 1.45 deg / 1.1 deg');
  assert.equal(cell(reversed, 'difference'), '-0.15 deg / -0.65 deg / -0.5 deg');
});

test('mounted view never rounds small radian endpoints to zero', async () => {
  const raw = fresh();
  const rm = raw.comparison.research_measurements;
  for (const s of rm.sessions) s.contract.units.knee_angle_r = 'rad';
  rm.coordinates[0].unit = 'rad';
  rm.coordinates[0].session_1 = { min: 0.001, max: 0.005, excursion: 0.005 - 0.001 };
  rm.coordinates[0].session_2 = { min: 0.002, max: 0.0035, excursion: 0.0035 - 0.002 };
  const view = await shown(raw);
  assert.equal(cell(view, 'endpoint-1'), '0.001 rad / 0.005 rad / 0.004 rad');
  for (const key of ['endpoint-1', 'endpoint-2', 'difference']) assert.doesNotMatch(cell(view, key), /(^|\/ )[+-]?0 rad/);
});

test('changed pair source rows hide same-pair evidence at render time and do not resurrect it', async () => {
  const changes = [
    s => s.filter(x => x.id !== 'b'),
    s => s.map(x => x.id === 'b' ? { ...x, evidence_status: 'unverified' } : x),
    s => s.map(x => x.id === 'b' ? { ...x, status: 'invalid' } : x),
    s => s.map(x => x.id === 'a' ? { ...x, captured_roles: 5 } : x),
  ];
  for (const change of changes) {
    const view = await shown(fresh());
    assert.ok(view.result());
    view.render({ sessions: change(listing()) });
    assert.equal(view.result(), undefined, 'render-time guard before effects');
    view.settle();
    assert.equal(view.result(), undefined);
    view.settle({ sessions: listing() });
    assert.equal(view.result(), undefined, 'restored rows do not resurrect cleared evidence');
  }
});

test('polling with new but value-identical session objects keeps the comparison', async () => {
  const view = await shown(fresh());
  view.settle({ sessions: structuredClone(listing()) });
  view.settle({ sessions: listing().map(x => ({ ...x })) });
  assert.ok(view.result());
});

test('rapid target switch discards a stale successful response and accepts the new pair', async () => {
  const pending = {};
  const view = studio((s1, s2) => new Promise(resolve => { pending[s2] = resolve; }));
  view.choose('b');
  const first = view.compare();
  view.render();
  view.choose('c');
  pending.b(fresh());
  await first;
  view.settle();
  assert.equal(view.result(), undefined);
  assert.equal(textOf(compareButton(view.tree)).trim(), 'Compare');
  const second = view.compare();
  pending.c(withTarget(fresh(), 'c'));
  await second;
  view.settle();
  assert.match(textOf(view.result()), /Endpoint 2 · c/);
});

test('an older same-pair request cannot replace the newer request result', async () => {
  const resolvers = [];
  const view = studio(() => new Promise(resolve => resolvers.push(resolve)));
  view.choose('b');
  const first = view.compare();
  view.choose('c');
  view.choose('b');
  const second = view.compare();
  const older = fresh();
  older.comparison.research_measurements.sessions[1].metadata.operator_id = 'op-' + '3'.repeat(32);
  resolvers[0](older);
  await first;
  view.settle();
  assert.equal(view.result(), undefined);
  resolvers[1](fresh());
  await second;
  view.settle();
  assert.match(textOf(view.result()), /Operator: SAME across endpoints/);
});

test('a pending comparison is discarded after the selected session prop changes', async () => {
  let resolve;
  const view = studio(() => new Promise(r => { resolve = r; }));
  view.choose('b');
  const request = view.compare();
  view.settle({ selectedSession: 'c' });
  resolve(fresh());
  await request;
  view.settle();
  assert.equal(view.result(), undefined);
});

test('a target removed from the session list disables comparison and sends no request', async () => {
  let calls = 0;
  const view = studio(async () => { calls++; return fresh(); });
  view.choose('b');
  view.settle({ sessions: listing().filter(x => x.id !== 'b') });
  assert.equal(compareButton(view.tree).props.disabled, true);
  await view.compare();
  assert.equal(calls, 0);
});
