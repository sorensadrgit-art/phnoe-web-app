import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import MotionApp from './MotionApp.jsx';
import EvidencePassport from './EvidencePassport.jsx';
import GuidedCaptureWizard from './GuidedCaptureWizard.jsx';
import SessionMetadataSetup from './SessionMetadataSetup.jsx';
import {METADATA_FIELDS,currentMetadataState,isValidSessionMetadata,metadataConfirmationMatches,metadataRevisionReceiptMatches,newOperationId} from './sessionMetadataSetup.js';
import ReportStudio from './ReportStudio.jsx';
import {evidenceMetadataIdentity,checkedContext,checkedReceipt} from './EvidenceExportPanel.jsx';
import {boundedJsonResponse,API_ERROR_JSON_LIMIT} from './boundedJsonResponse.js';
import LiveTrackerStudio from './LiveTrackerStudio.jsx';
import {NAV_ITEMS,STAGES,formatSession,roleStatus,apiSessionPath,readAccessToken,safeMetricValue,sessionDisplayBadge,isSessionActive,EXERCISE_TYPES,DEFAULT_PRESETS,formatExerciseMetric,formatStaleNotice,isStale} from './unifiedModel.js';

const API='/api/v1';
const TEST_ID='caliscope-walking-test-20261027';
const ROLE_NAMES={
 cam01_intrinsics:'Phone · Intrinsic calibration',cam02_intrinsics:'Webcam · Intrinsic calibration',
 cam01_board:'Phone · Board view',cam02_board:'Webcam · Board view',
 cam01_trial:'Phone · Movement trial',cam02_trial:'Webcam · Movement trial',
};
const NAV_SIGNS={
 overview:'◈',live:'⚡',sessions:'▦',capture:'◉',processing:'◎',motion:'◇',analysis:'⌁',reports:'▤',diagnostics:'⚙',
};
const dateMeta='Prototype / research only • Physical measurement accuracy unverified';

function Pill({children,tone='neutral'}){
 return <span className={'uw-pill uw-pill-'+tone}>{children}</span>;
}
function Box({children,className=''}){return <section className={'uw-card '+className}>{children}</section>}
function CardHeading({eyebrow,heading,detail,action}){
 return <div className="uw-card-header">
  <div><div className="uw-overline">{eyebrow}</div><h3>{heading}</h3>
   {detail&&<p>{detail}</p>}</div>{action}
 </div>;
}
function Notice({message,onClose}){
 if(!message)return null;
 return <div className={'uw-toast '+(message.type==='error'?'uw-error':'uw-info')} role="status">
  <span>{message.text}</span><button aria-label="Dismiss message" onClick={onClose}>×</button>
 </div>;
}
function EmptyState({headline,detail}){
 return <div className="uw-empty"><span aria-hidden="true">◇</span><strong>{headline}</strong>
  <p>{detail}</p></div>;
}
function Field({label,children}){return <label className="uw-field"><span>{label}</span>{children}</label>;}

