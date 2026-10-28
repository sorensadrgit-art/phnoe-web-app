import test from 'node:test';
import assert from 'node:assert/strict';
import {NAV_ITEMS,phaseStatus,canEdit,roleDevice,appIdentity} from './unifiedLogic.js';

test('single integrated shell has all six actual workflow sections',()=>{
 assert.deepEqual(NAV_ITEMS.map(x=>x.id),[
  'overview','sessions','capture','process','motion','analysis','reports','diagnostics',
 ]);
 assert.equal(new Set(NAV_ITEMS.map(x=>x.id)).size,NAV_ITEMS.length);
 assert.ok(NAV_ITEMS.every(x=>x.label&&x.icon));
});

test('test-only/registered/legacy session may not alter raw capture inputs',()=>{
 for(const record of [
  {kind:'test-only',status:'test-only',can_register:false},
  {kind:'demo',status:'draft',can_register:false},
  {kind:'real',status:'registered',can_register:false},
  {kind:'legacy',status:'legacy',can_register:false},
  null,
 ])assert.equal(canEdit(record),false);
 assert.equal(canEdit({kind:'real',status:'draft',can_register:true}),true);
});

test('roles are mapped exactly to physical phone/webcam and no unknown roles',()=>{
 for(const name of ['cam01_intrinsics','cam01_board','cam01_trial'])
  assert.equal(roleDevice(name),'phone');
 for(const name of ['cam02_intrinsics','cam02_board','cam02_trial'])
  assert.equal(roleDevice(name),'webcam');
 assert.throws(()=>roleDevice('cam03_trial'));
 assert.throws(()=>roleDevice('../../cam01_trial'));
});

test('raw file presence is not presented as successful native processing',()=>{
 const detail={kind:'real',status:'draft',captured_roles:6,
  artifacts:{registration:false,preflight:false,normalization:false,
    observed_cues:false,native_sync:false,native_run:false}};
 const info=phaseStatus(detail);
 assert.equal(info['captured'].state,'present');
 assert.equal(info['registered'].state,'pending');
 assert.equal(info['calibration'].state,'unverified');
 assert.equal(info['native_3d'].state,'unverified');
 assert.equal(info['clinical_accuracy'].state,'unverified');
 detail.artifacts.native_run=true;
 assert.equal(phaseStatus(detail)['native_3d'].state,'unverified');
});

test('T6 app identity never claims clinical software release',()=>{
 assert.ok(appIdentity.releaseStatus.includes('PRE-RELEASE'));
 assert.ok(appIdentity.validation.includes('UNVERIFIED'));
});
