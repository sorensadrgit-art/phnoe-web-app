// Standalone verified local-media contract for KineLab PT v1 T4.
// Nothing is uploaded. Only a v2 REAL motion export bound by hash to its exact
// native run manifest and source-video hashes can enable two-camera review.
import {angleDegrees} from './motionData.js';

const HASH=/^[0-9a-f]{64}$/;
const ROLES=['cam01_intrinsics','cam02_intrinsics','cam01_board','cam02_board','cam01_trial','cam02_trial'];
const STAGES=['calibration','poseEstimation','synchronization','personAssociation','triangulation','filtering'];
const CAMERAS=['cam01','cam02'];
const isObject=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const fail=why=>{throw Error('Unverified synchronized review: '+why)};

function equalInputs(a,b){
 if(!isObject(a)||!isObject(b))return false;
 return ROLES.every(role=>HASH.test(a[role])&&a[role]===b[role]) &&
  Object.keys(a).length===ROLES.length && Object.keys(b).length===ROLES.length;
}
function nativeStage(run,name){
 if(!Array.isArray(run.stages))fail('native run stages unavailable');
 const matches=run.stages.filter(s=>isObject(s)&&s.name===name);
 if(matches.length!==1||matches[0].status!=='passed'||!isObject(matches[0].quality)||
    matches[0].quality.ok!==true||!Array.isArray(matches[0].artifacts)||!matches[0].artifacts.length||
    Object.hasOwn(matches[0],'rejected_evidence'))
   fail('native stage missing, duplicated, incomplete or rejected: '+name);
 return matches[0];
}
function videoMeta(normalized,camera,hash){
 const role=camera+'_trial';
 const meta=normalized.outputs?.[role];
 if(!isObject(meta)||meta.path!=='videos/'+camera+'.mp4'||!HASH.test(meta.sha256)||
    meta.sha256!==hash) fail(camera+' MP4 provenance mismatch');
 if(meta.width!==1280||meta.height!==720||meta.fps!=='30/1'||
    !Number.isInteger(meta.frame_count)||meta.frame_count<2||
    !Array.isArray(meta.timestamps)||meta.timestamps.length!==meta.frame_count)
   fail(camera+' normalized geometry, timing or count invalid');
 if(meta.timestamps.some((t,i)=>!finite(t)||Math.abs(t-i/30)>.002))
   fail(camera+' normalized timestamps do not match actual 30 fps');
 return {frameCount:meta.frame_count,timestamps:meta.timestamps,sha256:meta.sha256};
}
function validCuePairs(sync,videos){
 if(!Array.isArray(sync.source_frame_pairs)||sync.source_frame_pairs.length!==4)
   fail('start/end observations for both cameras missing');
 for(const cam of CAMERAS){
  const rows=sync.source_frame_pairs.filter(row=>row?.camera===cam)
    .sort((a,b)=>a.synchronized_frame_index-b.synchronized_frame_index);
  if(rows.length!==2)fail('expected two independent '+cam+' cue pairs');
  const offset=sync.cameras[cam].offset_frames;
  const residual=[];
  for(const pair of rows){
   const source=pair.source_frame_index,ref=pair.synchronized_frame_index;
   if(!Number.isInteger(source)||!Number.isInteger(ref)||source<0||ref<0||
      source>=videos[cam].frameCount||Math.abs(source-ref-offset)>1)
     fail(cam+' operator cue indices contradict recorded signed offset');
   residual.push(source-ref-offset);
  }
  if(rows[0].source_frame_index>=rows[1].source_frame_index||
     rows[0].synchronized_frame_index>=rows[1].synchronized_frame_index||
     Math.abs(residual[1]-residual[0])>1||
     residual[0]!==sync.cameras[cam].start_residual_frames||
     residual[1]!==sync.cameras[cam].end_residual_frames)
    fail(cam+' start/end cue ordering or drift invalid');
 }
}
export function validateReviewEvidence(motion,normalized,sync,run,checks){
 if(!isObject(motion)||motion.schema!=='kinelab.motion.v2'||motion.kind!=='real'||
    motion.quality?.status!=='passed'||!Array.isArray(motion.frames)||!motion.frames.length||
    motion.time?.origin!=='synchronized_trial_start'||motion.time.unit!=='s')
   fail('only verified real session-bound v2 motion has video review');
 if(!isObject(run)||run.schema!=='kinelab.run.v1'||run.session_id!==motion.sessionId||
    !HASH.test(motion.provenance?.runManifestSha256)||
    checks?.runHash!==motion.provenance.runManifestSha256)
   fail('run manifest is not the exact motion-export provenance');
 if(!isObject(normalized)||normalized.schema!=='kinelab.normalization.v1'||
    normalized.session_id!==motion.sessionId||run.config_sha256!==normalized.config_sha256||
    !equalInputs(run.inputs,normalized.inputs))
   fail('normalized footage input/configuration differs from passed native run');
 if(run.native_triangulation_policy?.interpolation!=='none'||
    run.native_triangulation_policy?.fill_large_gaps_with!=='nan')
   fail('native triangulation policy is not the accepted no-gap-filling policy');
 for(const name of STAGES)nativeStage(run,name);
 if(!isObject(sync)||sync.schema!=='kinelab.sync.v1'||sync.ok!==true||
    sync.session_id!==motion.sessionId||!CAMERAS.includes(sync.reference)||
    !isObject(sync.cameras)||Object.keys(sync.cameras).length!==2||
    !finite(sync.native_correlation)||sync.native_correlation<=.5||sync.native_correlation>1)
   fail('independent native synchronization quality unavailable');
 const quality=nativeStage(run,'synchronization').quality;
 if(quality.reference!==sync.reference||quality.native_correlation!==sync.native_correlation||
    JSON.stringify(quality.source_frame_pairs)!==JSON.stringify(sync.source_frame_pairs))
   fail('native run synchronization record does not match supplied sync report');
 const videos={};
 for(const camera of CAMERAS){
  const parameters=sync.cameras[camera],recorded=quality.cameras?.[camera];
  if(!isObject(parameters)||!isObject(recorded)||
     !Number.isInteger(parameters.offset_frames)||
     !finite(parameters.start_residual_frames)||!finite(parameters.end_residual_frames)||
     Math.abs(parameters.start_residual_frames)>1||Math.abs(parameters.end_residual_frames)>1||
     Math.abs(parameters.end_residual_frames-parameters.start_residual_frames)>1||
     JSON.stringify(recorded)!==JSON.stringify(parameters))
   fail(camera+' native/observed camera offsets or drift disagree');
  videos[camera]=videoMeta(normalized,camera,checks?.videoHashes?.[camera]);
 }
 if(sync.cameras[sync.reference].offset_frames!==0)
  fail('native reference camera must have zero frame offset');
 validCuePairs(sync,videos);
 const triangulation=nativeStage(run,'triangulation');
 const trc=stageArtifact(triangulation,'.trc');
 const calibration=stageArtifact(nativeStage(run,'calibration'),'.toml');
 return {
  sessionId:motion.sessionId,
  fps:30,
  nativeCorrelation:sync.native_correlation,
  reference:sync.reference,
  offsets:Object.fromEntries(CAMERAS.map(cam=>[cam,sync.cameras[cam].offset_frames])),
  videos,
  proof:'native-synchronization-recorded-passed; not clinically validated',
  frameDiagnostics:diagnosticsBinding(triangulation.quality,trc,calibration),
  stageTrc:{triangulation:trc?.sha256??null,filtering:optionalStageTrc(run,'filtering'),
   markerAugmentation:optionalStageTrc(run,'markerAugmentation')},
  displayedTrcSha256:motion.provenance?.trcSha256??null,
  calibration,
 };
}

