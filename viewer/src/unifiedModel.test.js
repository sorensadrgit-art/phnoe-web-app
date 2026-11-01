import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {NAV_ITEMS,formatSession,roleStatus,apiSessionPath,
        readAccessToken,STAGES,tabFromHash,PASSPORT_GATES,
        gateIndex,isGatePassed,shortHash,formatBytes,
        sessionDisplayBadge,isSessionActive,safeMetricValue,
        EXERCISE_TYPES,DEFAULT_PRESETS,computeExerciseMetric,
        isKneeAngle,isTargetZoneReached,formatExerciseMetric,
        formatStaleNotice,isStale} from './unifiedModel.js';

test('T6 navigation covers live, capture, sessions, process, motion, analysis, reports and diagnostics',()=>{
 assert.deepEqual(NAV_ITEMS.map(x=>x.id),
  ['overview','live','sessions','capture','processing','motion','analysis','reports','diagnostics']);
 assert.ok(NAV_ITEMS.every(x=>x.label&&x.description));
 assert.deepEqual(STAGES.map(s=>s.id),
  ['normalize','calibrate_pose','reconstruct','export_markers']);
});

test('live sessions display UNVERIFIED badge and registration disabled',()=>{
 const session={id:'live-squat-01',kind:'live',status:'completed',captured_roles:0,can_register:false};
 const row=formatSession(session);
 assert.equal(row.badge,'UNVERIFIED');
 assert.equal(row.actionAvailable,false);
});

