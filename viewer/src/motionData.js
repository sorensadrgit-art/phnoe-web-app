// Pure, dependency-free boundary shared by demo and local-file playback.
const angular=new Set([
 'pelvis_tilt','pelvis_list','pelvis_rotation','lumbar_extension','lumbar_bending','lumbar_rotation',
 'neck_flexion','neck_bending','neck_rotation','Abs_r1','Abs_r2','Abs_r3','knee_angle_r_beta','knee_angle_l_beta',
 ...['L5_S1','L4_L5','L3_L4','L2_L3','L1_L2','L1_T12'].flatMap(joint=>
  ['Flex_Ext','Lat_Bending','axial_rotation'].map(axis=>`${joint}_${axis}`)),
 ...['r','l'].flatMap(side=>[
  'hip_flexion','hip_adduction','hip_rotation','knee_angle','ankle_angle','subtalar_angle',
  'mtp_angle','arm_flex','arm_add','arm_rot','elbow_flex','pro_sup','wrist_flex','wrist_dev'
 ].map(name=>`${name}_${side}`))
]);
const translations=new Set(['pelvis_tx','pelvis_ty','pelvis_tz','Abs_t1','Abs_t2']);
// OpenSim's coupled patellar coordinates remain radians in degree-declared MOT.
const nativeRadians=new Set(['knee_angle_r_beta','knee_angle_l_beta']);
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const hash=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
const fail=message=>{throw new Error(`Invalid motion: ${message}`)};

function checkTimes(times){
 if(!times.length||times.some((t,i)=>!finite(t)||(i>0&&t<=times[i-1])))
  fail('timestamps must be finite and strictly increasing');
}
function minInterval(times,fallback){
 let result=Infinity;
 for(let i=1;i<times.length;i++)result=Math.min(result,times[i]-times[i-1]);
 return result===Infinity?fallback:result;
}
function floorIndex(times,seconds){
 let lo=0,hi=times.length;
 while(lo<hi){const mid=Math.floor((lo+hi)/2);if(times[mid]<=seconds)lo=mid+1;else hi=mid;}
 return Math.max(0,lo-1);
}
function nearestIndex(times,seconds){
 const i=floorIndex(times,seconds);
 return i+1<times.length&&Math.abs(times[i+1]-seconds)<Math.abs(times[i]-seconds)?i+1:i;
}
function coordinateType(name){
 return angular.has(name)?'angular':translations.has(name)?'translation':null;
}
function coordinateUnit(name,inDegrees){
 return translations.has(name)?'m':inDegrees&&!nativeRadians.has(name)?'deg':'rad';
}
function validateKinematics(kin){
 if(!object(kin)||typeof kin.inDegrees!=='boolean')fail('kinematics requires boolean inDegrees');
 const {columns,rows}=kin;
 if(!Array.isArray(columns)||columns.length<2||columns[0]!=='time'||
  columns.some(c=>typeof c!=='string'||!c.trim()||c!==c.trim())||new Set(columns).size!==columns.length)
  fail('kinematics requires unique columns starting with time');
 const types={};
 for(const name of columns.slice(1)){
  const type=coordinateType(name);
  if(!type)fail(`unsupported OpenSim coordinate ${name}; explicit unit mapping required`);
  types[name]=type;
 }
 if(kin.columnTypes!==undefined&&(!object(kin.columnTypes)||Object.keys(kin.columnTypes).length!==columns.length-1||
  columns.slice(1).some(name=>kin.columnTypes[name]!==types[name])))
  fail('coordinate type mapping disagrees with supported OpenSim units');
 if(kin.columnUnits!==undefined&&(!object(kin.columnUnits)||Object.keys(kin.columnUnits).length!==columns.length-1||
  columns.slice(1).some(name=>kin.columnUnits[name]!==coordinateUnit(name,kin.inDegrees))))
  fail('coordinate unit mapping disagrees with native OpenSim units');
 if(!Array.isArray(rows)||!rows.length||rows.some(r=>!Array.isArray(r)||r.length!==columns.length||!r.every(finite)))
  fail('kinematics row shape or numeric values');
 checkTimes(rows.map(r=>r[0]));
 if(kin.timeTolerance!==undefined&&(!finite(kin.timeTolerance)||kin.timeTolerance<=0))
  fail('invalid kinematics time tolerance');
 return types;
}

