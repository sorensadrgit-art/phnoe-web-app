import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { transformSync } from 'esbuild';

// TEST_ONLY report-generation caller contract; helper copied from reviewed manual caller fixture.
// Child and fetch doubles only; no React DOM, StrictMode, browser or physical proof.
// Distinct metadata and report context digests; no client-side digest computation.
// Production callers and currentMetadataState execute when a later runtime lease is granted.
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
    useCallback(fn, deps) {
      const i = index++, previous = slots[i];
      if (!previous || !deps || deps.some((value, n) => !Object.is(value, previous.deps?.[n]))) slots[i] = { fn, deps };
      return slots[i].fn;
    },
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

const A = 'TEST_ONLY-A', B = 'TEST_ONLY-B';
const REPORT_SHA = '9'.repeat(64);
const HEAD = { generation: 'report-' + '8'.repeat(32), manifest_sha256: '6'.repeat(64) };
const context = (head = null) => ({ schema: 'kinelab.report-generation-context.v1', session_id: A,
  status: 'AVAILABLE', report_context_sha256: REPORT_SHA, head, reason: null });
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const settle = async () => { for (let index = 0; index < 6; index++) await tick(); };
const props = app => {
  const node = nodes(app.render(), value => value.type?.name === 'ReportStudio')[0];
  assert.ok(node, 'Actual UnifiedApp renders ReportStudio child');
  return node.props;
};
const notice = app => nodes(app.render(), value => value.type?.name === 'Notice')[0]?.props.message;
const reportCalls = requests => requests.filter(item => /\/(report-context|reports\/generate)$/.test(item.url));
const posts = requests => requests.filter(item => item.options.method === 'POST');
async function scenario({ list = [sessionRow(A, CTX_A1)], get = async () => response(context()),
  post = async () => response({ message: 'TEST_ONLY publication accepted' }, 201), cleanup } = {}, action) {
  const storage = new Map([['kinelab_active_tab', 'reports'], ['kinelab_selected_session', A], ['kinelab_t6_token', 'a'.repeat(50)]]);
  const requests = [], state = { list };
  await globals({
    window: { location: { hash: '#access=' + 'a'.repeat(64) }, confirm: () => true },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)) },
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      if (/\/report-context$/.test(url)) return get(url, options);
      if (/\/reports\/generate$/.test(url)) return post(url, options);
      if (url === '/api/v1/sessions') return response({ sessions: state.list });
      if (url === '/api/v1/analysis') return response({});
      const match = url.match(/^\/api\/v1\/sessions\/([^/]+)(\/[a-z]+)?$/);
      if (match) {
        const sid = decodeURIComponent(match[1]);
        if (!match[2]) return response(currentDetail(sid, { kind: state.list.find(row => row.id === sid)?.kind || 'real' }));
        if (match[2] === '/reports') return response({ session_id: sid, reports: [] });
        return response({ session_id: sid });
      }
      return response({ error: 'TEST_ONLY unexpected URL ' + url }, 404);
    },
  }, async () => {
    const app = unified(); app.render();
    const boot = app.effects.find(effect => effect?.fn.toString().includes('setLoading'));
    assert.ok(boot, 'Reviewed actual library-load effect exists');
    const cleanups = [boot.fn()]; await settle(); app.render();
    try {
      await action({ app, requests, state, async refreshMetadata(next) {
        state.list = next; app.render();
        const reload = app.effects.find(effect => effect?.fn.toString().includes('setLoading'));
        cleanups.push(reload.fn()); await settle(); app.render();
      } });
    } finally { cleanup?.(); await settle(); for (const dispose of cleanups) dispose?.(); }
  });
}

