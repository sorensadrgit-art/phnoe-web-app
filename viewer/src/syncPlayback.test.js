import test from 'node:test';
import assert from 'node:assert/strict';
import {validateReviewEvidence,videoFrameAtTime,angleSamples,sha256LocalFile} from './syncPlayback.js';
import {validateMotion} from './motionData.js';

const h=n=>String(n).repeat(64);
const roles=['cam01_intrinsics','cam02_intrinsics','cam01_board','cam02_board','cam01_trial','cam02_trial'];
const fixture=()=>{
 const inputs=Object.fromEntries(roles.map((role,i)=>[role,h((i%9)+1)]));
 const names=['calibration','poseEstimation','synchronization','personAssociation','triangulation','filtering'];
 const quality={ok:true,session_id:'session-a',reference:'cam01',
   cameras:{cam01:{offset_frames:0,start_residual_frames:0,end_residual_frames:0},
            cam02:{offset_frames:-3,start_residual_frames:0,end_residual_frames:0}},
   native_correlation:.9};
 const run={schema:'kinelab.run.v1',session_id:'session-a',inputs,
  config_sha256:h('b'),native_triangulation_policy:{interpolation:'none',fill_large_gaps_with:'nan'},
  stages:names.map(name=>({name,status:'passed',quality:{...quality},artifacts:[{path:'dummy',sha256:h('e')}] }))};
 const outputs={};
 for(const [i,camera] of ['cam01','cam02'].entries()){
  const count=i?50:60;
  outputs[camera+'_trial']={path:'videos/'+camera+'.mp4',sha256:h(i?'d':'c'),
   fps:'30/1',width:1280,height:720,frame_count:count,
   timestamps:Array.from({length:count},(_,j)=>j/30)};
 }
 const normalized={schema:'kinelab.normalization.v1',session_id:'session-a',config_sha256:h('b'),inputs,outputs};
 const sync={schema:'kinelab.sync.v1',session_id:'session-a',ok:true,reference:'cam01',
  native_correlation:.9,cameras:quality.cameras,
  source_frame_pairs:[
    {camera:'cam01',synchronized_frame_index:5,source_frame_index:5},
    {camera:'cam01',synchronized_frame_index:45,source_frame_index:45},
    {camera:'cam02',synchronized_frame_index:5,source_frame_index:2},
    {camera:'cam02',synchronized_frame_index:45,source_frame_index:42},
  ]};
 run.stages.find(stage=>stage.name==='synchronization').quality.source_frame_pairs=sync.source_frame_pairs;
 const motion=validateMotion({schema:'kinelab.motion.v2',sessionId:'session-a',kind:'real',
  units:'m',coordinateSystem:'opensim_y_up',fps:30,markers:['Hip'],bones:[],
  frames:Array.from({length:50},(_,i)=>({t:i/30,xyz:[[0,1,0]]})),
  time:{unit:'s',origin:'synchronized_trial_start'},
  provenance:{runManifestSha256:h('a'),trcSha256:h('f'),motSha256:null,calibrationSha256:h('c')},
  quality:{status:'passed',mode:'marker-only'},kinematics:null});
 return {motion,run,normalized,sync,checks:{runHash:h('a'),videoHashes:{cam01:h('c'),cam02:h('d')}}};
};

test('verified manifest ties motion, native run, sync, normalization and camera file hashes',()=>{
 const f=fixture();
 const info=validateReviewEvidence(f.motion,f.normalized,f.sync,f.run,f.checks);
 assert.equal(info.sessionId,'session-a');
 assert.equal(info.nativeCorrelation,.9);
 assert.equal(info.offsets.cam02,-3);
 assert.equal(info.fps,30);
});

test('one timeline uses normalized actual timestamps and signed camera offset',()=>{
 const f=fixture();
 const bound=validateReviewEvidence(f.motion,f.normalized,f.sync,f.run,f.checks);
 assert.equal(videoFrameAtTime(bound,.2).cam01.frame,6);
 assert.equal(videoFrameAtTime(bound,.2).cam02.frame,3);
 assert.ok(Math.abs(videoFrameAtTime(bound,.2).cam02.videoTime-.1)<1e-9);
 assert.equal(videoFrameAtTime(bound,0).cam02,null);
 assert.equal(videoFrameAtTime(bound,53/30).cam02,null);
 assert.equal(videoFrameAtTime(bound,-2).cam01,null);
});

test('refuses unverified stages and fabricated demo/legacy pairing',()=>{
 for(const [caseNumber,mutate] of [
  f=>f.motion.kind='demo',
  f=>f.motion.schema='kinelab.motion.v1',
  f=>f.run.stages[2].status='failed',
  f=>delete f.run.stages[2].quality,
  f=>f.sync.ok=false,
  f=>f.sync.reference='cam02',
  f=>f.sync.cameras.cam02.offset_frames=9,
  f=>f.normalized.session_id='different',
  f=>f.run.inputs={...f.run.inputs,cam01_trial:h('9')},
  f=>f.checks.runHash=h('8'),
  f=>f.checks.videoHashes.cam02=h('8'),
  f=>f.normalized.outputs.cam01_trial.path='../capture.mp4',
  f=>f.normalized.outputs.cam02_trial.timestamps[4]=Number.NaN,
 ].entries()){
  const f=fixture();
  mutate(f);
  assert.throws(()=>validateReviewEvidence(f.motion,f.normalized,f.sync,f.run,f.checks), 'mutation '+caseNumber);
 }
});

test('angle series is unavailable when marker-only; valid angles preserve gaps',()=>{
 const f=fixture();
 assert.equal(angleSamples(f.motion,'knee_angle_r'),null);
 f.motion.kinematics={columns:['time','knee_angle_r','knee_angle_l'],inDegrees:false,
  rows:[ [0,Math.PI/2,Math.PI/3],[1/30,Math.PI/2,Math.PI/3] ],timeTolerance:1/60};
 const right=angleSamples(f.motion,'knee_angle_r');
 assert.equal(Math.round(right[0].value),90);
 assert.equal(Math.round(right[1].value),90);
 assert.equal(right[2].value,null);

 // Bolt Optimization verification: Repeated calls return the exact cached reference
 const cachedRight=angleSamples(f.motion,'knee_angle_r');
 assert.equal(cachedRight, right);
 const left=angleSamples(f.motion,'knee_angle_l');
 assert.notEqual(left, right);
 assert.equal(Math.round(left[0].value),60);
});

test('local browser file digest verifies actual bytes without a network request',async()=>{
 const blob=new Blob(['abc']);
 assert.equal(await sha256LocalFile(blob),
  'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
});
