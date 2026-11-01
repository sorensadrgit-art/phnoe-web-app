// N01 frame-level diagnostic review: generated TEST_ONLY regressions.
// RED expectation before the N01 patch: assertion failures ("N01 MISSING ..."),
// never import/syntax errors. Only existing exports are imported by name.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {transformSync} from 'esbuild';
import * as sync from './syncPlayback.js';
import {validateMotion} from './motionData.js';

const h=c=>String(c).repeat(64); // generated digest placeholders only
const roles=['cam01_intrinsics','cam02_intrinsics','cam01_board','cam02_board','cam01_trial','cam02_trial'];
const REQUIRED=['Hip','RHip','RKnee','RAnkle','LHip','LKnee','LAnkle'];
const SCHEMA='kinelab.reconstruction-frames.v1';
const POLICY='kinelab.pipeline-quality.v4';
const CRITERIA={views:2,likelihood:[.3,1],reprojection_px_max:15,coverage_min:.95,longest_gap_frames_max:3};
const TRC={path:'pose-3d/TEST_ONLY.trc',sha256:h('7')};
const CALIBRATION={path:'calibration/TEST_ONLY.toml',sha256:h('c')};
const DIAG_SHA=h('5');
function api(name){
 assert.equal(typeof sync[name],'function','N01 MISSING: syncPlayback.'+name+' is not implemented');
 return sync[name];
}
function camera(status,likelihood=null,reprojection_px=null,camera_depth=null){return {status,likelihood,reprojection_px,camera_depth};}
const good=()=>({valid:true,views:2,cameras:{cam01:camera('supported',.9,2,2.1),cam02:camera('supported',.8,3.5,2.4)}});
function generatedDiagnostics(){
 const markers=()=>Object.fromEntries(REQUIRED.map(m=>[m,good()]));
 const frames=Array.from({length:50},(_,i)=>({synchronized_frame_index:i,rejected:false,markers:markers()}));
 frames[6].rejected=true;
 frames[6].markers.RKnee={valid:false,views:1,cameras:{cam01:camera('supported',.9,2,2.1),cam02:camera('no_pose_file')}};
 frames[7].rejected=true;
 frames[7].markers.RKnee={valid:false,views:1,cameras:{cam01:camera('behind_camera',.7,null,-0.4),cam02:camera('supported',.8,3,2.4)}};
 frames[8].rejected=true;
 frames[8].markers.LKnee={valid:false,views:2,cameras:{cam01:camera('supported',.2,2,2.1),cam02:camera('supported',.8,3,2.4)}};
 return {schema:SCHEMA,policy:POLICY,session_id:'TEST_ONLY-session',source_trc:{...TRC},calibration:{...CALIBRATION},
  camera_ids:['cam01','cam02'],required_markers:[...REQUIRED],classification:'native_triangulated_unfiltered',
  value_kind:'reconstruction estimate; research diagnostic; not measured physical truth',
  physical_accuracy:'not validated',clinical_validation:'UNVERIFIED',
  camera_depth_units:'calibration translation units; physical scale UNVERIFIED',
  frame_index_basis:'round(trc_time_s * trc_fps) = pose-associated file index; equality with decoded source video frame UNVERIFIED',
  criteria:structuredClone(CRITERIA),frames};
}
function fixture({withDiagnostics=true,binding={}}={}){
 const inputs=Object.fromEntries(roles.map((role,i)=>[role,h((i%9)+1)]));
 const cameras={cam01:{offset_frames:0,start_residual_frames:0,end_residual_frames:0},cam02:{offset_frames:-3,start_residual_frames:0,end_residual_frames:0}};
 const pairs=[{camera:'cam01',synchronized_frame_index:5,source_frame_index:5},{camera:'cam01',synchronized_frame_index:45,source_frame_index:45},
  {camera:'cam02',synchronized_frame_index:5,source_frame_index:2},{camera:'cam02',synchronized_frame_index:45,source_frame_index:42}];
 const artifacts={calibration:CALIBRATION,triangulation:TRC,filtering:{path:'pose-3d/TEST_ONLY_filt.trc',sha256:h('f')}};
 const names=['calibration','poseEstimation','synchronization','personAssociation','triangulation','filtering'];
 const run={schema:'kinelab.run.v1',session_id:'TEST_ONLY-session',inputs,config_sha256:h('b'),
  native_triangulation_policy:{interpolation:'none',fill_large_gaps_with:'nan'},
  stages:names.map(name=>({name,status:'passed',quality:{ok:true,policy:POLICY,reference:'cam01',cameras,native_correlation:.9,source_frame_pairs:pairs},
   artifacts:[{...(artifacts[name]??{path:'pose/TEST_ONLY.json',sha256:h('e')})}]}))};
 if(withDiagnostics)run.stages[4].quality.frame_diagnostics={path:'diagnostics/reconstruction-frames.'+DIAG_SHA+'.json',
  sha256:DIAG_SHA,schema:SCHEMA,source_trc:{...TRC},calibration:{...CALIBRATION},frames:50,...binding};
 const outputs={};
 for(const [i,cam] of ['cam01','cam02'].entries()){const count=i?50:60;
  outputs[cam+'_trial']={path:'videos/'+cam+'.mp4',sha256:h(i?'d':'c'),fps:'30/1',width:1280,height:720,frame_count:count,
   timestamps:Array.from({length:count},(_,j)=>j/30)};}
 const normalized={schema:'kinelab.normalization.v1',session_id:'TEST_ONLY-session',config_sha256:h('b'),inputs,outputs};
 const syncReport={schema:'kinelab.sync.v1',session_id:'TEST_ONLY-session',ok:true,reference:'cam01',native_correlation:.9,cameras,source_frame_pairs:pairs};
 const motion=validateMotion({schema:'kinelab.motion.v2',sessionId:'TEST_ONLY-session',kind:'real',units:'m',coordinateSystem:'opensim_y_up',fps:30,
  markers:['Hip'],bones:[],frames:Array.from({length:50},(_,i)=>({t:i/30,xyz:[[0,1,0]]})),time:{unit:'s',origin:'synchronized_trial_start'},
  provenance:{runManifestSha256:h('a'),trcSha256:h('f'),motSha256:null,calibrationSha256:h('c')},quality:{status:'passed',mode:'marker-only'},kinematics:null});
 const args=[motion,normalized,syncReport,run,{runHash:h('a'),videoHashes:{cam01:h('c'),cam02:h('d')}}];
 return {motion,run,args,evidence:withDiagnostics&&Object.keys(binding).length?null:sync.validateReviewEvidence(...args)};
}

