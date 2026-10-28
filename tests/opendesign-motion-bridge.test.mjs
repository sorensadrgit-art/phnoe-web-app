import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('OpenDesign Motion Token Bridge & Hyperframes Parity', () => {
  const tokensPath = path.resolve('examples/soren-motion-v8/src/resume/motion/openDesignMotionTokens.ts');
  const hyperframesPath = path.resolve('motion-source/biomechanical-hero/hyperframes.json');

  it('verifies openDesignMotionTokens.ts exists and exports mathematical motion curves', () => {
    assert.strictEqual(fs.existsSync(tokensPath), true, 'openDesignMotionTokens.ts must exist');
    const content = fs.readFileSync(tokensPath, 'utf8');
    assert.match(content, /export const BEZIER_EXPRESSIVE/, 'exports BEZIER_EXPRESSIVE');
    assert.match(content, /export const BEZIER_KINETIC/, 'exports BEZIER_KINETIC');
    assert.match(content, /export const BEZIER_TECHNICAL/, 'exports BEZIER_TECHNICAL');
    assert.match(content, /0\.16,\s*1,\s*0\.3,\s*1/, 'expressive curve cubic-bezier params');
  });

  it('exports frame timecode conversion helpers and shot sequence timing', () => {
    const content = fs.readFileSync(tokensPath, 'utf8');
    assert.match(content, /export function secondsToFrames/, 'exports secondsToFrames helper');
    assert.match(content, /export function framesToSeconds/, 'exports framesToSeconds helper');
    assert.match(content, /export const SHOT_SEQUENCE/, 'exports SHOT_SEQUENCE');
    assert.match(content, /Macro Bevel/, 'includes Shot 01 Macro Bevel');
    assert.match(content, /Kinetic Arc/, 'includes Shot 02 Kinetic Arc');
    assert.match(content, /Exploded View/, 'includes Shot 03 Exploded View');
    assert.match(content, /Isometric Lock/, 'includes Shot 04 Isometric Lock');
  });

  it('verifies hyperframes.json includes synchronized camera shot sequences and easings', () => {
    assert.strictEqual(fs.existsSync(hyperframesPath), true, 'hyperframes.json must exist');
    const config = JSON.parse(fs.readFileSync(hyperframesPath, 'utf8'));
    assert.ok(Array.isArray(config.shots), 'hyperframes.json must define shots array');
    assert.strictEqual(config.shots.length, 4, 'must declare 4 camera shots');
    assert.strictEqual(config.shots[0].name, 'Macro Bevel');
    assert.strictEqual(config.shots[0].startFrame, 0);
    assert.strictEqual(config.shots[0].endFrame, 180);
    assert.strictEqual(config.shots[3].name, 'Isometric Lock');
    assert.strictEqual(config.shots[3].endFrame, 900);
    assert.ok(config.easings, 'must declare easings');
    assert.deepStrictEqual(config.easings.expressive, [0.16, 1, 0.3, 1]);
  });
});
