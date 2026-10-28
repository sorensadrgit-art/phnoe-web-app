import { describe, it } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

describe('Task 7: Kinematic Monism Fine Art Trilogy & Folio Integration', () => {
  it('validates binary integrity of all three fine art PNG plates', () => {
    const plates = [
      'examples/soren-motion-v8/public/assets/art/plate-01-translation-geometry.png',
      'examples/soren-motion-v8/public/assets/art/plate-02-tibiofemoral-kinematics.png',
      'examples/soren-motion-v8/public/assets/art/plate-03-cybernetic-manipulation.png'
    ];

    for (const relPath of plates) {
      const fullPath = path.resolve(relPath);
      assert.strictEqual(fs.existsSync(fullPath), true, `${relPath} must exist`);
      const buffer = fs.readFileSync(fullPath);
      assert.ok(buffer.length > 500000, `${relPath} must be a high-resolution print (size: ${buffer.length})`);
      // PNG magic number: 0x89 0x50 0x4E 0x47 0x0D 0x0A 0x1A 0x0A
      assert.strictEqual(buffer[0], 0x89, 'PNG magic byte 0');
      assert.strictEqual(buffer.toString('ascii', 1, 4), 'PNG', 'PNG header ASCII');
    }
  });

  it('validates multi-page archival folio PDF document', () => {
    const pdfPath = path.resolve('examples/soren-motion-v8/public/assets/art/kinematic-monism-trilogy.pdf');
    assert.strictEqual(fs.existsSync(pdfPath), true, 'kinematic-monism-trilogy.pdf must exist');
    const buffer = fs.readFileSync(pdfPath);
    assert.ok(buffer.length > 1000000, 'trilogy PDF must contain high-res vector plates');
    const header = buffer.toString('utf8', 0, 8);
    assert.match(header, /%PDF-/, 'must be a valid PDF document');
  });

  it('confirms BiomechanicalLabProject modal embeds Archival Folio tab and downloads', () => {
    const modalPath = path.resolve('examples/soren-motion-v8/src/resume/projects/biomechanical-lab/BiomechanicalLabProject.tsx');
    assert.strictEqual(fs.existsSync(modalPath), true, 'BiomechanicalLabProject.tsx must exist');
    const source = fs.readFileSync(modalPath, 'utf8');

    assert.match(source, /activeTab === 'folio'/, 'must provide folio tab active state');
    assert.match(source, /Archival Folio/, 'must render Archival Folio tab header');
    assert.match(source, /kinematic-monism-trilogy\.pdf/, 'must link multi-page PDF download');
    assert.match(source, /Plate VIII/, 'must include Plate VIII');
    assert.match(source, /Plate IX/, 'must include Plate IX');
    assert.match(source, /Plate X/, 'must include Plate X');
  });

  it('validates design philosophy manifesto documentation', () => {
    const manifestoPath = path.resolve('docs/design-philosophy/KINEMATIC_MONISM.md');
    assert.strictEqual(fs.existsSync(manifestoPath), true, 'KINEMATIC_MONISM.md must exist');
    const text = fs.readFileSync(manifestoPath, 'utf8');

    assert.match(text, /Kinematic Monism/, 'must articulate Kinematic Monism');
    assert.match(text, /master-level execution/, 'must emphasize craftsmanship');
    assert.match(text, /meticulous craftsmanship/, 'must emphasize meticulous care');
  });
});