// Eight top-level cases; explicit variant labels below are diagnostic assertions,
// not separately executed Node test IDs. An early failure leaves later variants NOT_REACHED.
test('RGC01 real registered generation reads exact context then forwards null and existing head CAS', async () => {
  for (const head of [null, HEAD]) await scenario({ get: async () => response(context(head)) }, async ({ app, requests }) => {
    props(app).onGenerateReports(A); await settle();
    const calls = reportCalls(requests);
    assert.equal(calls[0]?.url, '/api/v1/sessions/' + A + '/report-context', 'GET context precedes publication');
    assert.equal(calls[0].options.method || 'GET', 'GET');
    assert.deepEqual(JSON.parse(calls[1]?.options.body || '{}'), {
      confirm: true, expected_report_head: head, expected_report_context_sha256: REPORT_SHA,
    });
    assert.notEqual(REPORT_SHA, CTX_A1, 'Report and metadata context fixtures deliberately differ');
    assert.match(calls[0].options.headers.Authorization, /^Bearer [a-f0-9]{64}$/);
    assert.equal(calls[1].options.method, 'POST');
    assert.equal(calls[1].options.headers.Authorization, calls[0].options.headers.Authorization);
  });
});

test('RGC02 malformed unavailable or wrong-session GET context never publishes', async () => {
  const valid = context(HEAD);
  const invalid = [
    ['null envelope', null], ['extra field', { ...valid, extra: true }],
    ['missing field', Object.fromEntries(Object.entries(valid).filter(([key]) => key !== 'head'))],
    ['wrong schema', { ...valid, schema: 'wrong' }], ['wrong session', { ...valid, session_id: B }],
    ['unavailable', { ...valid, status: 'UNAVAILABLE', report_context_sha256: null, head: null, reason: 'REPORT_CONTEXT_UNAVAILABLE' }],
    ['uppercase digest', { ...valid, report_context_sha256: 'A'.repeat(64) }],
    ['short digest', { ...valid, report_context_sha256: 'a'.repeat(63) }],
    ['non-string digest', { ...valid, report_context_sha256: 7 }],
    ['head extra field', { ...valid, head: { ...HEAD, extra: 1 } }],
    ['head missing hash', { ...valid, head: { generation: HEAD.generation } }],
    ['head traversal', { ...valid, head: { ...HEAD, generation: '../report-' + '8'.repeat(32) } }],
    ['head uppercase hash', { ...valid, head: { ...HEAD, manifest_sha256: 'B'.repeat(64) } }],
    ['non-null success reason', { ...valid, reason: 'not null' }],
  ];
  for (const [label, value] of invalid) await scenario({ get: async () => response(value) }, async ({ app, requests }) => {
    props(app).onGenerateReports(A); await settle();
    assert.equal(posts(requests).length, 0, label + ': no POST or demo fallback');
    assert.equal(notice(app)?.type, 'error', label + ': visible honest refusal');
  });
});

test('RGC03 stale supplied SID and missing current real metadata refuse before network', async () => {
  await scenario({}, async ({ app, requests }) => {
    const start = requests.length;
    props(app).onGenerateReports(B); await settle();
    assert.equal(requests.length, start, 'Supplied SID must match selected current session before network');
    assert.equal(notice(app)?.type, 'error');
  });
  await scenario({ list: [sessionRow(A)] }, async ({ app, requests }) => {
    const start = requests.length;
    props(app).onGenerateReports(A); await settle();
    assert.equal(requests.length, start, 'Unavailable real metadata cannot fall back to demo publication');
    assert.equal(notice(app)?.type, 'error');
  });
});

test('RGC04 selection epoch change while report GET is pending prevents POST and success', async () => {
  const pending = deferred();
  try { await scenario({ list: [sessionRow(A, CTX_A1), sessionRow(B, CTX_B)], get: () => pending.promise, cleanup: () => pending.resolve(response(context())) }, async ({ app, requests }) => {
    props(app).onGenerateReports(A); await settle();
    assert.equal(reportCalls(requests)[0]?.url, '/api/v1/sessions/' + A + '/report-context');
    props(app).onSelectSession(B); app.render();
    const before = requests.length; pending.resolve(response(context())); await settle();
    assert.equal(posts(requests).length, 0);
    assert.equal(requests.length, before, 'Stale GET must not refresh current or previous session');
    assert.notEqual(notice(app)?.text, 'TEST_ONLY publication accepted');
  }); } finally { pending.resolve(response(context())); }
});

