import React, {useCallback,useEffect,useRef,useState} from 'react';
import {RecordingClient,RECORDING_LIMITS,sha256Text} from './recordingClient.js';
import syntheticSource from './syntheticPose.js?raw';

export default function SyntheticRecordingPanel({token,apiPrefix,observationRef,exerciseType,targetROM,onBusy,stopSignal,stopRecordingRef}) {
 const client=useRef(null), started=useRef(0), mounted=useRef(true), requests=useRef(new Set());
 const [status,setStatus]=useState(null), [history,setHistory]=useState([]), [error,setError]=useState('');
 const [action,setAction]=useState(false);
 const request=useCallback(async(path,body)=>{
  const controller=new AbortController();requests.current.add(controller);
  const timeout=setTimeout(()=>controller.abort(),10000);
  try{
   const response=await fetch(apiPrefix+path,{method:body===undefined?'GET':'POST',signal:controller.signal,
    headers:{Authorization:`Bearer ${token}`,...(body===undefined?{}:{'Content-Type':'application/json'})},
    body:body===undefined?undefined:JSON.stringify(body)});
   const data=await response.json();if(!response.ok)throw Error(data.error||`Storage request failed (${response.status})`);
   return data;
  }finally{clearTimeout(timeout);requests.current.delete(controller);}
 },[apiPrefix,token]);
 const refresh=useCallback(async()=>{
  const data=await request('/recordings');if(mounted.current)setHistory(data.recordings);
 },[request]);
 useEffect(()=>{
  mounted.current=true;
  const stop=()=>{
   const current=client.current;if(!current)return;
   setAction(true);
   void current.stop().then(()=>{if(mounted.current)onBusy(false);return refresh();})
    .catch(e=>{if(mounted.current)setError(e.message);})
    .finally(()=>{if(mounted.current)setAction(false);});
  };
  if(stopRecordingRef)stopRecordingRef.current=stop;
  refresh().catch(e=>{if(mounted.current)setError(e.message);});
  const timer=setInterval(()=>{
   const current=client.current;if(stopSignal?.current||!current?.accepting)return;
   const sample=observationRef.current,now=performance.now();
   if(now-started.current>RECORDING_LIMITS.durationMs){
    current.accepting=false;current.interrupted=true;current.message='Duration limit reached; finalize saved frames';current.notify();
    void current.flush().catch(()=>{});return;
   }
   const stale=!sample || now-sample.capturedAt>250;
   const observation={time_ms:Math.round(now-started.current),valid:!stale,
    reasons:stale?['STALE']:[],landmarks:stale?null:sample.landmarks};
   try{current.enqueue(observation);}catch(e){current.fail(e);}
  },50);
  const flushTimer=setInterval(()=>{
   const current=client.current;
   if(current?.created&&!current.failed&&!current.finalized&&current.snapshot().pendingFrames)void current.flush().catch(()=>{});
  },500);
  const interrupt=()=>{
   const current=client.current;if(!current?.accepting || !document.hidden)return;
   current.accepting=false;current.interrupted=true;current.message='Capture interrupted while page was hidden';current.notify();
   void current.flush().catch(()=>{});
  };
  const leaving=event=>{if(client.current&&!client.current.finalized){event.preventDefault();event.returnValue='';}};
  document.addEventListener('visibilitychange',interrupt);window.addEventListener('beforeunload',leaving);
  return ()=>{mounted.current=false;if(stopRecordingRef)stopRecordingRef.current=null;clearInterval(timer);clearInterval(flushTimer);client.current?.close();
   requests.current.forEach(controller=>controller.abort());document.removeEventListener('visibilitychange',interrupt);
   window.removeEventListener('beforeunload',leaving);onBusy(false);};
 },[refresh,observationRef,onBusy,stopSignal,stopRecordingRef]);
 const start=async()=>{
  if(stopSignal?.current)return;
  setAction(true);setError('');onBusy(true);client.current?.close();client.current=null;setStatus(null);
  try{
   const uuid=()=>crypto.randomUUID().replaceAll('-','');
   const exercise={squats:'squat',lunges:'lunge'}[exerciseType]||exerciseType;
   const header={schema:'kinelab.recording.v1',session_id:`synthetic-${uuid()}`,operation_id:uuid(),
    subject_id:'synthetic-subject',operator_id:'synthetic-operator',
    source:{kind:'synthetic',capture_id:uuid(),model_id:'kinelab-synthetic-33',model_version:'1',model_sha256:await sha256Text(syntheticSource)},
    protocol:{id:`${exercise}-research-v1`,version:1,exercise,side:exercise==='squat'?'bilateral':'left',
     target_angle_degrees:exercise==='balance'?null:Number(targetROM),target_hold_ms:exercise==='balance'?Number(targetROM)*1000:null},
    coordinates:{space:'image-normalized',units:'normalized',z_units:'relative',width:640,height:480,mirrored:false}};
   if(stopSignal?.current){setError('Activity stopped before recording creation');onBusy(false);return;}
   client.current=new RecordingClient({header,request,onChange:s=>{if(mounted.current)setStatus(s);}});
   await client.current.start();started.current=performance.now();
  }catch(e){setError(e.message);if(!client.current)onBusy(false);}
  finally{setAction(false);}
 };
 const finish=async()=>{
  setAction(true);setError('');
  try{await client.current.finish();onBusy(false);await refresh();}
  catch(e){setError(e.message);}finally{setAction(false);}
 };
 const retry=async()=>{
  setAction(true);setError('');
  try{const creating=!client.current.created;await client.current.retry();if(creating)started.current=performance.now();}
  catch(e){setError(e.message);}finally{setAction(false);}
 };
 const leaveDraft=async()=>{
  const current=client.current;
  if(!current||current.accepting||current.snapshot().pendingFrames||current.saved!==current.produced)return;
  current.close();client.current=null;setStatus(null);setError('');onBusy(false);
  try{await refresh();}catch(e){setError(e.message);}
 };
 const recover=async(row)=>{
  setAction(true);setError('');
  try{
   const verified=await request(`/recordings/${encodeURIComponent(row.session_id)}`);
   if(verified.session_id!==row.session_id || verified.operation_id!==row.operation_id)throw Error('Recording identity mismatch');
   if(verified.saved_through!==verified.received_through)throw Error('Sequence gaps remain; retain draft for recovery');
   await request(`/recordings/${encodeURIComponent(row.session_id)}/finalize`,{
    operation_id:verified.operation_id,last_sequence:verified.saved_through,end_reason:'recovered_prefix'});
   await refresh();
  }catch(e){setError(e.message);}finally{setAction(false);}
 };
 const active=client.current&&!status?.finalized;
 return <section className="uw-card" aria-label="Synthetic recording">
  <h2>Synthetic recording · local software test</h2>
  <p>Raw generated landmarks only. No patient, camera measurements or clinical report. Up to 30 minutes at 20 samples/s.</p>
  <div className="uw-form-inline">
   <button type="button" onClick={start} disabled={!!stopSignal?.current||action||!!active||!token}>Record synthetic test</button>
   {active&&<button type="button" onClick={finish} disabled={action||status?.failed||!status?.producedThrough}>Finalize synthetic recording</button>}
   {status?.failed&&<button type="button" onClick={retry} disabled={action}>Retry pending save</button>}
   {active&&!status?.accepting&&!status?.pendingFrames&&status?.savedThrough===status?.producedThrough&&
    <button type="button" onClick={leaveDraft} disabled={action}>{status?.producedThrough?'Leave saved draft':'Close empty attempt'}</button>}
  </div>
  {status&&<p role="status" data-recording-saved={status.savedThrough}>
   Saved through frame {status.savedThrough} / produced {status.producedThrough}. Pending: {status.pendingFrames}. {status.message}
  </p>}
  {error&&<p role="alert">{error}</p>}
  <details open><summary>Synthetic recording history ({history.length})</summary>
   {history.filter(row=>row.session_id!==status?.sessionId||status.finalized).map(row=><div key={row.session_id} className="uw-card">
    <code>{row.session_id}</code><p>{row.state} · saved through {row.saved_through} · SYNTHETIC TEST ONLY</p>
    {row.state==='RECORDING'?<>
     <p>Unfinished capture. Unacknowledged tail: UNKNOWN. Only stored frames can be recovered.</p>
     <button type="button" disabled={action||!!active||!row.saved_through||row.missing_ranges.length>0} onClick={()=>recover(row)}>Finalize saved prefix</button>
    </>:<p>{row.manifest?.end_reason==='recovered_prefix'?'Recovered saved prefix · unacknowledged tail UNKNOWN':'Stored synthetic frames'} · physical accuracy and clinical validation UNVERIFIED</p>}
   </div>)}
  </details>
 </section>;
}
