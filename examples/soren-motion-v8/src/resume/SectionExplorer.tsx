import {lazy,Suspense,useEffect,useRef,useState,type ReactNode} from 'react';
import {motion} from 'motion/react';
import type {ResumeSection} from './resumeData';
import {ChapterTabs,CopyButton,Film,TransitionPanel} from './ExplorerControls';
import {frameFromTime,githubUrl,projects,projectTitle,skillLinks,splineUrl} from './explorerData';
import {animateModalEntrance} from './motion/gsapModalChoreography';
import {ModalAmbientCanvas} from './motion/ModalAmbientCanvas';
import {MotionGraphicType} from './motion/MotionGraphicType';

const LiveStudy=lazy(()=>import('./LiveStudy'));
const BiomechanicalLabProject=lazy(()=>import('./projects/biomechanical-lab/BiomechanicalLabProject'));
type Props={section:ResumeSection;reduced:boolean;initialProject?:string;onNavigate:(id:string,project?:string)=>void};
const captions:Record<string,string>={about:'THE HUMAN BEHIND THE SYSTEMS',experience:'SERVICE / EDUCATION / MAKING',education:'LEARNING THROUGH MOVEMENT',projects:'SELECTED WORK / OPEN EXPLORATIONS',skills:'TOOLS, CONNECTED TO PRACTICE',contact:'THE NEXT CONVERSATION'};
const sectionHexAccents:Record<string,string>={about:'#00f5a0',experience:'#ff9f43',education:'#00d2d3',projects:'#3867d6',skills:'#a55eea',contact:'#f5f6fa'};

