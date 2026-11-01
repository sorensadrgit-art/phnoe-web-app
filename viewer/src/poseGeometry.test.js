import test from 'node:test';
import assert from 'node:assert/strict';
import {calculateAngle2D,calculateAngle3D,calculateKneeFlexion,calculateTrunkLean,normalizePoint,computePoseKinematics} from './liveKinematics.js';

test('missing depth and degenerate joints never fabricate angles',()=>{
  const a={x:0,y:0}, b={x:1,y:1};
  assert.equal(normalizePoint(a).z,null);
  assert.equal(calculateAngle2D(a,a,b),null);
  assert.equal(calculateAngle3D(a,b,{x:2,y:2}),null);
  assert.equal(calculateKneeFlexion(a,a,b),null);
  assert.equal(calculateTrunkLean(a,a),null);
  assert.equal(normalizePoint({x:1,y:1,z:Infinity}),null);
});

const pose=()=>{
  const p=Array(33).fill(null);
  for(const [i,x,y] of [[11,.4,.1],[12,.6,.1],[23,.4,.2],[24,.6,.2],[25,.5,.4],[26,.7,.4],[27,.4,.6],[28,.6,.6]])p[i]={x,y,z:null,visibility:.9};
  return p;
};
const image={width:800,height:400,minConfidence:.6};
test('image-plane angles use pixel aspect ratio and preserve anatomical sides under display mirroring',()=>{
  const p=pose(); const a=computePoseKinematics(p,image);
  assert.equal(a.leftKneeFlexion,90);
  const mirrored=p.map(p=>p?{...p,x:1-p.x}:null);
  assert.equal(computePoseKinematics(mirrored,image).leftKneeFlexion,a.leftKneeFlexion);
  assert.equal(a.leftValgus,null,'single unknown camera plane is not anatomical valgus');
});
test('occluded or nonfinite landmarks leave dependent metrics unavailable',()=>{
  const p=pose();p[25].visibility=.1;p[12].x=NaN;
  const a=computePoseKinematics(p,image);
  assert.equal(a.leftKneeFlexion,null);assert.equal(a.trunkLean,null);assert.equal(a.kneeSymmetry,null);
  assert.equal(a.rightKneeFlexion,90);
  p[26].visibility=undefined;
  assert.equal(computePoseKinematics(p,image).rightKneeFlexion,null);
});
