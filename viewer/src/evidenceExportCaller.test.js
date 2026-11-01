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
// Executes actual UnifiedApp request closures with its real API helper. This is
// a synthetic hook driver, not mounted DOM, browser, StrictMode or backend proof.
const SID='TEST_ONLY A', OP='1'.repeat(32), SHA=c=>c.repeat(64);
const HEAD={generation:'report-'+'2'.repeat(32),manifest_sha256:SHA('a')};
const CONTEXT={schema:'kinelab.report-generation-context.v1',session_id:SID,status:'AVAILABLE',report_context_sha256:SHA('b'),head:HEAD,reason:null};
const REQUEST={confirm:true,profile:'privacy-reduced',operation_id:OP,expected_report_head:HEAD,expected_report_context_sha256:SHA('b')};
const RECEIPT={schema:'kinelab.evidence-export-receipt.v1',session_id:SID,operation_id:OP,export_id:'evidence-'+'3'.repeat(32),profile:'privacy-reduced',report_head:HEAD,report_context_sha256:SHA('b'),manifest_sha256:SHA('d'),archive:{bytes:4,sha256:SHA('e')},audit:{event_id:'5'.repeat(32),event_hash:SHA('f')}};
const response=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
function counted(raw,{declared=null,status=200}={}){
  let offset=0,cancelled=0;
  const data=typeof raw==='string'?new TextEncoder().encode(raw):raw;
  const headers={'Content-Type':'application/json'};if(declared!==null)headers['Content-Length']=String(declared);
  const value=new Response(new ReadableStream({pull(controller){
    if(offset===data.length){controller.close();return;}
    const next=Math.min(offset+1024,data.length);controller.enqueue(data.slice(offset,next));offset=next;
  },cancel(){cancelled++;}}),{status,headers});
  return {value,read:()=>offset,cancelled:()=>cancelled};
}
async function actualCase(fetchEvidence,action){
  const storage=new Map([['kinelab_active_tab','reports'],['kinelab_selected_session',SID]]);
  const requests=[];let list=[currentDetail(SID)];
  await globals({window:{location:{hash:'#access='+'a'.repeat(64)},confirm:()=>true},
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value))},
    fetch:async(url,options)=>{
      requests.push({url,options});
      if(url==='/api/v1/sessions')return response({sessions:list});
      if(url==='/api/v1/analysis')return response({});
      return fetchEvidence(url,options);
    }},async()=>{
      const overrides=Object.fromEntries(['MotionApp','EvidencePassport','ReportStudio','LiveTrackerStudio','GuidedCaptureWizard','SessionMetadataSetup']
        .map(name=>{const component=()=>null;Object.defineProperty(component,'name',{value:name});return ['./'+name+'.jsx',{__esModule:true,default:component}];}));
      const app=mounted('./UnifiedApp.jsx',{}, {overrides});app.render();
      const boot=()=>{const effect=app.effects.find(item=>item?.fn.toString().includes('setLoading'));assert.ok(effect);return effect.fn();};
      const cleanups=[boot()];await tick();await tick();
      const props=()=>{const item=nodes(app.render(),n=>n.type?.name==='ReportStudio')[0];assert.ok(item,'Actual ReportStudio wiring exists');return item.props;};
      const identity=()=>moduleAt('./EvidenceExportPanel.jsx').evidenceMetadataIdentity(list[0],SID);
      const invoke=(kind,body=null,signal)=>{const caller=props().onEvidenceExportRequest;assert.equal(typeof caller,'function','Actual UnifiedApp export caller is required');return caller(SID,identity(),kind,body,{signal});};
      try{await action({app,props,invoke,requests,async changeSubject(){list=[currentDetail(SID,{},metadataState(SID,{context:CTX_A2}))];app.render();cleanups.push(boot());await tick();await tick();app.render();}});}
      finally{for(const cleanup of cleanups)cleanup?.();}
    });
}
test('R08-CALLER-00 actual auth encoded route exact context publication receipt artifact',async()=>{
  const zip=new Response(new Uint8Array([1,2,3,4]),{headers:{'Content-Type':'application/zip'}});
  await actualCase(async(url,options)=>url.endsWith('/report-context')?response(CONTEXT):url.endsWith('/artifact')?zip:response(RECEIPT),async({invoke,requests})=>{
    assert.deepEqual(await invoke('context'),CONTEXT);
    assert.deepEqual(await invoke('publish',REQUEST),RECEIPT);
    assert.deepEqual(await invoke('receipt',REQUEST),RECEIPT);
    assert.equal(await invoke('artifact',REQUEST),zip);
    const calls=requests.filter(item=>item.url.includes('/sessions/'));
    assert.deepEqual(calls.map(item=>item.url),['/api/v1/sessions/TEST_ONLY%20A/report-context','/api/v1/sessions/TEST_ONLY%20A/evidence-exports',`/api/v1/sessions/TEST_ONLY%20A/evidence-exports/${OP}`,`/api/v1/sessions/TEST_ONLY%20A/evidence-exports/${OP}/artifact`]);
    for(const {options}of calls){assert.equal(options.headers.Authorization,'Bearer '+'a'.repeat(64));assert.equal(options.cache,'no-store');}
    assert.equal(calls[1].options.method,'POST');assert.equal(calls[1].options.headers['Content-Type'],'application/json');assert.deepEqual(JSON.parse(calls[1].options.body),REQUEST);
  });
});
test('R08-CALLER-01 oversized declared and streaming context receipt are cancelled',async()=>{
  for(const kind of ['context','publish','receipt'])for(const declared of [null,65537]){
    const input=counted(' '.repeat(70000),{declared});
    await actualCase(async()=>input.value,async({invoke})=>{await assert.rejects(invoke(kind,kind==='context'?null:REQUEST),/limit|malformed/);assert.ok(input.cancelled()>0);assert.ok(input.read()<70000);});
  }
});
test('R08-CALLER-02 malformed nonfinite utf8 and length mismatch refuse',async()=>{
  for(const raw of ['{bad','{"archive":{"bytes":1e999}}',new Uint8Array([0xff])]){
    await actualCase(async()=>counted(raw).value,async({invoke})=>assert.rejects(invoke('context')));
  }
  await actualCase(async()=>counted(JSON.stringify(CONTEXT),{declared:1}).value,async({invoke})=>assert.rejects(invoke('context'),/length/));
});
test('R08-CALLER-03 strict context and receipt contradictions refuse at actual caller',async()=>{
  const invalid=[['context',{...CONTEXT,session_id:'TEST_ONLY-other'}],['context',{...CONTEXT,status:'UNAVAILABLE'}],
    ['receipt',{...RECEIPT,operation_id:'4'.repeat(32)}],['publish',{...RECEIPT,archive:{...RECEIPT.archive,bytes:0}}],
    ['receipt',{...RECEIPT,report_context_sha256:SHA('f')}]];
  for(const[kind,value]of invalid)await actualCase(async()=>response(value),async({invoke})=>assert.rejects(invoke(kind,kind==='context'?null:REQUEST),/unavailable|malformed|another request/i));
});
test('R08-CALLER-04 selected session and subject change reject old inflight data',async()=>{
  for(const change of ['session','subject']){
    let release,started;const began=new Promise(resolve=>{started=resolve;});const waiting=new Promise(resolve=>{release=resolve;});
    await actualCase(async()=>{started();return waiting;},async({invoke,props,changeSubject})=>{
      const work=invoke('context');await began;
      if(change==='session')props().onSelectSession('TEST_ONLY-other');else await changeSubject();
      release(response(CONTEXT));await assert.rejects(work,/changed|unconfirmed/);
    });
  }
});
test('R08-CALLER-05 abort cancels pending stream and rejects acceptance',async()=>{
  let cancelled=0;const value=new Response(new ReadableStream({cancel(){cancelled++;}}),{headers:{'Content-Type':'application/json'}});
  await actualCase(async()=>value,async({invoke})=>{const controller=new AbortController();const work=invoke('context',null,controller.signal);await tick();controller.abort();await assert.rejects(work,/cancel|changed/);assert.ok(cancelled>0);});
});
test('R08-CALLER-06 bounded API errors retain status message or honest generic fallback',async()=>{
  for(const raw of ['{"error":"TEST_ONLY controlled refusal"}','x'.repeat(20000),'{bad','{"error":1e999}']){
    const input=counted(raw,{status:409});
    await actualCase(async()=>input.value,async({invoke})=>{
      await assert.rejects(invoke('context'),error=>error.status===409&&error.message===(raw.includes('controlled refusal')?'TEST_ONLY controlled refusal':'Local service rejected this action (HTTP 409)'));
      if(raw.length>8192){assert.ok(input.cancelled()>0);assert.ok(input.read()<raw.length);}
    });
  }
});

