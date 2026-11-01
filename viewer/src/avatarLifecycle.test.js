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
  const cleanName = filename.split('?')[0];
  const file = path.resolve(directory, cleanName);
  if (filename.includes('?raw')) {
    const rawContent = fs.readFileSync(file, 'utf8');
    return { default: rawContent, __esModule: true };
  }
  if (cleanName.endsWith('.json')) {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  }
  const module = { exports: {} };
  const source = transformSync(fs.readFileSync(file, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(
    name => {
      if (overrides[name]) return overrides[name];
      const resolved = name.startsWith('.') ? path.resolve(path.dirname(file), name) : name;
      if (overrides[resolved]) return overrides[resolved];
      if (name.includes('?raw')) {
        const rawFile = path.resolve(path.dirname(file), name.split('?')[0]);
        const content = fs.readFileSync(rawFile, 'utf8');
        return { default: content, __esModule: true };
      }
      return name.startsWith('.') ? moduleAt(resolved, overrides) : require(name);
    },
    module,
    module.exports
  );
  return module.exports;
}

test('avatar lifecycle helpers correctly report collapse and unmount state', () => {
  const {
    shouldMountAvatar,
    getAvatarLifecycleState,
    isRenderLoopSuspended,
    AVATAR_COLLAPSED_NOTICE,
    AVATAR_STATUS,
  } = moduleAt('./avatarLifecycle.js');

  // When avatar is collapsed
  assert.equal(shouldMountAvatar({ avatarVisible: false, isSimulated: true }), false);
  assert.equal(shouldMountAvatar({ avatarVisible: false, demoMode: true }), false);

  const collapsedState = getAvatarLifecycleState({
    avatarVisible: false,
    isSimulated: true,
    documentHidden: false,
  });

  assert.equal(collapsedState.isMounted, false, 'Collapsed avatar must not be mounted');
  assert.equal(collapsedState.shouldRenderCanvas, false, 'Canvas rendering must be disabled when collapsed');
  assert.equal(collapsedState.frameloop, 'never', 'Frameloop must be never when collapsed');
  assert.equal(collapsedState.status, AVATAR_STATUS.COLLAPSED);
  assert.ok(
    collapsedState.placeholderText.includes('3D Digital Twin collapsed to preserve resources'),
    'Collapsed placeholder must contain required collapse text'
  );
  assert.ok(
    collapsedState.placeholderText.includes('muscle activity NOT MEASURED'),
    'Collapsed placeholder must preserve unmeasured disclaimer'
  );
  assert.equal(collapsedState.placeholderText, AVATAR_COLLAPSED_NOTICE);

  // Render loop suspension
  assert.equal(isRenderLoopSuspended({ avatarVisible: false }), true);
});

test('document visibilityState hidden suspends WebGL render loop', () => {
  const {
    getAvatarLifecycleState,
    isRenderLoopSuspended,
    AVATAR_STATUS,
  } = moduleAt('./avatarLifecycle.js');

  // When document is hidden
  assert.equal(isRenderLoopSuspended({ avatarVisible: true, documentHidden: true }), true);

  const hiddenState = getAvatarLifecycleState({
    avatarVisible: true,
    isSimulated: true,
    documentHidden: true,
  });

  assert.equal(hiddenState.isMounted, true, 'Twin may remain mounted in memory or paused');
  assert.equal(hiddenState.frameloop, 'never', 'Frameloop MUST be never when document is hidden to pause RAF');
  assert.equal(hiddenState.status, AVATAR_STATUS.SUSPENDED_HIDDEN);

  // When document is visible
  assert.equal(isRenderLoopSuspended({ avatarVisible: true, documentHidden: false }), false);

  const activeState = getAvatarLifecycleState({
    avatarVisible: true,
    isSimulated: true,
    documentHidden: false,
  });

  assert.equal(activeState.isMounted, true);
  assert.equal(activeState.shouldRenderCanvas, true);
  assert.equal(activeState.frameloop, 'always');
  assert.equal(activeState.status, AVATAR_STATUS.ACTIVE);
  assert.equal(activeState.placeholderText, null);
});

test('WebGL context loss lifecycle keeps canvas mounted in suspended state and enables restoration', () => {
  const {
    createContextLossManager,
    getAvatarLifecycleState,
    AVATAR_STATUS,
    AVATAR_CONTEXT_LOST_NOTICE,
  } = moduleAt('./avatarLifecycle.js');

  let lostTriggered = false;
  let restoredTriggered = false;

  const manager = createContextLossManager({
    onContextLost: () => { lostTriggered = true; },
    onContextRestored: () => { restoredTriggered = true; },
  });

  assert.equal(manager.isContextLost(), false);

  let defaultPrevented = false;
  const mockEvent = {
    preventDefault: () => { defaultPrevented = true; },
  };

  manager.handleContextLost(mockEvent);
  assert.equal(defaultPrevented, true, 'Must prevent default on webglcontextlost to allow restoration');
  assert.equal(lostTriggered, true);
  assert.equal(manager.isContextLost(), true);

  const lostState = getAvatarLifecycleState({
    avatarVisible: true,
    isSimulated: true,
    contextLost: true,
  });

  assert.equal(lostState.status, AVATAR_STATUS.CONTEXT_LOST);
  // Key R4 Fix: Canvas remains mounted in suspended state to retain listeners for webglcontextrestored
  assert.equal(lostState.isMounted, true);
  assert.equal(lostState.shouldRenderCanvas, true);
  assert.equal(lostState.frameloop, 'never');
  assert.equal(lostState.placeholderText, AVATAR_CONTEXT_LOST_NOTICE);
  assert.equal(lostState.hasRestoreButton, true);

  manager.handleContextRestored({});
  assert.equal(restoredTriggered, true);
  assert.equal(manager.isContextLost(), false);
});

test('LiveDigitalTwin maintains mounted canvas with overlay during context loss and provides Restore 3D View button', () => {
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
    Canvas: ({ children, frameloop }) => React.createElement('div', { 'data-testid': 'mock-canvas', 'data-frameloop': frameloop }, children),
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

  // Active state renders canvas
  const activeHtml = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
      documentHidden: false,
    })
  );
  assert.ok(activeHtml.includes('data-testid="mock-canvas"'), 'Active avatar must render canvas');
  assert.ok(activeHtml.includes('data-testid="mock-grid"'), 'Active avatar must render grid');
  assert.ok(activeHtml.includes('data-testid="mock-orbit-controls"'), 'Active avatar must render controls');
  assert.ok(activeHtml.includes('data-frameloop="always"'));
  assert.ok(activeHtml.includes('3D Digital Twin · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED · Drag to rotate · Scroll to zoom'));

  // Suspended state sets frameloop="never"
  const hiddenHtml = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
      documentHidden: true,
    })
  );
  assert.ok(hiddenHtml.includes('data-frameloop="never"'), 'Hidden document must pass frameloop="never" to Canvas');

  // Context lost state: Canvas remains mounted in suspended state ('never') with overlay and Restore 3D View button
  const lostHtml = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
      initialContextLost: true,
    })
  );
  assert.ok(lostHtml.includes('data-testid="mock-canvas"'), 'Canvas MUST remain mounted during context loss to preserve webglcontextrestored listener');
  assert.ok(lostHtml.includes('data-frameloop="never"'), 'Canvas frameloop must be never while context is lost');
  assert.ok(!lostHtml.includes('data-testid="mock-grid"'), 'Scene elements like grid must be unmounted during context loss to prevent WebGL draw calls');
  assert.ok(!lostHtml.includes('data-testid="mock-orbit-controls"'), 'Scene controls must be unmounted during context loss');
  assert.ok(lostHtml.includes('WebGL context lost. Rendering suspended to protect GPU resources'), 'Overlay notice must be displayed');
  assert.ok(lostHtml.includes('Restore 3D View'), 'Accessible recreate/restore button must be available');
});

