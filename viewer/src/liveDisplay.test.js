import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformSync } from 'esbuild';

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

function moduleAt(filename, overrides = {}) {
  const file = path.resolve(directory, filename);
  const module = { exports: {} };
  const source = transformSync(fs.readFileSync(file, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(
    name => overrides[name] || (name.startsWith('.') ? moduleAt(path.resolve(path.dirname(file), name), overrides) : require(name)),
    module,
    module.exports
  );
  return module.exports;
}

test('live display helper computes correct exercise metrics and never fabricates 0', () => {
  const helper = moduleAt('./liveDisplayHelper.js');
  const { computeExerciseMetric } = helper;

  // Squats: bilateral average knee flexion
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: 90 }, 'squats'), 85);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 70, rightKneeFlexion: 70 }, 'squats'), 70);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: null, rightKneeFlexion: 80 }, 'squats'), null);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: undefined }, 'squats'), null);
  assert.equal(computeExerciseMetric(null, 'squats'), null);
  assert.equal(computeExerciseMetric({}, 'squats'), null);

  // Lunges: active side knee flexion
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 75, rightKneeFlexion: 30 }, 'lunges', 'left'), 75);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 75, rightKneeFlexion: 82 }, 'lunges', 'right'), 82);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: null, rightKneeFlexion: 80 }, 'lunges', 'left'), null);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: null }, 'lunges', 'right'), null);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: 80 }, 'lunges', 'middle'), null);

  // Knee Extension: extension excursion from 90° (90 - flexion)
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 20, rightKneeFlexion: 80 }, 'knee-extension', 'left'), 70);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: 15 }, 'knee-extension', 'right'), 75);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: null, rightKneeFlexion: 15 }, 'knee-extension', 'left'), null);

  // Single-Leg Balance: hold duration seconds
  const mockKinematics = { leftKneeFlexion: 10, rightKneeFlexion: 45, ankleHeightDifference: 0.22 };
  assert.equal(computeExerciseMetric(mockKinematics, 'balance', 'left', { balanceHoldSeconds: 12.5 }), 12.5);
  assert.equal(computeExerciseMetric(mockKinematics, 'balance', 'left', { balanceHoldSeconds: 0 }), 0);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 10, rightKneeFlexion: 45, ankleHeightDifference: null }, 'balance', 'left', { balanceHoldSeconds: 10 }), null);
  assert.equal(computeExerciseMetric(null, 'balance', 'left', { balanceHoldSeconds: 10 }), null);
  assert.equal(computeExerciseMetric(mockKinematics, 'balance', 'left', null), null);

  // Unknown exercise type
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: 80 }, 'unknown_exercise'), null);
});

test('target zone calculation requires valid finite currentDepth and matching exercise type', () => {
  const { isTargetZoneReached } = moduleAt('./liveDisplayHelper.js');

  // Squats target zone (targetROM - 5)
  assert.equal(isTargetZoneReached(75, 80, 'squats'), true);
  assert.equal(isTargetZoneReached(74.9, 80, 'squats'), false);
  assert.equal(isTargetZoneReached(null, 80, 'squats'), false);
  assert.equal(isTargetZoneReached(undefined, 80, 'squats'), false);
  assert.equal(isTargetZoneReached(NaN, 80, 'squats'), false);

  // Lunges target zone
  assert.equal(isTargetZoneReached(80, 80, 'lunges'), true);
  assert.equal(isTargetZoneReached(70, 80, 'lunges'), false);

  // Knee Extension target zone
  assert.equal(isTargetZoneReached(70, 75, 'knee-extension'), true);
  assert.equal(isTargetZoneReached(69, 75, 'knee-extension'), false);

  // Balance target zone (currentDepth >= targetROM)
  assert.equal(isTargetZoneReached(30, 30, 'balance'), true);
  assert.equal(isTargetZoneReached(29, 30, 'balance'), false);
  assert.equal(isTargetZoneReached(null, 30, 'balance'), false);

  // Mismatched / invalid exercise type or invalid targetROM
  assert.equal(isTargetZoneReached(80, 80, 'invalid-exercise'), false);
  assert.equal(isTargetZoneReached(80, null, 'squats'), false);
  assert.equal(isTargetZoneReached(80, 0, 'squats'), false);
  assert.equal(isTargetZoneReached(80, -10, 'squats'), false);
});

