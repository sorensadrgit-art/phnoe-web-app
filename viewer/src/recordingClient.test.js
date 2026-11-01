import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';

const fixtureHeader = () => ({schema:'kinelab.recording.v1',session_id:'synthetic-client-fixture',
 operation_id:'1'.repeat(32),subject_id:'synthetic-subject',operator_id:'synthetic-operator',
 source:{kind:'synthetic',capture_id:'2'.repeat(32),model_id:'kinelab-synthetic-33',model_version:'1',model_sha256:'a'.repeat(64)},
 protocol:{id:'squat-research-v1',version:1,exercise:'squat',side:'bilateral',target_angle_degrees:80,target_hold_ms:null},
 coordinates:{space:'image-normalized',units:'normalized',z_units:'relative',width:640,height:480,mirrored:false}});
const observation = time_ms => ({time_ms,valid:true,reasons:[],
 landmarks:Array.from({length:33},(_,i)=>[.1+(i%5)*.1,.1+Math.floor(i/5)*.1,0,.9])});
async function client(transport) {
 assert.ok(existsSync(new URL('./recordingClient.js',import.meta.url)), 'bounded recording client is required');
 const {RecordingClient}=await import('./recordingClient.js');
 return new RecordingClient({header:fixtureHeader(),request:transport});
}
const receipt = (saved=0,state='RECORDING') => ({session_id:fixtureHeader().session_id,
 operation_id:fixtureHeader().operation_id,header_sha256:'b'.repeat(64),source_kind:'synthetic',
 saved_through:saved,received_through:saved,revision:saved+1,state,
 manifest:state==='FINALIZED'?{frame_count:saved,header_sha256:'b'.repeat(64),source_kind:'synthetic'}:null});

test('backpressure stops capture with bounded memory and one in-flight request', async()=>{
 let release, entered, calls=0;
 const requestEntered=new Promise(resolve=>{entered=resolve;});
 const c=await client(async(path,body)=>{
  if(path==='/recordings')return receipt();
  calls++;entered();
  await new Promise(resolve=>{release=resolve;});
  return receipt(JSON.parse(body.frames_json).at(-1).sequence);
 });
 await c.start();
 for(let i=0;i<64;i++)assert.equal(c.enqueue(observation(i*30)),true);
 assert.equal(c.enqueue(observation(64*30)),false);
 assert.equal(c.snapshot().pendingFrames,64);
 let timeout;
 try {
  await Promise.race([requestEntered,new Promise((_,reject)=>{
   timeout=setTimeout(()=>reject(Error('Chunk transport did not enter before the test deadline')),5000);
  })]);
  assert.equal(calls,1);
  assert.match(c.snapshot().message,/BACKPRESSURE/);
 } finally {
  clearTimeout(timeout);c.close();release?.();
 }
 await c.flush();
 assert.equal(calls,1);
});

test('lost acknowledgment retries identical bytes and ID then finalizes once',async()=>{
 const chunks=[];let lost=true;
 const c=await client(async(path,body)=>{
  if(path==='/recordings')return receipt();
  if(path.endsWith('/finalize'))return receipt(body.last_sequence,'FINALIZED');
  chunks.push(structuredClone(body));
  if(lost){lost=false;throw new Error('connection lost after commit');}
  return receipt(JSON.parse(body.frames_json).at(-1).sequence);
 });
 await c.start();c.enqueue(observation(0));c.enqueue(observation(30));
 await assert.rejects(c.flush(),/connection lost/);
 assert.equal(c.snapshot().savedThrough,0);assert.equal(c.snapshot().pendingFrames,2);
 await c.retry();assert.deepEqual(chunks[0],chunks[1]);
 const done=await c.finish();assert.equal(done.state,'FINALIZED');
 assert.equal(c.enqueue(observation(60)),false);assert.equal(c.snapshot().pendingFrames,0);
});

test('wrong-session or impossible acknowledgments cannot advance saved-through',async()=>{
 for(const change of [r=>({...r,session_id:'synthetic-other'}),r=>({...r,saved_through:900})]){
  const c=await client(async path=>path==='/recordings'?receipt():change(receipt(1)));
  await c.start();c.enqueue(observation(0));
  await assert.rejects(c.flush(),/ACK_INVALID/);
  assert.equal(c.snapshot().savedThrough,0);assert.equal(c.snapshot().pendingFrames,1);
 }
});

test('invalid observations never consume a sequence or become zero measurements',async()=>{
 const c=await client(async()=>receipt());await c.start();
 for(const bad of [{...observation(0),time_ms:NaN},{...observation(0),landmarks:[]},
  {...observation(0),valid:false},{...observation(0),landmarks:null}]){
  assert.throws(()=>c.enqueue(bad),/MEASUREMENT_INVALID/);
 }
 assert.equal(c.snapshot().producedThrough,0);
 assert.equal(c.enqueue({time_ms:0,valid:false,reasons:['NO_POSE'],landmarks:null}),true);
 assert.equal(c.snapshot().producedThrough,1);c.close();
});

test('lost finalization acknowledgment retains the original completion reason on retry',async()=>{
 const finalizations=[];let lose=true;
 const c=await client(async(path,body)=>{
  if(path==='/recordings')return receipt();
  if(path.endsWith('/chunks'))return receipt(1);
  finalizations.push(structuredClone(body));
  if(lose){lose=false;throw Error('final acknowledgment lost');}
  return receipt(1,'FINALIZED');
 });
 await c.start();c.enqueue(observation(0));
 await assert.rejects(c.finish(),/final acknowledgment lost/);
 await c.retry();await c.finish();
 assert.deepEqual(finalizations[0],finalizations[1]);
});

