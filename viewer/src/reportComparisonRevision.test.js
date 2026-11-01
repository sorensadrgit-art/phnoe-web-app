import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { transformSync } from 'esbuild';

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const fixturePath = process.env.KINELAB_REVISION_CASE_FILE || path.join(directory, 'fixtures/comparisonRevision.generated.json');
const cases = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
assert.equal(cases.test_only, true);
assert.equal(cases.physical_accuracy_verified, false);

function moduleAt(filename, react) {
  const file = path.resolve(directory, filename), module = { exports: {} };
  const source = transformSync(fs.readFileSync(file, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
  new Function('require', 'module', 'exports', source)(name => name === 'react' ? react : name.startsWith('.')
    ? moduleAt(path.resolve(path.dirname(file), name), react) : require(name), module, module.exports);
  return module.exports;
}
function nodes(tree, predicate, result = []) {
  if (tree && typeof tree === 'object') {
    if (predicate(tree)) result.push(tree);
    React.Children.forEach(tree.props?.children, child => nodes(child, predicate, result));
  }
  return result;
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return tree && typeof tree === 'object' ? React.Children.toArray(tree.props?.children).map(text).join('') : '';
}
function studio(onCompareSessions) {
  const slots = [], effects = [];
  let index = 0, pending = [], props = { sessions: structuredClone(cases.before_rows), reports: [],
    selectedSession: 'a', busy: false, onSelectSession() {}, onCompareSessions };
  const react = { ...React,
    useState(initial) { const i = index++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(initial) { const i = index++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useMemo(fn) { index++; return fn(); },
    useEffect(fn, deps) { const i = index++, previous = effects[i];
      if (!previous || deps.some((value, n) => !Object.is(value, previous.deps[n]))) {
        pending.push(() => { previous?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; });
      }
    },
  };
  const Component = moduleAt('./ReportStudio.jsx', react).default;
  const view = {
    tree: null,
    render(next = {}) { props = { ...props, ...next }; index = 0; pending = []; view.tree = Component(props); return view.tree; },
    settle(next) { view.render(next); const current = pending; pending = []; current.forEach(effect => effect()); return view.render(); },
    choose(id) { nodes(view.tree, node => node.type === 'select' && /Select compatible session/.test(text(node)))[0]
      .props.onChange({ target: { value: id } }); return view.settle(); },
    button() { return nodes(view.tree, node => node.type === 'button' && /^(Compare|Comparing\.\.\.)$/.test(text(node).trim()))[0]; },
    compare() { return view.button().props.onClick(); },
    result() { return nodes(view.tree, node => node.props?.className?.split(' ').includes('uw-compare-result'))[0]; },
  };
  view.settle(); view.choose('b'); return view;
}

for (const [name, rows] of Object.entries(cases.changes)) {
  test(`actual API ${name} revision clears cached comparison before effects`, async () => {
    const view = studio(async () => structuredClone(cases.comparison));
    await view.compare(); view.settle(); assert.ok(view.result());
    view.render({ sessions: structuredClone(rows) });
    assert.equal(view.result(), undefined);
    view.settle(); assert.equal(view.result(), undefined);
  });
  test(`actual API ${name} revision discards a previously pending response`, async () => {
    let resolve;
    const view = studio(() => new Promise(done => { resolve = done; }));
    const request = view.compare();
    view.render({ sessions: structuredClone(rows) });
    resolve(structuredClone(cases.comparison)); await request;
    view.settle(); assert.equal(view.result(), undefined);
  });
}
test('identical fully observed actual API revision retains displayed comparison', async () => {
  const view = studio(async () => structuredClone(cases.comparison));
  await view.compare(); view.settle(); assert.ok(view.result());
  view.settle({ sessions: structuredClone(cases.equal_rows) }); assert.ok(view.result());
});
for (const invalid of [null, { schema: 'kinelab.comparison-source-observation.v1', status: 'UNAVAILABLE', token: null,
  reason: 'COMPARISON_SOURCE_LIMIT', evidence_verified: false }]) {
  test(`missing or unavailable observation cannot retain favorable comparison (${invalid?.status || 'missing'})`, async () => {
    const view = studio(async () => structuredClone(cases.comparison));
    await view.compare(); view.settle(); assert.ok(view.result());
    const rows = structuredClone(cases.before_rows);
    if (invalid) rows[1].research_source_revision = invalid;
    else delete rows[1].research_source_revision;
    view.render({ sessions: rows }); assert.equal(view.result(), undefined);
    view.settle(); assert.equal(view.button().props.disabled, true);
  });
}