test('LiveDigitalTwin displays required disclaimer and unverified avatar attribution', () => {
  // Mock three and react-three modules for static markup rendering
  const mockThree = {
    Vector3: class {
      constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
      set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
      copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
      subVectors(a, b) { this.x = a.x - b.x; this.y = a.y - b.y; this.z = a.z - b.z; return this; }
      length() { return Math.sqrt(this.x * this.x + this.y * this.y + this.z * this.z); }
      normalize() { return this; }
      add() { return this; }
      multiplyScalar() { return this; }
    },
  };
  const mockFiber = {
    Canvas: ({ children }) => React.createElement('div', { 'data-testid': 'mock-canvas' }, children),
    useFrame: () => {},
    useThree: () => ({ camera: { position: { set: () => {} } } }),
  };
  const mockDrei = {
    Grid: () => React.createElement('div', { 'data-testid': 'mock-grid' }),
    OrbitControls: () => React.createElement('div', { 'data-testid': 'mock-orbit-controls' }),
  };

  const LiveDigitalTwin = moduleAt('./LiveDigitalTwin.jsx', {
    three: mockThree,
    '@react-three/fiber': mockFiber,
    '@react-three/drei': mockDrei,
  }).default;

  const html = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
    })
  );

  const expectedNotice = '3D Digital Twin · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED · Drag to rotate · Scroll to zoom';
  assert.ok(html.includes(expectedNotice), `Expected disclaimer text not found in html: ${html}`);
});

test('LiveHUDOverlay renders UNAVAILABLE and explicit notice when kinematics are missing', () => {
  const LiveHUDOverlay = moduleAt('./LiveHUDOverlay.jsx').default;

  // When kinematics are null
  const htmlMissing = renderToStaticMarkup(
    React.createElement(LiveHUDOverlay, {
      landmarks: null,
      kinematics: null,
      trackerState: { exerciseType: 'squats', targetROM: 80, repCount: 0 },
      width: 640,
      height: 480,
    })
  );
  assert.ok(htmlMissing.includes('UNAVAILABLE'), 'Missing kinematics must render UNAVAILABLE');
  assert.ok(htmlMissing.includes('Exercise geometry UNAVAILABLE'), 'Coaching banner must report unavailable geometry');
  assert.doesNotMatch(htmlMissing, />0°</, 'Must not fabricate 0° when kinematics are missing');

  // When kinematics are valid for squats
  const htmlSquat = renderToStaticMarkup(
    React.createElement(LiveHUDOverlay, {
      landmarks: null,
      kinematics: { leftKneeFlexion: 80, rightKneeFlexion: 80 },
      trackerState: { exerciseType: 'squats', targetROM: 80, repCount: 3, lastCoachingMessage: 'Good depth' },
      width: 640,
      height: 480,
    })
  );
  assert.ok(htmlSquat.includes('80°'), 'Valid squat kinematics must render depth in degrees');
  assert.ok(htmlSquat.includes('Good depth'), 'Active coaching message displayed when available');
});

test('LiveTrackerStudio computes null currentDepth when kinematics are unavailable', () => {
  const helper = moduleAt('./liveDisplayHelper.js');
  // Missing kinematics must result in null currentDepth
  assert.equal(helper.computeExerciseMetric(null, 'squats', 'left', null), null);
  assert.equal(helper.computeExerciseMetric(null, 'lunges', 'left', null), null);
  assert.equal(helper.computeExerciseMetric(null, 'knee-extension', 'left', null), null);
  assert.equal(helper.computeExerciseMetric(null, 'balance', 'left', null), null);
});

test('unified.css provides focus-visible for transparent uploads and distinct disabled styling', () => {
  const cssPath = path.resolve(directory, 'unified.css');
  const css = fs.readFileSync(cssPath, 'utf8');

  // 1. Transparent file upload focus styling
  assert.match(
    css,
    /\.uw-upload-btn\s*:\s*has\([^)]*focus-visible\)|\.uw-upload-btn\s+input\[type=["']?file["']?\]:focus-visible/i,
    'unified.css must provide visible focus styling for transparent file upload input (:focus-visible)'
  );

  // 2. Unmistakable disabled button appearance for .uw-btn-finish-set:disabled
  assert.match(
    css,
    /\.uw-btn-finish-set:disabled/,
    'unified.css must have styles for .uw-btn-finish-set:disabled'
  );
  // Ensure disabled finish set button has distinct muted styling (e.g. low opacity, muted border or text)
  const disabledRuleMatch = css.match(/\.uw-btn-finish-set:disabled[^{]*\{([^}]+)\}/);
  assert.ok(disabledRuleMatch, 'Could not find .uw-btn-finish-set:disabled CSS block');
  const disabledStyles = disabledRuleMatch[1];
  assert.match(disabledStyles, /opacity\s*:\s*(0\.[1-5]|0\.[1-4][0-9])/i, 'Disabled button should have reduced opacity <= 0.5');
});
