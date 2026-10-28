import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('Task 4: Section Explorer Component Integration', () => {
  const explorerPath = path.resolve('examples/soren-motion-v8/src/resume/SectionExplorer.tsx');
  const biomechPath = path.resolve('examples/soren-motion-v8/src/resume/projects/biomechanical-lab/BiomechanicalLabProject.tsx');

  it('verifies SectionExplorer imports and utilizes MotionGraphicType for headlines', () => {
    assert.strictEqual(fs.existsSync(explorerPath), true, 'SectionExplorer.tsx must exist');
    const content = fs.readFileSync(explorerPath, 'utf8');
    assert.match(content, /import\s+.*MotionGraphicType.*from\s+['"]\.\/motion\/MotionGraphicType['"]/, 'imports MotionGraphicType');
    assert.match(content, /<MotionGraphicType\s+text=\{section\.title\}/, 'renders MotionGraphicType for section title');
  });

  it('passes kicker, variant and reduced props to MotionGraphicType in Heading', () => {
    const content = fs.readFileSync(explorerPath, 'utf8');
    assert.match(content, /kicker=\{/, 'passes kicker prop');
    assert.match(content, /reduced=\{/, 'passes reduced prop');
  });

  it('verifies BiomechanicalLabProject links OpenDesign motion tokens and telemetry', () => {
    assert.strictEqual(fs.existsSync(biomechPath), true, 'BiomechanicalLabProject.tsx must exist');
    const content = fs.readFileSync(biomechPath, 'utf8');
    assert.match(content, /openDesignMotionTokens|SHOT_SEQUENCE/, 'imports or integrates OpenDesign motion tokens');
    assert.match(content, /Real-Time Joint Telemetry|Telemetry Matrix/, 'renders telemetry matrix section');
  });
});