test('LiveTrackerStudio avatar toggle button updates aria-pressed and unmounts canvas while nonvisual tracking continues', () => {
  const mockThree = {
    Vector3: class {
      constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
      set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
      copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
      subVectors(a, b) { this.x = a.x - b.x; this.y = a.y - b.y; this.z = a.z - b.z; return this; }
      length() { return 0; }
      normalize() { return this; }
      add() { return this; }
      multiplyScalar() { return this; }
    },
  };
  const mockFiber = {
    Canvas: ({ children, frameloop }) => React.createElement('div', { 'data-testid': 'mock-canvas', 'data-frameloop': frameloop }, children),
    useFrame: () => {},
    useThree: () => ({ camera: { position: { set: () => {} } } }),
  };
  const mockDrei = {
    Grid: () => React.createElement('div', { 'data-testid': 'mock-grid' }),
    OrbitControls: () => React.createElement('div', { 'data-testid': 'mock-orbit-controls' }),
  };

  const LiveTrackerStudio = moduleAt('./LiveTrackerStudio.jsx', {
    three: mockThree,
    '@react-three/fiber': mockFiber,
    '@react-three/drei': mockDrei,
  }).default;

  // When avatar is visible (default)
  const visibleHtml = renderToStaticMarkup(
    React.createElement(LiveTrackerStudio, {
      demoMode: true,
      initialAvatarVisible: true,
    })
  );
  assert.ok(visibleHtml.includes('3D Avatar: ON'), 'Toggle button should indicate 3D Avatar is ON');
  assert.ok(visibleHtml.includes('aria-pressed="true"'), 'Toggle button must have aria-pressed="true" when avatar is ON');
  assert.ok(visibleHtml.includes('data-testid="mock-canvas"'), 'Canvas must be mounted when avatar is visible');
  assert.ok(!visibleHtml.includes('3D Digital Twin collapsed to preserve resources'), 'Must not display collapsed placeholder when visible');

  // When avatar is collapsed
  const collapsedHtml = renderToStaticMarkup(
    React.createElement(LiveTrackerStudio, {
      demoMode: true,
      initialAvatarVisible: false,
    })
  );
  assert.ok(collapsedHtml.includes('3D Avatar: OFF'), 'Toggle button should indicate 3D Avatar is OFF');
  assert.ok(collapsedHtml.includes('aria-pressed="false"'), 'Toggle button must have aria-pressed="false" when collapsed');
  assert.ok(!collapsedHtml.includes('data-testid="mock-canvas"'), 'Canvas must be completely unmounted when avatar is collapsed');
  assert.ok(
    collapsedHtml.includes('3D Digital Twin collapsed to preserve resources · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED'),
    'Must display required collapsed placeholder notice'
  );
  // Ensure nonvisual operation continues completely unhindered
  assert.ok(collapsedHtml.includes('uw-camera-viewport'), 'Camera feed/viewport remains mounted');
  assert.ok(collapsedHtml.includes('Chimes ON'), 'Audio chime controls remain functional');
  assert.ok(collapsedHtml.includes('SYNTHETIC SQUATS ANIMATION'), 'Exercise animation / tracking feed active');
});

