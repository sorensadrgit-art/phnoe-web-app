// N01 rejected triangulation review: generated TEST_ONLY regressions (refinement 2026-10-29).
// RED expectation before the slice: assertion failures ("N01-RR MISSING ..."),
// never import/syntax errors. Tests named *compat pass before and after.
// Browser trust: only bytes the browser actually hashed are BYTES_MATCHED; every other
// bound record stays NOT_OBSERVED. Physical accuracy and decoded-frame equality stay UNVERIFIED.
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
const REQUIRED=['Hip','RHip','RKnee','RAnkle','LHip','LKnee','LAnkle'];
const SCHEMA='kinelab.reconstruction-frames.v1';
const POLICY='kinelab.pipeline-quality.v4';
const CRITERIA={views:2,likelihood:[.3,1],reprojection_px_max:15,coverage_min:.95,longest_gap_frames_max:3};
const TRC={path:'pose-3d/TEST_ONLY.trc',sha256:h('7')};
const CALIBRATION={path:'calibration/TEST_ONLY.toml',sha256:h('c')};
const DIAG_SHA=h('5'),QUALITY_SHA=h('9'),PREFLIGHT_SHA=h('a'),NORMALIZATION_SHA=h('d'),SESSION='TEST_ONLY-rr-session';
const REASON='RECONSTRUCTION_REJECTED: TEST_ONLY generated coverage below criteria';
const LABEL='REJECTED / NOT USABLE FOR MEASUREMENT';
const NOT_OBSERVED=['config','preflight','normalization','normalized_outputs','calibration','source_trc'];
const directory=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);

function api(name){
 assert.equal(typeof sync[name],'function','N01-RR MISSING: syncPlayback.'+name+' is not implemented');
 return sync[name];
}
function camera(status,likelihood=null,reprojection_px=null,camera_depth=null){return {status,likelihood,reprojection_px,camera_depth};}
const good=()=>({valid:true,views:2,cameras:{cam01:camera('supported',.9,2,2.1),cam02:camera('supported',.8,3.5,2.4)}});
function diagnostics(session=SESSION){
 const markers=()=>Object.fromEntries(REQUIRED.map(m=>[m,good()]));
 const frames=Array.from({length:50},(_,i)=>({synchronized_frame_index:i,rejected:false,markers:markers()}));
 frames[6].rejected=true;
 frames[6].markers.RKnee={valid:false,views:1,cameras:{cam01:camera('supported',.9,2,2.1),cam02:camera('no_pose_file')}};
 frames[7].rejected=true;
 frames[7].markers.RKnee={valid:false,views:1,cameras:{cam01:camera('behind_camera',.7,null,-0.4),cam02:camera('supported',.8,3,2.4)}};
 frames[8].rejected=true;
 frames[8].markers.LKnee={valid:false,views:2,cameras:{cam01:camera('supported',.2,2,2.1),cam02:camera('supported',.8,3,2.4)}};
 return {schema:SCHEMA,policy:POLICY,session_id:session,source_trc:{...TRC},calibration:{...CALIBRATION},
  camera_ids:['cam01','cam02'],required_markers:[...REQUIRED],classification:'native_triangulated_unfiltered',
  value_kind:'reconstruction estimate; research diagnostic; not measured physical truth',
  physical_accuracy:'not validated',clinical_validation:'UNVERIFIED',
  camera_depth_units:'calibration translation units; physical scale UNVERIFIED',
  frame_index_basis:'round(trc_time_s * trc_fps) = pose-associated file index; equality with decoded source video frame UNVERIFIED',
  criteria:structuredClone(CRITERIA),frames};
}
const binding=()=>({path:'diagnostics/reconstruction-frames.'+DIAG_SHA+'.json',sha256:DIAG_SHA,schema:SCHEMA,
 source_trc:{...TRC},calibration:{...CALIBRATION},frames:50});
