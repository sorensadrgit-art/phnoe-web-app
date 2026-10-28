import React, {useEffect, useMemo, useState} from 'react';
import {AbsoluteFill, continueRender, delayRender, cancelRender, useCurrentFrame, useVideoConfig, staticFile, interpolate} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js';
import {MeshoptDecoder} from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import {TextGeometry} from 'three/examples/jsm/geometries/TextGeometry.js';
import {FontLoader} from 'three/examples/jsm/loaders/FontLoader.js';
import {RoomEnvironment} from 'three/examples/jsm/environments/RoomEnvironment.js';
import fontData from 'three/examples/fonts/helvetiker_bold.typeface.json';
import demo from '../public/premium/demo.motion.json';

type Kind='about'|'experience'|'education'|'projects';
type V3=[number,number,number];
const font=new FontLoader().parse(fontData);
const TAU=Math.PI*2;

function useModel(file:string){
 const advance=useThree(s=>s.advance);
 const [handle]=useState(()=>delayRender('Load existing anatomy asset'));
 const [model,setModel]=useState<THREE.Group|null>(null);
 useEffect(()=>{let live=true;new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).load(staticFile(file),g=>{if(live)setModel(g.scene)},undefined,e=>cancelRender(e));return()=>{live=false}},[file]);
 useEffect(()=>{if(model){advance(performance.now());continueRender(handle)}},[handle,model,advance]);
 return model;
}
function usePicture(file:string){
 const advance=useThree(s=>s.advance);
 const [handle]=useState(()=>delayRender('Load existing KineLab interface'));
 const [texture,setTexture]=useState<THREE.Texture|null>(null);
 useEffect(()=>{new THREE.TextureLoader().load(staticFile(file),t=>{t.colorSpace=THREE.SRGBColorSpace;setTexture(t)},undefined,e=>cancelRender(e))},[file]);
 useEffect(()=>{if(texture){advance(performance.now());continueRender(handle)}},[handle,texture,advance]);return texture;
}

function StudioEnvironment(){
 const {gl,scene,advance}=useThree();
 useEffect(()=>{const generator=new THREE.PMREMGenerator(gl),room=new RoomEnvironment(),target=generator.fromScene(room,.04);scene.environment=target.texture;advance(performance.now());return()=>{scene.environment=null;target.dispose();generator.dispose();room.dispose()}},[gl,scene,advance]);return null;
}

function Atlas({mode,phase}:{mode:'sculpture'|'layers';phase:number}){
 const model=useModel('premium/anatomy-low.glb');
 const prepared=useMemo(()=>{
  if(!model)return null;
  const scene=model.clone(true),discard:THREE.Object3D[]=[];
  scene.traverse(o=>{
   if(!(o instanceof THREE.Mesh))return;
   if(o.name.includes('skin')){discard.push(o);return}
   o.castShadow=true;o.receiveShadow=true;
   const bone=o.name.startsWith('bone'),tendon=o.name.startsWith('tendon');
   o.material=new THREE.MeshPhysicalMaterial({color:mode==='sculpture'?'#214137':bone?'#d9cba8':tendon?'#ae7338':'#6b2434',roughness:.56,metalness:mode==='sculpture'?.15:.03,clearcoat:.12,clearcoatRoughness:.4,envMapIntensity:.45});
   o.userData.baseX=o.position.x;
  });
  discard.forEach(o=>o.removeFromParent());
  const box=new THREE.Box3().setFromObject(scene),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
  scene.position.copy(center).multiplyScalar(-1);
  return {scene,scale:3.55/Math.max(size.y,.001),height:size.y};
 },[model,mode]);
 if(!prepared)return null;
 const peel=.2+.8*Math.sin(phase*Math.PI)**2;
 if(mode==='layers')prepared.scene.traverse(o=>{if(o instanceof THREE.Mesh){const layer=o.name.startsWith('muscle')?1:o.name.startsWith('tendon')?2:0;o.position.x=o.userData.baseX+layer*prepared.height*.18*peel}});
 return <group position={mode==='sculpture'?[1.75,-.08,0]:[1.0,-.1,0]} rotation={[0,mode==='sculpture'?.3+.24*Math.sin(phase*TAU):-.35+.16*Math.sin(phase*TAU),mode==='sculpture'?.03:0]}><group scale={prepared.scale}><primitive object={prepared.scene}/></group></group>;
}

function Word({text,position,color='#f2eee4',size=.16}:{text:string;position:V3;color?:string;size?:number}){
 const geometry=useMemo(()=>new TextGeometry(text,{font,size,depth:.008,curveSegments:3}),[text,size]);
 useEffect(()=>()=>geometry.dispose(),[geometry]);
 return <mesh position={position} geometry={geometry}><meshStandardMaterial color={color} roughness={.5}/></mesh>;
}

