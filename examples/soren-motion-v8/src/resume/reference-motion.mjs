// Independently expressed motion measurements from the live reference, 2026-10-28.
export const reference = Object.freeze({ fov:53.4, depth:.2, span:1.15, shift:-.2, bank:-.16,
  diagonal:.03, lean:-.12, speedDepth:1.1, edgeTwist:1.8, rearY:.1, rearZ:.2,
  damping:.1, speedNorm:550, wheelGain:1.25, wheelEase:.22, hoverMs:500, flightMs:1000 });

export function smoothRange(a,b,value) {
  const t=Math.max(0,Math.min(1,(value-a)/(b-a)));
  return t*t*(3-2*t);
}

export function surfacePoint(x,y,halfWidth,speed=0,z=0) {
  const w=Math.max(1,halfWidth), q=x/w*reference.span+reference.shift;
  const envelope=Math.exp(-q*q);
  const slope=(Math.PI*Math.cos(Math.PI*q)-2*q*Math.sin(Math.PI*q))*envelope;
  const velocity=Math.min(1,Math.abs(speed));
  const angle=reference.bank*slope/Math.PI+reference.edgeTwist*velocity*smoothRange(.3,.9,Math.abs(x/w))*Math.sign(x);
  const cosine=Math.cos(angle),sine=Math.sin(angle);
  const lift=1-smoothRange(-1,.3,x/w);
  const ramp=Math.max(-1,Math.min(1,x/w));
  return { x, y:y*cosine-z*sine+reference.diagonal*x+reference.rearY*w*velocity*lift,
    z:y*sine+z*cosine-w*reference.depth*(1+reference.speedDepth*velocity)*Math.sin(Math.PI*q)*envelope
      +reference.rearZ*w*velocity*lift+reference.lean*w*ramp*(1.5-.5*ramp*ramp) };
}

export function projectPoint(x,y,width,height,speed=0) {
  const point=surfacePoint(x,y,width/2,speed);
  const camera=height/2/Math.tan(reference.fov*Math.PI/360);
  const scale=camera/(camera-point.z);
  return {x:width/2+point.x*scale,y:height/2-point.y*scale};
}

export function projectCard(left,top,width,height,vw,vh,speed=0) {
  const points=[];
  for(let side=0;side<2;side++) for(let step=0;step<=32;step++) {
    const progress=side?1-step/32:step/32;
    points.push(projectPoint(left+width*progress-vw/2,vh/2-top-side*height,vw,vh,speed));
  }
  const x=Math.min(...points.map(p=>p.x)),y=Math.min(...points.map(p=>p.y));
  const w=Math.max(...points.map(p=>p.x))-x,h=Math.max(...points.map(p=>p.y))-y;
  return {left:x,top:y,width:w,height:h,clip:points.map(p=>`${(p.x-x)/w*100}% ${(p.y-y)/h*100}%`).join(',')};
}

export function stepPosition(current,target,deltaMs) {
  return Math.round((current+(target-current)*reference.damping*Math.min(2,Math.max(0,deltaMs)/(1000/60)))*100)/100;
}

export function softTarget(current,requested,width) {
  return width>0?current+Math.tanh((requested-current)/width)*width:current;
}

export function motionSpeed(remaining) { return Math.tanh(Math.abs(remaining)/reference.speedNorm)**2; }

export class WheelImpulse {
  pending=0; immediate=0; last=-Infinity; stream=-Infinity;
  push(event,height) {
    const scale=event.deltaMode===1?16:event.deltaMode===2?height:1;
    const delta=(event.deltaY+event.deltaX)*scale;
    const now=event.timeStamp, gap=now-this.last;
    if(gap<30) this.stream=now;
    if(Math.abs(delta)>=40&&gap>=30&&now-this.stream>=500) this.pending+=delta*reference.wheelGain*2;
    else this.immediate+=delta*reference.wheelGain;
    this.last=now;
  }
  step(deltaMs) {
    const ratio=Math.min(4,Math.max(0,deltaMs)/(1000/60));
    let delta=this.pending*(1-(1-reference.wheelEase)**ratio);
    this.pending-=delta;
    if(Math.abs(this.pending)<.05) {delta+=this.pending;this.pending=0;}
    delta+=this.immediate;this.immediate=0;
    return delta;
  }
}

const flightSegments=[[[0,0],[.094,.026],[.124,.127],[.157,.29]],
  [[.157,.29],[.197,.486],[.254,.8],[.348,.884]],
  [[.348,.884],[.42,.949],[.374,1],[1,1]]];
