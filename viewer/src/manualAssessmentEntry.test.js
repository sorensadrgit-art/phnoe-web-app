// R06 guided human reference entry: generated TEST_ONLY contract fixtures.
// Import the EXISTING Reports component: before implementation, missing form is
// an assertion RED, never a future-component import failure. No annotations below
// are participant evidence. This hook driver is not DOM, StrictMode or browser proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {transformSync} from 'esbuild';
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
const SID='TEST_ONLY-manual-A', OTHER='TEST_ONLY-manual-B';
const hex=c=>c.repeat(64), CTX=hex('a'), META=hex('b'), SOURCE=hex('c');
const FORM='Manual reference entry';
const FIELDS=['annotation_origin','confirm','context_sha256','input_id','labels','metadata_context_sha256','operation_id','reviewer','source_sha256','tolerance_frames'];
// Shape copied from current manual_assessment_entry._context / API fixtures;
// digest placeholders are generated contract values, not source-file attestations.
function context(sid=SID,{metadata=META,contextHash=CTX,...extra}={}){
 return {schema:'kinelab.manual-assessment-context.v1',status:'AVAILABLE',session_id:sid,
  metadata_context_sha256:metadata,context_sha256:contextHash,origin_sha256:hex('d'),run_sha256:hex('e'),
  test_only:true,clinical_accuracy_validated:false,input_sets:[
   {input_id:hex('1'),kind:'gait',source_role:'cam01_trial',source_sha256:SOURCE,frames:120,
    trajectory_sha256:hex('2'),candidates_sha256:hex('3'),image_size:[1280,720],assumptions:{screen_forward:'right'}},
   {input_id:hex('4'),kind:'squat',source_role:'cam01_trial',source_sha256:SOURCE,frames:120,
    trajectory_sha256:hex('5'),candidates_sha256:hex('6'),image_size:[1280,720],assumptions:{activity:'operator_confirmed_squat',camera_view:'side'}}],
  assessments:[],unavailable_assessments:[],...extra};
}
function row(id=SID,metadataContext=META){
 const metadata={schema:'kinelab.session-metadata.v1',subject_id:'sub-'+ '1'.repeat(32),operator_id:'op-'+ '2'.repeat(32),
  task_id:'TEST_ONLY-task',protocol_id:'TEST_ONLY-protocol',protocol_version:'1',laterality:'bilateral',
  confirmed:true,confirmed_at:'2026-10-29T13:00:00+00:00'};
 return {id,kind:'real',status:'registered',metadata_context_sha256:metadataContext,effective_metadata:metadata,
  metadata_state:{schema:'kinelab.session-metadata-state.v1',session_id:id,status:'AVAILABLE',metadata,
   initial_metadata:metadata,origin:{path:'session.json',sha256:hex('d')},head:null,context_sha256:metadataContext,
   reason:'TEST_ONLY verified-contract fixture; no physical or clinical evidence'}};
}
function receipt(sid,body){
 return {schema:'kinelab.manual-assessment-entry-receipt.v1',session_id:sid,operation_id:body.operation_id,
  metadata_context_sha256:body.metadata_context_sha256,
  descriptor:{path:'exports/manual-entry-'+body.operation_id+'.manual-assessment.json',sha256:hex('9')},
  test_only:true,clinical_accuracy_validated:false};
}
function props(overrides={}){
 return {sessions:[row(),row(OTHER)],selectedSession:SID,reports:[],busy:'',onSelectSession(){},
  onDownloadReport(){},onGenerateReports(){},onCompareSessions:async()=>({}),onCreateBackup(){},onRestoreBackup(){},onOpenFolder(){},
  onLoadManualAssessmentContext:async sid=>context(sid),
  onPublishManualAssessment:async(sid,body)=>receipt(sid,body),...overrides};
}
function form(tree){const result=nodes(tree,n=>n.type==='form'&&n.props['aria-label']===FORM)[0];
 assert.ok(result,'R06-UI MISSING: accessible Manual reference entry form in actual ReportStudio');return result;}
