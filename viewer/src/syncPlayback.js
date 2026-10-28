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
    matches[0].quality.ok!==true||!Array.isArray(matches[0].artifacts)||!matches[0].artifacts.length)
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
 return {
  sessionId:motion.sessionId,
  fps:30,
  nativeCorrelation:sync.native_correlation,
  reference:sync.reference,
  offsets:Object.fromEntries(CAMERAS.map(cam=>[cam,sync.cameras[cam].offset_frames])),
  videos,
  proof:'native-synchronization-recorded-passed; not clinically validated',
 };
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