export function flightEase(progress) {
  if(progress<=0||progress>=1) return Math.max(0,Math.min(1,progress));
  const segment=flightSegments.find(points=>progress<=points[3][0]);
  const cubic=(t,axis)=>segment[0][axis]*(1-t)**3+3*segment[1][axis]*(1-t)**2*t+3*segment[2][axis]*(1-t)*t*t+segment[3][axis]*t**3;
  let lo=0,hi=1;
  for(let step=0;step<20;step++) {const t=(lo+hi)/2;if(cubic(t,0)<progress)lo=t;else hi=t;}
  return cubic((lo+hi)/2,1);
}

export const ribbonVertex=`
uniform float uHalfW;
uniform float uSpeed;
uniform float uHover;
uniform float uReveal;
uniform vec2 uSize;
out vec2 vUv;
float rangeMask(float a,float b,float x){float t=clamp((x-a)/(b-a),0.,1.);return t*t*(3.-2.*t);}
void main(){
  vUv=uv;
  vec3 local=position;
  vec2 edge=uv*2.-1.;
  local.z-=uHover*uSize.y*.1*(1.-edge.x*edge.x)*(1.-edge.y*edge.y);
  vec4 point=modelMatrix*vec4(local,1.);
  point.x+=sign(modelMatrix[3].x+.0001)*uHalfW*.5*(1.-uReveal);
  float w=max(1.,uHalfW),q=point.x/w*1.15-.2;
  float envelope=exp(-q*q),velocity=clamp(abs(uSpeed),0.,1.);
  float slope=(3.141592653589793*cos(3.141592653589793*q)-2.*q*sin(3.141592653589793*q))*envelope;
  float bank=-.16*slope/3.141592653589793+1.8*velocity*rangeMask(.3,.9,abs(point.x/w))*sign(point.x);
  vec2 yz=mat2(cos(bank),sin(bank),-sin(bank),cos(bank))*point.yz;
  float lift=1.-rangeMask(-1.,.3,point.x/w),ramp=clamp(point.x/w,-1.,1.);
  point.y=yz.x+.03*point.x+.1*w*velocity*lift;
  point.z=yz.y-.2*w*(1.+1.1*velocity)*sin(3.141592653589793*q)*envelope+.2*w*velocity*lift-.12*w*ramp*(1.5-.5*ramp*ramp);
  gl_Position=projectionMatrix*viewMatrix*point;
}`;

