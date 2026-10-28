import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import MotionApp from './MotionApp.jsx';
import EvidencePassport from './EvidencePassport.jsx';
import GuidedCaptureWizard from './GuidedCaptureWizard.jsx';
import ReportStudio from './ReportStudio.jsx';
import {NAV_ITEMS,STAGES,formatSession,roleStatus,apiSessionPath,readAccessToken} from './unifiedModel.js';

const API='/api/v1';
const TEST_ID='caliscope-walking-test-20261027';
const ROLE_NAMES={
 cam01_intrinsics:'Phone · Intrinsic calibration',cam02_intrinsics:'Webcam · Intrinsic calibration',
 cam01_board:'Phone · Board view',cam02_board:'Webcam · Board view',
 cam01_trial:'Phone · Movement trial',cam02_trial:'Webcam · Movement trial',
};
const NAV_SIGNS={
 overview:'◈',sessions:'▦',capture:'◉',processing:'◎',motion:'◇',analysis:'⌁',reports:'▤',diagnostics:'⚙',
};
const dateMeta='Prototype / research only • Physical measurement accuracy unverified';

function Pill({children,tone='neutral'}){
 return <span className={'uw-pill uw-pill-'+tone}>{children}</span>;
}
function Box({children,className=''}){return <section className={'uw-card '+className}>{children}</section>}
function CardHeading({eyebrow,heading,detail,action}){
 return <div className="uw-card-header">
  <div><div className="uw-overline">{eyebrow}</div><h3>{heading}</h3>
   {detail&&<p>{detail}</p>}</div>{action}
 </div>;
}
function Notice({message,onClose}){
 if(!message)return null;
 return <div className={'uw-toast '+(message.type==='error'?'uw-error':'uw-info')} role="status">
  <span>{message.text}</span><button aria-label="Dismiss message" onClick={onClose}>×</button>
 </div>;
}
function EmptyState({headline,detail}){
 return <div className="uw-empty"><span aria-hidden="true">◇</span><strong>{headline}</strong>
  <p>{detail}</p></div>;
}
function Field({label,children}){return <label className="uw-field"><span>{label}</span>{children}</label>;}

