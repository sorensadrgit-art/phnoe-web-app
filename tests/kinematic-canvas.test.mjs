import { describe, it } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

describe('Task 3: Kinematic Canvas & GLSL Shader Instrumentation', () => {
  it('exports valid GLSL vertex and fragment shaders with uniforms', async () => {
    const shaderPath = path.resolve('examples/soren-motion-v8/src/resume/projects/biomechanical-lab/KinematicShader.mjs');
    const { KinematicArcShader } = await import(pathToFileURL(shaderPath).href);

    assert.ok(KinematicArcShader, 'KinematicArcShader must be exported');
    assert.match(KinematicArcShader.vertexShader, /attribute|in\s+vec3/, 'must have valid GLSL vertex position handling');
    assert.match(KinematicArcShader.fragmentShader, /gl_FragColor/, 'must assign output fragment color');
    assert.ok(KinematicArcShader.uniforms.uTime, 'must include uTime uniform');
    assert.ok(KinematicArcShader.uniforms.uProgress, 'must include uProgress uniform');
    assert.ok(KinematicArcShader.uniforms.uAccentColor, 'must include uAccentColor uniform');
  });

  it('declares KinematicCanvas component interface with fallback logic', async () => {
    const componentPath = path.resolve('examples/soren-motion-v8/src/resume/projects/biomechanical-lab/KinematicCanvas.tsx');
    const fs = await import('node:fs');
    assert.strictEqual(fs.existsSync(componentPath), true, 'KinematicCanvas.tsx must exist');
    const source = fs.readFileSync(componentPath, 'utf8');
    assert.match(source, /webglcontextlost/, 'must listen for webglcontextlost');
    assert.match(source, /aria-label="Biomechanical Kinematic Viewport"/, 'must provide accessible aria-label');
    assert.match(source, /ACESFilmicToneMapping/, 'must configure ACESFilmicToneMapping');
  });
});
