import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';

type Kind = 'about' | 'experience' | 'education' | 'projects' | 'skills' | 'contact';
const ink = '#10282b', paper = '#f1eee8', teal = '#88c9bd', copper = '#d5aa7d';
const polar = (x:number,y:number,r:number,a:number) => [x+r*Math.cos(a),y+r*Math.sin(a)];
const path = (p:number[][]) => p.map((v,i)=>`${i?'L':'M'}${v[0].toFixed(2)},${v[1].toFixed(2)}`).join(' ');
const Line = ({points, ...props}: {points:number[][]} & Omit<React.SVGProps<SVGPathElement>, 'points'>) => <path d={path(points)} fill="none" stroke={teal} strokeWidth={3} strokeLinecap="round" {...props}/>;
const Label = ({x,y,children,...props}:React.SVGProps<SVGTextElement>) => <text x={x} y={y} fill={paper} fontFamily="Arial, sans-serif" fontSize={24} letterSpacing={3} {...props}>{children}</text>;
const Dot = ({x,y,r=7, ...props}:{x:number;y:number;r?:number}&React.SVGProps<SVGCircleElement>) => <circle cx={x} cy={y} r={r} fill={copper} {...props}/>;

function Study({kind,phase}:{kind:Kind;phase:number}) {
 const a=phase*Math.PI*2;
 if(kind==='about') {
  const skeleton=(p:number)=>{
   const hip=[600+8*Math.sin(p),346]; const shoulder=[600-20*Math.sin(p),210];
   const kneeL=[540+54*Math.sin(p),431], ankleL=[535+115*Math.sin(p),554];
   const kneeR=[660-54*Math.sin(p),431], ankleR=[665-115*Math.sin(p),554];
   return <><Line points={[shoulder,hip]} strokeWidth={9}/><Line points={[hip,kneeL,ankleL]} strokeWidth={7}/><Line points={[hip,kneeR,ankleR]} strokeWidth={7}/><Line points={[[520-70*Math.sin(p),360],[548-45*Math.sin(p),280],shoulder,[652+45*Math.sin(p),280],[680+70*Math.sin(p),360]]}/><circle cx={shoulder[0]} cy={150} r={38} fill="none" stroke={paper} strokeWidth={3}/>{[hip,shoulder,kneeL,kneeR,ankleL,ankleR].map(([x,y],i)=><Dot key={i} x={x} y={y}/>)}</>;
  };
  return <><ellipse cx={600} cy={560} rx={220} ry={33} fill="none" stroke={teal} opacity={.2}/><g opacity={.12} transform="translate(-130 0)">{skeleton(a-.65)}</g><g opacity={.12} transform="translate(130 0)">{skeleton(a+.65)}</g>{skeleton(a)}<Label x={80} y={92}>HUMAN MOVEMENT</Label><Label x={80} y={635} fill={copper}>SCIENCE × CREATIVE ENGINEERING</Label><path d="M850 180h100v290H850" fill="none" stroke={teal} opacity={.3}/></>;
 }
 if(kind==='experience') return <><Label x={80} y={92}>A MULTIDISCIPLINARY PATH</Label>{['EDUCATION','SERVICE','CREATIVE DEVELOPMENT'].map((s,i)=>{
  const y=215+i*150;const x=150+i*320;const p=polar(x,y,50,a+i*1.4);
  return <g key={s}><path d={`M${x-40} ${y}H${x+270}`} stroke={teal} opacity={.25}/><circle cx={x} cy={y} r={52} fill="none" stroke={teal}/><circle cx={x} cy={y} r={32} fill="none" stroke={paper} strokeDasharray="2 10"/><Dot x={p[0]} y={p[1]}/><Label x={x-25} y={y+100} fontSize={21} letterSpacing={1}>{s}</Label></g>;
 })}<path d="M150 215C400 215 200 365 470 365S520 515 790 515" fill="none" stroke={copper} strokeWidth={2} strokeDasharray="8 14" strokeDashoffset={-phase*44}/><Label x={80} y={645} fill={copper}>LEARN / SUPPORT / BUILD</Label></>;
 if(kind==='education') return <><Label x={80} y={92}>LEARNING IN LAYERS</Label>{[0,1,2,3,4].map(i=><g key={i} transform={`translate(600 ${265+i*48+8*Math.sin(a+i*.7)})`}><path d="M-280 0L0-112 280 0 0 112Z" fill={i===2?'#284a49':ink} stroke={i===2?copper:teal} strokeWidth={2} opacity={.35+i*.11}/><path d="M-150 0L0-60 150 0 0 60Z" fill="none" stroke={paper} opacity={.25}/></g>)}<circle cx={600} cy={205} r={48} fill={ink} stroke={copper} strokeWidth={2}/><path d="M580 205l15 15 28-33" fill="none" stroke={paper} strokeWidth={4}/><Label x={80} y={600}>ARCADIA UNIVERSITY</Label><Label x={80} y={645} fill={copper}>DOCTOR OF PHYSICAL THERAPY · IN PROGRESS</Label></>;
 if(kind==='projects') {
  const arm=Array.from({length:9},(_,i)=>[430+i*43,330+85*Math.sin(i*.6+a)]);
  return <><Label x={80} y={92}>IDEAS INTO PROTOTYPES</Label><g transform={`translate(0 ${12*Math.sin(a)})`}><path d="M300 195L600 115 900 195 900 475 600 565 300 475Z" fill="none" stroke={teal} strokeWidth={2}/><path d="M300 195L600 285 900 195M600 285V565" fill="none" stroke={teal} opacity={.5}/><path d="M300 475L600 385 900 475M600 115V385" stroke={teal} fill="none" strokeDasharray="6 12" opacity={.3}/><Line points={arm} stroke={paper} strokeWidth={6}/>{arm.map(([x,y],i)=><Dot key={i} x={x} y={y} r={i%2?4:8}/>)}</g><g transform={`translate(${340+phase*520} 0)`}><path d="M0 175V525" stroke={copper} strokeWidth={2} opacity={Math.sin(phase*Math.PI)*.8}/></g><Label x={80} y={645} fill={copper}>MOVEMENT / CODE / EXPERIMENTS</Label></>;
 }
 if(kind==='skills') return <><Label x={80} y={92}>A CONNECTED TOOLKIT</Label>{[0,1,2].map(i=><g key={i} transform={`rotate(${i*60} 600 350)`}><ellipse cx={600} cy={350} rx={330} ry={95} stroke={teal} fill="none" opacity={.5}/><Dot x={600+330*Math.cos(a+i*2)} y={350+95*Math.sin(a+i*2)} r={11}/></g>)}<circle cx={600} cy={350} r={80} fill={ink} stroke={copper} strokeWidth={2}/><text x={600} y={363} textAnchor="middle" fill={paper} fontSize={39} fontFamily="Georgia,serif">SOREN</text><Label x={80} y={568}>WEB · MOTION · 3D</Label><Label x={80} y={635} fill={copper}>MOVEMENT × INTELLIGENT SYSTEMS</Label></>;
 return <><Label x={80} y={92}>START A CONVERSATION</Label>{[0,1,2,3].map(i=>{
  const f=(phase+i/4)%1;return <circle key={i} cx={600} cy={350} r={90+f*260} fill="none" stroke={teal} strokeWidth={2} opacity={(1-f)*.6}/>;
 })}<path d="M385 260H815V455H385ZM385 260L600 393 815 260" fill={ink} stroke={paper} strokeWidth={3}/><path d="M385 455L520 350M815 455L680 350" stroke={teal} strokeWidth={2}/><Dot x={600} y={260} r={10}/><Label x={80} y={635} fill={copper}>HUMAN MOVEMENT. SHARED CURIOSITY.</Label></>;
}

export const SectionStudy:React.FC<{kind:Kind}> = ({kind}) => {
 const frame=useCurrentFrame();const {fps}=useVideoConfig();
 return <AbsoluteFill style={{backgroundColor:ink}}><svg viewBox="0 0 1200 704" width="100%" height="100%" role="img" aria-label={`${kind} motion study`}><defs><radialGradient id="glow"><stop stopColor="#315958" stopOpacity=".55"/><stop offset="1" stopColor={ink}/></radialGradient><pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M48 0H0V48" fill="none" stroke={teal} strokeWidth=".7" opacity=".08"/></pattern></defs><rect width="1200" height="704" fill="url(#glow)"/><rect width="1200" height="704" fill="url(#grid)"/><Study kind={kind} phase={frame/(6*fps)}/></svg></AbsoluteFill>;
};