test('Unsupported or failed WebGL rendering gracefully displays unavailable notice while nonvisual tracking operates', () => {
  const mockThree = {
    Vector3: class {
      constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
      set() { return this; }
      copy() { return this; }
      subVectors() { return this; }
      length() { return 0; }
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

  const unsupportedHtml = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
      webglSupported: false,
    })
  );

  assert.ok(!unsupportedHtml.includes('data-testid="mock-canvas"'), 'Canvas must not be rendered when WebGL is unsupported');
  assert.ok(
    unsupportedHtml.includes('3D Viewport unavailable (WebGL unsupported or disabled)'),
    'Must display explicit unavailable notice when WebGL is unsupported'
  );
  assert.ok(
    unsupportedHtml.includes('3D Digital Twin · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED · Drag to rotate · Scroll to zoom'),
    'Disclaimer banner must be preserved'
  );
});

test('liveDisplayHelper computes metrics cleanly without fabricating metrics or conflating 2D angles with depth', () => {
  const { computeExerciseMetric, isTargetZoneReached } = moduleAt('./liveDisplayHelper.js');

  // Verify kinematics safety: null / missing kinematics never fabricate numbers or depth
  assert.equal(computeExerciseMetric(null, 'squats'), null);
  assert.equal(computeExerciseMetric({}, 'squats'), null);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: null, rightKneeFlexion: 80 }, 'squats'), null);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: undefined }, 'squats'), null);

  // Valid kinematics compute exact joint angles
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 80, rightKneeFlexion: 90 }, 'squats'), 85);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 75, rightKneeFlexion: 80 }, 'lunges', 'left'), 75);
  assert.equal(computeExerciseMetric({ leftKneeFlexion: 20, rightKneeFlexion: 80 }, 'knee-extension', 'left'), 70);

  // Target zone requires valid finite currentDepth and never triggers on null
  assert.equal(isTargetZoneReached(null, 80, 'squats'), false);
  assert.equal(isTargetZoneReached(80, 80, 'squats'), true);
});

