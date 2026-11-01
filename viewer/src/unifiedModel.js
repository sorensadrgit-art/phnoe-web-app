/** KineLab unified workspace view and rendering contracts (pure, testable). */
import { EXERCISE_TYPES, DEFAULT_PRESETS } from './exerciseStateMachine.js';
import { computeExerciseMetric, isKneeAngle, isTargetZoneReached } from './liveDisplayHelper.js';
export { EXERCISE_TYPES, DEFAULT_PRESETS, computeExerciseMetric, isKneeAngle, isTargetZoneReached };

export const NAV_ITEMS=[
 {id:'overview',label:'Overview',icon:'◈',description:'Workspace and current session'},
 {id:'live',label:'Live Tracker',icon:'⚡',description:'Real-time biofeedback and form coach'},
 {id:'sessions',label:'Sessions',icon:'▦',description:'Manage local captures'},
 {id:'capture',label:'Capture',icon:'◉',description:'Phone and webcam footage'},
 {id:'processing',label:'Process',icon:'◎',description:'Native stage gates'},
 {id:'motion',label:'3D Motion',icon:'◇',description:'Synchronized skeleton viewer'},
 {id:'analysis',label:'Analysis',icon:'⌁',description:'Gait and squat experiments'},
 {id:'reports',label:'Reports',icon:'▤',description:'Local evidence and exports'},
 {id:'diagnostics',label:'Diagnostics',icon:'⚙',description:'Safety, locks and software'},
];
export const STAGES=[
 {id:'normalize',label:'01 / Normalize',description:'Validate and normalize six original recordings'},
 {id:'calibrate_pose',label:'02 / Calibrate + 2D pose',description:'Native camera calibration and 2D pose estimation'},
 {id:'reconstruct',label:'03 / Reconstruct 3D',description:'Independent sync, association, triangulation and filtering'},
 {id:'export_markers',label:'04 / Export marker-only',description:'Only pass-through of verified run-bound artifacts'},
];

/**
 * Pure, ordinal-free semantic status badge resolver.
 * Distinguishes SYNTHETIC, UNAVAILABLE, UNVERIFIED, DRAFT, REGISTERED.
 * Safety priority:
 * 1. Missing or unavailable session -> UNAVAILABLE
 * 2. Synthetic kind or flag -> SYNTHETIC
 * 3. Live or explicitly unverified source -> UNVERIFIED (overrides forged status)
 * 4. Test-only kind or status -> TEST ONLY
 * 5. Registered status -> REGISTERED
 * 6. Draft status -> DRAFT
 * 7. Non-empty string status -> upper-cased status
 * 8. Fallback -> UNAVAILABLE
 */
export function sessionDisplayBadge(session){
 if(!session||typeof session!=='object')return 'UNAVAILABLE';
 if(session.status==='unavailable'||session.available===false||session.data_available===false){
  return 'UNAVAILABLE';
 }
 if(
  session.kind==='synthetic'||
  session.is_synthetic===true||
  session.synthetic===true||
  session.kind==='synthetic-exercise'
 ){
  return 'SYNTHETIC';
 }
 if(
  session.kind==='live'||
  session.evidence_status==='unverified'||
  session.status==='unverified'||
  session.unverified===true
 ){
  return 'UNVERIFIED';
 }
 if(session.kind==='test-only'||session.status==='test-only'){
  return 'TEST ONLY';
 }
 if(session.status==='registered'){
  return 'REGISTERED';
 }
 if(session.status==='draft'){
  return 'DRAFT';
 }
 if(session.status&&typeof session.status==='string'&&session.status!=='unknown'){
  return session.status.toUpperCase();
 }
 if(session.status==='unknown'&&session.kind==='unknown'){
  return 'UNKNOWN';
 }
 return 'UNAVAILABLE';
}

/**
 * Pure helper for active session comparison.
 * Safely compares session objects ({ id, session_id }) or string session IDs.
 */
export function isSessionActive(session, selectedId){
 if(!session||!selectedId)return false;
 const sId=typeof session==='string'
  ? session.trim()
  : (typeof session?.id==='string'
    ? session.id.trim()
    : (typeof session?.session_id==='string'?session.session_id.trim():''));
 const targetId=typeof selectedId==='string'
  ? selectedId.trim()
  : (typeof selectedId?.id==='string'
    ? selectedId.id.trim()
    : (typeof selectedId?.session_id==='string'?selectedId.session_id.trim():''));
 if(!sId||!targetId)return false;
 return sId===targetId;
}

/**
 * Evaluates a metric measurement safely.
 * Non-finite, missing, NaN, or non-numeric values strictly evaluate to null (UNAVAILABLE).
 * Never fabricates 0 or fallback defaults for missing data.
 * If valid, returns formatted string (with optional decimals and unit).
 */
export function safeMetricValue(value, options = {}){
 if(typeof value!=='number'||!Number.isFinite(value))return null;
 const decimals=typeof options?.decimals==='number'?options.decimals:undefined;
 let formatted=decimals!==undefined?value.toFixed(decimals):String(value);
 if(options?.unit){
  formatted=`${formatted}${options.unit}`;
 }
 return formatted;
}

/**
 * Formats an exercise metric with its protocol unit ('°' for joint angles, 's' for balance hold).
 * Non-finite, missing, NaN, or non-numeric values strictly evaluate to null (never fabricates defaults or 0°).
 * Legitimate 0 measurements are preserved.
 */