function Heading({section,reduced}:{section:ResumeSection;reduced?:boolean}) {
  return (
    <header className="ex-heading">
      <div className="ex-eyebrow"><span>{section.number} / SOREN SADR</span><span>{captions[section.id]}</span></div>
      <MotionGraphicType
        text={section.title}
        kicker={`${section.number} / ${section.id.toUpperCase()}`}
        variant="stagger"
        reduced={reduced}
      />
      <p className="ex-lead">{section.lead}</p>
    </header>
  );
}
function Panel({active,children}:{active:number;children:ReactNode}) {return <div role="tabpanel" id="ex-active-panel" aria-labelledby={'ex-active-panel-tab-'+active} tabIndex={0} className="ex-panel">{children}</div>;}
function Credit(){return <details className="ex-credit"><summary>About this anatomy study</summary><p>BodyParts3D © DBCLS. Adapted study geometry under <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer">CC BY 4.0</a>. Simplified study geometry; not a complete anatomical atlas or clinical instrument.</p></details>;}

function About({section,reduced,onNavigate}:Props) {
  const [active,setActive]=useState(0);
  const labels=['Background','Values','Focus','Now'];
  return <div className="ex-about-layout"><div className="ex-about-stage">
    <div className="ex-hud-overlay" aria-hidden="true"><span className="ex-hud-tag">+ REC // BIO-TELEMETRY</span><span className="ex-hud-coords">KINETIC 60 FPS</span></div>
    <Film id="about" reduced={reduced}/><div className="ex-atlas-caption"><span>FIELD NOTE / 0{active+1}</span><strong>{['The person.','The principles.','The intersection.','In progress.'][active]}</strong></div>
    <div className="ex-atlas-index" aria-hidden="true">{labels.map((name,i)=><span key={name} className={active===i?'is-active':''}>{String(i+1).padStart(2,'0')} {name}</span>)}</div>
  </div><div className="ex-about-story"><p className="ex-kicker">A PRACTICE IN TWO WORLDS</p><h2>Movement.<br/><em>Imagination.</em><br/>Possibility.</h2>
    <ChapterTabs labels={labels} active={active} onChange={setActive} label="About chapters"/>
    <Panel active={active}><TransitionPanel active={active} reduced={reduced}><h3>{section.blocks[active].label}</h3><p>{section.blocks[active].value}</p></TransitionPanel></Panel>
    <button type="button" className="ex-text-link" onClick={()=>onNavigate(active===0||active===3?'education':'projects')}>{active===0||active===3?'Explore my education':'See the work'} <span aria-hidden="true">↗</span></button><Credit/>
  </div></div>;
}

function Experience({section,reduced}:Props) {
  const [active,setActive]=useState(0);
  const rail=useRef<HTMLDivElement>(null);
  const labels=['Arcadia Hybrid Lab','Creative development','U.S. Army','Clinical education'];
  const select=(index:number)=>{setActive(index);rail.current?.querySelector<HTMLElement>('[data-role="'+index+'"]')?.scrollIntoView({block:'nearest',behavior:reduced?'instant':'smooth'});};
  return <div className="ex-experience-layout"><div className="ex-role-visual">
    <div className="ex-hud-overlay" aria-hidden="true"><span className="ex-hud-tag">+ LOG // CAREER SEQUENCE</span><span className="ex-hud-coords">CHAPTER: 0{active+1}</span></div>
    <Film id="experience" reduced={reduced}/>
    <div className="ex-role-plaque"><span>CHAPTER / 0{active+1}</span><TransitionPanel active={active} reduced={reduced}><strong>{labels[active]}</strong><p>{['Supporting the learning environment.','Building with code and motion.','A background in service.','Developing clinical foundations.'][active]}</p></TransitionPanel></div>
  </div><div className="ex-role-story"><p className="ex-kicker">FOUR CONNECTED CHAPTERS</p>
    <div className="ex-role-timeline" aria-hidden="true"><div className="ex-role-timeline-fill" style={{width:`${((active+1)/4)*100}%`}}/></div>
    <div className="ex-role-index" aria-label="Experience chapters">{labels.map((name,i)=><button key={name} type="button" aria-current={active===i?'step':undefined} onClick={()=>select(i)}><span>0{i+1}</span>{name}</button>)}</div>
    <div ref={rail} className="ex-role-scroll" tabIndex={0} aria-label="Experience detail" data-local-keys onKeyDown={e=>{
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();e.stopPropagation();select(Math.max(0,Math.min(3,active+(e.key==='ArrowDown'?1:-1))));}
    }} onScroll={e=>{const parent=e.currentTarget;const nodes=Array.from(parent.querySelectorAll<HTMLElement>('[data-role]'));const top=parent.getBoundingClientRect().top;const nearest=nodes.reduce((best,node,i)=>Math.abs(node.getBoundingClientRect().top-top)<Math.abs(nodes[best].getBoundingClientRect().top-top)?i:best,0);setActive(nearest);}}>
      {section.blocks.map((block,i)=><article key={block.label} data-role={i} className={active===i?'is-active':''}><span className="ex-role-number">0{i+1}</span><h2>{labels[i]}</h2><p className="ex-kicker">{block.label}</p><p>{block.value}</p></article>)}
    </div><p className="ex-small">Service dates and assignments remain pending résumé review.</p>
  </div></div>;
}

