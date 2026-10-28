import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const shaderFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'motion', 'modalShaders.ts');
const canvasFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'motion', 'ModalAmbientCanvas.tsx');
const explorerFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'SectionExplorer.tsx');

test('Task 3: Interactive WebGL Ambient Background Shader Canvas', async (t) => {
  await t.test('modalShaders exports ambientVertexShader and ambientFragmentShader with uniforms', () => {
    assert.ok(fs.existsSync(shaderFile), 'modalShaders.ts must exist');
    const content = fs.readFileSync(shaderFile, 'utf8');
    assert.match(content, /export const ambientVertexShader/, 'must export ambientVertexShader');
    assert.match(content, /export const ambientFragmentShader/, 'must export ambientFragmentShader');
    assert.match(content, /uniform float uTime;/, 'must declare uTime uniform');
    assert.match(content, /uniform vec3 uAccentColor;/, 'must declare uAccentColor uniform');
    assert.match(content, /uniform vec2 uMouse;/, 'must declare uMouse uniform');
    assert.match(content, /uniform vec2 uResolution;/, 'must declare uResolution uniform');
  });

  await t.test('ModalAmbientCanvas component manages Three.js WebGL canvas lifecycle', () => {
    assert.ok(fs.existsSync(canvasFile), 'ModalAmbientCanvas.tsx must exist');
    const content = fs.readFileSync(canvasFile, 'utf8');
    assert.match(content, /export function ModalAmbientCanvas/, 'must export ModalAmbientCanvas component');
    assert.match(content, /THREE\.WebGLRenderer/, 'must instantiate Three.js WebGLRenderer');
    assert.match(content, /requestAnimationFrame/, 'must use RAF render loop');
    assert.match(content, /pointer-events: none|ex-modal-ambient-canvas/, 'must be pointer-events none to preserve scroll');
  });

  await t.test('SectionExplorer embeds ModalAmbientCanvas into modal background', () => {
    assert.ok(fs.existsSync(explorerFile), 'SectionExplorer.tsx must exist');
    const content = fs.readFileSync(explorerFile, 'utf8');
    assert.match(content, /ModalAmbientCanvas/, 'SectionExplorer must render ModalAmbientCanvas');
  });
});
