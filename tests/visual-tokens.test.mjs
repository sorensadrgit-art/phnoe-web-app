import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const htmlPath = path.join(root, 'examples', 'soren-motion-v8', 'index.html');
const tokensPath = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'luxuryTokens.ts');
const cssPath = path.join(root, 'examples', 'soren-motion-v8', 'src', 'resume', 'explorers.css');

test('Task 1: Typography System & Dark Cybernetic Token Architecture', async (t) => {
  await t.test('index.html links Google Fonts Syne, Space Grotesk, and JetBrains Mono', () => {
    assert.ok(fs.existsSync(htmlPath), 'index.html must exist');
    const html = fs.readFileSync(htmlPath, 'utf8');
    assert.match(html, /fonts\.googleapis\.com/, 'must preconnect to fonts.googleapis.com');
    assert.match(html, /fonts\.gstatic\.com/, 'must preconnect to fonts.gstatic.com');
    assert.match(html, /family=Syne/, 'must load Syne display font');
    assert.match(html, /Space\+Grotesk/, 'must load Space Grotesk font');
    assert.match(html, /JetBrains\+Mono/, 'must load JetBrains Mono font');
  });

  await t.test('luxuryTokens exports cyberneticTokens with luminous palettes', () => {
    assert.ok(fs.existsSync(tokensPath), 'luxuryTokens.ts must exist');
    const content = fs.readFileSync(tokensPath, 'utf8');
    assert.match(content, /cyberneticTokens/, 'must export cyberneticTokens');
    assert.match(content, /emeraldBio/, 'must define emeraldBio accent');
    assert.match(content, /solarAmber/, 'must define solarAmber accent');
    assert.match(content, /synapticCyan/, 'must define synapticCyan accent');
    assert.match(content, /cobaltCyber/, 'must define cobaltCyber accent');
    assert.match(content, /neonViolet/, 'must define neonViolet accent');
    assert.match(content, /hyperPlatinum/, 'must define hyperPlatinum accent');
  });

  await t.test('explorers.css applies dark glassmorphic styling and futuristic typography', () => {
    assert.ok(fs.existsSync(cssPath), 'explorers.css must exist');
    const css = fs.readFileSync(cssPath, 'utf8');
    assert.match(css, /Syne/, 'headings must use Syne font');
    assert.match(css, /Space Grotesk/, 'body content must use Space Grotesk');
    assert.match(css, /JetBrains Mono/, 'kickers and labels must use JetBrains Mono');
    assert.match(css, /backdrop-filter/, 'modal container must use backdrop-filter');
  });
});