// ---- Run-bound reconstruction frame diagnostics (research diagnostic; not clinically validated) ----
export const FRAME_DIAGNOSTICS_MAX_BYTES=32*1024*1024;
const FRAME_SCHEMA='kinelab.reconstruction-frames.v1';
const FRAME_POLICY='kinelab.pipeline-quality.v4';
const FRAME_PATH=/^diagnostics\/reconstruction-frames\.([0-9a-f]{64})\.json$/;
const FRAME_MARKERS=['Hip','RHip','RKnee','RAnkle','LHip','LKnee','LAnkle'];
const FRAME_STATUSES=['supported','projection_non_finite','behind_camera','trc_point_missing',
 'no_pose_file','people_count_not_one','keypoint_missing'];
const FRAME_CRITERIA={views:2,likelihood:[.3,1],reprojection_px_max:15,coverage_min:.95,longest_gap_frames_max:3};
const FRAME_TEXT={classification:'native_triangulated_unfiltered',
 value_kind:'reconstruction estimate; research diagnostic; not measured physical truth',
 physical_accuracy:'not validated',clinical_validation:'UNVERIFIED',
 camera_depth_units:'calibration translation units; physical scale UNVERIFIED',
 frame_index_basis:'round(trc_time_s * trc_fps) = pose-associated file index; equality with decoded source video frame UNVERIFIED'};