function fixture(){
 const names=['calibration','poseEstimation','synchronization','personAssociation','triangulation','filtering','markerAugmentation','kinematics'];
 const run={schema:'kinelab.run.v1',coordinateSystem:'opensim_y_up',quality_policy:POLICY,session_id:SESSION,inputs:{},config_sha256:h('b'),
  native_triangulation_policy:{interpolation:'none',fill_large_gaps_with:'nan'},
  stages:names.map((name,i)=>i<4?{name,status:'passed',artifacts:[{...(i?{path:'pose/TEST_ONLY.json',sha256:h('e')}:CALIBRATION)}],quality:{ok:true,policy:POLICY}}
   :{name,status:'not-run',artifacts:[]})};
 run.stages[4]={name:'triangulation',status:'failed',artifacts:[],error:'ValueError: QUALITY_REJECTED: triangulation: '+REASON,
  rejected_evidence:{schema:'kinelab.rejected-triangulation.v1',session_id:SESSION,quality:{path:'quality.json',sha256:QUALITY_SHA},
   frame_diagnostics:binding(),source_trc:{...TRC},calibration:{...CALIBRATION},
   bound_inputs:{preflight:{path:'preflight.json',sha256:PREFLIGHT_SHA},normalization:{path:'normalization.json',sha256:NORMALIZATION_SHA}},
   reasons:[REASON],usable_for_measurement:false}};
 const quality={schema:'kinelab.quality.v1',policy:POLICY,session_id:SESSION,ok:false,errors:[REASON],frame_diagnostics:binding()};
 return {run,quality,qualitySha256:QUALITY_SHA,diagnostics:diagnostics(),diagnosticsSha256:DIAG_SHA,sessionId:SESSION,observed:{}};
}
// Harness prerequisite only: VerifiedReview reads motion.schema on every render. This generated
// real-contract motion never makes the failed run measured evidence; it is one stable object so
// the component's [motion] reset effect does not fire on rerender.
const MOTION=validateMotion({schema:'kinelab.motion.v2',sessionId:SESSION,kind:'real',units:'m',coordinateSystem:'opensim_y_up',fps:30,
 markers:['Hip'],bones:[],frames:Array.from({length:50},(_,i)=>({t:i/30,xyz:[[0,1,0]]})),time:{unit:'s',origin:'synchronized_trial_start'},
 provenance:{runManifestSha256:h('a'),trcSha256:h('f'),motSha256:null,calibrationSha256:h('c')},quality:{status:'passed',mode:'marker-only'},kinematics:null});
const rejectedProps=(seconds=.2,playing=false)=>({mode:'rejected',motion:MOTION,seconds,playing,onSeek(){}});
// Otherwise-valid passed-review inputs following frameDiagnostics.test.js; generated only.
function passedReview(){
 const roles=['cam01_intrinsics','cam02_intrinsics','cam01_board','cam02_board','cam01_trial','cam02_trial'];
 const inputs=Object.fromEntries(roles.map((role,i)=>[role,h((i%9)+1)]));
 const cameras={cam01:{offset_frames:0,start_residual_frames:0,end_residual_frames:0},cam02:{offset_frames:-3,start_residual_frames:0,end_residual_frames:0}};
 const pairs=[{camera:'cam01',synchronized_frame_index:5,source_frame_index:5},{camera:'cam01',synchronized_frame_index:45,source_frame_index:45},
  {camera:'cam02',synchronized_frame_index:5,source_frame_index:2},{camera:'cam02',synchronized_frame_index:45,source_frame_index:42}];
 const artifacts={calibration:CALIBRATION,triangulation:TRC,filtering:{path:'pose-3d/TEST_ONLY_filt.trc',sha256:h('f')}};
 const names=['calibration','poseEstimation','synchronization','personAssociation','triangulation','filtering'];
 const run={schema:'kinelab.run.v1',session_id:SESSION,inputs,config_sha256:h('b'),
  native_triangulation_policy:{interpolation:'none',fill_large_gaps_with:'nan'},
  stages:names.map(name=>({name,status:'passed',quality:{ok:true,policy:POLICY,reference:'cam01',cameras,native_correlation:.9,source_frame_pairs:pairs},
   artifacts:[{...(artifacts[name]??{path:'pose/TEST_ONLY.json',sha256:h('e')})}]}))};
 const outputs={};
 for(const [i,cam] of ['cam01','cam02'].entries()){const count=i?50:60;
  outputs[cam+'_trial']={path:'videos/'+cam+'.mp4',sha256:h(i?'d':'c'),fps:'30/1',width:1280,height:720,frame_count:count,
   timestamps:Array.from({length:count},(_,j)=>j/30)};}
 const normalized={schema:'kinelab.normalization.v1',session_id:SESSION,config_sha256:h('b'),inputs,outputs};
 const syncReport={schema:'kinelab.sync.v1',session_id:SESSION,ok:true,reference:'cam01',native_correlation:.9,cameras,source_frame_pairs:pairs};
 const checks={runHash:h('a'),videoHashes:{cam01:h('c'),cam02:h('d')}};
 return {run,args:value=>[MOTION,normalized,syncReport,value,checks]};
}
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
// Same hook-driving harness as frameDiagnostics.test.js: the real component, real effects and cleanups.
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
const RECORD={synchronizedFrame:6,sourceFrames:{cam01:6,cam02:3},rejected:true,record:{synchronized_frame_index:6},
 markers:{RKnee:{valid:false,views:1,cameras:{cam01:camera('supported',.9,2,2.1),cam02:camera('no_pose_file')}}}};
