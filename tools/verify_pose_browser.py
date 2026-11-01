"""Mounted inference through generated CanvasCaptureMediaStream; real devices denied."""
import base64
from pathlib import Path

from pose_inference import PoseInference

ROOT = Path(__file__).resolve().parents[1]


def run_checks(browser, evaluate, wait_for, service, output, checks, reopen):
    service.pose_inference = PoseInference(ROOT/'dist/fullproject-20261028/model-investigation')
    assert evaluate('window.__cameraRequests') == 0
    assert evaluate("document.querySelector('.uw-btn-finish-set').disabled")
    checks['no_automatic_camera_or_measured_finish'] = True
    encoded = base64.b64encode((ROOT/'tests/fixtures/pose/generated-body.png').read_bytes()).decode()
    evaluate("""(async()=>{
 const picture=new Image();picture.src='data:image/png;base64,ENCODED';await picture.decode();
 window.__poseReplies=[];window.__cameraStops=0;
 window.__testCamera=()=>{
  const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;
  const ctx=canvas.getContext('2d');const draw=()=>{ctx.fillStyle='#f0f0f0';ctx.fillRect(0,0,640,480);if(!window.__blank)ctx.drawImage(picture,0,0);};
  draw();const timer=setInterval(draw,80);const stream=canvas.captureStream(12);
  for(const track of stream.getTracks()){const stop=track.stop.bind(track);track.stop=()=>{clearInterval(timer);window.__cameraStops++;stop();};}
  return stream;
 };
 const original=window.fetch;
 window.fetch=async(input,options)=>{
  const response=await original(input,options);
  if(!String(input).endsWith('/inference/frame'))return response;
  const body=await response.clone().json();window.__poseReplies.push(body);
  if(window.__wrongPose)body.operation_id='wrong-operation';
  if(window.__holdPose)await new Promise(resolve=>window.__releasePose=resolve);
  return new Response(JSON.stringify(body),{status:response.status,headers:{'Content-Type':'application/json'}});
 };return true;
})()""".replace('ENCODED', encoded))
    browser('find','role','button','click','--name','Start local camera','--exact')
    wait_for("document.querySelector('.uw-pose-status strong')?.textContent==='AVAILABLE'")
    initial=evaluate("window.__poseReplies.filter(r=>r.status==='AVAILABLE').at(-1)")
    assert initial['visible_landmarks'] >= 12
    assert all(p is None or p['z'] is None for p in initial['landmarks'])
    assert evaluate("document.body.textContent.includes('3D depth UNAVAILABLE')&&document.body.textContent.includes('muscle activity NOT MEASURED')")
    checks['actual_generated_frame_inference']={k:initial[k] for k in ('image_sha256','model_hashes','visible_landmarks','inference_ms','width','height')}
    browser('screenshot',str(output/'generated-camera-inference.png'))

    browser('find','role','button','click','--name','Mirror ON','--exact')
    count=evaluate('window.__poseReplies.length')
    wait_for(f'window.__poseReplies.length>{count}')
    after=evaluate("window.__poseReplies.filter(r=>r.status==='AVAILABLE').at(-1)")
    assert after['landmarks']==initial['landmarks']
    checks['mirror_changes_display_only']=True

    browser('find','role','button','click','--name','Pause tracking','--exact')
    wait_for("document.querySelector('.uw-pose-status')?.textContent.includes('PAUSED')")
    assert evaluate("document.querySelector('.uw-pose-status').textContent.includes('Left knee UNAVAILABLE')")
    browser('find','role','button','click','--name','Resume tracking','--exact')
    wait_for("document.querySelector('.uw-pose-status strong')?.textContent==='AVAILABLE'")
    checks['pause_discards_pose_and_resume_starts_new_operation']=True

    evaluate('window.__wrongPose=true')
    wait_for("document.querySelector('.uw-pose-status')?.textContent.includes('INFERENCE_FAILED')")
    assert evaluate("document.querySelector('.uw-pose-status').textContent.includes('Left knee UNAVAILABLE')")
    checks['wrong_operation_clears_metrics']=True
    evaluate('window.__wrongPose=false;window.__blank=true')
    wait_for("document.querySelector('.uw-pose-status')?.textContent.includes('NO_PERSON')")
    assert evaluate("document.querySelector('.uw-camera-viewport canvas')===null")
    checks['blank_frame_never_falls_back_to_synthetic']=True
    browser('screenshot',str(output/'no-person.png'))

    evaluate('window.__blank=false;window.__holdPose=true')
    wait_for("typeof window.__releasePose==='function'")
    browser('find','role','button','click','--name','Feed: REAL CAMERA','--exact')
    evaluate('window.__holdPose=false;window.__releasePose()')
    wait_for("document.body.textContent.includes('SYNTHETIC TEST ONLY')")
    assert evaluate("document.querySelector('.uw-pose-status')===null&&window.__cameraStops>0")
    assert service.index.conn.execute('SELECT COUNT(*) FROM recordings').fetchone()[0]==0
    checks['switched_source_discards_late_result_and_saves_no_measured_data']=True
    assert not browser('errors').get('errors',[])