export function validateMotion(value){
 if(!object(value)||!['kinelab.motion.v1','kinelab.motion.v2'].includes(value.schema))fail('unsupported schema');
 if(value.units!=='m'||value.coordinateSystem!=='opensim_y_up')fail('expected OpenSim Y-up meters');
 if(!finite(value.fps)||value.fps<=0)fail('fps must be finite and positive');
 const {markers,bones,frames}=value;
 if(!Array.isArray(markers)||!markers.length||
  markers.some(n=>typeof n!=='string'||!n.trim()||n!==n.trim())||new Set(markers).size!==markers.length)
  fail('markers must be unique nonempty names');
 if(!Array.isArray(frames)||!frames.length)fail('no frames');
 for(const f of frames){
  if(!object(f)||!Array.isArray(f.xyz)||f.xyz.length!==markers.length)fail('frame marker count');
  for(const p of f.xyz)if(p!==null&&(!Array.isArray(p)||p.length!==3||!p.every(finite)))fail('marker must be a finite triple or null');
 }
 const times=frames.map(f=>f.t);
 checkTimes(times);
 if(!Array.isArray(bones))fail('bones must be index pairs');
 const seen=new Set();
 for(const pair of bones){
  if(!Array.isArray(pair)||pair.length!==2||
   pair.some(i=>!Number.isInteger(i)||i<0||i>=markers.length)||pair[0]===pair[1])fail('invalid bone reference');
  const key=[...pair].sort((a,b)=>a-b).join(',');
  if(seen.has(key))fail('duplicate bone');
  seen.add(key);
 }
 let kinematics=value.kinematics??null;
 if(kinematics!==null){
  const columnTypes=validateKinematics(kinematics),ktimes=kinematics.rows.map(r=>r[0]);
  const tolerance=minInterval(times,1/value.fps);
  if(Math.abs(ktimes[0]-times[0])>tolerance+1e-9||
   Math.abs(ktimes.at(-1)-times.at(-1))>tolerance+1e-9||
   times.some(t=>Math.abs(ktimes[nearestIndex(ktimes,t)]-t)>tolerance+1e-9))
   fail('MOT time range/gaps have no nearby TRC match');
  const columnUnits=Object.fromEntries(kinematics.columns.slice(1).map(name=>[name,coordinateUnit(name,kinematics.inDegrees)]));
  kinematics={...kinematics,columnTypes,columnUnits,timeTolerance:Math.min(tolerance,kinematics.timeTolerance??tolerance)};
 }
 if(value.schema==='kinelab.motion.v2'){
  if(typeof value.sessionId!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(value.sessionId))fail('invalid sessionId');
  if(!['real','demo'].includes(value.kind))fail('invalid session kind');
  if(!object(value.time)||value.time.unit!=='s'||value.time.origin!=='synchronized_trial_start')fail('invalid time declaration');
  const p=value.provenance;
  if(!object(p)||!['runManifestSha256','trcSha256','calibrationSha256'].every(k=>hash(p[k])))
   fail('missing or invalid provenance hashes');
  if(kinematics!==null?!hash(p.motSha256):p.motSha256!==null)fail('MOT hash disagrees with kinematics');
  const mode=kinematics===null?'marker-only':'kinematics';
  if(!object(value.quality)||value.quality.status!=='passed'||value.quality.mode!==mode)fail('missing passed stage quality/mode');
 }
 return {...value,kinematics};
}

// Hold the last observed sample, clamped at both ends. Never invent missing markers.
export function frameAtTime(motion,seconds){
 if(!finite(seconds))fail('playback time must be finite');
 return motion.frames[floorIndex(motion.frames.map(f=>f.t),seconds)];
}

export function angleDegrees(kinematics,columnName,seconds){
 if(!kinematics||!finite(seconds)||coordinateType(columnName)!=='angular')return null;
 const index=kinematics.columns.indexOf(columnName);
 if(index<1)return null;
 const times=kinematics.rows.map(row=>row[0]),rowIndex=nearestIndex(times,seconds);
 const tolerance=kinematics.timeTolerance??minInterval(times,0);
 if(Math.abs(times[rowIndex]-seconds)>tolerance+1e-9)return null;
 const value=kinematics.rows[rowIndex][index];
 return finite(value)?value*(coordinateUnit(columnName,kinematics.inDegrees)==='deg'?1:180/Math.PI):null;
}
