import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const explorerFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'SectionExplorer.tsx');
const cssFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'explorers.css');
const biomechTokensFile = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'projects', 'biomechanical-lab', 'tokens.css');

test('Task 4: Section-by-Section Visual & Graphic Uplift', async (t) => {
  await t.test('SectionExplorer embeds futuristic telemetry badges and HUD elements', () => {
    assert.ok(fs.existsSync(explorerFile), 'SectionExplorer.tsx must exist');
    const content = fs.readFileSync(explorerFile, 'utf8');
    assert.match(content, /ex-hud-overlay|ex-bio-hud/, 'must render HUD overlays or telemetry badges');
    assert.match(content, /ex-role-timeline/, 'Experience must render styled timeline rail');
  });

  await t.test('explorers.css defines glowing cybernetic styles for HUD, rails, and badges', () => {
    assert.ok(fs.existsSync(cssFile), 'explorers.css must exist');
    const css = fs.readFileSync(cssFile, 'utf8');
    assert.match(css, /\.ex-hud-overlay/, 'must style .ex-hud-overlay');
    assert.match(css, /\.ex-role-timeline/, 'must style .ex-role-timeline');
    assert.match(css, /box-shadow:.*0 0/, 'must incorporate neon bloom glows on active elements');
  });

  await t.test('biomechanical-lab tokens.css harmonizes with dark cybernetic theme', () => {
    assert.ok(fs.existsSync(biomechTokensFile), 'biomechanical-lab tokens.css must exist');
    const tokens = fs.readFileSync(biomechTokensFile, 'utf8');
    assert.match(tokens, /--biomech-bg:.*#0/, 'must use deep obsidian background');
    assert.match(tokens, /--biomech-cyan:.*#0/, 'must define luminous cyan accent');
  });
});
