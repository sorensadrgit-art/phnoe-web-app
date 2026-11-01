import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {transformSync} from 'esbuild';

// TEST_ONLY component/callback tests. The actual recorder panel and parent are
// compiled from source. Storage, timers and model hashing are controlled unit
// dependencies; these cases do not establish HTTP, browser or device behavior.
const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const Twin = () => null, HUD = () => null, Summary = () => null, PanelSlot = () => null;
const esm = value => ({__esModule: true, default: value});
const sameDeps = (left, right) => Array.isArray(left) && Array.isArray(right)
  && left.length === right.length && left.every((value, index) => Object.is(value, right[index]));

function moduleAt(filename, overrides, cache = new Map()) {
  const file = path.resolve(directory, filename);
  if (cache.has(file)) return cache.get(file).exports;
  const module = {exports: {}};
  cache.set(file, module);
  const baseline = process.env.KINELAB_N02_N03_RED_SNAPSHOT;
  const sourceFile = baseline && path.basename(file) === 'LiveTrackerStudio.jsx'
    ? path.join(baseline, 'viewer/src/LiveTrackerStudio.jsx') : file;
  const source = transformSync(fs.readFileSync(sourceFile, 'utf8'), {loader: 'jsx', format: 'cjs'}).code;
  new Function('require', 'module', 'exports', source)(name => Object.hasOwn(overrides, name)
    ? overrides[name] : name.startsWith('.')
      ? moduleAt(path.resolve(path.dirname(file), name), overrides, cache) : require(name), module, module.exports);
  return module.exports;
}

function mounted(filename, initialProps, overrides = {}) {
  const slots = [], effects = new Map();
  let index = 0, props = initialProps;
  const memo = (factory, deps) => {
    const position = index++, previous = slots[position];
    if (!previous || !sameDeps(previous.deps, deps)) slots[position] = {value: factory(), deps};
    return slots[position].value;
  };
  const react = {...React,
    useState(initial) {
      const position = index++;
      if (!(position in slots)) slots[position] = typeof initial === 'function' ? initial() : initial;
      return [slots[position], value => { slots[position] = typeof value === 'function' ? value(slots[position]) : value; }];
    },
    useRef(value) { const position = index++; if (!(position in slots)) slots[position] = {current: value}; return slots[position]; },
    useMemo: memo,
    useCallback: (callback, deps) => memo(() => callback, deps),
    useEffect(callback, deps) {
      const position = index++, previous = effects.get(position);
      if (!previous || !sameDeps(previous.deps, deps)) effects.set(position, {callback, deps, pending: true, cleanup: previous?.cleanup});
    },
  };
  const Component = moduleAt(filename, {react: {...esm(react), ...react}, ...overrides}).default;
  return {
    render(next = props) { props = next; index = 0; return Component(props); },
    effects() { for (const effect of effects.values()) if (effect.pending) { effect.cleanup?.(); effect.cleanup = effect.callback(); effect.pending = false; } },
    unmount() { for (const effect of effects.values()) effect.cleanup?.(); effects.clear(); },
  };
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
function button(app, label) {
  const found = nodes(app.render(), node => node.type === 'button'
    && (node.props['aria-label'] === label || textOf(node).trim() === label))[0];
  assert.ok(found, 'Actual component button exists: ' + label);
  return found;
}
function parent(visible = true) {
  const emissions = [];
  const app = mounted('LiveTrackerStudio.jsx', {token: 'TEST_ONLY', initialAvatarVisible: visible,
    onRecordingBusy: value => emissions.push(value)}, {
    './LiveDigitalTwin.jsx': esm(Twin), './LiveHUDOverlay.jsx': esm(HUD),
    './LiveSetSummaryModal.jsx': esm(Summary), './SyntheticRecordingPanel.jsx': esm(PanelSlot),
    './poseClient.js': {createPoseClient() { throw Error('Unexpected camera request'); }},
  });
  const feed = nodes(app.render(), node => node.type === 'button' && textOf(node).includes('Feed:'))[0];
  assert.ok(feed); feed.props.onClick();
  const panel = () => {
    const found = nodes(app.render(), node => node.type === PanelSlot)[0];
    assert.ok(found, 'Explicit synthetic selection exposes actual recording props');
    return found;
  };
  return {app, emissions, panel};
}
function assertYielded(app) {
  const tree = app.render();
  assert.equal(nodes(tree, node => node.type === Twin).length, 0, 'Optional avatar yields while recording is busy');
  assert.match(textOf(tree), /(?:paused|suspended).*recording|recording.*(?:paused|suspended)/i,
    'A visible status explains the recording-priority pause');
  assert.match(textOf(tree), /SYNTHETIC TEST ONLY/);
  assert.match(textOf(tree), /not measured movement/);
  assert.equal(nodes(tree, node => node.type === HUD).length, 1, 'The recording-priority change retains the HUD');
  assert.equal(nodes(tree, node => node.type === 'video').length, 1, 'The camera/preview element remains mounted');
}
function assertRestored(app, visible) {
  assert.equal(nodes(app.render(), node => node.type === Twin).length, visible ? 1 : 0);
  const toggle = button(app, 'Toggle 3D Digital Twin avatar');
  assert.equal(toggle.props['aria-pressed'], visible ? 'true' : 'false');
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}

async function environment(action) {
  const originals = new Map(), timers = new Set(), listeners = new Set();
  let timerId = 0;
  const target = name => ({hidden: false,
    addEventListener(event, callback) { listeners.add({name, event, callback}); },
    removeEventListener(event, callback) { for (const value of listeners) if (value.name === name && value.event === event && value.callback === callback) listeners.delete(value); },
  });
  const values = {
    document: target('document'), window: target('window'),
    setInterval: () => {const id = ++timerId; timers.add(id); return id;},
    clearInterval: id => timers.delete(id),
    setTimeout: () => {const id = ++timerId; timers.add(id); return id;},
    clearTimeout: id => timers.delete(id),
    fetch: async () => ({ok: true, json: async () => ({recordings: []})}),
    crypto: {randomUUID: () => '00000000-0000-4000-8000-000000000001'},
  };
  for (const [name, value] of Object.entries(values)) {
    originals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, {configurable: true, writable: true, value});
  }
  try { await action({timers, listeners}); }
  finally { for (const [name, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];
  } }
}