function validatedResult(extra={}){
 return {status:'REJECTED',label:LABEL,usableForMeasurement:false,reasons:[REASON],sessionId:SESSION,
  diagnostics:{available:true,rejectedFrames:[6,7,8],byIndex:new Map(),criteria:structuredClone(CRITERIA)},
  verification:{quality:'BYTES_MATCHED',frame_diagnostics:'BYTES_MATCHED',...Object.fromEntries(NOT_OBSERVED.map(k=>[k,'NOT_OBSERVED'])),
   physical_accuracy:'UNVERIFIED',decoded_frame_equality:'UNVERIFIED'},normalizedOutputs:null,...extra};
}
function rejectedReview(stubs={}){
 const originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;
 const allocations=[],revocations=[];
 URL.createObjectURL=file=>{const url='blob:generated-'+(allocations.length+1);allocations.push({file,url});return url;};
 URL.revokeObjectURL=url=>{revocations.push(url);};
 const app=mounted('./VerifiedReview.jsx',rejectedProps(),{'./syncPlayback.js':{
  sha256LocalFile:async file=>file.sha256??'generated-hash',
  validateReviewEvidence:()=>{throw new Error('TEST_ONLY: passed-run validator must not accept rejected evidence');},
  validateRejectedRunEvidence:()=>validatedResult(),
  videoFrameAtTime:()=>({cam01:null,cam02:null}),
  loadFrameDiagnosticsFile:async file=>({sha256:DIAG_SHA,document:{name:file.name}}),
  validateFrameDiagnostics:()=>({available:true,rejectedFrames:[6],displayedClassification:'native_triangulated_unfiltered'}),
  frameDiagnosticAt:()=>RECORD,
  frameDiagnosticLegend:()=>[{id:'native_triangulated_unfiltered',label:'Observed native triangulation reconstruction estimate; not clinically validated'}],
  FRAME_DIAGNOSTICS_MAX_BYTES:1024,...stubs}});
 const view={app,allocations,revocations,restore(){URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke;}};
 view.select=(pattern,file)=>{
  app.render();app.effects();
  const input=nodes(app.render(),x=>x.type==='input'&&pattern.test(String(x.props['aria-label']||'')))[0];
  assert.ok(input,'N01-RR MISSING: rejected review has no local selector matching '+pattern);
  input.props.onChange({target:{files:[file],value:''}});
  app.render();app.effects();
 };
 view.selectEvidence=()=>{
  view.select(/rejected run\.json/i,{name:'run.json',size:2,text:async()=>'{}'});
  view.select(/rejected quality\.json/i,{name:'quality.json',size:2,text:async()=>'{}'});
  view.select(/rejected frame diagnostics/i,{name:'reconstruction-frames.json',size:2,text:async()=>'{}'});
 };
 view.verifyButton=()=>{
  const button=nodes(app.render(),x=>x.type==='button'&&/Verify rejected evidence/i.test(textOf(x)))[0];
  assert.ok(button,'N01-RR MISSING: rejected review has no local verify action');
  return button;
 };
 view.settle=()=>{app.render();app.effects();return app.render();};
 return view;
}