test('R08-CALLER-07 actual epoch binding aborts retained artifact operation on batched A B A',async()=>{
 await actualCase(async(url)=>url.endsWith('/report-context')?response(CONTEXT):new Response(new ReadableStream({}),{headers:{'Content-Type':'application/zip'}}),async({props})=>{
  const controller=new AbortController(),operation={controller,current:null};
  const identity=moduleAt('./EvidenceExportPanel.jsx').evidenceMetadataIdentity(currentDetail(SID),SID);
  const caller=props().onEvidenceExportRequest;
  try{
   await caller(SID,identity,'context',null,{signal:controller.signal,operation});
   const artifact=await caller(SID,identity,'artifact',REQUEST,{signal:controller.signal,operation});
   props().onSelectSession('TEST_ONLY-other');props().onSelectSession(SID);
   assert.equal(controller.signal.aborted,true,'Actual selection setter must invalidate the owned artifact operation synchronously');
   assert.equal(typeof operation.current,'function');assert.equal(operation.current(),false);
   await artifact.body.cancel();
  }finally{controller.abort();}
 });
});
test('R08-CALLER-08 JSON stream cleanup preserves bound refusal despite cancellation rejection',async()=>{
 let cancelled=0;
 const value=new Response(new ReadableStream({start(controller){controller.enqueue(new Uint8Array(65537));},cancel(){cancelled++;throw Error('TEST_ONLY secondary cancellation failed');}}),{headers:{'Content-Type':'application/json'}});
 await actualCase(async()=>value,async({invoke})=>{
  await assert.rejects(invoke('context'),error=>/exceeds its byte limit/.test(error.message)&&!/secondary cancellation/.test(error.message));
  assert.ok(cancelled>0);
 });
});
test('R08-CALLER-09 no reader and unsafe declared lengths refuse without acceptance',async()=>{
 for(const mode of ['null-body','missing-reader','unsafe-length']){
  let cancelled=0;
  const value=mode==='null-body'?new Response(null,{headers:{'Content-Type':'application/json'}}):mode==='unsafe-length'?new Response('{}',{headers:{'Content-Type':'application/json','Content-Length':'9007199254740993'}}):{ok:true,headers:new Headers({'Content-Type':'application/json'}),body:{cancel(){cancelled++;throw Error('TEST_ONLY secondary cancellation failed');}}};
  await actualCase(async()=>value,async({invoke})=>{
   await assert.rejects(invoke('context'),/unavailable|malformed|limit/);
   if(mode==='missing-reader')assert.equal(cancelled,1);
  });
 }
});