test('verified review evidence carries the run-bound diagnostics binding and stage identities',()=>{
 const {evidence}=fixture();
 assert.ok('frameDiagnostics' in evidence,'N01 MISSING: validateReviewEvidence does not expose the triangulation frame_diagnostics binding');
 assert.deepEqual(evidence.frameDiagnostics,{path:'diagnostics/reconstruction-frames.'+DIAG_SHA+'.json',sha256:DIAG_SHA,schema:SCHEMA,
  source_trc:TRC,calibration:CALIBRATION,frames:50});
 assert.deepEqual(evidence.stageTrc,{triangulation:h('7'),filtering:h('f'),markerAugmentation:null});
 assert.equal(evidence.displayedTrcSha256,h('f'));
 assert.equal(fixture({withDiagnostics:false}).evidence.frameDiagnostics,null,'legacy run: NOT RECORDED, still reviewable');
});

test('a present but malformed or rebound diagnostics binding refuses the review',()=>{
 assert.ok('frameDiagnostics' in fixture().evidence,'N01 MISSING: validateReviewEvidence does not expose the frame_diagnostics binding');
 for(const [number,binding] of [
  {path:'diagnostics/reconstruction-frames.'+h('6')+'.json'},
  {path:'../reconstruction-frames.'+DIAG_SHA+'.json'},
  {sha256:'not-a-hash'},
  {schema:'kinelab.reconstruction-frames.v0'},
  {source_trc:{path:TRC.path,sha256:h('8')}},
  {calibration:{path:CALIBRATION.path,sha256:h('8')}},
  {frames:0},
  {frames:true},
 ].entries()){
  const {args}=fixture({binding});
  assert.throws(()=>sync.validateReviewEvidence(...args),'binding mutation '+number);
 }
});