test('N03: getAvatarLifecycleState handles kinematicsMissing and exposes unmeasured disclaimer notice', () => {
  const {
    getAvatarLifecycleState,
    AVATAR_STATUS,
    AVATAR_UNMEASURED_KINEMATICS_NOTICE,
    AVATAR_COLLAPSED_NOTICE,
  } = moduleAt('./avatarLifecycle.js');

  assert.ok(AVATAR_UNMEASURED_KINEMATICS_NOTICE, 'AVATAR_UNMEASURED_KINEMATICS_NOTICE must be defined');
  assert.ok(
    AVATAR_UNMEASURED_KINEMATICS_NOTICE.includes('muscle activity NOT MEASURED'),
    'Notice must include required unmeasured disclaimer'
  );

  const missingKinematicsState = getAvatarLifecycleState({
    avatarVisible: true,
    isSimulated: true,
    kinematicsMissing: true,
  });

  assert.equal(missingKinematicsState.status, AVATAR_STATUS.UNMEASURED_KINEMATICS);
  assert.equal(missingKinematicsState.isMounted, true);
  assert.equal(missingKinematicsState.shouldRenderCanvas, true);
  assert.equal(missingKinematicsState.unmeasuredNotice, AVATAR_UNMEASURED_KINEMATICS_NOTICE);
  assert.ok(
    missingKinematicsState.unmeasuredNotice.includes('muscle activity NOT MEASURED'),
    'Unmeasured banner must include unmeasured notice'
  );

  // Collapsed state takes priority over kinematics missing
  const collapsedState = getAvatarLifecycleState({
    avatarVisible: false,
    isSimulated: true,
    kinematicsMissing: true,
  });
  assert.equal(collapsedState.status, AVATAR_STATUS.COLLAPSED);
  assert.equal(collapsedState.placeholderText, AVATAR_COLLAPSED_NOTICE);
});

test('N03: LiveDigitalTwin respects avatarVisible=false by unmounting Canvas without display:none and rendering collapsed notice', () => {
  const mockThree = {
    Vector3: class {
      constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
      set() { return this; }
      copy() { return this; }
      subVectors() { return this; }
      length() { return 0; }
      normalize() { return this; }
      add() { return this; }
      multiplyScalar() { return this; }
    },
  };
  const mockFiber = {
    Canvas: ({ children, frameloop }) => React.createElement('div', { 'data-testid': 'mock-canvas', 'data-frameloop': frameloop }, children),
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

  const collapsedHtml = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
      avatarVisible: false,
    })
  );

  assert.ok(!collapsedHtml.includes('data-testid="mock-canvas"'), 'Canvas MUST be completely unmounted when avatarVisible is false');
  assert.ok(!collapsedHtml.includes('display:none'), 'display:none alone is strictly prohibited for avatar collapse');
  assert.ok(!collapsedHtml.includes('display: none'), 'display: none alone is strictly prohibited for avatar collapse');
  assert.ok(
    collapsedHtml.includes('3D Digital Twin collapsed to preserve resources · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED'),
    'Must display unmeasured disclaimer banner when collapsed'
  );
});

