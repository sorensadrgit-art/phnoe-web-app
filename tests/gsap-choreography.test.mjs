import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const motionFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'motion', 'gsapModalChoreography.ts');
const explorerFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'SectionExplorer.tsx');
const controlsFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'ExplorerControls.tsx');

test('Task 2: GSAP Kinetic Choreography & Text Motion Engine', async (t) => {
  await t.test('gsapModalChoreography exists and exports choreography methods', () => {
    assert.ok(fs.existsSync(motionFile), 'gsapModalChoreography.ts must exist');
    const content = fs.readFileSync(motionFile, 'utf8');
    assert.match(content, /export function animateModalEntrance/, 'must export animateModalEntrance');
    assert.match(content, /export function animateTabTransition/, 'must export animateTabTransition');
    assert.match(content, /export function animateKineticKicker/, 'must export animateKineticKicker');
    assert.match(content, /import gsap from 'gsap'/, 'must import GSAP');
  });

  await t.test('SectionExplorer imports and wires GSAP entrance choreography', () => {
    assert.ok(fs.existsSync(explorerFile), 'SectionExplorer.tsx must exist');
    const content = fs.readFileSync(explorerFile, 'utf8');
    assert.match(content, /animateModalEntrance/, 'SectionExplorer must import and invoke animateModalEntrance');
  });

  await t.test('ExplorerControls incorporates kinetic transitions and spring indicators', () => {
    assert.ok(fs.existsSync(controlsFile), 'ExplorerControls.tsx must exist');
    const content = fs.readFileSync(controlsFile, 'utf8');
    assert.match(content, /animateTabTransition|motion\.div|spring/, 'ExplorerControls must use kinetic transition dynamics');
  });
});
