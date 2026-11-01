import { test } from 'node:test';
import { webcrypto } from 'node:crypto';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { transformSync } from 'esbuild';

// Generated receipt trust-boundary regressions; actual UnifiedApp callback. The
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
    crypto: webcrypto,
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

// Only local fetch responses and child surfaces are doubled. Receipt validation,
// retry state, selection fences and notices come from the actual UnifiedApp.
const SID = 'TEST_ONLY-A';
const RECEIPT_SCHEMA = 'kinelab.session-metadata-revision-receipt.v1';
const posts = requests => requests.filter(item => item.options?.method === 'POST'
  && item.url === '/api/v1/sessions/' + SID + '/metadata-revisions');
const notice = app => app.slots.find(slot => slot && typeof slot.text === 'string' && slot.type);
const canonical = value => value !== null && typeof value === 'object'
  ? Array.isArray(value) ? value.map(canonical)
    : Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
async function contextDigest(body, descriptor, sessionId = SID) {
  const payload = { schema: 'kinelab.session-metadata-context.v1', session_id: sessionId,
    origin: { path: 'session.json', sha256: body.expected_origin_sha256 }, head: descriptor };
  const bytes = new TextEncoder().encode(JSON.stringify(canonical(payload)));
  return Buffer.from(await webcrypto.subtle.digest('SHA-256', bytes)).toString('hex');
}
async function receiptFor(body) {
  const revision = '6'.repeat(32);
  const descriptor = { path: `metadata-revisions/revision-${revision}/revision.json`, sha256: '8'.repeat(64) };
  return { schema: RECEIPT_SCHEMA, session_id: SID, operation_id: body.operation_id,
    revision_id: revision, descriptor, context_sha256: await contextDigest(body, descriptor) };
}
const resolveReceipt = (state, value) => state.revision({ ok: true, status: 200, json: async () => value });
const selectedProps = app => placeholderProps(app, 'GuidedCaptureWizard');
async function receiptCase(action) {
  await unifiedCase({ tab: 'capture', list: [sessionRow(SID, CTX_A1), sessionRow('TEST_ONLY-B', CTX_B)],
    details: { [SID]: firstRevisionDetail(SID) } }, async fixture => {
    await fixture.loadSelected();
    assert.equal(typeof selectedProps(fixture.app).onCorrectMetadata, 'function');
    await action(fixture);
  });
}
async function rejectedReceipt(label, change) {
  await receiptCase(async ({ app, requests, state }) => {
    const completion = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    assert.equal(posts(requests).length, 1, label + ': actual callback sent one request');
    const original = posts(requests)[0].options.body, body = JSON.parse(original);
    resolveReceipt(state, await change(await receiptFor(body), body));
    await completion; await tick();
    assert.equal(notice(app)?.type, 'error', label + ': unvalidated receipt cannot show success');
    assert.match(notice(app).text, /unconfirmed|unknown|inspect|receipt/i, label + ': honest outcome notice');
    const retry = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    const retryPost = posts(requests).at(-1);
    const retryBody = JSON.parse(retryPost.options.body);
    resolveReceipt(state, await receiptFor(retryBody));
    await retry; await tick();
    assert.equal(posts(requests).length, 2, label + ': deliberate retry sent exactly once');
    assert.equal(retryPost.options.body, original, label + ': exact ambiguous operation body must remain retryable');
  });
}

test('W24-RECEIPT-01 malformed and extra or missing fields never clear the ambiguous operation', async () => {
  const variants = [
    ['null', () => null], ['array', receipt => [receipt]], ['string', () => 'TEST_ONLY receipt'],
    ['missing field', receipt => { delete receipt.revision_id; return receipt; }],
    ['extra field', receipt => ({ ...receipt, status: 'published' })],
    ['descriptor extra field', receipt => ({ ...receipt, descriptor: { ...receipt.descriptor, bytes: 1 } })],
    ['descriptor missing digest', receipt => ({ ...receipt, descriptor: { path: receipt.descriptor.path } })],
  ];
  for (const [label, change] of variants) await rejectedReceipt(label, change);
});

test('W24-RECEIPT-02 exact schema session operation revision path and lowercase hashes are required', async () => {
  const variants = [
    ['wrong schema', receipt => ({ ...receipt, schema: 'kinelab.session-metadata-revision-receipt.v2' })],
    ['wrong session', receipt => ({ ...receipt, session_id: 'TEST_ONLY-B' })],
    ['wrong operation', receipt => ({ ...receipt, operation_id: 'f'.repeat(32) })],
    ['boolean operation', receipt => ({ ...receipt, operation_id: true })],
    ['uppercase revision', receipt => ({ ...receipt, revision_id: 'A'.repeat(32) })],
    ['short revision', receipt => ({ ...receipt, revision_id: '6'.repeat(31) })],
    ['boolean revision', receipt => ({ ...receipt, revision_id: true })],
    ['different revision path', receipt => ({ ...receipt, descriptor: { ...receipt.descriptor,
      path: 'metadata-revisions/revision-' + '7'.repeat(32) + '/revision.json' } })],
    ['traversal path', receipt => ({ ...receipt, descriptor: { ...receipt.descriptor, path: '../revision.json' } })],
    ['absolute path', receipt => ({ ...receipt, descriptor: { ...receipt.descriptor, path: 'C:/TEST_ONLY/revision.json' } })],
    ['uppercase digest', receipt => ({ ...receipt, descriptor: { ...receipt.descriptor, sha256: 'A'.repeat(64) } })],
    ['short digest', receipt => ({ ...receipt, descriptor: { ...receipt.descriptor, sha256: '8'.repeat(63) } })],
    ['boolean digest', receipt => ({ ...receipt, descriptor: { ...receipt.descriptor, sha256: true } })],
  ];
  for (const [label, change] of variants) await rejectedReceipt(label, change);
});

