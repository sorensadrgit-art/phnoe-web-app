import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('Task 1: OpenDesign & HyperFrames Scaffolding', () => {
  it('scaffolds valid HyperFrames configuration', () => {
    const configPath = path.resolve('motion-source/biomechanical-hero/hyperframes.json');
    assert.strictEqual(fs.existsSync(configPath), true, 'hyperframes.json must exist');
    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    assert.strictEqual(config.fps, 60, 'fps must be 60');
    assert.strictEqual(config.width, 2560, 'width must be 2560');
    assert.strictEqual(config.height, 1440, 'height must be 1440');
  });

  it('declares required dark luxury design tokens in tokens.css', () => {
    const cssPath = path.resolve('examples/soren-motion-v8/src/resume/projects/biomechanical-lab/tokens.css');
    assert.strictEqual(fs.existsSync(cssPath), true, 'tokens.css must exist');
    const css = fs.readFileSync(cssPath, 'utf8');
    assert.match(css, /--bg:\s*#080f12/, 'tokens.css must declare signature v8 ink background');
    assert.match(css, /--alpine-blue:\s*#7fafc7/, 'tokens.css must declare v8 alpine blue');
    assert.match(css, /--telemetry-amber:/, 'tokens.css must declare --telemetry-amber');
  });

  it('verifies roughness texture map generation', () => {
    const texPath = path.resolve('examples/soren-motion-v8/public/assets/textures/roughness-imperfections.png');
    assert.strictEqual(fs.existsSync(texPath), true, 'roughness-imperfections.png must exist');
    const stat = fs.statSync(texPath);
    assert.ok(stat.size > 10000, 'texture map must be greater than 10KB');
  });
});
