import test from 'node:test';
import assert from 'node:assert/strict';
import {NAV_ITEMS,formatSession,roleStatus,apiSessionPath,
        readAccessToken,STAGES,tabFromHash,PASSPORT_GATES,
        gateIndex,isGatePassed,shortHash,formatBytes} from './unifiedModel.js';

test('T6 navigation covers capture, sessions, process, motion, analysis, reports and diagnostics',()=>{
 assert.deepEqual(NAV_ITEMS.map(x=>x.id),
  ['overview','sessions','capture','processing','motion','analysis','reports','diagnostics']);
 assert.ok(NAV_ITEMS.every(x=>x.label&&x.description));
 assert.deepEqual(STAGES.map(s=>s.id),
  ['normalize','calibrate_pose','reconstruct','export_markers']);
});
test('test-only sessions never display registration as available',()=>{
 const session={id:'caliscope-walking-test-20261027',kind:'test-only',
  status:'test-only',captured_roles:6,can_register:false};
 const row=formatSession(session);
 assert.equal(row.badge,'TEST ONLY');
 assert.equal(row.actionAvailable,false);
 assert.equal(row.count,'6 / 6');
});
test('incomplete real captures are drafts, not clinically accepted',()=>{
 const session={id:'capture-a',kind:'real',status:'draft',
  captured_roles:2,can_register:true};
 const item=formatSession(session);
 assert.equal(item.badge,'DRAFT');
 assert.equal(item.count,'2 / 6');
 assert.equal(item.clinicallyValidated,false);
 assert.equal(roleStatus({file_present:false}).label,'Missing');
 assert.equal(roleStatus({file_present:true}).label,'File present');
});
test('safe session path encoding avoids URL route injection',()=>{
 assert.equal(apiSessionPath('trial a'),'/api/v1/sessions/trial%20a');
 assert.equal(apiSessionPath('hello#world'),'/api/v1/sessions/hello%23world');
 assert.throws(()=>apiSessionPath(''));
 assert.throws(()=>apiSessionPath(null));
});
test('fragment access token is only read from URL hash, not query string',()=>{
 assert.equal(readAccessToken('#access='+'c'.repeat(64)),'c'.repeat(64));
 assert.equal(readAccessToken('#access=bad'),null);
 assert.equal(readAccessToken('#view=motion'),null);
 assert.equal(tabFromHash('#view=motion'),'motion');
 assert.equal(tabFromHash('#view=untrusted'),'overview');

 const store = new Map();
 const mockStorage = { setItem: (k, v) => store.set(k, v), getItem: (k) => store.get(k) || null };
 assert.equal(readAccessToken('#access=' + 'd'.repeat(64), mockStorage), 'd'.repeat(64));
 assert.equal(mockStorage.getItem('kinelab_t6_token'), 'd'.repeat(64));
 // When hash lacks token, token is restored from storage
 assert.equal(readAccessToken('#view=motion', mockStorage), 'd'.repeat(64));
});
test('passport gates progression and gate checks',()=>{
 assert.equal(PASSPORT_GATES.length, 10);
 assert.equal(PASSPORT_GATES[0].id, 'EMPTY');
 assert.equal(PASSPORT_GATES[9].id, 'RESEARCH_REPORTABLE');
 assert.equal(gateIndex('EMPTY'), 0);
 assert.equal(gateIndex('CALIBRATION_PASSED'), 5);
 assert.equal(gateIndex('UNKNOWN_STATE'), -1);
 assert.equal(isGatePassed('CALIBRATION_PASSED', 'EMPTY'), true);
 assert.equal(isGatePassed('CALIBRATION_PASSED', 'CALIBRATION_PASSED'), true);
 assert.equal(isGatePassed('CALIBRATION_PASSED', '3D_PASSED'), false);
});
test('formatting utilities for bytes and hashes',()=>{
 assert.equal(shortHash('5ebefc8748e5d93fadfe07497c8f27913f8a9fd3e42f17fbcff8e850008b45f7'), '5ebefc8748e5...');
 assert.equal(shortHash('short'), 'short');
 assert.equal(formatBytes(1048576), '1.0 MB');
 assert.equal(formatBytes(2048), '2.0 KB');
 assert.equal(formatBytes(500), '500 B');
});