test('N01-RR exact rejected evidence validates read-only with its stored reasons',()=>{
 const result=api('validateRejectedRunEvidence')(fixture());
 assert.equal(result.status,'REJECTED');
 assert.equal(result.label,LABEL);
 assert.equal(result.usableForMeasurement,false);
 assert.deepEqual(result.reasons,[REASON]);
 assert.equal(result.diagnostics.available,true);
 assert.deepEqual(result.diagnostics.rejectedFrames,[6,7,8]);
});

test('N01-RR browser marks only observed bytes as matched and leaves the rest NOT_OBSERVED',()=>{
 const validate=api('validateRejectedRunEvidence');
 const result=validate(fixture());
 assert.equal(result.verification.quality,'BYTES_MATCHED');
 assert.equal(result.verification.frame_diagnostics,'BYTES_MATCHED');
 for(const key of NOT_OBSERVED)assert.equal(result.verification[key],'NOT_OBSERVED',key+' was never observed by the browser');
 assert.equal(result.verification.physical_accuracy,'UNVERIFIED');
 assert.equal(result.verification.decoded_frame_equality,'UNVERIFIED');
 assert.equal(result.normalizedOutputs,null,'normalized output hashes are unavailable until normalization.json bytes are observed');
 const observed=fixture();observed.observed={preflight:PREFLIGHT_SHA};
 assert.equal(validate(observed).verification.preflight,'BYTES_MATCHED');
 const mismatch=fixture();mismatch.observed={normalization:h('0')};
 assert.throws(()=>validate(mismatch),Error,'observed bytes that differ from the publication digest must refuse review');
});

test('N01-RR missing, malformed, cross-session, swapped or tampered evidence is refused',()=>{
 const validate=api('validateRejectedRunEvidence');
 const cases={
  'stage promoted':f=>{f.run.stages[4].status='passed';},
  'evidence missing':f=>{delete f.run.stages[4].rejected_evidence;},
  'evidence malformed':f=>{f.run.stages[4].rejected_evidence='quality.json';},
  'bound inputs missing':f=>{delete f.run.stages[4].rejected_evidence.bound_inputs;},
  'quality passed':f=>{f.quality.ok=true;},
  'quality ok not exactly false':f=>{f.quality.ok='false';},
  'other session requested':f=>{f.sessionId='TEST_ONLY-rr-other';},
  'sidecar from other session':f=>{f.diagnostics=diagnostics('TEST_ONLY-rr-other');},
  'quality bytes changed':f=>{f.qualitySha256=h('1');},
  'sidecar bytes changed':f=>{f.diagnosticsSha256=h('2');},
  'source TRC swapped':f=>{f.run.stages[4].rejected_evidence.source_trc={path:TRC.path,sha256:h('3')};},
  'calibration swapped':f=>{f.diagnostics.calibration={path:CALIBRATION.path,sha256:h('4')};},
  'quality bound to other sidecar':f=>{f.quality.frame_diagnostics={...binding(),frames:49};},
  'reasons rewritten':f=>{f.run.stages[4].rejected_evidence.reasons=['TEST_ONLY edited'];},
  'protocol changed':f=>{f.run.quality_policy='kinelab.pipeline-quality.v1';},
  'legacy v2 protocol':f=>{f.run.quality_policy='kinelab.pipeline-quality.v2';},
  'legacy v3 protocol':f=>{f.run.quality_policy='kinelab.pipeline-quality.v3';},
 };
 for(const [name,mutate] of Object.entries(cases)){
  const value=fixture();mutate(value);
  assert.throws(()=>validate(value),Error,name);
 }
});

test('N01-RR review exposes no fabricated metric and keeps unavailable values unavailable',()=>{
 const result=api('validateRejectedRunEvidence')(fixture());
 const keys=Object.keys(result).filter(key=>key!=='usableForMeasurement');
 assert.deepEqual(keys.filter(key=>/angle|rom|degree|motion|measured|metric/i.test(key)),[]);
 const cell=result.diagnostics.byIndex.get(6).markers.RKnee.cameras.cam02;
 assert.equal(cell.status,'no_pose_file');
 assert.equal(cell.likelihood,null);
 assert.equal(cell.reprojection_px,null);
});

