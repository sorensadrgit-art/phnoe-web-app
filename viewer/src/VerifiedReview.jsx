import React,{useEffect,useMemo,useRef,useState} from 'react';
import {sha256LocalFile,validateReviewEvidence,videoFrameAtTime} from './syncPlayback.js';

const FILES=[
 {id:'run',name:'run.json',label:'Native run manifest',accept:'.json'},
 {id:'normalization',name:'normalization.json',label:'Normalization record',accept:'.json'},
 {id:'sync',name:'sync.json',label:'Passed native sync report',accept:'.json'},
 {id:'cam01',name:'cam01.mp4',label:'Phone normalized MP4',accept:'.mp4,video/mp4'},
 {id:'cam02',name:'cam02.mp4',label:'Webcam normalized MP4',accept:'.mp4,video/mp4'},
];
const CAMERAS=['cam01','cam02'];

export default function VerifiedReview({motion,seconds,playing}){
 const [selected,setSelected]=useState({});
 const [verified,setVerified]=useState(null);
 const [urls,setUrls]=useState({});
 const [checking,setChecking]=useState('');
 const [error,setError]=useState('');
 const [readyVersion,setReadyVersion]=useState(0);
 const videos=useRef({cam01:null,cam02:null});
 const generation=useRef(0);
 useEffect(()=>{
  generation.current++;
  setSelected({});setVerified(null);setUrls({});setError('');setChecking('');
 },[motion]);
 useEffect(()=>()=>{for(const url of Object.values(urls))URL.revokeObjectURL(url)},[urls]);

 const real=motion.schema==='kinelab.motion.v2'&&motion.kind==='real';
 const mapping=useMemo(()=>{
  if(!verified)return null;
  try{return videoFrameAtTime(verified,seconds)}
  catch{return null}
 },[verified,seconds]);

 useEffect(()=>{
  if(!mapping)return;
  for(const camera of CAMERAS){
   const player=videos.current[camera],target=mapping[camera];
   if(!player||player.readyState<1)continue;
   player.pause(); // master skeleton timeline owns time; video never auto-plays independently
   if(target===null)continue;
   // The native sync record determines the target frame. Browser HTML media
   // seeking is only a preview, not proof of a decoded frame within one tick.
   if(Number.isFinite(target.videoTime)&&Math.abs(player.currentTime-target.videoTime)>.023){
    try{player.currentTime=target.videoTime}catch{/* show unavailable until metadata loads */}
   }
  }
 },[mapping,readyVersion,playing]);

 async function loadEvidence(){
  if(!real){setError('Demo or unbound motion cannot be paired with a real two-camera session.');return}
  const request=++generation.current;
  setChecking('Validating session identity and native run...');
  setError('');setVerified(null);setUrls({});
  try{
   for(const spec of FILES){
    if(!selected[spec.id]||selected[spec.id].name.toLowerCase()!==spec.name){
     throw Error('Choose the exact '+spec.name+' from the same session.');
    }
   }
   const [run,normalization,sync]=await Promise.all(
    ['run','normalization','sync'].map(id=>selected[id].text().then(JSON.parse)));
   const runHash=await sha256LocalFile(selected.run);
   if(request!==generation.current)return;
   setChecking('Hashing local phone video — nothing is uploaded...');
   const cam01=await sha256LocalFile(selected.cam01);
   if(request!==generation.current)return;
   setChecking('Hashing local webcam video — nothing is uploaded...');
   const cam02=await sha256LocalFile(selected.cam02);
   if(request!==generation.current)return;
   const result=validateReviewEvidence(
    motion,normalization,sync,run,{runHash,videoHashes:{cam01,cam02}},
   );
   const prepared={cam01:URL.createObjectURL(selected.cam01),cam02:URL.createObjectURL(selected.cam02)};
   if(request!==generation.current){
    Object.values(prepared).forEach(url=>URL.revokeObjectURL(url));
    return;
   }
   setVerified(result);setUrls(prepared);setReadyVersion(v=>v+1);
  }catch(exception){
   if(request===generation.current){
    setError(exception instanceof Error?exception.message:String(exception));
   }
  }finally{
   if(request===generation.current)setChecking('');
  }
 }

 return <section className="panel verified-review" aria-labelledby="verified-review-heading">
  <div className="panelhead">
   <span id="verified-review-heading">Synchronized dual-camera review</span>
   <span>{verified?'NATIVE SYNC RECORD PASSED':'LOCAL EVIDENCE REQUIRED'}</span>
  </div>
  <div className="review-content">
   <p className="review-explain">
    {real?
     'Select the native manifests and both normalized MP4 files from this exact session. SHA-256 checks must match the motion export before any synchronized video preview appears. Files stay on your computer.':
     'This is demo or legacy motion. No synchronized real camera pairing is claimed.'}
   </p>
   {real&&!verified&&<div className="review-files">
    {FILES.map(spec=><label key={spec.id} className="review-file">
     <span>{spec.label}</span>
     <input type="file" accept={spec.accept} aria-label={'Select '+spec.name}
      onChange={event=>{
       const file=event.target.files?.[0]??null;
       event.target.value='';
       generation.current++;
       setSelected(current=>({...current,[spec.id]:file}));
       setVerified(null);setUrls({});setError('');
      }}/>
     <small>{selected[spec.id]?.name??spec.name}</small>
    </label>)}
    <button type="button" className="play" onClick={loadEvidence} disabled={!!checking}>
     {checking?'Verifying local files...':'Verify and open both videos'}
    </button>
   </div>}
   {checking&&<p className="review-loading" role="status">{checking}</p>}
   {error&&<p className="error" role="alert">{error}</p>}
   {verified&&<div className="review-ready">
    <div className="review-proof">
     <span>Session: <strong>{verified.sessionId}</strong></span>
     <span>Native correlation: <strong>{verified.nativeCorrelation.toFixed(3)}</strong></span>
     <span>Reference: <strong>{verified.reference}</strong></span>
     <button type="button" onClick={()=>{generation.current++;setVerified(null);setUrls({})}}>
      Unload session videos
     </button>
    </div>
    <div className="review-video-grid">
     {CAMERAS.map(camera=><div className="review-camera" key={camera}>
      <div className="review-camera-head">
       <strong>{camera==='cam01'?'Phone view':'Webcam view'}</strong>
       <span>Native offset: {verified.offsets[camera]>=0?'+':''}{verified.offsets[camera]} frames</span>
      </div>
      <div className="review-media">
       <video ref={element=>{videos.current[camera]=element}}
        src={urls[camera]} muted playsInline preload="auto"
        aria-label={camera==='cam01'?'Phone normalized footage':'Webcam normalized footage'}
        onLoadedMetadata={()=>setReadyVersion(v=>v+1)}
        onError={()=>setError('The browser could not decode the verified local '+camera+' MP4.')}
       />
       {!mapping?.[camera]&&<div className="review-no-frame">No observed camera frame for this timeline position</div>}
      </div>
      <p className="review-frame">
       {mapping?.[camera]?
        'Target recorded frame '+mapping[camera].frame+
        ' · normalized timestamp '+mapping[camera].videoTime.toFixed(3)+' s':
        'Outside recorded camera coverage'}
      </p>
     </div>)}
    </div>
    <p className="review-limit">
     Motion, camera frame targets and native sync metadata share the recorded timeline. 
     Browser-decoded video frames may lag during playback or seeking; this preview is
     not an independent sub-frame synchronization measurement and is not clinically validated.
     {playing?' Pause to inspect a precise selected timeline position.':''}
    </p>
   </div>}
  </div>
 </section>;
}
