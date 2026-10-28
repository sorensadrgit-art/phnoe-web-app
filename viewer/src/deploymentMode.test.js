import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveDeploymentSurface } from './deploymentMode.js';

test('desktop launcher stays on the complete local application', () => {
  assert.equal(resolveDeploymentSurface('127.0.0.1'), 'desktop');
  assert.equal(resolveDeploymentSurface('localhost'), 'desktop');
  assert.equal(resolveDeploymentSurface('::1'), 'desktop');
  assert.equal(resolveDeploymentSurface('[::1]'), 'desktop');
});

test('hosted sites use a deliberately limited browser demo', () => {
  assert.equal(resolveDeploymentSurface('kinelab-pt.vercel.app'), 'web-demo');
  assert.equal(resolveDeploymentSurface('kinelab.example.org'), 'web-demo');
  assert.equal(resolveDeploymentSurface('192.168.1.50'), 'web-demo');
});
