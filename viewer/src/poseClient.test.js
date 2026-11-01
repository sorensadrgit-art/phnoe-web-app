import test from 'node:test';
import assert from 'node:assert/strict';
import {createPoseClient} from './poseClient.js';
import modelManifest from '../../models/pose-models.json' with {type:'json'};
const modelHashes=Object.fromEntries(modelManifest.models.map(model=>[model.filename,model.sha256]));
const image={jpegBase64:btoa('generated-fixture'),width:320,height:240,capturedAtMs:1000};
const digest='58c3121b7182859fce5d462d2f5a5709f4ff4dfc69c7e93c715b42dd2396a00ac';
const response=(p,extra={})=>({schema_version:1,operation_id:p.operation_id,sequence:p.sequence,captured_at_ms:p.captured_at_ms,
 source:p.source,status:'UNAVAILABLE',reason:'NO_PERSON',landmarks:null,width:320,height:240,
 image_sha256:digest,model_id:modelManifest.id,model_hashes:{...modelHashes},
 coordinate_basis:'NORMALIZED_IMAGE_PLANE_2D',mirrored:false,min_confidence:.6,visible_landmarks:0,inference_ms:12,
 clinical_accuracy_verified:false,persistence:'DISABLED',...extra});
const options={token:'fixture',clock:()=>1000,hashImage:async()=>digest};
const supportedIndices=[0,2,5,7,8,11,12,13,14,15,16,23,24,25,26,27,28];
const landmarksAt=indices=>Array.from({length:33},(_,index)=>indices.includes(index)?{x:.4,y:.6,z:null,visibility:.9}:null);
async function requestResponse(extra){
 const client=createPoseClient({...options,fetchImpl:async(u,o)=>({ok:true,json:async()=>response(JSON.parse(o.body),extra)})});
 try{return await client.infer(image,'TEST_IMAGE');}finally{client.close();}
}
test('response model identity requires the exact manifest filenames and hashes',async t=>{
 const cases=[
  ['missing hashes',{model_hashes:undefined}],['null hashes',{model_hashes:null}],
  ['array hashes',{model_hashes:[]}],['missing detector',{model_hashes:{'pose.onnx':modelHashes['pose.onnx']}}],
  ['additional model',{model_hashes:{...modelHashes,'unknown.onnx':'a'.repeat(64)}}],
  ['mismatched detector',{model_hashes:{...modelHashes,'detector.onnx':'a'.repeat(64)}}],
  ['malformed pose digest',{model_hashes:{...modelHashes,'pose.onnx':'invalid'}}],
  ['wrong model ID',{model_id:'other-model'}],
 ];
 for(const [name,extra] of cases)await t.test(name,()=>assert.rejects(requestResponse(extra),/POSE_RESPONSE_INVALID/));
 assert.equal((await requestResponse({})).reason,'NO_PERSON');
});
test('available observations require supported points, exact counts and no unavailable reason',async t=>{
 const valid={status:'AVAILABLE',reason:null,landmarks:landmarksAt([0]),visible_landmarks:1};
 const cases=[
  ['no visible points',{landmarks:landmarksAt([]),visible_landmarks:0}],
  ['unsupported foot point',{landmarks:landmarksAt([31])}],
  ['incorrect count',{visible_landmarks:2}],['missing count',{visible_landmarks:undefined}],
  ['noninteger count',{visible_landmarks:1.5}],['nonfinite count',{visible_landmarks:Infinity}],
  ['unavailable reason',{reason:'NO_PERSON'}],['missing reason',{reason:undefined}],
 ];
 for(const [name,extra] of cases)await t.test(name,()=>assert.rejects(requestResponse({...valid,...extra}),/POSE_RESPONSE_INVALID/));
 assert.equal((await requestResponse(valid)).visible_landmarks,1);
 assert.equal((await requestResponse({...valid,landmarks:landmarksAt(supportedIndices),visible_landmarks:17})).visible_landmarks,17);
});
test('unavailable observations require zero points and a supported reason',async t=>{
 for(const [name,extra] of [
  ['nonzero count',{visible_landmarks:1}],['missing count',{visible_landmarks:undefined}],
  ['nonnull landmarks',{landmarks:landmarksAt([])}],['missing reason',{reason:undefined}],
  ['empty reason',{reason:''}],['unknown reason',{reason:'UNRECOGNIZED'}],
 ])await t.test(name,()=>assert.rejects(requestResponse(extra),/POSE_RESPONSE_INVALID/));
 for(const reason of ['INFERENCE_BUSY','MODELS_UNAVAILABLE','MODEL_INTEGRITY_FAILED','MODEL_RUNTIME_UNAVAILABLE',
  'MODEL_OUTPUT_INVALID','NO_PERSON','MULTIPLE_PEOPLE','MODEL_RUNTIME_ERROR','STALE_FRAME','LOW_CONFIDENCE']){
  assert.equal((await requestResponse({reason})).reason,reason);
 }
});
test('client binds response to exact frame operation and source',async()=>{
 let calls=0;
 const c=createPoseClient({...options,fetchImpl:async(url,opts)=>{calls++;assert.equal(url,'/api/v1/inference/frame');
  assert.equal(opts.headers.Authorization,'Bearer fixture');return {ok:true,json:async()=>response(JSON.parse(opts.body))};}});
 assert.equal((await c.infer(image,'TEST_IMAGE')).reason,'NO_PERSON');assert.equal(calls,1);c.close();
});
test('switched operation, source, image hash, shape and stale timestamp are rejected',async()=>{
 for(const extra of [{operation_id:'wrong'},{source:'CAMERA_FRAME'},{image_sha256:'b'.repeat(64)},
  {width:640},{captured_at_ms:999},{landmarks:[],status:'AVAILABLE'},{clinical_accuracy_verified:true}]){
  const c=createPoseClient({...options,fetchImpl:async(u,o)=>({ok:true,json:async()=>response(JSON.parse(o.body),extra)})});
  await assert.rejects(c.infer(image,'TEST_IMAGE'),/POSE_RESPONSE_INVALID/);c.close();
 }
});
test('only one request in flight and closed clients discard late responses',async()=>{
 let release;let calls=0;
 const c=createPoseClient({...options,fetchImpl:async(u,o)=>{calls++;await new Promise(r=>release=r);return {ok:true,json:async()=>response(JSON.parse(o.body))};}});
 const pending=c.infer(image,'TEST_IMAGE');await new Promise(r=>setImmediate(r));
 assert.equal(await c.infer(image,'TEST_IMAGE'),null);assert.equal(calls,1);
 c.close();release();assert.equal(await pending,null);
});
test('expired result is unavailable and request failures cannot retain an old pose',async()=>{
 let now=1000;
 const c=createPoseClient({...options,clock:()=>now,fetchImpl:async(u,o)=>{now=4000;return {ok:true,json:async()=>response(JSON.parse(o.body))};}});
 assert.equal(await c.infer(image,'TEST_IMAGE'),null);c.close();
 const failed=createPoseClient({...options,fetchImpl:async()=>({ok:false,status:409})});
 await assert.rejects(failed.infer(image,'TEST_IMAGE'),/POSE_REQUEST_FAILED/);failed.close();
});