function field(tree,name){const result=nodes(form(tree),n=>n.props?.name===name)[0];
 assert.ok(result,'R06-UI MISSING field '+name);return result;}
function button(tree,label){const result=nodes(form(tree),n=>n.type==='button'&&textOf(n).trim()===label)[0];
 assert.ok(result,'R06-UI MISSING button '+label);return result;}
function submitButton(tree){const result=nodes(form(tree),n=>n.type==='button'&&n.props.type==='submit')[0];
 assert.ok(result,'R06-UI MISSING submit button');return result;}
function change(app,tree,name,value){const control=field(tree,name);assert.equal(!!control.props.disabled,false,name+' unexpectedly disabled');
 control.props.onChange({target:{value,checked:value===true}});return app.render();}
async function settle(app){let tree;for(let i=0;i<5;i++){await Promise.resolve();tree=app.render();app.effects();}return app.render();}
async function boot(values=props()){
 const app=mounted('./ReportStudio.jsx',values);let tree=app.render();app.effects();tree=await settle(app);
 form(tree);return {app,tree,values};
}
function annotate(app,tree,kind='gait'){
 tree=change(app,tree,'manual_input_id',hex(kind==='gait'?'1':'4'));
 button(tree,'Add annotation').props.onClick();tree=app.render();
 if(kind==='gait'){
  tree=change(app,tree,'manual_frame_0','50');tree=change(app,tree,'manual_side_0','left');tree=change(app,tree,'manual_event_0','initial_contact');
 }else{tree=change(app,tree,'manual_start_0','50');tree=change(app,tree,'manual_bottom_0','73');tree=change(app,tree,'manual_end_0','97');}
 tree=change(app,tree,'manual_reviewer','TEST_ONLY human-declaration fixture');
 tree=change(app,tree,'manual_tolerance_frames','3');
 tree=change(app,tree,'manual_human_observed',true);
 return change(app,tree,'manual_confirmed',true);
}
async function publish(app,tree){assert.equal(!!submitButton(tree).props.disabled,false,'Valid manual declaration must enable publication');
 await form(tree).props.onSubmit({preventDefault(){}});return settle(app);}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject};}

