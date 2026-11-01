// R08 generated TEST_ONLY component fixtures against existing ReportStudio.
// Missing controls are assertion RED, never a future-module import failure.
// Hook fixture is not DOM, StrictMode, actual download or backend proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {transformSync} from 'esbuild';
import {createHash} from 'node:crypto';
const directory=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
function moduleAt(filename,overrides={}){
 const file=path.resolve(directory,filename),module={exports:{}};
 const code=transformSync(fs.readFileSync(file,'utf8'),{loader:'jsx',format:'cjs'}).code;
 new Function('require','module','exports',code)(name=>Object.hasOwn(overrides,name)?overrides[name]:
  (name.startsWith('.')?moduleAt(path.resolve(path.dirname(file),name),overrides):require(name)),module,module.exports);
 return module.exports;
}
function nodes(tree,predicate,out=[]){
 if(tree&&typeof tree==='object'){
  if(predicate(tree))out.push(tree);
  React.Children.forEach(tree.props?.children,child=>nodes(child,predicate,out));
 }
 return out;
}
function textOf(tree){
 if(typeof tree==='string'||typeof tree==='number')return String(tree);
 if(!tree||typeof tree!=='object')return '';
 return React.Children.toArray(tree.props?.children).map(textOf).join('');
}
function mounted(filename,props,overrides={}){
 // Synthetic hook driver, not a React DOM/StrictMode proof. Keep hook ownership
 // per function child so JSX component dispatch can preserve all existing cases.
 const instances=new Map();let active=null,pending=[],seen=new Set();
 const react={...React,
  useState(initial){const {slots}=active,i=active.index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;
   return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value}];},
  useRef(value){const {slots}=active,i=active.index++;if(!(i in slots))slots[i]={current:value};return slots[i];},
  useMemo(fn){active.index++;return fn();},
  useId(){const i=active.index++;return 'generated-dialog-'+i;},
  useEffect(fn,deps){const {effects}=active,i=active.index++,previous=effects[i];
   if(!previous||!deps||deps.some((value,n)=>!Object.is(value,previous.deps?.[n])))pending.push(()=>{previous?.cleanup?.();effects[i]={deps,cleanup:fn()};});}};
 const Component=moduleAt(filename,{'react':react,...overrides}).default;
 function cleanup(instance){for(const effect of instance.effects)effect?.cleanup?.();}
 function invoke(type,values,identity){
  let instance=instances.get(identity);
  if(instance&&instance.type!==type){const removed=instance;pending.push(()=>cleanup(removed));instances.delete(identity);instance=null;}
  if(!instance){instance={type,slots:[],effects:[],index:0};instances.set(identity,instance);}
  seen.add(identity);instance.index=0;const parent=active;active=instance;
  let result;try{result=type(values);}finally{active=parent;}
  return expand(result,identity);
 }
 function expand(tree,identity){
  if(Array.isArray(tree))return tree.map((child,i)=>expand(child,identity+'/'+i));
  if(!React.isValidElement(tree))return tree;
  const key=identity+'/'+String(tree.key??'child');
  if(typeof tree.type==='function')return invoke(tree.type,tree.props,key);
  return React.cloneElement(tree,{},React.Children.toArray(tree.props.children).map((child,i)=>expand(child,key+'/'+i)));
 }
 return {render(next=props){props=next;pending=[];seen=new Set();return invoke(Component,props,'root');},
  effects(){for(const [identity,instance] of instances)if(!seen.has(identity)){cleanup(instance);instances.delete(identity);}
   const current=pending;pending=[];for(const effect of current)effect();},
  unmount(){for(const instance of instances.values())cleanup(instance);instances.clear();}};
}
const SID='TEST_ONLY-evidence-A',OTHER='TEST_ONLY-evidence-B',H=c=>c.repeat(64);
const HEAD={generation:'report-'+'1'.repeat(32),manifest_sha256:H('a')};
const CONTEXT={schema:'kinelab.report-generation-context.v1',session_id:SID,status:'AVAILABLE',report_context_sha256:H('b'),head:HEAD,reason:null};
const PAYLOAD=new TextEncoder().encode('TEST_ONLY archive bytes');
function row(id=SID,subject='1',context=H('c')){
 const metadata={schema:'kinelab.session-metadata.v1',subject_id:'sub-'+subject.repeat(32),operator_id:'op-'+'2'.repeat(32),task_id:'TEST_ONLY-task',protocol_id:'TEST_ONLY-protocol',protocol_version:'1',laterality:'bilateral',confirmed:true,confirmed_at:'2026-10-30T07:00:00Z'};
 return {id,kind:'real',effective_metadata:metadata,metadata_context_sha256:context,metadata_state:{schema:'kinelab.session-metadata-state.v1',session_id:id,status:'AVAILABLE',metadata,initial_metadata:metadata,origin:{path:'session.json',sha256:H('d')},head:null,context_sha256:context,reason:'TEST_ONLY contract fixture'}};
}
const receipt=body=>({schema:'kinelab.evidence-export-receipt.v1',session_id:SID,operation_id:body.operation_id,export_id:'evidence-'+'4'.repeat(32),profile:body.profile,report_head:HEAD,report_context_sha256:H('b'),manifest_sha256:H('e'),archive:{sha256:createHash('sha256').update(PAYLOAD).digest('hex'),bytes:PAYLOAD.length},audit:{event_id:'5'.repeat(32),event_hash:H('f')}});
function setup(onRequest){
 const props={sessions:[row(),row(OTHER)],selectedSession:SID,reports:[],busy:'',onSelectSession(){},onEvidenceExportRequest:onRequest};
 const driver=mounted('ReportStudio.jsx',props);let tree;
 const render=(next=props)=>{tree=driver.render(next);driver.effects();return tree;};
 const panel=()=>{const value=nodes(tree,n=>n.props?.['aria-label']==='Evidence export')[0];assert.ok(value,'R08 missing evidence export controls in ReportStudio');return value;};
 const button=label=>{const value=nodes(panel(),n=>n.type==='button'&&textOf(n)===label)[0];assert.ok(value,'Missing '+label);return value;};
 const field=label=>{const value=nodes(panel(),n=>n.props?.['aria-label']===label)[0];assert.ok(value,'Missing '+label);return value;};
 const choose=()=>{nodes(panel(),n=>n.type==='input'&&n.props.value==='privacy-reduced')[0].props.onChange();render();field('Confirm evidence export').props.onChange({target:{checked:true}});render();};
 render();return {props,render,panel,button,field,choose,driver};
}
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
test('R08-UI 00 exact reduced publication then authenticated receipt artifact flow and same-byte hash',async()=>{
 const calls=[];let published,clicks=0,revoked=0;const oldDocument=globalThis.document,create=URL.createObjectURL,revoke=URL.revokeObjectURL;
 globalThis.document={body:{append(){}},createElement:()=>({click(){clicks++;},remove(){}})};URL.createObjectURL=()=> 'blob:TEST_ONLY';URL.revokeObjectURL=()=>{revoked++;};
 const app=setup(async(sid,identity,action,body)=>{calls.push({sid,identity,action,body});if(action==='context')return CONTEXT;if(action==='publish'){published=receipt(body);return published;}if(action==='receipt')return published;return new Response(PAYLOAD,{headers:{'Content-Type':'application/zip','Content-Length':String(PAYLOAD.length)}});});
 try{app.choose();await app.button('Create evidence export').props.onClick();app.render();assert.deepEqual(calls.map(c=>c.action),['context','publish']);assert.deepEqual(Object.keys(calls[1].body).sort(),['confirm','expected_report_context_sha256','expected_report_head','operation_id','profile']);assert.deepEqual(calls[1].body.expected_report_head,HEAD);assert.match(calls[1].body.operation_id,/^[0-9a-f]{32}$/);assert.equal(calls[1].body.profile,'privacy-reduced');assert.match(textOf(app.panel()),/not anonymous/);await app.button('Download verified export').props.onClick();assert.deepEqual(calls.map(c=>c.action),['context','publish','receipt','artifact']);assert.equal(clicks,1);assert.equal(revoked,0);app.driver.unmount();assert.equal(revoked,1);}
 finally{app.driver.unmount();globalThis.document=oldDocument;URL.createObjectURL=create;URL.revokeObjectURL=revoke;}
});
test('R08-UI 01 full profile requires separate disclosure and exact confirm_full field',async()=>{
 const calls=[];const app=setup(async(sid,identity,action,body)=>{calls.push({action,body});return action==='context'?CONTEXT:receipt(body);});
 try{nodes(app.panel(),n=>n.type==='input'&&n.props.value==='full')[0].props.onChange();app.render();app.field('Confirm evidence export').props.onChange({target:{checked:true}});app.render();assert.equal(app.button('Create evidence export').props.disabled,true);app.field('Confirm full disclosure').props.onChange({target:{checked:true}});app.render();await app.button('Create evidence export').props.onClick();assert.equal(calls[1].body.confirm_full,true);assert.equal(calls[1].body.profile,'full');assert.equal(Object.keys(calls[1].body).length,6);}
 finally{app.driver.unmount();}
});
test('R08-UI 02 pending context cannot publish after session or subject change',async()=>{
 for(const change of [{selectedSession:OTHER},{sessions:[row(SID,'3'),row(OTHER)]}]){
  const pending=deferred(),calls=[];const app=setup(async(sid,identity,action)=>{calls.push(action);return pending.promise;});let work;
  try{app.choose();work=app.button('Create evidence export').props.onClick();app.render({...app.props,...change});pending.resolve(CONTEXT);await work;assert.deepEqual(calls,['context']);assert.equal(nodes(app.panel(),n=>n.type==='button'&&textOf(n)==='Download verified export').length,0);}
  finally{pending.resolve(CONTEXT);await work;app.driver.unmount();}
 }
});
test('R08-UI 03 late publication cannot expose receipt after metadata context change',async()=>{
 const pending=deferred();let body,work;const app=setup(async(sid,identity,action,request)=>{if(action==='context')return CONTEXT;body=request;return pending.promise;});
 try{app.choose();work=app.button('Create evidence export').props.onClick();await settle();assert.ok(body);app.render({...app.props,sessions:[row(SID,'1',H('f')),row(OTHER)]});pending.resolve(receipt(body));await work;assert.equal(nodes(app.panel(),n=>n.type==='button'&&textOf(n)==='Download verified export').length,0);}
 finally{pending.resolve(body?receipt(body):null);await work;app.driver.unmount();}
});
test('R08-UI 04 ambiguous publication failure retains explicit exact operation retry',async()=>{
 const calls=[];let fail=true;const app=setup(async(sid,identity,action,body)=>{calls.push({action,body});if(action==='context')return CONTEXT;if(fail){fail=false;throw Error('TEST_ONLY network failure');}return receipt(body);});
 try{app.choose();await app.button('Create evidence export').props.onClick();app.render();assert.match(textOf(app.panel()),/unconfirmed/);await app.button('Retry exact export').props.onClick();app.render();assert.deepEqual(calls.map(c=>c.action),['context','publish','publish']);assert.deepEqual(calls[1].body,calls[2].body);assert.equal(app.button('Create evidence export').props.disabled,true);}
 finally{app.driver.unmount();}
});
test('R08-UI 05 unavailable malformed mismatched or missing current report never publishes',async()=>{
 for(const value of [{...CONTEXT,status:'UNAVAILABLE'},{...CONTEXT,session_id:OTHER},{...CONTEXT,head:null},{...CONTEXT,unexpected:true}]){
  const calls=[];const app=setup(async(sid,identity,action)=>{calls.push(action);return value;});
  try{app.choose();await app.button('Create evidence export').props.onClick();app.render();assert.deepEqual(calls,['context']);assert.ok(nodes(app.panel(),n=>n.props?.role==='alert').length);}
  finally{app.driver.unmount();}
 }
});
test('R08-UI 06 source-tamper refusal and altered archive hash never trigger download',async()=>{
 for(const tamper of ['source','archive']){
  let published,clicks=0;const oldDocument=globalThis.document;globalThis.document={body:{append(){}},createElement:()=>({click(){clicks++;},remove(){}})};
  const app=setup(async(sid,identity,action,body)=>{if(action==='context')return CONTEXT;if(action==='publish'){published=receipt(body);return published;}if(action==='receipt'){if(tamper==='source')throw Error('EXPORT_SOURCE_INVALID');return published;}return new Response(new Uint8Array(PAYLOAD.length).fill(1),{headers:{'Content-Type':'application/zip'}});});
  try{app.choose();await app.button('Create evidence export').props.onClick();app.render();await app.button('Download verified export').props.onClick();app.render();assert.equal(clicks,0);assert.ok(nodes(app.panel(),n=>n.props?.role==='alert').length);}
  finally{app.driver.unmount();globalThis.document=oldDocument;}
 }
});
test('R08-UI 07 stop waiting ignores late receipt and retains exact retry without rollback claim',async()=>{
 const pending=deferred();let body,work;const app=setup(async(sid,identity,action,request)=>{if(action==='context')return CONTEXT;body=request;return pending.promise;});
 try{app.choose();work=app.button('Create evidence export').props.onClick();await settle();app.render();app.button('Stop waiting').props.onClick();app.render();assert.match(textOf(app.panel()),/may already exist/);pending.resolve(receipt(body));await work;app.render();assert.equal(nodes(app.panel(),n=>n.type==='button'&&textOf(n)==='Download verified export').length,0);await app.button('Retry exact export').props.onClick();app.render();assert.ok(app.button('Download verified export'));}
 finally{pending.resolve(body?receipt(body):null);await work;app.driver.unmount();}
});

