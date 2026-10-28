import { describe, it } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

describe('Task 2: Kinematic Telemetry Calculations', () => {
  it('interpolates smooth flexion and extension curves', async () => {
    const modulePath = path.resolve('examples/soren-motion-v8/src/resume/projects/biomechanical-lab/telemetry-data.mjs');
    const { getKinematicFrame, KINEMATIC_PHASES } = await import(pathToFileURL(modulePath).href);

    const start = getKinematicFrame(0);
    const mid = getKinematicFrame(0.5);
    const end = getKinematicFrame(1.0);

    assert.ok(Math.abs(start.jointAngleDeg - 0) < 1, 'start angle must be approx 0 deg');
    assert.ok(mid.jointAngleDeg > 60, 'mid flexion angle must be > 60 deg');
    assert.ok(Math.abs(end.jointAngleDeg - 0) < 1, 'end angle must return to approx 0 deg');

    assert.strictEqual(Array.isArray(mid.endEffectorPosition), true, 'endEffectorPosition must be an array');
    assert.strictEqual(mid.endEffectorPosition.length, 3, 'endEffectorPosition must have 3 coordinates');
    assert.ok(mid.angularVelocity !== undefined, 'angularVelocity must be defined');
    assert.ok(mid.torqueNm !== undefined, 'torqueNm must be defined');
    assert.ok(KINEMATIC_PHASES.length >= 4, 'must have at least 4 clinical movement phases');
  });
});