function ExperienceObject({phase}:{phase:number}){
 const spread=.18+.24*Math.sin(phase*Math.PI)**2;
 return <group position={[1.75,-.25,0]} rotation={[.14,.1+.22*Math.sin(phase*TAU),-.07]}>
  {['U.S. ARMY','ARCADIA HYBRID LAB','CREATIVE DEVELOPMENT'].map((text,i)=>{
   const y=1.08-i*1.03;
   return <group key={text} position={[(i-1)*spread,y,(i-1)*spread]} rotation={[0,0,(i-1)*.025]}>
    <mesh castShadow receiveShadow><boxGeometry args={[3.55,.82,.17]}/><meshPhysicalMaterial color="#24292c" metalness={.82} roughness={.25} clearcoat={.55}/></mesh>
    <mesh position={[-1.63,0,.1]}><boxGeometry args={[.045,.53,.035]}/><meshStandardMaterial color="#ef7b39" emissive="#ef7b39" emissiveIntensity={.12}/></mesh>
    <Word text={text} size={i===2?.13:.15} position={[-1.45,.035,.108]}/>
    <Word text={['SERVICE BACKGROUND','GRADUATE ASSISTANT','DESIGN / CODE / MOTION'][i]} size={.072} color="#e4a881" position={[-1.44,-.19,.111]}/>
    {[-1.64,1.64].map(x=>[-.29,.29].map(y1=><mesh key={x+'-'+y1} position={[x,y1,.1]}><cylinderGeometry args={[.035,.035,.012,12]}/><meshStandardMaterial color="#a7aba6" metalness={.9} roughness={.2}/></mesh>))}
   </group>;
  })}
  {[-1.4,1.4].map(x=><mesh key={x} position={[x,0,-.25]} castShadow><cylinderGeometry args={[.065,.065,3.4,18]}/><meshStandardMaterial color="#b85b2d" metalness={.7} roughness={.3}/></mesh>)}
 </group>;
}

function Bone({a,b}:{a:V3;b:V3}){
 const av=new THREE.Vector3(...a),bv=new THREE.Vector3(...b),direction=bv.clone().sub(av),q=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),direction.clone().normalize());
 return <mesh position={av.add(bv).multiplyScalar(.5)} quaternion={q} castShadow><cylinderGeometry args={[.019,.019,direction.length(),10]}/><meshStandardMaterial color="#f2bd86" metalness={.35} roughness={.3}/></mesh>;
}

function KineLabObject({phase}:{phase:number}){
 const texture=usePicture('premium/kinelab-workspace.png');
 const index=Math.round((.5-.5*Math.cos(phase*TAU*2))*(demo.frames.length-1));
 const pose=demo.frames[index].xyz,hip=pose[0];
 const points:V3[]=pose.map(p=>[(p[0]-hip[0])*1.7,p[1]*1.7,(p[2]-hip[2])*1.7]);
 return <group position={[0,-.2,0]} rotation={[.02,.06*Math.sin(phase*TAU),0]}>
  <group position={[-1.25,-.05,-.2]} rotation={[0,.13,0]}>
   <mesh position={[0,0,-.05]} castShadow><boxGeometry args={[4.55,3.02,.14]}/><meshStandardMaterial color="#234052" metalness={.7} roughness={.3}/></mesh>
   {texture?<mesh position={[0,0,.03]}><planeGeometry args={[4.4,2.88]}/><meshBasicMaterial map={texture} toneMapped={false}/></mesh>:null}
  </group>
  <group position={[2.02,-1.56,.45]} rotation={[0,.35,0]}>
   {demo.bones.map(([i,j],k)=><Bone key={k} a={points[i]} b={points[j]}/>)}
   {points.map((p,i)=><mesh key={i} position={p} castShadow><sphereGeometry args={[.045,12,10]}/><meshStandardMaterial color="#c5ed83" roughness={.35} metalness={.25}/></mesh>)}
  </group>
  {[-.4,.5].map((rot,i)=><group key={i} position={[i===0?.4:3.2,-1.1,i===0?1.5:-1.2]} rotation={[0,rot,0]}>
   <mesh><boxGeometry args={[.26,.18,.17]}/><meshStandardMaterial color="#91aaa9" metalness={.7} roughness={.32}/></mesh>
   <mesh position={[0,0,.13]} rotation={[Math.PI/2,0,0]}><cylinderGeometry args={[.065,.065,.1,16]}/><meshStandardMaterial color="#050c15" metalness={.4} roughness={.14}/></mesh>
   <mesh position={[0,-.38,0]}><cylinderGeometry args={[.015,.025,.65,10]}/><meshStandardMaterial color="#769094" metalness={.7}/></mesh>
  </group>)}
 </group>;
}

