import {useEffect,useRef,useState,type ReactNode} from 'react';
import {AnimatePresence,motion} from 'motion/react';

export function ChapterTabs({labels,active,onChange,label,panelId='ex-active-panel'}:{labels:readonly string[];active:number;onChange:(index:number)=>void;label:string;panelId?:string}) {
  return <div className="ex-tabs" role="tablist" aria-label={label} onKeyDown={e=>{
    let next=active;
    if(e.key==='ArrowRight'||e.key==='ArrowDown')next=(active+1)%labels.length;
    else if(e.key==='ArrowLeft'||e.key==='ArrowUp')next=(active+labels.length-1)%labels.length;
    else if(e.key==='Home')next=0;else if(e.key==='End')next=labels.length-1;else return;
    e.preventDefault();e.stopPropagation();onChange(next);
    e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }}>{labels.map((text,i)=><button key={text} id={panelId+'-tab-'+i} type="button" role="tab" aria-selected={active===i}
    aria-controls={panelId} tabIndex={active===i?0:-1} onClick={()=>onChange(i)}>{text}</button>)}
  </div>;
}

// Adapted from Motion Primitives' MIT TransitionPanel: one controlled chapter, no nested dialog.
export function TransitionPanel({active,children,reduced}:{active:string|number;children:ReactNode;reduced:boolean}) {
  return <AnimatePresence mode="wait" initial={false}><motion.div key={active} className="ex-transition"
    initial={reduced?false:{opacity:0,y:12,filter:'blur(3px)'}} animate={{opacity:1,y:0,filter:'blur(0px)'}}
    exit={{opacity:0,y:reduced?0:-8}} transition={{duration:reduced?0:.22}}>{children}</motion.div></AnimatePresence>;
}

export function Film({id,reduced,className='',playing=true}:{id:string;reduced:boolean;className?:string;playing?:boolean}) {
  const ref=useRef<HTMLVideoElement>(null);
  const [failed,setFailed]=useState(false);
  const [paused,setPaused]=useState(false);
  const base=import.meta.env.BASE_URL+'media/'+id+'-';
  useEffect(()=>{
    const video=ref.current;if(!video)return;
    let visible=true;
    const sync=()=>{if(reduced||document.hidden||!visible||!playing||paused)video.pause();else video.play().catch(()=>setPaused(true));};
    const observer=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;sync();},{threshold:.01});observer.observe(video);
    sync();document.addEventListener('visibilitychange',sync);
    return()=>{observer.disconnect();document.removeEventListener('visibilitychange',sync);video.pause();};
  },[reduced,playing,paused,id]);
  return <div className={'ex-film-wrap '+className}>{failed||reduced?<img className="ex-film" src={base+'poster.png'} alt=""/>:
    <video ref={ref} className="ex-film" poster={base+'poster.png'} src={base+'film.mp4'} muted loop playsInline preload="metadata" aria-hidden="true" onError={()=>setFailed(true)}/>}
    {!reduced&&!failed&&<button type="button" className="ex-film-toggle" aria-label={(paused?'Play':'Pause')+' '+id+' film'} onClick={()=>setPaused(!paused)}>{paused?'Play film':'Pause film'}</button>}</div>;
}

export function CopyButton({text}:{text:string}) {
  const [status,setStatus]=useState('');
  const timeout=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  useEffect(()=>()=>clearTimeout(timeout.current),[]);
  return <div className="ex-copy"><button type="button" className="ex-button" onClick={async()=>{
    clearTimeout(timeout.current);
    try{await navigator.clipboard.writeText(text);setStatus('Link copied.');}
    catch{setStatus('Copy unavailable. Select and copy the link below.');}
    timeout.current=setTimeout(()=>setStatus(''),4500);
  }}>Copy GitHub link <span aria-hidden="true">↗</span></button><span role="status" aria-live="polite">{status}</span></div>;
}