test('local diagnostics file is size-capped, read once, and hashed and parsed from the same bytes',async()=>{
 const load=api('loadFrameDiagnosticsFile');
 assert.ok(Number.isInteger(sync.FRAME_DIAGNOSTICS_MAX_BYTES)&&sync.FRAME_DIAGNOSTICS_MAX_BYTES>0,'N01 MISSING: explicit byte cap');
 const body=new TextEncoder().encode('{"a":1}');
 let reads=0;
 const once={name:'reconstruction-frames.json',size:body.byteLength,
  arrayBuffer:async()=>(++reads===1?body:new TextEncoder().encode('{"a":2}')).slice().buffer};
 const loaded=await load(once);
 assert.equal(reads,1,'the file must be read once');
 assert.equal(loaded.sha256,await sync.sha256LocalFile(new Blob([body])));
 assert.deepEqual(loaded.document,{a:1});
 let oversizedRead=false;
 await assert.rejects(load({name:'x.json',size:sync.FRAME_DIAGNOSTICS_MAX_BYTES+1,arrayBuffer:async()=>{oversizedRead=true;return body.slice().buffer}}));
 assert.equal(oversizedRead,false,'oversized file must be refused before reading');
 for(const text of ['{"a":1,"a":2}','{"a":{"b":1,"b":1}}','{"a":1e999}','{"a":NaN}','not json']){
  const bytes=new TextEncoder().encode(text);
  await assert.rejects(load({name:'x.json',size:bytes.byteLength,arrayBuffer:async()=>bytes.slice().buffer}),text);
 }
 const invalid=new Uint8Array([0x7b,0xff,0x7d]);
 await assert.rejects(load({name:'x.json',size:3,arrayBuffer:async()=>invalid.slice().buffer}),'invalid UTF-8');
});

test('stored diagnostics are accepted only when bytes and content match the verified run binding',()=>{
 const validate=api('validateFrameDiagnostics');
 const {evidence}=fixture();
 const accepted=validate(evidence,generatedDiagnostics(),DIAG_SHA);
 assert.equal(accepted.available,true);
 assert.deepEqual(accepted.rejectedFrames,[6,7,8]);
 assert.equal(accepted.displayedClassification,'native_filtered_research_only');
 const m=(d,f,marker)=>d.frames[f].markers[marker];
 for(const [number,mutate] of [
  d=>({doc:d,sha:h('9')}),                                          // arbitrary uploaded JSON / different bytes
  d=>{d.session_id='other';},
  d=>{d.source_trc.sha256=h('8');},
  d=>{d.calibration.sha256=h('8');},
  d=>{d.policy='kinelab.pipeline-quality.v1';},
  d=>{d.policy='kinelab.pipeline-quality.v2';},
  d=>{d.policy='kinelab.pipeline-quality.v3';},
  d=>{d.schema='kinelab.reconstruction-frames.v0';},
  d=>{d.criteria.reprojection_px_max=20;},
  d=>{d.required_markers=d.required_markers.slice(1);},
  d=>{delete d.frames[3].markers.LAnkle;},
  d=>{d.camera_ids=['cam02','cam01'];},
  d=>{d.clinical_validation='VALIDATED';},
  d=>{d.frames[3].synchronized_frame_index=2;},
  d=>{d.frames[0].synchronized_frame_index=-1;},
  d=>{d.frames.pop();},
  d=>{m(d,6,'RKnee').cameras.cam03=camera('supported',.9,1,1);},
  d=>{m(d,6,'RKnee').cameras.cam02.status='interpolated';},
  d=>{m(d,0,'Hip').cameras.cam01.reprojection_px=Number.NaN;},
  d=>{m(d,0,'Hip').cameras.cam01.reprojection_px=-1;},
  d=>{m(d,0,'Hip').cameras.cam01.likelihood=1.2;},
  d=>{m(d,0,'Hip').cameras.cam01.camera_depth=0;},
  d=>{m(d,7,'RKnee').cameras.cam01.camera_depth=2;},          // behind_camera with positive depth
  d=>{m(d,6,'RKnee').cameras.cam02.likelihood=.5;},           // no_pose_file cannot carry a likelihood
  d=>{m(d,6,'RKnee').valid=true;},                            // contradicts views 1
  d=>{m(d,8,'LKnee').valid=true;},                            // contradicts likelihood .2 below 0.3
  d=>{m(d,0,'Hip').valid=false;d.frames[0].rejected=true;},   // contradicts predicate true
  d=>{m(d,0,'Hip').valid='true';},
  d=>{m(d,6,'RKnee').views=2;},
  d=>{d.frames[6].rejected=false;},
  d=>{d.frames[1].rejected=1;},
 ].entries()){
  const doc=generatedDiagnostics();
  const result=mutate(doc)??{doc,sha:DIAG_SHA};
  assert.throws(()=>validate(evidence,result.doc,result.sha),'mutation '+number);
 }
});