export function referenceTrack(React,config) {
  const trackRef=React.useRef(null),instance=React.useRef(null),selected=React.useRef(config.initialIndex);
  const callbacks=React.useRef(config);callbacks.current=config;
  React.useLayoutEffect(()=>{
    const track=trackRef.current;if(!track)return;
    let current=0,target=0,period=0,raf=null,lastFrame=0,suspended=document.hidden;
    let layout=[];
    let clockStep=1000/60,carry=0,clockRaf=null,clockTime=0;
    const idleIntervals=[];
    // Measure the display while idle, then keep its physics cadence when a rendered frame is late.
    const observeClock=time=>{
      const dt=time-clockTime;clockTime=time;
      if(raf===null&&!suspended&&dt>=4&&dt<=40){
        idleIntervals.push(dt);if(idleIntervals.length>12)idleIntervals.shift();
        if(idleIntervals.length===12)clockStep=[...idleIntervals].sort((a,b)=>a-b)[6];
      }
      clockRaf=requestAnimationFrame(observeClock);
    };
    clockRaf=requestAnimationFrame(observeClock);
    let dragLast=0,dragTime=0,dragVelocity=0,dragArmed=false,navigation=false;
    const wheel=new WheelImpulse();
    const desktop=()=>innerWidth>720;
    const cards=()=>[...track.querySelectorAll('.sr-card')];
    const position=index=>innerWidth/2-layout[index].left-layout[index].width/2;
    const wrap=index=>(index%config.count+config.count)%config.count;
    const apply=(speed=0)=>{
      track.style.transform=`translate3d(${current}px,-50%,0)`;
      track.dataset.position=String(current);track.dataset.speed=String(speed);
      track.dataset.motionReference='2026-10-28';
      const top=track.getBoundingClientRect().top;
      layout.forEach(({card,left:offset,top:offsetTop,width,height})=>{
        const left=current+offset,y=top+offsetTop;
        const outside=left+width<-innerWidth*.5||left>innerWidth*1.5;
        card.style.visibility=outside?'hidden':'';
        if(outside)return;
        const projection=projectCard(left,y,width,height,innerWidth,innerHeight,speed);
        card.style.setProperty('--ribbon-transform',`translate(${projection.left-left}px,${projection.top-y}px) scale(${projection.width/width},${projection.height/height})`);
        card.style.setProperty('--ribbon-clip',`polygon(${projection.clip})`);
        card.style.zIndex=String(100-Math.round(Math.abs(left+width/2-innerWidth/2)/10));
      });
      callbacks.current.onFrame(speed);
    };
    const schedule=()=>{if(raf===null&&!suspended&&desktop()){lastFrame=performance.now();carry=clockStep;raf=requestAnimationFrame(frame);}};
    const frame=time=>{
      raf=null;if(suspended||!desktop())return;
      const dt=lastFrame?time-lastFrame:1000/60;lastFrame=time;
      carry+=Math.min(1000,Math.max(0,dt));
      while(carry>=clockStep){
        const delta=wheel.step(clockStep);
        if(delta)target=softTarget(current,target-delta,innerWidth);
        current=config.reduced?target:stepPosition(current,target,clockStep);
        carry-=clockStep;
      }
      const items=layout,coordinate=innerWidth/2-current,base=items[config.count].left;
      if(coordinate>=base+period){current+=period;target+=period;}
      else if(coordinate<base){current-=period;target-=period;}
      if(Math.abs(target-current)<.15)current=target;
      const remaining=target-current,speed=config.reduced?0:motionSpeed(remaining);
      apply(speed);
      let nearest=0;
      for(let n=1;n<items.length;n++)if(Math.abs(position(n)-current)<Math.abs(position(nearest)-current))nearest=n;
      const index=wrap(nearest);
      if(!navigation&&index!==selected.current){selected.current=index;callbacks.current.onSelected(index);}
      if(Math.abs(remaining)>.05||wheel.pending||wheel.immediate)raf=requestAnimationFrame(frame);
      else{current=target;navigation=false;apply(0);}
    };
    const measure=()=>{
      if(!desktop()){
        if(raf!==null)cancelAnimationFrame(raf);raf=null;
        track.style.removeProperty('transform');track.dataset.mode='vertical';
        track.querySelectorAll('.sr-card').forEach(card=>{card.style.removeProperty('--ribbon-transform');card.style.removeProperty('--ribbon-clip');card.style.removeProperty('z-index');card.style.removeProperty('visibility');});
        return;
      }
      const card=track.querySelector('[data-resume-card]');if(!card)return;
      layout=cards().map(card=>({card,left:card.offsetLeft,top:card.offsetTop,width:card.offsetWidth,height:card.offsetHeight}));
      period=layout[config.count].left-layout[0].left;
      current=target=position(selected.current+config.count);track.dataset.mode='inertial';apply();
    };
    instance.current={
      goTo(index){
        selected.current=index;callbacks.current.onSelected(index);
        if(!desktop()){track.querySelectorAll('[data-resume-card]')[index]?.scrollIntoView({block:'center',behavior:config.reduced?'instant':'smooth'});return;}
        const candidates=[index,index+config.count,index+2*config.count];
        const nearest=candidates.reduce((a,b)=>Math.abs(position(b)-current)<Math.abs(position(a)-current)?b:a);
        wheel.pending=wheel.immediate=0;navigation=true;target=position(nearest);schedule();
      },
      wheel(event){if(!desktop())return;navigation=false;wheel.push(event,innerHeight);schedule();},
      drag(delta,phase){
        if(!desktop())return;navigation=false;
        if(phase==='start'){wheel.pending=wheel.immediate=0;dragArmed=false;dragLast=dragVelocity=0;dragTime=performance.now();return;}
        const now=performance.now();
        if(phase==='move'){
          if(!dragArmed){dragArmed=true;dragLast=delta;dragTime=now;return;}
          dragVelocity=(delta-dragLast)*1.5;dragLast=delta;dragTime=now;
          target=softTarget(current,target+dragVelocity,innerWidth);
        }
        if(phase==='end'&&!config.reduced&&now-dragTime<100)target=softTarget(current,target+dragVelocity*12,innerWidth);
        schedule();
      }
    };
    const visible=()=>{suspended=document.hidden;if(suspended){if(raf!==null)cancelAnimationFrame(raf);raf=null;}else schedule();};
    addEventListener('resize',measure,{passive:true});document.addEventListener('visibilitychange',visible);measure();
    return()=>{if(raf!==null)cancelAnimationFrame(raf);if(clockRaf!==null)cancelAnimationFrame(clockRaf);removeEventListener('resize',measure);document.removeEventListener('visibilitychange',visible);instance.current=null;};
  },[config.count,config.reduced]);
  const goTo=React.useCallback(index=>instance.current?.goTo(index),[]);
  const wheel=React.useCallback(event=>instance.current?.wheel(event),[]);
  const drag=React.useCallback((delta,phase)=>instance.current?.drag(delta,phase),[]);
  return {trackRef,goTo,wheel,drag};
}
