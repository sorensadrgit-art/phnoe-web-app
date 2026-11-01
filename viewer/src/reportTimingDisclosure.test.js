import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformSync } from 'esbuild';

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const fixturePath = path.join(directory, 'fixtures/comparisonRevision.generated.json');
const cases = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
assert.equal(cases.test_only, true);
assert.equal(cases.physical_accuracy_verified, false);

function moduleAt(filename, react) {
  const file = path.resolve(directory, filename), module = { exports: {} };
  const source = transformSync(fs.readFileSync(file, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(name => name === 'react' ? react : name.startsWith('.')
    ? moduleAt(path.resolve(path.dirname(file), name), react) : require(name), module, module.exports);
  return module.exports;
}
function nodes(tree, predicate, result = []) {
  if (tree && typeof tree === 'object') {
    if (predicate(tree)) result.push(tree);
    React.Children.forEach(tree.props?.children, child => nodes(child, predicate, result));
  }
  return result;
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return tree && typeof tree === 'object' ? React.Children.toArray(tree.props?.children).map(text).join('') : '';
}
// Expand the real hook-free timing child; this is SSR, not DOM or StrictMode proof.
function timingText(group) {
  return renderToStaticMarkup(group).replace(/<[^>]*>/g, '');
}
function studio(onCompareSessions, sessionRows = cases.before_rows) {
  const slots = [], effects = [];
  let index = 0, pending = [], props = { sessions: structuredClone(sessionRows), reports: [],
    selectedSession: 'a', busy: false, onSelectSession() {}, onCompareSessions };
  const react = { ...React,
    useState(initial) { const i = index++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(initial) { const i = index++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useMemo(fn) { index++; return fn(); },
    useEffect(fn, deps) { const i = index++, previous = effects[i];
      if (!previous || deps.some((value, n) => !Object.is(value, previous.deps[n]))) {
        pending.push(() => { previous?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; });
      }
    },
  };
  const Component = moduleAt('./ReportStudio.jsx', react).default;
  const view = {
    tree: null,
    render(next = {}) { props = { ...props, ...next }; index = 0; pending = []; view.tree = Component(props); return view.tree; },
    settle(next) { view.render(next); const current = pending; pending = []; current.forEach(effect => effect()); return view.render(); },
    choose(id) { nodes(view.tree, node => node.type === 'select' && /Select compatible session/.test(text(node)))[0]
      .props.onChange({ target: { value: id } }); return view.settle(); },
    button() { return nodes(view.tree, node => node.type === 'button' && /^(Compare|Comparing\.\.\.)$/.test(text(node).trim()))[0]; },
    compare() { return view.button().props.onClick(); },
    result() { return nodes(view.tree, node => node.props?.className?.split(' ').includes('uw-compare-result'))[0]; },
  };
  view.settle(); view.choose('b'); return view;
}

test('R04 generated comparison preserves endpoint identity and discloses unobserved timing', async () => {
  const response = structuredClone(cases.comparison);
  for (const source of response.comparison.research_measurements.sessions) delete source.timing;
  const payload = response.comparison;
  assert.equal(payload.research_measurements.status, 'AVAILABLE');
  assert.equal(payload.clinical_accuracy_verified, false);
  const view = studio(async () => structuredClone(response));
  await view.compare(); view.settle();
  const result = view.result();
  assert.ok(result, 'actual generated compatible comparison must render before timing assertions');
  const visible = text(result);
  for (const [index, source] of payload.research_measurements.sessions.entries()) {
    assert.ok(visible.includes(`Endpoint ${index + 1} · Session: ${source.session_id}`));
    assert.ok(visible.includes(`Subject (pseudonymous): ${source.metadata.subject_id}`));
    assert.ok(visible.includes(`Operator (pseudonymous): ${source.metadata.operator_id}`));
    assert.ok(visible.includes(`Task: ${source.metadata.task_id}`));
    assert.ok(visible.includes(`Protocol: ${source.metadata.protocol_id} · version ${source.metadata.protocol_version}`));
    for (const [label, digest] of [
      ['Model SHA-256', source.contract.model_sha256],
      ['Calibration SHA-256', source.contract.calibration_sha256],
      ['Session revision', source.source_revision.session_sha256],
      ['Run revision', source.source_revision.run_sha256],
      ['Motion revision', source.source_revision.motion_sha256],
    ]) assert.ok(visible.includes(`${label}: ${digest.slice(0, 12)}…`));
  }
  assert.ok(visible.includes('6/6 sources'));
  assert.ok(visible.includes('CLINICAL_VALIDATION: UNVERIFIED'));
  assert.ok(visible.includes('PHYSICAL_ACCURACY: UNVERIFIED'));
  const timing = nodes(result, node => node.props?.role === 'group' &&
    /^Endpoint [12] timing and review state$/.test(node.props?.['aria-label'] || ''));
  assert.equal(timing.length, 2, 'each bound endpoint must disclose unavailable duration and gap observations');
  for (const [index, group] of timing.entries()) {
    const id = index ? payload.session_2 : payload.session_1;
    const passport = index ? payload.passport_2 : payload.passport_1;
    const disclosure = timingText(group);
    assert.equal(group.props['aria-label'], `Endpoint ${index + 1} timing and review state`);
    assert.ok(disclosure.includes(`Endpoint ${index + 1} · Session: ${id}`));
    assert.ok(disclosure.includes(`Review state: ${passport.state}`));
    assert.ok(disclosure.includes('Valid duration: UNAVAILABLE'));
    assert.ok(disclosure.includes('Rejected duration: UNAVAILABLE'));
    assert.ok(disclosure.includes('Gap timeline: UNAVAILABLE'));
  }
  assert.ok(visible.includes('Timing partitions adjacent observed endpoints; decoded source extent and physical accuracy remain UNVERIFIED.'));
});

test('R04 generated producer comparison renders its actual bound timing observations', async () => {
  const generated = JSON.parse(fs.readFileSync(path.join(directory, 'fixtures/researchComparison.generated.json'), 'utf8'));
  assert.equal(generated.test_only, true);
  assert.equal(generated.research_only, true);
  assert.equal(generated.physical_accuracy_verified, false);
  const payload = generated.comparison;
  const view = studio(async () => structuredClone(payload), generated.session_rows);
  await view.compare(); view.settle();
  const result = view.result();
  assert.ok(result, 'the actual generated producer comparison must pass its row/source binding');
  const groups = nodes(result, node => node.props?.role === 'group' &&
    /^Endpoint [12] timing and review state$/.test(node.props?.['aria-label'] || ''));
  assert.equal(groups.length, 2);
  for (const [index, source] of payload.research_measurements.sessions.entries()) {
    const observed = source.timing;
    assert.equal(observed.status, 'AVAILABLE');
    assert.deepEqual(observed.sample_counts, { observed: 5, valid: 4, rejected: 1, missing_interior: 1 });
    const presented = nodes(groups[index], node => node.props?.timing)[0]?.props.timing;
    assert.deepEqual(presented, observed, 'endpoint timing disclosure must preserve the producer receipt');
    assert.equal(observed.bindings.session_id, source.session_id);
    assert.equal(observed.bindings.session_sha256, source.source_revision.session_sha256);
    assert.equal(observed.bindings.run_sha256, source.source_revision.run_sha256);
    const visible = timingText(groups[index]);
    assert.ok(visible.includes(`Endpoint ${index + 1} · Session: ${source.session_id}`));
    assert.ok(visible.includes('Observed samples: 5 · valid: 4 · rejected: 1 · missing interior: 1'));
    for (const [kind, label] of [
      ['valid_adjacent', 'valid adjacent endpoints'],
      ['rejected_or_transition_adjacent', 'rejected/transition adjacent'],
      ['unknown_gap', 'unknown gap'],
    ]) assert.ok(visible.includes(`${label}: ${observed.duration_s[kind].toFixed(6)} s`));
    assert.ok(visible.includes(`Observed span: ${observed.duration_s.observed_span.toFixed(6)} s · no endpoint extrapolation`));
    assert.equal(observed.gaps.length, 1);
    const [gap] = observed.gaps;
    assert.ok(visible.includes(`Unknown gap frames ${gap.first_missing_frame}–${gap.last_missing_frame} · ${gap.missing_samples} missing samples · adjacent bounds ${gap.left_time_s.toFixed(6)} s–${gap.right_time_s.toFixed(6)} s`));
    assert.ok(visible.includes('Physical accuracy: UNVERIFIED · Clinical validation: UNVERIFIED · Decoded source extent: UNVERIFIED'));
    assert.ok(!visible.includes('Valid duration: UNAVAILABLE'));
  }
});

test('R04 explicit unavailable timing stays unavailable on a bound generated comparison', async () => {
  const generated = JSON.parse(fs.readFileSync(path.join(directory, 'fixtures/researchComparison.generated.json'), 'utf8'));
  for (const source of generated.comparison.research_measurements.sessions) source.timing = {
    schema: 'kinelab.reconstruction-timing.v1', status: 'UNAVAILABLE',
    code: 'TIMING_NOT_REPORTED', reason: 'TIMING_NOT_REPORTED', duration_s: null,
    segments: [], gaps: [], intervals: [], physical_accuracy_verified: false,
    clinical_accuracy_verified: false, clinical_validation: 'UNVERIFIED',
  };
  const view = studio(async () => structuredClone(generated.comparison), generated.session_rows);
  await view.compare(); view.settle();
  const result = view.result();
  assert.ok(result);
  const groups = nodes(result, node => node.props?.role === 'group' &&
    /^Endpoint [12] timing and review state$/.test(node.props?.['aria-label'] || ''));
  assert.equal(groups.length, 2);
  for (const group of groups) {
    const visible = timingText(group);
    assert.ok(visible.includes('Valid duration: UNAVAILABLE'));
    assert.ok(visible.includes('Rejected duration: UNAVAILABLE'));
    assert.ok(visible.includes('Gap timeline: UNAVAILABLE'));
    assert.ok(visible.includes('TIMING_NOT_REPORTED'));
    assert.ok(!visible.includes('Observed samples:'));
  }
});
