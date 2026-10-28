import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('Task 6: Full-Suite Verification & Build Audit', () => {
  it('validates binary GLB asset integrity and magic headers', () => {
    const models = [
      'examples/soren-motion-v8/public/assets/models/simready-franka-arm.opt.glb',
      'examples/soren-motion-v8/public/assets/models/biomech-joint-assembly.opt.glb'
    ];

    for (const modelPath of models) {
      const fullPath = path.resolve(modelPath);
      assert.strictEqual(fs.existsSync(fullPath), true, `${modelPath} must exist`);
      const buffer = fs.readFileSync(fullPath);
      assert.ok(buffer.length > 20, `${modelPath} must have valid size`);
      const magic = buffer.toString('utf8', 0, 4);
      assert.strictEqual(magic, 'glTF', `${modelPath} must begin with glTF binary magic`);
    }
  });

  it('validates documentation and attribution integrity', () => {
    const readmePath = path.resolve('examples/soren-motion-v8/README.md');
    const creditsPath = path.resolve('docs/attribution/BIOMECHANICAL_LAB_CREDITS.md');

    assert.strictEqual(fs.existsSync(readmePath), true, 'README.md must exist');
    assert.strictEqual(fs.existsSync(creditsPath), true, 'BIOMECHANICAL_LAB_CREDITS.md must exist');

    const readme = fs.readFileSync(readmePath, 'utf8');
    assert.match(readme, /Biomechanical Cybernetic Lab/, 'README must document project');
    assert.match(readme, /CC BY 4\.0/, 'README must cite CC BY 4.0');
  });

  it('verifies all implementation files are present across codebase', () => {
    const requiredFiles = [
      'motion-source/biomechanical-hero/hyperframes.json',
      'motion-source/biomechanical-hero/meta.json',
      'motion-source/biomechanical-hero/index.html',
      'motion-source/biomechanical-hero/src/Root.tsx',
      'motion-source/biomechanical-hero/src/compositions/BiomechHeroFilm.mjs',
      'motion-source/biomechanical-hero/src/compositions/BiomechHeroFilm.tsx',
      'motion-source/biomechanical-hero/src/components/TelemetryOverlay.tsx',
      'examples/soren-motion-v8/src/resume/SectionExplorer.tsx',
      'examples/soren-motion-v8/src/resume/projects/biomechanical-lab/BiomechanicalLabProject.tsx',
      'examples/soren-motion-v8/src/resume/projects/biomechanical-lab/KinematicCanvas.tsx',
      'examples/soren-motion-v8/src/resume/projects/biomechanical-lab/KinematicShader.ts',
      'examples/soren-motion-v8/src/resume/projects/biomechanical-lab/telemetry-data.ts',
      'examples/soren-motion-v8/src/resume/projects/biomechanical-lab/tokens.css',
      'docs/attribution/BIOMECHANICAL_LAB_CREDITS.md'
    ];

    for (const relPath of requiredFiles) {
      assert.strictEqual(fs.existsSync(path.resolve(relPath)), true, `Required file ${relPath} must exist`);
    }
  });
});
