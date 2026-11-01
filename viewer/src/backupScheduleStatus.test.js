import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {transformSync} from 'esbuild';

const require = createRequire(import.meta.url);
const module = {exports: {}};
const code = transformSync(fs.readFileSync(new URL('./BackupScheduleStatus.jsx', import.meta.url), 'utf8'), {loader: 'jsx', format: 'cjs'}).code;
new Function('require', 'module', 'exports', code)(require, module, module.exports);
const {default: BackupScheduleStatus, parseBackupScheduleStatus} = module.exports;
const base = () => ({
  schema: 'kinelab.backup-schedule-status.v1', enabled: false, state: 'DISABLED', policy_status: 'OPEN',
  next_due_at_utc: null, engine_mode: 'UNCONFIGURED', last_job: null, history: [], missed_count: 0,
  last_verified_archive: null, last_verified_recovery_point: null,
  pruning: {enabled: false, reason: 'POLICY_NOT_APPROVED'}, service_alive_only: true, journal_capacity: 4096,
  journal_health: 'VALIDATED', historical_prefix_only: false, engine_health: 'IDLE',
  clock_health: null, pump_health: null, pump_status: 'NOT_ATTACHED',
});
const historical = () => ({archive: 'scheduled-' + 'a'.repeat(32) + '.zip', generation_id: 'b'.repeat(32),
  sha256: 'c'.repeat(64), bytes: 128, verified_at: 100, verification_kind: 'CREATED_AND_MEMBER_HASH_VERIFIED'});
const render = value => renderToStaticMarkup(React.createElement(BackupScheduleStatus, {schedule: value}));
// Actual JSX/React server rendering, not mounted hooks, browser or network proof.
test('R18 UI idle default retains disabled policy and unavailable recovery', () => {
  const html = render(base()); assert.match(html, /Scheduling is disabled/); assert.match(html, /UNAVAILABLE/); assert.doesNotMatch(html, /role="alert"/);
});
test('R18 UI torn history warns despite historical verified archive', () => {
  const html = render({...base(), journal_health: 'RECOVERY_REQUIRED', historical_prefix_only: true, engine_health: 'REVIEW_REQUIRED', last_verified_archive: historical()});
  assert.match(html, /RECOVERY_REQUIRED/); assert.match(html, /Historical prefix only/); assert.match(html, /historical archive/); assert.match(html, /role="alert"/);
});
test('R18 UI unrecorded pump health failure warns despite historical archive', () => {
  const html = render({...base(), pump_status: 'HEALTH_UNRECORDED', engine_health: 'REVIEW_REQUIRED', last_verified_archive: historical()});
  assert.match(html, /HEALTH_UNRECORDED/); assert.match(html, /health journal could not be written/); assert.match(html, /historical archive/);
});
test('R18 UI durable pump failure and clock rollback remain visible', () => {
  const html = render({...base(), engine_health: 'REVIEW_REQUIRED', pump_health: {reason: 'TICK_FAILED', observed_utc: 90}, clock_health: {observed_utc: 80, reference_utc: 90}});
  assert.match(html, /TICK_FAILED/); assert.match(html, /CLOCK_UNCERTAIN/);
});
test('R18 UI refuses missing or contradictory health rather than favorable display', () => {
  const missing = base(); delete missing.pump_status; assert.throws(() => render(missing));
  assert.throws(() => render({...base(), pump_status: 'TICK_FAILED'}));
  assert.throws(() => render({...base(), journal_health: 'RECOVERY_REQUIRED'}));
});
test('R18 UI refuses numeric archive identities and nonfinite observations', () => {
  assert.throws(() => render({...base(), last_verified_archive: {...historical(), generation_id: 11111111111111111111111111111111}}));
  assert.throws(() => render({...base(), last_verified_archive: {...historical(), bytes: Infinity}}));
  assert.throws(() => render({...base(), clock_health: {observed_utc: NaN, reference_utc: 90}, engine_health: 'REVIEW_REQUIRED'}));
});
test('R18 UI rejects unknown reason or path strings before React rendering', () => {
  const job = {operation_id: 'a'.repeat(32), archive: 'scheduled-' + 'a'.repeat(32) + '.zip', due: 100, at: 100, status: 'FAILED', reason: 'TEST_ONLY-private-path'};
  assert.throws(() => render({...base(), history: [job], last_job: job}));
});
test('R18 ReportStudio delegates checking and actual UI health rendering', () => {
  const source = fs.readFileSync(new URL('./ReportStudio.jsx', import.meta.url), 'utf8');
  assert.match(source, /const checked = parseBackupScheduleStatus\(value\)/);
  assert.match(source, /<BackupScheduleStatus schedule=\{schedule\}/);
  assert.equal(parseBackupScheduleStatus(base()).enabled, false);
});