test('N01-RR passed-run review accepts its positive control and refuses only at the rejected triangulation stage compat',()=>{
 const {run,args}=passedReview();
 const accepted=sync.validateReviewEvidence(...args(run));
 assert.equal(accepted.sessionId,SESSION,'positive control: the generated passed-review fixture must verify');
 assert.equal(accepted.frameDiagnostics,null);
 const failed=fixture().run.stages[4];
 for(const [name,stage] of Object.entries({'failed with rejected_evidence':structuredClone(failed),
  'rejected envelope relabelled passed':Object.assign(structuredClone(run.stages[4]),{rejected_evidence:structuredClone(failed.rejected_evidence)})})){
  const rejected=structuredClone(run);rejected.stages[4]=stage;
  assert.throws(()=>sync.validateReviewEvidence(...args(rejected)),/native stage missing, duplicated, incomplete or rejected: triangulation/,name);
 }
 assert.equal(sync.validateFrameDiagnostics({},null,null).available,false);
});
test('N01-RR mounted VerifiedReview shows persistent REJECTED label, reasons, unavailable values and no promotion',async()=>{
 const view=rejectedReview();
 try{
  view.selectEvidence();
  await view.verifyButton().props.onClick();
  let text=textOf(view.settle());
  assert.ok(text.includes(LABEL),'N01-RR MISSING: persistent rejected label');
  assert.ok(text.includes(REASON),'N01-RR MISSING: stored rejection reason');
  assert.ok(text.includes('missing (not recorded)'),'unavailable diagnostic values must be labelled, not invented');
  assert.match(text,/NOT OBSERVED/,'records the browser never hashed must be shown as not observed');
  assert.match(text,/model-derived|reconstruction estimate/i,'model-derived values must stay labelled separately from observed values');
  assert.doesNotMatch(text,/clinically validated measurement/i);
  const actions=nodes(view.settle(),x=>(x.type==='button'||x.type==='a')&&/export|save|report|download/i.test(textOf(x)));
  assert.deepEqual(actions,[],'rejected review must expose no save, export or report action');
  text=textOf(view.app.render(rejectedProps(1.4,true)));
  assert.ok(text.includes(LABEL),'the rejected label must persist across playback updates');
 }finally{view.app.unmount();view.restore();}
});

test('N01-RR mounted VerifiedReview discards a stale rejected-evidence load',async()=>{
 let release,calls=0;const gate=new Promise(resolve=>{release=resolve;});
 const view=rejectedReview({sha256LocalFile:async file=>{calls++;if(calls===1)await gate;return file.sha256??'generated-hash';}});
 try{
  view.selectEvidence();
  const stale=view.verifyButton().props.onClick();
  view.select(/rejected run\.json/i,{name:'run.json',size:3,text:async()=>'{} '});
  release();await stale;
  assert.ok(!textOf(view.settle()).includes(REASON),'a load superseded by a new selection must not publish its result');
  await view.verifyButton().props.onClick();
  assert.ok(textOf(view.settle()).includes(LABEL),'N01-RR MISSING: current selection did not verify after the stale load');
 }finally{view.app.unmount();view.restore();}
});

