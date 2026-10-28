import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Canvas,useFrame,useThree} from '@react-three/fiber';
import {Grid,OrbitControls} from '@react-three/drei';
import * as THREE from 'three';
import {validateMotion,frameAtTime,angleDegrees} from './motionData.js';
import AngleChart from './AngleChart.jsx';
import VerifiedReview from './VerifiedReview.jsx';

function Rig({motion,currentFrame}){
 const meshes=useRef([]), segments=useRef([]);
 const up=useMemo(()=>new THREE.Vector3(0,1,0),[]);
 const a=useMemo(()=>new THREE.Vector3(),[]),b=useMemo(()=>new THREE.Vector3(),[]),dir=useMemo(()=>new THREE.Vector3(),[]);
 useFrame(()=>{
  const xyz=currentFrame.xyz;
  if(!xyz)return;
  meshes.current.forEach((m,i)=>{
   if(!m)return;
   const p=xyz[i];m.visible=!!(p&&p.every(Number.isFinite));
   if(m.visible)m.position.set(...p);
  });
  motion.bones.forEach(([i,j],k)=>{
   const o=segments.current[k],pi=xyz[i],pj=xyz[j];
   if(!o)return;
   o.visible=!!(pi&&pj&&pi.every(Number.isFinite)&&pj.every(Number.isFinite));
   if(!o.visible)return;
   a.fromArray(pi);b.fromArray(pj);dir.subVectors(b,a);
   o.position.copy(a).add(b).multiplyScalar(.5);
   o.scale.set(1,dir.length(),1);
   if(dir.lengthSq()>1e-8)o.quaternion.setFromUnitVectors(up,dir.normalize());
  });
 });
 return <group>
  {motion.markers.map((name,i)=><mesh key={'joint'+i} ref={el=>{meshes.current[i]=el}}>
   <sphereGeometry args={[.022,12,8]}/><meshStandardMaterial color="#1ce6ce" metalness={.45} roughness={.22} emissive="#087d70" emissiveIntensity={.55}/>
  </mesh>)}
  {motion.bones.map(([i,j],k)=><mesh key={'seg'+k} ref={el=>{segments.current[k]=el}}>
   <cylinderGeometry args={[.009,.009,1,10]}/><meshStandardMaterial color="#d98753" metalness={.46} roughness={.28}/>
  </mesh>)}
 </group>;
}

function CameraPresetHandler({preset,controlsRef}){
 const {camera}=useThree();
 useEffect(()=>{
  if(!preset)return;
  if(preset==='front'){
   camera.position.set(0,1.0,3.2);
   controlsRef.current?.target?.set(0,1.0,0);
  }else if(preset==='side'){
   camera.position.set(3.2,1.0,0);
   controlsRef.current?.target?.set(0,1.0,0);
  }else if(preset==='top'){
   camera.position.set(0,4.2,0.01);
   controlsRef.current?.target?.set(0,0,0);
  }else if(preset==='iso'){
   camera.position.set(2.3,1.9,3.3);
   controlsRef.current?.target?.set(0,1.0,0);
  }
  controlsRef.current?.update();
 },[preset,camera,controlsRef]);
 return null;
}

