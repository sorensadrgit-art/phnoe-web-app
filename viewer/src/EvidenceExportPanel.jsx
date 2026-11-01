import React, {useEffect, useRef, useState} from 'react';
import {currentMetadataState, newOperationId} from './sessionMetadataSetup.js';

const LIMIT=192*1024*1024;
const exact=(value,keys)=>value!==null&&typeof value==='object'&&!Array.isArray(value)
  &&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
const digest=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
const head=value=>exact(value,['generation','manifest_sha256'])
  &&typeof value.generation==='string'&&/^report-[0-9a-f]{32}$/.test(value.generation)&&digest(value.manifest_sha256);
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
export function evidenceMetadataIdentity(record,sid){
  const current=currentMetadataState(record,sid);
  return record?.kind==='real'&&current?JSON.stringify([sid,current.context,current.metadata,current.state.origin,current.state.head]):null;
}
export function checkedContext(value,sid){
  if(!exact(value,['schema','session_id','status','report_context_sha256','head','reason'])
    ||value.schema!=='kinelab.report-generation-context.v1'||value.session_id!==sid
    ||value.status!=='AVAILABLE'||value.reason!==null||!digest(value.report_context_sha256)||!head(value.head))
    throw Error('A verified current registered report is unavailable. Nothing was exported.');
  return value;
}
export function checkedReceipt(value,sid,request){
  if(!exact(value,['schema','session_id','operation_id','export_id','profile','report_head','report_context_sha256','manifest_sha256','archive','audit'])
    ||value.schema!=='kinelab.evidence-export-receipt.v1'||value.session_id!==sid
    ||value.operation_id!==request.operation_id||typeof value.export_id!=='string'||!/^evidence-[0-9a-f]{32}$/.test(value.export_id)
    ||value.profile!==request.profile||!head(value.report_head)
    ||value.report_head.generation!==request.expected_report_head.generation
    ||value.report_head.manifest_sha256!==request.expected_report_head.manifest_sha256
    ||value.report_context_sha256!==request.expected_report_context_sha256||!digest(value.manifest_sha256)
    ||!exact(value.audit,['event_id','event_hash'])
    ||typeof value.audit.event_id!=='string'||!/^[a-f0-9]{32}$/.test(value.audit.event_id)
    ||!digest(value.audit.event_hash)
    ||!exact(value.archive,['sha256','bytes'])||!digest(value.archive.sha256)
    ||!Number.isSafeInteger(value.archive.bytes)||value.archive.bytes<=0||value.archive.bytes>LIMIT)
    throw Error('Export receipt is malformed or belongs to another request. Download refused.');
  return value;
}
async function boundedArchive(response,proof,signal,current){
  let reader=null,complete=false,primary=null;
  try{
    if(signal.aborted||!current())throw Error('Download cancelled.');
    if(response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()!=='application/zip')
      throw Error('Export artifact type is invalid. Download refused.');
    const declared=response.headers.get('Content-Length');
    if(declared!==null&&(!/^\d+$/.test(declared)||Number(declared)!==proof.bytes))
      throw Error('Export artifact size is invalid. Download refused.');
    reader=response.body?.getReader?.();
    if(!reader)throw Error('Bounded export download is unavailable.');
    const chunks=[];let size=0;
    while(true){
      if(signal.aborted||!current())throw Error('Download cancelled.');
      const {done,value}=await reader.read();
      if(signal.aborted||!current())throw Error('Download cancelled.');
      if(done){complete=true;break;}
      if(!(value instanceof Uint8Array)||size+value.byteLength>proof.bytes||size+value.byteLength>LIMIT)
        throw Error('Export artifact exceeds its verified size. Download refused.');
      size+=value.byteLength;chunks.push(value);
    }
    if(size!==proof.bytes)throw Error('Export artifact is incomplete. Download refused.');
    const bytes=new Uint8Array(size);let offset=0;
    for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
    if(signal.aborted||!current())throw Error('Download cancelled.');
    if(hash!==proof.sha256)throw Error('Export artifact hash changed. Download refused.');
    return bytes;
  }catch(error){primary=error;throw error;}
  finally{
    let cleanup=null;
    try{if(!complete){if(reader)await reader.cancel();else await response.body?.cancel?.();}}
    catch(error){cleanup=error;}
    try{reader?.releaseLock();}catch(error){cleanup??=error;}
    if(!primary&&cleanup)throw cleanup;
  }
}

