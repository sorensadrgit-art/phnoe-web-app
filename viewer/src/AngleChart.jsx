import React,{useMemo,useState} from 'react';
import {angleSamples} from './syncPlayback.js';

const SERIES={
 knees:[['knee_angle_r','Right knee','#6bece3'],['knee_angle_l','Left knee','#e5a269']],
 hips:[['hip_flexion_r','Right hip','#6bece3'],['hip_flexion_l','Left hip','#e5a269']],
 ankles:[['ankle_angle_r','Right ankle','#6bece3'],['ankle_angle_l','Left ankle','#e5a269']],
};
const W=940,H=244,M={left:51,right:15,top:17,bottom:33};

function makePath(points,toX,toY){
 let result='',open=false;
 for(const {t,value} of points){
  if(value===null||!Number.isFinite(value)){open=false;continue}
  result+=(open?'L':'M')+toX(t).toFixed(1)+','+toY(value).toFixed(1);
  open=true;
 }
 return result;
}

export default function AngleChart({motion,seconds,onScrub}){
 const [selection,setSelection]=useState('knees');
 // Bolt Optimization: Precompute SVG path `d` strings, min/max range, and ROM display labels
 // inside `useMemo`. When `seconds` updates at 60 FPS during motion playback, this avoids
 // re-running `makePath()` point loop string formatting and `.map().filter()` array allocations
 // on every single render frame.
 const data=useMemo(()=>{
  if(!motion?.kinematics)return null;
  const rawItems=SERIES[selection].map(([key,label,color])=>({
   key,label,color,points:angleSamples(motion,key),
  }));
  const numbers=rawItems.flatMap(item=>item.points??[]).map(point=>point.value)
   .filter(value=>value!==null&&Number.isFinite(value));
  if(!numbers.length)return null;
  const minimum=Math.min(...numbers),maximum=Math.max(...numbers);
  const padding=Math.max(6,(maximum-minimum)*.13);
  const minPadded=minimum-padding,maxPadded=maximum+padding;
  const first=motion.frames[0].t,last=Math.max(first+1e-6,motion.frames.at(-1).t);

  const toX=t=>M.left+(t-first)/(last-first)*(W-M.left-M.right);
  const toY=v=>M.top+(maxPadded-v)/(maxPadded-minPadded)*(H-M.top-M.bottom);

  const items=rawItems.map(item=>{
   const valid=(item.points??[]).map(p=>p.value).filter(v=>v!==null&&Number.isFinite(v));
   const range=valid.length?Math.max(...valid)-Math.min(...valid):null;
   const rom=range!==null?range.toFixed(1)+'° ROM':'Unavailable';
   const d=makePath(item.points??[],toX,toY);
   return {...item,rom,d};
  });

  return {items,minimum:minPadded,maximum:maxPadded,first,last};
 },[motion,selection]);

 const x=t=>M.left+(t-data.first)/(data.last-data.first)*(W-M.left-M.right);
 const y=v=>M.top+(data.maximum-v)/(data.maximum-data.minimum)*(H-M.top-M.bottom);

 const seek=event=>{
  if(!data)return;
  const rectangle=event.currentTarget.getBoundingClientRect();
  const localX=(event.clientX-rectangle.left)/rectangle.width*W;
  const position=Math.max(0,Math.min(1,(localX-M.left)/(W-M.left-M.right)));
  const time=data.first+position*(data.last-data.first);
  onScrub(time);
 };
 return <section className="panel angle-chart" aria-labelledby="angle-chart-title">
  <div className="panelhead"><span id="angle-chart-title">Angle over time</span><span>ESTIMATED OPENSIM COORDINATES</span></div>
  <div className="angle-controls" role="group" aria-label="Select paired joint angles">
   {Object.keys(SERIES).map(item=><button type="button" key={item}
     aria-pressed={selection===item} className={selection===item?'active':''}
     onClick={()=>setSelection(item)}>{item[0].toUpperCase()+item.slice(1)}</button>)}
  </div>
  {!data?<div className="angle-empty">
   {motion?.kinematics?'The selected joint coordinates are unavailable in this run.':
    'Marker-only motion. OpenSim joint-angle data has not been established; no ROM curve is generated.'}
  </div>:<div className="angle-chart-body">
   <div className="angle-legends">
    {data.items.map(item=>(
     <div key={item.key} className="angle-legend">
      <span className="legend-dot" style={{backgroundColor:item.color}} aria-hidden="true"/>
      <span>{item.label}</span>
      <strong>{item.rom}</strong>
     </div>
    ))}
   </div>
   <svg className="angle-svg" viewBox={'0 0 '+W+' '+H} role="img"
     aria-label="Timeline plot of available model-estimated left and right joint angles in degrees"
     onPointerDown={seek} style={{cursor:'crosshair'}}>
    {[0,.25,.5,.75,1].map((fraction,index)=>{
     const value=data.minimum+(data.maximum-data.minimum)*fraction;
     const yy=y(value);
     return <g key={index}>
      <line x1={M.left} x2={W-M.right} y1={yy} y2={yy} stroke="#28505c" strokeWidth="1"/>
      <text x={M.left-7} y={yy+4} fill="#92acb7" fontSize="12" textAnchor="end">{value.toFixed(0)}°</text>
     </g>;
    })}
    {data.items.map(item=><path key={item.key} d={item.d}
      fill="none" stroke={item.color} strokeWidth="2.5" strokeLinejoin="round"
      strokeLinecap="round"/>)}
    <line x1={x(Math.min(data.last,Math.max(data.first,seconds)))}
      x2={x(Math.min(data.last,Math.max(data.first,seconds)))}
      y1={M.top} y2={H-M.bottom} stroke="#edf7fa" strokeWidth="1.3" strokeDasharray="5 5"/>
    <text x={M.left} y={H-9} fill="#9fb7bc" fontSize="12">{data.first.toFixed(2)} s</text>
    <text x={W-M.right} y={H-9} fill="#9fb7bc" fontSize="12" textAnchor="end">{data.last.toFixed(2)} s</text>
   </svg>
   <p className="angle-disclaimer">
    Click the plot to scrub the shared 3D timeline. Only supported OpenSim model angles are shown.
    Missing measurements remain gaps. ROM is a descriptive range of available samples,
    not a diagnosis or validated clinical accuracy claim.
   </p>
  </div>}
 </section>;
}
