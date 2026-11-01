import React,{useEffect,useMemo,useRef,useState} from 'react';
import {
 FRAME_DIAGNOSTICS_MAX_BYTES,frameDiagnosticAt,frameDiagnosticLegend,loadFrameDiagnosticsFile,sha256LocalFile,
 validateFrameDiagnostics,validateRejectedRunEvidence,validateReviewEvidence,videoFrameAtTime,
} from './syncPlayback.js';

const FILES=[
 {id:'run',name:'run.json',label:'Native run manifest',accept:'.json'},
 {id:'normalization',name:'normalization.json',label:'Normalization record',accept:'.json'},
 {id:'sync',name:'sync.json',label:'Passed native sync report',accept:'.json'},
 {id:'cam01',name:'cam01.mp4',label:'Phone normalized MP4',accept:'.mp4,video/mp4'},
 {id:'cam02',name:'cam02.mp4',label:'Webcam normalized MP4',accept:'.mp4,video/mp4'},
];
const CAMERAS=['cam01','cam02'];
const DIAGNOSTIC_FIELDS=[['likelihood','Likelihood'],['reprojection_px','Reprojection px'],['camera_depth','Camera depth']];
const diagnosticValue=value=>typeof value==='number'?value.toFixed(3):'missing (not recorded)';

const REJECTED_FILES=[
 {id:'run',label:'Rejected native run manifest',name:/^run\.json$/i,aria:'Select rejected run.json',required:true},
 {id:'quality',label:'Rejected quality report',name:/^quality\.json$/i,aria:'Select rejected quality.json',required:true},
 {id:'diagnostics',label:'Run-bound reconstruction frame diagnostics',name:/^reconstruction-frames(\.[0-9a-f]{64})?\.json$/i,
  aria:'Select rejected frame diagnostics',required:true},
 {id:'preflight',label:'Preflight record (optional)',name:/^preflight\.json$/i,aria:'Select rejected preflight.json (optional)',required:false},
 {id:'normalization',label:'Normalization record (optional; required for video)',name:/^normalization\.json$/i,
  aria:'Select rejected normalization.json (optional)',required:false},
];
const VERIFICATION_TEXT={BYTES_MATCHED:'BYTES MATCHED (hashed in this browser)',NOT_OBSERVED:'NOT OBSERVED by this browser',UNVERIFIED:'UNVERIFIED'};
const SYNCHRONIZED_FPS=30;

// Distinct child components so each mode owns its own hooks; a mode switch remounts.
export default function VerifiedReview(props){
 return props.mode==='rejected'?<RejectedReview {...props}/>:<PassedReview {...props}/>;
}