const palette={about:{bg:'#e9e5dc',ink:'#202b28',accent:'#617531'},experience:{bg:'#171c1f',ink:'#f2eee4',accent:'#f18a4b'},education:{bg:'#f4ecd9',ink:'#492731',accent:'#a0444d'},projects:{bg:'#091421',ink:'#edf6fc',accent:'#c5ed83'}};
const captions={about:['HUMAN MOVEMENT / CREATIVE ENGINEERING','Movement.','Imagination.','Possibility.','MOVEMENT SCIENCE × INTERACTIVE SYSTEMS'],experience:['SERVICE / EDUCATION / CREATIVE DEVELOPMENT','SHOW UP.','BUILD','FORWARD.','U.S. Army · Arcadia Hybrid Lab · Creative development'],education:['ARCADIA UNIVERSITY / HYBRID DPT','Learning','through','layers.','Doctor of Physical Therapy · Class of 2028 · In progress'],projects:['SELECTED WORK / KINELAB PT','Movement,','made','visible.','Dual-camera movement analysis · Research prototype']};

export const PremiumStudy:React.FC<{kind:Kind}>=({kind})=>{
 const frame=useCurrentFrame(),{width,height,fps}=useVideoConfig(),phase=frame/(8*fps),p=palette[kind],text=captions[kind];
 return <AbsoluteFill style={{backgroundColor:p.bg,color:p.ink,overflow:'hidden'}}>
  <ThreeCanvas width={width} height={height} premountFor={fps} shadows dpr={1} camera={{position:[0,.12,8.3],fov:36}} gl={{antialias:true,alpha:true,powerPreference:'high-performance'}}>
   <StudioEnvironment/>
   <ambientLight intensity={kind==='experience'?.8:1.3}/>
   <hemisphereLight args={[kind==='projects'?'#d8eaf7':'#ffffff',kind==='experience'?'#302820':'#b2aa98',1.3]}/>
   <directionalLight position={[-3,5,5]} intensity={kind==='experience'?4:3} castShadow shadow-mapSize={[1024,1024]} shadow-bias={-.0001}/>
   <directionalLight position={[5,1,-2]} intensity={4} color={kind==='experience'?'#ef8b53':kind==='education'?'#f2cbc1':'#d7e5dc'}/>
   {kind==='about'?<Atlas mode="sculpture" phase={phase}/>:kind==='education'?<Atlas mode="layers" phase={phase}/>:kind==='experience'?<ExperienceObject phase={phase}/>:<KineLabObject phase={phase}/>}
   <mesh receiveShadow position={[0,-1.92,0]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[30,30]}/><shadowMaterial transparent opacity={kind==='experience'?.35:.18}/></mesh>
  </ThreeCanvas>
  <AbsoluteFill style={{padding:52,pointerEvents:'none'}}>
   <div style={{font:'17px Consolas, monospace',letterSpacing:2.4,opacity:.9}}>{text[0]}</div>
   <div style={{position:'absolute',left:52,top:kind==='projects'?115:195,width:kind==='projects'?410:470,translate:`0 ${interpolate(frame,[0,40],[12,0],{extrapolateRight:'clamp'})}px`}}>
    <h1 style={{margin:0,fontFamily:kind==='experience'?'Arial Black, Arial':'Georgia, serif',fontWeight:kind==='experience'?900:400,fontSize:kind==='experience'?65:kind==='projects'?64:74,lineHeight:1.01,letterSpacing:-3.5}}>{kind==='projects'?<>KineLab <span style={{color:p.accent}}>PT</span></>:<><span style={{display:'block'}}>{text[1]}</span><span style={{display:'block',color:p.accent,fontStyle:kind==='about'?'italic':'normal'}}>{text[2]}</span><span style={{display:'block'}}>{text[3]}</span></>}</h1>
    {kind==='projects'?null:<p style={{font:'22px/1.5 Arial',maxWidth:360,marginTop:27}}>{kind==='about'?'DPT student.\nCreative developer.':kind==='education'?'Biomechanics.\nClinical reasoning.\nEvidence-informed learning.':'A background in service,\neducation and making things work.'}</p>}
   </div>
   {kind==='education'?<div style={{position:'absolute',right:48,top:146,font:'15px/1.8 Consolas',color:p.accent,textAlign:'right'}}>BONE / MUSCLE / TENDON<br/>EXISTING ANATOMY STUDY<br/>LAYER SEPARATION</div>:null}
   <div style={{position:'absolute',left:52,right:52,bottom:38,borderTop:`1px solid ${p.accent}55`,paddingTop:16,font:'16px Consolas',letterSpacing:.5}}>{text[4]}</div>
   <div style={{position:'absolute',right:52,bottom:82,font:'13px Consolas',opacity:.75}}>{kind==='projects'?'DEMO EXPORT · PHYSICAL ACCURACY UNVERIFIED':kind==='education'||kind==='about'?'BodyParts3D © DBCLS · CC BY 4.0 · adapted study geometry':''}</div>
  </AbsoluteFill>
 </AbsoluteFill>;
};
