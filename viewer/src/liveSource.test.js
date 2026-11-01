import {after, before, test} from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {createExerciseTracker,EXERCISE_TYPES} from './exerciseStateMachine.js';

// Exercise the actual React presentation without opening a camera or a server port.
let vite, Studio, Reports, Summary, appendPreviewFrame;
before(async()=>{
 vite=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),
  server:{middlewareMode:true,hmr:false,ws:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom'});
 const studio=await vite.ssrLoadModule('/src/LiveTrackerStudio.jsx');
 Studio=studio.default;appendPreviewFrame=studio.appendPreviewFrame;
 Reports=(await vite.ssrLoadModule('/src/ReportStudio.jsx')).default;
 Summary=(await vite.ssrLoadModule('/src/LiveSetSummaryModal.jsx')).default;
});
after(async()=>{await vite?.close();});

test('illustrative preview frames stay bounded and disclose omitted samples',()=>{
 assert.equal(typeof appendPreviewFrame,'function');
 const frames=[];let omitted=0;
 for(let i=0;i<10000;i++)omitted+=appendPreviewFrame(frames,{t:i});
 assert.equal(frames.length,600);assert.equal(omitted,9400);
 assert.equal(frames[0].t,9400);assert.equal(frames.at(-1).t,9999);
});

test('camera starts unavailable without automatic acquisition or measured finish action',()=>{
 const html=renderToStaticMarkup(React.createElement(Studio));
 assert.match(html,/REAL CAMERA/);
 assert.match(html,/CAMERA_NOT_STARTED/);
 assert.match(html,/Start local camera/);
 assert.match(html,/3D depth UNAVAILABLE; muscle activity NOT MEASURED/);
 assert.match(html,/<button[^>]*disabled=""[^>]*>Finish Synthetic Set<\/button>/);
 assert.doesNotMatch(html,/<canvas|Save to Sessions|PATIENT \/ SUBJECT/);
});

test('cloud synthetic mode remains explicitly separate and finishable',()=>{
 const html=renderToStaticMarkup(React.createElement(Studio,{demoMode:true}));
 assert.match(html,/SYNTHETIC TEST ONLY/);
 assert.doesNotMatch(html,/CAMERA PREVIEW ONLY|PATIENT \/ SUBJECT/);
 assert.match(html,/<button(?=[^>]*title="Finish synthetic test set")[^>]*>Finish Synthetic Set<\/button>/);
});

test('synthetic summary offers export without a patient field or save callback',()=>{
 const html=renderToStaticMarkup(React.createElement(Summary,{
  summary:{totalReps:0,validReps:0,reps:[],faultsLog:[]},exerciseType:'squats'}));
 assert.match(html,/SYNTHETIC TEST SUMMARY/);
 assert.match(html,/Server saving and clinical reporting are unavailable/);
 assert.doesNotMatch(html,/PATIENT \/ SUBJECT RECORD ID|Save to Sessions/);
});

test('empty synthetic summary cannot imply perfect symmetry or assessed form',()=>{
 const html=renderToStaticMarkup(React.createElement(Summary,{
  summary:{totalReps:0,validReps:0,averageDepth:null,bestDepth:null,averageSymmetry:null,reps:[],faultsLog:[]}}));
 assert.match(html,/UNAVAILABLE/);
 assert.doesNotMatch(html,/Clean form|Mild Asymmetry|\(Balanced\)/);
 // Assert on the rendered symmetry value/label itself, not unrelated CSS such as width:100%.
 assert.match(html,/Bilateral Movement Symmetry<\/span><span[^>]*>UNAVAILABLE<\/span>/);
 assert.doesNotMatch(html,/\d+(?:\.\d+)?% \(/);
});

const renderSummary=summary=>renderToStaticMarkup(React.createElement(Summary,{summary}));

test('nonfinite and malformed summary values render UNAVAILABLE instead of numbers or quality labels',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:NaN,validReps:'3',averageDepth:Infinity,bestDepth:'90',
  targetDepth:undefined,averageSymmetry:-Infinity,durationSeconds:NaN,faultsLog:null});
 assert.ok((html.match(/UNAVAILABLE/g)||[]).length>=6);
 assert.doesNotMatch(html,/NaN|Infinity|null|>°|Target: °|Clean form|No synthetic test faults|Balanced|Asymmetry/);
 assert.match(html,/SYNTHETIC TEST SUMMARY · NOT MEASURED/);
});

test('reps with unassessed form never claim clean form from an empty fault history',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:2,validReps:null,averageDepth:84,bestDepth:88,
  targetDepth:80,averageSymmetry:null,durationSeconds:12,faultsLog:[]});
 assert.match(html,/Form assessment UNAVAILABLE/);
 assert.match(html,/Clean count UNAVAILABLE/);
 assert.doesNotMatch(html,/Clean form|No synthetic test faults|Balanced|Asymmetry/);
 assert.match(html,/>84°</);assert.match(html,/>88°</);
});

test('finite symmetry without assessed repetitions carries no quality rating',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:2,validReps:null,averageDepth:84,bestDepth:88,
  targetDepth:80,averageSymmetry:100,durationSeconds:12,faultsLog:[]});
 assert.match(html,/>100% \(rating UNAVAILABLE/);
 assert.match(html,/repetitions were not assessed/);
 assert.doesNotMatch(html,/Balanced|Mild Asymmetry/);
});

