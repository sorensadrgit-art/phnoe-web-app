import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { transformSync } from 'esbuild';

// Actual components and their callbacks, with deterministic hooks and no camera,
// browser, timers, physical participant, or network. TEST_ONLY identifiers only.
const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const metadata = () => ({
  schema: 'kinelab.session-metadata.v1', subject_id: 'sub-' + '1'.repeat(32),
  operator_id: 'op-' + '2'.repeat(32), task_id: 'TEST_ONLY-task',
  protocol_id: 'TEST_ONLY-protocol', protocol_version: '1', laterality: 'bilateral',
  confirmed: true, confirmed_at: '2026-10-29T13:00:00+00:00',
});
const confirmation = (id, value = metadata()) => ({
  schema: 'kinelab.session-metadata-readback.v1', session_id: id, status: 'AVAILABLE',
  metadata: value, source: { path: 'session-template.json', sha256: 'a'.repeat(64) },
  reason: 'TEST_ONLY format confirmation, not authentication',
});

function moduleAt(filename, overrides = {}) {
  const file = path.resolve(directory, filename), module = { exports: {} };
  // A RED replay can read the immutable prechange source without replacing any
  // application bytes. Imports still resolve against the actual source tree.
  const baseline = process.env.KINELAB_METADATA_RED_SNAPSHOT;
  const sourceFile = baseline && ['UnifiedApp.jsx', 'GuidedCaptureWizard.jsx'].includes(path.basename(file))
    ? path.join(baseline, 'viewer/src', path.basename(file)) : file;
  const source = transformSync(fs.readFileSync(sourceFile, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(
    name => Object.hasOwn(overrides, name) ? overrides[name]
      : name.startsWith('.') ? moduleAt(path.resolve(path.dirname(file), name), overrides) : require(name),
    module, module.exports,
  );
  return module.exports;
}

function mounted(filename, props, { overrides = {}, sessions = null } = {}) {
  const slots = [], effects = [];
  let index = 0, seeded = false;
  const react = { ...React,
    useState(initial) {
      const i = index++;
      if (!(i in slots)) {
        slots[i] = typeof initial === 'function' ? initial() : initial;
        if (sessions && !seeded && Array.isArray(initial) && initial.length === 0) {
          slots[i] = sessions; seeded = true;
        }
      }
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
function input(app, name) {
  const found = nodes(app.render(), n => n.props?.name === name)[0];
  assert.ok(found, 'Actual component field exists: ' + name);
  return found;
}
function fill(app) {
  const value = metadata();
  for (const name of ['subject_id', 'operator_id', 'task_id', 'protocol_id', 'protocol_version', 'laterality'])
    input(app, name).props.onChange({ target: { value: value[name] } });
}
function submit(app) {
  const form = nodes(app.render(), n => n.type === 'form')[0];
  assert.ok(form, 'Actual setup form exists');
  return form.props.onSubmit({ preventDefault() {} });
}
function submitButton(app) {
  return nodes(app.render(), n => n.type === 'button' && n.props.type === 'submit')[0];
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

test('setup starts blank and never generates identity on mount', async () => {
  let generated = 0, created = 0;
  await globals({ crypto: { randomUUID() { generated++; return '11111111-1111-4111-8111-111111111111'; } } }, () => {
    const app = mounted('./SessionMetadataSetup.jsx', { sessionId: 'TEST_ONLY-new', onCreate() { created++; } });
    for (const name of ['subject_id', 'operator_id', 'task_id', 'protocol_id', 'protocol_version', 'laterality'])
      assert.equal(input(app, name).props.value, '');
    assert.equal(input(app, 'metadata_confirmed').props.checked, false);
    assert.equal(submitButton(app).props.disabled, true);
    submit(app);
    assert.equal(created, 0);
    assert.equal(generated, 0);
  });
});

test('opaque identifiers are generated only by explicit secure buttons', async () => {
  let generated = 0;
  await globals({ crypto: { randomUUID() { generated++; return '11111111-1111-4111-8111-111111111111'; } } }, () => {
    const app = mounted('./SessionMetadataSetup.jsx', { sessionId: 'TEST_ONLY-new', onCreate() {} });
    for (const [label, field, prefix] of [['Generate subject ID', 'subject_id', 'sub-'], ['Generate operator ID', 'operator_id', 'op-']]) {
      const button = nodes(app.render(), n => n.type === 'button' && textOf(n) === label)[0];
      assert.ok(button, label); button.props.onClick();
      assert.equal(input(app, field).props.value, prefix + '11111111111141118111111111111111');
    }
    assert.equal(generated, 2);
  });
});

test('actual form requires deliberate confirmation, snapshots nine fields and invalidates edits', () => {
  const created = [];
  const app = mounted('./SessionMetadataSetup.jsx', { sessionId: 'TEST_ONLY-new', onCreate(value) { created.push(value); } });
  fill(app);
  assert.equal(submitButton(app).props.disabled, true);
  submit(app); assert.equal(created.length, 0);
  input(app, 'metadata_confirmed').props.onChange({ target: { checked: true } });
  assert.equal(submitButton(app).props.disabled, false);
  submit(app);
  assert.equal(created.length, 1);
  assert.deepEqual(Object.keys(created[0]).sort(), Object.keys(metadata()).sort());
  assert.deepEqual({ ...created[0], confirmed_at: metadata().confirmed_at }, metadata());
  assert.ok(Number.isFinite(Date.parse(created[0].confirmed_at)));
  input(app, 'laterality').props.onChange({ target: { value: 'left' } });
  assert.equal(input(app, 'metadata_confirmed').props.checked, false);
  assert.equal(submitButton(app).props.disabled, true);
  assert.equal(created[0].laterality, 'bilateral');
});

test('busy form blocks all metadata changes and submit callbacks', () => {
  let created = 0;
  const app = mounted('./SessionMetadataSetup.jsx', { sessionId: 'TEST_ONLY-new', busy: true, onCreate() { created++; } });
  for (const control of nodes(app.render(), n => ['input', 'select', 'button'].includes(n.type)))
    assert.equal(control.props.disabled, true);
  submit(app); assert.equal(created, 0);
});

test('strict frontend confirmation rejects malformed, extra, missing and mismatched source identities', () => {
  const { metadataConfirmationMatches } = moduleAt('./sessionMetadataSetup.js');
  assert.equal(metadataConfirmationMatches(confirmation('TEST_ONLY-new'), 'TEST_ONLY-new', metadata()), true);
  for (const value of [null, {}, confirmation('other'), { ...confirmation('TEST_ONLY-new'), status: 'UNAVAILABLE' },
    { ...confirmation('TEST_ONLY-new'), source: { path: '../session.json', sha256: 'a'.repeat(64) } },
    { ...confirmation('TEST_ONLY-new'), source: { path: 'session.json', sha256: '' } },
    confirmation('TEST_ONLY-new', { ...metadata(), confirmed: 'true' }),
    confirmation('TEST_ONLY-new', { ...metadata(), confirmed_at: '2026-10-29T13:00:00' }),
    confirmation('TEST_ONLY-new', { ...metadata(), extra: 'not-in-contract' }),
    confirmation('TEST_ONLY-new', { ...metadata(), subject_id: 'patient-name' }),
    confirmation('TEST_ONLY-new', { ...metadata(), laterality: 'left' })])
    assert.equal(metadataConfirmationMatches(value, 'TEST_ONLY-new', metadata()), false);
});

test('summary uses only persisted confirmation bound to the selected session', () => {
  const { MetadataConfirmationSummary } = moduleAt('./SessionMetadataSetup.jsx');
  const available = textOf(MetadataConfirmationSummary({ confirmation: confirmation('TEST_ONLY-new'), sessionId: 'TEST_ONLY-new' }));
  assert.ok(available.includes(metadata().subject_id));
  assert.ok(available.includes('bilateral'));
  for (const value of [null, confirmation('other'), { ...confirmation('TEST_ONLY-new'), status: 'UNAVAILABLE' }]) {
    const unavailable = textOf(MetadataConfirmationSummary({ confirmation: value, sessionId: 'TEST_ONLY-new' }));
    assert.ok(unavailable.includes('UNAVAILABLE'));
    assert.ok(!unavailable.includes(metadata().subject_id));
  }
});

function placeholder(name) {
  const component = () => null;
  Object.defineProperty(component, 'name', { value: name });
  return { __esModule: true, default: component };
}
function unified() {
  const overrides = Object.fromEntries(['MotionApp', 'EvidencePassport', 'ReportStudio', 'LiveTrackerStudio', 'GuidedCaptureWizard', 'SessionMetadataSetup']
    .map(name => ['./' + name + '.jsx', placeholder(name)]));
  return mounted('./UnifiedApp.jsx', {}, { overrides, sessions: [{ id: 'TEST_ONLY-B', kind: 'real', status: 'draft', captured_roles: [] }] });
}
function beginCreate(app) {
  let setup = nodes(app.render(), n => n.type?.name === 'SessionMetadataSetup')[0];
  if (setup) {
    setup.props.onSessionIdChange('TEST_ONLY-created');
    setup = nodes(app.render(), n => n.type?.name === 'SessionMetadataSetup')[0];
    return setup.props.onCreate(metadata());
  }
  // Exercise the actual prechange callback too, so RED captures the concrete
  // existing missing-metadata and stale-selection defects, not a missing test adapter.
  const field = nodes(app.render(), n => n.type === 'input' && n.props.placeholder === 'e.g. gait-pilot-01')[0];
  assert.ok(field, 'Creation input missing; inputs=' + JSON.stringify(nodes(app.render(), n => n.type === 'input').map(n => n.props.placeholder))
    + '; text=' + textOf(app.render()).slice(0, 180) + '; view=' + JSON.stringify(app.slots.slice(2, 4)));
  field.props.onChange({ target: { value: 'TEST_ONLY-created' } });
  const button = nodes(app.render(), n => n.type === 'button' && textOf(n) === 'Create session')[0];
  assert.ok(button); return button.props.onClick();
}
async function creationCase(action, result = { id: 'TEST_ONLY-created', metadata_confirmation: confirmation('TEST_ONLY-created') }) {
  const storage = new Map([['kinelab_active_tab', 'sessions'], ['kinelab_selected_session', 'TEST_ONLY-A'], ['kinelab_t6_token', 'a'.repeat(50)]]);
  const requests = []; let resolveCreate;
  const create = new Promise(resolve => { resolveCreate = resolve; });
  await globals({
    window: { location: { hash: '#access=' + 'a'.repeat(64) }, confirm() { return true; } },
    localStorage: { getItem(key) { return storage.get(key) ?? null; }, setItem(key, value) { storage.set(key, String(value)); } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (options.method === 'POST' && url === '/api/v1/sessions') return create;
      return { ok: true, json: async () => ({ sessions: [
        { id: 'TEST_ONLY-A', kind: 'real', status: 'draft' },
        { id: 'TEST_ONLY-B', kind: 'real', status: 'draft' },
      ] }) };
    },
  }, async () => {
    const app = unified();
    app.render();
    const boot = app.effects.find(effect => effect?.fn.toString().includes('setLoading'));
    assert.ok(boot, 'Actual initial library-load effect exists');
    const cleanup = boot.fn();
    await new Promise(resolve => setImmediate(resolve));
    try {
      const completion = beginCreate(app);
      await action({ app, storage, requests, resolve() { resolveCreate({ ok: true, json: async () => result }); } });
      await completion;
      await new Promise(resolve => setImmediate(resolve));
    } finally { cleanup?.(); }
  });
}

test('actual UnifiedApp creation forwards the confirmed metadata snapshot', async () => {
  await creationCase(async ({ requests, resolve }) => {
    const body = JSON.parse(requests.find(item => item.options.method === 'POST').options.body);
    assert.deepEqual(body, { id: 'TEST_ONLY-created', kind: 'real', metadata: metadata() });
    resolve();
  });
});

test('late actual creation response cannot replace a subsequently selected session', async () => {
  await creationCase(async ({ app, storage, resolve }) => {
    const row = nodes(app.render(), n => n.type === 'button' && n.key === 'TEST_ONLY-B')[0];
    assert.ok(row); row.props.onClick();
    resolve(); await new Promise(done => setImmediate(done));
    assert.equal(storage.get('kinelab_selected_session'), 'TEST_ONLY-B');
  });
});

test('actual creation refuses mismatched persisted metadata before selecting the response', async () => {
  await creationCase(async ({ storage, resolve }) => {
    resolve(); await new Promise(done => setImmediate(done));
    assert.equal(storage.get('kinelab_selected_session'), 'TEST_ONLY-A');
  }, { id: 'TEST_ONLY-wrong', metadata_confirmation: confirmation('TEST_ONLY-wrong') });
});

test('actual capture wizard keeps participant capture disabled and shows bound readback', () => {
  const props = {
    selectedSession: 'TEST_ONLY-new', detail: { id: 'TEST_ONLY-new', metadata_confirmation: confirmation('TEST_ONLY-new'), roles: [] },
    activeSession: { kind: 'real' }, cameraState: null, busy: '',
  };
  const app = mounted('./GuidedCaptureWizard.jsx', props);
  const tree = app.render();
  const summary = nodes(tree, n => n.type?.name === 'MetadataConfirmationSummary')[0];
  assert.ok(summary, 'Wizard must consume the shared persisted confirmation summary');
  assert.equal(summary.props.confirmation.session_id, 'TEST_ONLY-new');
  for (const button of nodes(tree, n => n.type === 'button' && /Open Capture Station|Record Webcam|Start Recording/.test(textOf(n))))
    assert.equal(button.props.disabled, true);
  assert.ok(textOf(tree).includes('PARTICIPANT_RECORDING_BLOCKED'));
  const stale = app.render({ ...props, detail: { ...props.detail, id: 'TEST_ONLY-other' } });
  const staleSummary = nodes(stale, n => n.type?.name === 'MetadataConfirmationSummary')[0];
  assert.equal(staleSummary.props.confirmation, null);
});