export function formatExerciseMetric(metric, exerciseType, options = {}){
 if(typeof metric!=='number'||!Number.isFinite(metric))return null;
 if(!Object.values(EXERCISE_TYPES).includes(exerciseType))return null;
 const isBalance=exerciseType===EXERCISE_TYPES.BALANCE;
 const unit=options?.unit!==undefined?options.unit:(isBalance?'s':'°');
 const decimals=typeof options?.decimals==='number'?options.decimals:(isBalance?1:0);
 return safeMetricValue(metric, { decimals, unit });
}

export function formatSession(info){
 const badge=sessionDisplayBadge(info);
 const kind=info?.kind??'unknown';
 const status=info?.status??'unknown';
 const unverified=badge==='UNVERIFIED'||kind==='live'||info?.evidence_status==='unverified';
 return {
  badge,
  count:String(Number(info?.captured_roles??0))+' / 6',
  actionAvailable:!unverified&&kind==='real'&&status==='draft'&&info?.can_register===true,
  clinicallyValidated:false,
 };
}

export function roleStatus(role){
 return role?.file_present
  ? {label:'File present',tone:'present'}
  : {label:'Missing',tone:'missing'};
}
export function apiSessionPath(sessionId){
 if(typeof sessionId!=='string'||!sessionId.trim())throw Error('Session ID required');
 return '/api/v1/sessions/'+encodeURIComponent(sessionId);
}
export function readAccessToken(fragment, storage = globalThis?.localStorage){
 const text=typeof fragment==='string'?fragment:'';
 const match=text.match(/(?:^#|&)access=([a-f0-9]{64})(?:&|$)/);
 if (match) {
  try {
   storage?.setItem?.('kinelab_t6_token', match[1]);
   globalThis?.sessionStorage?.setItem?.('kinelab_t6_token', match[1]);
  } catch {}
  return match[1];
 }
 try {
  const cached = storage?.getItem?.('kinelab_t6_token')
              || globalThis?.sessionStorage?.getItem?.('kinelab_t6_token');
  if (cached && /^[a-f0-9]{64}$/.test(cached)) return cached;
 } catch {}
 return null;
}
export function tabFromHash(fragment){
 const match=String(fragment??'').match(/(?:^#|&)view=([a-z-]+)(?:&|$)/);
 return NAV_ITEMS.some(item=>item.id===match?.[1])?match[1]:'overview';
}

export const PASSPORT_GATES = [
 { id: 'EMPTY', label: 'Initialized', desc: 'Session folder ready' },
 { id: 'DRAFT', label: 'Capture in Progress', desc: 'Capturing six camera roles' },
 { id: 'SIX_FILES_PROBED', label: 'Six Files Probed', desc: 'Valid formats and geometry' },
 { id: 'REGISTERED_ORIGINALS', label: 'Hashes Registered', desc: 'Immutable source manifest' },
 { id: 'NORMALIZATION_PASSED', label: 'Normalized', desc: 'Verified 30fps CFR alignment' },
 { id: 'CALIBRATION_PASSED', label: 'Calibrated', desc: 'Extrinsics & reprojection error' },
 { id: 'SYNC_PASSED', label: 'Synchronized', desc: 'Dual visual sync cues verified' },
 { id: '3D_PASSED', label: '3D Triangulation', desc: 'Filtered TRC marker trajectories' },
 { id: 'KINEMATICS_PASSED', label: 'Kinematics', desc: 'OpenSim IK model joint angles' },
 { id: 'RESEARCH_REPORTABLE', label: 'Research Reportable', desc: 'Full verified evidence packet' },
];

export function gateIndex(state){
 return PASSPORT_GATES.findIndex(g=>g.id===state);
}

export function isGatePassed(currentState, targetGateId){
 const curIdx = gateIndex(currentState);
 const tgtIdx = gateIndex(targetGateId);
 if(curIdx === -1 || tgtIdx === -1) return false;
 return curIdx >= tgtIdx;
}

export function shortHash(hash){
 if(typeof hash !== 'string') return '';
 if(hash.length <= 16) return hash;
 return hash.slice(0, 12) + '...';
}

export function formatBytes(bytes){
 if(typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes < 0) return '0 B';
 if(bytes < 1024) return bytes + ' B';
 if(bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
 return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/**
 * Formats a truthful stale notice indicating when data was last updated.
 * If lastRefreshedMs is missing, non-finite, or <= 0, returns 'STALE · Update time unavailable'.
 * Legitimate timestamps calculate elapsed seconds bounded to >= 0s.
 */
export function formatStaleNotice(lastRefreshedMs, nowMs){
 if(typeof lastRefreshedMs !== 'number' || !Number.isFinite(lastRefreshedMs) || lastRefreshedMs <= 0){
  return 'STALE · Update time unavailable';
 }
 const current = typeof nowMs === 'number' && Number.isFinite(nowMs) ? nowMs : Date.now();
 const elapsedSec = Math.max(0, Math.round((current - lastRefreshedMs) / 1000));
 return `STALE · Last updated ${elapsedSec}s ago`;
}

/**
 * Pure helper determining whether data exceeds a staleness threshold.
 * Missing or invalid timestamps fail closed to true (stale).
 * Default threshold is 15000ms (15 seconds).
 */
export function isStale(lastRefreshedMs, thresholdMs = 15000, nowMs){
 if(typeof lastRefreshedMs !== 'number' || !Number.isFinite(lastRefreshedMs) || lastRefreshedMs <= 0){
  return true;
 }
 const threshold = typeof thresholdMs === 'number' && Number.isFinite(thresholdMs) ? thresholdMs : 15000;
 const current = typeof nowMs === 'number' && Number.isFinite(nowMs) ? nowMs : Date.now();
 return (current - lastRefreshedMs) > threshold;
}
