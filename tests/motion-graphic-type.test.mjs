import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('Task 2: Motion Graphic Kinetic Typography Component', () => {
  const componentPath = path.resolve('examples/soren-motion-v8/src/resume/motion/MotionGraphicType.tsx');
  const cssPath = path.resolve('examples/soren-motion-v8/src/resume/explorers.css');

  it('verifies MotionGraphicType.tsx exists and exports MotionGraphicType component', () => {
    assert.strictEqual(fs.existsSync(componentPath), true, 'MotionGraphicType.tsx must exist');
    const content = fs.readFileSync(componentPath, 'utf8');
    assert.match(content, /export function MotionGraphicType/, 'exports MotionGraphicType component');
    assert.match(content, /interface MotionGraphicTypeProps/, 'declares MotionGraphicTypeProps');
  });

  it('verifies accessible character splitting and aria attributes in MotionGraphicType', () => {
    const content = fs.readFileSync(componentPath, 'utf8');
    assert.match(content, /aria-label=\{/, 'outer container sets aria-label for accessibility');
    assert.match(content, /aria-hidden="true"/, 'inner visual characters are marked aria-hidden');
    assert.match(content, /ex-kinetic-char/, 'renders ex-kinetic-char class per glyph');
    assert.match(content, /ex-kinetic-title/, 'renders ex-kinetic-title root container');
  });

  it('verifies support for telemetry kicker, animation variants, and reduced motion', () => {
    const content = fs.readFileSync(componentPath, 'utf8');
    assert.match(content, /kicker/, 'supports kicker prop');
    assert.match(content, /variant/, 'supports animation variant prop (stagger, wave, telemetry-scramble)');
    assert.match(content, /prefersReducedMotion|reduced/, 'supports reduced motion fallback');
    assert.match(content, /gsap/, 'uses GSAP for kinetic typography animation');
  });

  it('verifies explorers.css defines kinetic typography classes and 3D transforms', () => {
    assert.strictEqual(fs.existsSync(cssPath), true, 'explorers.css must exist');
    const css = fs.readFileSync(cssPath, 'utf8');
    assert.match(css, /\.ex-kinetic-title/, 'explorers.css must declare .ex-kinetic-title');
    assert.match(css, /\.ex-kinetic-char/, 'explorers.css must declare .ex-kinetic-char');
    assert.match(css, /transform-style:\s*preserve-3d|will-change:\s*transform/, 'hardware-accelerated transforms');
    assert.match(css, /font-family:\s*var\(--font-display,/, 'uses Syne display font variable');
  });
});
