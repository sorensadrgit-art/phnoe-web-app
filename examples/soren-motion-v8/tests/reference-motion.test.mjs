import assert from 'node:assert/strict';
import test from 'node:test';
import {surfacePoint,projectPoint,projectCard,stepPosition,softTarget,motionSpeed,WheelImpulse,flightEase,reference} from '../src/resume/reference-motion.mjs';

test('resting ribbon has opposite signed lobes and a banked cross-section',()=>{
  assert.ok(surfacePoint(-400,0,720).z>0);
  assert.ok(surfacePoint(400,0,720).z<0);
  assert.notEqual(surfacePoint(0,200,720).z,surfacePoint(0,-200,720).z);
  assert.equal(reference.fov,53.4);
});
test('velocity rears the left side and twists both edges without moving x',()=>{
  const idle=surfacePoint(-600,0,720),moving=surfacePoint(-600,0,720,.7);
  assert.equal(idle.x,moving.x);
  assert.ok(moving.y-idle.y>40);
  assert.ok(Math.abs(idle.z-moving.z)>50);
  assert.ok(motionSpeed(0)===0&&motionSpeed(550)>.5&&motionSpeed(5000)<1);
});
test('semantic hit regions enclose the same surface at rest and during a flick',()=>{
  for(const speed of [0,.2,.7,1]) for(const left of [-300,400,1100]) {
    const box=projectCard(left,254,666,392,1440,900,speed);
    assert.equal(box.clip.split(',').length,66);
    for(let n=0;n<=32;n++)for(const y of [196,-196]) {
      const p=projectPoint(left+666*n/32-720,y,1440,900,speed);
      assert.ok(p.x>=box.left-.001&&p.x<=box.left+box.width+.001);
      assert.ok(p.y>=box.top-.001&&p.y<=box.top+box.height+.001);
    }
  }
});
test('wheel impulses preserve gain, discrete-wheel easing and trackpad response',()=>{
  const wheel=new WheelImpulse();wheel.push({deltaY:550,deltaX:0,deltaMode:0,timeStamp:1000},900);
  assert.equal(wheel.pending,1375);
  assert.ok(Math.abs(wheel.step(1000/60)-302.5)<1e-9);
  const trackpad=new WheelImpulse();
  trackpad.push({deltaY:4,deltaX:0,deltaMode:0,timeStamp:10},900);
  assert.equal(trackpad.step(1000/60),5);
  assert.equal(stepPosition(0,100,1000/60),10);
  assert.equal(stepPosition(0,100,1000/120),5);
  assert.ok(Math.abs(softTarget(0,10000,1440))<1440);
});
test('section flight easing is continuous and reaches each measured segment knot',()=>{
  assert.equal(flightEase(0),0);assert.equal(flightEase(1),1);
  assert.ok(Math.abs(flightEase(.157)-.29)<.00001);
  assert.ok(Math.abs(flightEase(.348)-.884)<.00001);
  let previous=0;
  for(let n=1;n<=1000;n++){const value=flightEase(n/1000);assert.ok(value>=previous);previous=value;}
});