export default function UnifiedApp(){
 const token=useMemo(()=>readAccessToken(window.location.hash),[]);
 const activeToken=useMemo(()=>{
  return token || (typeof localStorage!=='undefined'&&localStorage.getItem('kinelab_t6_token')) || '';
 },[token]);
 const [view,setViewState]=useState(()=>{
  try{return localStorage.getItem('kinelab_active_tab')||'overview'}catch{return 'overview'}
 });
 const setView=useCallback(next=>{
  setViewState(next);
  try{localStorage.setItem('kinelab_active_tab',next)}catch{}
 },[]);
 const [sessions,setSessions]=useState([]);
 const [recordingBusy,setRecordingBusy]=useState(false);
 const [selected,setSelectedState]=useState(()=>{
  try{return localStorage.getItem('kinelab_selected_session')||''}catch{return ''}
 });
  const evidenceOperations=useRef(new Set());
  const selectedRef=useRef(selected);
  const selectionEpoch=useRef(0);
  const selectedRequest=useRef({sequence:0,controller:null});
  const sessionsRequest=useRef(0);
 const setSelected=useCallback(next=>{
   const val=typeof next==='function'?next(selectedRef.current):next;
   if(val!==selectedRef.current){
    selectedRef.current=val;selectionEpoch.current++;
    for(const controller of evidenceOperations.current)controller.abort();
    selectedRequest.current.controller?.abort();
    setDetail(null);setPassport(null);setReports([]);setJob(null);setCamera(null);setRecovery(null);setLastPoll('');
   }
   try{localStorage.setItem('kinelab_selected_session',val)}catch{}
   setSelectedState(val);
 },[]);
 const [connected,setConnected]=useState(true);
 const [detail,setDetail]=useState(null);
 const [passport,setPassport]=useState(null);
 const [job,setJob]=useState(null);
 const [camera,setCamera]=useState(null);
 const [reports,setReports]=useState([]);
 const [analysis,setAnalysis]=useState(null);
 const [recovery,setRecovery]=useState(null);
 const [newId,setNewId]=useState('');
 const [operator,setOperator]=useState('');
 const [boardMm,setBoardMm]=useState('');
 const [loading,setLoading]=useState(true);
 const [busy,setBusy]=useState('');
 const [notice,setNotice]=useState(null);
 const [lastPoll,setLastPoll]=useState('');
 const [lastRefreshedMs,setLastRefreshedMs]=useState(null);
 const [fetchError,setFetchError]=useState(null);
 const [nowTick,setNowTick]=useState(()=>Date.now());
 useEffect(()=>{
  const interval=setInterval(()=>setNowTick(Date.now()),1000);
  return ()=>clearInterval(interval);
 },[]);
 const inputRefs=useRef({});
 const correctionAttempt=useRef(null);
 const sessionsRef=useRef(sessions);
 const show=(text,type='info')=>setNotice({text:String(text),type});

  const api=useCallback(async(path,{method='GET',body=null,binary=false,signal}={})=>{
  const tok=activeToken;
  if(!tok)throw Error('Open KineLab PT using its single desktop icon to authorize the local workspace.');
  const headers={Authorization:'Bearer '+tok};
  if(!binary && body!==null)headers['Content-Type']='application/json';
  if(binary){headers['Content-Type']='video/mp4';headers['X-KineLab-Consent']='yes';}
   const response=await fetch(path,{method,headers,signal,
   body:body===null?undefined:(binary?body:JSON.stringify(body)),cache:'no-store'});
  if(!response.ok){
   let msg='Local service rejected this action (HTTP '+response.status+')';
   try{const result=await boundedJsonResponse(response,{maxBytes:API_ERROR_JSON_LIMIT,signal});if(typeof result?.error==='string')msg=result.error}catch{/* keep honest status */}
   const failure=Error(msg);failure.status=response.status;throw failure;
  }
  return response;
 },[activeToken]);
 const json=useCallback(async(path,options)=>await (await api(path,options)).json(),[api]);
 const evidenceExportRequest=useCallback(async(sid,identity,action,body,{signal,operation}={})=>{
  const epoch=selectionEpoch.current;
  const current=()=>!signal?.aborted&&sid===selectedRef.current&&epoch===selectionEpoch.current
    &&identity!==null&&evidenceMetadataIdentity(sessionsRef.current.find(item=>item?.id===sid),sid)===identity;
  if(!current())throw Error('Evidence export session or subject context changed. No request was sent.');
  if(operation!==undefined){
   if(!operation||operation.controller?.signal!==signal||typeof operation.controller?.abort!=='function'
      ||!(operation.current===null||typeof operation.current==='function'))
    throw Error('Evidence export operation binding is invalid.');
   if(operation.current===null){
    operation.current=()=>{const valid=current();if(!valid)operation.controller.abort();return valid;};
    evidenceOperations.current.add(operation.controller);
    signal.addEventListener('abort',()=>evidenceOperations.current.delete(operation.controller),{once:true});
   }
   if(!operation.current())throw Error('Evidence export operation changed. Result is unconfirmed.');
  }
  const root=apiSessionPath(sid);
  let path,options={signal};
  if(action==='context')path=root+'/report-context';
  else if(action==='publish'){path=root+'/evidence-exports';options={method:'POST',body,signal};}
  else if((action==='receipt'||action==='artifact')&&typeof body?.operation_id==='string'&&/^[0-9a-f]{32}$/.test(body.operation_id))
    path=root+'/evidence-exports/'+body.operation_id+(action==='artifact'?'/artifact':'');
  else throw Error('Evidence export request is invalid.');
  const response=await api(path,options);
  if(!current()){try{await response.body?.cancel();}catch{}throw Error('Evidence export context changed. Result is unconfirmed.');}
  const value=action==='artifact'?response:await boundedJsonResponse(response,{signal});
  if(!current())throw Error('Evidence export context changed. Result is unconfirmed.');
  return action==='artifact'?value:action==='context'?checkedContext(value,sid):checkedReceipt(value,sid,body);
 },[api]);

 const loadManualAssessmentContext=useCallback(async(sid,{signal}={})=>{
  const epoch=selectionEpoch.current;
  const current=currentMetadataState(sessionsRef.current.find(item=>item?.id===sid),sid);
  if(!current||sid!==selectedRef.current||signal?.aborted)
   throw Error('Manual assessment context is unavailable for the current selected session.');
  const result=await json(apiSessionPath(sid)+'/manual-assessment-context',{signal});
  const latest=currentMetadataState(sessionsRef.current.find(item=>item?.id===sid),sid);
  if(signal?.aborted||sid!==selectedRef.current||epoch!==selectionEpoch.current||latest?.context!==current.context)
   throw Error('Selected session or metadata context changed while loading the manual assessment context.');
  if(result?.schema!=='kinelab.manual-assessment-context.v1'||result.status!=='AVAILABLE'
     ||result.session_id!==sid||result.metadata_context_sha256!==current.context
     ||result.origin_sha256!==current.state.origin.sha256
     ||result.test_only!==true||result.clinical_accuracy_validated!==false)
   throw Error('Manual assessment context does not match the selected session and current metadata.');
  return result;
 },[json]);
 const publishManualAssessment=useCallback(async(sid,body)=>{
  const epoch=selectionEpoch.current;
  const current=currentMetadataState(sessionsRef.current.find(item=>item?.id===sid),sid);
  if(!current||sid!==selectedRef.current||body?.metadata_context_sha256!==current.context)
   throw Error('Manual assessment publication refused: selected session or metadata context is stale.');
  const receipt=await json(apiSessionPath(sid)+'/manual-assessments',{method:'POST',body});
  const latest=currentMetadataState(sessionsRef.current.find(item=>item?.id===sid),sid);
  if(sid!==selectedRef.current||epoch!==selectionEpoch.current||latest?.context!==current.context)
   throw Error('Manual assessment publication outcome is unconfirmed: selected session or metadata context changed. Inspect the session before retrying.');
  if(receipt?.schema!=='kinelab.manual-assessment-entry-receipt.v1'||receipt.session_id!==sid
     ||receipt.operation_id!==body.operation_id||receipt.metadata_context_sha256!==current.context
     ||receipt.test_only!==true||receipt.clinical_accuracy_validated!==false)
   throw Error('Manual assessment receipt does not match the selected session and metadata context. Publication is unconfirmed.');
  return receipt;
 },[json]);

 const refreshSessions=useCallback(async()=>{
   const sequence=++sessionsRequest.current,epoch=selectionEpoch.current;
  try {
   const result=await json(API+'/sessions');
   if(sequence!==sessionsRequest.current)return;
   const nextSessions=result.sessions||[];
   sessionsRef.current=nextSessions;
   setSessions(nextSessions);
   setLastRefreshedMs(Date.now());
   setFetchError(null);
   if(epoch!==selectionEpoch.current)return;
   setSelected(old=>{
    if(result.sessions.some(item=>isSessionActive(item,old)))return old;
     return '';
   });
  } catch(error) {
   if(sequence!==sessionsRequest.current)return;
   setFetchError(error?.message||'Session library refresh failed');
   throw error;
  }
 },[json]);

  const refreshSelected=useCallback(async(sid,{force=false}={})=>{
   if(!sid||sid!==selectedRef.current)return;
   const prior=selectedRequest.current;
   if(!force&&prior.pending&&prior.sid===sid&&prior.epoch===selectionEpoch.current)return;
   selectedRequest.current.controller?.abort();
   const controller=new AbortController(),sequence=++selectedRequest.current.sequence;
   const epoch=selectionEpoch.current;
   selectedRequest.current={controller,sequence,epoch,sid,pending:true};
   const timeout=setTimeout(()=>controller.abort('Session refresh timed out'),15000);
   const current=()=>selectedRef.current===sid && selectionEpoch.current===epoch &&
      selectedRequest.current.sequence===sequence && !controller.signal.aborted;
  const base=apiSessionPath(sid);
  try {
     const [info,pstate,cstate,reps,pass]=await Promise.all(
      [base,base+'/processing',base+'/capture',base+'/reports',base+'/passport'].map(path=>json(path,{signal:controller.signal})));
     if(!current())return;
     if(info.id!==sid||pass.session_id!==sid||[pstate,cstate,reps].some(item=>item.session_id&&item.session_id!==sid))
       throw Error('Session identity mismatch; data was not displayed.');
     setDetail(info);setJob(pstate);setCamera(cstate);
     setReports((reps.reports||[]).map(item=>({...item,session_id:sid})));setPassport(pass);
     setLastPoll(new Date().toLocaleTimeString());
     setLastRefreshedMs(Date.now());
     setFetchError(null);
   } catch(error) {
     if(selectedRef.current!==sid||selectionEpoch.current!==epoch||selectedRequest.current.sequence!==sequence)return;
     setDetail(null);setPassport(null);setReports([]);setJob(null);setCamera(null);
     setLastPoll('Refresh failed — session data unavailable');
     setFetchError(error?.message||'Active session refresh failed');
     throw error;
   } finally {
     clearTimeout(timeout);
     if(selectedRequest.current.sequence===sequence)selectedRequest.current.pending=false;
  }
 },[json]);

 useEffect(()=>{
  if(!token){setLoading(false);return}
  let cancelled=false;
  Promise.all([refreshSessions(),json(API+'/analysis')])
   .then(([,data])=>{if(!cancelled)setAnalysis(data)})
   .catch(error=>{if(!cancelled)show(error.message,'error')})
   .finally(()=>{if(!cancelled)setLoading(false)});
  return ()=>{cancelled=true};
 },[token,refreshSessions,json]);

 useEffect(()=>{
  if(!selected||!token)return;
  let active=true;
  refreshSelected(selected).catch(error=>{if(active)show(error.message,'error')});
   return ()=>{active=false;selectedRequest.current.controller?.abort()};
 },[selected,token,refreshSelected]);

 useEffect(()=>{
  if(!selected||!token)return;
  const tick=()=>refreshSelected(selected).catch(()=>{});
  const id=setInterval(tick,3500);
  return ()=>clearInterval(id);
 },[selected,activeToken,refreshSelected]);

 useEffect(()=>{
  const tok=activeToken;
  if(!tok){
   setConnected(false);
   return;
  }
  let unmounted=false;
  const ping=async()=>{
   try{
    const res=await fetch(API+'/health',{headers:{Authorization:'Bearer '+tok},cache:'no-store'});
    if(!unmounted)setConnected(res.ok);
   }catch{if(!unmounted)setConnected(false)}
  };
  ping();
  const timer=setInterval(ping,5000);
  return ()=>{unmounted=true;clearInterval(timer);};
 },[activeToken]);

 const handleRetryConnection=useCallback(async()=>{
  setLoading(true);
  setFetchError(null);
  try {
   await refreshSessions();
   if(selectedRef.current){
    await refreshSelected(selectedRef.current,{force:true});
   }
   show('Session connection refreshed successfully.','info');
  } catch(err) {
   setFetchError(err?.message||'Retry connection failed');
   show('Retry failed: '+(err?.message||'service unavailable'),'error');
  } finally {
   setLoading(false);
  }
 },[refreshSessions,refreshSelected]);

 const shutdownServer=async()=>{
  if(!confirmAction('Are you sure you want to stop the local KineLab service? You can restart it anytime via the desktop shortcut.'))return;
  try{
   await json('/api/v1/system/shutdown',{method:'POST',body:{confirm:true}});
   show('Local service has been shut down. You can safely close this browser window.');
   setConnected(false);
  }catch(err){show('Shutdown error: '+err.message,'error')}
 };

 const mutate=async(label,work)=>{
  if(busy)return;
   const epoch=selectionEpoch.current;
  setBusy(label);setNotice(null);
  try{
   const response=await work();
    if(epoch===selectionEpoch.current)show((response&&response.message)||label+' completed. Review the updated status.');
   await refreshSessions();
    if(epoch===selectionEpoch.current&&selectedRef.current)await refreshSelected(selectedRef.current,{force:true});
   }catch(error){if(epoch===selectionEpoch.current)show(error.message,'error')}
  finally{setBusy('')}
 };
 const doPost=(suffix,data)=>json(apiSessionPath(selected)+suffix,
   {method:'POST',body:data});

 function confirmAction(message){
  return window.confirm(message);
 }
 function openNative(target){
  if(!selected)return show('Choose a session first.','error');
  if(!confirmAction('Open '+target+' for session '+selected+'? This may open a native window.'))return;
  mutate('open-'+target,()=>doPost('/open',{target,confirm:true}));
 }
 const newSession=metadata=>{
  const text=newId.trim();
  if(!text)return show('Provide a unique session ID.','error');
  if(!isValidSessionMetadata(metadata))return show('Confirm valid opaque subject, operator, task, protocol and laterality metadata.','error');
  if(!confirmAction('Create a new, unregistered REAL capture session named '+text+'?'))return;
  const snapshot=Object.freeze({...metadata}),epoch=selectionEpoch.current;
  return mutate('new-session',async()=>{
   const result=await json(API+'/sessions',{method:'POST',body:{id:text,kind:'real',metadata:snapshot}});
   if(result.id!==text||!metadataConfirmationMatches(result.metadata_confirmation,text,snapshot))
    throw Error('Session metadata readback is unavailable or mismatched. Inspect the created session; no retry was performed.');
   if(epoch===selectionEpoch.current){setSelected(result.id);setNewId('');}
   return {message:'New local session created: '+result.id};
  });
 };
 const register=()=>{
  if(!detail?.ready_to_register)return show('Registration is blocked until six sources and real board measurement pass file checks.','error');
  if(!confirmAction('Permanently register six REAL original video hashes? This is NOT clinical validation and prevents replacing selected footage.'))return;
  mutate('register',()=>doPost('/register',{confirm:true}));
 };
 const saveBoard=()=>{
  const mm=Number(boardMm);
  if(!Number.isFinite(mm)||mm<=0||!operator.trim())return show('Enter the actual measured square side and operator initials.','error');
  if(!confirmAction('Did you physically measure the printed square with a ruler? Save '+mm+' mm as an operator measurement?'))return;
  mutate('board',async()=>{
   const value=await doPost('/board',{confirm:true,mm,operator:operator.trim()});
   const measured=safeMetricValue(value?.measured_square_mm)??'UNAVAILABLE';
   return {message:'Recorded physical ruler entry of '+measured+' mm. This is not verified calibration.'};
  });
 };
 async function importPhone(role,file){
  if(!file)return;
  if(file.size>1024*1024*1024)return show('MP4 exceeds the 1 GiB local import limit. Use the native Capture Station.','error');
  if(!file.name.toLowerCase().endsWith('.mp4'))return show('Only genuine MP4 footage can be imported.','error');
  if(!confirmAction('Import this local phone MP4 as '+role+' in '+selected+'? Existing originals are never overwritten.'))return;
  mutate('import-'+role,async()=>{
   const result=await api(apiSessionPath(selected)+'/import/'+role,
     {method:'POST',body:file,binary:true});
   const body=await result.json();
   return {message:body.filename+' copied and probed. The source remains unchanged.'};
  });
 }
 const startCapture=(role,seconds)=>{
  if(!confirmAction('Turn ON the Integrated Webcam and record '+seconds+' seconds for '+role+'? Video stays local.'))return;
  mutate('capture',()=>doPost('/capture',{confirm:true,role,seconds}));
 };
 const stopCapture=()=>{
  if(!confirmAction('Stop the local webcam and finalize the MP4? Partial data may remain unverified.'))return;
  mutate('stop-capture',()=>doPost('/capture/stop',{confirm:true}));
 };
 const processAction=id=>{
  if(!confirmAction('Run native '+id+' for '+selected+'? Existing synchronization and quality gates remain strict.'))return;
  mutate('process-'+id,()=>doPost('/processing',{confirm:true,action:id}));
 };
 const cancelProcess=()=>{
  if(!confirmAction('Cancel the verified native process tree? Partial outputs will remain UNVERIFIED.'))return;
  mutate('cancel-process',()=>doPost('/processing/cancel',{confirm:true}));
 };
 const fetchRecovery=()=>mutate('recovery',async()=>{
   const sid=selectedRef.current,epoch=selectionEpoch.current;
   const result=await json(apiSessionPath(sid)+'/recovery');
   if(sid===selectedRef.current&&epoch===selectionEpoch.current)setRecovery(result);
  return {message:'Recovery and lock diagnostics inspected without changing any files.'};
 });
 const downloadReport=async item=>{
   const sid=selectedRef.current,epoch=selectionEpoch.current;
  try{
    if(item.session_id!==sid)throw Error('Report belongs to a different session. Refresh its report list.');
   setBusy('download-'+item.key);
    const response=await api(apiSessionPath(sid)+'/artifact/'+item.key);
    const blob=await response.blob();
    if(sid!==selectedRef.current||epoch!==selectionEpoch.current)return;
    const url=URL.createObjectURL(blob);
   const link=document.createElement('a');link.href=url;link.download=item.filename;
   document.body.append(link);link.click();link.remove();
   setTimeout(()=>URL.revokeObjectURL(url),2000);
    show('Download requested for '+item.filename+' from '+sid+'. Check the browser download result.');
   }catch(error){if(epoch===selectionEpoch.current)show(error.message,'error')}
  finally{setBusy('')}
 };

 const handleGenerateReports = async (sid) => {
  if(busy)return;
  const epoch=selectionEpoch.current;
  if(!sid||sid!==selectedRef.current)return show('Report generation requires the currently selected session. No request was sent.','error');
  const row=sessionsRef.current.find(item=>item?.id===sid);
  const demo=row?.kind==='demo';
  const metadata=demo?null:currentMetadataState(row,sid);
  if(!demo&&(row?.kind!=='real'||!metadata))return show('Current verified metadata is UNAVAILABLE for this real session. No report request was sent.','error');
  const metadataContext=metadata?.context;
  const current=()=>{
   if(sid!==selectedRef.current||epoch!==selectionEpoch.current)return false;
   const latest=sessionsRef.current.find(item=>item?.id===sid);
   return demo?latest?.kind==='demo':latest?.kind==='real'&&currentMetadataState(latest,sid)?.context===metadataContext;
  };
  if(!confirmAction(`Generate truthful offline PDF, CSV and JSON research reports for ${sid}?`))return;
  if(!current())return;
  setBusy('generate-reports');setNotice(null);
  try{
   let body={confirm:true};
   if(!demo){
    const context=await json(apiSessionPath(sid)+'/report-context');
    if(!current())return;
    const exact=(value,keys)=>value!==null&&typeof value==='object'&&!Array.isArray(value)
     &&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
    const digest=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
    const validHead=value=>value===null||(exact(value,['generation','manifest_sha256'])
     &&typeof value.generation==='string'&&/^report-[0-9a-f]{32}$/.test(value.generation)&&digest(value.manifest_sha256));
    if(!exact(context,['schema','session_id','status','report_context_sha256','head','reason'])
      ||context.schema!=='kinelab.report-generation-context.v1'||context.session_id!==sid
      ||context.status!=='AVAILABLE'||!digest(context.report_context_sha256)||!validHead(context.head)||context.reason!==null)
     throw Error('Current report context is UNAVAILABLE or malformed. No report was generated.');
    body={confirm:true,expected_report_head:context.head===null?null:{generation:context.head.generation,manifest_sha256:context.head.manifest_sha256},
     expected_report_context_sha256:context.report_context_sha256};
   }
   if(!current())return;
   const response=await json(apiSessionPath(sid)+'/reports/generate',{method:'POST',body});
   if(!current())return;
   await refreshSessions();
   if(!current())return;
   await refreshSelected(sid,{force:true});
   if(!current())return;
   show(response?.message||'Reports generated. Review the updated research reports.');
  }catch(error){if(current())show(error?.message||'Report generation outcome is unavailable.','error')}
  finally{setBusy('')}
 };

 // An unanswered or 5xx attempt keeps its exact body so resubmitting the same
 // correction retries the same operation instead of publishing a second revision.
 const correctMetadata=metadata=>{
  const sid=selectedRef.current;
  const current=sid&&detail?.id===sid?currentMetadataState(detail,sid):null;
  if(!current)return show('Current verified metadata is UNAVAILABLE for this session. No correction was sent.','error');
  if(!isValidSessionMetadata(metadata))return show('Confirm valid opaque subject, operator, task, protocol and laterality metadata.','error');
  if(!confirmAction('Publish an operator-reported metadata correction for '+sid+'? The original session file stays unchanged. This is not identity, protocol or clinical verification.'))return;
  const origin=current.state.origin.sha256,head=current.state.head?current.state.head.sha256:null;
  const key=JSON.stringify([sid,origin,head,METADATA_FIELDS.map(name=>metadata[name])]);
  let body=correctionAttempt.current?.key===key?correctionAttempt.current.body:null;
  if(!body){
   try{
    body={metadata:Object.freeze({...metadata}),expected_origin_sha256:origin,expected_head_sha256:head,
     operation_id:newOperationId(),reason_code:'operator_correction',confirm:true};
   }catch(error){return show(error.message,'error')}
  }
  correctionAttempt.current={key,body};
  return mutate('metadata-correction',async()=>{
   try{
    const receipt=await json(apiSessionPath(sid)+'/metadata-revisions',{method:'POST',body});
    if(!await metadataRevisionReceiptMatches(receipt,sid,body))throw Error('Metadata revision receipt is unconfirmed for '+sid+'. Inspect the session before further work.');
    if(correctionAttempt.current?.body===body)correctionAttempt.current=null;
    return {message:'Operator-reported metadata correction published for '+sid+'. Current metadata was re-read from the local service.'};
   }catch(error){
    const definitive=Number.isInteger(error?.status)&&error.status>=400&&error.status<500;
    if(definitive&&correctionAttempt.current?.body===body)correctionAttempt.current=null;
    if(definitive)throw error;
    throw Error((error?.message||'Correction outcome unknown')+'. The outcome is unconfirmed; resubmit the same correction to retry the same operation.');
   }
  });
 };

 const handleCompareSessions = async (s1, s2) => {
  const ids=[s1,s2];
  const contexts=ids.map(id=>currentMetadataState(sessionsRef.current.find(item=>item?.id===id),id)?.context);
  const missing=ids.filter((id,i)=>!contexts[i]);
  if(missing.length)throw Error('Comparison unavailable: verified current metadata context is missing or malformed for '+missing.join(', ')+'. No comparison request was sent.');
  return await json(`${API}/compare?s1=${encodeURIComponent(s1)}&s2=${encodeURIComponent(s2)}`
   +`&expected_metadata_context_s1=${contexts[0]}&expected_metadata_context_s2=${contexts[1]}`);
 };

 const loadBackupSchedule = useCallback(() => json(`${API}/backup/schedule`), [json]);

 const handleCreateBackup = async () => {
  if (!confirmAction('Create a local backup of all sessions, saved synthetic recordings and audit history? Finish native capture and processing first.')) return;
  mutate('create-backup', async () => {
   const res = await json(`${API}/backup/create`, { method: 'POST', body: { confirm: true } });
   return res;
  });
 };

 const handleRestoreBackup = async (backupName) => {
  if (!confirmAction(`Recover ${backupName}? Complete backups are verified into a separate recovery folder. Legacy archives import new sessions only, without their database or audit history. Existing sessions are never overwritten.`)) return;
  mutate('restore-backup', async () => {
   const res = await json(`${API}/backup/restore`, { method: 'POST', body: { confirm: true, backup_name: backupName, overwrite: false } });
   await refreshSessions();
   if (selected) await refreshSelected(selected);
   return res;
  });
 };

 const isDataStale=isStale(lastRefreshedMs,15000,nowTick);
 const showStaleBanner=!connected||fetchError!==null||(lastRefreshedMs!==null&&isDataStale);

 const active=sessions.find(entry=>isSessionActive(entry,selected));
 const mode=active?formatSession(active):null;
 const subhead=NAV_ITEMS.find(item=>item.id===view);

 if(!token)return <div className="uw-legacy">
  <div className="uw-old-warning">This legacy Motion Lab shortcut opens the viewer only.
   For the unified workspace, double-click the <strong>KineLab PT</strong> desktop icon.</div>
  <MotionApp/>
 </div>;

 const navigation=()=>{
  setRecovery(null);
  if(view==='diagnostics'&&selected)fetchRecovery();
 };

 return <div className="uw-app">
  <aside className="uw-sidebar" aria-label="Application navigation">
   <div className="uw-brand"><div className="uw-brand-mark">K</div><div><strong>KineLab PT</strong>
    <span>Motion Analysis Studio</span></div></div>
   <div className="uw-sidebar-group">WORKSPACE</div>
   <nav aria-label="KineLab views">{NAV_ITEMS.map(item=><button
    key={item.id} type="button" className={'uw-nav-link '+(view===item.id?'is-active':'')+(item.id==='live'?' is-live-link':'')}
    aria-current={view===item.id?'page':undefined}
    disabled={recordingBusy&&item.id!==view}
    onClick={()=>{setView(item.id);if(item.id==='diagnostics'&&selected)fetchRecovery()}}>
    <span className="uw-nav-icon" aria-hidden="true">{item.icon || NAV_SIGNS[item.id]}</span>
    <span>{item.label}{item.id==='live'&&<span className="uw-nav-live-dot">LIVE</span>}<small>{item.description}</small></span>
   </button>)}</nav>
   <div className="uw-sidebar-bottom">
    <span className="uw-online-dot"/> LOCAL SYSTEM <strong>ONLINE</strong>
    <p>127.0.0.1 · Offline-first<br/>No cloud upload or clinical validation.</p>
   </div>
  </aside>

  <div className="uw-main">
   <header className="uw-topbar">
    <div className="uw-top-title"><span>KINELAB / WORKSPACE</span>
     <h2>{subhead?.label||'Overview'}</h2>
    </div>
    <div className="uw-top-controls">
     <div className={"uw-connection-pill " + (connected ? "uw-connected" : "uw-disconnected")} title={connected ? "Connected to local KineLab service" : "Reconnecting to local KineLab service..."}>
      <span className="uw-conn-dot" />
      <span>{connected ? "127.0.0.1" : "Reconnecting..."}</span>
     </div>
     <label className="uw-select-wrap"><span>ACTIVE SESSION</span>
      <select aria-label="Select active session" value={selected}
       onChange={event=>setSelected(event.target.value)} disabled={loading||!!busy||recordingBusy}>
       {!selected&&<option value="">No sessions available</option>}
       {sessions.map(session=><option value={session.id} key={session.id}>{session.id}</option>)}
      </select></label>
     <Pill tone={mode?.badge==='TEST ONLY'?'warning':mode?.badge==='SYNTHETIC'?'warning':mode?.badge==='UNVERIFIED'?'warning':mode?.badge==='REGISTERED'?'present':'neutral'}>{mode?.badge??'NO SESSION'}</Pill>
     {passport?.board_measurement ? (
      <div className="uw-setup-pill" title="Physical ruler measurement self-reported by operator; unverified auto-inferred scale">
       <span className="uw-setup-dot" />
       <span>RULER: {safeMetricValue(passport.board_measurement.measured_square_mm) ?? 'UNAVAILABLE'} mm (SELF-REPORTED)</span>
      </div>
     ) : selected ? (
      <div className="uw-setup-pill is-pending" title="Checkerboard physical ruler measurement pending">
       <span className="uw-setup-dot" />
       <span>RULER: UNAVAILABLE</span>
      </div>
     ) : null}
    </div>
   </header>
   <div className="uw-content">
    <Notice message={notice} onClose={()=>setNotice(null)}/>
    {showStaleBanner&&(
     <div className="uw-stale-banner" role="alert">
      <div className="uw-stale-banner-content">
       <span className="uw-stale-icon" aria-hidden="true">⚠️</span>
       <div className="uw-stale-text">
        <strong>{formatStaleNotice(lastRefreshedMs,nowTick)}</strong>
        <span className="uw-stale-desc">
         {!connected
          ? ' — Local service disconnected. Reconnecting...'
          : (fetchError
            ? ` — ${fetchError}`
            : ' — Session data exceeds 15s refresh threshold')}
        </span>
       </div>
      </div>
      <button
       type="button"
       className="uw-btn uw-btn-retry"
       onClick={handleRetryConnection}
       disabled={loading||!!busy}
      >
       Retry Connection
      </button>
     </div>
    )}
    {loading&&<div className="uw-loading" role="status">Connecting to local session library...</div>}
    {!loading&&<div className="uw-view">
     <div className="uw-title-row"><div><span className="uw-overline">T6 / INTEGRATED MOTION WORKSPACE</span>
      <h1>{subhead?.label}</h1>
      <p>{subhead?.description}. {dateMeta}</p>
      <div className="uw-setup-banner">
       {passport?.board_measurement ? (
        <span>SETUP: <strong>{safeMetricValue(passport.board_measurement.measured_square_mm) ?? 'UNAVAILABLE'} mm</strong> self-reported ruler measurement by {passport.board_measurement.measured_by || 'operator'} · Auto-inferred physical scale NOT ESTABLISHED</span>
       ) : selected ? (
        <span className="uw-setup-missing">SETUP: Ruler measurement UNAVAILABLE · Self-reported physical calibration pending</span>
       ) : (
        <span>SETUP: No session selected · Physical scale unverified</span>
       )}
      </div></div>
      <span className="uw-version">KINELAB PT / V1 DEVELOPMENT</span>
     </div>

     {view==='overview'&&<>
      <div className="uw-stat-grid">
       <div className="uw-stat"><span>LOCAL SESSIONS</span><strong>{safeMetricValue(sessions.length)??'0'}</strong><small>Test recordings stay separated</small></div>
       <div className="uw-stat"><span>CAPTURE SLOTS</span><strong>{mode?.count||'UNAVAILABLE'}</strong><small>Current selected session</small></div>
       <div className="uw-stat"><span>STATUS</span><strong className="uw-stat-word">{mode?.badge??'NO SESSION'}</strong><small>No physical accuracy claim</small></div>
       <div className="uw-stat"><span>NATIVE JOB</span><strong className="uw-stat-word">{job?.state?.toUpperCase()??'IDLE'}</strong><small>Only native passes count</small></div>
      </div>
      <EvidencePassport passport={passport} onOpenNative={openNative} />
      <div className="uw-two" style={{marginTop:'18px'}}>
       <Box><CardHeading eyebrow="YOUR NEXT WORKFLOW" heading="From capture to motion"
        detail="Every step uses the current local session and the existing quality gates."/>
        <div className="uw-step-list">{[
         ['01','Capture','Record webcam, import phone MP4, measure board','capture'],
         ['02','Process','Normalize, calibrate, synchronize, reconstruct','processing'],
         ['03','Review','Open verified 3D motion and actual joint graphs','motion'],
         ['04','Analyze','Inspect research-grade gait and squat experiments','analysis'],
        ].map(([index,heading,desc,next])=><button key={index} className="uw-step"
          onClick={()=>setView(next)}><span>{index}</span><div><strong>{heading}</strong><small>{desc}</small></div>
          <em>→</em></button>)}</div>
       </Box>
       <Box><CardHeading eyebrow="SESSION HEALTH" heading={selected||'No session selected'}
         detail="No test clips will be presented as calibrated clinical recordings."/>
        <div className="uw-checklist">
         {Object.entries(detail?.sources||{}).map(([name,present])=><div key={name}>
          <span>{name}</span><Pill tone={present?'present':'neutral'}>{present?'Available':'UNAVAILABLE'}</Pill>
         </div>)}
         {!detail&&<EmptyState headline="No selected session" detail="Create a new real session in the Sessions tab."/>}
        </div>
       </Box>
      </div>
     </>}

     {view==='live'&&<LiveTrackerStudio
       token={activeToken}
       onRecordingBusy={setRecordingBusy}
       onSessionCreated={sid=>{
         refreshSessions();
         setSelected(sid);
         show('Live session recorded and selected: ' + sid, 'info');
       }}
     />}

     {view==='sessions'&&<>
      <div className="uw-two">
       <Box><CardHeading eyebrow="NEW LOCAL WORKSPACE" heading="Create a recording session"
         detail="No camera opens and no files are registered until you explicitly request them."/>
         <SessionMetadataSetup sessionId={newId} onSessionIdChange={setNewId}
          onCreate={newSession} busy={!!busy}/>
        <p className="uw-help">Session IDs stay under the local projects folder. Existing files are never overwritten.</p>
       </Box>
       <Box><CardHeading eyebrow="CURRENT SESSION" heading={selected||'None'}
        detail={mode?.badge+' · '+(mode?.count??'0 / 6')+' source recordings'}/>
        <div className="uw-actions">
         <button className="uw-btn" disabled={!selected} onClick={()=>openNative('folder')}>Open local folder</button>
          <button className="uw-btn" disabled>Open Capture Station</button>
        </div>
         <p role="status" className="uw-help">PARTICIPANT_RECORDING_BLOCKED: recording requires an independently approved privacy, consent, physical-validation and clinical-use protocol.</p>
       </Box>
      </div>
      <Box><CardHeading eyebrow="LOCAL LIBRARY" heading="Your session inventory"
       detail="Select a row to open its capture, processing and reports status."/>
       <div className="uw-list">{sessions.map(session=>{
        const s=formatSession(session);
        return <button className={'uw-session-row '+(isSessionActive(session,selected)?'chosen':'')}
          key={session.id} onClick={()=>setSelected(session.id)}>
          <div><strong>{session.id}</strong><small>{session.kind} · {session.status}</small></div>
          <Pill tone={session.kind==='test-only'?'warning':s.badge==='SYNTHETIC'?'warning':s.badge==='UNVERIFIED'?'warning':s.badge==='REGISTERED'?'present':'neutral'}>{s.badge}</Pill>
          <span>{s.count} sources</span><em>→</em>
         </button>;
       })}
       {!sessions.length&&<EmptyState headline="No local sessions" detail="Create your first recording session above."/>}</div>
      </Box>
     </>}

     {view==='capture'&&<GuidedCaptureWizard
        key={selected}
        onCorrectMetadata={correctMetadata}
       detail={detail}
       selectedSession={selected}
       activeSession={active}
       cameraState={camera}
       busy={busy}
       onImportPhone={importPhone}
       onStartCapture={startCapture}
       onStopCapture={stopCapture}
       onSaveBoard={(mm, op) => mutate('board', () => doPost('/board', { confirm: true, mm, operator: op }))}
       onRegister={register}
       onOpenNative={openNative}
     />}

     {view==='processing'&&<>
      <Box><CardHeading eyebrow="POSE2SIM / OPEN SIM PIPELINE" heading="Native processing coordinator"
       detail="Each action starts only on request. Actual stage and hash checks—not process exit alone—determine acceptance."/>
       <div className="uw-progress"><div>
        <Pill tone={job?.state==='passed'?'present':job?.state==='running'?'warning':'neutral'}>
         {job?.state?.toUpperCase()??'IDLE'}</Pill>
         <p>{job?.message??'No native stage has been started.'}</p>
        </div>
        {job?.state==='running'&&<button className="uw-btn danger" onClick={cancelProcess}
         disabled={!!busy}>Cancel native action</button>}
       </div>
       <div className="uw-stage-grid">{STAGES.map(stage=><div className="uw-stage" key={stage.id}>
        <div className="uw-stage-ico">◎</div><strong>{stage.label}</strong>
        <p>{stage.description}</p>
        <button className="uw-btn" onClick={()=>processAction(stage.id)}
          disabled={!!busy||active?.kind!=='real'||active?.status!=='registered'||job?.state==='running'}>
          Start stage</button>
       </div>)}</div>
      </Box>
      <div className="uw-two">
       <Box><CardHeading eyebrow="RECONSTRUCTION PREREQUISITES" heading="Evidence checkpoints"/>
        <div className="uw-checklist">{[
          ['Source hash manifest',detail?.sources?.['session.json']],
          ['Verified normalization preflight',detail?.sources?.['preflight.json']],
          ['Manually observed sync cues',detail?.sources?.['sync-observations.json']],
          ['Native Pose2Sim run manifest',detail?.sources?.['run.json']],
         ].map(([label,value])=><div key={label}><span>{label}</span>
          <Pill tone={value?'present':'neutral'}>{value?'File exists':'UNAVAILABLE'}</Pill></div>)}</div>
       </Box>
       <Box><CardHeading eyebrow="MANUAL FRAME REVIEW" heading="Observe synchronization cues"
        detail="Existing native two-camera cue reviewer verifies the exact displayed video frame."/>
        <button className="uw-btn" onClick={()=>openNative('sync')} disabled={!selected}>
         Open native frame review</button>
        <p className="uw-help">Native correlation, reference and drift must still be verified by Pose2Sim.</p>
       </Box>
      </div>
     </>}

     {view==='motion'&&<div className="uw-motion-slot"><MotionApp key={selected} sessionId={selected} token={activeToken}/></div>}

     {view==='analysis'&&<>
      <div className="uw-two">
       <Box><CardHeading eyebrow="2D WALKING TEST" heading="Gait event review"
        detail="Unvalidated foot-motion proposals, annotated sample videos and human observations."/>
        <div className="uw-analysis-data">
         {(analysis?.gait?.candidates||[]).map(v=><div key={v.role}>
          <span>{v.role}</span><strong>{safeMetricValue(v.count)??'UNAVAILABLE'} extrema</strong></div>)}
        </div>
        <Pill tone="warning">{analysis?.gait?.status==='unvalidated_candidates'?'UNVALIDATED / TEST ONLY':'UNAVAILABLE'}</Pill>
        <p className="uw-help">These extrema are not confirmed heel strikes, toe-offs or step counts.</p>
       </Box>
       <Box><CardHeading eyebrow="SYNTHETIC EXERCISE MODULE" heading="Squat phase detection"
        detail="Tested algorithm; awaiting real, manually reviewed side-view squat footage."/>
        <div className="uw-analysis-data">
         <div><span>Protocol</span><strong>{DEFAULT_PRESETS[EXERCISE_TYPES.SQUAT]?.name ?? 'Squat'}</strong></div>
         <div><span>Target ROM</span><strong>{formatExerciseMetric(DEFAULT_PRESETS[EXERCISE_TYPES.SQUAT]?.targetROM, EXERCISE_TYPES.SQUAT) ?? 'UNAVAILABLE'}</strong></div>
         <div><span>Algorithm</span><strong>2D phase / repetition</strong></div>
         <div><span>Evidence status</span><strong>Research only</strong></div>
         <div><span>Physical validation</span><strong>Not established</strong></div>
        </div>
        <Pill tone="warning">SYNTHETIC TESTS ONLY</Pill>
        <p className="uw-help">No real squat counts, joint angles or clinical outcomes are fabricated.</p>
       </Box>
      </div>
      {analysis?.gait?.status==='unvalidated_candidates'&&<Box>
        <CardHeading eyebrow="LOCAL EXPERIMENTAL WORKSPACE" heading="Manual gait-event reviewer"
         detail="Inspect the two sample videos, label events before seeing hypotheses, and keep references separate."/>
        <iframe className="uw-embed" src="/samples/gait-t5/index.html"
         sandbox="allow-scripts allow-downloads"
         title="Test-only Caliscope gait event review (not clinically validated)" loading="lazy"/>
       </Box>}
     </>}

     {view==='reports'&&<ReportStudio
       key={selected}
       sessions={sessions}
       selectedSession={selected}
       reports={reports}
       busy={busy}
       onSelectSession={setSelected}
       onDownloadReport={downloadReport}
       onGenerateReports={handleGenerateReports}
       onCompareSessions={handleCompareSessions}
       onLoadBackupSchedule={loadBackupSchedule}
       onCreateBackup={handleCreateBackup}
       onRestoreBackup={handleRestoreBackup}
       onLoadManualAssessmentContext={loadManualAssessmentContext}
       onPublishManualAssessment={publishManualAssessment}
 onEvidenceExportRequest={evidenceExportRequest}
       onOpenFolder={()=>openNative('folder')}
     />}

     {view==='diagnostics'&&<>
      <div className="uw-two">
       <Box><CardHeading eyebrow="LOCAL SERVICE" heading="Runtime and access"
        detail="Private loopback Python API authenticated by this app session's local token."/>
        <div className="uw-checklist">
         <div><span>API binding</span><Pill tone="present">127.0.0.1 ONLY</Pill></div>
         <div><span>Cloud endpoints</span><Pill>NONE</Pill></div>
         <div><span>Clinical validation</span><Pill tone="warning">UNVERIFIED</Pill></div>
         <div><span>Last status refresh</span><span>{lastPoll||'Not yet'}</span></div>
        </div>
        <div className="uw-actions">
         <button className="uw-btn" onClick={()=>openNative('runbook')} disabled={!selected}>Open runbook</button>
         <button className="uw-btn" onClick={()=>refreshSelected(selected)} disabled={!selected}>Refresh status</button>
         <button className="uw-btn danger" onClick={shutdownServer}>Shut down local service</button>
        </div>
       </Box>
       <Box><CardHeading eyebrow="SAFE RECOVERY" heading="Native jobs and abandoned locks"
        detail="Diagnostics do not delete or clear run locks. Use the original Capture Station for confirmed orphan archival."/>
        <button className="uw-btn" onClick={fetchRecovery} disabled={!selected||!!busy}>Inspect lock state</button>
        {recovery&&<div className="uw-checklist">
         {Object.entries(recovery.locks||{}).map(([name,lock])=><div key={name}>
          <span>{name}</span><Pill tone={lock.state==='absent'?'present':'warning'}>{lock.state}</Pill>
         </div>)}
         <div><span>Native run state</span><strong>{recovery.native_run}</strong></div>
        </div>}
       </Box>
      </div>
      <Box><CardHeading eyebrow="QUALITY BOUNDARY" heading="What does not count as a clinical pass"
       detail="Test videos, synthetic squat repetitions, raw model scores, and an incomplete six-role capture."/>
       <p className="uw-help">A proper consumer physical-measurement pilot requires matching phone and webcam views,
        measured board geometry, independently confirmed cue timing, native camera reprojection quality,
        reconstruction repeatability and suitable external reference evidence.</p>
      </Box>
     </>}
    </div>}
    <footer className="uw-footer">
     <span>© KineLab PT · Local research platform</span>
     <span>No fabricated data · Test-only results remain segregated · Not for diagnosis</span>
    </footer>
   </div>
  </div>
 </div>;
}