test('N03: LiveDigitalTwin displays unmeasured disclaimer banner when kinematics are missing and does not fabricate metrics', () => {
  const mockThree = {
    Vector3: class {
      constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
      set() { return this; }
      copy() { return this; }
      subVectors() { return this; }
      length() { return 0; }
      normalize() { return this; }
      add() { return this; }
      multiplyScalar() { return this; }
    },
  };
  const mockFiber = {
    Canvas: ({ children, frameloop }) => React.createElement('div', { 'data-testid': 'mock-canvas', 'data-frameloop': frameloop }, children),
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

  const htmlMissingKinematics = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      kinematics: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
      avatarVisible: true,
    })
  );

  assert.ok(htmlMissingKinematics.includes('data-testid="mock-canvas"'), 'Canvas mounted when avatarVisible is true');
  assert.ok(
    htmlMissingKinematics.includes('3D Digital Twin · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED'),
    'Unmeasured disclaimer banner must be displayed'
  );
  assert.ok(
    htmlMissingKinematics.includes('Kinematics unmeasured') || htmlMissingKinematics.includes('Kinematics missing'),
    'Explicit unmeasured kinematics notice must be displayed when kinematics are missing'
  );
  assert.doesNotMatch(htmlMissingKinematics, />0°</, 'Never fabricate 0° or dummy angles when kinematics are missing');
});

test('N03: WebGL context restores automatically on native webglcontextrestored browser event without prior manual button click', () => {
  const mockThree = {
    Vector3: class {
      constructor() { return this; }
      set() { return this; }
      copy() { return this; }
      subVectors() { return this; }
      length() { return 0; }
      normalize() { return this; }
      add() { return this; }
      multiplyScalar() { return this; }
    },
  };
  const mockFiber = {
    Canvas: ({ children, frameloop }) => React.createElement('div', { 'data-testid': 'mock-canvas', 'data-frameloop': frameloop }, children),
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

  // Render with initialContextLost=true
  const lostHtml = renderToStaticMarkup(
    React.createElement(LiveDigitalTwin, {
      landmarks: null,
      mirrored: true,
      targetROM: 80,
      currentDepth: null,
      exerciseType: 'squats',
      initialContextLost: true,
    })
  );
  assert.ok(lostHtml.includes('WebGL context lost. Rendering suspended to protect GPU resources'));

  // Test that context manager handleContextRestored clears contextLost even without isRestoringRef
  const { createContextLossManager } = moduleAt('./avatarLifecycle.js');
  let restored = false;
  const manager = createContextLossManager({
    onContextLost: () => {},
    onContextRestored: () => { restored = true; },
  });
  manager.handleContextLost({ preventDefault: () => {} });
  assert.equal(manager.isContextLost(), true);
  manager.handleContextRestored({});
  assert.equal(manager.isContextLost(), false);
  assert.equal(restored, true);
});


// Stubbed hook/Canvas harness: runs actual component callbacks/effects and prop
// transitions. This is not a React mount or browser/WebGL verification.
function lifecycleHarness(initialProps = {}) {
  let slots = [], cursor = 0, pending = [], dirty = false, tree, props;
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]));
  const hooks = {
    ...React,
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => {
        const next = typeof value === 'function' ? value(slots[i]) : value;
        if (!Object.is(next, slots[i])) { slots[i] = next; dirty = true; }
      }];
    },
    useRef(initial) {
      const i = cursor++;
      return slots[i] ??= { current: initial };
    },
    useMemo(factory, deps) {
      const i = cursor++;
      if (!slots[i] || changed(slots[i].deps, deps)) slots[i] = { value: factory(), deps };
      return slots[i].value;
    },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!slots[i] || changed(slots[i].deps, deps)) {
        pending.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, cleanup: effect() };
        });
      }
    },
  };
  const Canvas = () => null;
  let frame;
  const Component = moduleAt('./LiveDigitalTwin.jsx', {
    react: hooks,
    '@react-three/fiber': {
      Canvas, useFrame: callback => { frame = callback; },
      useThree: () => ({ gl: harness.renderer, camera: { position: { set() {} } } }),
    },
    '@react-three/drei': { Grid: () => null, OrbitControls: () => null },
  }).default;
  function nodes(node, predicate) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(child => nodes(child, predicate));
    return [...(predicate(node) ? [node] : []), ...nodes(node.props?.children, predicate)];
  }
  const harness = {
    renderer: null,
    references: () => slots.filter(slot => slot && Object.hasOwn(slot, 'current')).map(slot => slot.current),
    render(next = {}) {
      props = { landmarks: null, webglSupported: true, ...props, ...next };
      let passes = 0;
      do {
        assert.ok(++passes < 20, 'Harness effects must settle');
        dirty = false; cursor = 0; pending = [];
        tree = Component(props);
        pending.forEach(effect => effect());
      } while (dirty);
      return tree;
    },
    canvas: () => nodes(tree, node => node.type === Canvas)[0],
    lost: () => nodes(tree, node => node.props?.className === 'uw-twin-context-lost-overlay').length > 0,
    text: () => nodes(tree, () => true).flatMap(node => React.Children.toArray(node.props?.children).filter(child => typeof child === 'string')).join(' '),
    create(renderer) { harness.renderer = renderer; harness.canvas().props.onCreated({ gl: renderer }); harness.render(); },
    restore() {
      const button = nodes(tree, node => node.props?.className === 'uw-twin-btn-restore')[0];
      assert.ok(button, 'Loss must expose recovery control');
      button.props.onClick(); harness.render();
    },
    unmount() { slots.forEach(slot => slot?.cleanup?.()); },
    frame(renderer, landmarks) {
      const rig = nodes(tree, node => node.type?.name === 'AvatarRig')[0];
      assert.ok(rig, 'Active scene contains actual AvatarRig');
      harness.renderer = renderer;
      const parentSlots = slots;
      slots = []; cursor = 0;
      try { rig.type({ ...rig.props, landmarks }); } finally { slots = parentSlots; }
      frame({}, 0.016);
    },
  };
  harness.render(initialProps);
  return harness;
}

