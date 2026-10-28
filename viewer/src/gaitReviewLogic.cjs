/* Portable UMD logic. CommonJS tests and offline file:// HTML share same code.
 * Manual annotation agreement is NOT clinical or instrumented event accuracy.
 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.KineLabGaitReview=api;
})(typeof window!=='undefined'?window:globalThis,function(){
 'use strict';
 const ROLE_SET=new Set(['cam01_trial','cam02_trial']);
 const SIDES=new Set(['left','right']);
 const EVENT_TYPES=new Set(['initial_contact','toe_off']);
 const SOURCE_SCHEMA='kinelab.2d-gait-candidates.v1';
 const REFERENCE_SCHEMA='kinelab.manual-gait-reference.v1';
 const HEX64=/^[a-f0-9]{64}$/;
 const fail=what=>{throw new Error('Unverified gait review: '+what)};
 const finite=v=>typeof v==='number'&&Number.isFinite(v);
 const require=(ok,text)=>{if(!ok)fail(text)};

 function validateCandidates(source){
   require(source&&typeof source==='object'&&!Array.isArray(source)&&
    source.schema===SOURCE_SCHEMA&&source.test_only===true&&
    source.classification==='UNVALIDATED_EVENT_CANDIDATES',
    'missing unvalidated candidate contract');
   require(ROLE_SET.has(source.role)&&HEX64.test(source.source_sha256)&&
    source.fps===30&&Number.isInteger(source.observed_frames)&&
    source.observed_frames>0&&source.observed_frames<=24000,
    'invalid camera/source-frame provenance');
   require(typeof source.algorithm_version==='string'&&
    source.algorithm_version.startsWith('kinelab-t5-'),
    'unsupported detector version');
   require(Array.isArray(source.candidates)&&
    source.candidate_count===source.candidates.length,
    'candidate count mismatch');
   const known=new Set();
   for(const e of source.candidates){
     require(e&&typeof e==='object'&&typeof e.id==='string'&&
      !known.has(e.id)&&e.role===source.role&&
      SIDES.has(e.side)&&['heel','big_toe'].includes(e.foot_point)&&
      ['max','min'].includes(e.extremum)&&
      Number.isInteger(e.frame_index)&&e.frame_index>=0&&
      e.frame_index<source.observed_frames&&
      e.event_type==='unassigned_extremum',
      'invalid or prematurely classified gait extrema');
     known.add(e.id);
   }
   return source;
 }

 function normalizeLabel(label,source){
   require(label&&typeof label==='object'&&
    Number.isInteger(label.frame_index)&&label.frame_index>=0&&
    label.frame_index<source.observed_frames&&
    SIDES.has(label.side)&&EVENT_TYPES.has(label.event_type),
    'manual annotation must have source frame, body side and event kind');
   return {frame_index:label.frame_index,time_seconds:Number((label.frame_index/30).toFixed(6)),
    side:label.side,event_type:label.event_type};
 }

 function addManualLabel(labels,label,source){
   validateCandidates(source);
   require(Array.isArray(labels),'invalid annotations collection');
   const mark=normalizeLabel(label,source);
   const items=labels.map(item=>normalizeLabel(item,source));
   require(!items.some(e=>e.frame_index===mark.frame_index&&
    e.side===mark.side&&e.event_type===mark.event_type),'duplicate annotation');
   return [...items,mark].sort((a,b)=>a.frame_index-b.frame_index||
    a.side.localeCompare(b.side)||a.event_type.localeCompare(b.event_type));
 }

 function makeReference(source,labels,{reviewer,confirmed}={}){
   validateCandidates(source);
   require(typeof reviewer==='string'&&reviewer.trim().length>=2&&
    reviewer.trim().length<=90,'reviewer initials/name required');
   require(confirmed===true,'explicit operator confirmation required');
   require(Array.isArray(labels)&&labels.length>0&&labels.length<=1000,
    'manual reference requires reviewed events; never invent labels');
   let valid=[];
   for(const mark of labels)valid=addManualLabel(valid,mark,source);
   return {
    schema:REFERENCE_SCHEMA,test_only:true,
    status:'MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH',
    role:source.role,source_sha256:source.source_sha256,
    fps:30,frames:source.observed_frames,
    annotation_origin:'human_observed_video_frames',
    operator_confirmed:true,reviewer:reviewer.trim(),
    algorithm_events_shown_during_annotation:false,
    clinical_accuracy_validated:false,
    recorded_at_utc:new Date().toISOString(),labels:valid,
    limitations:'Self-reported video-frame events. Browser seek may differ from the actual decoded frame; no instrumented gait event reference or clinical accuracy.'
   };
 }

 function importReference(value,source){
   validateCandidates(source);
   require(value&&typeof value==='object'&&!Array.isArray(value)&&
    value.schema===REFERENCE_SCHEMA&&value.test_only===true&&
    value.status==='MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH'&&
    value.clinical_accuracy_validated===false&&
    value.operator_confirmed===true&&
    value.annotation_origin==='human_observed_video_frames'&&
    value.algorithm_events_shown_during_annotation===false&&
    value.role===source.role&&value.source_sha256===source.source_sha256&&
    value.fps===30&&value.frames===source.observed_frames&&
    typeof value.reviewer==='string'&&value.reviewer.trim().length>=2,
    'manual reference belongs to a different or unverified source');
   require(Array.isArray(value.labels)&&value.labels.length>0&&value.labels.length<=1000,
    'manual reference has no checked annotations');
   let labels=[];
   for(const label of value.labels){
     const clean=normalizeLabel(label,source);
     require(finite(label.time_seconds)&&Math.abs(clean.time_seconds-label.time_seconds)<.0001,
      'manual reference timeline does not match original video frame');
     labels=addManualLabel(labels,label,source);
   }
   return {...value,labels};
 }

 function orientCandidates(source,direction){
   validateCandidates(source);
   require(direction==='left'||direction==='right',
    'explicit operator screen-forward direction required; no guessed gait contacts');
   const heelPeak=direction==='right'?'max':'min';
   const toePeak=direction==='right'?'min':'max';
   return source.candidates.map(e=>({...e,
    event_type:e.foot_point==='heel'&&e.extremum===heelPeak?
      'candidate_initial_contact':
      e.foot_point==='big_toe'&&e.extremum===toePeak?
        'candidate_toe_off':'unassigned_extremum',
    assumed_forward_screen_direction:direction,
    human_confirmed:false,
   }));
 }

 function compareAnnotations(source,manual,direction,toleranceFrames=3){
   validateCandidates(source);
   require(Number.isInteger(toleranceFrames)&&toleranceFrames>=0&&toleranceFrames<=15,
    'invalid comparison tolerance');
   const events=orientCandidates(source,direction).filter(
    e=>e.event_type==='candidate_initial_contact'||e.event_type==='candidate_toe_off');
   if(manual===null||manual===undefined)return {
    status:'NO_MANUAL_REFERENCE',candidate_count:events.length,
    reference_count:0,matched_count:0,precision:null,recall:null,
    mean_absolute_error_frames:null,tolerance_frames:toleranceFrames,
    clinical_accuracy_validated:false,
   };
   const reference=importReference(manual,source);
   const options=[];
   for(const [i,label] of reference.labels.entries()){
     for(const [j,candidate] of events.entries()){
       if(candidate.side!==label.side||
          candidate.event_type!=='candidate_'+label.event_type)continue;
       const error=Math.abs(candidate.frame_index-label.frame_index);
       if(error<=toleranceFrames)options.push({error,i,j});
     }
   }
   options.sort((a,b)=>a.error-b.error||a.i-b.i||a.j-b.j);
   const usedReference=new Set(),usedCandidate=new Set(),errors=[];
   for(const option of options){
     if(usedReference.has(option.i)||usedCandidate.has(option.j))continue;
     usedReference.add(option.i);usedCandidate.add(option.j);errors.push(option.error);
   }
   const n=errors.length;
   return {
    status:'EXPLORATORY_REVIEWER_AGREEMENT_ONLY',
    candidate_count:events.length,reference_count:reference.labels.length,
    matched_count:n,
    unmatched_reference_count:reference.labels.length-n,
    unmatched_candidate_count:events.length-n,
    precision:events.length?n/events.length:null,
    recall:n/reference.labels.length,
    mean_absolute_error_frames:errors.length?errors.reduce((a,b)=>a+b,0)/n:null,
    tolerance_frames:toleranceFrames,absolute_frame_errors:errors.sort((a,b)=>a-b),
    clinical_accuracy_validated:false,
    reference_is_instrumented_ground_truth:false,
    interpretation:'Exploratory agreement with human-observed browser-video annotations only, not physical or clinical measurement accuracy.',
   };
 }

 return {validateCandidates,addManualLabel,makeReference,importReference,
         orientCandidates,compareAnnotations};
});