function Education({section,reduced}:Props) {
  const [live,setLive]=useState(false),[failed,setFailed]=useState(false),[ready,setReady]=useState(false);
  const [active,setActive]=useState(0),[separation,setSeparation]=useState(0),[rotation,setRotation]=useState(0),[zoom,setZoom]=useState(1),[reset,setReset]=useState(0);
  const layers=['all','bone','muscle','tendon'];
  return <div className="ex-education-layout"><div className="ex-anatomy-stage">
    <div className="ex-hud-overlay" aria-hidden="true"><span className="ex-hud-tag">+ 3D ANATOMY ATLAS</span><span className="ex-hud-coords">LAYER: {layers[active].toUpperCase()}</span></div>
    {live&&!failed?<><Suspense fallback={<Film id="education" reduced/>}><LiveStudy kind="anatomy" layer={layers[active]} separation={separation} rotation={rotation} zoom={zoom} reset={reset} onReady={()=>setReady(true)} onFailure={()=>{setFailed(true);setLive(false);}}/></Suspense>
      <div className="ex-stage-stamp"><span>ANATOMY STUDY</span><strong>{ready?['All layers','Bone','Muscle','Tendon'][active]:'Loading study…'}</strong></div></>:<Film id="education" reduced={reduced}/>}
    <button type="button" className="ex-explore-button" onClick={()=>{setFailed(false);setLive(!live);setReady(false);}}>{live?'Return to film':'Explore in 3D'} <span aria-hidden="true">↗</span></button>
    <div className="ex-stage-caption">{live?'Drag to orbit · wheel to zoom · controls below':'Anatomy in motion · activate the live study'}</div>
  </div><div className="ex-education-story"><p className="ex-kicker">ARCADIA UNIVERSITY / IN PROGRESS</p><h2>Understand<br/><em>what moves us.</em></h2>
    <p>{section.blocks[0].value}</p><ChapterTabs labels={['Overview','Bone','Muscle','Tendon']} active={active} onChange={i=>{setActive(i);if(!failed)setLive(true);}} label="Anatomy layers"/>
    <Panel active={active}><TransitionPanel active={active} reduced={reduced}><h3>{['A layered way of learning','Structure & support','Force & movement','Connection & transfer'][active]}</h3><p>{[section.blocks[2].value,'Isolate the existing bone meshes and inspect their relationship to the surrounding study geometry.','Isolate the existing muscle meshes. Orbit the study to inspect their arrangement.','Isolate the existing tendon meshes in this simplified lower-body study.'][active]}</p></TransitionPanel></Panel>
    <div className="ex-study-controls"><label>Layer separation <output>{Math.round(separation*100)}%</output><input type="range" aria-label="Layer separation" min="0" max="1" step=".01" value={separation} disabled={!live||active!==0} onChange={e=>setSeparation(Number(e.target.value))}/></label>
      <label>Study zoom <output>{Math.round(zoom*100)}%</output><input type="range" aria-label="Study zoom" min=".7" max="1.5" step=".05" value={zoom} disabled={!live} onChange={e=>setZoom(Number(e.target.value))}/></label>
      <div className="ex-control-row"><button type="button" disabled={!live} onClick={()=>setRotation(v=>v-30)} aria-label="Rotate anatomy left">Rotate left</button><button type="button" disabled={!live} onClick={()=>setRotation(v=>v+30)} aria-label="Rotate anatomy right">Rotate right</button><button type="button" onClick={()=>{setRotation(0);setSeparation(0);setZoom(1);setActive(0);setReset(v=>v+1);}}>Reset</button></div>
      <span role="status" className="ex-small">{failed?'3D unavailable. The film and education details remain available.':live&&!ready?'Loading the existing anatomy asset.':''}</span>
    </div><div className="ex-education-notes">{[section.blocks[1],section.blocks[3]].map(b=><p key={b.label}><strong>{b.label}</strong>{b.value}</p>)}</div><Credit/>
  </div></div>;
}