test('W24-RECEIPT-03 context digest must bind canonical session immutable origin and exact descriptor', async () => {
  const variants = [
    ['wrong context', receipt => ({ ...receipt, context_sha256: '0'.repeat(64) })],
    ['uppercase context', receipt => ({ ...receipt, context_sha256: receipt.context_sha256.toUpperCase() })],
    ['boolean context', receipt => ({ ...receipt, context_sha256: true })],
    ['other origin', async (receipt, body) => ({ ...receipt,
      context_sha256: await contextDigest({ ...body, expected_origin_sha256: 'b'.repeat(64) }, receipt.descriptor) })],
    ['other head', async (receipt, body) => ({ ...receipt,
      context_sha256: await contextDigest(body, { ...receipt.descriptor, sha256: '9'.repeat(64) }) })],
    ['other context session', async (receipt, body) => ({ ...receipt,
      context_sha256: await contextDigest(body, receipt.descriptor, 'TEST_ONLY-B') })],
  ];
  for (const [label, change] of variants) await rejectedReceipt(label, change);
});

test('W24-RECEIPT-04 canonical valid six-field receipt permits success and retires only that retry body', async () => {
  await receiptCase(async ({ app, requests, state }) => {
    const completion = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    const first = JSON.parse(posts(requests)[0].options.body), valid = await receiptFor(first);
    assert.deepEqual(Object.keys(valid).sort(),
      ['context_sha256', 'descriptor', 'operation_id', 'revision_id', 'schema', 'session_id']);
    assert.equal(valid.context_sha256, await contextDigest(first, valid.descriptor));
    resolveReceipt(state, valid);
    await completion; await tick();
    assert.equal(notice(app)?.type, 'info');
    assert.match(notice(app).text, /correction published/);
    const second = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    const next = JSON.parse(posts(requests).at(-1).options.body);
    resolveReceipt(state, await receiptFor(next));
    await second; await tick();
    assert.notEqual(next.operation_id, first.operation_id, 'Validated receipt retired only the completed attempt');
  });
});

test('W24-RECEIPT-05 a 5xx then malformed receipt keeps the exact ambiguous retry across both outcomes', async () => {
  await receiptCase(async ({ app, requests, state }) => {
    const first = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    const original = posts(requests)[0].options.body;
    state.revision({ ok: false, status: 503, json: async () => ({ error: 'TEST_ONLY ambiguous transport' }) });
    await first; await tick();
    assert.equal(notice(app)?.type, 'error');
    const second = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    assert.equal(posts(requests).at(-1).options.body, original, '5xx retains exact operation');
    const malformed = await receiptFor(JSON.parse(original)); malformed.operation_id = 'f'.repeat(32);
    resolveReceipt(state, malformed);
    await second; await tick();
    assert.equal(notice(app)?.type, 'error', 'Malformed 200 never confirms prior ambiguous publication');
    const third = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    const last = posts(requests).at(-1).options.body;
    resolveReceipt(state, await receiptFor(JSON.parse(last)));
    await third; await tick();
    assert.equal(last, original, 'Malformed response must not clear the original retry body');
  });
});

test('W24-RECEIPT-06 valid late session-A receipt cannot refresh or show success on session B', async () => {
  await receiptCase(async ({ app, requests, state, storage }) => {
    const completion = selectedProps(app).onCorrectMetadata(corrected());
    await tick();
    const body = JSON.parse(posts(requests)[0].options.body), valid = await receiptFor(body);
    const nav = nodes(app.render(), node => node.type === 'button' && node.key === 'sessions')[0];
    assert.ok(nav); nav.props.onClick();
    const row = nodes(app.render(), node => node.type === 'button' && node.key === 'TEST_ONLY-B')[0];
    assert.ok(row); row.props.onClick();
    const before = requests.length;
    resolveReceipt(state, valid);
    await completion; await tick(); await tick();
    assert.equal(storage.get('kinelab_selected_session'), 'TEST_ONLY-B');
    assert.deepEqual(requests.slice(before).filter(item => item.url.startsWith('/api/v1/sessions/' + SID)), []);
    assert.ok(!notice(app) || notice(app).type === 'error' || !notice(app).text.includes(SID));
  });
});