const FRAME_KEYS=['schema','policy','session_id','source_trc','calibration','camera_ids','required_markers','criteria','frames',...Object.keys(FRAME_TEXT)];
const MIN_DEPTH=1e-12;
const CLASSIFICATIONS={triangulation:'native_triangulated_unfiltered',filtering:'native_filtered_research_only',
 markerAugmentation:'model_derived_LSTM_estimate_not_observed'};

const hasKeys=(value,keys)=>isObject(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
function canonical(value){
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(isObject(value))return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';
 return JSON.stringify(value);
}
function stageArtifact(stage,suffix){
 const items=(Array.isArray(stage?.artifacts)?stage.artifacts:[])
  .filter(a=>isObject(a)&&typeof a.path==='string'&&a.path.endsWith(suffix));
 return items.length===1&&HASH.test(items[0].sha256)?{path:items[0].path,sha256:items[0].sha256}:null;
}
function optionalStageTrc(run,name){
 const matches=run.stages.filter(s=>isObject(s)&&s.name===name&&s.status==='passed');
 return matches.length===1?stageArtifact(matches[0],'.trc')?.sha256??null:null;
}
const sameReference=(value,reference)=>reference!==null&&hasKeys(value,['path','sha256'])&&
 value.path===reference.path&&value.sha256===reference.sha256;
function diagnosticsBinding(quality,trc,calibration){
 if(!Object.hasOwn(quality,'frame_diagnostics'))return null;
 const binding=quality.frame_diagnostics;
 const match=typeof binding?.path==='string'?FRAME_PATH.exec(binding.path):null;
 if(!hasKeys(binding,['path','sha256','schema','source_trc','calibration','frames'])||!match||
    !HASH.test(binding.sha256)||match[1]!==binding.sha256||binding.schema!==FRAME_SCHEMA||
    !sameReference(binding.source_trc,trc)||!sameReference(binding.calibration,calibration)||
    !Number.isInteger(binding.frames)||binding.frames<1)
  fail('frame diagnostics binding is malformed or not bound to the recorded triangulation TRC and calibration');
 return {path:binding.path,sha256:binding.sha256,schema:binding.schema,source_trc:{...trc},
  calibration:{...calibration},frames:binding.frames};
}

// JSON.parse keeps the last duplicate key silently; scan the same text so an
// ambiguous document is refused instead of resolved.
function assertUniqueKeys(text){
 const stack=[];
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(c==='"'){
   let j=i+1;
   while(text[j]!=='"'){if(text[j]==='\\')j++;j++;}
   const top=stack[stack.length-1];
   if(top?.keys&&top.expectKey){
    const key=JSON.parse(text.slice(i,j+1));
    if(top.keys.has(key))fail('frame diagnostics contain a duplicate key '+key);
    top.keys.add(key);top.expectKey=false;
   }
   i=j;
  }else if(c==='{')stack.push({keys:new Set(),expectKey:true});
  else if(c==='[')stack.push({keys:null,expectKey:false});
  else if(c==='}'||c===']')stack.pop();
  else if(c===','&&stack[stack.length-1]?.keys)stack[stack.length-1].expectKey=true;
 }
}
function assertFiniteNumbers(root){
 const pending=[root];
 while(pending.length){
  const value=pending.pop();
  if(typeof value==='number'&&!Number.isFinite(value))fail('frame diagnostics contain a non-finite number');
  if(value!==null&&typeof value==='object')pending.push(...Object.values(value));
 }
}
// One bounded buffer supplies both the digest and the parsed document; also used for
// the other local JSON evidence files so a hash never describes different parsed bytes.
export async function loadFrameDiagnosticsFile(file,label='frame diagnostics'){
 if(!Number.isInteger(file?.size)||file.size<1||file.size>FRAME_DIAGNOSTICS_MAX_BYTES)
  fail(label+' file is empty or exceeds the byte cap (size limit '+FRAME_DIAGNOSTICS_MAX_BYTES+' bytes)');
 if(typeof file.arrayBuffer!=='function'||!globalThis.crypto?.subtle?.digest)
  fail('local SHA-256 is unavailable; use the app on localhost');
 const bytes=await file.arrayBuffer();
 if(bytes.byteLength!==file.size)fail(label+' file changed while it was read (byte length differs from declared size)');
 const digest=await globalThis.crypto.subtle.digest('SHA-256',bytes);
 const sha256=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
 let text,document;
 try{
  text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  document=JSON.parse(text);
 }catch{fail(label+' are not valid UTF-8 JSON')}
 assertUniqueKeys(text);
 assertFiniteNumbers(document);
 return {sha256,document};
}