export default function EvidenceExportPanel({sessionId,session,busy,onRequest}){
  const identity=evidenceMetadataIdentity(session,sessionId);
  const available=Boolean(identity)&&typeof onRequest==='function';
  const live=useRef({identity,sequence:0,controller:null,active:false,urls:new Map()});
  live.current.identity=identity;
  const [profile,setProfile]=useState('');
  const [confirmed,setConfirmed]=useState(false);
  const [fullConfirmed,setFullConfirmed]=useState(false);
  const [attempt,setAttempt]=useState(null);
  const [receipt,setReceipt]=useState(null);
  const [working,setWorking]=useState(false);
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  useEffect(()=>()=>{live.current.sequence++;live.current.controller?.abort();for(const [url,timer] of live.current.urls){clearTimeout(timer);URL.revokeObjectURL(url);}live.current.urls.clear();},[]);
  const begin=()=>{
    if(live.current.active||busy||!identity||typeof onRequest!=='function')return null;
    live.current.active=true;setWorking(true);setError('');setMessage('');
    const sequence=++live.current.sequence,controller=new AbortController();live.current.controller=controller;
    const operation={controller,current:null};return {sequence,operation,signal:controller.signal,current:()=>!controller.signal.aborted&&sequence===live.current.sequence&&identity===live.current.identity&&(!operation.current||operation.current())};
  };
  const finish=task=>{if(task.sequence===live.current.sequence){live.current.active=false;setWorking(false);}task.operation.controller.abort();};
  const request=(action,body,task)=>onRequest(sessionId,identity,action,body,{signal:task.signal,operation:task.operation});
  const publish=async retry=>{
    const task=begin();if(!task)return;
    let submitted=false;
    try{
      let body=retry?attempt:null;
      if(!body){
        if(!confirmed||!['privacy-reduced','full'].includes(profile)||(profile==='full'&&!fullConfirmed))throw Error('Select a profile and confirm its disclosure.');
        const context=checkedContext(await request('context',null,task),sessionId);if(!task.current())return;
        body={confirm:true,profile,operation_id:newOperationId(),expected_report_head:{...context.head},expected_report_context_sha256:context.report_context_sha256};
        if(profile==='full')body.confirm_full=true;
        setAttempt(body);
      }
      if(!task.current())return;submitted=true;
      const value=checkedReceipt(await request('publish',body,task),sessionId,body);if(!task.current())return;
      setReceipt(value);setMessage('Export published locally. Download verifies the archive again.');
    }catch(failure){if(task.current())setError(submitted?'Publication is unconfirmed. Use Retry exact export to inspect or complete this same operation. '+failure.message:failure.message);}
    finally{finish(task);}
  };
  const download=async()=>{
    const task=begin();if(!task||!attempt||!receipt){if(task)finish(task);return;}
    try{
      const latest=checkedReceipt(await request('receipt',attempt,task),sessionId,attempt);
      if(!task.current())return;if(!equal(latest,receipt))throw Error('Export receipt changed. Download refused.');
      const response=await request('artifact',attempt,task);if(!task.current())return;
      const bytes=await boundedArchive(response,latest.archive,task.signal,task.current);if(!task.current())return;
      const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
      live.current.urls.set(url,null);
      try{const link=document.createElement('a');link.href=url;link.download=latest.export_id+'.zip';document.body.append(link);link.click();link.remove();}
      finally{live.current.urls.set(url,setTimeout(()=>{URL.revokeObjectURL(url);live.current.urls.delete(url);},2000));}
      setMessage('Verified archive download requested. Check your browser download result.');
    }catch(failure){if(task.current())setError(failure.message);}
    finally{finish(task);}
  };
  const cancel=()=>{live.current.sequence++;live.current.controller?.abort();live.current.active=false;setWorking(false);setMessage(attempt?'Request stopped in this view. Publication may already exist; retry uses the same operation.':'Request stopped before publication.');};
  return <section className="uw-card" aria-label="Evidence export">
    <h3>Evidence export</h3>
    <p>Current registered report only. Local hashes are unsigned evidence, not clinical or interoperability certification. Native, TRC and MOT adapters are unavailable.</p>
    {!available&&<p role="status">UNAVAILABLE: select a registered real session with verified current metadata and report, using its authorized local service.</p>}
    <fieldset disabled={!available||Boolean(busy)||working||Boolean(attempt)}>
      <legend>Export profile</legend>
      <label><input type="radio" name="evidence-profile" value="privacy-reduced" checked={profile==='privacy-reduced'} onChange={()=>{setProfile('privacy-reduced');setFullConfirmed(false);setConfirmed(false);}}/> Pseudonymous: reduced identifiers, still linkable and not anonymous</label>
      <label><input type="radio" name="evidence-profile" value="full" checked={profile==='full'} onChange={()=>{setProfile('full');setConfirmed(false);}}/> Full: original report members and source identities</label>
      {profile==='full'&&<label><input type="checkbox" aria-label="Confirm full disclosure" checked={fullConfirmed} onChange={event=>setFullConfirmed(event.target.checked)}/> I confirm this export includes original report identities.</label>}
      <label><input type="checkbox" aria-label="Confirm evidence export" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/> I confirm the selected profile and current session.</label>
    </fieldset>
    <div className="uw-actions">
      <button type="button" disabled={!available||Boolean(busy)||working||Boolean(attempt)||!confirmed||!profile||(profile==='full'&&!fullConfirmed)} onClick={()=>publish(false)}>Create evidence export</button>
      {attempt&&<button type="button" disabled={!available||Boolean(busy)||working} onClick={()=>publish(true)}>Retry exact export</button>}
      {receipt&&<button type="button" disabled={!available||Boolean(busy)||working} onClick={download}>Download verified export</button>}
      {receipt&&<button type="button" disabled={!available||Boolean(busy)||working} onClick={()=>{setAttempt(null);setReceipt(null);setProfile('');setConfirmed(false);setFullConfirmed(false);setMessage('Select and confirm a new export profile.');setError('');}}>Start another export</button>}
      {working&&<button type="button" onClick={cancel}>Stop waiting</button>}
    </div>
    {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
  </section>;
}