test('N01-RR mounted VerifiedReview shows only byte-matched video and revokes every owned URL exactly once',async()=>{
 const outputs={cam01:{sha256:h('6')},cam02:{sha256:h('8')}};
 const view=rejectedReview({validateRejectedRunEvidence:()=>validatedResult({normalizedOutputs:outputs})});
 const files={mismatch:{name:'cam01.mp4',size:2,sha256:h('0')},cam01:{name:'cam01.mp4',size:2,sha256:outputs.cam01.sha256},
  cam02:{name:'cam02.mp4',size:2,sha256:outputs.cam02.sha256}};
 const urlsFor=file=>view.allocations.filter(entry=>entry.file===file).map(entry=>entry.url);
 const videoSources=()=>Object.fromEntries(nodes(view.settle(),x=>x.type==='video').map(x=>{
  const label=String(x.props['aria-label']||'');
  return [/cam01/.test(label)?'cam01':/cam02/.test(label)?'cam02':'unlabelled:'+label,x.props.src??null];
 }));
 let unmounted=false;
 try{
  view.selectEvidence();
  await view.verifyButton().props.onClick();
  view.settle();
  view.select(/rejected cam01 video/i,files.mismatch);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(textOf(view.settle()),/VIDEO UNAVAILABLE/,'a video whose bytes differ from the bound output must stay unavailable');
  assert.deepEqual(view.allocations,[],'no object URL may be allocated for unmatched bytes');
  assert.equal(videoSources().cam01??null,null,'an unmatched video must not be rendered with a source');
  view.select(/rejected cam01 video/i,files.cam01);
  view.select(/rejected cam02 video/i,files.cam02);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(urlsFor(files.cam01).length,1,'N01-RR MISSING: byte-matched cam01 video was not allocated exactly once');
  assert.equal(urlsFor(files.cam02).length,1,'N01-RR MISSING: byte-matched cam02 video was not allocated exactly once');
  assert.deepEqual(urlsFor(files.mismatch),[],'the mismatched file must never be allocated');
  assert.deepEqual(videoSources(),{cam01:urlsFor(files.cam01)[0],cam02:urlsFor(files.cam02)[0]},
   'each rendered video must use the URL allocated for its own matched camera file');
  view.app.unmount();unmounted=true;
  const created=view.allocations.map(entry=>entry.url);
  assert.equal(new Set(created).size,created.length,'allocated URLs must be unique');
  assert.deepEqual([...view.revocations].sort(),[...created].sort(),'every owned URL must be revoked exactly once on cleanup');
 }finally{
  if(!unmounted)view.app.unmount();
  view.restore();
 }
});