function frameCell(cell){
 if(!hasKeys(cell,['status','likelihood','reprojection_px','camera_depth'])||!FRAME_STATUSES.includes(cell.status))
  fail('frame diagnostics camera record has an unknown status or fields');
 const {likelihood:l,reprojection_px:r,camera_depth:d}=cell;
 if([l,r,d].some(v=>v!==null&&!finite(v)))fail('frame diagnostics camera values must be finite numbers or null');
 const deep=d!==null&&d>MIN_DEPTH;
 const shape={supported:l!==null&&r!==null&&r>=0&&deep,projection_non_finite:l!==null&&r===null&&deep,
  behind_camera:l!==null&&r===null&&!deep,trc_point_missing:r===null&&d===null}[cell.status]??(l===null&&r===null&&d===null);
 if(!shape||(l!==null&&(l<0||l>1)))fail('frame diagnostics values contradict camera status '+cell.status);
 return cell;
}
function frameMarker(stored){
 if(!hasKeys(stored,['valid','views','cameras'])||!hasKeys(stored.cameras,CAMERAS))fail('frame diagnostics marker record malformed');
 const supported=CAMERAS.map(cam=>frameCell(stored.cameras[cam])).filter(cell=>cell.status==='supported');
 const residual=supported.length?Math.max(...supported.map(cell=>cell.reprojection_px)):null;
 // Literal assess_reconstruction predicate: two supported views, likelihood in [0.3,1], residual in [0,15] px.
 const valid=supported.length===2&&supported.every(cell=>cell.likelihood>=.3&&cell.likelihood<=1)&&
  finite(residual)&&residual>=0&&residual<=15;
 if(typeof stored.valid!=='boolean'||stored.valid!==valid||!Number.isInteger(stored.views)||stored.views!==supported.length)
  fail('stored frame validity contradicts camera support');
 return valid;
}
export function validateFrameDiagnostics(evidence,document,sha256){
 const binding=evidence?.frameDiagnostics;
 if(!binding)return {available:false,reason:'Frame diagnostics NOT RECORDED by this native run'};
 if(sha256!==binding.sha256)fail('frame diagnostics bytes differ from the run-bound SHA-256');
 if(!hasKeys(document,FRAME_KEYS)||document.schema!==FRAME_SCHEMA||document.policy!==FRAME_POLICY||
    document.session_id!==evidence.sessionId||canonical(document.criteria)!==canonical(FRAME_CRITERIA)||
    canonical(document.camera_ids)!==canonical(CAMERAS)||canonical(document.required_markers)!==canonical(FRAME_MARKERS)||
    Object.entries(FRAME_TEXT).some(([key,value])=>document[key]!==value))
  fail('frame diagnostics identity, policy, criteria or labels differ from the verified run');
 if(!sameReference(document.source_trc,binding.source_trc)||!sameReference(document.calibration,binding.calibration))
  fail('frame diagnostics are bound to a different TRC or calibration');
 if(!Array.isArray(document.frames)||document.frames.length!==binding.frames)
  fail('frame diagnostics frame count differs from the run binding');
 const byIndex=new Map(),rejectedFrames=[];
 let last=-1;
 for(const frame of document.frames){
  if(!hasKeys(frame,['synchronized_frame_index','rejected','markers'])||!Number.isInteger(frame.synchronized_frame_index)||
     frame.synchronized_frame_index<=last||!hasKeys(frame.markers,FRAME_MARKERS))
   fail('frame diagnostics frame order or marker set invalid');
  last=frame.synchronized_frame_index;
  const rejected=!FRAME_MARKERS.map(marker=>frameMarker(frame.markers[marker])).every(Boolean);
  if(typeof frame.rejected!=='boolean'||frame.rejected!==rejected)fail('stored frame rejection contradicts marker validity');
  byIndex.set(last,frame);
  if(rejected)rejectedFrames.push(last);
 }
 const stage=Object.keys(CLASSIFICATIONS).find(name=>evidence.stageTrc?.[name]&&evidence.stageTrc[name]===evidence.displayedTrcSha256);
 return {available:true,sessionId:document.session_id,byIndex,rejectedFrames,
  displayedClassification:stage?CLASSIFICATIONS[stage]:'unknown',criteria:structuredClone(FRAME_CRITERIA)};
}
// ---- Rejected native triangulation review (read-only; never usable for measurement) ----
const REJECTED_SCHEMA='kinelab.rejected-triangulation.v1';
const REJECTED_LABEL='REJECTED / NOT USABLE FOR MEASUREMENT';
const REJECTED_KEYS=['schema','session_id','quality','frame_diagnostics','source_trc','calibration','bound_inputs','reasons','usable_for_measurement'];
const BOUND_INPUTS={preflight:'preflight.json',normalization:'normalization.json'};
const rejectedFail=why=>{throw Error('Rejected run evidence refused: '+why)};
// run_pipeline._bound_bytes containment (relative, no backslash, drive or ".."), and
// additionally no empty or "." segment, which Path.parts would silently normalize away.
const canonicalRelative=path=>typeof path==='string'&&path.length>0&&!path.startsWith('/')&&
 !path.includes('\\')&&!path.includes(':')&&path.split('/').every(part=>part!==''&&part!=='.'&&part!=='..');
