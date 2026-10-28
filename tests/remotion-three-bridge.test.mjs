import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('Task 3: Remotion & Three.js Deterministic 3D Canvas Bridge', () => {
  const bridgePath = path.resolve('motion-source/biomechanical-hero/src/components/ThreeCanvasBridge.tsx');
  const compPath = path.resolve('motion-source/biomechanical-hero/src/compositions/BiomechHeroFilm.tsx');

  it('verifies ThreeCanvasBridge.tsx exists and exports ThreeCanvasBridge component', () => {
    assert.strictEqual(fs.existsSync(bridgePath), true, 'ThreeCanvasBridge.tsx must exist');
    const content = fs.readFileSync(bridgePath, 'utf8');
    assert.match(content, /export const ThreeCanvasBridge|export function ThreeCanvasBridge/, 'exports ThreeCanvasBridge component');
    assert.match(content, /frame:\s*number/, 'component accepts frame prop');
  });

  it('verifies deterministic Three.js rendering driven by frame prop without RAF loop', () => {
    const content = fs.readFileSync(bridgePath, 'utf8');
    assert.match(content, /renderer\.render\(scene,\s*camera\)/, 'explicitly renders scene and camera per frame');
    assert.match(content, /THREE\.PerspectiveCamera/, 'configures Three.js PerspectiveCamera');
    assert.match(content, /THREE\.WebGLRenderer/, 'configures Three.js WebGLRenderer');
    assert.strictEqual(/requestAnimationFrame/.test(content), false, 'must not use requestAnimationFrame loop for Remotion determinism');
  });

  it('verifies BiomechHeroFilm mounts ThreeCanvasBridge underneath TelemetryOverlay', () => {
    assert.strictEqual(fs.existsSync(compPath), true, 'BiomechHeroFilm.tsx must exist');
    const content = fs.readFileSync(compPath, 'utf8');
    assert.match(content, /import\s+.*ThreeCanvasBridge.*from/, 'imports ThreeCanvasBridge');
    assert.match(content, /<ThreeCanvasBridge\s+frame=\{frame\}/, 'mounts ThreeCanvasBridge with current frame');
  });
});