function trackedRenderer({ lost = false, extension = null } = {}) {
  const listeners = new Map();
  const history = new Map();
  const context = { isContextLost: () => lost, getExtension: () => extension };
  const canvas = {
    addEventListener(type, callback) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(callback);
      history.set(type, callback);
    },
    removeEventListener(type, callback) { listeners.get(type)?.delete(callback); },
  };
  return {
    domElement: canvas,
    getContext: () => context,
    count: type => listeners.get(type)?.size || 0,
    callback: type => history.get(type),
    emit(type) {
      lost = type === 'webglcontextlost';
      let prevented = false;
      const event = { target: canvas, preventDefault() { prevented = true; } };
      [...(listeners.get(type) || [])].forEach(callback => callback(event));
      return prevented;
    },
  };
}

const LOST_EVENT = 'webglcontextlost';
const RESTORED_EVENT = 'webglcontextrestored';

test('stubbed lifecycle: collapse releases owned listeners/references; reopen and unmount cleanly', () => {
  const h = lifecycleHarness();
  const old = trackedRenderer();
  h.create(old);
  assert.equal(old.count(LOST_EVENT), 1);
  assert.equal(old.count(RESTORED_EVENT), 1);
  h.render({ avatarVisible: false });
  assert.equal(h.canvas(), undefined);
  assert.match(h.text(), /collapsed to preserve resources.*muscle activity NOT MEASURED/);
  assert.equal(old.count(LOST_EVENT), 0, 'Prop collapse detaches loss listener');
  assert.equal(old.count(RESTORED_EVENT), 0, 'Prop collapse detaches restoration listener');
  assert.equal(h.references().includes(old), false, 'Collapse clears renderer reference');
  assert.equal(h.references().includes(old.domElement), false, 'Collapse clears canvas reference');
  h.render({ avatarVisible: true });
  const current = trackedRenderer();
  h.create(current);
  h.create(current);
  assert.equal(current.count(LOST_EVENT), 1);
  assert.equal(current.count(RESTORED_EVENT), 1);
  old.emit(LOST_EVENT); h.render();
  assert.equal(h.lost(), false);
  h.unmount();
  assert.equal(current.count(LOST_EVENT), 0);
  assert.equal(current.count(RESTORED_EVENT), 0);
  assert.equal(h.references().includes(current), false, 'Unmount clears renderer reference');
  assert.equal(h.references().includes(current.domElement), false, 'Unmount clears canvas reference');
});

