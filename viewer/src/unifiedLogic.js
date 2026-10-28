export const appIdentity={
  name:'KineLab PT',
  version:'T6 unified preview',
  releaseStatus:'PRE-RELEASE / LOCAL SOFTWARE PROTOTYPE',
  validation:'REAL 3D PHYSICAL ACCURACY UNVERIFIED',
};
export const NAV_ITEMS=[
  {id:'overview',label:'Overview',icon:'▦',description:'Application and pipeline status'},
  {id:'sessions',label:'Session library',icon:'▤',description:'Capture inventory and session management'},
  {id:'capture',label:'Capture studio',icon:'◎',description:'Phone and webcam recordings'},
  {id:'process',label:'Processing',icon:'⌁',description:'Calibration, synchronization and 3D gates'},
  {id:'motion',label:'Motion lab',icon:'◇',description:'3D skeleton, video and time plots'},
  {id:'analysis',label:'Analysis',icon:'◫',description:'Test-only gait and squat tools'},
  {id:'reports',label:'Reports',icon:'▥',description:'Local manifest exports and guides'},
  {id:'diagnostics',label:'Diagnostics',icon:'⚙',description:'Local service and recovery'},
];
export const VIDEO_ROLES=[
 'cam01_intrinsics','cam02_intrinsics','cam01_board','cam02_board','cam01_trial','cam02_trial',
];
export function roleDevice(name){
 if(!VIDEO_ROLES.includes(name))throw new Error('Unknown camera role');
 return name.startsWith('cam01_')?'phone':'webcam';
}
export function canEdit(record){
 return !!record&&record.kind==='real'&&record.status==='draft'&&record.can_register===true;
}
export function phaseStatus(record){
 const a=record?.artifacts||{};
 const has=(flag)=>!!a[flag];
 return {
  captured:{state:(record?.captured_roles??0)>0?'present':'pending',label:'Source clips: presence only'},
  registered:{state:has('registration')?'recorded':'pending',label:'Source SHA-256 identity'},
  normalized:{state:has('normalization')?'recorded':'pending',label:'Video normalization'},
  calibration:{state:'unverified',label:'Measured camera residuals require native quality review'},
  synchronization:{state:has('observed_cues')?'operator-observed':'pending',label:'Native timing verification is separate'},
  native_3d:{state:'unverified',label:'Complete accepted 3D run not certified by file existence'},
  clinical_accuracy:{state:'unverified',label:'Independent physical reference study not completed'},
 };
}