// Public API receipts bind the publication audit event (evidence_export._records).
test('R08-CALLER-10 audited API receipt survives strict validation unchanged',()=>{
  const {checkedReceipt}=moduleAt('./EvidenceExportPanel.jsx');
  const before=JSON.stringify(RECEIPT);
  assert.equal(checkedReceipt(RECEIPT,SID,REQUEST),RECEIPT);
  assert.equal(JSON.stringify(RECEIPT),before);
  assert.deepEqual(Object.keys(RECEIPT.audit).sort(),['event_hash','event_id']);
});
test('R08-CALLER-11 missing malformed or extended audit receipt refuses at actual caller',async()=>{
  const missing={...RECEIPT};delete missing.audit;
  const invalid=[missing,...[null,[],{},
    {event_id:'5'.repeat(32)},
    {...RECEIPT.audit,event_id:5},
    {...RECEIPT.audit,event_id:'5'.repeat(31)},
    {...RECEIPT.audit,event_id:'A'.repeat(32)},
    {...RECEIPT.audit,event_hash:'F'.repeat(64)},
    {...RECEIPT.audit,event_hash:'f'.repeat(63)},
    {...RECEIPT.audit,event_hash:null},
    {...RECEIPT.audit,unexpected:true},
  ].map(audit=>({...RECEIPT,audit})),{...RECEIPT,unexpected:true}];
  for(const value of invalid)for(const kind of ['publish','receipt'])
    await actualCase(async()=>response(value),async({invoke})=>
      assert.rejects(invoke(kind,REQUEST),/malformed|another request/i));
});