test('partial or inconsistent chunk acknowledgments retain every pending frame',async()=>{
 for(const change of [()=>receipt(0),()=>({...receipt(1),received_through:0}),
  ()=>({...receipt(1),received_through:-1}),()=>({...receipt(1),received_through:2})]){
  const c=await client(async path=>path==='/recordings'?receipt():change());
  await c.start();c.enqueue(observation(0));
  await assert.rejects(c.flush(),/ACK_INVALID/);
  assert.equal(c.snapshot().savedThrough,0);
  assert.equal(c.snapshot().pendingFrames,1);
 }
});

test('thirty minutes at twenty samples per second stays bounded with exact final count',async()=>{
 let maximumPending=0, chunks=0, totalBytes=0;
 const c=await client(async(path,body)=>{
  if(path==='/recordings')return receipt();
  if(path.endsWith('/finalize'))return receipt(body.last_sequence,'FINALIZED');
  const frames=JSON.parse(body.frames_json);
  assert.ok(frames.length<=16);
  const bytes=new TextEncoder().encode(JSON.stringify(body)).length;
  assert.ok(bytes<64*1024);totalBytes+=bytes;chunks++;
  return receipt(frames.at(-1).sequence);
 });
 await c.start();
 for(let i=0;i<36000;i++){
  assert.equal(c.enqueue(observation(i*50)),true);
  maximumPending=Math.max(maximumPending,c.snapshot().pendingFrames);
  if((i+1)%16===0)await c.flush();
 }
 const done=await c.finish();
 assert.equal(done.manifest.frame_count,36000);
 assert.equal(c.snapshot().pendingFrames,0);
 assert.ok(maximumPending<=16);assert.equal(chunks,2250);
 assert.ok(totalBytes>64*1024);
});

test('R17 stop during pending creation never enables sampling after the real client accepts the late receipt',async()=>{
 let release, finalizations=0;
 const created=new Promise(resolve=>{release=resolve;});
 const c=await client(async path=>{
  if(path==='/recordings')return created;
  finalizations++;throw Error('An empty stopped attempt must not finalize');
 });
 const starting=c.start();let stopping;
 try{
  stopping=c.stop();
  assert.equal(c.snapshot().accepting,false);
  assert.equal(c.enqueue(observation(0)),false);
  assert.equal(c.snapshot().finalized,false);
  release(receipt());await starting;await stopping;
  assert.equal(c.snapshot().accepting,false,'Late create ACK must not restart sampling');
  assert.equal(c.enqueue(observation(30)),false);
  assert.equal(c.snapshot().producedThrough,0);
  assert.equal(c.snapshot().savedThrough,0);
  assert.equal(c.snapshot().finalized,false,'Empty draft is not fabricated finalization');
  assert.equal(finalizations,0);
 }finally{release(receipt());await Promise.allSettled([starting,stopping]);c.close();}
});

test('R17 stop immediately freezes production while a chunk ACK is pending and finalizes that exact prefix once',async()=>{
 let release, entered;const finals=[],chunks=[];
 const waiting=new Promise(resolve=>{entered=resolve;});
 const c=await client(async(path,body)=>{
  if(path==='/recordings')return receipt();
  if(path.endsWith('/finalize')){finals.push(structuredClone(body));return receipt(body.last_sequence,'FINALIZED');}
  chunks.push(structuredClone(body));entered();await new Promise(resolve=>{release=resolve;});return receipt(1);
 });
 await c.start();c.enqueue(observation(0));const flushing=c.flush();let stopping,timer;
 try{
  await Promise.race([waiting,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Chunk did not enter')),5000);})]);
  clearTimeout(timer);const before=c.snapshot();stopping=c.stop();
  assert.strictEqual(c.stop(),stopping,'Repeated stop shares the same settlement');
  assert.equal(c.snapshot().accepting,false);
  assert.equal(c.enqueue(observation(30)),false);
  assert.equal(c.snapshot().producedThrough,before.producedThrough);
  assert.equal(c.snapshot().savedThrough,before.savedThrough,'Stopping cannot invent a receipt');
  assert.equal(c.snapshot().pendingFrames,before.pendingFrames,'Pending frames remain owned');
  assert.equal(c.snapshot().finalized,false);assert.equal(finals.length,0);
  release();await flushing;await stopping;
  assert.equal(chunks.length,1);assert.equal(finals.length,1);
  assert.equal(finals[0].last_sequence,1);assert.equal(finals[0].end_reason,'capture_interrupted');
  assert.equal(c.snapshot().savedThrough,1);assert.equal(c.snapshot().pendingFrames,0);
  assert.equal(c.snapshot().finalized,true);assert.equal(c.enqueue(observation(60)),false);
 }finally{clearTimeout(timer);release?.();await Promise.allSettled([flushing,stopping]);c.close();}
});

test('R17 stopped transport failure retains identical pending bytes and never resumes on retry',async()=>{
 const chunks=[];let lose=true;
 const c=await client(async(path,body)=>{
  if(path==='/recordings')return receipt();
  if(path.endsWith('/finalize'))return receipt(body.last_sequence,'FINALIZED');
  chunks.push(structuredClone(body));if(lose){lose=false;throw Error('TEST_ONLY stopped save unavailable');}
  return receipt(1);
 });
 try{
  await c.start();c.enqueue(observation(0));await assert.rejects(c.stop(),/stopped save unavailable/);
  assert.equal(c.snapshot().accepting,false);assert.equal(c.snapshot().failed,true);
  assert.equal(c.snapshot().savedThrough,0);assert.equal(c.snapshot().pendingFrames,1);
  await c.retry();assert.deepEqual(chunks[1],chunks[0]);assert.equal(c.enqueue(observation(30)),false);
  await c.finish();assert.equal(c.snapshot().savedThrough,1);assert.equal(c.snapshot().finalized,true);
 }finally{c.close();}
});
