import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('Task 4: Project 05 Section Integration & Attribution', () => {
  it('implements accessible BiomechanicalLabProject modal presentation', () => {
    const modalPath = path.resolve('examples/soren-motion-v8/src/resume/projects/biomechanical-lab/BiomechanicalLabProject.tsx');
    assert.strictEqual(fs.existsSync(modalPath), true, 'BiomechanicalLabProject.tsx must exist');
    const source = fs.readFileSync(modalPath, 'utf8');

    assert.match(source, /role="dialog"/, 'modal must have role="dialog"');
    assert.match(source, /aria-modal="true"/, 'modal must have aria-modal="true"');
    assert.match(source, /Escape/, 'modal must handle Escape key navigation');
    assert.match(source, /KinematicCanvas/, 'modal must embed KinematicCanvas');
  });

  it('declares Project 05 in SectionExplorer project catalog', () => {
    const explorerPath = path.resolve('examples/soren-motion-v8/src/resume/SectionExplorer.tsx');
    assert.strictEqual(fs.existsSync(explorerPath), true, 'SectionExplorer.tsx must exist');
    const source = fs.readFileSync(explorerPath, 'utf8');

    assert.match(source, /biomech-lab/, 'SectionExplorer must register biomech-lab project ID');
    assert.match(source, /Biomechanical Cybernetic Lab/, 'SectionExplorer must display project title');
  });

  it('documents full CC BY 4.0 attribution in BIOMECHANICAL_LAB_CREDITS.md', () => {
    const creditsPath = path.resolve('docs/attribution/BIOMECHANICAL_LAB_CREDITS.md');
    assert.strictEqual(fs.existsSync(creditsPath), true, 'BIOMECHANICAL_LAB_CREDITS.md must exist');
    const content = fs.readFileSync(creditsPath, 'utf8');

    assert.match(content, /BodyParts3D/, 'must credit BodyParts3D');
    assert.match(content, /DBCLS/, 'must credit DBCLS');
    assert.match(content, /NVIDIA SimReady Assets/, 'must credit NVIDIA SimReady Assets');
    assert.match(content, /CC BY 4\.0/, 'must specify CC BY 4.0 license');
  });
});