function boundReference(value,path,suffix){
 if(!hasKeys(value,['path','sha256'])||!canonicalRelative(value.path)||!HASH.test(value.sha256)||
    (path!==null&&value.path!==path)||(suffix&&!value.path.endsWith(suffix)))
  rejectedFail('bound record malformed: '+(path??suffix));
 return {path:value.path,sha256:value.sha256};
}
// The browser only attests bytes it hashed itself. Every other bound record is
// reported NOT_OBSERVED; physical accuracy and decoded-frame equality are never attested.
export function validateRejectedRunEvidence({run,quality,qualitySha256,diagnostics,diagnosticsSha256,sessionId,observed={},normalization=null}){
 if(!isObject(run)||run.schema!=='kinelab.run.v1'||typeof sessionId!=='string'||!sessionId||run.session_id!==sessionId)
  rejectedFail('run manifest is not the requested session');
 if(run.quality_policy!==FRAME_POLICY)rejectedFail('quality policy differs from '+FRAME_POLICY);
 if(run.native_triangulation_policy?.interpolation!=='none'||run.native_triangulation_policy?.fill_large_gaps_with!=='nan')
  rejectedFail('native triangulation policy is not the accepted no-gap-filling policy');
 if(!Array.isArray(run.stages))rejectedFail('native run stages unavailable');
 const order=run.stages.map(stage=>isObject(stage)?stage.name:null);
 const at=order.indexOf('triangulation');
 if(at<0||order.lastIndexOf('triangulation')!==at)rejectedFail('triangulation stage missing or duplicated');
 for(const name of STAGES.slice(0,STAGES.indexOf('triangulation'))){
  if(order.indexOf(name)<0||order.indexOf(name)>at)rejectedFail('stage before triangulation missing: '+name);
  nativeStage(run,name);
 }
 run.stages.forEach((stage,index)=>{
  if(index!==at&&Object.hasOwn(stage,'rejected_evidence'))rejectedFail('rejected evidence outside the triangulation stage');
  if(index>at&&stage.status==='passed')rejectedFail('a stage after the rejected triangulation is recorded as passed');
 });
 const stage=run.stages[at];
 if(stage.status!=='failed'||!Array.isArray(stage.artifacts)||stage.artifacts.length!==0||Object.hasOwn(stage,'quality'))
  rejectedFail('triangulation stage is not a failed stage without artifacts');
 const envelope=stage.rejected_evidence;
 if(!hasKeys(envelope,REJECTED_KEYS)||envelope.schema!==REJECTED_SCHEMA||envelope.session_id!==sessionId||
    envelope.usable_for_measurement!==false)
  rejectedFail('rejected evidence envelope missing or malformed');
 if(!Array.isArray(envelope.reasons)||!envelope.reasons.length||envelope.reasons.some(reason=>typeof reason!=='string'||!reason))
  rejectedFail('stored rejection reasons missing');
 const qualityRef=boundReference(envelope.quality,'quality.json');
 const trc=boundReference(envelope.source_trc,null,'.trc');
 const calibration=boundReference(envelope.calibration,null,'.toml');
 if(!sameReference(calibration,stageArtifact(nativeStage(run,'calibration'),'.toml')))
  rejectedFail('calibration differs from the recorded calibration stage');
 if(!hasKeys(envelope.bound_inputs,Object.keys(BOUND_INPUTS)))rejectedFail('bound inputs missing');
 const bound=Object.fromEntries(Object.entries(BOUND_INPUTS).map(([id,path])=>[id,boundReference(envelope.bound_inputs[id],path)]));
 let binding;
 try{binding=diagnosticsBinding({frame_diagnostics:envelope.frame_diagnostics},trc,calibration);}
 catch(error){rejectedFail(error.message);}
 if(!binding)rejectedFail('frame diagnostics binding missing');
 if(qualitySha256!==qualityRef.sha256)rejectedFail('quality.json bytes differ from the run-bound SHA-256');
 if(!isObject(quality)||quality.schema!=='kinelab.quality.v1'||quality.policy!==FRAME_POLICY||
    quality.session_id!==sessionId||quality.ok!==false)
  rejectedFail('quality report is not a rejected report for this session and policy');
 if(canonical(quality.errors)!==canonical(envelope.reasons))rejectedFail('stored reasons differ from the quality report');
 if(canonical(quality.frame_diagnostics)!==canonical(envelope.frame_diagnostics))
  rejectedFail('quality report is bound to different frame diagnostics');
 const evidence={sessionId,frameDiagnostics:binding,stageTrc:{triangulation:trc.sha256},displayedTrcSha256:trc.sha256};
 let checked;
 try{checked=validateFrameDiagnostics(evidence,diagnostics,diagnosticsSha256);}
 catch(error){rejectedFail(error.message);}
 const verification={config:'NOT_OBSERVED',quality:'BYTES_MATCHED',frame_diagnostics:'BYTES_MATCHED',
  preflight:'NOT_OBSERVED',normalization:'NOT_OBSERVED',normalized_outputs:'NOT_OBSERVED',
  calibration:'NOT_OBSERVED',source_trc:'NOT_OBSERVED',physical_accuracy:'UNVERIFIED',decoded_frame_equality:'UNVERIFIED'};
 if(!isObject(observed))rejectedFail('observed digests malformed');
 for(const [id,digest] of Object.entries(observed)){
  if(!Object.hasOwn(BOUND_INPUTS,id))rejectedFail('unknown observed record '+id);
  if(digest!==bound[id].sha256)rejectedFail(BOUND_INPUTS[id]+' bytes differ from the run-bound SHA-256');
  verification[id]='BYTES_MATCHED';
 }
 let normalizedOutputs=null;
 if(verification.normalization==='BYTES_MATCHED'&&normalization!==null){
  if(!isObject(normalization)||normalization.schema!=='kinelab.normalization.v1'||normalization.session_id!==sessionId||
     normalization.config_sha256!==run.config_sha256||!isObject(normalization.outputs))
   rejectedFail('normalization record is not bound to this session and configuration');
  normalizedOutputs=Object.fromEntries(CAMERAS.map(cam=>{
   const meta=normalization.outputs[cam+'_trial'];
   if(!isObject(meta)||meta.path!=='videos/'+cam+'.mp4'||!HASH.test(meta.sha256))rejectedFail(cam+' normalized output record malformed');
   return [cam,{path:meta.path,sha256:meta.sha256}];
  }));
 }
 return {status:'REJECTED',label:REJECTED_LABEL,usableForMeasurement:false,reasons:[...envelope.reasons],sessionId,
  diagnostics:checked,verification,normalizedOutputs,
  records:{quality:qualityRef,frameDiagnostics:{path:binding.path,sha256:binding.sha256},sourceTrc:trc,calibration,boundInputs:bound}};
}
export function frameDiagnosticAt(diagnostics,evidence,seconds){
 if(!diagnostics?.available)return null;
 const targets=videoFrameAtTime(evidence,seconds);
 const synchronizedFrame=Math.round(seconds*evidence.fps);
 const record=diagnostics.byIndex.get(synchronizedFrame)??null;
 return {synchronizedFrame,sourceFrames:Object.fromEntries(CAMERAS.map(cam=>[cam,targets[cam]?.frame??null])),
  record,rejected:record?record.rejected:null,markers:record?record.markers:null};
}
export function frameDiagnosticLegend(){
 return [
  {id:'native_triangulated_unfiltered',label:'Native two-camera triangulation, unfiltered: reconstruction estimate, not clinically validated'},
  {id:'native_filtered_research_only',label:'Native filtered TRC: research-only reconstruction estimate, not clinically validated'},
  {id:'model_derived_LSTM_estimate_not_observed',label:'LSTM model-derived marker estimate, not observed by either camera; not clinically validated'},
  {id:'missing',label:'Missing sample: shown as missing (not recorded) and never filled'},
  {id:'source_video',label:'Source video frame target from the native sync record; decoded frame equality UNVERIFIED'},
 ];
}

