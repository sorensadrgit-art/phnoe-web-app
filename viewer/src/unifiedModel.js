/** KineLab unified workspace view and rendering contracts (pure, testable). */
export const NAV_ITEMS=[
 {id:'overview',label:'Overview',description:'Workspace and current session'},
 {id:'sessions',label:'Sessions',description:'Manage local captures'},
 {id:'capture',label:'Capture',description:'Phone and webcam footage'},
 {id:'processing',label:'Process',description:'Native stage gates'},
 {id:'motion',label:'3D Motion',description:'Synchronized skeleton viewer'},
 {id:'analysis',label:'Analysis',description:'Gait and squat experiments'},
 {id:'reports',label:'Reports',description:'Local evidence and exports'},
 {id:'diagnostics',label:'Diagnostics',description:'Safety, locks and software'},
];
export const STAGES=[
 {id:'normalize',label:'01 / Normalize',description:'Validate and normalize six original recordings'},
 {id:'calibrate_pose',label:'02 / Calibrate + 2D pose',description:'Native camera calibration and 2D pose estimation'},
 {id:'reconstruct',label:'03 / Reconstruct 3D',description:'Independent sync, association, triangulation and filtering'},
 {id:'export_markers',label:'04 / Export marker-only',description:'Only pass-through of verified run-bound artifacts'},
];
export function formatSession(info){
 const kind=info?.kind??'unknown',status=info?.status??'unknown';
 const badge=kind==='test-only'?'TEST ONLY':
   status==='registered'?'REGISTERED':
   status==='draft'?'DRAFT':status.toUpperCase();
 return {
  badge,
  count:String(Number(info?.captured_roles??0))+' / 6',
  actionAvailable:kind==='real'&&status==='draft'&&info?.can_register===true,
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
export function readAccessToken(fragment){
 const text=typeof fragment==='string'?fragment:'';
 const match=text.match(/(?:^#|&)access=([a-f0-9]{64})(?:&|$)/);
 return match?match[1]:null;
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