test('stubbed lifecycle: active native loss suspends; automatic restore needs no manual flag', () => {
  const h = lifecycleHarness();
  const renderer = trackedRenderer();
  h.create(renderer);
  assert.equal(renderer.emit(LOST_EVENT), true, 'Active loss prevents default'); h.render();
  assert.equal(h.lost(), true);
  assert.equal(h.canvas().props.frameloop, 'never');
  assert.match(h.text(), /muscle activity NOT MEASURED/);
  renderer.emit(RESTORED_EVENT); h.render();
  assert.equal(h.lost(), false);
  assert.equal(h.canvas().props.frameloop, 'always');
  h.render({ documentHidden: true });
  assert.equal(h.canvas().props.frameloop, 'never');
  h.render({ documentHidden: false });
  assert.equal(h.canvas().props.frameloop, 'always');
  h.unmount();
});

test('stubbed lifecycle: queued events from superseded canvas cannot change current state', () => {
  const h = lifecycleHarness();
  const old = trackedRenderer(); h.create(old);
  const staleLoss = old.callback(LOST_EVENT), staleRestore = old.callback(RESTORED_EVENT);
  const current = trackedRenderer(); h.create(current);
  assert.equal(old.count(LOST_EVENT), 0);
  assert.equal(old.count(RESTORED_EVENT), 0);
  staleLoss({ target: old.domElement, preventDefault() {} }); h.render();
  assert.equal(h.lost(), false, 'Queued old loss cannot affect active canvas');
  current.emit(LOST_EVENT); h.render();
  staleRestore({ target: old.domElement }); h.render();
  assert.equal(h.lost(), true, 'Queued old restore cannot clear current loss');
  current.emit(RESTORED_EVENT); h.render();
  assert.equal(h.lost(), false);
  h.unmount();
});

test('stubbed lifecycle: manual recovery stays suspended until healthy native restore or replacement', () => {
  const h = lifecycleHarness();
  let attempts = 0;
  const old = trackedRenderer({ extension: { restoreContext() { attempts++; } } });
  h.create(old); old.emit(LOST_EVENT); h.render();
  const key = h.canvas().key;
  h.restore();
  assert.equal(h.lost(), true, 'A recovery request is not proof of restored context');
  assert.equal(h.canvas().props.frameloop, 'never');
  old.emit(LOST_EVENT); h.render();
  assert.equal(h.lost(), true, 'Further losses remain visible during recovery');
  if (h.canvas().key === key) {
    assert.equal(attempts, 1, 'Native strategy must actually request restoration');
    old.emit(RESTORED_EVENT); h.render();
  } else {
    h.create(trackedRenderer());
  }
  assert.equal(h.lost(), false);
  assert.equal(h.canvas().props.frameloop, 'always');
  h.unmount();
});

test('stubbed lifecycle: failed recovery and unhealthy replacement retain loss warning', () => {
  const h = lifecycleHarness();
  const old = trackedRenderer({ extension: { restoreContext() { throw new Error('restore failed'); } } });
  h.create(old); old.emit(LOST_EVENT); h.render();
  h.restore();
  assert.equal(h.lost(), true, 'Failure must remain visible');
  h.create(trackedRenderer({ lost: true }));
  assert.equal(h.lost(), true, 'An already-lost replacement is not healthy creation');
  assert.equal(h.canvas().props.frameloop, 'never');
  h.create(trackedRenderer());
  assert.equal(h.lost(), false, 'Healthy replacement is observable recovery');
  h.unmount();
});

