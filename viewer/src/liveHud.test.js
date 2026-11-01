import {after, before, test} from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {computePoseKinematics} from './liveKinematics.js';

let vite, HUD;
before(async () => {
  vite = await createServer({root: fileURLToPath(new URL('..', import.meta.url)),
    server: {middlewareMode: true, hmr: false, ws: false}, optimizeDeps: {noDiscovery: true, include: []}, appType: 'custom'});
  HUD = (await vite.ssrLoadModule('/src/LiveHUDOverlay.jsx')).default;
});
after(async () => { await vite?.close(); });

const sample = (left, right = left) => ({leftKneeFlexion: left, rightKneeFlexion: right,
  trunkLean: 0, ankleHeightDifference: 0});
const render = (kinematics, options = {}) => renderToStaticMarkup(React.createElement(HUD, {
  landmarks: [{x: 0.5, y: 0.1, visibility: 1}], kinematics,
  ...options, trackerState: {exerciseType: 'squats', targetROM: 80, phase: 'BOTTOM_HOLD',
    lastCoachingMessage: 'Target reached', currentFaults: ['EXCESSIVE_TRUNK_LEAN'], ...options.trackerState},
}));
const metric = html => html.match(/<output\b[^>]*aria-label="Current exercise metric"[^>]*>([^<]*)<\/output>/)?.[1];

test('head-only geometry is unavailable and cannot show stale coaching or phase', () => {
  const html = render(computePoseKinematics([{x: 0.5, y: 0.1, visibility: 1}]));
  assert.equal(metric(html), 'UNAVAILABLE');
  assert.doesNotMatch(html, /Target reached|EXCESSIVE TRUNK_LEAN|BOTTOM HOLD/);
  assert.match(html, /Exercise geometry UNAVAILABLE/);
});

test('squat rejects absent, nonfinite, out-of-range, and nonnumeric required knee angles', () => {
  for (const missing of [null, undefined, NaN, Infinity, -Infinity, '0', -1, 181]) {
    assert.equal(metric(render(sample(missing, 80))), 'UNAVAILABLE', String(missing));
    assert.equal(metric(render({...sample(80), rightKneeFlexion: missing})), 'UNAVAILABLE', String(missing));
  }
  assert.equal(metric(render(null)), 'UNAVAILABLE');
});

test('finite zero remains zero and squat metric uses both knees', () => {
  assert.equal(metric(render(sample(0))), '0°');
  assert.equal(metric(render(sample(20, 80))), '50°');
});

test('lunge uses only the selected side and never substitutes the opposite knee', () => {
  for (const [activeSide, expected] of [['left', '20°'], ['right', '80°']]) {
    assert.equal(metric(render(sample(20, 80), {activeSide, trackerState: {exerciseType: 'lunges'}})), expected);
  }
  assert.equal(metric(render(sample(null, 80), {activeSide: 'right', trackerState: {exerciseType: 'lunges'}})), '80°');
  assert.equal(metric(render(sample(null, 80), {activeSide: 'left', trackerState: {exerciseType: 'lunges'}})), 'UNAVAILABLE');
});

test('knee extension reports excursion from 90 degrees on the selected side', () => {
  for (const [activeSide, expected] of [['left', '70°'], ['right', '10°']]) {
    assert.equal(metric(render(sample(20, 80), {activeSide, trackerState: {exerciseType: 'knee-extension'}})), expected);
  }
  assert.equal(metric(render(sample(90, null), {activeSide: 'left', trackerState: {exerciseType: 'knee-extension'}})), '0°');
  assert.equal(metric(render(sample(10, null), {activeSide: 'right', trackerState: {exerciseType: 'knee-extension'}})), 'UNAVAILABLE');
});

test('balance displays seconds only when its knee and ankle geometry and hold are finite', () => {
  const options = {trackerState: {exerciseType: 'balance', targetROM: 30, balanceHoldSeconds: 4}};
  assert.equal(metric(render(sample(10, 60), options)), '4s');
  assert.equal(metric(render({...sample(10, 60), ankleHeightDifference: null}, options)), 'UNAVAILABLE');
  assert.equal(metric(render(sample(null, 60), options)), 'UNAVAILABLE');
  for (const balanceHoldSeconds of [null, undefined, NaN, Infinity]) {
    assert.equal(metric(render(sample(10, 60), {trackerState: {...options.trackerState, balanceHoldSeconds}})), 'UNAVAILABLE');
  }
  assert.equal(metric(render(sample(10, 60), {trackerState: {...options.trackerState, balanceHoldSeconds: 0}})), '0s');
});
