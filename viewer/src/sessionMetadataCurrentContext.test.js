import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { transformSync } from 'esbuild';

// W2.2: the current (effective) registered metadata is shown separately from the
// immutable original confirmation, and comparison requests are bound to the
// current metadata contexts. Actual components only; TEST_ONLY identifiers; no
// camera, browser, timers, physical participant or network.
const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const HEX64 = /^[0-9a-f]{64}$/;
const CTX_A1 = 'c'.repeat(64), CTX_A2 = 'e'.repeat(64), CTX_B = 'd'.repeat(64);
const EFFECTIVE_LABEL = 'Current effective session metadata';
const CORRECTION_CHECKBOX = 'metadata_correction_confirmed';
const REVISION_KEYS = ['confirm', 'expected_head_sha256', 'expected_origin_sha256', 'metadata', 'operation_id', 'reason_code'];

const metadata = () => ({
  schema: 'kinelab.session-metadata.v1', subject_id: 'sub-' + '1'.repeat(32),
  operator_id: 'op-' + '2'.repeat(32), task_id: 'TEST_ONLY-task',
  protocol_id: 'TEST_ONLY-protocol', protocol_version: '1', laterality: 'bilateral',
  confirmed: true, confirmed_at: '2026-10-29T13:00:00+00:00',
});
const corrected = () => ({ ...metadata(), laterality: 'left', confirmed_at: '2026-10-29T14:00:00+00:00' });
const confirmation = (id, value = metadata()) => ({
  schema: 'kinelab.session-metadata-readback.v1', session_id: id, status: 'AVAILABLE',
  metadata: value, source: { path: 'session-template.json', sha256: 'a'.repeat(64) },
  reason: 'TEST_ONLY format confirmation, not authentication',
});
// Mirrors session_metadata_revision.read_metadata_state and its t6_service list/detail projection.
const ORIGIN_SHA = '0123456789abcdef'.repeat(4);
const headRef = digit => ({ path: 'metadata-revisions/revision-' + digit.repeat(32) + '/revision.json', sha256: digit.repeat(64) });
const metadataState = (id, { value = corrected(), head = headRef('7'), context = CTX_A1, ...extra } = {}) => ({
  schema: 'kinelab.session-metadata-state.v1', session_id: id, status: 'AVAILABLE',
  metadata: value, initial_metadata: metadata(), origin: { path: 'session.json', sha256: ORIGIN_SHA },
  head, context_sha256: context, reason: 'Verified immutable origin and audited revision chain', ...extra,
});
const unavailableState = id => ({
  schema: 'kinelab.session-metadata-state.v1', session_id: id, status: 'UNAVAILABLE',
  metadata: null, initial_metadata: null, origin: null, head: null, context_sha256: null,
  reason: 'METADATA_UNAVAILABLE: TEST_ONLY',
});
const projected = state => ({ metadata_state: state,
  effective_metadata: state?.status === 'AVAILABLE' ? state.metadata : null,
  metadata_context_sha256: state?.status === 'AVAILABLE' ? state.context_sha256 : null });
const currentDetail = (id, overrides = {}, state = metadataState(id)) => ({
  id, kind: 'real', status: 'registered', roles: [], metadata_confirmation: confirmation(id),
  ...projected(state), ...overrides,
});
const firstRevisionDetail = id => currentDetail(id, {}, metadataState(id, { value: metadata(), head: null }));

