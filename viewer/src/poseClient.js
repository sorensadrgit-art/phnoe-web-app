// One ephemeral operation; images and results never enter the session store.
import modelManifest from '../../models/pose-models.json' with {type:'json'};

const expectedModelHashes=modelManifest.models.map(model=>[model.filename,model.sha256]);
const supportedIndices=new Set([0,2,5,7,8,11,12,13,14,15,16,23,24,25,26,27,28]);
const unavailableReasons=new Set(['INFERENCE_BUSY','MODELS_UNAVAILABLE','MODEL_INTEGRITY_FAILED','MODEL_RUNTIME_UNAVAILABLE',
  'MODEL_OUTPUT_INVALID','NO_PERSON','MULTIPLE_PEOPLE','MODEL_RUNTIME_ERROR','STALE_FRAME','LOW_CONFIDENCE']);

function hasExpectedModelHashes(hashes) {
  return hashes!==null&&typeof hashes==='object'&&!Array.isArray(hashes)&&
    Object.keys(hashes).length===expectedModelHashes.length&&
    expectedModelHashes.every(([filename,digest])=>Object.hasOwn(hashes,filename)&&hashes[filename]===digest);
}

function hasConsistentObservation(result) {
  const {status,landmarks,visible_landmarks:count,reason}=result;
  if(status==='UNAVAILABLE')return landmarks===null&&count===0&&unavailableReasons.has(reason);
  if(status!=='AVAILABLE'||reason!==null||!Number.isInteger(count)||count<1||count>supportedIndices.size||
      !Array.isArray(landmarks)||landmarks.length!==33)return false;
  let visible=0;
  for(let index=0;index<landmarks.length;index++) {
    const point=landmarks[index];
    if(point===null)continue;
    if(!supportedIndices.has(index)||!point||typeof point!=='object'||Array.isArray(point)||
        !Number.isFinite(point.x)||!Number.isFinite(point.y)||point.x<0||point.x>=1||point.y<0||point.y>=1||
        point.z!==null||!Number.isFinite(point.visibility)||point.visibility<.6||point.visibility>1)return false;
    visible++;
  }
  return visible===count;
}

async function hashImage(base64) {
  const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
}
export function createPoseClient({token,apiPrefix='/api/v1',fetchImpl=fetch,clock=Date.now,hashImage:hash=hashImage}) {
  const operation=crypto.randomUUID();let sequence=0,busy=false,closed=false,controller=null;
  async function infer(frame,source='CAMERA_FRAME') {
    if (closed||busy) return null;
    busy=true;const seq=++sequence;controller=new AbortController();
    const timer=setTimeout(()=>controller?.abort(),2500);
    try {
      if (!frame||typeof frame.jpegBase64!=='string'||frame.jpegBase64.length>60000||
          !['CAMERA_FRAME','TEST_IMAGE'].includes(source)||!Number.isSafeInteger(frame.capturedAtMs)||
          [frame.width,frame.height].some(v=>!Number.isInteger(v)||v<32||v>640)) throw Error('POSE_INPUT_INVALID');
      const digest=await hash(frame.jpegBase64);
      if(closed) return null;
      const response=await fetchImpl(`${apiPrefix}/inference/frame`,{method:'POST',signal:controller.signal,
        headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},
        body:JSON.stringify({schema_version:1,operation_id:operation,sequence:seq,captured_at_ms:frame.capturedAtMs,source,jpeg_base64:frame.jpegBase64})});
      if(closed) return null;
      if(!response.ok) throw Error(`POSE_REQUEST_FAILED: ${response.status}`);
      const result=await response.json();
      if(closed||clock()-frame.capturedAtMs>1500) return null;
      if(!result||typeof result!=='object'||Array.isArray(result)||
        result.schema_version!==1||result.operation_id!==operation||result.sequence!==seq||result.source!==source||
        result.captured_at_ms!==frame.capturedAtMs||result.image_sha256!==digest||result.width!==frame.width||result.height!==frame.height||
        result.model_id!==modelManifest.id||!hasExpectedModelHashes(result.model_hashes)||result.coordinate_basis!=='NORMALIZED_IMAGE_PLANE_2D'||
        result.mirrored!==false||result.clinical_accuracy_verified!==false||result.persistence!=='DISABLED'||result.min_confidence!==.6||
        !Number.isFinite(result.inference_ms)||result.inference_ms<0||!hasConsistentObservation(result)) throw Error('POSE_RESPONSE_INVALID');
      return result;
    } catch(error) {
      if(closed) return null;
      throw error;
    } finally {clearTimeout(timer);busy=false;controller=null;}
  }
  return {infer,close(){closed=true;controller?.abort();}};
}