test('unverified source overrides a forged registered or draft label',()=>{
 for(const status of ['registered','draft']){
  const row=formatSession({kind:'real',status,evidence_status:'unverified',can_register:true});
  assert.equal(row.badge,'UNVERIFIED');
  assert.equal(row.actionAvailable,false);
 }
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

test('sessionDisplayBadge performs ordinal-free status badge determination',()=>{
 // Distinguishes UNAVAILABLE
 assert.equal(sessionDisplayBadge(null), 'UNAVAILABLE');
 assert.equal(sessionDisplayBadge(undefined), 'UNAVAILABLE');
 assert.equal(sessionDisplayBadge({ status: 'unavailable' }), 'UNAVAILABLE');
 assert.equal(sessionDisplayBadge({ available: false }), 'UNAVAILABLE');
 assert.equal(sessionDisplayBadge({ data_available: false }), 'UNAVAILABLE');

 // Distinguishes SYNTHETIC
 assert.equal(sessionDisplayBadge({ kind: 'synthetic' }), 'SYNTHETIC');
 assert.equal(sessionDisplayBadge({ is_synthetic: true }), 'SYNTHETIC');
 assert.equal(sessionDisplayBadge({ synthetic: true }), 'SYNTHETIC');
 assert.equal(sessionDisplayBadge({ kind: 'synthetic-exercise' }), 'SYNTHETIC');
 // Synthetic sessions cannot claim registered real evidence
 assert.equal(sessionDisplayBadge({ kind: 'synthetic', status: 'registered' }), 'SYNTHETIC');

 // Distinguishes UNVERIFIED
 assert.equal(sessionDisplayBadge({ kind: 'live' }), 'UNVERIFIED');
 assert.equal(sessionDisplayBadge({ evidence_status: 'unverified' }), 'UNVERIFIED');
 assert.equal(sessionDisplayBadge({ status: 'unverified' }), 'UNVERIFIED');
 assert.equal(sessionDisplayBadge({ unverified: true }), 'UNVERIFIED');
 // Unverified source overrides forged registered or draft status
 assert.equal(sessionDisplayBadge({ status: 'registered', evidence_status: 'unverified' }), 'UNVERIFIED');
 assert.equal(sessionDisplayBadge({ status: 'draft', kind: 'live' }), 'UNVERIFIED');

 // Distinguishes DRAFT and REGISTERED
 assert.equal(sessionDisplayBadge({ status: 'draft' }), 'DRAFT');
 assert.equal(sessionDisplayBadge({ kind: 'real', status: 'draft' }), 'DRAFT');
 assert.equal(sessionDisplayBadge({ status: 'registered' }), 'REGISTERED');
 assert.equal(sessionDisplayBadge({ kind: 'real', status: 'registered' }), 'REGISTERED');

 // Distinguishes TEST ONLY
 assert.equal(sessionDisplayBadge({ kind: 'test-only' }), 'TEST ONLY');
 assert.equal(sessionDisplayBadge({ status: 'test-only' }), 'TEST ONLY');
});

test('isSessionActive pure helper accurately compares sessions without side effects',()=>{
 assert.equal(isSessionActive({ id: 'gait-01' }, 'gait-01'), true);
 assert.equal(isSessionActive('gait-01', 'gait-01'), true);
 assert.equal(isSessionActive({ id: 'gait-01' }, { id: 'gait-01' }), true);
 assert.equal(isSessionActive({ session_id: 'gait-01' }, 'gait-01'), true);
 assert.equal(isSessionActive({ id: 'gait-01' }, { session_id: 'gait-01' }), true);

 // Non-matching or invalid inputs
 assert.equal(isSessionActive({ id: 'gait-01' }, 'gait-02'), false);
 assert.equal(isSessionActive(null, 'gait-01'), false);
 assert.equal(isSessionActive({ id: 'gait-01' }, null), false);
 assert.equal(isSessionActive('', ''), false);
 assert.equal(isSessionActive('   ', 'gait-01'), false);
 assert.equal(isSessionActive({}, 'gait-01'), false);
});

test('safeMetricValue strictly evaluates missing or non-finite measurements to null and never fabricates defaults',()=>{
 // Missing / null / undefined
 assert.equal(safeMetricValue(null), null);
 assert.equal(safeMetricValue(undefined), null);

 // Non-finite numbers
 assert.equal(safeMetricValue(NaN), null);
 assert.equal(safeMetricValue(Infinity), null);
 assert.equal(safeMetricValue(-Infinity), null);

 // Strings (including numeric strings '0', '45.2', whitespace, invalid) must strictly evaluate to null
 assert.equal(safeMetricValue(''), null);
 assert.equal(safeMetricValue('   '), null);
 assert.equal(safeMetricValue('invalid'), null);
 assert.equal(safeMetricValue('0'), null);
 assert.equal(safeMetricValue('45.2'), null);
 assert.equal(safeMetricValue('100.5'), null);

 // Non-numeric types (never coerced to 0 or 1)
 assert.equal(safeMetricValue(false), null);
 assert.equal(safeMetricValue(true), null);
 assert.equal(safeMetricValue([]), null);
 assert.equal(safeMetricValue([10]), null);
 assert.equal(safeMetricValue({}), null);

 // Valid 0 measurement (real biological or duration value, not fabricated default)
 assert.equal(safeMetricValue(0), '0');
 assert.equal(safeMetricValue(0, { decimals: 1 }), '0.0');
 assert.equal(safeMetricValue(0, { unit: '°' }), '0°');

 // Valid measurements with formatting
 assert.equal(safeMetricValue(85.4), '85.4');
 assert.equal(safeMetricValue(85.456, { decimals: 1 }), '85.5');
 assert.equal(safeMetricValue(85.456, { decimals: 2, unit: '°' }), '85.46°');
 assert.equal(safeMetricValue(-12.3, { decimals: 1, unit: ' mm' }), '-12.3 mm');
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

test('re-exported true shared contracts match expected shapes and functions',()=>{
 assert.equal(typeof EXERCISE_TYPES, 'object');
 assert.equal(EXERCISE_TYPES.SQUAT, 'squats');
 assert.equal(EXERCISE_TYPES.LUNGE, 'lunges');
 assert.equal(EXERCISE_TYPES.KNEE_EXTENSION, 'knee-extension');
 assert.equal(EXERCISE_TYPES.BALANCE, 'balance');

 assert.equal(typeof DEFAULT_PRESETS, 'object');
 assert.ok(DEFAULT_PRESETS[EXERCISE_TYPES.SQUAT]);
 assert.equal(typeof DEFAULT_PRESETS[EXERCISE_TYPES.SQUAT].targetROM, 'number');

 assert.equal(typeof computeExerciseMetric, 'function');
 assert.equal(typeof isKneeAngle, 'function');
 assert.equal(typeof isTargetZoneReached, 'function');
 assert.equal(isKneeAngle(90), true);
 assert.equal(isKneeAngle(-5), false);
 assert.equal(isKneeAngle(null), false);
});

test('N02-FMT-001 unknown exercise identity is unavailable even for a finite metric', () => {
 for (const exercise of [undefined, null, '', 'unknown', 'squat', 'BALANCE', false, {}, [], new String(EXERCISE_TYPES.SQUAT)]) {
  assert.equal(formatExerciseMetric(12, exercise), null);
  assert.equal(formatExerciseMetric(12, exercise, {decimals: 2, unit: 'TEST_ONLY'}), null);
  assert.equal(renderToStaticMarkup(React.createElement('strong', null,
   formatExerciseMetric(12, exercise) ?? 'UNAVAILABLE')), '<strong>UNAVAILABLE</strong>');
 }
});

test('N02-FMT-002 known exercise formatting retains precision options and zero', () => {
 for (const exercise of Object.values(EXERCISE_TYPES)) {
  const balance = exercise === EXERCISE_TYPES.BALANCE;
  assert.equal(formatExerciseMetric(0, exercise), balance ? '0.0s' : '0°');
  assert.equal(formatExerciseMetric(12.25, exercise, {decimals: 2}), balance ? '12.25s' : '12.25°');
  assert.equal(formatExerciseMetric(12.25, exercise, {decimals: 1, unit: 'TEST_ONLY'}), '12.3TEST_ONLY');
 }
});

test('formatExerciseMetric strictly assigns protocol units and evaluates unsupported inputs to null', () => {
 // Squat / Lunge / Knee-Extension: angles in degrees (°)
 assert.equal(formatExerciseMetric(80, EXERCISE_TYPES.SQUAT), '80°');
 assert.equal(formatExerciseMetric(75.5, EXERCISE_TYPES.KNEE_EXTENSION, { decimals: 1 }), '75.5°');
 assert.equal(formatExerciseMetric(82, EXERCISE_TYPES.LUNGE), '82°');

 // Balance: duration in seconds (s)
 assert.equal(formatExerciseMetric(30, EXERCISE_TYPES.BALANCE), '30.0s');
 assert.equal(formatExerciseMetric(12.5, EXERCISE_TYPES.BALANCE), '12.5s');

 // Preserves legitimate numeric 0
 assert.equal(formatExerciseMetric(0, EXERCISE_TYPES.SQUAT), '0°');
 assert.equal(formatExerciseMetric(0, EXERCISE_TYPES.BALANCE), '0.0s');

 // Strictly evaluates unsupported/malformed inputs to null (UNAVAILABLE)
 assert.equal(formatExerciseMetric('80', EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric('0', EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric('45.2', EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric(NaN, EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric(Infinity, EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric(null, EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric(undefined, EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric({}, EXERCISE_TYPES.SQUAT), null);
 assert.equal(formatExerciseMetric(false, EXERCISE_TYPES.SQUAT), null);
});

test('consumer component presentation renders UNAVAILABLE for unsupported inputs rather than fabricated values', () => {
 // Consumer 1: Candidate extrema count in Analysis view (UnifiedApp.jsx:536)
 function renderExtrema(count) {
  return renderToStaticMarkup(React.createElement('strong', null, (safeMetricValue(count) ?? 'UNAVAILABLE') + ' extrema'));
 }

 assert.equal(renderExtrema(12), '<strong>12 extrema</strong>');
 assert.equal(renderExtrema(0), '<strong>0 extrema</strong>');
 assert.equal(renderExtrema('12'), '<strong>UNAVAILABLE extrema</strong>');
 assert.equal(renderExtrema('0'), '<strong>UNAVAILABLE extrema</strong>');
 assert.equal(renderExtrema('45.2'), '<strong>UNAVAILABLE extrema</strong>');
 assert.equal(renderExtrema(NaN), '<strong>UNAVAILABLE extrema</strong>');
 assert.equal(renderExtrema(null), '<strong>UNAVAILABLE extrema</strong>');
 assert.equal(renderExtrema(undefined), '<strong>UNAVAILABLE extrema</strong>');
 assert.equal(renderExtrema({}), '<strong>UNAVAILABLE extrema</strong>');

 // Consumer 2: Protocol Target ROM presentation in Synthetic Module (UnifiedApp.jsx:543)
 function renderTargetROM(targetROM, exerciseType) {
  return renderToStaticMarkup(React.createElement('strong', null, formatExerciseMetric(targetROM, exerciseType) ?? 'UNAVAILABLE'));
 }

 assert.equal(renderTargetROM(DEFAULT_PRESETS[EXERCISE_TYPES.SQUAT].targetROM, EXERCISE_TYPES.SQUAT), '<strong>80°</strong>');
 assert.equal(renderTargetROM(DEFAULT_PRESETS[EXERCISE_TYPES.BALANCE].targetROM, EXERCISE_TYPES.BALANCE), '<strong>30.0s</strong>');
 assert.equal(renderTargetROM(0, EXERCISE_TYPES.SQUAT), '<strong>0°</strong>');
 assert.equal(renderTargetROM('80', EXERCISE_TYPES.SQUAT), '<strong>UNAVAILABLE</strong>');
 assert.equal(renderTargetROM('0', EXERCISE_TYPES.SQUAT), '<strong>UNAVAILABLE</strong>');
 assert.equal(renderTargetROM('45.2', EXERCISE_TYPES.SQUAT), '<strong>UNAVAILABLE</strong>');
 assert.equal(renderTargetROM(NaN, EXERCISE_TYPES.SQUAT), '<strong>UNAVAILABLE</strong>');
 assert.equal(renderTargetROM(null, EXERCISE_TYPES.SQUAT), '<strong>UNAVAILABLE</strong>');
 assert.equal(renderTargetROM({}, EXERCISE_TYPES.SQUAT), '<strong>UNAVAILABLE</strong>');

 // Consumer 3: Board measurement notification (UnifiedApp.jsx:248)
 function formatBoardEntry(valueMm) {
  const measured = safeMetricValue(valueMm) ?? 'UNAVAILABLE';
  return `Recorded physical ruler entry of ${measured} mm. This is not verified calibration.`;
 }

 assert.equal(formatBoardEntry(200), 'Recorded physical ruler entry of 200 mm. This is not verified calibration.');
 assert.equal(formatBoardEntry('200'), 'Recorded physical ruler entry of UNAVAILABLE mm. This is not verified calibration.');
 assert.equal(formatBoardEntry(null), 'Recorded physical ruler entry of UNAVAILABLE mm. This is not verified calibration.');
 assert.equal(formatBoardEntry(NaN), 'Recorded physical ruler entry of UNAVAILABLE mm. This is not verified calibration.');
 assert.equal(formatBoardEntry({}), 'Recorded physical ruler entry of UNAVAILABLE mm. This is not verified calibration.');
});

test('formatStaleNotice returns formatted notice or unavailable for missing/invalid timestamps', () => {
 // Valid timestamps with elapsed calculation
 assert.equal(formatStaleNotice(10000, 25000), 'STALE · Last updated 15s ago');
 assert.equal(formatStaleNotice(10000, 10000), 'STALE · Last updated 0s ago');
 assert.equal(formatStaleNotice(10000, 70000), 'STALE · Last updated 60s ago');

 // Bounded to >= 0s when clock skew or future timestamp
 assert.equal(formatStaleNotice(20000, 10000), 'STALE · Last updated 0s ago');

 // Invalid, non-finite, missing or non-positive timestamps strictly return 'STALE · Update time unavailable'
 assert.equal(formatStaleNotice(null, 20000), 'STALE · Update time unavailable');
 assert.equal(formatStaleNotice(undefined, 20000), 'STALE · Update time unavailable');
 assert.equal(formatStaleNotice(0, 20000), 'STALE · Update time unavailable');
 assert.equal(formatStaleNotice(-5000, 20000), 'STALE · Update time unavailable');
 assert.equal(formatStaleNotice(NaN, 20000), 'STALE · Update time unavailable');
 assert.equal(formatStaleNotice(Infinity, 20000), 'STALE · Update time unavailable');
 assert.equal(formatStaleNotice('10000', 20000), 'STALE · Update time unavailable');
 assert.equal(formatStaleNotice({}, 20000), 'STALE · Update time unavailable');

 // Default nowMs works when omitted
 const recent = Date.now() - 5000;
 assert.match(formatStaleNotice(recent), /^STALE · Last updated \d+s ago$/);
});

test('isStale pure helper accurately determines data staleness against threshold', () => {
 // Fresh data within threshold
 assert.equal(isStale(10000, 15000, 20000), false); // elapsed 10s <= 15s
 assert.equal(isStale(10000, 15000, 25000), false); // elapsed 15s <= 15s (exact boundary)

 // Stale data exceeding threshold
 assert.equal(isStale(10000, 15000, 25001), true);  // elapsed 15.001s > 15s
 assert.equal(isStale(10000, 15000, 30000), true);  // elapsed 20s > 15s

 // Custom threshold
 assert.equal(isStale(10000, 5000, 14000), false);  // elapsed 4s <= 5s
 assert.equal(isStale(10000, 5000, 16000), true);   // elapsed 6s > 5s

 // Default threshold is 15000ms
 assert.equal(isStale(10000, undefined, 20000), false);
 assert.equal(isStale(10000, undefined, 26000), true);

 // Missing, null, undefined, non-finite, or <= 0 timestamps fail closed to true (stale)
 assert.equal(isStale(null), true);
 assert.equal(isStale(undefined), true);
 assert.equal(isStale(0), true);
 assert.equal(isStale(-1000), true);
 assert.equal(isStale(NaN), true);
 assert.equal(isStale('10000'), true);
 assert.equal(isStale({}), true);

 // Future timestamp or clock drift
 assert.equal(isStale(30000, 15000, 20000), false);
});

test('truthful stale and error banner component renders active retry button and truthful notice', () => {
 function renderStaleBanner({ lastRefreshedMs, nowMs, connected, fetchError, onRetry }) {
  const isDataStale = isStale(lastRefreshedMs, 15000, nowMs);
  const shouldShow = !connected || fetchError !== null || (lastRefreshedMs !== null && isDataStale);
  if (!shouldShow) return null;
  return renderToStaticMarkup(
   React.createElement('div', { className: 'uw-stale-banner', role: 'alert' },
    React.createElement('div', { className: 'uw-stale-banner-content' },
     React.createElement('span', { className: 'uw-stale-icon', 'aria-hidden': true }, '⚠️'),
     React.createElement('div', { className: 'uw-stale-text' },
      React.createElement('strong', null, formatStaleNotice(lastRefreshedMs, nowMs)),
      React.createElement('span', { className: 'uw-stale-desc' },
       !connected ? ' — Service disconnected' : (fetchError ? ` — ${fetchError}` : ' — Data exceeds 15s threshold')
      )
     )
    ),
    React.createElement('button', {
     type: 'button',
     className: 'uw-btn uw-btn-retry',
     onClick: onRetry,
    }, 'Retry Connection')
   )
  );
 }

 // Test 1: Stale data beyond 15s threshold renders banner with elapsed time and retry button
 const htmlStale = renderStaleBanner({ lastRefreshedMs: 10000, nowMs: 30000, connected: true, fetchError: null });
 assert.ok(htmlStale.includes('uw-stale-banner'));
 assert.ok(htmlStale.includes('STALE · Last updated 20s ago'));
 assert.ok(htmlStale.includes('Retry Connection'));

 // Test 2: Fresh data within 15s does not render banner
 const htmlFresh = renderStaleBanner({ lastRefreshedMs: 20000, nowMs: 25000, connected: true, fetchError: null });
 assert.equal(htmlFresh, null);

 // Test 3: Disconnected network renders banner even without prior timestamp
 const htmlDisconnected = renderStaleBanner({ lastRefreshedMs: null, nowMs: 20000, connected: false, fetchError: null });
 assert.ok(htmlDisconnected.includes('uw-stale-banner'));
 assert.ok(htmlDisconnected.includes('STALE · Update time unavailable'));
 assert.ok(htmlDisconnected.includes('Service disconnected'));
 assert.ok(htmlDisconnected.includes('Retry Connection'));

 // Test 4: Fetch error renders banner with error message
 const htmlError = renderStaleBanner({ lastRefreshedMs: 15000, nowMs: 20000, connected: true, fetchError: 'HTTP 503 unavailable' });
 assert.ok(htmlError.includes('uw-stale-banner'));
 assert.ok(htmlError.includes('HTTP 503 unavailable'));
 assert.ok(htmlError.includes('Retry Connection'));
});

