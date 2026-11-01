"""Actual mounted Capture acceptance using generated localhost contracts only.

Run only through the root-owned runtime collector with a pinned desktop build and
agent-browser CLI. This module is a scenario, never a passing runtime receipt.
No physical/clinical validation or positive research-comparison acceptance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from session_contract import sha256_file
from session_metadata_revision import read_metadata_state
from tools.verify_browser_isolation import _prepare_default_comparison_fixture, verify

D = "synthetic-race-d"
E = "synthetic-race-e"
SELECTOR = '[aria-label="Select active session"]'
CARD = ".uw-flight-check-card"
BOXES = CARD + ' input[type="checkbox"]'
METADATA = 'section[aria-label="Current effective session metadata"]'

TRANSPORT = r"""
(() => {
  if (window.__guidedCapture) throw Error('Capture transport already installed');
  const original = window.fetch;
  const state = window.__guidedCapture = {
    original, mode: 'normal', details: [], requests: [], card: null
  };
  window.fetch = async function(input, options={}) {
    const pathname = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
    const method = (options.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    state.requests.push({pathname, method});
    const response = await original.call(this, input, options);
    if (method !== 'GET' || pathname !== '/api/v1/sessions/synthetic-race-d') return response;
    const originalJSON = response.json.bind(response);
    response.json = async function() {
      const value = await originalJSON();
      const omitted = state.mode === 'omit-context';
      if (omitted) {
        delete value.metadata_context_sha256;
        if (value.metadata_state) delete value.metadata_state.context_sha256;
      }
      state.details.push({at: performance.now(), omitted,
        context: value.metadata_context_sha256 || null});
      return value;
    };
    return response;
  };
  return true;
})()
"""

SNAPSHOT = r"""
(() => {
  const card = document.querySelector('.uw-flight-check-card');
  const boxes = [...document.querySelectorAll('.uw-flight-check-card input[type="checkbox"]')];
  const wizard = document.querySelector('.uw-capture-wizard');
  const buttons = [...(wizard?.querySelectorAll('button') || [])];
  const native = buttons.filter(b => b.textContent.trim() === 'Open Capture Station GUI');
  return {
    selected: document.querySelector('[aria-label="Select active session"]')?.value,
    metadata: document.querySelector('section[aria-label="Current effective session metadata"]')?.textContent,
    boxes: boxes.map(b => ({checked: b.checked, disabled: b.disabled})),
    pill: card?.querySelector('.uw-pill')?.textContent.trim(),
    same_mount: !!card && card === window.__guidedCapture.card && card.isConnected,
    participant_blocked: !!wizard?.textContent.includes('PARTICIPANT_RECORDING_BLOCKED'),
    camera_requests: window.__cameraRequests,
    native_control_disabled: native.length === 1 && native[0].disabled,
    enabled_record_controls: buttons.filter(b => /^Record .* Webcam$/.test(b.textContent.trim()) && !b.disabled).length
  };
})()
"""


def require(condition, evidence):
    if not condition:
        raise AssertionError(evidence)


def run_checks(browser, evaluate, wait_for, service, output, checks, reopen):
    # Deliberately never reopen, retry the connection, or reload the session list.
    del reopen
    output = Path(output)
    originals = {}
    for sid in (D, E):
        folder = service.index.projects_root / sid
        paths = [folder / 'session.json', folder / 'Config.toml', *sorted((folder / 'raw').iterdir())]
        originals[sid] = {str(p.relative_to(folder)): sha256_file(p) for p in paths}
    initial = read_metadata_state(service.index, D)
    other = read_metadata_state(service.index, E)
    require(initial['status'] == other['status'] == 'AVAILABLE', (initial, other))
    wait_for("[...document.querySelector(" + json.dumps(SELECTOR) + ").options].some(o=>o.value===" + json.dumps(D) + ")")
    browser('select', SELECTOR, D)
    browser('snapshot', '-i')
    browser('find', 'role', 'button', 'click', '--name', 'Capture Phone and webcam footage', '--exact')
    wait_for("!!document.querySelector(" + json.dumps(CARD) + ")")
    require(evaluate(TRANSPORT) is True, 'transport installation failed')

    def record(name, **evidence):
        require(name not in checks, 'duplicate acceptance ID: ' + name)
        item = {'status': 'PASS', **evidence}
        (output / (name + '.json')).write_text(json.dumps(item, indent=2) + '\n', encoding='utf-8')
        checks[name] = item

    def remember_card():
        require(evaluate("!!(window.__guidedCapture.card=document.querySelector(" + json.dumps(CARD) + "))"), 'Capture card missing')

    def available(sid, context):
        wait_for("document.querySelector(" + json.dumps(SELECTOR) + ")?.value===" + json.dumps(sid) +
                 " && document.querySelector(" + json.dumps(METADATA) + ")?.textContent.includes('Current effective metadata: AVAILABLE')" +
                 " && document.querySelector(" + json.dumps(METADATA) + ")?.textContent.includes(" + json.dumps(context) + ")")

    def inspect(*, checked, disabled=False):
        state = evaluate(SNAPSHOT)
        require(state['same_mount'], state)
        require(len(state['boxes']) == 4, state)
        require(all(b == {'checked': checked, 'disabled': disabled} for b in state['boxes']), state)
        require(state['pill'] == ('Operator checklist reported' if checked else 'Checklist Incomplete'), state)
        require(state['participant_blocked'] and state['camera_requests'] == 0, state)
        require(state['native_control_disabled'] and state['enabled_record_controls'] == 0, state)
        return state

    def report_all():
        for index in range(1, 5):
            browser('check', CARD + f' .uw-checklist-grid > label:nth-child({index}) input[type="checkbox"]')
        wait_for("document.querySelector(" + json.dumps(CARD) + ")?.querySelector('.uw-pill')?.textContent.trim()==='Operator checklist reported'")
        return inspect(checked=True)

    def revise(field=None, value=None):
        before = read_metadata_state(service.index, D)
        metadata = dict(before['metadata'])
        if field is not None:
            metadata[field] = value
        service.publish_metadata_revision(D, {
            'metadata': metadata, 'expected_origin_sha256': before['origin']['sha256'],
            'expected_head_sha256': before['head']['sha256'] if before['head'] else None,
            'operation_id': uuid4().hex, 'reason_code': 'operator_correction', 'confirm': True,
        })
        after = read_metadata_state(service.index, D)
        require(after['status'] == 'AVAILABLE' and after['metadata'] == metadata, after)
        require(after['context_sha256'] != before['context_sha256'], (before, after))
        available(D, after['context_sha256'])
        state = inspect(checked=False)
        return before, after, state

    try:
        available(D, initial['context_sha256'])
        remember_card()
        inspect(checked=False)
        record('GUIDED_BROWSER_01_mounted_available_reported', state=report_all(),
               metadata_context=initial['context_sha256'])

        # A consumed ordinary detail response at least 3.5 seconds after the report
        # distinguishes polling from a cached DOM read. The saved DOM node must survive.
        evaluate('window.__guidedCapture.pollStart=performance.now()')
        wait_for("window.__guidedCapture.details.some(d=>!d.omitted && d.context===" +
                 json.dumps(initial['context_sha256']) + " && d.at>=window.__guidedCapture.pollStart+3500)")
        record('GUIDED_BROWSER_02_same_context_poll_preserves', state=inspect(checked=True),
               poll=evaluate('window.__guidedCapture.details.at(-1)'), minimum_elapsed_ms=3500)

        before, current, state = revise('protocol_id', 'TEST_ONLY-browser-revised-protocol')
        record('GUIDED_BROWSER_03_protocol_id_revision_resets', state=state,
               before_context=before['context_sha256'], after_context=current['context_sha256'],
               protocol_id=current['metadata']['protocol_id'])
        report_all()
        before, current, state = revise('protocol_version', 'TEST_ONLY-browser-v2')
        record('GUIDED_BROWSER_04_protocol_version_revision_resets', state=state,
               before_context=before['context_sha256'], after_context=current['context_sha256'],
               protocol_version=current['metadata']['protocol_version'])
        report_all()
        before, current, state = revise()
        require(before['metadata'] == current['metadata'], 'same-value revision changed effective metadata')
        record('GUIDED_BROWSER_05_same_values_new_context_resets', state=state,
               effective_metadata_unchanged=True, before_context=before['context_sha256'],
               after_context=current['context_sha256'])
        report_all()

        evaluate("window.__guidedCapture.mode='omit-context'")
        wait_for("window.__guidedCapture.details.at(-1)?.omitted===true && document.querySelector(" +
                 json.dumps(METADATA) + ")?.textContent.includes('Current effective metadata: UNAVAILABLE')")
        record('GUIDED_BROWSER_06_missing_context_fails_closed', state=inspect(checked=False, disabled=True),
               omitted_context_response_consumed=True)
        evaluate("window.__guidedCapture.mode='normal'")
        available(D, current['context_sha256'])
        require(evaluate('window.__guidedCapture.details.at(-1)?.omitted===false'), 'restoration was not consumed')
        record('GUIDED_BROWSER_07_restoration_cannot_resurrect', state=inspect(checked=False),
               restored_context=current['context_sha256'])
        report_all()

        browser('select', SELECTOR, E)
        available(E, other['context_sha256'])
        require(not evaluate(SNAPSHOT)['same_mount'], 'session transition did not mount the selected Capture')
        remember_card()
        e_reset = inspect(checked=False)
        report_all()
        browser('select', SELECTOR, D)
        available(D, current['context_sha256'])
        require(not evaluate(SNAPSHOT)['same_mount'], 'return transition reused the other session Capture')
        remember_card()
        record('GUIDED_BROWSER_08_d_e_d_no_stale_report', e_state=e_reset,
               d_state=inspect(checked=False), d_context=current['context_sha256'])

        after_originals = {}
        for sid, paths in originals.items():
            folder = service.index.projects_root / sid
            after_originals[sid] = {name: sha256_file(folder / name) for name in paths}
        require(originals == after_originals, 'immutable fixture originals changed')
        requests = evaluate('window.__guidedCapture.requests')
        require(all(item['method'] in ('GET', 'HEAD') for item in requests), requests)
        console = browser('console')
        page_errors = browser('errors')
        require(isinstance(console.get('messages'), list), {'unsupported_console_schema': console})
        require(all(isinstance(item, dict) and isinstance(item.get('type'), str)
                    for item in console['messages']), {'unsupported_console_message_schema': console})
        require(not [item for item in console['messages'] if item['type'].lower() == 'error'], console)
        require(isinstance(page_errors.get('errors'), list) and not page_errors['errors'], page_errors)
        record('GUIDED_BROWSER_09_guards_originals_console', state=inspect(checked=False),
               original_sha256=after_originals, requests=requests, console=console, page_errors=page_errors,
               evidence_kind='GENERATED_CONTRACT_FIXTURE_ONLY', physical_accuracy_verified=False,
               clinical_validation='UNVERIFIED', research_comparison_acceptance='NOT_CLAIMED')
    finally:
        primary = sys.exc_info()[1]
        try:
            require(evaluate("(() => {const s=window.__guidedCapture;if(!s)return false;window.fetch=s.original;delete window.__guidedCapture;return true;})()") is True,
                    'Capture transport restoration failed')
        except Exception as cleanup_error:
            if primary is None:
                raise
            primary.add_note('Capture transport cleanup failed: ' + str(cleanup_error))


def main():
    if not __debug__:
        raise RuntimeError('Optimized Python would disable assertions in the reused verifier')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--frontend-dist', type=Path, required=True)
    parser.add_argument('--agent-browser-executable', type=Path, required=True)
    parser.add_argument('--agent-browser-sha256', required=True)
    args = parser.parse_args()
    verify(args.out, scenario=run_checks, frontend_dist=args.frontend_dist,
           fixture=_prepare_default_comparison_fixture,
           agent_browser_executable=args.agent_browser_executable,
           agent_browser_sha256=args.agent_browser_sha256)


if __name__ == '__main__':
    main()