// Frame positions derive from the normalized source-video timestamps, not from
// the chosen browser video's autoplay clock or unrelated wall-clock start.
export function videoFrameAtTime(evidence,seconds){
 if(!finite(seconds))fail('invalid synchronized playback timestamp');
 const aligned=Math.round(seconds*evidence.fps);
 return Object.fromEntries(CAMERAS.map(camera=>{
  const video=evidence.videos[camera],index=aligned+evidence.offsets[camera];
  return [camera,index<0||index>=video.frameCount?null:{
    frame:index,synchronizedFrame:aligned,videoTime:video.timestamps[index],
  }];
 }));
}

// Missing OpenSim data stays missing; do not synthesize an angular graph from 3D points.
export function angleSamples(motion,columnName){
 if(!motion?.kinematics)return null;
 return motion.frames.map(frame=>({t:frame.t,value:angleDegrees(motion.kinematics,columnName,frame.t)}));
}

// Browser-only digest helper. Used after the operator explicitly chooses local
// run.json and cam01/cam02 MP4 files; the bytes never leave the browser.
export async function sha256LocalFile(file){
 if(!file || typeof file.arrayBuffer!=='function' || !globalThis.crypto?.subtle?.digest)
  fail('local SHA-256 is unavailable; use the app on localhost');
 const bytes=await file.arrayBuffer();
 const digest=await globalThis.crypto.subtle.digest('SHA-256',bytes);
 return Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
}