test('runs recorded before N01 report diagnostics NOT RECORDED instead of inventing them',()=>{
 const validate=api('validateFrameDiagnostics');
 const result=validate(fixture({withDiagnostics:false}).evidence,null,null);
 assert.equal(result.available,false);
 assert.match(result.reason,/NOT RECORDED/);
});

test('selected timeline frame uses the same synchronized index and signed offsets as video targets',()=>{
 const at=api('frameDiagnosticAt');
 const {evidence}=fixture();
 const diagnostics=api('validateFrameDiagnostics')(evidence,generatedDiagnostics(),DIAG_SHA);
 const selected=at(diagnostics,evidence,.2);
 assert.equal(selected.synchronizedFrame,6);
 assert.deepEqual(selected.sourceFrames,{cam01:6,cam02:3});
 assert.equal(selected.rejected,true);
 assert.deepEqual(selected.markers.RKnee.cameras.cam02,camera('no_pose_file'));
 const behind=at(diagnostics,evidence,7/30);
 assert.equal(behind.markers.RKnee.cameras.cam01.status,'behind_camera');
 assert.equal(behind.markers.RKnee.cameras.cam01.camera_depth,-0.4);
 assert.equal(at(diagnostics,evidence,60/30).record,null,'no stored diagnostic must not be presented as a passing frame');
 assert.equal(at({available:false,reason:'NOT RECORDED'},evidence,.2),null);
});

