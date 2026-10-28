import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

describe('Task 5: Hero Film Composition & Sequencer Specs', () => {
  it('declares 15-second 1440p60 composition parameters in BiomechHeroFilm', async () => {
    const compPath = path.resolve('motion-source/biomechanical-hero/src/compositions/BiomechHeroFilm.mjs');
    const { BIOMECH_HERO_CONFIG, FILM_SHOTS } = await import(pathToFileURL(compPath).href);

    assert.strictEqual(BIOMECH_HERO_CONFIG.fps, 60, 'fps must be 60');
    assert.strictEqual(BIOMECH_HERO_CONFIG.durationInFrames, 900, 'duration must be 900 frames (15s @ 60fps)');
    assert.strictEqual(BIOMECH_HERO_CONFIG.width, 2560, 'width must be 2560 (1440p)');
    assert.strictEqual(BIOMECH_HERO_CONFIG.height, 1440, 'height must be 1440 (1440p)');

    assert.strictEqual(FILM_SHOTS.length, 4, 'must have exactly 4 cinematic shots');
    assert.strictEqual(FILM_SHOTS[0].id, 'shot-01-macro-bevel');
    assert.strictEqual(FILM_SHOTS[1].id, 'shot-02-kinetic-arc');
    assert.strictEqual(FILM_SHOTS[2].id, 'shot-03-exploded-view');
    assert.strictEqual(FILM_SHOTS[3].id, 'shot-04-isometric-lock');
  });

  it('implements TelemetryOverlay and Root composition registry', () => {
    const overlayPath = path.resolve('motion-source/biomechanical-hero/src/components/TelemetryOverlay.tsx');
    const rootPath = path.resolve('motion-source/biomechanical-hero/src/Root.tsx');

    assert.strictEqual(fs.existsSync(overlayPath), true, 'TelemetryOverlay.tsx must exist');
    assert.strictEqual(fs.existsSync(rootPath), true, 'Root.tsx must exist');

    const overlaySource = fs.readFileSync(overlayPath, 'utf8');
    assert.match(overlaySource, /tabular-nums/, 'overlay must use tabular-nums');
    assert.match(overlaySource, /font-mono/, 'overlay must use monospace font');

    const rootSource = fs.readFileSync(rootPath, 'utf8');
    assert.match(rootSource, /Composition/, 'Root must register Remotion Composition');
  });
});