test('RGC05 same SID metadata change while report GET is pending prevents POST', async () => {
  const pending = deferred();
  try { await scenario({ get: () => pending.promise, cleanup: () => pending.resolve(response(context())) }, async ({ app, requests, refreshMetadata }) => {
    props(app).onGenerateReports(A); await settle();
    assert.equal(reportCalls(requests)[0]?.url, '/api/v1/sessions/' + A + '/report-context');
    await refreshMetadata([sessionRow(A, CTX_A2)]);
    const before = requests.length; pending.resolve(response(context())); await settle();
    assert.equal(posts(requests).length, 0, 'Report GET digest is not a substitute for the original metadata epoch');
    assert.equal(requests.length, before, 'Stale metadata work cannot refresh');
    assert.notEqual(notice(app)?.text, 'TEST_ONLY publication accepted');
  }); } finally { pending.resolve(response(context())); }
});

test('RGC06 late publication cannot refresh or show success after metadata or selection change', async () => {
  for (const change of ['metadata', 'selection']) {
    const pending = deferred();
    try { await scenario({ list: [sessionRow(A, CTX_A1), sessionRow(B, CTX_B)], post: () => pending.promise, cleanup: () => pending.resolve(response({}, 201)) }, async ({ app, requests, refreshMetadata }) => {
      props(app).onGenerateReports(A); await settle();
      assert.deepEqual(JSON.parse(posts(requests)[0]?.options.body || '{}'), {
        confirm: true, expected_report_head: null, expected_report_context_sha256: REPORT_SHA,
      }, change + ': must first start a valid CAS publication');
      if (change === 'metadata') await refreshMetadata([sessionRow(A, CTX_A2), sessionRow(B, CTX_B)]);
      else { props(app).onSelectSession(B); app.render(); }
      const before = requests.length;
      pending.resolve(response({ message: 'TEST_ONLY publication accepted' }, 201)); await settle();
      assert.equal(requests.length, before, change + ': late response must not refresh');
      assert.notEqual(notice(app)?.text, 'TEST_ONLY publication accepted', change + ': no stale success');
    }); } finally { pending.resolve(response({}, 201)); }
  }
});

test('RGC07 network token and definitive conflict errors stay visible without retry or fallback', async () => {
  const cases = [
    { label: 'network', get: async () => { throw new Error('TEST_ONLY network offline'); }, expected: /network offline/, count: 0 },
    { label: 'token', get: async () => response({ error: 'TEST_ONLY token rejected' }, 401), expected: /token rejected/, count: 0 },
    { label: 'conflict', post: async () => response({ error: 'REPORT_CONTEXT_CHANGED: TEST_ONLY' }, 409), expected: /REPORT_CONTEXT_CHANGED/, count: 1 },
  ];
  for (const item of cases) await scenario(item, async ({ app, requests }) => {
    props(app).onGenerateReports(A); await settle();
    assert.equal(notice(app)?.type, 'error', item.label + ': honest error notice');
    assert.match(notice(app)?.text || '', item.expected);
    assert.equal(posts(requests).length, item.count, item.label + ': no automatic retry or bare-confirm fallback');
  });
});

test('RGC08 selected actual demo preserves bare confirmation without report context GET', async () => {
  await scenario({ list: [{ id: A, kind: 'demo', status: 'demo', captured_roles: [] }] }, async ({ app, requests }) => {
    props(app).onGenerateReports(A); await settle();
    const calls = reportCalls(requests);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/v1/sessions/' + A + '/reports/generate');
    assert.deepEqual(JSON.parse(calls[0].options.body), { confirm: true });
    assert.equal(notice(app)?.text, 'TEST_ONLY publication accepted');
  });
});