function MotionDemo({reduced}:{reduced:boolean}) {
  const [live,setLive]=useState(false),[failed,setFailed]=useState(false),[playing,setPlaying]=useState(false);
  const [info,setInfo]=useState({count:0,fps:60}),[frame,setFrame]=useState(0),[view,setView]=useState('front'),[reset,setReset]=useState(0);
  useEffect(()=>{if(reduced)setPlaying(false);},[reduced]);
  useEffect(()=>{
    if(!playing||!info.count)return;
    let raf=0,last=0,time=frame/info.fps;
    const tick=(now:number)=>{if(!document.hidden){if(last)time=(time+Math.min((now-last)/1000,.1))%(info.count/info.fps);setFrame(frameFromTime(time,info.fps,info.count));}last=now;raf=requestAnimationFrame(tick);};
    raf=requestAnimationFrame(tick);const visible=()=>{last=0;if(document.hidden){cancelAnimationFrame(raf);}else raf=requestAnimationFrame(tick);};document.addEventListener('visibilitychange',visible);
    return()=>{cancelAnimationFrame(raf);document.removeEventListener('visibilitychange',visible);};
  },[playing,info]);
  return <div className="ex-demo"><div className="ex-demo-stage">
    <div className="ex-hud-overlay" aria-hidden="true"><span className="ex-hud-tag">+ MOTION VIEWER</span><span className="ex-hud-coords">FRAME: {frame + 1}</span></div>
    {live&&!failed?<Suspense fallback={<Film id="projects" reduced/>}><LiveStudy kind="motion" frame={frame} view={view} reset={reset} onReady={(count,fps)=>setInfo({count,fps})} onFailure={()=>{setFailed(true);setLive(false);setPlaying(false);}}/></Suspense>:<Film id="biomech" reduced={reduced}/>}
    {!live&&<button type="button" className="ex-explore-button" onClick={()=>{setFailed(false);setLive(true);}}>Open motion viewer <span aria-hidden="true">↗</span></button>}
    </div><span className="ex-demo-badge">DEMO EXPORT / ACCURACY UNVERIFIED</span>
    {live&&<div className="ex-demo-controls"><div className="ex-control-row"><button type="button" disabled={!info.count} onClick={()=>setPlaying(!playing)}>{playing?'Pause':'Play'} motion</button><button type="button" aria-pressed={view==='front'} onClick={()=>setView('front')}>Front</button><button type="button" aria-pressed={view==='side'} onClick={()=>setView('side')}>Side</button><button type="button" onClick={()=>{setPlaying(false);setFrame(0);setView('front');setReset(v=>v+1);}}>Reset</button><button type="button" onClick={()=>{setLive(false);setPlaying(false);}}>Film</button></div>
      <label>Motion frame <output>{frame+1} / {info.count||'—'}</output><input type="range" aria-label="Motion frame" min="0" max={Math.max(0,info.count-1)} disabled={!info.count} value={frame} onChange={e=>{setPlaying(false);setFrame(Number(e.target.value));}}/></label></div>}
    {failed&&<p role="status">3D unavailable. The project film remains available.</p>}</div>;
}

function SystemStudy({reduced}:{reduced:boolean}) {
  const [active,setActive]=useState(0);
  const labels=['Source','Plan','Tools','Review'];
  return <div className="ex-system-study"><p className="ex-kicker">SOREN / WORKFLOW STUDY</p><h3>From source<br/>to something<br/><em>worth reviewing.</em></h3><div className="ex-system-chain" aria-label="Illustrative workflow">{labels.map((name,i)=><button key={name} type="button" aria-pressed={active===i} onClick={()=>setActive(i)}><span>0{i+1}</span>{name}</button>)}</div>
    <TransitionPanel active={active} reduced={reduced}><p>{['Start with the supplied material and verified context.','Make the intended work and its limits clear.','Connect appropriate tools to the task.','Inspect the result and record what remains unverified.'][active]}</p></TransitionPanel><span className="ex-small">Illustrative diagram · no background agent is running</span></div>;
}
function StepprStudy(){const [night,setNight]=useState(false);return <div className={'ex-steppr-study'+(night?' is-night':'')}><p className="ex-kicker">STEPPR / ENVIRONMENT STUDY</p><h3>Same space.<br/><em>Different light.</em></h3><p>A study of atmosphere, lighting, and first-person navigation in Spline.</p><button className="ex-light-switch" type="button" role="switch" aria-checked={night} onClick={()=>setNight(!night)}><span aria-hidden="true"/>{night?'Night palette':'Day palette'}</button><p className="ex-small">Palette preview only. Open Spline for the actual room.</p><a className="ex-button" href={splineUrl} target="_blank" rel="noopener noreferrer">Open the Spline study ↗</a></div>;}

