import test from 'node:test';
import assert from 'node:assert/strict';
import {createExerciseTracker,EXERCISE_TYPES,PHASES} from './exerciseStateMachine.js';
const sample=(left,right=left)=>({leftKneeFlexion:left,rightKneeFlexion:right,trunkLean:0,leftValgus:0,rightValgus:0,kneeSymmetry:100,ankleHeightDifference:0});
const make=(type=EXERCISE_TYPES.SQUAT,extra={})=>createExerciseTracker(type,{smoothingWindow:1,minDurationMs:100,...extra});
const squat=(tracker,start=1000)=>[10,35,85,60,10].forEach((value,i)=>tracker.update(sample(value),start+200*i));

test('missing, stale, nonmonotonic and paused frames cannot finish an incomplete rep',()=>{
  for(const interrupt of [t=>t.update(null,1700),t=>t.update({leftKneeFlexion:null,rightKneeFlexion:10},1700),t=>t.update(sample(10),1500),t=>t.update(sample(10),9000),t=>t.pause()]){
    const t=make();[10,35,85,60].forEach((v,i)=>t.update(sample(v),1000+200*i));
    interrupt(t);t.update(sample(10),9200);assert.equal(t.getState().repCount,0);
  }
});
test('completed sets and reps are immutable and finish is idempotent',()=>{
  const t=make();squat(t);const state=t.getState();
  assert.throws(()=>{state.reps[0].valid=false;},TypeError);
  const summary=t.finishSet();assert.equal(summary.totalReps,1);
  assert.throws(()=>summary.reps.push({}),TypeError);
  squat(t,2500);assert.strictEqual(t.finishSet(),summary);assert.equal(t.getState().repCount,1);
  t.reset();assert.equal(t.finishSet().averageSymmetry,null);
});
test('partial form metrics cannot produce a valid assessed rep or perfect symmetry',()=>{
  const t=make();[10,35,85,60,10].forEach((v,i)=>t.update({leftKneeFlexion:v,rightKneeFlexion:v},1000+200*i));
  const summary=t.finishSet();assert.equal(summary.totalReps,1);assert.equal(summary.validReps,0);
  assert.equal(summary.averageSymmetry,null);
});
test('knee extension counts left flexed-extended-flexed cycle despite bent right knee',()=>{
  const t=make(EXERCISE_TYPES.KNEE_EXTENSION);
  [85,50,10,40,85].forEach((v,i)=>t.update(sample(v,80),1000+200*i));
  assert.equal(t.getState().repCount,1);
  assert.ok(t.getState().reps[0].peakDepth>=75);
});
test('unilateral lunge does not switch the active side or assess load from angle symmetry',()=>{
  const t=make(EXERCISE_TYPES.LUNGE);[10,35,85,60,10].forEach((v,i)=>t.update({...sample(v,10),kneeSymmetry:5},1000+200*i));
  assert.equal(t.getState().repCount,1);assert.equal(t.getState().validRepCount,1);
});
test('balance requires a visible raised ankle and excludes interruption time',()=>{
  const t=make(EXERCISE_TYPES.BALANCE);
  t.update(sample(10,60),1000);assert.equal(t.getState().phase,PHASES.READY);
  t.update({...sample(10,60),ankleHeightDifference:.3},1100);
  t.update({...sample(10,60),ankleHeightDifference:.3},1300);
  assert.equal(t.getState().balanceHoldSeconds,.2);
  t.pause();t.update(sample(10,10),9000);assert.equal(t.getState().repCount,0);
});
test('projected camera cycles are never rated as clinically valid form',()=>{
  const t=make(EXERCISE_TYPES.SQUAT,{projectionOnly:true});squat(t);
  assert.equal(t.getState().repCount,1);assert.equal(t.getState().validRepCount,null);
  assert.equal(t.getState().reps[0].valid,null);
});