function actualPanel(parentApp, options = {}) {
  const clients = [];
  class ControlledClient {
    constructor({onChange}) {
      this.onChange = onChange; this.created = false; this.accepting = false;
      this.failed = false; this.finalized = false; this.produced = 1; this.saved = 1; this.pending = 0;
      clients.push(this); this.notify();
    }
    snapshot() { return {created: this.created, accepting: this.accepting, failed: this.failed,
      finalized: this.finalized, producedThrough: this.produced, savedThrough: this.saved,
      pendingFrames: this.pending, sessionId: 'TEST_ONLY-session', message: 'TEST_ONLY controlled storage'}; }
    notify() { this.onChange(this.snapshot()); }
    async start() {
      try { await options.start?.(); this.created = true; this.accepting = true; this.notify(); }
      catch (error) { this.failed = true; this.notify(); throw error; }
    }
    async retry() { this.failed = false; this.created = true; this.accepting = true; this.notify(); }
    async finish() {
      try { await options.finish?.(); this.accepting = false; this.finalized = true; this.notify(); }
      catch (error) { this.failed = true; this.notify(); throw error; }
    }
    close() { this.accepting = false; }
  }
  const app = mounted('SyntheticRecordingPanel.jsx', parentApp.panel().props, {
    './recordingClient.js': {RecordingClient: ControlledClient, RECORDING_LIMITS: {durationMs: 1800000},
      sha256Text: options.hash ?? (async () => 'a'.repeat(64))},
    './syntheticPose.js?raw': esm('TEST_ONLY controlled model source'),
  });
  return {app, clients};
}

test('N03-REC-001 recording priority yields at the actual busy-before-model-hash callback', async () => environment(async () => {
  const host = parent(), hash = deferred(), panel = actualPanel(host, {hash: () => hash.promise});
  const start = button(panel.app, 'Record synthetic test').props.onClick();
  try {
    assert.deepEqual(host.emissions, [true]);
    assert.equal(panel.clients.length, 0, 'The recorder has not created storage while model hashing is pending');
    assertYielded(host.app);
    const stable = host.panel().props.onBusy;
    assert.strictEqual(host.panel().props.onBusy, stable, 'Unchanged callback dependencies retain identity');
  } finally { hash.resolve('a'.repeat(64)); await start; panel.app.unmount(); }
}));

test('N03-REC-002 recording priority disables keyboard toggle and guards direct toggle callbacks', () => {
  const host = parent();
  host.panel().props.onBusy(true);
  const toggle = button(host.app, 'Toggle 3D Digital Twin avatar');
  assert.equal(toggle.props.disabled, true);
  assert.equal(toggle.props['aria-pressed'], 'false');
  assertYielded(host.app);
  toggle.props.onClick();
  assertYielded(host.app);
  host.panel().props.onBusy(false);
  assertRestored(host.app, true);
});

test('N03-REC-003 recording priority preserves the collapsed user preference across repeated busy signals', () => {
  const host = parent(false);
  host.panel().props.onBusy(true); host.panel().props.onBusy(true);
  assert.equal(button(host.app, 'Toggle 3D Digital Twin avatar').props.disabled, true);
  assertRestored(host.app, false);
  host.panel().props.onBusy(false);
  assertRestored(host.app, false);
  assert.deepEqual(host.emissions, [true, true, false]);
});

test('N03-REC-004 recording priority retains yield after actual storage-start failure and retry', async () => environment(async () => {
  const host = parent(), panel = actualPanel(host, {start: async () => {throw Error('TEST_ONLY storage unavailable');}});
  await button(panel.app, 'Record synthetic test').props.onClick();
  assert.deepEqual(host.emissions, [true]);
  assert.match(textOf(panel.app.render()), /TEST_ONLY storage unavailable/);
  assertYielded(host.app);
  await button(panel.app, 'Retry pending save').props.onClick();
  assert.deepEqual(host.emissions, [true]);
  assertYielded(host.app);
}));