function BiomechanicalLabStage({reduced}:{reduced:boolean}) {
  const [open,setOpen]=useState(false);
  return <div className="ex-biomech-stage">
    <div className="ex-hud-overlay" aria-hidden="true"><span className="ex-hud-tag">+ CYBERNETIC LAB</span><span className="ex-hud-coords">TELEMETRY MATRIX</span></div>
    <Film id="projects" reduced={reduced}/>
    <div className="ex-stage-stamp"><span>PROJECT 05 · biomech-lab</span><strong>Biomechanical Cybernetic Lab</strong></div>
    <button type="button" className="ex-explore-button" onClick={()=>setOpen(true)}>Open 3D laboratory <span aria-hidden="true">↗</span></button>
    {open&&<Suspense fallback={null}><BiomechanicalLabProject isOpen={open} onClose={()=>setOpen(false)}/></Suspense>}
  </div>;
}

function ResumeStudy({reduced}:{reduced:boolean}) {
  const [active,setActive]=useState(0);
  const ids=['about','experience','education','projects','skills','contact'];
  return <div className="ex-resume-study"><div className="ex-resume-study-heading"><span className="ex-kicker">LIVING RÉSUMÉ / MOTION LIBRARY</span><h3>Six topics.<br/><em>One living system.</em></h3></div><Film key={ids[active]} id={ids[active]} reduced={reduced}/><div className="ex-resume-study-controls" aria-label="Résumé film previews">{ids.map((id,i)=><button key={id} type="button" aria-pressed={active===i} onClick={()=>setActive(i)}>{id}</button>)}</div></div>;
}

function Projects({section,reduced,initialProject}:Props) {
  const [active,setActive]=useState(()=>Math.max(0,projects.findIndex(p=>p.id===initialProject))),[expanded,setExpanded]=useState<string|null>('evidence');
  const project=projects[active];
  return <div className="ex-project-layout"><div className="ex-project-select"><ChapterTabs labels={projects.map(p=>p.title)} active={active} onChange={setActive} label="Selected projects"/></div>
    <Panel active={active}><div className={'ex-project-grid ex-project-'+project.id}><div className="ex-project-stage" key={project.id}>
      {active===0?<MotionDemo reduced={reduced}/>:active===1?<SystemStudy reduced={reduced}/>:active===2?<StepprStudy/>:active===3?<ResumeStudy reduced={reduced}/>:<BiomechanicalLabStage reduced={reduced}/>}
    </div><div className="ex-project-story"><span className="ex-kicker">0{active+1} / {project.status}</span><h2>{project.title}</h2><p>{project.overview}</p><div className="ex-stack">{project.stack.map(s=><span key={s}>{s}</span>)}</div>
      <div className="ex-expandable">{(['problem','build','evidence','limits'] as const).map(key=><div key={key}><h3><button type="button" aria-expanded={expanded===key} aria-controls={'ex-project-'+key} onClick={()=>setExpanded(expanded===key?null:key)}>{key}<span aria-hidden="true">{expanded===key?'−':'+'}</span></button></h3>
        <motion.div id={'ex-project-'+key} className="ex-expand-content" inert={expanded!==key} initial={false} animate={{height:expanded===key?'auto':0,opacity:expanded===key?1:0}} transition={{duration:reduced?0:.24}}><p>{project[key]}</p></motion.div></div>)}</div>
    </div></div></Panel></div>;
}