test('R08-UI 08 early archive refusals cancel body and retain primary error',async()=>{
 for(const mode of ['type','length','missing-reader','throwing-reader','oversize']){
  let cancelled=0,clicked=0,published;
  const failure=Error('TEST_ONLY cancellation failure');
  const body={cancel(){cancelled++;return Promise.reject(failure);}};
  if(mode==='throwing-reader')body.getReader=()=>{throw Error('TEST_ONLY reader acquisition failed');};
  if(mode==='oversize')body.getReader=()=>({read:async()=>({done:false,value:new Uint8Array(PAYLOAD.length+1)}),cancel(){cancelled++;return Promise.reject(failure);},releaseLock(){}});
  const artifact={headers:new Headers({'Content-Type':mode==='type'?'text/plain':'application/zip',...(mode==='length'?{'Content-Length':'1'}:{})}),body};
  const oldDocument=globalThis.document;globalThis.document={body:{append(){}},createElement:()=>({click(){clicked++;},remove(){}})};
  const app=setup(async(_sid,_identity,action,request)=>{
   if(action==='context')return CONTEXT;
   if(action==='publish'){published=receipt(request);return published;}
   if(action==='receipt')return published;return artifact;
  });
  try{
   app.choose();await app.button('Create evidence export').props.onClick();app.render();
   await app.button('Download verified export').props.onClick();app.render();
   assert.equal(clicked,0);assert.equal(cancelled,1,'Every refused owned body is cancelled');
   const alert=nodes(app.panel(),node=>node.props?.role==='alert').map(textOf).join('');
   assert.match(alert,mode==='type'?/type is invalid/:mode==='length'?/size is invalid/:mode==='throwing-reader'?/reader acquisition failed/:mode==='oversize'?/exceeds its verified size/:/Bounded export download is unavailable/);
   assert.doesNotMatch(alert,/cancellation failure/);
  }finally{app.driver.unmount();globalThis.document=oldDocument;}
 }
});
test('R08-UI 09 operation guard survives pending ZIP read and digest until final download',async()=>{
 for(const phase of ['stream','digest']){
  let epoch=0,published,clicked=0,artifactReady=deferred(),hashReady=deferred(),hashResult=deferred(),streamController;
  const actualCrypto=globalThis.crypto,descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  const oldDocument=globalThis.document;
  globalThis.document={body:{append(){}},createElement:()=>({click(){clicked++;},remove(){}})};
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{randomUUID:actualCrypto.randomUUID.bind(actualCrypto),subtle:{digest:async(...args)=>{hashReady.resolve();return phase==='digest'?hashResult.promise:actualCrypto.subtle.digest(...args);}}}});
  const artifact=phase==='stream'?new Response(new ReadableStream({start(controller){streamController=controller;}}),{headers:{'Content-Type':'application/zip'}}):new Response(PAYLOAD,{headers:{'Content-Type':'application/zip'}});
  const app=setup(async(_sid,_identity,action,request,options)=>{
   if(options.operation&&options.operation.current===null){const bound=epoch;options.operation.current=()=>epoch===bound;}
   if(action==='context')return CONTEXT;
   if(action==='publish'){published=receipt(request);return published;}
   if(action==='receipt')return published;
   artifactReady.resolve();return artifact;
  });
  let work;
  try{
   app.choose();await app.button('Create evidence export').props.onClick();app.render();
   work=app.button('Download verified export').props.onClick();await artifactReady.promise;await settle();
   if(phase==='digest')await hashReady.promise;
   epoch+=2; // Same final identity; operation epoch is obsolete.
   if(phase==='stream'){streamController.enqueue(PAYLOAD);streamController.close();}
   else hashResult.resolve(await actualCrypto.subtle.digest('SHA-256',PAYLOAD));
   await work;app.render();
   assert.equal(clicked,0,'No stale operation may create a browser download');
   assert.doesNotMatch(textOf(app.panel()),/Verified archive download requested/);
   assert.equal(app.button('Download verified export').props.disabled,false,'Aborted task does not wedge the retained view');
  }finally{
   hashResult.resolve(await actualCrypto.subtle.digest('SHA-256',PAYLOAD));
   if(work)await work;app.driver.unmount();globalThis.document=oldDocument;
   if(descriptor)Object.defineProperty(globalThis,'crypto',descriptor);else delete globalThis.crypto;
  }
 }
});