test('stubbed lifecycle: AvatarRig reads actual renderer context and skips hidden/lost frame work', () => {
  const h = lifecycleHarness();
  let reads = 0;
  const landmarks = new Proxy([], { get(target, key) { if (key === 'length') reads++; return Reflect.get(target, key); } });
  h.frame(trackedRenderer({ lost: true }), landmarks);
  assert.equal(reads, 0, 'Lost getContext() must return before landmark work');
  h.frame(trackedRenderer(), landmarks);
  assert.ok(reads > 0, 'Healthy frame reaches landmark work; guard assertion is meaningful');
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  try {
    Object.defineProperty(globalThis, 'document', { configurable: true, value: { hidden: true } });
    reads = 0;
    h.frame(trackedRenderer(), landmarks);
    assert.equal(reads, 0, 'Hidden document skips frame work with healthy context');
  } finally {
    if (previousDocument) Object.defineProperty(globalThis, 'document', previousDocument);
    else delete globalThis.document;
  }
  h.unmount();
});

test('stubbed lifecycle: WebGL support probe runs once per fresh mount, never on prop rerenders', () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const mounted = [];
  let probes = 0;
  let supported = true;
  try {
    Object.defineProperty(globalThis, 'window', {
      configurable: true, value: { WebGLRenderingContext: function WebGLRenderingContext() {} },
    });
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        hidden: false,
        addEventListener() {}, removeEventListener() {},
        createElement(tag) {
          assert.equal(tag, 'canvas');
          probes++;
          return { getContext: () => supported ? {} : null };
        },
      },
    });
    const mount = props => {
      const h = lifecycleHarness(props);
      mounted.push(h);
      return h;
    };
    const automatic = mount({ webglSupported: undefined });
    assert.equal(probes, 1, 'Fresh automatic mount probes support');
    assert.ok(automatic.canvas(), 'Supported automatic mount renders Canvas');
    for (let i = 0; i < 100; i++) {
      automatic.render({
        documentHidden: i % 2 === 0,
        currentDepth: i,
        initialContextLost: i % 3 === 0,
        avatarVisible: i % 5 !== 0,
      });
    }
    assert.equal(probes, 1, 'Prop and effect rerenders must not create support-probe canvases');
    automatic.render({ webglSupported: false, avatarVisible: true });
    assert.equal(automatic.canvas(), undefined, 'Explicit unsupported update removes Canvas');
    assert.match(automatic.text(), /WebGL unsupported or disabled.*muscle activity NOT MEASURED/);
    automatic.render({ webglSupported: true, initialContextLost: false, documentHidden: false });
    assert.ok(automatic.canvas(), 'Explicit supported update still synchronizes');
    automatic.render({ webglSupported: undefined });
    assert.equal(probes, 1, 'Removing override preserves existing support state without a new mount');

    mount({ webglSupported: undefined });
    assert.equal(probes, 2, 'A distinct fresh mount performs its own support probe');
    const overridden = mount({ webglSupported: false });
    assert.equal(probes, 2, 'Explicit initial override bypasses automatic support probe');
    assert.equal(overridden.canvas(), undefined);
    overridden.render({ webglSupported: true });
    assert.ok(overridden.canvas(), 'Initially unsupported override can be changed');
    assert.equal(probes, 2);

    assert.ok(mount({ webglSupported: true }).canvas(), 'Explicit supported initial override renders Canvas');
    assert.equal(probes, 2, 'Explicit supported initial override also bypasses detection');

    supported = false;
    const unavailable = mount({ webglSupported: undefined });
    assert.equal(probes, 3, 'Unsupported automatic mount probes once');
    assert.equal(unavailable.canvas(), undefined);
    assert.match(unavailable.text(), /WebGL unsupported or disabled.*muscle activity NOT MEASURED/);
    for (let i = 0; i < 100; i++) unavailable.render({ currentDepth: i, documentHidden: i % 2 === 0 });
    assert.equal(probes, 3, 'Unsupported rerenders must not retry support detection');
    assert.equal(unavailable.canvas(), undefined);
    unavailable.render({ webglSupported: true });
    assert.ok(unavailable.canvas(), 'Explicit override remains authoritative after detection');
    assert.equal(probes, 3);
  } finally {
    mounted.forEach(h => h.unmount());
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow);
    else delete globalThis.window;
    if (previousDocument) Object.defineProperty(globalThis, 'document', previousDocument);
    else delete globalThis.document;
  }
});