export default function UnifiedApp(){
 const token=useMemo(()=>readAccessToken(window.location.hash),[]);
 const [view,setView]=useState('overview');
 const [sessions,setSessions]=useState([]);
 const [selected,setSelected]=useState('');
 const [detail,setDetail]=useState(null);
 const [passport,setPassport]=useState(null);
 const [job,setJob]=useState(null);
 const [camera,setCamera]=useState(null);
 const [reports,setReports]=useState([]);
 const [analysis,setAnalysis]=useState(null);
 const [recovery,setRecovery]=useState(null);
 const [newId,setNewId]=useState('');
 const [operator,setOperator]=useState('');
 const [boardMm,setBoardMm]=useState('');
 const [loading,setLoading]=useState(true);
 const [busy,setBusy]=useState('');
 const [notice,setNotice]=useState(null);
 const [lastPoll,setLastPoll]=useState('');
 const inputRefs=useRef({});
 const show=(text,type='info')=>setNotice({text:String(text),type});

 const api=useCallback(async(path,{method='GET',body=null,binary=false}={})=>{
  if(!token)throw Error('Open KineLab PT using its single desktop icon to authorize the local workspace.');
  const headers={Authorization:'Bearer '+token};
  if(!binary && body!==null)headers['Content-Type']='application/json';
  if(binary){headers['Content-Type']='video/mp4';headers['X-KineLab-Consent']='yes';}
  const response=await fetch(path,{method,headers,
   body:body===null?undefined:(binary?body:JSON.stringify(body)),cache:'no-store'});
  if(!response.ok){
   let msg='Local service rejected this action (HTTP '+response.status+')';
   try{const result=await response.json();msg=result.error??msg}catch{/* keep honest status */}
   throw Error(msg);
  }
  return response;
 },[token]);
 const json=useCallback(async(path,options)=>await (await api(path,options)).json(),[api]);

 const refreshSessions=useCallback(async()=>{
  const result=await json(API+'/sessions');
  setSessions(result.sessions||[]);
  setSelected(old=>{
   if(result.sessions.some(item=>item.id===old))return old;
   return result.sessions.find(item=>item.id==='capture-20261026-trial01')?.id
     ??result.sessions.find(item=>item.kind==='real'&&item.status==='draft')?.id
     ??result.sessions[0]?.id??'';
  });
 },[json]);

 const refreshSelected=useCallback(async(sid)=>{
  if(!sid){setDetail(null);setPassport(null);setReports([]);setJob(null);setCamera(null);return}
  const base=apiSessionPath(sid);
  try {
    const [info,pstate,cstate,reps,pass]=await Promise.all([
     json(base),json(base+'/processing'),json(base+'/capture'),json(base+'/reports'),json(base+'/passport')]);
    setDetail(info);setJob(pstate);setCamera(cstate);setReports(reps.reports||[]);setPassport(pass);
  } catch(e) {
    const [info,pstate,cstate,reps]=await Promise.all([
     json(base),json(base+'/processing'),json(base+'/capture'),json(base+'/reports')]);
    setDetail(info);setJob(pstate);setCamera(cstate);setReports(reps.reports||[]);setPassport(null);
  }
  setLastPoll(new Date().toLocaleTimeString());
 },[json]);

 useEffect(()=>{
  if(!token){setLoading(false);return}
  let cancelled=false;
  Promise.all([refreshSessions(),json(API+'/analysis')])
   .then(([,data])=>{if(!cancelled)setAnalysis(data)})
   .catch(error=>{if(!cancelled)show(error.message,'error')})
   .finally(()=>{if(!cancelled)setLoading(false)});
  return ()=>{cancelled=true};
 },[token,refreshSessions,json]);

 useEffect(()=>{
  if(!selected||!token)return;
  let active=true;
  refreshSelected(selected).catch(error=>{if(active)show(error.message,'error')});
  return ()=>{active=false};
 },[selected,token,refreshSelected]);

 useEffect(()=>{
  if(!selected||!token)return;
  const tick=()=>refreshSelected(selected).catch(()=>{});
  const id=setInterval(tick,3500);
  return ()=>clearInterval(id);
 },[selected,token,refreshSelected]);

 const mutate=async(label,work)=>{
  if(busy)return;
  setBusy(label);setNotice(null);
  try{
   const response=await work();
   show((response&&response.message)||label+' completed. Review the updated status.');
   await refreshSessions();
   if(selected)await refreshSelected(selected);
  }catch(error){show(error.message,'error')}
  finally{setBusy('')}
 };
 const doPost=(suffix,data)=>json(apiSessionPath(selected)+suffix,
   {method:'POST',body:data});

 function confirmAction(message){
  return window.confirm(message);
 }
 function openNative(target){
  if(!selected)return show('Choose a session first.','error');
  if(!confirmAction('Open '+target+' for session '+selected+'? This may open a native window.'))return;
  mutate('open-'+target,()=>doPost('/open',{target,confirm:true}));
 }
 const newSession=()=>{
  const text=newId.trim();
  if(!text)return show('Provide a unique session ID.','error');
  if(!confirmAction('Create a new, unregistered REAL capture session named '+text+'?'))return;
  mutate('new-session',async()=>{
   const result=await json(API+'/sessions',{method:'POST',body:{id:text,kind:'real'}});
   setSelected(result.id);setNewId('');
   return {message:'New local session created: '+result.id};
  });
 };
 const register=()=>{
  if(!detail?.ready_to_register)return show('Registration is blocked until six sources and real board measurement pass file checks.','error');
  if(!confirmAction('Permanently register six REAL original video hashes? This is NOT clinical validation and prevents replacing selected footage.'))return;
  mutate('register',()=>doPost('/register',{confirm:true}));
 };
 const saveBoard=()=>{
  const mm=Number(boardMm);
  if(!Number.isFinite(mm)||mm<=0||!operator.trim())return show('Enter the actual measured square side and operator initials.','error');
  if(!confirmAction('Did you physically measure the printed square with a ruler? Save '+mm+' mm as an operator measurement?'))return;
  mutate('board',async()=>{
   const value=await doPost('/board',{confirm:true,mm,operator:operator.trim()});
   return {message:'Recorded physical ruler entry of '+value.measured_square_mm+' mm. This is not verified calibration.'};
  });
 };
 async function importPhone(role,file){
  if(!file)return;
  if(file.size>1024*1024*1024)return show('MP4 exceeds the 1 GiB local import limit. Use the native Capture Station.','error');
  if(!file.name.toLowerCase().endsWith('.mp4'))return show('Only genuine MP4 footage can be imported.','error');
  if(!confirmAction('Import this local phone MP4 as '+role+' in '+selected+'? Existing originals are never overwritten.'))return;
  mutate('import-'+role,async()=>{
   const result=await api(apiSessionPath(selected)+'/import/'+role,
     {method:'POST',body:file,binary:true});
   const body=await result.json();
   return {message:body.filename+' copied and probed. The source remains unchanged.'};
  });
 }
 const startCapture=(role,seconds)=>{
  if(!confirmAction('Turn ON the Integrated Webcam and record '+seconds+' seconds for '+role+'? Video stays local.'))return;
  mutate('capture',()=>doPost('/capture',{confirm:true,role,seconds}));
 };
 const stopCapture=()=>{
  if(!confirmAction('Stop the local webcam and finalize the MP4? Partial data may remain unverified.'))return;
  mutate('stop-capture',()=>doPost('/capture/stop',{confirm:true}));
 };
 const processAction=id=>{
  if(!confirmAction('Run native '+id+' for '+selected+'? Existing synchronization and quality gates remain strict.'))return;
  mutate('process-'+id,()=>doPost('/processing',{confirm:true,action:id}));
 };
 const cancelProcess=()=>{
  if(!confirmAction('Cancel the verified native process tree? Partial outputs will remain UNVERIFIED.'))return;
  mutate('cancel-process',()=>doPost('/processing/cancel',{confirm:true}));
 };
 const fetchRecovery=()=>mutate('recovery',async()=>{
  setRecovery(await json(apiSessionPath(selected)+'/recovery'));
  return {message:'Recovery and lock diagnostics inspected without changing any files.'};
 });
 const downloadReport=async item=>{
  try{
   setBusy('download-'+item.key);
   const response=await api(apiSessionPath(selected)+'/artifact/'+item.key);
   const blob=await response.blob(),url=URL.createObjectURL(blob);
   const link=document.createElement('a');link.href=url;link.download=item.filename;
   document.body.append(link);link.click();link.remove();
   setTimeout(()=>URL.revokeObjectURL(url),2000);
   show('Downloaded '+item.filename+' from the selected local session.');
  }catch(error){show(error.message,'error')}
  finally{setBusy('')}
 };

 const handleGenerateReports = async (sid) => {
  if (!confirmAction(`Generate truthful offline PDF, CSV and JSON research reports for ${sid}?`)) return;
  mutate('generate-reports', async () => {
   const res = await json(apiSessionPath(sid) + '/reports/generate', { method: 'POST', body: { confirm: true } });
   await refreshSelected(sid);
   return res;
  });
 };

 const handleCompareSessions = async (s1, s2) => {
  return await json(`${API}/compare?s1=${encodeURIComponent(s1)}&s2=${encodeURIComponent(s2)}`);
 };

 const handleCreateBackup = async () => {
  if (!confirmAction('Create a local ZIP backup of all sessions and the SQLite index?')) return;
  mutate('create-backup', async () => {
   const res = await json(`${API}/backup/create`, { method: 'POST', body: { confirm: true } });
   return res;
  });
 };

 const handleRestoreBackup = async (backupName) => {
  if (!confirmAction(`Restore sessions from ${backupName}? This will verify all file hashes in safe staging before updating.`)) return;
  mutate('restore-backup', async () => {
   const res = await json(`${API}/backup/restore`, { method: 'POST', body: { confirm: true, backup_name: backupName, overwrite: true } });
   await refreshSessions();
   if (selected) await refreshSelected(selected);
   return res;
  });
 };

 const active=sessions.find(entry=>entry.id===selected);
 const mode=active?formatSession(active):null;
 const subhead=NAV_ITEMS.find(item=>item.id===view);

 if(!token)return <div className="uw-legacy">
  <div className="uw-old-warning">This legacy Motion Lab shortcut opens the viewer only.
   For the unified workspace, double-click the <strong>KineLab PT</strong> desktop icon.</div>
  <MotionApp/>
 </div>;

 const navigation=()=>{
  setRecovery(null);
  if(view==='diagnostics'&&selected)fetchRecovery();
 };

 return <div className="uw-app">
  <aside className="uw-sidebar" aria-label="Application navigation">
   <div className="uw-brand"><div className="uw-brand-mark">K</div><div><strong>KineLab PT</strong>
    <span>Motion Analysis Studio</span></div></div>
   <div className="uw-sidebar-group">WORKSPACE</div>
   <nav aria-label="KineLab views">{NAV_ITEMS.map(item=><button
    key={item.id} type="button" className={'uw-nav-link '+(view===item.id?'is-active':'')}
    aria-current={view===item.id?'page':undefined}
    onClick={()=>{setView(item.id);if(item.id==='diagnostics'&&selected)fetchRecovery()}}>
    <span className="uw-nav-icon" aria-hidden="true">{NAV_SIGNS[item.id]}</span>
    <span>{item.label}<small>{item.description}</small></span>
   </button>)}</nav>
   <div className="uw-sidebar-bottom">
    <span className="uw-online-dot"/> LOCAL SYSTEM <strong>ONLINE</strong>
    <p>127.0.0.1 · Offline-first<br/>No cloud upload or clinical validation.</p>
   </div>
  </aside>

  <div className="uw-main">
   <header className="uw-topbar">
    <div className="uw-top-title"><span>KINELAB / WORKSPACE</span>
     <h2>{subhead?.label||'Overview'}</h2>
    </div>
    <div className="uw-top-controls">
     <label className="uw-select-wrap"><span>ACTIVE SESSION</span>
      <select aria-label="Select active session" value={selected}
       onChange={event=>setSelected(event.target.value)} disabled={loading||!!busy}>
       {!selected&&<option value="">No sessions available</option>}
       {sessions.map(session=><option value={session.id} key={session.id}>{session.id}</option>)}
      </select></label>
     <Pill tone={mode?.badge==='TEST ONLY'?'warning':'neutral'}>{mode?.badge??'NO SESSION'}</Pill>
    </div>
   </header>
   <div className="uw-content">
    <Notice message={notice} onClose={()=>setNotice(null)}/>
    {loading&&<div className="uw-loading" role="status">Connecting to local session library...</div>}
    {!loading&&<div className="uw-view">
     <div className="uw-title-row"><div><span className="uw-overline">T6 / INTEGRATED MOTION WORKSPACE</span>
      <h1>{subhead?.label}</h1>
      <p>{subhead?.description}. {dateMeta}</p></div>
      <span className="uw-version">KINELAB PT / V1 DEVELOPMENT</span>
     </div>

     {view==='overview'&&<>
      <div className="uw-stat-grid">
       <div className="uw-stat"><span>LOCAL SESSIONS</span><strong>{sessions.length}</strong><small>Test recordings stay separated</small></div>
       <div className="uw-stat"><span>CAPTURE SLOTS</span><strong>{mode?.count??'—'}</strong><small>Current selected session</small></div>
       <div className="uw-stat"><span>STATUS</span><strong className="uw-stat-word">{mode?.badge??'NO SESSION'}</strong><small>No physical accuracy claim</small></div>
       <div className="uw-stat"><span>NATIVE JOB</span><strong className="uw-stat-word">{job?.state?.toUpperCase()??'IDLE'}</strong><small>Only native passes count</small></div>
      </div>
      <EvidencePassport passport={passport} onOpenNative={openNative} />
      <div className="uw-two" style={{marginTop:'18px'}}>
       <Box><CardHeading eyebrow="YOUR NEXT WORKFLOW" heading="From capture to motion"
        detail="Every step uses the current local session and the existing quality gates."/>
        <div className="uw-step-list">{[
         ['01','Capture','Record webcam, import phone MP4, measure board','capture'],
         ['02','Process','Normalize, calibrate, synchronize, reconstruct','processing'],
         ['03','Review','Open verified 3D motion and actual joint graphs','motion'],
         ['04','Analyze','Inspect research-grade gait and squat experiments','analysis'],
        ].map(([index,heading,desc,next])=><button key={index} className="uw-step"
          onClick={()=>setView(next)}><span>{index}</span><div><strong>{heading}</strong><small>{desc}</small></div>
          <em>→</em></button>)}</div>
       </Box>
       <Box><CardHeading eyebrow="SESSION HEALTH" heading={selected||'No session selected'}
         detail="No test clips will be presented as calibrated clinical recordings."/>
        <div className="uw-checklist">
         {Object.entries(detail?.sources||{}).map(([name,present])=><div key={name}>
          <span>{name}</span><Pill tone={present?'present':'neutral'}>{present?'Available':'Missing'}</Pill>
         </div>)}
         {!detail&&<EmptyState headline="No selected session" detail="Create a new real session in the Sessions tab."/>}
        </div>
       </Box>
      </div>
     </>}

     {view==='sessions'&&<>
      <div className="uw-two">
       <Box><CardHeading eyebrow="NEW LOCAL WORKSPACE" heading="Create a recording session"
         detail="No camera opens and no files are registered until you explicitly request them."/>
        <div className="uw-form-inline">
         <Field label="Unique session ID"><input value={newId}
          onChange={event=>setNewId(event.target.value)}
          placeholder="e.g. gait-pilot-01" maxLength={100}/></Field>
         <button className="uw-btn primary" onClick={newSession} disabled={!!busy}>Create session</button>
        </div>
        <p className="uw-help">Session IDs stay under the local projects folder. Existing files are never overwritten.</p>
       </Box>
       <Box><CardHeading eyebrow="CURRENT SESSION" heading={selected||'None'}
        detail={mode?.badge+' · '+(mode?.count??'0 / 6')+' source recordings'}/>
        <div className="uw-actions">
         <button className="uw-btn" disabled={!selected} onClick={()=>openNative('folder')}>Open local folder</button>
         <button className="uw-btn" disabled={!selected} onClick={()=>openNative('capture')}>Open Capture Station</button>
        </div>
       </Box>
      </div>
      <Box><CardHeading eyebrow="LOCAL LIBRARY" heading="Your session inventory"
       detail="Select a row to open its capture, processing and reports status."/>
       <div className="uw-list">{sessions.map(session=>{
        const s=formatSession(session);
        return <button className={'uw-session-row '+(selected===session.id?'chosen':'')}
          key={session.id} onClick={()=>setSelected(session.id)}>
          <div><strong>{session.id}</strong><small>{session.kind} · {session.status}</small></div>
          <Pill tone={session.kind==='test-only'?'warning':session.status==='registered'?'present':'neutral'}>{s.badge}</Pill>
          <span>{s.count} sources</span><em>→</em>
         </button>;
       })}
       {!sessions.length&&<EmptyState headline="No local sessions" detail="Create your first recording session above."/>}</div>
      </Box>
     </>}

     {view==='capture'&&<GuidedCaptureWizard
       detail={detail}
       selectedSession={selected}
       activeSession={active}
       cameraState={camera}
       busy={busy}
       onImportPhone={importPhone}
       onStartCapture={startCapture}
       onStopCapture={stopCapture}
       onSaveBoard={(mm, op) => mutate('board', () => doPost('/board', { confirm: true, mm, operator: op }))}
       onRegister={register}
       onOpenNative={openNative}
     />}

     {view==='processing'&&<>
      <Box><CardHeading eyebrow="POSE2SIM / OPEN SIM PIPELINE" heading="Native processing coordinator"
       detail="Each action starts only on request. Actual stage and hash checks—not process exit alone—determine acceptance."/>
       <div className="uw-progress"><div>
        <Pill tone={job?.state==='passed'?'present':job?.state==='running'?'warning':'neutral'}>
         {job?.state?.toUpperCase()??'IDLE'}</Pill>
         <p>{job?.message??'No native stage has been started.'}</p>
        </div>
        {job?.state==='running'&&<button className="uw-btn danger" onClick={cancelProcess}
         disabled={!!busy}>Cancel native action</button>}
       </div>
       <div className="uw-stage-grid">{STAGES.map(stage=><div className="uw-stage" key={stage.id}>
        <div className="uw-stage-ico">◎</div><strong>{stage.label}</strong>
        <p>{stage.description}</p>
        <button className="uw-btn" onClick={()=>processAction(stage.id)}
          disabled={!!busy||active?.kind!=='real'||active?.status!=='registered'||job?.state==='running'}>
          Start stage</button>
       </div>)}</div>
      </Box>
      <div className="uw-two">
       <Box><CardHeading eyebrow="RECONSTRUCTION PREREQUISITES" heading="Evidence checkpoints"/>
        <div className="uw-checklist">{[
          ['Source hash manifest',detail?.sources?.['session.json']],
          ['Verified normalization preflight',detail?.sources?.['preflight.json']],
          ['Manually observed sync cues',detail?.sources?.['sync-observations.json']],
          ['Native Pose2Sim run manifest',detail?.sources?.['run.json']],
         ].map(([label,value])=><div key={label}><span>{label}</span>
          <Pill tone={value?'present':'neutral'}>{value?'File exists':'Missing'}</Pill></div>)}</div>
       </Box>
       <Box><CardHeading eyebrow="MANUAL FRAME REVIEW" heading="Observe synchronization cues"
        detail="Existing native two-camera cue reviewer verifies the exact displayed video frame."/>
        <button className="uw-btn" onClick={()=>openNative('sync')} disabled={!selected}>
         Open native frame review</button>
        <p className="uw-help">Native correlation, reference and drift must still be verified by Pose2Sim.</p>
       </Box>
      </div>
     </>}

     {view==='motion'&&<div className="uw-motion-slot"><MotionApp/></div>}

     {view==='analysis'&&<>
      <div className="uw-two">
       <Box><CardHeading eyebrow="2D WALKING TEST" heading="Gait event review"
        detail="Unvalidated foot-motion proposals, annotated sample videos and human observations."/>
        <div className="uw-analysis-data">
         {(analysis?.gait?.candidates||[]).map(v=><div key={v.role}>
          <span>{v.role}</span><strong>{v.count} extrema</strong></div>)}
        </div>
        <Pill tone="warning">{analysis?.gait?.status==='unvalidated_candidates'?'UNVALIDATED / TEST ONLY':'NO SAMPLE'}</Pill>
        <p className="uw-help">These extrema are not confirmed heel strikes, toe-offs or step counts.</p>
       </Box>
       <Box><CardHeading eyebrow="SYNTHETIC EXERCISE MODULE" heading="Squat phase detection"
        detail="Tested algorithm; awaiting real, manually reviewed side-view squat footage."/>
        <div className="uw-analysis-data"><div><span>Algorithm</span><strong>2D phase / repetition</strong></div>
        <div><span>Test status</span><strong>15 focused checks passed</strong></div>
        <div><span>Physical validation</span><strong>Not established</strong></div></div>
        <Pill tone="warning">SYNTHETIC TESTS ONLY</Pill>
        <p className="uw-help">No real squat counts, joint angles or clinical outcomes are fabricated.</p>
       </Box>
      </div>
      {analysis?.gait?.status==='unvalidated_candidates'&&<Box>
        <CardHeading eyebrow="LOCAL EXPERIMENTAL WORKSPACE" heading="Manual gait-event reviewer"
         detail="Inspect the two sample videos, label events before seeing hypotheses, and keep references separate."/>
        <iframe className="uw-embed" src="/samples/gait-t5/index.html"
         sandbox="allow-scripts allow-downloads"
         title="Test-only Caliscope gait event review (not clinically validated)" loading="lazy"/>
       </Box>}
     </>}

     {view==='reports'&&<ReportStudio
       sessions={sessions}
       selectedSession={selected}
       reports={reports}
       busy={busy}
       onSelectSession={setSelected}
       onDownloadReport={downloadReport}
       onGenerateReports={handleGenerateReports}
       onCompareSessions={handleCompareSessions}
       onCreateBackup={handleCreateBackup}
       onRestoreBackup={handleRestoreBackup}
       onOpenFolder={()=>openNative('folder')}
     />}

     {view==='diagnostics'&&<>
      <div className="uw-two">
       <Box><CardHeading eyebrow="LOCAL SERVICE" heading="Runtime and access"
        detail="Private loopback Python API authenticated by this app session's local token."/>
        <div className="uw-checklist">
         <div><span>API binding</span><Pill tone="present">127.0.0.1 ONLY</Pill></div>
         <div><span>Cloud endpoints</span><Pill>NONE</Pill></div>
         <div><span>Clinical validation</span><Pill tone="warning">UNVERIFIED</Pill></div>
         <div><span>Last status refresh</span><span>{lastPoll||'Not yet'}</span></div>
        </div>
        <div className="uw-actions">
         <button className="uw-btn" onClick={()=>openNative('runbook')} disabled={!selected}>Open runbook</button>
         <button className="uw-btn" onClick={()=>refreshSelected(selected)} disabled={!selected}>Refresh status</button>
        </div>
       </Box>
       <Box><CardHeading eyebrow="SAFE RECOVERY" heading="Native jobs and abandoned locks"
        detail="Diagnostics do not delete or clear run locks. Use the original Capture Station for confirmed orphan archival."/>
        <button className="uw-btn" onClick={fetchRecovery} disabled={!selected||!!busy}>Inspect lock state</button>
        {recovery&&<div className="uw-checklist">
         {Object.entries(recovery.locks||{}).map(([name,lock])=><div key={name}>
          <span>{name}</span><Pill tone={lock.state==='absent'?'present':'warning'}>{lock.state}</Pill>
         </div>)}
         <div><span>Native run state</span><strong>{recovery.native_run}</strong></div>
        </div>}
       </Box>
      </div>
      <Box><CardHeading eyebrow="QUALITY BOUNDARY" heading="What does not count as a clinical pass"
       detail="Test videos, synthetic squat repetitions, raw model scores, and an incomplete six-role capture."/>
       <p className="uw-help">A proper consumer physical-measurement pilot requires matching phone and webcam views,
        measured board geometry, independently confirmed cue timing, native camera reprojection quality,
        reconstruction repeatability and suitable external reference evidence.</p>
      </Box>
     </>}
    </div>}
    <footer className="uw-footer">
     <span>© KineLab PT · Local research platform</span>
     <span>No fabricated data · Test-only results remain segregated · Not for diagnosis</span>
    </footer>
   </div>
  </div>
 </div>;
}