// Independent native Codex supplemental cases. Generated TEST_ONLY data only.
// These exercise actual callbacks; the hook driver is not React DOM evidence.
function sessionProps(sessionId){return {...rejectedProps(),sessionId};}
function switchSession(view,sessionId){view.app.render(sessionProps(sessionId));view.app.effects();return view.settle();}
function encodedFile(name,document,textDocument=document){
 const bytes=new TextEncoder().encode(JSON.stringify(document));
 const reads={buffer:0,text:0};
 return {name,size:bytes.byteLength,reads,
  async arrayBuffer(){reads.buffer++;return bytes.slice().buffer;},
  async text(){reads.text++;return JSON.stringify(textDocument);}};
}
async function digestFile(file){
 const bytes=await file.arrayBuffer();file.reads.buffer--;
 return [...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
}
async function actualRejectedFiles({qualityText,normalizationText}={}){
 const f=fixture();
 const diagnostic=encodedFile('reconstruction-frames.json',f.diagnostics);
 f.diagnosticsSha256=await digestFile(diagnostic);
 const binding={...f.quality.frame_diagnostics,sha256:f.diagnosticsSha256,
  path:'diagnostics/reconstruction-frames.'+f.diagnosticsSha256+'.json'};
 f.quality.frame_diagnostics=structuredClone(binding);
 f.run.stages[4].rejected_evidence.frame_diagnostics=structuredClone(binding);
 const normalization={schema:'kinelab.normalization.v1',session_id:SESSION,config_sha256:f.run.config_sha256,
  outputs:Object.fromEntries(['cam01','cam02'].map((cam,i)=>[cam+'_trial',{path:'videos/'+cam+'.mp4',sha256:h(i?'8':'6')}]))};
 const normalized=encodedFile('normalization.json',normalization,normalizationText??normalization);
 const normalizationSha256=await digestFile(normalized);
 f.run.stages[4].rejected_evidence.bound_inputs.normalization.sha256=normalizationSha256;
 const quality=encodedFile('quality.json',f.quality,qualityText??f.quality);
 f.qualitySha256=await digestFile(quality);
 f.run.stages[4].rejected_evidence.quality.sha256=f.qualitySha256;
 // Real validator positive control: bad fixture construction must never count as RED.
 assert.equal(sync.validateRejectedRunEvidence({...f,observed:{normalization:normalizationSha256},normalization}).status,'REJECTED');
 return {f,run:encodedFile('run.json',f.run),quality,diagnostic,normalized};
}
function selectActual(view,files,includeNormalization=false){
 switchSession(view,SESSION);
 view.select(/rejected run\.json/i,files.run);
 view.select(/rejected quality\.json/i,files.quality);
 view.select(/rejected frame diagnostics/i,files.diagnostic);
 if(includeNormalization)view.select(/rejected normalization\.json/i,files.normalized);
}
function assertEveryUrlRevokedOnce(view){
 const created=view.allocations.map(entry=>entry.url);
 assert.deepEqual([...view.revocations].sort(),[...created].sort(),'every previous-session URL must be revoked exactly once');
}

test('N01-IR-02 pending A validation cannot publish after session A to B',async()=>{
 let release,calls=0;const gate=new Promise(resolve=>{release=resolve;});
 const view=rejectedReview({sha256LocalFile:async file=>{if(++calls===1)await gate;return file.sha256??'generated-hash';}});
 try{
  switchSession(view,SESSION);view.selectEvidence();
  const pending=view.verifyButton().props.onClick();
  await Promise.resolve();await Promise.resolve();
  switchSession(view,'TEST_ONLY-other-session');release();await pending;
  assert.doesNotMatch(textOf(view.settle()),new RegExp(REASON),'session A must not appear under session B');
  assert.deepEqual(view.allocations,[]);
 }finally{release?.();view.app.unmount();view.restore();}
});

test('N01-IR-02 verified A and both video URLs are cleared on session A to B',async()=>{
 const outputs={cam01:{sha256:h('6')},cam02:{sha256:h('8')}};
 const view=rejectedReview({validateRejectedRunEvidence:()=>validatedResult({normalizedOutputs:outputs})});
 try{
  switchSession(view,SESSION);view.selectEvidence();await view.verifyButton().props.onClick();
  for(const cam of ['cam01','cam02'])view.select(new RegExp('rejected '+cam+' video','i'),{name:cam+'.mp4',size:2,sha256:outputs[cam].sha256});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(view.allocations.length,2,'positive control: two matched TEST_ONLY videos must load');
  switchSession(view,'TEST_ONLY-other-session');
  assertEveryUrlRevokedOnce(view);
  assert.doesNotMatch(textOf(view.settle()),new RegExp(REASON));
  assert.equal(nodes(view.settle(),node=>node.type==='video'&&node.props.src).length,0);
  view.app.unmount();assertEveryUrlRevokedOnce(view);
 }finally{view.app.unmount();view.restore();}
});

test('N01-IR-01 quality digest and parsed reasons use one bounded buffer',async()=>{
 const files=await actualRejectedFiles({qualityText:{schema:'TEST_ONLY-swapped-text'}});
 const view=rejectedReview({...sync});
 try{
  selectActual(view,files);await view.verifyButton().props.onClick();
  assert.ok(textOf(view.settle()).includes(REASON),'bound arrayBuffer quality must supply the displayed reasons');
  assert.equal(files.quality.reads.buffer,1,'quality buffer must be read exactly once');
  assert.equal(files.quality.reads.text,0,'a second independent text read must not control parsed quality');
 }finally{view.app.unmount();view.restore();}
});

test('N01-IR-01 normalization digest and parsed video identities use one bounded buffer',async()=>{
 const files=await actualRejectedFiles({normalizationText:{schema:'TEST_ONLY-swapped-text'}});
 const view=rejectedReview({...sync});
 try{
  selectActual(view,files,true);await view.verifyButton().props.onClick();
  assert.ok(textOf(view.settle()).includes(REASON),'bound normalization buffer must verify');
  assert.equal(files.normalized.reads.buffer,1);
  assert.equal(files.normalized.reads.text,0,'normalization must never be parsed from an independent text read');
  assert.equal(nodes(view.settle(),node=>node.type==='input'&&/rejected cam0[12] video/i.test(node.props['aria-label']??'')).length,2);
 }finally{view.app.unmount();view.restore();}
});

for(const [id,pattern,name] of [
 ['run',/rejected run\.json/i,'run.json'],['quality',/rejected quality\.json/i,'quality.json'],
 ['preflight',/rejected preflight\.json/i,'preflight.json'],['normalization',/rejected normalization\.json/i,'normalization.json'],
])test('N01-IR-03 oversized '+id+' metadata is refused before either reader',async()=>{
 const files=await actualRejectedFiles();const view=rejectedReview({...sync});let reads=0;
 const oversized={name,size:sync.FRAME_DIAGNOSTICS_MAX_BYTES+1,
  async arrayBuffer(){reads++;throw new Error('TEST_ONLY oversized buffer was read');},
  async text(){reads++;throw new Error('TEST_ONLY oversized text was read');}};
 try{
  selectActual(view,files);view.select(pattern,oversized);await view.verifyButton().props.onClick();
  assert.equal(reads,0,'declared oversized '+id+' must be refused before allocation/hash/parse');
  assert.match(textOf(view.settle()),/size|large|limit|bytes/i,'size refusal must remain visible');
  assert.doesNotMatch(textOf(view.settle()),new RegExp(REASON));assert.deepEqual(view.allocations,[]);
 }finally{view.app.unmount();view.restore();}
});

test('N01-IR-03 actual metadata byte length must equal the declared bounded size',async()=>{
 const files=await actualRejectedFiles();const view=rejectedReview({...sync});
 files.quality.size=1;
 try{
  selectActual(view,files);await view.verifyButton().props.onClick();
  assert.doesNotMatch(textOf(view.settle()),new RegExp(REASON),'mismatched actual buffer length must not verify');
  assert.match(textOf(view.settle()),/size|length|bytes/i);assert.deepEqual(view.allocations,[]);
 }finally{view.app.unmount();view.restore();}
});

for(const [role,invalid] of [
 ['source_trc','../TEST_ONLY.trc'],['source_trc','/TEST_ONLY.trc'],['source_trc','C:/TEST_ONLY.trc'],['source_trc','pose-3d\\TEST_ONLY.trc'],
 ['calibration','../TEST_ONLY.toml'],['calibration','/TEST_ONLY.toml'],['calibration','C:/TEST_ONLY.toml'],['calibration','calibration\\TEST_ONLY.toml'],
])test('N01-IR-05 noncanonical '+role+' reference is refused: '+invalid,()=>{
 const f=fixture();const envelope=f.run.stages[4].rejected_evidence;
 envelope[role].path=invalid;envelope.frame_diagnostics[role].path=invalid;
 f.quality.frame_diagnostics[role].path=invalid;f.diagnostics[role].path=invalid;
 if(role==='calibration')f.run.stages[0].artifacts[0].path=invalid;
 assert.throws(()=>sync.validateRejectedRunEvidence(f),undefined,'noncanonical self-consistent reference must be refused');
});

test('N01-IR-06 dispatch creates a child boundary before any hook is called',()=>{
 const forbidden={...React};
 for(const name of ['useState','useRef','useEffect','useMemo','useId'])forbidden[name]=()=>{throw new Error('TEST_ONLY hook executed by dispatcher: '+name);};
 const Component=moduleAt('./VerifiedReview.jsx',{'react':forbidden}).default;
 let passed,rejected;
 assert.doesNotThrow(()=>{passed=Component({...rejectedProps(),mode:'passed'});},'passed dispatcher must leave hooks to the mounted child');
 assert.doesNotThrow(()=>{rejected=Component(sessionProps(SESSION));},'rejected dispatcher must leave hooks to the mounted child');
 assert.ok(React.isValidElement(passed)&&React.isValidElement(rejected));
 assert.equal(typeof passed.type,'function');assert.equal(typeof rejected.type,'function');
 assert.notEqual(passed.type,rejected.type,'mode switch must change component ownership boundary');
});

// Generated TEST_ONLY legacy fixture; no saved evidence is promoted or rewritten.
test('B14-FRONTEND-02 v3 rejected review accepted and unchanged coherent v2 refused',()=>{
 const current=fixture(),currentBefore=structuredClone(current);
 assert.equal(api('validateRejectedRunEvidence')(current).status,'REJECTED');
 assert.deepEqual(current,currentBefore,'v4 validation preserves input');
 const legacy=fixture();
 legacy.run.quality_policy='kinelab.pipeline-quality.v2';
 legacy.quality.policy='kinelab.pipeline-quality.v2';
 legacy.diagnostics.policy='kinelab.pipeline-quality.v2';
 for(const stage of legacy.run.stages)if(stage.quality)stage.quality.policy='kinelab.pipeline-quality.v2';
 const legacyBefore=structuredClone(legacy);
 assert.throws(()=>api('validateRejectedRunEvidence')(legacy),/quality policy differs/);
 assert.deepEqual(legacy,legacyBefore,'v2 refusal must not relabel legacy evidence');
});