function moduleAt(filename, overrides = {}) {
  const file = path.resolve(directory, filename), module = { exports: {} };
  const source = transformSync(fs.readFileSync(file, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(
    name => Object.hasOwn(overrides, name) ? overrides[name]
      : name.startsWith('.') ? moduleAt(path.resolve(path.dirname(file), name), overrides) : require(name),
    module, module.exports,
  );
  return module.exports;
}

function mounted(filename, props, { overrides = {} } = {}) {
  const slots = [], effects = [];
  let index = 0;
  const react = { ...React,
    useState(initial) {
      const i = index++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
    },
    useRef(value) { const i = index++; if (!(i in slots)) slots[i] = { current: value }; return slots[i]; },
    useMemo(fn) { index++; return fn(); },
    useCallback(fn) { index++; return fn; },
    useEffect(fn, deps) { effects[index++] = { fn, deps }; },
  };
  const Component = moduleAt(filename, { react: { __esModule: true, default: react, ...react }, ...overrides }).default;
  return { render(next = props) { props = next; index = 0; return Component(props); }, slots, effects };
}

function nodes(tree, predicate, found = []) {
  if (tree && typeof tree === 'object') {
    if (predicate(tree)) found.push(tree);
    React.Children.forEach(tree.props?.children, child => nodes(child, predicate, found));
  }
  return found;
}
function textOf(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree !== 'object') return String(tree);
  return React.Children.toArray(tree.props?.children).map(textOf).join('');
}
async function globals(values, action) {
  const previous = Object.fromEntries(Object.keys(values).map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  for (const [name, value] of Object.entries(values)) Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  try { return await action(); }
  finally {
    for (const [name, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];
    }
  }
}
const tick = () => new Promise(resolve => setImmediate(resolve));

// ---------- GuidedCaptureWizard: effective-current summary ----------
const wizardProps = detail => ({ selectedSession: 'TEST_ONLY-new', detail, activeSession: { kind: 'real', status: 'registered' }, cameraState: null, busy: '' });
function effectiveRegion(tree) {
  const region = nodes(tree, n => n.props?.['aria-label'] === EFFECTIVE_LABEL)[0];
  assert.ok(region, 'Wizard must render a separately labelled "' + EFFECTIVE_LABEL + '" region');
  return region;
}

test('W22-UI-01 wizard shows corrected effective metadata separately from the immutable original', () => {
  const app = mounted('./GuidedCaptureWizard.jsx', wizardProps(currentDetail('TEST_ONLY-new')));
  const tree = app.render();
  const region = effectiveRegion(tree);
  const current = textOf(region);
  assert.ok(current.includes('AVAILABLE'), 'Effective region reports AVAILABLE state');
  assert.ok(current.includes('left'), 'Effective region shows corrected laterality');
  assert.ok(current.includes(CTX_A1.slice(0, 12)), 'Effective region shows its metadata context digest');
  assert.ok(!current.includes('bilateral'), 'Original laterality is not presented as current');
  const original = nodes(tree, n => n.type?.name === 'MetadataConfirmationSummary')[0];
  assert.ok(original, 'Original persisted confirmation summary remains');
  assert.notEqual(original, region);
  assert.equal(original.props.confirmation.metadata.laterality, 'bilateral');
});

test('W22-UI-02 unavailable or tampered effective state never shows the original or corrected value as current', () => {
  const id = 'TEST_ONLY-new', tampered = value => currentDetail(id, {}, metadataState(id, { value }));
  const context = value => currentDetail(id, {}, metadataState(id, { context: value }));
  for (const [label, detail] of [
    ['full UNAVAILABLE state', currentDetail(id, {}, unavailableState(id))],
    ['malformed string state', currentDetail(id, { metadata_state: 'AVAILABLE' })],
    ['state missing', currentDetail(id, { metadata_state: undefined })],
    ['unknown state field', currentDetail(id, {}, metadataState(id, { extra: 'not-in-contract' }))],
    ['extra metadata field', tampered({ ...corrected(), extra: 'not-in-contract' })],
    ['metadata not confirmed', tampered({ ...corrected(), confirmed: 'true' })],
    ['effective metadata missing', currentDetail(id, { effective_metadata: undefined })],
    ['uppercase context', context('C'.repeat(64))],
    ['short context', context('c'.repeat(63))],
    ['context missing', context(null)],
  ]) {
    const app = mounted('./GuidedCaptureWizard.jsx', wizardProps(detail));
    const current = textOf(effectiveRegion(app.render()));
    assert.ok(current.includes('UNAVAILABLE'), label + ': UNAVAILABLE shown');
    assert.ok(!current.includes('left'), label + ': corrected value withheld');
    assert.ok(!current.includes('bilateral'), label + ': original not presented as current');
    assert.ok(!current.includes(CTX_A1.slice(0, 12)), label + ': context digest withheld');
  }
});

test('W22-UI-03 selected-session mismatch refuses effective metadata', () => {
  const app = mounted('./GuidedCaptureWizard.jsx', wizardProps(currentDetail('TEST_ONLY-other')));
  const current = textOf(effectiveRegion(app.render()));
  assert.ok(current.includes('UNAVAILABLE'));
  assert.ok(!current.includes('left'));
  assert.ok(!current.includes(CTX_A1.slice(0, 12)));
});

test('W22-UI-04 same-session metadata context change resets correction confirmation', () => {
  const props = wizardProps(currentDetail('TEST_ONLY-new'));
  const app = mounted('./GuidedCaptureWizard.jsx', props);
  const checkbox = () => nodes(app.render(), n => n.type === 'input' && n.props?.name === CORRECTION_CHECKBOX)[0];
  assert.ok(checkbox(), 'Wizard must offer a deliberate correction confirmation checkbox: ' + CORRECTION_CHECKBOX);
  checkbox().props.onChange({ target: { checked: true } });
  assert.equal(checkbox().props.checked, true, 'Precondition: correction confirmation can be checked');
  const nextState = metadataState('TEST_ONLY-new', { head: headRef('8'), context: CTX_A2 });
  const changed = wizardProps(currentDetail('TEST_ONLY-new', {}, nextState));
  app.render(changed);
  const keys = [CTX_A2, nextState, changed.detail];
  for (const effect of app.effects.filter(item => item?.deps?.some(dep => keys.includes(dep)))) effect.fn();
  const after = nodes(app.render(changed), n => n.type === 'input' && n.props?.name === CORRECTION_CHECKBOX)[0];
  assert.ok(after);
  assert.equal(after.props.checked, false, 'A new metadata context must clear the earlier correction confirmation');
});

// ---------- UnifiedApp: correction envelope, stale success and compare contexts ----------
function placeholder(name) {
  const component = () => null;
  Object.defineProperty(component, 'name', { value: name });
  return { __esModule: true, default: component };
}
function unified() {
  const overrides = Object.fromEntries(['MotionApp', 'EvidencePassport', 'ReportStudio', 'LiveTrackerStudio', 'GuidedCaptureWizard', 'SessionMetadataSetup']
    .map(name => ['./' + name + '.jsx', placeholder(name)]));
  return mounted('./UnifiedApp.jsx', {}, { overrides });
}
const sessionRow = (id, context) => ({ id, kind: 'real', status: 'registered', captured_roles: [],
  ...projected(context === undefined ? unavailableState(id) : metadataState(id, { context })) });

async function unifiedCase({ tab, list, details = {} }, action) {
  const storage = new Map([['kinelab_active_tab', tab], ['kinelab_selected_session', 'TEST_ONLY-A'], ['kinelab_t6_token', 'a'.repeat(50)]]);
  const requests = [], state = { list, revision: null };
  const ok = body => ({ ok: true, status: 200, json: async () => body });
  await globals({
    window: { location: { hash: '#access=' + 'a'.repeat(64) }, confirm() { return true; } },
    localStorage: { getItem(key) { return storage.get(key) ?? null; }, setItem(key, value) { storage.set(key, String(value)); } },
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      const method = options.method || 'GET';
      if (method === 'POST' && /\/metadata-revisions$/.test(url)) return new Promise(resolve => { state.revision = resolve; });
      if (url === '/api/v1/sessions') return ok({ sessions: state.list });
      if (url === '/api/v1/analysis') return ok({});
      if (url.startsWith('/api/v1/compare')) return ok({ status: 'UNAVAILABLE', coordinates: [], reason: 'TEST_ONLY stub' });
      const match = url.match(/^\/api\/v1\/sessions\/([^/]+)(\/[a-z]+)?$/);
      if (match) {
        const id = decodeURIComponent(match[1]);
        if (!match[2]) return ok(details[id] ?? { id });
        if (match[2] === '/reports') return ok({ session_id: id, reports: [] });
        return ok({ session_id: id });
      }
      return { ok: false, status: 404, json: async () => ({ error: 'TEST_ONLY unexpected ' + url }) };
    },
  }, async () => {
    const app = unified();
    app.render();
    const boot = app.effects.find(effect => effect?.fn.toString().includes('setLoading'));
    assert.ok(boot, 'Actual initial library-load effect exists');
    const cleanups = [boot.fn()];
    await tick(); await tick();
    try {
      await action({ app, storage, requests, state,
        async reloadSessions(next) {
          state.list = next; app.render();
          const again = app.effects.find(effect => effect?.fn.toString().includes('setLoading'));
          cleanups.push(again.fn()); await tick(); await tick();
        },
        async loadSelected() {
          app.render();
          const effect = app.effects.find(item => item?.fn.toString().includes('refreshSelected(selected).catch(')
            && !item.fn.toString().includes('setInterval'));
          assert.ok(effect, 'Actual selected-session load effect exists');
          cleanups.push(effect.fn()); await tick(); await tick();
        },
      });
    } finally { for (const cleanup of cleanups) cleanup?.(); }
  });
}
const placeholderProps = (app, name) => {
  const found = nodes(app.render(), n => n.type?.name === name)[0];
  assert.ok(found, name + ' is rendered');
  return found.props;
};
const revisionPost = (requests, id) => requests.find(item => item.options?.method === 'POST'
  && item.url === '/api/v1/sessions/' + encodeURIComponent(id) + '/metadata-revisions');

test('W22-UI-05 correction submits exactly the six-field revision envelope for the selected session', async () => {
  await unifiedCase({ tab: 'capture', list: [sessionRow('TEST_ONLY-A', CTX_A1), sessionRow('TEST_ONLY-B', CTX_B)],
    details: { 'TEST_ONLY-A': firstRevisionDetail('TEST_ONLY-A') } }, async ({ app, requests, state, loadSelected }) => {
    await loadSelected();
    const wizard = placeholderProps(app, 'GuidedCaptureWizard');
    assert.equal(typeof wizard.onCorrectMetadata, 'function', 'UnifiedApp must pass onCorrectMetadata to the wizard');
    const completion = wizard.onCorrectMetadata(corrected());
    await tick();
    const post = revisionPost(requests, 'TEST_ONLY-A');
    assert.ok(post, 'Correction POSTs to /api/v1/sessions/{sid}/metadata-revisions');
    assert.equal(post.options.headers['Content-Type'], 'application/json');
    const body = JSON.parse(post.options.body);
    assert.deepEqual(Object.keys(body).sort(), REVISION_KEYS);
    assert.deepEqual(body.metadata, corrected());
    assert.notEqual(ORIGIN_SHA, confirmation('TEST_ONLY-A').source.sha256, 'Fixture precondition: origin differs from confirmation source');
    assert.equal(body.expected_origin_sha256, ORIGIN_SHA, 'Origin digest comes from metadata_state.origin');
    assert.equal(body.expected_head_sha256, null, 'First revision carries a null expected head');
    assert.match(body.operation_id, /^[0-9a-f]{32}$/);
    assert.equal(body.reason_code, 'operator_correction');
    assert.equal(body.confirm, true);
    assert.ok(new TextEncoder().encode(post.options.body).length <= 64 * 1024);
    state.revision?.({ ok: true, status: 200, json: async () => ({ session_id: 'TEST_ONLY-A', status: 'TEST_ONLY receipt' }) });
    await completion; await tick();
  });
});

test('W22-UI-06 a late correction success for session A cannot attach to subsequently selected session B', async () => {
  await unifiedCase({ tab: 'capture', list: [sessionRow('TEST_ONLY-A', CTX_A1), sessionRow('TEST_ONLY-B', CTX_B)],
    details: { 'TEST_ONLY-A': firstRevisionDetail('TEST_ONLY-A') } }, async ({ app, storage, requests, state, loadSelected }) => {
    await loadSelected();
    const wizard = placeholderProps(app, 'GuidedCaptureWizard');
    assert.equal(typeof wizard.onCorrectMetadata, 'function', 'UnifiedApp must pass onCorrectMetadata to the wizard');
    const completion = wizard.onCorrectMetadata(corrected());
    await tick();
    assert.ok(revisionPost(requests, 'TEST_ONLY-A'), 'Precondition: correction for A is in flight');
    const nav = nodes(app.render(), n => n.type === 'button' && n.key === 'sessions')[0];
    assert.ok(nav, 'Sessions navigation exists'); nav.props.onClick();
    const row = nodes(app.render(), n => n.type === 'button' && n.key === 'TEST_ONLY-B')[0];
    assert.ok(row, 'Session B row exists'); row.props.onClick();
    const before = requests.length;
    state.revision({ ok: true, status: 200, json: async () => ({ session_id: 'TEST_ONLY-A', status: 'TEST_ONLY receipt' }) });
    await completion; await tick(); await tick();
    assert.equal(storage.get('kinelab_selected_session'), 'TEST_ONLY-B');
    assert.deepEqual(requests.slice(before).filter(item => item.url.startsWith('/api/v1/sessions/TEST_ONLY-A')).map(item => item.url), [],
      'No session A refresh is attached after B is selected');
    const shown = app.slots.filter(slot => slot && typeof slot === 'object' && typeof slot.text === 'string' && slot.type);
    assert.ok(!shown.some(slot => slot.type !== 'error' && slot.text.includes('TEST_ONLY-A')), 'No success notice for A is shown while B is selected');
  });
});

function compareParams(requests) {
  return requests.filter(item => item.url.startsWith('/api/v1/compare')).map(item => new URL(item.url, 'http://localhost').searchParams);
}

test('W22-UI-07 comparison sends both current lowercase metadata contexts and never a cached earlier one', async () => {
  await unifiedCase({ tab: 'reports', list: [sessionRow('TEST_ONLY-A', CTX_A1), sessionRow('TEST_ONLY-B', CTX_B)] },
    async ({ app, requests, reloadSessions }) => {
    await placeholderProps(app, 'ReportStudio').onCompareSessions('TEST_ONLY-A', 'TEST_ONLY-B');
    let [params] = compareParams(requests);
    assert.ok(params, 'Comparison request issued');
    assert.deepEqual(params.getAll('s1'), ['TEST_ONLY-A']);
    assert.deepEqual(params.getAll('s2'), ['TEST_ONLY-B']);
    assert.deepEqual(params.getAll('expected_metadata_context_s1'), [CTX_A1]);
    assert.deepEqual(params.getAll('expected_metadata_context_s2'), [CTX_B]);
    await reloadSessions([sessionRow('TEST_ONLY-A', CTX_A2), sessionRow('TEST_ONLY-B', CTX_B)]);
    await placeholderProps(app, 'ReportStudio').onCompareSessions('TEST_ONLY-A', 'TEST_ONLY-B');
    params = compareParams(requests)[1];
    assert.ok(params, 'Second comparison request issued');
    assert.deepEqual(params.getAll('expected_metadata_context_s1'), [CTX_A2], 'Updated context replaces the cached one');
    assert.deepEqual(params.getAll('expected_metadata_context_s2'), [CTX_B]);
  });
});

test('W22-UI-08 comparison is refused locally when either current context is missing or malformed', async () => {
  for (const [label, rowB] of [
    ['missing B context', sessionRow('TEST_ONLY-B')],
    ['uppercase B context', sessionRow('TEST_ONLY-B', 'D'.repeat(64))],
    ['short B context', sessionRow('TEST_ONLY-B', 'd'.repeat(63))],
  ]) {
    await unifiedCase({ tab: 'reports', list: [sessionRow('TEST_ONLY-A', CTX_A1), rowB] }, async ({ app, requests }) => {
      await assert.rejects(() => placeholderProps(app, 'ReportStudio').onCompareSessions('TEST_ONLY-A', 'TEST_ONLY-B'),
        undefined, label + ': comparison must reject without a valid pair of contexts');
      assert.equal(compareParams(requests).length, 0, label + ': no partial or legacy comparison request is sent');
    });
  }
});

// TEST_ONLY component-state regressions; no camera, browser or physical validation.
const flightBoxes = tree => nodes(tree, n => n.type === 'input'
  && n.props?.type === 'checkbox' && !n.props?.name);
function confirmFlightChecks(app, props) {
  for (let index = 0; index < 4; index++) flightBoxes(app.render(props))[index].props.onChange();
  assert.equal(flightBoxes(app.render(props)).length, 4);
  assert.ok(flightBoxes(app.render(props)).every(box => box.props.checked === true));
  assert.ok(textOf(app.render(props)).includes('Operator checklist reported'));
}
function assertFlightIncomplete(app, props) {
  const tree = app.render(props);
  assert.equal(flightBoxes(tree).length, 4);
  assert.ok(flightBoxes(tree).every(box => box.props.checked === false));
  assert.ok(textOf(tree).includes('Checklist Incomplete'));
  assert.ok(!textOf(tree).includes('Operator checklist reported'));
  assert.ok(textOf(tree).includes('PARTICIPANT_RECORDING_BLOCKED'));
}

test('R03-UI-01 same-session protocol and metadata context invalidate operator checklist', () => {
  const id = 'TEST_ONLY-new';
  const changes = [
    metadataState(id, { value: { ...corrected(), protocol_id: 'TEST_ONLY-next-protocol' }, context: CTX_A2 }),
    metadataState(id, { value: { ...corrected(), protocol_version: '2' }, context: CTX_A2 }),
    metadataState(id, { value: { ...corrected(), task_id: 'TEST_ONLY-next-task' }, head: headRef('8'), context: CTX_A2 }),
  ];
  for (const state of changes) {
    const props = wizardProps(currentDetail(id));
    const app = mounted('./GuidedCaptureWizard.jsx', props);
    confirmFlightChecks(app, props);
    const changed = wizardProps(currentDetail(id, {}, state));
    assertFlightIncomplete(app, changed);
    confirmFlightChecks(app, changed);
    assertFlightIncomplete(app, props);
  }
});

test('R03-UI-02 refresh preserves report but unavailable or mismatched context discards it', () => {
  const id = 'TEST_ONLY-new';
  for (const changed of [
    wizardProps(currentDetail(id, {}, unavailableState(id))),
    wizardProps(currentDetail('TEST_ONLY-other')),
  ]) {
    const props = wizardProps(currentDetail(id));
    const app = mounted('./GuidedCaptureWizard.jsx', props);
    confirmFlightChecks(app, props);
    const refreshed = wizardProps(currentDetail(id));
    assert.ok(flightBoxes(app.render(refreshed)).every(box => box.props.checked === true));
    assertFlightIncomplete(app, changed);
    const refused = flightBoxes(app.render(changed));
    assert.ok(refused.every(box => box.props.disabled === true));
    for (const box of refused) box.props.onChange();
    assertFlightIncomplete(app, changed);
    assertFlightIncomplete(app, props);
  }
});