test('N03-REC-005 actual pre-client hash failure releases busy and restores the user preference', async () => environment(async () => {
  const host = parent(), panel = actualPanel(host, {hash: async () => {throw Error('TEST_ONLY hash unavailable');}});
  await button(panel.app, 'Record synthetic test').props.onClick();
  assert.equal(panel.clients.length, 0);
  assert.deepEqual(host.emissions, [true, false]);
  assert.match(textOf(panel.app.render()), /TEST_ONLY hash unavailable/);
  assertRestored(host.app, true);
}));

test('N03-REC-006 recording priority persists through pending finalize and releases only after actual success', async () => environment(async () => {
  const host = parent(), finish = deferred(), panel = actualPanel(host, {finish: () => finish.promise});
  await button(panel.app, 'Record synthetic test').props.onClick();
  const finishing = button(panel.app, 'Finalize synthetic recording').props.onClick();
  try { assert.deepEqual(host.emissions, [true]); assertYielded(host.app); }
  finally { finish.resolve(); await finishing; }
  assert.deepEqual(host.emissions, [true, false]); assertRestored(host.app, true);
}));

test('N03-REC-007 recording priority retains yield on actual finalize failure', async () => environment(async () => {
  const host = parent(), panel = actualPanel(host, {finish: async () => {throw Error('TEST_ONLY finalize unavailable');}});
  await button(panel.app, 'Record synthetic test').props.onClick();
  await button(panel.app, 'Finalize synthetic recording').props.onClick();
  assert.deepEqual(host.emissions, [true]); assert.match(textOf(panel.app.render()), /TEST_ONLY finalize unavailable/);
  assertYielded(host.app);
}));

test('N03-REC-008 actual leave-draft guard retains busy for an unsaved tail then releases a saved draft', async () => environment(async () => {
  const host = parent(), panel = actualPanel(host);
  await button(panel.app, 'Record synthetic test').props.onClick();
  const client = panel.clients[0]; client.accepting = false; client.notify();
  const leave = button(panel.app, 'Leave saved draft').props.onClick;
  client.pending = 1; client.notify(); await leave();
  assert.deepEqual(host.emissions, [true]); assertYielded(host.app);
  client.pending = 0; client.notify(); await leave();
  assert.deepEqual(host.emissions, [true, false]); assertRestored(host.app, true);
}));

test('N03-REC-009 actual recorder cleanup clears owned timers/listeners and releases busy once', async () => environment(async ({timers, listeners}) => {
  const host = parent(), panel = actualPanel(host);
  panel.app.render(); panel.app.effects();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await button(panel.app, 'Record synthetic test').props.onClick();
  assert.equal(timers.size, 2); assert.equal(listeners.size, 2);
  assertYielded(host.app);
  panel.app.unmount();
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
  assert.deepEqual(host.emissions, [true, false]); assertRestored(host.app, true);
}));

test('R17 actual live Stop activity stays enabled while recording busy and latches before storage callback',()=>{
 const host=parent();let stops=0;
 const props=host.panel().props;
 assert.ok(props.stopSignal&&props.stopRecordingRef,'Actual parent exposes its stop boundary to the recorder');
 props.stopRecordingRef.current=()=>{assert.equal(props.stopSignal.current,true);stops++;};
 props.onBusy(true);
 assert.equal(button(host.app,'Pause tracking').props.disabled,true);
 const stop=button(host.app,'Stop activity');assert.notEqual(stop.props.disabled,true);
 stop.props.onClick();assert.equal(stops,1);assert.equal(props.stopSignal.current,true);
 assert.equal(host.app.render().props['data-activity-stopped'],true);
 assert.equal(button(host.app,'Resume tracking').props.disabled,true);
 button(host.app,'Resume tracking').props.onClick();
 assert.equal(button(host.app,'Resume tracking').props.disabled,true,'A direct stale resume callback cannot restart');
 props.onBusy(false);assert.equal(button(host.app,'Resume tracking').props.disabled,true);
 assert.match(textOf(host.app.render()),/clinical next-step approval is PENDING/);
 host.app.unmount();
});

test('R17 stop during model hashing prevents later recording creation in the actual panel callback',async()=>environment(async()=>{
 const host=parent(),hash=deferred(),panel=actualPanel(host,{hash:()=>hash.promise});
 panel.app.render();panel.app.effects();
 const starting=button(panel.app,'Record synthetic test').props.onClick();
 try{
  button(host.app,'Stop activity').props.onClick();assert.equal(panel.clients.length,0);
  hash.resolve('a'.repeat(64));await starting;
  assert.equal(panel.clients.length,0,'Late hash must not create a stopped recording');
  assert.equal(button(panel.app,'Record synthetic test').props.disabled,true);
  assert.equal(host.emissions.at(-1),false);
 }finally{hash.resolve('a'.repeat(64));await starting;panel.app.unmount();}
}));