test('R06-UI-01 actual input context is labelled TEST_ONLY and never prepopulates human observations',async()=>{
 const loads=[];const {app,tree}=await boot(props({onLoadManualAssessmentContext:async sid=>{loads.push(sid);return context(sid);}}));
 assert.deepEqual(loads,[SID]);const section=textOf(form(tree));
 assert.match(section,/TEST_ONLY/);assert.match(section,/physical.{0,30}unverified|unverified.{0,30}physical/i);
 assert.match(section,/clinical.{0,30}unverified|unverified.{0,30}clinical/i);
 assert.match(section,/cam01_trial/);assert.match(section,/120/);assert.match(section,new RegExp(SOURCE));
 for(const name of ['manual_input_id','manual_reviewer','manual_tolerance_frames'])assert.equal(field(tree,name).props.value,'');
 assert.equal(!!field(tree,'manual_human_observed').props.checked,false);assert.equal(!!field(tree,'manual_confirmed').props.checked,false);
 assert.equal(nodes(form(tree),n=>/^manual_(frame|start|bottom|end)_\d+$/.test(n.props?.name??'')).length,0);
 assert.equal(!!submitButton(tree).props.disabled,true);app.unmount();
});
test('R06-UI-02 explicit gait observation submits exact CAS envelope and bound readback receipt',async()=>{
 const sent=[];const {app,tree}=await boot(props({onPublishManualAssessment:async(sid,body)=>{sent.push({sid,body});return receipt(sid,body);}}));
 let current=annotate(app,tree);current=await publish(app,current);assert.equal(sent.length,1);
 const {sid,body}=sent[0];assert.equal(sid,SID);assert.deepEqual(Object.keys(body).sort(),FIELDS);
 assert.match(body.operation_id,/^[0-9a-f]{32}$/);assert.equal(body.context_sha256,CTX);assert.equal(body.metadata_context_sha256,META);
 assert.equal(body.input_id,hex('1'));assert.equal(body.source_sha256,SOURCE);assert.equal(body.annotation_origin,'human_observed_video_frames');
 assert.deepEqual(body.labels,[{frame_index:50,side:'left',event_type:'initial_contact'}]);assert.equal(body.tolerance_frames,3);
 assert.equal(body.reviewer,'TEST_ONLY human-declaration fixture');assert.equal(body.confirm,true);
 assert.match(textOf(form(current)),new RegExp('manual-entry-'+body.operation_id));assert.match(textOf(form(current)),/TEST_ONLY/);app.unmount();
});
test('R06-UI-03 squat observation requires integer ordered nonoverlapping source-frame intervals',async()=>{
 const sent=[];const {app,tree}=await boot(props({onPublishManualAssessment:async(sid,body)=>{sent.push(body);return receipt(sid,body);}}));
 let current=annotate(app,tree,'squat');
 for(const [name,bad] of [['manual_start_0','50.5'],['manual_bottom_0','50'],['manual_end_0','120']]){
  current=change(app,current,name,bad);assert.equal(!!submitButton(current).props.disabled,true);
  current=change(app,current,name,{manual_start_0:'50',manual_bottom_0:'73',manual_end_0:'97'}[name]);
 }
 button(current,'Add annotation').props.onClick();current=app.render();
 current=change(app,current,'manual_start_1','90');current=change(app,current,'manual_bottom_1','100');current=change(app,current,'manual_end_1','110');
 assert.equal(!!submitButton(current).props.disabled,true,'Overlapping observed repetitions must refuse');
 button(current,'Remove annotation 2').props.onClick();current=app.render();
 current=change(app,current,'manual_human_observed',true);current=change(app,current,'manual_confirmed',true);current=await publish(app,current);
 assert.equal(sent.length,1);assert.deepEqual(sent[0].labels,[{start_frame:50,bottom_frame:73,end_frame:97}]);app.unmount();
});
test('R06-UI-04 reviewer declaration tolerance and confirmation are deliberate and editing resets confirmation',async()=>{
 const {app,tree}=await boot();let current=annotate(app,tree);
 for(const [name,value] of [['manual_reviewer',''],['manual_tolerance_frames',''],['manual_tolerance_frames','16'],['manual_tolerance_frames','1.5'],['manual_human_observed',false],['manual_confirmed',false]]){
  current=change(app,current,name,value);assert.equal(!!submitButton(current).props.disabled,true);
  current=change(app,current,'manual_reviewer','TEST_ONLY human-declaration fixture');current=change(app,current,'manual_tolerance_frames','3');
  current=change(app,current,'manual_human_observed',true);current=change(app,current,'manual_confirmed',true);
 }
 current=change(app,current,'manual_frame_0','51');assert.equal(!!field(current,'manual_confirmed').props.checked,false);
 assert.equal(!!submitButton(current).props.disabled,true);app.unmount();
});
test('R06-UI-05 session change discards visible A state and ignores late A context publication and errors',async()=>{
 for(const lateKind of ['context','success','error']){
  const late=deferred(),sent=[];let loads=0;
  const values=props({onLoadManualAssessmentContext:sid=>{loads++;return sid===SID&&lateKind==='context'?late.promise:Promise.resolve(context(sid));},
   onPublishManualAssessment:(sid,body)=>{sent.push({sid,body});return late.promise;}});
  const app=mounted('./ReportStudio.jsx',values);let current=app.render();app.effects();current=await settle(app);form(current);
  let pending;
  if(lateKind!=='context'){current=annotate(app,current);pending=form(current).props.onSubmit({preventDefault(){}});}
  current=app.render({...values,selectedSession:OTHER});app.effects();current=await settle(app);
  if(lateKind==='context')late.resolve(context(SID));else if(lateKind==='success')late.resolve(receipt(SID,sent[0].body));else late.reject(new Error('TEST_ONLY late A failure'));
  if(pending)await pending;current=await settle(app);const visible=textOf(form(current));
  assert.doesNotMatch(visible,/TEST_ONLY late A failure|manual-entry-/);assert.equal(field(current,'manual_reviewer').props.value,'');
  assert.equal(!!field(current,'manual_confirmed').props.checked,false);assert.ok(loads>=2);app.unmount();
 }
});
test('R06-UI-06 same-session metadata revision invalidates old context and cannot silently rebind annotations',async()=>{
 const sent=[];let currentContext=context();const values=props({onLoadManualAssessmentContext:async()=>currentContext,onPublishManualAssessment:async(sid,body)=>{sent.push(body);return receipt(sid,body);}});
 const {app,tree}=await boot(values);let current=annotate(app,tree);currentContext=context(SID,{metadata:hex('f'),contextHash:hex('7')});
 current=app.render({...values,sessions:[row(SID,hex('f')),row(OTHER)]});
 assert.equal(!!submitButton(current).props.disabled,true,'Stale confirmation must be hidden before effects');app.effects();current=await settle(app);
 assert.equal(!!field(current,'manual_confirmed').props.checked,false);assert.equal(!!submitButton(current).props.disabled,true);
 assert.equal(sent.length,0);app.unmount();
});
test('R06-UI-07 busy publication is single-flight and explicit exact retry retains operation and request bytes',async()=>{
 const sent=[],held=deferred();let calls=0;
 const {app,tree,values}=await boot(props({onPublishManualAssessment:(sid,body)=>{sent.push({sid,body:structuredClone(body)});return ++calls===1?held.promise:Promise.resolve(receipt(sid,body));}}));
 let current=annotate(app,tree);current=app.render({...values,busy:'capture'});assert.equal(!!submitButton(current).props.disabled,true);
 current=app.render(values);const pending=form(current).props.onSubmit({preventDefault(){}});current=app.render();
 assert.equal(!!submitButton(current).props.disabled,true);await form(current).props.onSubmit({preventDefault(){}});assert.equal(sent.length,1);
 held.reject(new Error('MANUAL_ASSESSMENT_BUSY'));await pending;current=await settle(app);
 assert.match(textOf(form(current)),/MANUAL_ASSESSMENT_BUSY/);assert.equal(field(current,'manual_reviewer').props.value,'TEST_ONLY human-declaration fixture');
 current=await publish(app,current);assert.equal(sent.length,2);assert.deepEqual(sent[1],sent[0]);app.unmount();
});
test('R06-UI-08 unavailable malformed mismatched contexts and backend refusals never manufacture receipts',async()=>{
 for(const supplied of [{...context(),status:'UNAVAILABLE'},context(OTHER),{...context(),metadata_context_sha256:'BAD'},null]){
  const sent=[];const {app,tree}=await boot(props({onLoadManualAssessmentContext:async()=>supplied,onPublishManualAssessment:async(...args)=>sent.push(args)}));
  assert.equal(!!submitButton(tree).props.disabled,true);assert.match(textOf(form(tree)),/unavailable/i);assert.equal(sent.length,0);app.unmount();
 }
 for(const reason of ['MANUAL_ASSESSMENT_CONTEXT_CHANGED','MANUAL_ASSESSMENT_REPORT_IMMUTABLE','MANUAL_ASSESSMENT_UNAVAILABLE']){
  const {app,tree}=await boot(props({onPublishManualAssessment:async()=>{throw new Error(reason);}}));let current=annotate(app,tree);current=await publish(app,current);
  const alerts=nodes(form(current),n=>n.props?.role==='alert');assert.ok(alerts.some(n=>textOf(n).includes(reason)));
  assert.doesNotMatch(textOf(form(current)),/manual-entry-[0-9a-f]{32}/);assert.equal(field(current,'manual_reviewer').props.value,'TEST_ONLY human-declaration fixture');app.unmount();
 }
});
