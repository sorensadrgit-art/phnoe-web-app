'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {addManualLabel, makeReference, importReference, orientCandidates,
  compareAnnotations, validateCandidates} =require('./gaitReviewLogic.cjs');

function data(role='cam01_trial'){
 return {
  schema:'kinelab.2d-gait-candidates.v1',
  test_only:true,role,source_sha256:'f'.repeat(64),fps:30,
  observed_frames:360,algorithm_version:'kinelab-t5-foot-extrema-2d-v1',
  candidate_count:5,classification:'UNVALIDATED_EVENT_CANDIDATES',
  candidates:[
   {id:role+':left:heel:max:30',role,side:'left',foot_point:'heel',extremum:'max',frame_index:30,event_type:'unassigned_extremum'},
   {id:role+':left:heel:max:32',role,side:'left',foot_point:'heel',extremum:'max',frame_index:32,event_type:'unassigned_extremum'},
   {id:role+':left:big_toe:min:50',role,side:'left',foot_point:'big_toe',extremum:'min',frame_index:50,event_type:'unassigned_extremum'},
   {id:role+':right:heel:max:60',role,side:'right',foot_point:'heel',extremum:'max',frame_index:60,event_type:'unassigned_extremum'},
   {id:role+':right:big_toe:min:79',role,side:'right',foot_point:'big_toe',extremum:'min',frame_index:79,event_type:'unassigned_extremum'}
  ],
 };
}

test('manual reference captures actual selected frame, side, event, never auto-populates',()=>{
 const referenceSource=data(), labels=[];
 const first=addManualLabel(labels,{frame_index:30,side:'left',event_type:'initial_contact'},referenceSource);
 assert.equal(first.length,1);
 assert.equal(first[0].time_seconds,1);
 assert.equal(labels.length,0);
 const second=addManualLabel(first,{frame_index:50,side:'left',event_type:'toe_off'},referenceSource);
 assert.equal(second.length,2);
 for(const wrong of [
  {frame_index:-1,side:'left',event_type:'toe_off'},
  {frame_index:360,side:'left',event_type:'toe_off'},
  {frame_index:30,side:'left',event_type:'unknown'},
  {frame_index:25.4,side:'right',event_type:'initial_contact'},
 ]){
  assert.throws(()=>addManualLabel(first,wrong,referenceSource));
 }
 assert.throws(()=>addManualLabel(first,{frame_index:30,side:'left',event_type:'initial_contact'},referenceSource));
});

test('explicit named reviewer and confirmation required before exporting',()=>{
 const source=data();
 const labels=addManualLabel([],{frame_index:30,side:'left',event_type:'initial_contact'},source);
 for(const args of [
  {reviewer:'',confirmed:true},
  {reviewer:'A',confirmed:true},
  {reviewer:'tester',confirmed:false},
 ]){
  assert.throws(()=>makeReference(source,labels,args));
 }
 assert.throws(()=>makeReference(source,[],{reviewer:'PT tester',confirmed:true}));
 const record=makeReference(source,labels,{reviewer:'PT tester',confirmed:true});
 assert.equal(record.annotation_origin,'human_observed_video_frames');
 assert.equal(record.source_sha256,source.source_sha256);
 assert.equal(record.status,'MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH');
 assert.equal(record.labels.length,1);
 assert.equal(record.labels[0].frame_index,30);
 assert.equal(record.clinical_accuracy_validated,false);
 assert.equal(record.algorithm_events_shown_during_annotation,false);
});

test('manual annotation imports refuse changed camera, hash, duplicate or status',()=>{
 const s=data(),labels=addManualLabel([],{frame_index:30,side:'left',event_type:'initial_contact'},s);
 const good=makeReference(s,labels,{reviewer:'test person',confirmed:true});
 assert.equal(importReference(good,s).labels.length,1);
 for(const changed of [
  {...good,role:'cam02_trial'},
  {...good,source_sha256:'a'.repeat(64)},
  {...good,labels:[good.labels[0],good.labels[0]]},
  {...good,annotation_origin:'automatic'},
  {...good,status:'CLINICALLY_VALIDATED'},
  {...good,operator_confirmed:false}
 ])assert.throws(()=>importReference(changed,s));
});

test('provisional screen orientation cannot be guessed',()=>{
 const source=data();
 assert.throws(()=>orientCandidates(source,'unknown'));
 const right=orientCandidates(source,'right');
 assert.equal(right.filter(c=>c.event_type==='candidate_initial_contact').length,3);
 assert.equal(right.filter(c=>c.event_type==='candidate_toe_off').length,2);
 const left=orientCandidates(source,'left');
 assert.equal(left.filter(c=>c.event_type!=='unassigned_extremum').length,0);
 assert.equal(source.candidates[0].event_type,'unassigned_extremum');
});

test('agreement is one-to-one, narrow and described as manual agreement, not accuracy',()=>{
 const source=data();
 const labels=[
  {frame_index:31,side:'left',event_type:'initial_contact',time_seconds:31/30},
  {frame_index:48,side:'left',event_type:'toe_off',time_seconds:48/30},
  {frame_index:60,side:'right',event_type:'initial_contact',time_seconds:2},
 ];
 const ref=makeReference(source,labels,{reviewer:'observer',confirmed:true});
 const result=compareAnnotations(source,ref,'right',3);
 assert.equal(result.matched_count,3);
 assert.equal(result.reference_count,3);
 assert.equal(result.candidate_count,5);
 assert.equal(result.precision,3/5);
 assert.equal(result.recall,1);
 assert.equal(result.mean_absolute_error_frames,1);
 assert.equal(result.clinical_accuracy_validated,false);
 assert.equal(result.status,'EXPLORATORY_REVIEWER_AGREEMENT_ONLY');
});

test('reference absent never produces perfect scores',()=>{
 const result=compareAnnotations(data(),null,'right',3);
 assert.equal(result.status,'NO_MANUAL_REFERENCE');
 assert.equal(result.precision,null);
 assert.equal(result.recall,null);
 assert.equal(result.matched_count,0);
});

test('wrong direction, scope and tolerance are rejected for comparison',()=>{
 const source=data(),ref=makeReference(source,[
  {frame_index:30,side:'left',event_type:'initial_contact'}
 ],{reviewer:'observer',confirmed:true});
 assert.throws(()=>compareAnnotations(source,ref,'unknown',3));
 assert.throws(()=>compareAnnotations(source,ref,'right',-1));
 assert.throws(()=>compareAnnotations(source,{...ref,source_sha256:'0'.repeat(64)},'right',3));
 assert.throws(()=>compareAnnotations(data('cam02_trial'),ref,'right',3));
});

test('reject malformed candidate report or fabricated event label',()=>{
 for(const changed of [
  {...data(),test_only:false},
  {...data(),role:'cam03_trial'},
  {...data(),candidate_count:9},
  {...data(),candidates:[{...data().candidates[0],frame_index:400}]},
  {...data(),candidates:[{...data().candidates[0],event_type:'initial_contact'}]},
 ]){
  assert.throws(()=>validateCandidates(changed));
 }
});
