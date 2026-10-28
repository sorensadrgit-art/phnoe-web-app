import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateMotion,frameAtTime,angleDegrees} from './motionData.js';

const makeMotion=()=>({
 schema:'kinelab.motion.v1',units:'m',coordinateSystem:'opensim_y_up',fps:30,
 markers:['Hip','RHip'],bones:[[0,1]],
 frames:[{t:2,xyz:[[1,2,3],null]},{t:2.1,xyz:[[2,2,3],[4,5,6]]},{t:2.4,xyz:[[3,2,3],[4,5,6]]}],
 kinematics:{columns:['time','knee_angle_r','pelvis_tx'],rows:[[2,Math.PI/2,.25],[2.1,Math.PI/2,.25],[2.4,Math.PI/2,.25]],inDegrees:false}
});
const makeV2=()=>({...makeMotion(),schema:'kinelab.motion.v2',sessionId:'factory_session',kind:'real',
 provenance:{runManifestSha256:'a'.repeat(64),trcSha256:'b'.repeat(64),motSha256:'c'.repeat(64),calibrationSha256:'d'.repeat(64)},
 quality:{status:'passed',mode:'kinematics'},time:{unit:'s',origin:'synchronized_trial_start'}});

test('legacy and provenance-bound JSON retain source times and missing markers',()=>{
 assert.equal(validateMotion(makeMotion()).frames[0].xyz[1],null);
 assert.equal(validateMotion(makeV2()).sessionId,'factory_session');
});

test('timestamp lookup follows nonuniform sample times, not nominal FPS',()=>{
 const m=validateMotion(makeMotion());
 for(const [t,want] of [[-1,2],[2,2],[2.09,2],[2.1,2.1],[2.3,2.1],[2.4,2.4],[99,2.4]])
  assert.equal(frameAtTime(m,t).t,want);
 assert.throws(()=>frameAtTime(m,NaN));
});

test('only angular coordinates convert radians to degrees',()=>{
 const kin=validateMotion(makeMotion()).kinematics;
 assert.ok(Math.abs(angleDegrees(kin,'knee_angle_r',2)-90)<1e-10);
 kin.inDegrees=true;kin.rows[0][1]=90;
 assert.equal(angleDegrees(kin,'knee_angle_r',2),90);
 assert.equal(angleDegrees(kin,'pelvis_tx',2),null);
 assert.equal(angleDegrees(kin,'missing',2),null);
 assert.equal(angleDegrees(kin,'knee_angle_r',20),null);
 assert.equal(angleDegrees(null,'knee_angle_r',2),null);
});

test('malformed shapes, units, time, columns and bone references fail visibly',()=>{
 const mutations=[
  d=>d.schema='unknown',d=>d.units='mm',d=>d.coordinateSystem='z_up',d=>d.fps=Infinity,
  d=>d.markers[1]='Hip',d=>d.bones=[[0,2]],d=>d.bones=[[0,0]],d=>d.bones=[[0,1.5]],
  d=>d.frames=[],d=>d.frames[0].xyz.pop(),d=>d.frames[0].xyz[0]=[1,2],
  d=>d.frames[0].xyz[0]=[1,NaN,3],d=>d.frames[1].t=2,d=>d.frames[1].t=1,
  d=>d.kinematics.inDegrees='no',d=>d.kinematics.rows[0][1]=Infinity,
  d=>d.kinematics.columns[2]='knee_angle_r',d=>d.kinematics.columns[2]='unknown_coordinate',
  d=>d.kinematics.columnTypes={knee_angle_r:'translation',pelvis_tx:'translation'},
  d=>d.kinematics.rows[0].pop()
 ];
 for(const mutate of mutations){const m=makeMotion();mutate(m);assert.throws(()=>validateMotion(m));}
});

test('v2 requires complete provenance, identity, quality and explicit marker-only state',()=>{
 const mutations=[
  d=>delete d.provenance,d=>d.provenance.trcSha256='bad',d=>delete d.provenance.calibrationSha256,
  d=>d.provenance.motSha256=null,d=>d.sessionId='../bad',d=>d.kind='unverified',
  d=>delete d.quality,d=>d.quality.status='failed',d=>d.time.unit='ms',
  d=>d.quality.mode='marker-only'
 ];
 for(const mutate of mutations){const m=makeV2();mutate(m);assert.throws(()=>validateMotion(m));}
 const markers=makeV2();markers.kinematics=null;markers.provenance.motSha256=null;markers.quality.mode='marker-only';
 assert.equal(validateMotion(markers).quality.mode,'marker-only');
 const dotted=makeV2();dotted.sessionId='factory.session-01';assert.ok(validateMotion(dotted));
});

test('distant and internally gapped MOT samples are rejected',()=>{
 for(const times of [[20,20.1,20.4],[2,20],[2,2.4]]){
  const m=makeMotion();m.frames.splice(2,0,{t:2.2,xyz:[[3,2,3],[4,5,6]]});m.kinematics.rows=times.map(t=>[t,1,.25]);
  assert.throws(()=>validateMotion(m));
 }
});

test('a MOT match exactly one source interval away is allowed',()=>{
 const m=makeMotion();m.kinematics.rows=[[2,1,.25],[2.4,1,.25]];
 assert.ok(validateMotion(m).kinematics);
});

test('native model coordinate units include spine, neck, translations and coupled radians',()=>{
 const fixture=JSON.parse(readFileSync(new URL('../../tests/factory_opensim_units.json',import.meta.url),'utf8'));
 const names=[...fixture.angular,...fixture.nativeRadians,...fixture.translations];
 const m=makeMotion();m.kinematics={columns:['time',...names],inDegrees:true,
  rows:[2,2.1,2.4].map(t=>[t,...names.map(name=>fixture.nativeRadians.includes(name)?Math.PI/2:fixture.translations.includes(name)?.25:90)])};
 const kin=validateMotion(m).kinematics;
 for(const name of fixture.angular)assert.equal(angleDegrees(kin,name,2),90);
 for(const name of fixture.nativeRadians)assert.ok(Math.abs(angleDegrees(kin,name,2)-90)<1e-9);
 for(const name of fixture.translations)assert.equal(angleDegrees(kin,name,2),null);
});

test('unit mappings and sampling tolerances cannot mislabel input values',()=>{
 for(const change of [k=>k.timeTolerance=-1,k=>k.columnUnits={knee_angle_r:'m',pelvis_tx:'m'}]){
  const m=makeMotion();change(m.kinematics);assert.throws(()=>validateMotion(m));
 }
});

test('the existing bundled demo remains readable',()=>{
 const demo=JSON.parse(readFileSync(new URL('../public/motion/demo.motion.json',import.meta.url),'utf8'));
 assert.equal(validateMotion(demo).frames.length,97);
});