test('malformed fault history renders UNAVAILABLE instead of a no-fault claim',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:3,validReps:3,averageDepth:86,bestDepth:90,
  targetDepth:80,averageSymmetry:95,durationSeconds:20,faultsLog:[null]});
 assert.match(html,/Form Fault Diagnostics \(UNAVAILABLE\)/);
 assert.match(html,/fault history missing or malformed/);
 assert.doesNotMatch(html,/No synthetic test faults|Clean form/);
});

test('out-of-range depths, symmetry and fault counts cannot render as valid evidence',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:1,validReps:1,averageDepth:999,bestDepth:999,
  targetDepth:80,averageSymmetry:500,durationSeconds:12,faultsLog:[{fault:'KNEE_VALGUS',count:20,percentage:500}]});
 assert.doesNotMatch(html,/>999|500%|20 rep|Balanced|Mild Asymmetry/);
 assert.match(html,/Form Fault Diagnostics \(UNAVAILABLE\)/);
 assert.match(html,/fault history missing or malformed/);
});

test('balance hold seconds cannot exceed elapsed test time',()=>{
 const html=renderSummary({exerciseType:'balance',totalReps:1,validReps:1,averageDepth:9999,bestDepth:9999,
  targetDepth:30,averageSymmetry:null,durationSeconds:10,faultsLog:[]});
 assert.doesNotMatch(html,/>9999/);
 assert.match(html,/UNAVAILABLE/);
});
test('valid squat summary keeps finite values, fault counts and the synthetic label',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:2,validReps:1,averageDepth:85.5,bestDepth:92,
  targetDepth:80,averageSymmetry:90,durationSeconds:75,faultsLog:[{fault:'KNEE_VALGUS',count:1,percentage:50}]});
 assert.match(html,/SQUATS PERFORMANCE/);
 assert.match(html,/1 clean \(50%\)/);assert.match(html,/>85.5°</);assert.match(html,/>92°</);
 assert.match(html,/Target: 80°/);assert.match(html,/>1:15</);assert.match(html,/90% \(Balanced\)/);
 assert.match(html,/KNEE VALGUS/);assert.match(html,/1 rep \(50%\)/);
 assert.doesNotMatch(html,/UNAVAILABLE|Clean form/);
 assert.match(html,/Export JSON/);assert.match(html,/Start New Set/);
 assert.doesNotMatch(html,/PATIENT \/ SUBJECT RECORD ID|Save to KineLab Sessions/);
});

test('explicit zero values remain values rather than becoming unavailable',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:1,validReps:0,averageDepth:0,bestDepth:0,
  targetDepth:80,averageSymmetry:0,durationSeconds:0,faultsLog:[{fault:'INSUFFICIENT_DEPTH',count:1,percentage:100}]});
 assert.match(html,/0 clean \(0%\)/);assert.match(html,/>0°</);assert.match(html,/>0:00</);
 assert.match(html,/>0% \(Mild Asymmetry\)</);assert.match(html,/INSUFFICIENT DEPTH/);
 assert.doesNotMatch(html,/UNAVAILABLE/);
});

test('flag-free synthetic reps are not described as clinically clean form',()=>{
 const html=renderSummary({exerciseType:'squats',totalReps:3,validReps:3,averageDepth:86,bestDepth:90,
  targetDepth:80,averageSymmetry:95,durationSeconds:20,faultsLog:[]});
 assert.match(html,/No synthetic test faults flagged in 3 completed reps/);
 assert.match(html,/not a clinical form assessment/);
 assert.doesNotMatch(html,/Clean form/);
});

test('balance summary uses hold seconds from the tracker and never degrees or symmetry ratings',()=>{
 const tracker=createExerciseTracker(EXERCISE_TYPES.BALANCE,{smoothingWindow:1,minDurationMs:100});
 for(let t=1000;t<=2000;t+=100)tracker.update({leftKneeFlexion:10,rightKneeFlexion:60,trunkLean:0,leftValgus:0,
  rightValgus:0,kneeSymmetry:100,ankleHeightDifference:.3},t);
 const summary=tracker.finishSet();
 assert.equal(summary.totalReps,1);
 const html=renderSummary(summary);
 assert.match(html,new RegExp(`>${summary.bestDepth} s<`));
 assert.match(html,new RegExp(`Target: ${summary.targetDepth} s`));
 assert.doesNotMatch(html,/°|Balanced|Asymmetry/);
 assert.match(html,/not assessed for this exercise/);
});
test('unverified inventory disables both generation and archived download',()=>{
 const html=renderToStaticMarkup(React.createElement(Reports,{
  sessions:[{id:'fixture',kind:'unknown',evidence_status:'unverified'}],selectedSession:'fixture',
  reports:[{key:'exports/old.pdf',filename:'old.pdf',bytes:12,type:'pdf'}],backups:[]}));
 assert.match(html,/EVIDENCE_UNVERIFIED/);
 assert.match(html,/<button[^>]*disabled=""[^>]*>Generate Offline Research Reports<\/button>/);
 assert.match(html,/<button[^>]*disabled=""[^>]*>Download PDF<\/button>/);
});
