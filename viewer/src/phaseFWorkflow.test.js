import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {transformSync} from 'esbuild';

const directory=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
function moduleAt(filename,overrides={}){
 const file=path.resolve(directory,filename),module={exports:{}};
 const source=transformSync(fs.readFileSync(file,'utf8'),{loader:'jsx',format:'cjs'}).code;
 new Function('require','module','exports',source)(name=>overrides[name]||
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
// Generated hook/effect fixture: it runs actual component handlers and cleanup,
// not a browser, network request, real-file decoder or evidence validator.
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
const Guided=moduleAt('./GuidedCaptureWizard.jsx').default;
test('guided registration does not claim validated files without affirmative complete detail',()=>{
 for(const detail of [null,{roles:[],issues:[],ready_to_register:false},{roles:[],issues:[],ready_to_register:true}]){
  const html=renderToStaticMarkup(React.createElement(Guided,{detail}));
  assert.doesNotMatch(html,/All 6 role files probed and valid/);
  assert.match(html,/unavailable|pending|not ready/i);
 }
 const roles=Array.from({length:6},(_,i)=>({role:'generated_'+i}));
 const html=renderToStaticMarkup(React.createElement(Guided,{detail:{roles,issues:[],ready_to_register:true}}));
 assert.match(html,/All 6 role files probed and valid/);
});

const sessions=[{id:'alpha-real',kind:'real',status:'draft'},{id:'beta-demo',kind:'demo',status:'draft'}];
const reportProps={sessions,reports:[],selectedSession:'alpha-real',onSelectSession:()=>{},onCompareSessions:async()=>{}};
// Exact generated API identities and observation tokens; cache observations do not verify evidence.
const comparisonRows=JSON.parse(fs.readFileSync(path.join(directory,'fixtures/comparisonRevision.generated.json'),'utf8')).before_rows;
const comparisonProps={...reportProps,sessions:comparisonRows,selectedSession:'a'};
function history(tree){return nodes(tree,x=>x.props?.['aria-label']==='Session history')[0];}
test('report history renders filtered sessions and selects the chosen session',()=>{
 const selected=[];const app=mounted('./ReportStudio.jsx',{...reportProps,onSelectSession:id=>selected.push(id)});
 let tree=app.render();app.effects();
 assert.ok(history(tree),'history has an accessible region');
 assert.match(textOf(history(tree)),/alpha-real/);
 assert.match(textOf(history(tree)),/beta-demo/);
 nodes(tree,x=>x.type==='input'&&x.props.placeholder==='Filter by session ID...')[0].props.onChange({target:{value:'beta'}});
 tree=app.render();app.effects();
 assert.doesNotMatch(textOf(history(tree)),/alpha-real/);
 const row=nodes(history(tree),x=>x.type==='button')[0];row.props.onClick();
 assert.deepEqual(selected,['beta-demo']);
 nodes(tree,x=>x.type==='input'&&x.props.placeholder==='Filter by session ID...')[0].props.onChange({target:{value:''}});
 nodes(tree,x=>x.type==='select'&&x.props.value==='all')[0].props.onChange({target:{value:'real'}});
 tree=app.render();app.effects();
 assert.match(textOf(history(tree)),/alpha-real/);
 assert.doesNotMatch(textOf(history(tree)),/beta-demo/);
});
test('comparison rejection is visible and obsolete failures do not replace the new selection',async()=>{
 let reject;const compared=[];
 const app=mounted('./ReportStudio.jsx',{...comparisonProps,onCompareSessions:(a,b)=>{
  compared.push([a,b]);return new Promise((_,r)=>{reject=r});
 }});
 let tree=app.render();app.effects();
 nodes(nodes(tree,x=>x.type==='label'&&textOf(x).startsWith('Compare Active With:'))[0],x=>x.type==='select')[0].props.onChange({target:{value:'b'}});
 tree=app.render();app.effects();
 const button=nodes(tree,x=>x.type==='button'&&textOf(x).trim()==='Compare')[0];
 assert.equal(button.props.disabled,false);
 const comparison=button.props.onClick();
 assert.deepEqual(compared,[['a','b']]);
 reject(new Error('Generated comparison unavailable'));await comparison;
 tree=app.render();
 assert.match(textOf(nodes(tree,x=>x.props?.role==='alert'&&textOf(x).startsWith('Comparison unavailable:'))[0]),/Generated comparison unavailable/);
 app.effects();
 const stale=nodes(tree,x=>x.type==='button'&&textOf(x).trim()==='Compare')[0].props.onClick();
 assert.deepEqual(compared,[['a','b'],['a','b']]);
 tree=app.render({...comparisonProps,selectedSession:'b'});app.effects();
 reject(new Error('Stale failure'));await stale;
 tree=app.render();assert.doesNotMatch(textOf(tree),/Stale failure/);
});

function deferred(){let resolve;const promise=new Promise(r=>{resolve=r});return{promise,resolve};}
function reviewFixture(deferIndex=1){
 const deferredHash=deferred();let hashes=0;
 const app=mounted('./VerifiedReview.jsx',{motion:{schema:'kinelab.motion.v2',kind:'real'},seconds:0,playing:false},{
  './syncPlayback.js':{
   sha256LocalFile:()=>++hashes===deferIndex?deferredHash.promise:Promise.resolve('generated-hash'),
   validateReviewEvidence:()=>({sessionId:'generated',nativeCorrelation:1,reference:'cam01',offsets:{cam01:0,cam02:0}}),
   videoFrameAtTime:()=>({cam01:null,cam02:null}),
  }
 });
 let tree=app.render();app.effects();tree=app.render();app.effects();
 for(const input of nodes(tree,x=>x.type==='input')){
  input.props.onChange({target:{files:[{name:input.props['aria-label'].replace('Select ',''),text:async()=>'{}'}],value:''}});
 }
 tree=app.render();app.effects();
 return{app,deferredHash,start:()=>nodes(app.render(),x=>x.type==='button')[0].props.onClick()};
}
test('replacing a file cancels verification busy state and permits a fresh request',async()=>{
 const fixture=reviewFixture(),request=fixture.start();
 await Promise.resolve();await Promise.resolve();
 nodes(fixture.app.render(),x=>x.type==='input')[0].props.onChange({target:{files:[{name:'run.json',text:async()=>'{}'}],value:''}});
 const tree=fixture.app.render();
 assert.equal(nodes(tree,x=>x.type==='button')[0].props.disabled,false);
 fixture.deferredHash.resolve('generated-hash');await request;fixture.app.unmount();
});
test('unmount during any hash cannot create orphan video URLs',async()=>{
 const originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;let allocated=0,revoked=0;
 URL.createObjectURL=()=>{allocated++;return 'blob:generated-'+allocated};URL.revokeObjectURL=()=>revoked++;
 try{
  for(const index of [1,2,3]){
   const fixture=reviewFixture(index),request=fixture.start();
   for(let n=0;n<12;n++)await Promise.resolve();
   fixture.app.unmount();fixture.deferredHash.resolve('generated-hash');await request;
  }
  assert.equal(allocated,0);assert.equal(revoked,0);
 }finally{URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke;}
});
test('successfully opened review URLs are revoked on replacement and final unmount',async()=>{
 const originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;
 const created=[],revoked=[];
 URL.createObjectURL=()=>{const url='blob:generated-'+created.length;created.push(url);return url};
 URL.revokeObjectURL=url=>revoked.push(url);
 try{
  const fixture=reviewFixture(),request=fixture.start();fixture.deferredHash.resolve('generated-hash');await request;
  fixture.app.render();fixture.app.effects();assert.equal(created.length,2);
  const unload=nodes(fixture.app.render(),x=>x.type==='button'&&textOf(x).includes('Unload'))[0];
  unload.props.onClick();fixture.app.render();fixture.app.effects();
  assert.deepEqual(revoked,created);fixture.app.unmount();assert.equal(revoked.length,2);
 }finally{URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke;}
});

test('review URL ownership covers unmount before a render and partial allocation failure',async()=>{
 const originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;
 const created=[],revoked=[];
 let failSecond=false;
 URL.createObjectURL=()=>{
  if(failSecond && created.length===3)throw new Error('Generated URL allocation failure');
  const url='blob:generated-'+created.length;created.push(url);return url;
 };
 URL.revokeObjectURL=url=>revoked.push(url);
 try{
  const first=reviewFixture(),firstRequest=first.start();first.deferredHash.resolve('generated-hash');await firstRequest;
  first.app.unmount();assert.deepEqual(revoked,created);
  failSecond=true;
  const second=reviewFixture(),secondRequest=second.start();second.deferredHash.resolve('generated-hash');await secondRequest;
  assert.deepEqual(revoked,created);
  const tree=second.app.render();
  assert.match(textOf(nodes(tree,x=>x.props?.role==='alert')[0]),/Generated URL allocation failure/);
  assert.equal(nodes(tree,x=>x.type==='button')[0].props.disabled,false);
  second.app.unmount();assert.deepEqual(revoked,created);
 }finally{URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke;}
});

test('comparison identity mismatches are visible and the filtered empty state is explicit',async()=>{
 const compared=[];
 const app=mounted('./ReportStudio.jsx',{...comparisonProps,onCompareSessions:async(a,b)=>{
  compared.push([a,b]);return {session_1:'wrong',session_2:'b'};
 }});
 let tree=app.render();app.effects();
 nodes(nodes(tree,x=>x.type==='label'&&textOf(x).startsWith('Compare Active With:'))[0],x=>x.type==='select')[0].props.onChange({target:{value:'b'}});
 tree=app.render();app.effects();
 const button=nodes(tree,x=>x.type==='button'&&textOf(x).trim()==='Compare')[0];
 assert.equal(button.props.disabled,false);
 await button.props.onClick();
 assert.deepEqual(compared,[['a','b']]);
 tree=app.render();
 assert.match(textOf(nodes(tree,x=>x.props?.role==='alert'&&textOf(x).startsWith('Comparison unavailable:'))[0]),/Comparison identity mismatch/);
 nodes(tree,x=>x.type==='input'&&x.props.placeholder==='Filter by session ID...')[0].props.onChange({target:{value:'missing-session'}});
 tree=app.render();assert.match(textOf(history(tree)),/No sessions match these filters/);
});

const generatedSummary={source_type:'SYNTHETIC_TEST_ONLY',exerciseType:'squats'};
test('summary has a named modal dialog and generated focus lifecycle',()=>{
 const previousDocument=globalThis.document;
 const doc={activeElement:null};
 globalThis.document=doc;
 const trigger={isConnected:true,focus(){doc.activeElement=this}};
 const first={disabled:false,hidden:false,focus(){doc.activeElement=this}};
 const last={disabled:false,hidden:false,focus(){doc.activeElement=this}};
 let closes=0,showCalls=0,closeCalls=0;
 const modal={open:false,querySelectorAll:()=>[first,last],contains:el=>el===first||el===last,
  querySelector:()=>first,focus(){doc.activeElement=this},
  showModal(){showCalls++;this.open=true},close(){closeCalls++;this.open=false}};
 try{
  doc.activeElement=trigger;
  const app=mounted('./LiveSetSummaryModal.jsx',{summary:generatedSummary,onClose:()=>closes++});
  const tree=app.render(),dialog=nodes(tree,x=>x.type==='dialog'||x.props?.role==='dialog')[0];
  assert.ok(dialog,'native dialog or explicit dialog role is required');
  assert.equal(dialog.props['aria-modal'],true);
  const heading=nodes(tree,x=>x.type==='h2')[0];
  assert.equal(dialog.props['aria-labelledby'],heading.props.id);
  assert.ok(heading.props.id);
  dialog.props.ref.current=modal;app.effects();
  assert.equal(showCalls,1);assert.equal(doc.activeElement,first);
  doc.activeElement=last;let prevented=false;
  dialog.props.onKeyDown({key:'Tab',shiftKey:false,preventDefault(){prevented=true}});
  assert.equal(prevented,true);assert.equal(doc.activeElement,first);
  doc.activeElement=first;
  dialog.props.onKeyDown({key:'Tab',shiftKey:true,preventDefault(){}});
  assert.equal(doc.activeElement,last);
  dialog.props.onKeyDown({key:'Escape',preventDefault(){}});
  assert.equal(closes,1);
  app.unmount();assert.equal(closeCalls,1);assert.equal(doc.activeElement,trigger);
 }finally{if(previousDocument===undefined)delete globalThis.document;else globalThis.document=previousDocument;}
});

