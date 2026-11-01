import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformSync } from 'esbuild';

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

function moduleAt(filename, overrides = {}) {
  const file = path.resolve(directory, filename);
  const module = { exports: {} };
  const source = transformSync(fs.readFileSync(file, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(
    name => overrides[name] || (name.startsWith('.') ? moduleAt(path.resolve(path.dirname(file), name), overrides) : require(name)),
    module,
    module.exports
  );
  return module.exports;
}

function nodes(tree, predicate, out = []) {
  if (tree && typeof tree === 'object') {
    if (predicate(tree)) out.push(tree);
    React.Children.forEach(tree.props?.children, child => nodes(child, predicate, out));
  }
  return out;
}

function mounted(filename, props, overrides = {}) {
  const slots = [], effects = [];
  let index = 0, pending = [];
  const react = {
    ...React,
    useState(initial) {
      const i = index++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
    },
    useRef(value) {
      const i = index++;
      if (!(i in slots)) slots[i] = { current: value };
      return slots[i];
    },
    useMemo(fn) {
      index++;
      return fn();
    },
    useId() {
      const i = index++;
      return 'test-dialog-id-' + i;
    },
    useEffect(fn, deps) {
      const i = index++, previous = effects[i];
      if (!previous || !deps || deps.some((value, n) => !Object.is(value, previous.deps?.[n]))) {
        pending.push(() => {
          previous?.cleanup?.();
          effects[i] = { deps, cleanup: fn() };
        });
      }
    },
  };
  const Component = moduleAt(filename, { react, ...overrides }).default;
  return {
    render(next = props) {
      props = next;
      index = 0;
      pending = [];
      return Component(props);
    },
    effects() {
      const current = pending;
      pending = [];
      for (const effect of current) effect();
    },
    unmount() {
      for (const effect of effects) effect?.cleanup?.();
    },
  };
}

const sampleSummary = {
  exerciseType: 'squats',
  totalReps: 5,
  validReps: 4,
  averageDepth: 85,
  bestDepth: 95,
  targetDepth: 80,
  averageSymmetry: 90,
  durationSeconds: 45,
  faultsLog: [],
};

test('LiveSetSummaryModal has empty initial patientId, neutral placeholder, and prevents generic default ID', () => {
  let savedId = null;
  const app = mounted('./LiveSetSummaryModal.jsx', {
    summary: sampleSummary,
    onSaveToSessions: (id) => { savedId = id; },
    demoMode: false,
  });

  const tree = app.render();
  const input = nodes(tree, x => x.type === 'input')[0];
  assert.ok(input, 'Patient ID input should be rendered when onSaveToSessions is provided');

  // Verify neutral placeholder and no dormant default state
  assert.equal(input.props.value, '', 'Initial patientId must be empty string');
  assert.equal(input.props.placeholder, 'e.g. Enter subject/record ID', 'Placeholder must be neutral');
  assert.notEqual(input.props.value, 'PT-PATIENT-01', 'Dormant generic default ID must be removed');
  assert.ok(!input.props.placeholder.includes('PT-PATIENT-01'), 'Placeholder must not suggest PT-PATIENT-01');

  // Save button must start disabled when patient ID is empty
  const saveBtn = nodes(tree, x => x.type === 'button' && x.props?.children?.includes?.('Save to KineLab Sessions'))[0];
  assert.ok(saveBtn, 'Save button should be rendered');
  assert.equal(saveBtn.props.disabled, true, 'Save button must be disabled when patientId is empty');

  // Clicking disabled save button must not invoke callback
  saveBtn.props.onClick();
  assert.equal(savedId, null, 'Save callback must not be invoked when patientId is empty');
});

test('LiveSetSummaryModal prevents blank/whitespace input from invoking save callback', () => {
  let savedId = null;
  const app = mounted('./LiveSetSummaryModal.jsx', {
    summary: sampleSummary,
    onSaveToSessions: (id) => { savedId = id; },
    demoMode: false,
  });

  let tree = app.render();
  const input = nodes(tree, x => x.type === 'input')[0];

  // User enters only spaces
  input.props.onChange({ target: { value: '     ' } });
  tree = app.render();

  const saveBtn = nodes(tree, x => x.type === 'button' && x.props?.children?.includes?.('Save to KineLab Sessions'))[0];
  assert.equal(saveBtn.props.disabled, true, 'Save button must be disabled for whitespace-only input');

  saveBtn.props.onClick();
  assert.equal(savedId, null, 'Save callback must not be invoked for whitespace-only input');
});

test('LiveSetSummaryModal enables save for valid input and passes trimmed patientId', () => {
  let savedId = null;
  const app = mounted('./LiveSetSummaryModal.jsx', {
    summary: sampleSummary,
    onSaveToSessions: (id) => { savedId = id; },
    demoMode: false,
  });

  let tree = app.render();
  const input = nodes(tree, x => x.type === 'input')[0];

  // User enters ID with surrounding whitespace
  input.props.onChange({ target: { value: '   SUBJ-2026-X   ' } });
  tree = app.render();

  const saveBtn = nodes(tree, x => x.type === 'button' && x.props?.children?.includes?.('Save to KineLab Sessions'))[0];
  assert.equal(saveBtn.props.disabled, false, 'Save button must be enabled when valid ID is entered');

  saveBtn.props.onClick();
  assert.equal(savedId, 'SUBJ-2026-X', 'Save callback must receive trimmed patientId');
});

test('LiveSetSummaryModal handles Escape key to trigger onClose and traps Tab focus', () => {
  let closed = 0;
  const trigger = { focus() {} };
  const first = { disabled: false, hidden: false, focus() { doc.activeElement = this; } };
  const last = { disabled: false, hidden: false, focus() { doc.activeElement = this; } };
  let showCalls = 0, closeCalls = 0;
  const modal = {
    open: false,
    querySelectorAll: () => [first, last],
    contains: el => el === first || el === last,
    querySelector: () => first,
    focus() { doc.activeElement = this; },
    showModal() { showCalls++; this.open = true; },
    close() { closeCalls++; this.open = false; },
  };

  const previousDocument = globalThis.document;
  const doc = { activeElement: trigger };
  globalThis.document = doc;

  try {
    const app = mounted('./LiveSetSummaryModal.jsx', {
      summary: sampleSummary,
      onClose: () => closed++,
    });

    const tree = app.render();
    const dialog = nodes(tree, x => x.type === 'dialog')[0];
    assert.ok(dialog, 'Native dialog must be rendered');
    assert.equal(dialog.props['aria-modal'], true);

    dialog.props.ref.current = modal;
    app.effects();
    assert.equal(showCalls, 1, 'showModal must be called on mount');

    // Test Escape key
    let escapePrevented = false;
    dialog.props.onKeyDown({
      key: 'Escape',
      preventDefault() { escapePrevented = true; },
    });
    assert.equal(escapePrevented, true, 'Escape must call preventDefault');
    assert.equal(closed, 1, 'Escape must call onClose');

    // Test Tab wrap: forward at last element wraps to first
    doc.activeElement = last;
    let tabPrevented = false;
    dialog.props.onKeyDown({
      key: 'Tab',
      shiftKey: false,
      preventDefault() { tabPrevented = true; },
    });
    assert.equal(tabPrevented, true);
    assert.equal(doc.activeElement, first, 'Tab from last element should wrap to first');

    // Test Shift+Tab wrap: backward at first element wraps to last
    doc.activeElement = first;
    let shiftTabPrevented = false;
    dialog.props.onKeyDown({
      key: 'Tab',
      shiftKey: true,
      preventDefault() { shiftTabPrevented = true; },
    });
    assert.equal(shiftTabPrevented, true);
    assert.equal(doc.activeElement, last, 'Shift+Tab from first element should wrap to last');

    app.unmount();
    assert.equal(closeCalls, 1, 'close must be called on unmount');
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test('LiveSetSummaryModal preserves server human-save refusal notice when onSaveToSessions is undefined or demoMode is true', () => {
  const LiveSetSummaryModal = moduleAt('./LiveSetSummaryModal.jsx').default;

  // Case 1: onSaveToSessions is undefined
  const htmlNoCallback = renderToStaticMarkup(
    React.createElement(LiveSetSummaryModal, {
      summary: sampleSummary,
      onSaveToSessions: undefined,
      demoMode: false,
    })
  );
  assert.ok(
    htmlNoCallback.includes('SYNTHETIC TEST ONLY. These metrics are generated animation, not measured human movement. Server saving and clinical reporting are unavailable.'),
    'Refusal notice must be rendered when onSaveToSessions is undefined'
  );
  assert.ok(!htmlNoCallback.includes('PATIENT / SUBJECT RECORD ID'), 'Patient input field must NOT be rendered when onSaveToSessions is undefined');
  assert.ok(!htmlNoCallback.includes('Save to KineLab Sessions'), 'Save button must NOT be rendered when onSaveToSessions is undefined');

  // Case 2: demoMode is true
  const htmlDemo = renderToStaticMarkup(
    React.createElement(LiveSetSummaryModal, {
      summary: sampleSummary,
      onSaveToSessions: () => {},
      demoMode: true,
    })
  );
  assert.ok(
    htmlDemo.includes('SYNTHETIC TEST ONLY. These metrics are generated animation, not measured human movement. Server saving and clinical reporting are unavailable.'),
    'Refusal notice must be rendered when demoMode is true'
  );
  assert.ok(!htmlDemo.includes('PATIENT / SUBJECT RECORD ID'), 'Patient input field must NOT be rendered when demoMode is true');
  assert.ok(!htmlDemo.includes('Save to KineLab Sessions'), 'Save button must NOT be rendered when demoMode is true');
});

test('R17 summary exposes the same enabled Stop activity callback inside its native dialog and forbids restart after stop',()=>{
 let stopped=0;const props={summary:sampleSummary,onStopActivity:()=>{stopped++;},activityStopped:false};
 const app=mounted('./LiveSetSummaryModal.jsx',props);
 const stop=nodes(app.render(),node=>node.type==='button'&&node.props.children==='Stop activity')[0];
 assert.ok(stop,'The modal must not make the only stop action inert outside the dialog');
 assert.notEqual(stop.props.disabled,true);stop.props.onClick();assert.equal(stopped,1);
 const tree=app.render({...props,activityStopped:true});
 const restart=nodes(tree,node=>node.type==='button'&&node.props.children==='Start New Set')[0];
 assert.equal(restart.props.disabled,true);
 assert.ok(nodes(tree,node=>node.props?.role==='status').some(node=>JSON.stringify(node.props.children).includes('clinical next-step approval is PENDING')));
 app.unmount();
});