function useMotion(token){
 const [data,setData]=useState(null),[error,setError]=useState(''),[source,setSource]=useState('demo');
 const generation=useRef(0);
 useEffect(()=>{
  const abort=new AbortController(),request=generation.current;
  fetch('/motion/demo.motion.json',{signal:abort.signal}).then(r=>{if(!r.ok)throw new Error('Missing demo.motion.json: '+r.status);return r.json()}).then(d=>{
   if(request===generation.current)setData(validateMotion(d));
  }).catch(e=>{if(e.name!=='AbortError'&&request===generation.current)setError(String(e.message||e))});
  return ()=>abort.abort();
 },[]);
 const loadFile=async file=>{
  if(!file)return;
  const request=++generation.current;
  setData(null);setError('');setSource('local file');
  try{
   const loaded=validateMotion(JSON.parse(await file.text()));
   if(request===generation.current)setData(loaded);
  }catch(e){if(request===generation.current)setError(String(e.message||e));}
 };
 const loadSession=async sid=>{
  if(!sid)return;
  const request=++generation.current;
  setData(null);setError('');setSource('session: '+sid);
  try{
   const headers=token?{Authorization:'Bearer '+token}:{};
   const res=await fetch('/api/v1/sessions/'+encodeURIComponent(sid)+'/motion',{headers});
   if(!res.ok){
    const body=await res.json().catch(()=>({}));
    throw new Error(body.error||`HTTP ${res.status}`);
   }
   const loaded=validateMotion(await res.json());
   if(request===generation.current)setData(loaded);
  }catch(e){
   if(request===generation.current)setError(`Cannot load motion for ${sid}: ${e.message}`);
  }
 };
 return {data,error,source,loadFile,loadSession};
}