function Skills({section,reduced,onNavigate}:Props) {
  const [active,setActive]=useState(0),[reset,setReset]=useState(0);
  const bounds=useRef<HTMLDivElement>(null);
  const skill=skillLinks[active];
  return <div className="ex-skills-layout"><div className="ex-workbench" ref={bounds}><p className="ex-kicker">A TOOLKIT / IN USE</p><h2>Pick a tool.<br/><em>Follow the work.</em></h2><div className="ex-tool-grid" key={reset}>{skillLinks.map((tool,i)=><motion.button key={tool.name} type="button" drag={!reduced} dragConstraints={bounds} dragMomentum={false} dragElastic={.08} whileDrag={{scale:1.06,zIndex:3}} className={'ex-tool ex-tool-'+i} aria-pressed={active===i} onClick={()=>setActive(i)}><span>{tool.category}</span><strong>{tool.name}</strong><span className="ex-tool-number">0{i+1}</span></motion.button>)}</div>
    <div className="ex-workbench-bottom"><span>Click or tap to connect. Drag to arrange.</span><button type="button" className="ex-text-link" onClick={()=>setReset(v=>v+1)}>Reset positions</button></div></div>
    <div className="ex-skills-story"><Film id="skills" reduced={reduced}/><div className="ex-skill-connection"><span className="ex-kicker">SELECTED CONNECTION</span><TransitionPanel active={active} reduced={reduced}><h2>{skill.name}</h2><p>{skill.note}</p><div className="ex-connection-path"><span className={'ex-beam'+(reduced?' is-static':'')} aria-hidden="true"/>{skill.projects.map(id=><button type="button" className="ex-project-link" key={id} onClick={()=>onNavigate('projects',id)}>{projectTitle(id)} <span aria-hidden="true">↗</span></button>)}</div></TransitionPanel></div>
    <details className="ex-skill-inventory"><summary>Read the complete toolkit</summary>{section.blocks.map(b=><p key={b.label}><strong>{b.label}</strong>{b.value}</p>)}</details></div></div>;
}

function Contact({section,reduced}:Props) {
  return <div className="ex-contact-layout"><div className="ex-contact-stage"><Film id="contact" reduced={reduced}/><span className="ex-postcard-stamp">SOREN SADR / AN OPEN INVITATION</span></div><div className="ex-contact-story"><p className="ex-kicker">LET'S FOLLOW THE CURIOSITY</p><h2>Movement.<br/>Making.<br/><em>What's next?</em></h2><p>{section.lead}</p><a className="ex-contact-link" href={githubUrl} target="_blank" rel="noopener noreferrer"><span>01 / CODE & EXPERIMENTS</span><strong>GitHub <span aria-hidden="true">↗</span></strong></a><a className="ex-contact-link" href={splineUrl} target="_blank" rel="noopener noreferrer"><span>02 / SPACES & INTERACTION</span><strong>Spline study <span aria-hidden="true">↗</span></strong></a><CopyButton text={githubUrl}/><a className="ex-copy-source" href={githubUrl}>{githubUrl}</a></div></div>;
}

export function SectionExplorer(props:Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const components:Record<string,(p:Props)=>ReactNode>={about:About,experience:Experience,education:Education,projects:Projects,skills:Skills,contact:Contact};
  const Component=components[props.section.id];

  useEffect(() => {
    if (containerRef.current) {
      const tl = animateModalEntrance(containerRef.current, { reduced: props.reduced });
      return () => {
        tl?.kill();
      };
    }
  }, [props.section.id, props.reduced]);

  return (
    <div ref={containerRef} className={'ex-scroll ex-'+props.section.id} style={{ position: 'relative' }}>
      <ModalAmbientCanvas accentColor={sectionHexAccents[props.section.id]} reduced={props.reduced}/>
      <Heading section={props.section} reduced={props.reduced}/>
      <main className="ex-content" style={{ position: 'relative', zIndex: 1 }}><Component {...props}/></main>
      <footer className="ex-footer" style={{ position: 'relative', zIndex: 1 }}>
        <span>SOREN / A LIVING RÉSUMÉ</span>
        <span>Draft résumé content · projects and studies in progress</span>
      </footer>
    </div>
  );
}