test('legend separates observed, filtered and model-derived estimates and makes no validation claim',()=>{
 const entries=api('frameDiagnosticLegend')();
 const text=JSON.stringify(entries);
 for(const label of ['native_triangulated_unfiltered','native_filtered_research_only','model_derived_LSTM_estimate_not_observed','missing','source_video'])
  assert.ok(entries.some(entry=>entry.id===label),label);
 for(const entry of entries)assert.match(entry.label,/not clinically validated|never filled|UNVERIFIED/);
 assert.match(text,/reconstruction estimate/i);
 assert.doesNotMatch(text,/(?<!not )(clinically validated|validated clinical|measured physical truth(?!"))/i);
});

// ---- Mounted VerifiedReview fixture (same generated hook harness as phaseFWorkflow.test.js) ----
const directory=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
function moduleAt(filename,overrides={}){
 const file=path.resolve(directory,filename),module={exports:{}};
 const source=transformSync(fs.readFileSync(file,'utf8'),{loader:'jsx',format:'cjs'}).code;
 new Function('require','module','exports',source)(name=>overrides[name]||
  (name.startsWith('.')?moduleAt(path.resolve(path.dirname(file),name),overrides):require(name)),module,module.exports);
 return module.exports;
}
function nodes(tree,predicate,out=[]){
 if(tree&&typeof tree==='object'){if(predicate(tree))out.push(tree);React.Children.forEach(tree.props?.children,child=>nodes(child,predicate,out));}
 return out;
}
function textOf(tree){
 if(typeof tree==='string'||typeof tree==='number')return String(tree);
 if(!tree||typeof tree!=='object')return '';
 return React.Children.toArray(tree.props?.children).map(textOf).join('');
}
function mounted(filename,props,overrides={}){
 // Synthetic hook driver, not a React DOM/StrictMode proof. Keep hook ownership
 // per function child so JSX component dispatch can preserve all existing cases.
 const instances=new Map();let active=null,pending=[],seen=new Set();
 const react={...React,
  useState(initial){const {slots}=active,i=active.index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;
   return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value}];},
  useRef(value){const {slots}=active,i=active.index++;if(!(i in slots))slots[i]={current:value};return slots[i];},
  useMemo(fn){active.index++;return fn();},
  useId(){const i=active.index++;return 'generated-'+i;},
  useEffect(fn,deps){const {effects}=active,i=active.index++,previous=effects[i];
   if(!previous||!deps||deps.some((value,n)=>!Object.is(value,previous.deps?.[n])))pending.push(()=>{previous?.cleanup?.();effects[i]={deps,cleanup:fn()};});}};
 const Component=moduleAt(filename,{'react':react,...overrides}).default;
 function cleanup(instance){for(const effect of instance.effects)effect?.cleanup?.();}
 function invoke(type,values,identity){
  let instance=instances.get(identity);
  if(instance&&instance.type!==type){const removed=instance;pending.push(()=>cleanup(removed));instances.delete(identity);instance=null;}
  if(!instance){instance={type,slots:[],effects:[],index:0};instances.set(identity,instance);}
  seen.add(identity);instance.index=0;const parent=active;active=instance;
  let result;try{result=type(values);}finally{active=parent;}
  return expand(result,identity);
 }
 function expand(tree,identity){
  if(Array.isArray(tree))return tree.map((child,i)=>expand(child,identity+'/'+i));
  if(!React.isValidElement(tree))return tree;
  const key=identity+'/'+String(tree.key??'child');
  if(typeof tree.type==='function')return invoke(tree.type,tree.props,key);
  return React.cloneElement(tree,{},React.Children.toArray(tree.props.children).map((child,i)=>expand(child,key+'/'+i)));
 }
 return {render(next=props){props=next;pending=[];seen=new Set();return invoke(Component,props,'root');},
  effects(){for(const [identity,instance] of instances)if(!seen.has(identity)){cleanup(instance);instances.delete(identity);}
   const current=pending;pending=[];for(const effect of current)effect();},
  unmount(){for(const instance of instances.values())cleanup(instance);instances.clear();}};
}
const SELECTOR='Select reconstruction frame diagnostics';
const BINDING={path:'diagnostics/reconstruction-frames.'+DIAG_SHA+'.json',sha256:DIAG_SHA,schema:SCHEMA,source_trc:TRC,calibration:CALIBRATION,frames:50};
const RECORD={synchronizedFrame:6,sourceFrames:{cam01:6,cam02:3},rejected:true,
 record:{synchronized_frame_index:6},markers:{RKnee:{valid:false,views:1,cameras:{cam01:camera('supported',.9,2,2.1),cam02:camera('no_pose_file')}}}};
async function verifiedReview(stubs={},extraProps={},binding=BINDING){
 const originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;let created=0,revoked=0;
 URL.createObjectURL=()=>'blob:generated-'+(++created);URL.revokeObjectURL=()=>{revoked++};
 const app=mounted('./VerifiedReview.jsx',{motion:{schema:'kinelab.motion.v2',kind:'real'},seconds:.2,playing:false,...extraProps},{'./syncPlayback.js':{
  sha256LocalFile:async()=>'generated-hash',
  validateReviewEvidence:()=>({sessionId:'TEST_ONLY-session',fps:30,nativeCorrelation:1,reference:'cam01',offsets:{cam01:0,cam02:0},
   frameDiagnostics:binding,stageTrc:{},displayedTrcSha256:h('f')}),
  videoFrameAtTime:()=>({cam01:null,cam02:null}),
  loadFrameDiagnosticsFile:async file=>({sha256:DIAG_SHA,document:{name:file.name}}),
  validateFrameDiagnostics:()=>({available:true,rejectedFrames:[6],displayedClassification:'native_filtered_research_only'}),
  frameDiagnosticAt:()=>RECORD,
  frameDiagnosticLegend:()=>[{id:'native_triangulated_unfiltered',label:'Observed native triangulation reconstruction estimate; not clinically validated'}],
  FRAME_DIAGNOSTICS_MAX_BYTES:1024,...stubs}});
 const view={app,counts:()=>({created,revoked}),restore(){URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke;}};
 view.verify=async()=>{
  let tree=app.render();app.effects();
  for(const input of nodes(tree,x=>x.type==='input'&&x.props['aria-label']!==SELECTOR))
   input.props.onChange({target:{files:[{name:input.props['aria-label'].replace('Select ',''),text:async()=>'{}'}],value:''}});
  app.render();app.effects();
  await nodes(app.render(),x=>x.type==='button'&&/Verify/.test(textOf(x)))[0].props.onClick();
  app.render();app.effects();
  return app.render();
 };
 view.selector=tree=>{
  const found=nodes(tree,x=>x.type==='input'&&x.props['aria-label']===SELECTOR)[0];
  assert.ok(found,'N01 MISSING: no frame diagnostics selector after verified review');
  return found;
 };
 view.upload=(tree,name)=>view.selector(tree).props.onChange({target:{files:[{name,size:2}],value:''}});
 view.tree=await view.verify();
 return view;
}

test('verified review offers a separate run-bound diagnostics selector, never part of video proof',async()=>{
 const view=await verifiedReview();
 try{
  view.selector(view.tree);
  assert.match(textOf(view.tree),/NATIVE SYNC RECORD PASSED/);
  assert.doesNotMatch(textOf(view.tree),/clinically validated measurement/i);
 }finally{view.app.unmount();view.restore();}
});

test('legacy run without a diagnostics binding shows NOT RECORDED and keeps its verified review',async()=>{
 const view=await verifiedReview({},{},null);
 try{
  assert.match(textOf(view.tree),/NOT RECORDED/,'N01 MISSING: legacy run does not disclose absent frame diagnostics');
  assert.equal(nodes(view.tree,x=>x.type==='input'&&x.props['aria-label']===SELECTOR).length,0);
  assert.match(textOf(view.tree),/NATIVE SYNC RECORD PASSED/);
 }finally{view.app.unmount();view.restore();}
});

test('a stale diagnostics read after unload is never validated',async()=>{
 let resolveRead;const pendingRead=new Promise(r=>{resolveRead=r});const validated=[];
 const view=await verifiedReview({loadFrameDiagnosticsFile:()=>pendingRead,
  validateFrameDiagnostics:(e,doc)=>{validated.push(doc);return {available:true,rejectedFrames:[6]}}});
 try{
  const loading=view.upload(view.tree,'reconstruction-frames.'+DIAG_SHA+'.json');
  nodes(view.app.render(),x=>x.type==='button'&&/Unload/.test(textOf(x)))[0].props.onClick();
  resolveRead({sha256:DIAG_SHA,document:{name:'stale'}});await loading;
  assert.deepEqual(validated,[],'stale diagnostics result was validated after unload');
  assert.doesNotMatch(textOf(view.app.render()),/Rejected frames/);
 }finally{view.app.unmount();view.restore();}
});

test('upload A then B in the same motion generation: only B can attach',async()=>{
 const reads={};const validated=[];
 const view=await verifiedReview({
  loadFrameDiagnosticsFile:file=>new Promise(resolve=>{reads[file.name]=resolve}),
  validateFrameDiagnostics:(e,doc)=>{validated.push(doc.name);return {available:true,rejectedFrames:doc.name==='B'?[7]:[6]}}});
 try{
  const a=view.upload(view.tree,'A');
  const b=view.upload(view.app.render(),'B');
  reads.B({sha256:DIAG_SHA,document:{name:'B'}});await b;
  reads.A({sha256:DIAG_SHA,document:{name:'A'}});await a;
  assert.deepEqual(validated,['B']);
  const tree=view.app.render();
  assert.ok(nodes(tree,x=>x.props?.['aria-label']==='Review rejected synchronized frame 7')[0]);
  assert.equal(nodes(tree,x=>x.props?.['aria-label']==='Review rejected synchronized frame 6').length,0);
 }finally{view.app.unmount();view.restore();}
});

test('refused diagnostics show an alert and no rejected-frame list',async()=>{
 const view=await verifiedReview({validateFrameDiagnostics:()=>{throw Error('Unverified synchronized review: generated refusal')}});
 try{
  await view.upload(view.tree,'reconstruction-frames.'+DIAG_SHA+'.json');
  const tree=view.app.render();
  assert.ok(nodes(tree,x=>x.props?.role==='alert'&&/generated refusal/.test(textOf(x)))[0]);
  assert.doesNotMatch(textOf(tree),/Rejected frames/);
 }finally{view.app.unmount();view.restore();}
});

test('selecting a stored rejected frame seeks the shared timeline with estimate/UNVERIFIED labels',async()=>{
 const seeks=[];
 const view=await verifiedReview({},{onSeek:time=>seeks.push(time)});
 try{
  await view.upload(view.tree,'reconstruction-frames.'+DIAG_SHA+'.json');
  const tree=view.app.render();view.app.effects();
  const button=nodes(tree,x=>x.type==='button'&&x.props['aria-label']==='Review rejected synchronized frame 6')[0];
  assert.ok(button,'N01 MISSING: stored rejected frame is not selectable');
  button.props.onClick();
  assert.deepEqual(seeks,[6/30]);
  const text=textOf(tree);
  assert.match(text,/Rejected frames/);
  assert.match(text,/reconstruction estimate/i);
  assert.match(text,/research diagnostic/i);
  assert.match(text,/camera depth units UNVERIFIED/i);
  assert.match(text,/decoded frame equality UNVERIFIED/i);
  assert.match(text,/missing \(not recorded\)/);
  assert.match(text,/not an independent sub-frame/);
  assert.doesNotMatch(text,/(?<!not )clinically validated/i);
 }finally{view.app.unmount();view.restore();}
});

test('source change clears diagnostics; re-verification starts without them and URL cleanup is intact',async()=>{
 const view=await verifiedReview();
 try{
  await view.upload(view.tree,'reconstruction-frames.'+DIAG_SHA+'.json');
  assert.match(textOf(view.app.render()),/Rejected frames/,'N01 MISSING: diagnostics did not attach');
  nodes(view.app.render(),x=>x.type==='button'&&/Unload/.test(textOf(x)))[0].props.onClick();
  const again=await view.verify();
  assert.doesNotMatch(textOf(again),/Rejected frames/);
  view.selector(again);
  assert.deepEqual(view.counts(),{created:4,revoked:2},'two verifications create two URL pairs; unload revokes the first pair');
 }finally{view.app.unmount();view.restore();}
});

// Generated TEST_ONLY fixtures; no saved evidence is relabeled.
test('B14-FRONTEND-01 v3 frame diagnostics accepted and unchanged v2 refused',()=>{
 const {evidence}=fixture(),current=generatedDiagnostics(),currentBefore=structuredClone(current);
 assert.equal(api('validateFrameDiagnostics')(evidence,current,DIAG_SHA).available,true);
 assert.deepEqual(current,currentBefore,'v4 validation preserves input');
 const legacy={...generatedDiagnostics(),policy:'kinelab.pipeline-quality.v2'},legacyBefore=structuredClone(legacy);
 assert.throws(()=>api('validateFrameDiagnostics')(evidence,legacy,DIAG_SHA),/identity, policy, criteria or labels/);
 assert.deepEqual(legacy,legacyBefore,'v2 refusal must not relabel legacy evidence');
});