export default function MotionApp({sessionId='',token=''}){
 const {data,error,source,loadFile,loadSession}=useMotion(token);
 const [playing,setPlaying]=useState(()=>!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
 const [seconds,setSeconds]=useState(null);
 const [speed,setSpeed]=useState(1.0);
 const [preset,setPreset]=useState('iso');
 const controlsRef=useRef();

 useEffect(()=>{setSeconds(data?.frames[0].t??null);},[data]);
 useEffect(()=>{
  if(!data||!playing||data.frames.length<2)return;
  const first=data.frames[0].t,last=data.frames.at(-1).t,duration=last-first;
  let previous=null,id;
  const tick=now=>{
   if(previous!==null){
    const delta=((now-previous)/1000)*speed;
    setSeconds(t=>{const next=(t??first)+delta;return next>last?first+(next-first)%duration:next;});
   }
   previous=now;id=requestAnimationFrame(tick);
  };
  id=requestAnimationFrame(tick);
  return ()=>cancelAnimationFrame(id);
 },[data,playing,speed]);

 const f=data?frameAtTime(data,seconds??data.frames[0].t):null;
 const kin=data?.kinematics;
 const label=source==='demo'?'DEMO':data?.schema==='kinelab.motion.v2'?data.kind.toUpperCase():source.toUpperCase();
 const angle=key=>{
  const value=angleDegrees(kin,key,f?.t);
  return Number.isFinite(value)?value.toFixed(1)+'°':'—';
 };

 return <main className="shell">
  <div className="top"><div><div className="eyebrow">KineLab PT · Clinical Motion Systems</div><h1>Motion Analysis Lab</h1>
   <p className="sub">Local offline bundle · Pose2Sim → OpenSim (optional) · JSON → Three.js / Blender</p>
   <div style={{display:'flex',gap:12,alignItems:'center',marginTop:6,flexWrap:'wrap'}}>
    {sessionId&&<button type="button" className="uw-btn is-accent" style={{fontSize:11,padding:'4px 10px'}}
     onClick={()=>loadSession(sessionId)}>Load active: {sessionId}</button>}
    <label className="sub" style={{margin:0}}>Import motion JSON <input type="file" accept=".json,application/json"
     onChange={e=>{const file=e.target.files?.[0];e.target.value='';setPlaying(false);loadFile(file);}} /></label>
   </div>
   </div><div className="chip">● {label} / EXPLORATORY</div></div>

  <div className="uw-motion-bar">
   <div style={{display:'flex',gap:6,alignItems:'center'}}>
    <span style={{fontSize:11,color:'#85a6b0'}}>View:</span>
    <div className="uw-btn-group">
     <button type="button" className={preset==='front'?'is-active':''} onClick={()=>setPreset('front')}>Front (Coronal)</button>
     <button type="button" className={preset==='side'?'is-active':''} onClick={()=>setPreset('side')}>Side (Sagittal)</button>
     <button type="button" className={preset==='top'?'is-active':''} onClick={()=>setPreset('top')}>Top (Transverse)</button>
     <button type="button" className={preset==='iso'?'is-active':''} onClick={()=>setPreset('iso')}>3D (Isometric)</button>
    </div>
   </div>
   <div style={{display:'flex',gap:6,alignItems:'center',marginLeft:'auto'}}>
    <span style={{fontSize:11,color:'#85a6b0'}}>Speed:</span>
    <div className="uw-btn-group">
     <button type="button" className={speed===0.25?'is-active':''} onClick={()=>setSpeed(0.25)}>0.25x</button>
     <button type="button" className={speed===0.5?'is-active':''} onClick={()=>setSpeed(0.5)}>0.5x</button>
     <button type="button" className={speed===1.0?'is-active':''} onClick={()=>setSpeed(1.0)}>1.0x</button>
    </div>
   </div>
  </div>

  {!data?<div className="panel" style={{marginTop:12,padding:30}}>{error?<p className="error" role="alert">{error}</p>:'Loading local motion data…'}</div>:
  <div className="dashboard">
   <div className="panel"><div className="panelhead"><span>Three-dimensional reconstruction</span><span>OPENSim Y-Up • Meters</span></div>
    <div className="scene"><Canvas camera={{position:[2.3,1.9,3.3],fov:48,near:.02,far:80}}>
     <color attach="background" args={['#0b151c']}/><ambientLight intensity={1.45}/><directionalLight position={[3,6,4]} intensity={2.5}/>
     <Grid args={[10,10]} cellSize={.5} sectionColor="#37636a" cellColor="#214750" fadeDistance={18} fadeStrength={2}/>
     <Rig motion={data} currentFrame={f}/>
     <CameraPresetHandler preset={preset} controlsRef={controlsRef}/>
     <OrbitControls ref={controlsRef} makeDefault target={[0,1.0,0]} enableDamping minDistance={.4} maxDistance={14}/>
    </Canvas></div>
    <div className="controls"><button className="play" disabled={data.frames.length<2} onClick={()=>setPlaying(v=>!v)}>{playing?'Pause':'Play'}</button>
     <input className="timeline" type="range" aria-label="Scrub movement" min={data.frames[0].t} max={data.frames.at(-1).t}
     step="any" value={seconds??data.frames[0].t} onChange={e=>{setPlaying(false);setSeconds(Number(e.target.value))}} />
     <span className="time">{Number(f.t).toFixed(2)} s</span></div>
   </div>
   <aside className="panel"><div className="panelhead"><span>Biomechanics telemetry</span><span>{label}</span></div>
    <div className="metrics">{[['knee_angle_r','Right knee'],['knee_angle_l','Left knee'],['hip_flexion_r','Right hip'],['hip_flexion_l','Left hip']]
     .map(([key,label])=><div className="metric" key={key}><span className="metricname">{label}</span><strong className="metricval">{angle(key)}</strong></div>)}</div>
    <div className="caption">{data.frames.length} motion frames • {data.markers.length} reconstructed points • {data.bones.length} anatomical connections.
    <p>{kin?'OpenSim coordinates loaded; angular values display in degrees. Translations are not angles.':'Marker-only motion. No joint-angle coordinates are loaded.'}</p>
    <p>{data.schema==='kinelab.motion.v2'?'Session-bound export; recorded stages passed, not clinically validated.':'Legacy data has no verified session provenance.'}</p></div>
    <div className="status">For research and prototype use only. Consumer dual-camera reconstruction is not clinically validated.</div>
   </aside>
  </div>}
  {data&&<AngleChart motion={data} seconds={seconds??data.frames[0].t}
    onScrub={time=>{setPlaying(false);setSeconds(time)}}/>}
  {data&&<VerifiedReview motion={data} seconds={seconds??data.frames[0].t}
    playing={playing}/>}
 </main>;
}
