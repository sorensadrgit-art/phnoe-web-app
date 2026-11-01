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

async function unifiedCase({ tab, list, details = {}, manualGet, manualPost }, action) {
  const storage = new Map([['kinelab_active_tab', tab], ['kinelab_selected_session', 'TEST_ONLY-A'], ['kinelab_t6_token', 'a'.repeat(50)]]);
  const requests = [], state = { list, revision: null };
  const ok = body => ({ ok: true, status: 200, json: async () => body });
  await globals({
    window: { location: { hash: '#access=' + 'a'.repeat(64) }, confirm() { return true; } },
    localStorage: { getItem(key) { return storage.get(key) ?? null; }, setItem(key, value) { storage.set(key, String(value)); } },
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      const method = options.method || 'GET';
      const manual = url.match(/^\/api\/v1\/sessions\/([^/]+)\/(manual-assessment-context|manual-assessments)$/);
      if (manual && method === 'GET' && manual[2] === 'manual-assessment-context') return ok(await manualGet(decodeURIComponent(manual[1]), options));
      if (manual && method === 'POST' && manual[2] === 'manual-assessments') return ok(await manualPost(decodeURIComponent(manual[1]), JSON.parse(options.body)));
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
// Actual UnifiedApp caller with child/fetch doubles only. The copied hook driver
// is not React DOM/StrictMode/browser proof. No report-context route is invented:
// current HTTP generation lacks a safe report context/head CAS API (see receipt).
const A='TEST_ONLY-A', B='TEST_ONLY-B';
const manualContext = (sid=A, metadata=CTX_A1) => ({
  schema:'kinelab.manual-assessment-context.v1',status:'AVAILABLE',session_id:sid,
  context_sha256:'a'.repeat(64),metadata_context_sha256:metadata,
  origin_sha256:ORIGIN_SHA,run_sha256:'b'.repeat(64),test_only:true,clinical_accuracy_validated:false,
  input_sets:[{input_id:'1'.repeat(64),kind:'gait',source_role:'cam01_trial',source_sha256:'2'.repeat(64),
    frames:120,trajectory_sha256:'3'.repeat(64),candidates_sha256:'4'.repeat(64),image_size:[1280,720],assumptions:{screen_forward:'right'}}],
  assessments:[],unavailable_assessments:[],
});
const request = () => ({operation_id:'5'.repeat(32),context_sha256:'a'.repeat(64),metadata_context_sha256:CTX_A1,
  input_id:'1'.repeat(64),source_sha256:'2'.repeat(64),reviewer:'TEST_ONLY human declaration',
  annotation_origin:'human_observed_video_frames',labels:[{frame_index:50,side:'left',event_type:'initial_contact'}],
  tolerance_frames:3,confirm:true});
const publication = (sid, body) => ({schema:'kinelab.manual-assessment-entry-receipt.v1',session_id:sid,
  operation_id:body.operation_id,metadata_context_sha256:body.metadata_context_sha256,
  descriptor:{path:'exports/manual-entry-'+body.operation_id+'.manual-assessment.json',sha256:'6'.repeat(64)},
  test_only:true,clinical_accuracy_validated:false});
const library = () => [sessionRow(A,CTX_A1),sessionRow(B,CTX_B)];
const opts = extra => ({tab:'reports',list:library(),details:{[A]:currentDetail(A),[B]:currentDetail(B)},
  manualGet:async sid=>manualContext(sid,sid===A?CTX_A1:CTX_B),manualPost:async(sid,body)=>publication(sid,body),...extra});
function callback(app,name){const fn=placeholderProps(app,'ReportStudio')[name];
  assert.equal(typeof fn,'function','INTEGRATION MISSING: UnifiedApp must forward '+name);return fn;}
function pending(){let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};}

test('R06-CALLER-01 actual UnifiedApp forwards manual context GET and returns the unwrapped API object',async()=>{
  const expected=manualContext();
  await unifiedCase(opts({manualGet:async()=>expected}),async({app,requests,loadSelected})=>{
    await loadSelected();const result=await callback(app,'onLoadManualAssessmentContext')(A);
    assert.deepEqual(result,expected);
    const get=requests.filter(item=>item.url==='/api/v1/sessions/'+A+'/manual-assessment-context');
    assert.equal(get.length,1);assert.equal(get[0].options.method??'GET','GET');assert.equal(get[0].options.body,undefined);
    assert.ok(get[0].options.headers.Authorization.startsWith('Bearer '));
  });
});
test('R06-CALLER-02 actual UnifiedApp POST preserves exact ten-field CAS body and unwraps bound receipt',async()=>{
  const body=request();
  await unifiedCase(opts(),async({app,requests,loadSelected})=>{
    await loadSelected();const result=await callback(app,'onPublishManualAssessment')(A,body);
    assert.deepEqual(result,publication(A,body));
    const posts=requests.filter(item=>item.url==='/api/v1/sessions/'+A+'/manual-assessments'&&item.options.method==='POST');
    assert.equal(posts.length,1);assert.deepEqual(JSON.parse(posts[0].options.body),body);
    assert.equal(Object.keys(JSON.parse(posts[0].options.body)).length,10);
  });
});
test('R06-CALLER-03 manual callback identities survive an unrelated actual UnifiedApp rerender',async()=>{
  await unifiedCase(opts(),async({app,loadSelected})=>{
    await loadSelected();const load=callback(app,'onLoadManualAssessmentContext'),publish=callback(app,'onPublishManualAssessment');
    app.render();assert.equal(callback(app,'onLoadManualAssessmentContext'),load);
    assert.equal(callback(app,'onPublishManualAssessment'),publish);
    // An unrelated controlled search update must not restart a mounted manual form.
    const search=nodes(app.render(),n=>n.type==='input'&&typeof n.props?.onChange==='function'&&n.props?.placeholder?.includes('Search'))[0];
    if(search){search.props.onChange({target:{value:'TEST_ONLY unrelated filter'}});app.render();}
    assert.equal(callback(app,'onLoadManualAssessmentContext'),load);
    assert.equal(callback(app,'onPublishManualAssessment'),publish);
  });
});
test('R06-CALLER-04 stale selected SID and stale metadata body are refused before manual network requests',async()=>{
  await unifiedCase(opts(),async({app,requests,loadSelected,reloadSessions})=>{
    await loadSelected();const load=callback(app,'onLoadManualAssessmentContext'),publish=callback(app,'onPublishManualAssessment');
    const before=requests.length;
    await assert.rejects(()=>load(B),/session|stale|context|selected/i);
    await assert.rejects(()=>publish(B,request()),/session|stale|context|selected/i);
    assert.equal(requests.length,before,'Stale SID must not send a request');
    await reloadSessions([sessionRow(A,CTX_A2),sessionRow(B,CTX_B)]);
    const after=requests.length;
    await assert.rejects(()=>callback(app,'onPublishManualAssessment')(A,request()),/metadata|stale|context/i);
    assert.equal(requests.length,after,'A stale metadata envelope must not be silently rebound');
  });
});
test('R06-CALLER-05 late manual context and publication results cannot escape changed session or metadata epochs',async()=>{
  for(const operation of ['load','publish'])for(const change of ['session','metadata']){
    const held=pending();
    await unifiedCase(opts({manualGet:async()=>held.promise,manualPost:async()=>held.promise}),async({app,loadSelected,reloadSessions})=>{
      await loadSelected();const body=request();
      const result=operation==='load'?callback(app,'onLoadManualAssessmentContext')(A):callback(app,'onPublishManualAssessment')(A,body);
      // Attach the rejection assertion before changing the epoch, avoiding an unhandled rejection fixture fault.
      const rejected=assert.rejects(()=>result,/session|metadata|stale|context|changed|abort/i);
      if(change==='session'){placeholderProps(app,'ReportStudio').onSelectSession(B);app.render();}
      else await reloadSessions([sessionRow(A,CTX_A2),sessionRow(B,CTX_B)]);
      held.resolve(operation==='load'?manualContext():publication(A,body));
      await rejected;
    });
  }
});