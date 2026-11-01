"""Generated TEST_ONLY actual-HTTP R08 contract; no future module imported at setup.

The existing public route is exercised first, so absent implementation is a
business assertion, never missing-new-module/import credit. Codec-only fixture
observation is doubled by the established report fixture; no device/participant.
"""
import copy
import hashlib
import http.client
import io
import json
import sqlite3
import unittest
import zipfile
from unittest.mock import patch

import test_report_context_api as base

SID = base.SID
TOKEN = base.TOKEN
STORE = '.kinelab-evidence-exports'


class EvidenceExportApiTests(unittest.TestCase):
    write = staticmethod(base.ReportContextApiTests.write)
    tree = staticmethod(base.ReportContextApiTests.tree)
    head = base.ReportContextApiTests.head
    correct_metadata = base.ReportContextApiTests.correct_metadata
    assert_originals = base.ReportContextApiTests.assert_originals
    setUp = base.ReportContextApiTests.setUp
    stop_server = base.ReportContextApiTests.stop_server
    request = base.ReportContextApiTests.request
    frozen = base.ReportContextApiTests.frozen
    assert_unchanged = base.ReportContextApiTests.assert_unchanged
    context = base.ReportContextApiTests.context
    first = base.ReportContextApiTests.first

    def envelope(self, *, profile='privacy-reduced', operation='a' * 32):
        state = self.context()
        result = {'confirm': True, 'profile': profile, 'operation_id': operation,
                  'expected_report_head': state['head'],
                  'expected_report_context_sha256': state['report_context_sha256']}
        if profile == 'full':
            result['confirm_full'] = True
        return result

    def exported(self):
        store = self.projects / STORE
        return {} if not store.exists() else {path.name: path.read_bytes() for path in store.iterdir()}

    def publish(self, body=None):
        body = self.envelope() if body is None else body
        status, receipt = self.request('POST', 'evidence-exports', body)
        self.assertEqual(status, 201, ('R08_EXPORT_HTTP_MISSING business RED', receipt))
        self.assertEqual(receipt['schema'], 'kinelab.evidence-export-receipt.v1')
        self.assertEqual(receipt['session_id'], SID)
        self.assertEqual(receipt['operation_id'], body['operation_id'])
        self.assertEqual(receipt['report_head'], body['expected_report_head'])
        self.assertEqual(receipt['report_context_sha256'], body['expected_report_context_sha256'])
        return receipt

    def download(self, operation='a' * 32, *, authenticated=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=8)
        headers = {'Host': f'127.0.0.1:{self.port}'}
        if authenticated:
            headers.update(Authorization='Bearer ' + TOKEN, Origin=f'http://127.0.0.1:{self.port}')
        try:
            connection.request('GET', f'/api/v1/sessions/{SID}/evidence-exports/{operation}/artifact', headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def refuse(self, body, expected):
        before = self.frozen(), self.exported()
        status, result = self.request('POST', 'evidence-exports', body)
        self.assertEqual(status, expected, result)
        self.assertEqual((self.frozen(), self.exported()), before)
        self.assert_originals()
        return result

    def test_00_current_registered_route_publishes_and_fresh_bundle_self_verifies(self):
        self.first()
        before = self.tree(self.folder)
        receipt = self.publish()
        status, raw = self.download()
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['archive']['sha256'])
        self.assertEqual(len(raw), receipt['archive']['bytes'])
        from evidence_export import verify_bytes
        result = verify_bytes(raw)
        self.assertTrue(result['ok'])
        self.assertEqual(result['manifest_sha256'], receipt['manifest_sha256'])
        self.assertEqual(result['audit_authenticity'], 'UNVERIFIED_OFFLINE')
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            self.assertEqual(set(bundle.namelist()), {'evidence.json', 'export-manifest.json'})
            projection = json.loads(bundle.read('evidence.json'))
            self.assertEqual(projection['classification']['privacy'], 'pseudonymous-linkable')
            self.assertIs(projection['classification']['anonymity_claimed'], False)
            self.assertNotIn('session_id', projection)
            self.assertNotIn('effective_metadata', projection)
        rows = [row[0] for row in self.index.conn.execute(
            "SELECT event_type FROM audit_events WHERE event_type LIKE 'EVIDENCE_EXPORT_%' ORDER BY id")]
        self.assertEqual(rows, ['EVIDENCE_EXPORT_STARTED', 'EVIDENCE_EXPORT_PUBLISHED'])
        self.assertEqual(self.tree(self.folder), before)
        self.assert_originals()

    def test_01_receipt_and_artifact_are_actual_token_gated_endpoints(self):
        self.first()
        receipt = self.publish()
        status, observed = self.request('GET', 'evidence-exports/' + 'a' * 32)
        self.assertEqual((status, observed), (200, receipt))
        self.assertEqual(self.request('GET', 'evidence-exports/' + 'a' * 32, authenticated=False)[0], 401)
        self.assertEqual(self.download(authenticated=False)[0], 401)
        self.assertEqual(self.download('b' * 32)[0], 409)

    def test_02_strict_profiles_unknown_partial_and_unsafe_request_fields_are_400_no_writes(self):
        self.first()
        valid = self.envelope()
        cases = [{**valid, 'profile': 'anonymous'}, {**valid, 'out': '../PRIVATE_TEST_ONLY'},
                 {**valid, 'profile': []}, {**valid, 'operation_id': '../PRIVATE_TEST_ONLY'},
                 {**valid, 'confirm': 1}, {**valid, 'expected_report_head': None}]
        for body in cases:
            with self.subTest(body=body):
                self.refuse(body, 400)

    def test_03_stale_head_or_context_refuses_before_intent_or_store_creation(self):
        self.first()
        body = self.envelope()
        for changed in ({**body, 'expected_report_context_sha256': '0' * 64},
                        {**body, 'expected_report_head': {'generation': 'report-' + '0' * 32, 'manifest_sha256': '0' * 64}}):
            with self.subTest(changed=changed):
                self.refuse(changed, 409)
        self.assertFalse((self.projects / STORE).exists())

    def test_04_full_requires_explicit_confirmation_and_preserves_original_report_bytes(self):
        manifest_path, _ = self.first()
        body = self.envelope(profile='full')
        missing = copy.deepcopy(body)
        del missing['confirm_full']
        self.refuse(missing, 400)
        receipt = self.publish(body)
        status, raw = self.download()
        self.assertEqual(status, 200)
        from evidence_export import verify_bytes
        self.assertTrue(verify_bytes(raw)['ok'])
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            self.assertEqual(bundle.read('source-report-manifest.json'), manifest_path.read_bytes())
            for name, suffix in (('report.pdf', 'research-report.pdf'), ('report-summary.json', 'research-summary.json'), ('metrics.csv', 'metrics.csv')):
                self.assertEqual(bundle.read(name), (manifest_path.parent / f'{SID}-{suffix}').read_bytes())
        self.assertEqual(receipt['profile'], 'full')
        self.assert_originals()

    def test_05_orphan_selected_generation_is_not_a_publication_authority(self):
        self.first()
        body = self.envelope()
        orphan = self.folder / 'exports' / ('report-' + 'f' * 32)
        orphan.mkdir()
        (orphan / 'manifest.json').write_text('{"TEST_ONLY":"not audited"}', encoding='utf-8')
        body['expected_report_head'] = {'generation': orphan.name, 'manifest_sha256': hashlib.sha256((orphan / 'manifest.json').read_bytes()).hexdigest()}
        self.refuse(body, 409)

    def test_06_tampered_historical_report_refuses_with_originals_and_bad_bytes_preserved(self):
        manifest, _ = self.first()
        body = self.envelope()
        member = manifest.parent / f'{SID}-metrics.csv'
        member.write_bytes(member.read_bytes() + b'TEST_ONLY_CHANGED')
        self.refuse(body, 409)
        self.assertTrue(member.read_bytes().endswith(b'TEST_ONLY_CHANGED'))

    def test_07_exact_retry_is_same_receipt_and_conflicting_operation_does_not_republish(self):
        self.first()
        body = self.envelope()
        receipt = self.publish(body)
        self.correct_metadata()  # Exact retry retains the audited prior export after legitimate metadata change.
        before = self.frozen(), self.exported()
        self.assertEqual(self.publish(body), receipt)
        self.assertEqual((self.frozen(), self.exported()), before)
        changed = {**body, 'profile': 'full', 'confirm_full': True}
        self.refuse(changed, 409)

    def test_08_failed_durable_intent_creates_no_output_and_no_saved_ack(self):
        self.first()
        body = self.envelope()
        original = self.index._append_audit
        def append(sid, event, details, **context):
            if event == 'EVIDENCE_EXPORT_STARTED':
                raise sqlite3.OperationalError('TEST_ONLY_PRIVATE_DB_SENTINEL')
            return original(sid, event, details, **context)
        before = self.frozen(), self.exported()
        with patch.object(self.index, '_append_audit', side_effect=append):
            status, result = self.request('POST', 'evidence-exports', body)
        self.assertEqual(status, 503)
        self.assertNotIn('PRIVATE_DB', json.dumps(result))
        self.assertEqual((self.frozen(), self.exported()), before)
        self.assertFalse((self.projects / STORE).exists())

    def test_09_failed_publication_audit_preserves_output_and_pending_refuses_retry(self):
        self.first()
        body = self.envelope()
        original = self.index._append_audit
        def append(sid, event, details, **context):
            if event == 'EVIDENCE_EXPORT_PUBLISHED':
                raise sqlite3.OperationalError('TEST_ONLY_PRIVATE_COMMIT_SENTINEL')
            return original(sid, event, details, **context)
        with patch.object(self.index, '_append_audit', side_effect=append):
            status, result = self.request('POST', 'evidence-exports', body)
        self.assertEqual(status, 503)
        self.assertNotIn('PRIVATE_COMMIT', json.dumps(result))
        self.assertEqual(len(self.exported()), 1)
        before = self.frozen(), self.exported()
        self.refuse(body, 409)
        self.assertEqual((self.frozen(), self.exported()), before)

    def test_10_standalone_verifier_rejects_tamper_extra_path_and_missing_manifest(self):
        self.first()
        self.publish()
        _, raw = self.download()
        from evidence_export import EvidenceExportError, verify_bytes
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        changed = {**members, 'evidence.json': members['evidence.json'] + b' '}
        extras = {**members, '../TEST_ONLY-private': b'TEST_ONLY'}
        missing = {name: value for name, value in members.items() if name != 'export-manifest.json'}
        for case in (changed, extras, missing):
            with self.subTest(names=sorted(case)):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
                    for name, value in case.items():
                        archive.writestr(name, value)
                with self.assertRaises(EvidenceExportError):
                    verify_bytes(stream.getvalue())

    def test_11_export_store_is_excluded_from_session_index_backup_and_report_inputs(self):
        self.first()
        baseline = self.context()
        ids = [row['id'] for row in self.service.library.list_sessions()]
        backup_ids = self.service.backup_mgr._session_ids()
        self.publish()
        self.assertEqual([row['id'] for row in self.service.library.list_sessions()], ids)
        self.assertEqual(self.service.backup_mgr._session_ids(), backup_ids)
        self.assertEqual(self.context(), baseline)
        self.index.reindex()
        self.assertNotIn(STORE, [row['id'] for row in self.index.conn.execute('SELECT id FROM sessions')])

    def test_12_changed_metadata_context_is_not_exported_as_current_old_report(self):
        self.first()
        body = self.envelope()
        self.correct_metadata()
        self.refuse(body, 409)

    def test_13_oversized_archive_is_refused_before_open_and_preserved(self):
        self.first()
        receipt = self.publish()
        from evidence_export import LIMIT, EvidenceExportError, _read
        path = self.projects / STORE / (receipt['export_id'] + '.zip')
        with path.open('r+b') as stream:
            stream.truncate(LIMIT + 1)
        with patch('pathlib.Path.open', side_effect=AssertionError('oversized input must never open')), self.assertRaises(EvidenceExportError):
            _read(path, LIMIT)
        self.assertEqual(path.stat().st_size, LIMIT + 1)
        self.assert_originals()
    def test_14_mutated_published_archive_refuses_both_endpoints_and_retry_without_healing(self):
        self.first()
        body = self.envelope()
        receipt = self.publish(body)
        archive = self.projects / STORE / (receipt['export_id'] + '.zip')
        original = archive.read_bytes()
        changed = original + b'TEST_ONLY_PUBLISHED_ARCHIVE_TAMPER'
        archive.write_bytes(changed)
        before = self.frozen(), self.exported()
        status, result = self.request('GET', 'evidence-exports/' + body['operation_id'])
        self.assertEqual(status, 409, result)
        self.assertNotIn('export_id', result)
        self.assertEqual(self.download(body['operation_id'])[0], 409)
        self.refuse(body, 409)
        self.assertEqual((self.frozen(), self.exported()), before)
        self.assertEqual(archive.read_bytes(), changed)
        self.assertEqual(len(self.exported()), 1)
        self.assert_originals()

    def test_15_real_report_member_change_after_selection_preserves_pending_output_and_refuses_retry(self):
        manifest, _ = self.first()
        body = self.envelope()
        member = manifest.parent / f'{SID}-metrics.csv'
        original = member.read_bytes()
        changed = original + b'\nTEST_ONLY_CHANGED_BETWEEN_SELECTION_AND_COMMIT\n'
        append_original = self.index._append_audit
        mutations = []

        def append(sid, event, details, **context):
            result = append_original(sid, event, details, **context)
            if event == 'EVIDENCE_EXPORT_STARTED':
                self.assertEqual(member.read_bytes(), original)
                member.write_bytes(changed)
                mutations.append(member.read_bytes())
            return result

        with patch.object(self.index, '_append_audit', side_effect=append):
            status, result = self.request('POST', 'evidence-exports', body)
        self.assertEqual(status, 409, result)
        self.assertNotIn('export_id', result)
        self.assertNotIn('TEST_ONLY_CHANGED_BETWEEN_SELECTION_AND_COMMIT', json.dumps(result))
        self.assertEqual(mutations, [changed])
        self.assertEqual(member.read_bytes(), changed)
        rows = [row[0] for row in self.index.conn.execute(
            "SELECT event_type FROM audit_events WHERE event_type LIKE 'EVIDENCE_EXPORT_%' ORDER BY id")]
        self.assertEqual(rows, ['EVIDENCE_EXPORT_STARTED'])
        self.assertEqual(len(self.exported()), 1)
        before = self.frozen(), self.exported()
        self.refuse(body, 409)
        self.assertEqual((self.frozen(), self.exported()), before)
        self.assertEqual(member.read_bytes(), changed)
        self.assert_originals()
    def test_16_bound_original_tamper_refuses_receipt_artifact_and_exact_retry_without_healing(self):
        # Compose fresh generated fixtures; do not inherit or invoke another test.
        for relative in ('raw/cam01_trial.mp4', 'session.json', 'run.json'):
            with self.subTest(source=relative):
                case = EvidenceExportApiTests('test_00_current_registered_route_publishes_and_fresh_bundle_self_verifies')
                try:
                    case.setUp()
                    manifest, _ = case.first()
                    document = json.loads(manifest.read_bytes())
                    self.assertIn(relative, document['inputs'])
                    target = case.folder / relative
                    original = target.read_bytes()
                    self.assertEqual(document['inputs'][relative], {
                        'sha256': hashlib.sha256(original).hexdigest(), 'bytes': len(original)})
                    body = case.envelope()
                    receipt = case.publish(body)
                    status, archived = case.download(body['operation_id'])
                    self.assertEqual(status, 200)
                    self.assertEqual(hashlib.sha256(archived).hexdigest(), receipt['archive']['sha256'])
                    changed = original + b'\nTEST_ONLY_BOUND_ORIGINAL_TAMPER\n'
                    target.write_bytes(changed)
                    before = case.frozen(), case.exported()
                    for endpoint in ('receipt', 'artifact', 'replay'):
                        with self.subTest(source=relative, endpoint=endpoint):
                            if endpoint == 'receipt':
                                status, result = case.request('GET', 'evidence-exports/' + body['operation_id'])
                            elif endpoint == 'artifact':
                                status, raw = case.download(body['operation_id'])
                                result = raw
                            else:
                                status, result = case.request('POST', 'evidence-exports', body)
                            self.assertEqual(status, 409, ('bound original changed; no saved acknowledgment', endpoint, status))
                            if isinstance(result, bytes):
                                self.assertFalse(result.startswith(b'PK'), 'refusal must not serve the archived ZIP')
                                result = json.loads(result)
                            self.assertNotIn('export_id', result)
                            self.assertNotIn('archive', result)
                            self.assertNotIn('TEST_ONLY_BOUND_ORIGINAL_TAMPER', json.dumps(result))
                    self.assertEqual((case.frozen(), case.exported()), before)
                    self.assertEqual(target.read_bytes(), changed, 'refusals must retain tampered bytes')
                    for name, raw in case.originals.items():
                        if name != relative:
                            self.assertEqual((case.folder / name).read_bytes(), raw)
                    self.assertEqual(len(case.exported()), 1)
                    self.assertEqual(next(iter(case.exported().values())), archived)
                    case.index.verify_audit()
                finally:
                    self.assertTrue(case.doCleanups(), 'owned generated fixture cleanup failed')

    def test_17_recognized_markers_refuse_registered_real_report_without_publication(self):
        # Classification does not override immutable registered metadata identity.
        for marker in ('SAMPLE-PROVENANCE.json', 'TEST-ONLY-NOT-CALIBRATED.txt', 'TEST-STATUS.md'):
            with self.subTest(marker=marker):
                case = EvidenceExportApiTests('test_00_current_registered_route_publishes_and_fresh_bundle_self_verifies')
                try:
                    case.setUp()
                    marker_bytes = b'{"test_only":true,"source":"generated acceptance fixture"}\n'
                    (case.folder / marker).write_bytes(marker_bytes)
                    self.assertEqual(json.loads((case.folder / 'session.json').read_bytes())['kind'], 'real')
                    status, result = case.request('POST', 'reports/generate', {'confirm': True})
                    self.assertEqual(status, 409, result)
                    self.assertIs(result['ok'], False)
                    self.assertTrue(result['error'].startswith('REPORT_CONTEXT_CHANGED:'), result)
                    self.assertNotIn('archive', result)
                    passport = case.index.get_passport(SID)
                    self.assertEqual(passport['kind'], 'test-only')
                    self.assertIs(passport['is_test_only'], True)
                    self.assertEqual(case.index.conn.execute(
                        'SELECT kind FROM sessions WHERE id=?', (SID,)).fetchone()['kind'], 'test-only')
                    self.assertFalse(list((case.folder / 'exports').glob('report-*')))
                    self.assertEqual(case.exported(), {})
                    status, raw = case.download('b' * 32)
                    self.assertEqual(status, 409)
                    self.assertFalse(raw.startswith(b'PK'))
                    self.assertEqual(case.index.conn.execute(
                        "SELECT COUNT(*) FROM audit_events WHERE session_id=? AND "
                        "(event_type='REPORT_PUBLISHED' OR event_type LIKE 'EVIDENCE_EXPORT_%')",
                        (SID,)).fetchone()[0], 0)
                    self.assertEqual((case.folder / marker).read_bytes(), marker_bytes)
                    self.assertEqual(json.loads((case.folder / 'session.json').read_bytes())['kind'], 'real')
                    case.assert_originals()
                    # Rendering reindexes classification; audit immutability is not assumed.
                    case.index.verify_audit()
                finally:
                    self.assertTrue(case.doCleanups(), 'owned generated marker fixture cleanup failed')

    def test_18_late_recognized_marker_refuses_old_report_export_reads_and_exact_retry(self):
        # A new marker is an unaudited input addition, never permission to relabel old bytes.
        self.first()
        body = self.envelope()
        self.publish(body)
        status, archived = self.download()
        self.assertEqual(status, 200)
        (self.folder / 'TEST-STATUS.md').write_text('Generated test-only acceptance fixture\n', encoding='utf-8')
        before = self.frozen(), self.exported()
        status, result = self.request('GET', 'evidence-exports/' + body['operation_id'])
        self.assertEqual(status, 409, result)
        self.assertNotIn('archive', result)
        status, raw = self.download()
        self.assertEqual(status, 409)
        self.assertFalse(raw.startswith(b'PK'))
        self.refuse(body, 409)
        status, result = self.request('POST', 'reports/generate', {
            'confirm': True, 'expected_report_head': body['expected_report_head'],
            'expected_report_context_sha256': body['expected_report_context_sha256']})
        self.assertEqual(status, 409, result)
        self.assertEqual((self.frozen(), self.exported()), before)
        self.assertEqual(next(iter(self.exported().values())), archived)
        self.assertTrue((self.folder / 'TEST-STATUS.md').exists())
        self.assert_originals()

    def test_19_registered_demo_report_and_both_export_profiles_remain_test_only(self):
        from evidence_export import verify_bytes
        from session_contract import sha256_file
        from session_metadata_revision import read_metadata_state
        from tools import verify_report_browser as reports

        # This existing generator registers demo before immutable baselines exist.
        fixture = reports.prepare_fixture(self.service)
        sid = fixture['session_id']
        folder = self.projects / sid
        self.assertNotEqual(sid, SID)
        self.assertEqual(json.loads((folder / 'session.json').read_bytes())['kind'], 'demo')
        state = read_metadata_state(self.index, sid)
        self.assertEqual(state['status'], 'AVAILABLE', state)
        self.assertEqual(state['context_sha256'], fixture['metadata_context_sha256'])
        status, result = self.request('POST', 'reports/generate', {'confirm': True}, session_id=sid)
        self.assertEqual(status, 201, result)
        history = list((folder / 'exports').glob('report-*/manifest.json'))
        self.assertEqual(len(history), 1)
        manifest_path = history[0]
        manifest = json.loads(manifest_path.read_bytes())
        self.assertEqual(manifest['schema'], 'kinelab.report-generation.v2')
        self.assertEqual(manifest['inputs']['generated-fixture-provenance.json']['sha256'],
                         fixture['originals_sha256']['generated-fixture-provenance.json'])
        summary_bytes = (manifest_path.parent / f'{sid}-research-summary.json').read_bytes()
        csv_bytes = (manifest_path.parent / f'{sid}-metrics.csv').read_bytes()
        summary = json.loads(summary_bytes)
        self.assertIs(summary['is_test_only'], True)
        self.assertEqual(summary['passport']['kind'], 'demo')
        self.assertIs(summary['passport']['is_test_only'], True)
        self.assertIs(summary['physical_accuracy_verified'], False)
        self.assertIs(summary['clinical_accuracy_verified'], False)
        self.assertEqual(summary['measurement_count'], 0)
        self.assertEqual(summary['measurement_status'], 'No valid measurements')
        status, context = self.request('GET', 'report-context', session_id=sid)
        self.assertEqual(status, 200, context)
        self.assertEqual(context['status'], 'AVAILABLE', context)
        self.assertEqual(context['head'], {'generation': manifest_path.parent.name,
                                          'manifest_sha256': sha256_file(manifest_path)})
        before = self.tree(folder)
        for profile, operation in (('privacy-reduced', 'b' * 32), ('full', 'c' * 32)):
            with self.subTest(profile=profile):
                body = {'confirm': True, 'profile': profile, 'operation_id': operation,
                        'expected_report_head': context['head'],
                        'expected_report_context_sha256': context['report_context_sha256']}
                if profile == 'full':
                    body['confirm_full'] = True
                status, receipt = self.request('POST', 'evidence-exports', body, session_id=sid)
                self.assertEqual(status, 201, receipt)
                self.assertEqual(receipt['schema'], 'kinelab.evidence-export-receipt.v1')
                self.assertEqual(receipt['session_id'], sid)
                self.assertEqual(receipt['operation_id'], operation)
                self.assertEqual(receipt['report_head'], context['head'])
                self.assertEqual(receipt['report_context_sha256'], context['report_context_sha256'])
                connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=6)
                try:
                    connection.request('GET', f'/api/v1/sessions/{sid}/evidence-exports/{operation}/artifact',
                        headers={'Host': f'127.0.0.1:{self.port}', 'Authorization': 'Bearer ' + TOKEN,
                                 'Origin': f'http://127.0.0.1:{self.port}'})
                    response = connection.getresponse()
                    status, raw = response.status, response.read()
                finally:
                    connection.close()
                self.assertEqual(status, 200)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['archive']['sha256'])
                self.assertEqual(len(raw), receipt['archive']['bytes'])
                verified = verify_bytes(raw)
                self.assertTrue(verified['ok'], verified)
                self.assertEqual(verified['manifest_sha256'], receipt['manifest_sha256'])
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    classification = json.loads(archive.read('export-manifest.json'))['classification']
                    self.assertIs(classification['is_test_only'], True)
                    self.assertEqual(classification['physical_validation'], 'UNVERIFIED')
                    self.assertEqual(classification['clinical_validation'], 'UNVERIFIED')
                    self.assertIs(classification['anonymity_claimed'], False)
                    if profile == 'privacy-reduced':
                        projection = json.loads(archive.read('evidence.json'))
                        self.assertEqual(projection['classification'], classification)
                        self.assertEqual(projection['measurement_count'], 0)
                    else:
                        self.assertEqual(archive.read('report-summary.json'), summary_bytes)
                        self.assertIs(json.loads(archive.read('report-summary.json'))['is_test_only'], True)
                        self.assertEqual(archive.read('metrics.csv'), csv_bytes)
                self.assertEqual(self.tree(folder), before)
        for name, digest in fixture['originals_sha256'].items():
            self.assertEqual(sha256_file(folder / name), digest, name)
        self.assertEqual(json.loads((folder / 'session.json').read_bytes())['kind'], 'demo')
        self.assert_originals()
        self.index.verify_audit()
