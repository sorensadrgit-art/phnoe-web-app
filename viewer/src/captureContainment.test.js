import {after, before, test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

let vite, Wizard;
before(async () => {
  vite = await createServer({root: fileURLToPath(new URL('..', import.meta.url)),
    server: {middlewareMode: true, hmr: false, ws: false}, optimizeDeps: {noDiscovery: true, include: []}, appType: 'custom'});
  Wizard = (await vite.ssrLoadModule('/src/GuidedCaptureWizard.jsx')).default;
});

test('session capture entry is unconditionally disabled with a visible reason', () => {
  const source = readFileSync(new URL('./UnifiedApp.jsx', import.meta.url), 'utf8');
  const captureButton = source.split('\n').find(line => line.includes('>Open Capture Station</button>'));
  assert.ok(captureButton, 'The session capture entry must be accounted for');
  assert.match(captureButton, /\sdisabled(?:\s|>)/);
  assert.doesNotMatch(captureButton, /\bonClick\b/);
  assert.match(source, /<p role="status" className="uw-help">PARTICIPANT_RECORDING_BLOCKED: recording requires an independently approved privacy, consent, physical-validation and clinical-use protocol\.<\/p>/);
});
after(async () => { await vite?.close(); });

test('raw capture controls disclose containment and cannot start a recording', () => {
  const html = renderToStaticMarkup(React.createElement(Wizard, {
    selectedSession: 'empty-test-session', activeSession: {kind: 'real', status: 'draft'},
    detail: {roles: [{role: 'cam02_trial', camera: 'webcam', record_seconds: 12}]},
    onOpenNative() {}, onStartCapture() {},
  }));
  assert.match(html, /PARTICIPANT_RECORDING_BLOCKED/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Open Capture Station GUI<\/button>/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Record 12s Webcam<\/button>/);
});