function RejectedReview({sessionId='',seconds,onSeek}){
 const [selected,setSelected]=useState({});
 const [verified,setVerified]=useState(null);
 const [checking,setChecking]=useState('');
 const [error,setError]=useState('');
 const [urls,setUrls]=useState({});
 const [videoState,setVideoState]=useState({});
 const generation=useRef(0);
 const ownedUrls=useRef({});
 const videoRequests=useRef({cam01:0,cam02:0});
 function releaseUrls(){
  for(const url of Object.values(ownedUrls.current))URL.revokeObjectURL(url);
  ownedUrls.current={};
  videoRequests.current={cam01:videoRequests.current.cam01+1,cam02:videoRequests.current.cam02+1};
 }
 function reset(){
  generation.current++;
  releaseUrls();setVerified(null);setUrls({});setVideoState({});setError('');setChecking('');
 }
 // A session change invalidates every pending read and clears the previous session's evidence and videos.
 useEffect(()=>{
  generation.current++;
  releaseUrls();
  setSelected({});setVerified(null);setUrls({});setVideoState({});setError('');setChecking('');
  return ()=>{generation.current++;releaseUrls()};
 },[sessionId]);

 async function loadEvidence(){
  const request=++generation.current;
  releaseUrls();setVerified(null);setUrls({});setVideoState({});setError('');
  setChecking('Hashing local rejected evidence — nothing is uploaded...');
  try{
   for(const spec of REJECTED_FILES){
    const file=selected[spec.id];
    if(spec.required&&!file)throw Error('Choose the rejected '+spec.label+' from the same session.');
    if(file&&!spec.name.test(String(file.name)))throw Error('Choose the exact '+spec.label+' file.');
   }
   // Every selected JSON is size-checked before any file is read, hashed or parsed.
   for(const spec of REJECTED_FILES){
    const file=selected[spec.id];
    if(file&&(!Number.isInteger(file.size)||file.size<1||file.size>FRAME_DIAGNOSTICS_MAX_BYTES))
     throw Error(spec.label+' size must be 1 to '+FRAME_DIAGNOSTICS_MAX_BYTES+' bytes; nothing was read.');
   }
   const loaded={};
   for(const spec of REJECTED_FILES){
    if(!selected[spec.id])continue;
    loaded[spec.id]=await loadFrameDiagnosticsFile(selected[spec.id],spec.label);
    if(request!==generation.current)return;
   }
   const run=loaded.run.document,quality=loaded.quality.document,qualitySha256=loaded.quality.sha256;
   const {sha256:diagnosticsSha256,document:diagnostics}=loaded.diagnostics;
   const observed={};
   for(const id of ['preflight','normalization'])if(loaded[id])observed[id]=loaded[id].sha256;
   const normalization=loaded.normalization?.document??null;
   const result=validateRejectedRunEvidence({run,quality,qualitySha256,diagnostics,diagnosticsSha256,
    sessionId:sessionId||run?.session_id,observed,normalization});
   if(request!==generation.current)return;
   setVerified(result);
  }catch(exception){
   if(request===generation.current)setError(exception instanceof Error?exception.message:String(exception));
  }finally{
   if(request===generation.current)setChecking('');
  }
 }

 // A URL exists only for bytes hashed here and equal to the observed normalization output digest.
 async function loadVideo(camera,file){
  const owner=generation.current,request=++videoRequests.current[camera];
  const previous=ownedUrls.current[camera];
  if(previous){URL.revokeObjectURL(previous);delete ownedUrls.current[camera];}
  setUrls(current=>({...current,[camera]:undefined}));
  const expected=verified?.normalizedOutputs?.[camera]?.sha256;
  if(!file||!expected){setVideoState(current=>({...current,[camera]:'VIDEO UNAVAILABLE: no byte-matched local '+camera+' video'}));return;}
  setVideoState(current=>({...current,[camera]:'Hashing local '+camera+' video — nothing is uploaded...'}));
  try{
   const digest=await sha256LocalFile(file);
   if(owner!==generation.current||request!==videoRequests.current[camera])return;
   if(digest!==expected){
    setVideoState(current=>({...current,[camera]:'VIDEO UNAVAILABLE: '+camera+' bytes differ from the run-bound normalized output'}));
    return;
   }
   const url=URL.createObjectURL(file);
   ownedUrls.current[camera]=url;
   setUrls(current=>({...current,[camera]:url}));
   setVideoState(current=>({...current,[camera]:camera+' bytes matched the normalized output digest; frame alignment UNVERIFIED'}));
  }catch(exception){
   if(owner===generation.current&&request===videoRequests.current[camera]){
    setVideoState(current=>({...current,[camera]:'VIDEO UNAVAILABLE: '+(exception instanceof Error?exception.message:String(exception))}));
   }
  }
 }

 const frame=Number.isFinite(seconds)?Math.round(seconds*SYNCHRONIZED_FPS):null;
 const record=verified?.diagnostics?.available&&frame!==null?verified.diagnostics.byIndex?.get(frame)??null:null;
 return <section className="panel verified-review rejected-review" aria-labelledby="rejected-review-heading">
  <div className="panelhead">
   <span id="rejected-review-heading">Rejected run review</span>
   <span>{verified?verified.label:'LOCAL EVIDENCE REQUIRED'}</span>
  </div>
  <div className="review-content">
   <p className="review-explain">
    Select the rejected run manifest, its quality report and its run-bound frame diagnostics. Files stay on your
    computer. A rejected run is never usable for measurement and produces no motion export.
   </p>
   {!verified&&<div className="review-files">
    {REJECTED_FILES.map(spec=><label key={spec.id} className="review-file">
     <span>{spec.label}</span>
     <input type="file" accept=".json,application/json" aria-label={spec.aria}
      onChange={event=>{
       const file=event.target.files?.[0]??null;
       event.target.value='';
       setSelected(current=>({...current,[spec.id]:file}));
       reset();
      }}/>
     <small>{selected[spec.id]?.name??'not selected'}</small>
    </label>)}
    <button type="button" className="play" onClick={loadEvidence} disabled={!!checking}>
     {checking?'Verifying local files...':'Verify rejected evidence'}
    </button>
   </div>}
   {checking&&<p className="review-loading" role="status">{checking}</p>}
   {error&&<p className="error" role="alert">{error}</p>}
   {verified&&<div className="review-ready">
    <p className="error" role="status"><strong>{verified.label}</strong></p>
    <div className="review-proof">
     <span>Session: <strong>{verified.sessionId}</strong></span>
     <span>Status: <strong>{verified.status}</strong></span>
     <button type="button" onClick={reset}>Unload rejected evidence</button>
    </div>
    <div role="group" aria-label="Stored rejection reasons">
     <strong>Stored rejection reasons</strong>
     <ul>{verified.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>
    </div>
    <table className="review-diagnostic-table">
     <caption>Browser verification of bound records</caption>
     <thead><tr><th>Record</th><th>Browser verification</th></tr></thead>
     <tbody>{Object.entries(verified.verification).map(([key,value])=><tr key={key}>
      <td>{key}</td><td>{VERIFICATION_TEXT[value]??'UNVERIFIED'}</td>
     </tr>)}</tbody>
    </table>
    <div className="review-video-grid">
     {CAMERAS.map(camera=><div className="review-camera" key={camera}>
      <div className="review-camera-head">
       <strong>{camera==='cam01'?'Phone view':'Webcam view'}</strong>
       <span>Synchronization offsets NOT OBSERVED</span>
      </div>
      {verified.normalizedOutputs?.[camera]?
       <label className="review-file">
        <span>{camera+' normalized MP4 (shown only when its bytes match the bound digest)'}</span>
        <input type="file" accept=".mp4,video/mp4" aria-label={'Select rejected '+camera+' video'}
         onChange={event=>{
          const file=event.target.files?.[0]??null;
          event.target.value='';
          return loadVideo(camera,file);
         }}/>
       </label>:
       <p className="review-explain">{'VIDEO UNAVAILABLE: normalization.json bytes NOT OBSERVED, so no '+camera+' digest is bound'}</p>}
      <div className="review-media">
       {urls[camera]?
        <video src={urls[camera]} muted playsInline controls preload="metadata"
         aria-label={'Rejected run '+camera+' byte-matched normalized footage'}/>:
        <div className="review-no-frame">{videoState[camera]??'VIDEO UNAVAILABLE: no byte-matched local '+camera+' video'}</div>}
      </div>
      {urls[camera]&&<p className="review-frame">{videoState[camera]}</p>}
     </div>)}
    </div>
    <div className="review-diagnostics" aria-label="Rejected reconstruction frame diagnostics">
     <p className="review-explain">
      {'Values are model-derived reconstruction estimates and research diagnostics, not measured physical truth. '+
       'Physical accuracy UNVERIFIED; camera depth units UNVERIFIED; decoded frame equality UNVERIFIED.'}
     </p>
     <div role="group" aria-label="Rejected frames">
      <strong>Rejected frames</strong>
      {verified.diagnostics.rejectedFrames.length?verified.diagnostics.rejectedFrames.map(index=>
       <button type="button" key={index} aria-label={'Review rejected synchronized frame '+index}
        onClick={()=>onSeek?.(index/SYNCHRONIZED_FPS)}>{'Frame '+index}</button>):
       <span>{' None stored as rejected under the existing reconstruction criteria'}</span>}
     </div>
     {record===null?
      <p className="review-frame">{'Synchronized frame '+(frame??'unknown')+': diagnostic missing (not recorded)'}</p>:
      <table className="review-diagnostic-table">
       <caption>{'Synchronized frame '+frame+(record.rejected?
        ': rejected under the existing reconstruction criteria':': meets the existing reconstruction criteria')}</caption>
       <thead><tr><th>Marker</th><th>Camera</th><th>Status</th>{DIAGNOSTIC_FIELDS.map(([key,label])=><th key={key}>{label}</th>)}</tr></thead>
       <tbody>
        {Object.entries(record.markers??{}).flatMap(([marker,stored])=>CAMERAS.map(camera=>{
         const cell=stored?.cameras?.[camera]??{};
         return <tr key={marker+camera}>
          <td>{marker}</td><td>{camera}</td><td>{cell.status??'missing (not recorded)'}</td>
          {DIAGNOSTIC_FIELDS.map(([key])=><td key={key}>{diagnosticValue(cell[key])}</td>)}
         </tr>;
        }))}
       </tbody>
      </table>}
     <ul className="review-legend">
      {frameDiagnosticLegend().map(entry=><li key={entry.id}>{entry.label}</li>)}
     </ul>
    </div>
    <p className="review-limit">{verified.label+'. This read-only review offers no motion, angle or export output.'}</p>
   </div>}
  </div>
 </section>;
}

function PassedReview({motion,seconds,playing,onSeek}){
 const [selected,setSelected]=useState({});
 const [verified,setVerified]=useState(null);
 const [urls,setUrls]=useState({});
 const [checking,setChecking]=useState('');
 const [error,setError]=useState('');
 const [readyVersion,setReadyVersion]=useState(0);
 const videos=useRef({cam01:null,cam02:null});
 const generation=useRef(0);
 const ownedUrls=useRef({});
 const [diagnostics,setDiagnostics]=useState(null);
 const [diagnosticError,setDiagnosticError]=useState('');
 const diagnosticsRequest=useRef(0);
 function releaseUrls(){
  for(const url of Object.values(ownedUrls.current))URL.revokeObjectURL(url);
  ownedUrls.current={};
 }
 function clearDiagnostics(){
  diagnosticsRequest.current++;
  setDiagnostics(null);setDiagnosticError('');
 }
 useEffect(()=>{
  generation.current++;
  releaseUrls();clearDiagnostics();
  setSelected({});setVerified(null);setUrls({});setError('');setChecking('');
  return ()=>{generation.current++;diagnosticsRequest.current++;releaseUrls()};
 },[motion]);

 const real=motion.schema==='kinelab.motion.v2'&&motion.kind==='real';
 const mapping=useMemo(()=>{
  if(!verified)return null;
  try{return videoFrameAtTime(verified,seconds)}
  catch{return null}
 },[verified,seconds]);
 const diagnosticAt=useMemo(()=>{
  if(!verified||!diagnostics?.available)return null;
  try{return frameDiagnosticAt(diagnostics,verified,seconds)}
  catch{return null}
 },[diagnostics,verified,seconds]);

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
  releaseUrls();clearDiagnostics();setError('');setVerified(null);setUrls({});
  const prepared={};
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
   for(const camera of CAMERAS)prepared[camera]=URL.createObjectURL(selected[camera]);
   if(request!==generation.current){
    Object.values(prepared).forEach(url=>URL.revokeObjectURL(url));
    return;
   }
   ownedUrls.current=prepared;
   setVerified(result);setUrls(prepared);setReadyVersion(v=>v+1);
  }catch(exception){
   for(const url of Object.values(prepared))URL.revokeObjectURL(url);
   if(request===generation.current){
    setError(exception instanceof Error?exception.message:String(exception));
   }
  }finally{
   if(request===generation.current)setChecking('');
  }
 }

 // Diagnostics belong to one verified generation and one upload; a slower
 // earlier read or a read that outlives Unload is discarded unvalidated.
 async function loadDiagnostics(file){
  clearDiagnostics();
  if(!file||!verified)return;
  const owner=generation.current,request=diagnosticsRequest.current,evidence=verified;
  try{
   const {sha256,document}=await loadFrameDiagnosticsFile(file);
   if(owner!==generation.current||request!==diagnosticsRequest.current)return;
   setDiagnostics(validateFrameDiagnostics(evidence,document,sha256));
  }catch(exception){
   if(owner===generation.current&&request===diagnosticsRequest.current){
    setDiagnosticError(exception instanceof Error?exception.message:String(exception));
   }
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
      releaseUrls();clearDiagnostics();setVerified(null);setUrls({});setError('');setChecking('');
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
     <button type="button" onClick={()=>{generation.current++;releaseUrls();clearDiagnostics();setVerified(null);setUrls({})}}>
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
    <div className="review-diagnostics" aria-label="Reconstruction frame diagnostics">
     {!verified.frameDiagnostics?
      <p className="review-explain">Frame diagnostics NOT RECORDED by this native run. The verified review above is unaffected.</p>:
      <>
       <label className="review-file">
        <span>Run-bound reconstruction frame diagnostics (research diagnostic, separate from video proof)</span>
        <input type="file" accept=".json,application/json" aria-label="Select reconstruction frame diagnostics"
         onChange={event=>{
          const file=event.target.files?.[0]??null;
          event.target.value='';
          return loadDiagnostics(file);
         }}/>
        <small>{verified.frameDiagnostics.path}</small>
       </label>
       {diagnosticError&&<p className="error" role="alert">{diagnosticError}</p>}
       {diagnostics?.available&&<>
        <p className="review-explain">
         {'Values are reconstruction estimates and research diagnostics, not measured physical truth. Camera depth units UNVERIFIED; decoded frame equality UNVERIFIED.'}
        </p>
        <p className="review-frame">{'Displayed skeleton classification: '+(diagnostics.displayedClassification??'unknown')}</p>
        <div role="group" aria-label="Rejected frames">
         <strong>Rejected frames</strong>
         {diagnostics.rejectedFrames.length?diagnostics.rejectedFrames.map(frame=>
          <button type="button" key={frame} aria-label={'Review rejected synchronized frame '+frame}
           onClick={()=>onSeek?.(frame/verified.fps)}>{'Frame '+frame}</button>):
          <span>{' None stored as rejected under the existing reconstruction criteria'}</span>}
        </div>
        {diagnosticAt&&(diagnosticAt.record===null?
         <p className="review-frame">No stored diagnostic for this timeline position</p>:
         <table className="review-diagnostic-table">
          <caption>{'Synchronized frame '+diagnosticAt.synchronizedFrame+(diagnosticAt.rejected?
           ': rejected under the existing reconstruction criteria':': meets the existing reconstruction criteria')}</caption>
          <thead><tr><th>Marker</th><th>Camera</th><th>Status</th>{DIAGNOSTIC_FIELDS.map(([key,label])=><th key={key}>{label}</th>)}</tr></thead>
          <tbody>
           {Object.entries(diagnosticAt.markers??{}).flatMap(([marker,record])=>CAMERAS.map(camera=>{
            const cell=record?.cameras?.[camera]??{};
            return <tr key={marker+camera}>
             <td>{marker}</td><td>{camera}</td><td>{cell.status??'missing (not recorded)'}</td>
             {DIAGNOSTIC_FIELDS.map(([key])=><td key={key}>{diagnosticValue(cell[key])}</td>)}
            </tr>;
           }))}
          </tbody>
         </table>)}
        <ul className="review-legend">
         {frameDiagnosticLegend().map(entry=><li key={entry.id}>{entry.label}</li>)}
        </ul>
       </>}
      </>}
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
