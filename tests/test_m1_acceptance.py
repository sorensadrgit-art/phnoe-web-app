"""Independent M1 containment checks. All records and archives are synthetic."""
import hashlib
import http.client
import json
import os
import subprocess
import tempfile
import threading
import unittest
import warnings
import zipfile
from functools import partial
from pathlib import Path
from unittest.mock import patch

from backup_manager import BackupConflictError, BackupCorruptError, BackupManager
from t6_server import make_server
from t6_service import IntegratedService


def snapshot(root):
    return {p.relative_to(root).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            for p in root.rglob('*') if not p.is_symlink()}


def archive_at(path, entries, sessions=('restore-one',), **overrides):
    manifest = {'schema': 'kinelab.backup.v1', 'sessions': list(sessions),
                'database_included': 'index.db' in entries, 'file_count': len(entries),
                'files': [{'path': name, 'bytes': len(data),
                           'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in entries.items()], **overrides}
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('backup_manifest.json', json.dumps(manifest))
        for name, data in entries.items():
            z.writestr(name, data)
    return path


class M1AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kinelab-m1-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = self.root / 'projects'
        self.projects.mkdir()
        self.service = IntegratedService(self.projects)
        self.addCleanup(self.service.close)
        self.manager = self.service.backup_mgr
        self.zip = self.root / 'fixture.zip'
        self.files = {'sessions/restore-one/Config.toml': b'[session]\nkind="demo"\n'}

    def legacy(self, metadata):
        folder = self.projects / 'legacy-live'
        (folder / 'exports').mkdir(parents=True, exist_ok=True)
        (folder / 'Config.toml').write_text('[session]\nkind="live"\n')
        (folder / 'session.json').write_text(metadata, encoding='utf-8')
        (folder / 'live_telemetry.json').write_text('{"source":"unknown"}')
        (folder / 'exports/legacy.motion.json').write_text('{"frames":[]}')
        (folder / 'exports/legacy-research-report.pdf').write_bytes(b'%PDF-fixture-only')
        return folder

    def test_corrupt_or_relabelled_legacy_cannot_bypass_evidence_gate(self):
        for metadata in ('{broken', '{}', '{"kind":"real","schema":"kinelab.live-session.v1"}',
                         '{"kind":"live"}'):
            with self.subTest(metadata=metadata):
                folder = self.legacy(metadata)
                original = snapshot(folder)
                self.assertEqual(self.service.library.describe_session(folder.name)['evidence_status'], 'unverified')
                passport = self.service.passport(folder.name)
                self.assertEqual(passport['state'], 'EVIDENCE_UNVERIFIED')
                self.assertFalse(passport['physical_accuracy_verified'])
                for operation in (partial(self.service.motion_data, folder.name),
                                  partial(self.service.generate_reports, folder.name, confirm=True),
                                  partial(self.service.artifact, folder.name, 'exports/legacy-research-report.pdf')):
                    with self.assertRaisesRegex(ValueError, 'EVIDENCE_UNVERIFIED'):
                        operation()
                self.assertEqual(snapshot(folder), original)

    def test_legacy_test_marker_cannot_erase_unverified_source(self):
        folder = self.legacy('{"kind":"live"}')
        (folder / 'TEST-ONLY-NOT-CALIBRATED.txt').write_text('fixture')
        self.assertEqual(self.service.passport(folder.name)['state'], 'EVIDENCE_UNVERIFIED')

    def test_modified_legacy_motion_remains_unavailable_after_reindex(self):
        folder = self.legacy('{"kind":"live"}')
        self.service.passport(folder.name)
        motion = folder / 'exports/legacy.motion.json'
        motion.write_text('{"frames":[{"xyz":[[999,0,0]]}]}')
        original = snapshot(folder)
        self.assertEqual(self.service.passport(folder.name)['state'], 'EVIDENCE_UNVERIFIED')
        with self.assertRaisesRegex(ValueError, 'EVIDENCE_UNVERIFIED'):
            self.service.motion_data(folder.name)
        self.assertEqual(snapshot(folder), original)

    def test_live_refusal_preserves_existing_record_and_index(self):
        self.legacy('{"kind":"live"}')
        before = snapshot(self.projects)
        for payload in (None, [], {}, {'session_id': 'legacy-live', 'source': 'camera',
                                      'frames': [], 'reps': [{'valid': 'false'}]}):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, 'LIVE_ACQUISITION_UNVERIFIED'):
                self.service.save_live_session(payload)
            self.assertEqual(snapshot(self.projects), before)

    def test_invalid_inventory_and_hash_preserve_every_destination_byte(self):
        self.legacy('{"kind":"live"}')
        for overrides in ({'file_count': 2}, {'database_included': True},
                          {'sessions': ['../sibling']}, {'sessions': [None]},
                          {'files': [{'path': next(iter(self.files)), 'bytes': 999, 'sha256': '0' * 64}]},
                          {'files': [{'path': next(iter(self.files)), 'bytes': len(next(iter(self.files.values()))),
                                      'sha256': '0' * 64}]}):
            with self.subTest(overrides=overrides):
                archive_at(self.zip, self.files, **overrides)
                before = snapshot(self.projects)
                with self.assertRaises(BackupCorruptError):
                    self.manager.restore_backup(self.zip)
                self.assertEqual(snapshot(self.projects), before)

    def test_broken_and_truncated_zip_preserve_index_and_existing_files(self):
        archive_at(self.zip, self.files)
        good = self.zip.read_bytes()
        for blob in (b'not a zip', good[:-24], good[:60]):
            self.zip.write_bytes(blob)
            before = snapshot(self.projects)
            with self.assertRaises(BackupCorruptError):
                self.manager.restore_backup(self.zip)
            self.assertEqual(snapshot(self.projects), before)

    def test_windows_aliases_and_file_directory_conflicts_fail_preflight(self):
        for extra in ({'sessions/restore-one/a/file.txt': b'a', 'sessions/restore-one/A/other.txt': b'b'},
                      {'sessions/restore-one/data': b'a', 'sessions/restore-one/data/file.txt': b'b'},
                      *({f'sessions/restore-one/{name}': b'a'} for name in
                        ('CON.txt', 'file.', 'file ', 'file:stream', 'bad?.txt', 'bad*.txt', 'bad|.txt'))):
            with self.subTest(extra=extra):
                archive_at(self.zip, {**self.files, **extra})
                before = snapshot(self.projects)
                with self.assertRaises(BackupCorruptError):
                    self.manager.inspect_backup(self.zip)
                with self.assertRaises(BackupCorruptError):
                    self.manager.restore_backup(self.zip)
                self.assertEqual(snapshot(self.projects), before)

    def test_duplicate_zip_member_and_windows_reparse_attribute_rejected(self):
        archive_at(self.zip, self.files)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.zip, 'a') as z:
                z.writestr(next(iter(self.files)), next(iter(self.files.values())))
        with self.assertRaises(BackupCorruptError):
            self.manager.inspect_backup(self.zip)
        archive_at(self.zip, self.files)
        with zipfile.ZipFile(self.zip) as z:
            entries = [(i, z.read(i)) for i in z.infolist()]
        with zipfile.ZipFile(self.zip, 'w') as z:
            for info, data in entries:
                if info.filename.startswith('sessions/'):
                    info.create_system = 0
                    info.external_attr = 0x400
                z.writestr(info, data)
        with self.assertRaises(BackupCorruptError):
            self.manager.inspect_backup(self.zip)

    def test_restore_limits_enforced_before_staging(self):
        archive_at(self.zip, self.files)
        for name, limit in (('MAX_MEMBERS', 1), ('MAX_MEMBER_BYTES', 1),
                            ('MAX_TOTAL_BYTES', 1), ('MAX_MANIFEST_BYTES', 1)):
            before = snapshot(self.projects)
            with self.subTest(limit=name), patch.object(BackupManager, name, limit), \
                    self.assertRaises(BackupCorruptError):
                self.manager.restore_backup(self.zip)
            self.assertEqual(snapshot(self.projects), before)

    def test_multiple_sessions_restore_preserves_original_audit_and_database(self):
        self.service.index.record_audit_event('existing', 'PRESERVE', {'synthetic': True})
        archive_at(self.zip, {**self.files, 'sessions/restore-two/Config.toml': b'[session]\n',
                             'index.db': b'ARCHIVED DATABASE MUST NOT REPLACE CURRENT INDEX'},
                   sessions=('restore-one', 'restore-two'))
        result = self.manager.restore_backup(self.zip)
        self.assertEqual(result['restored_sessions'], ['restore-one', 'restore-two'])
        self.assertFalse(result['database_restored'])
        self.assertFalse(result['overwrite_permitted'])
        self.assertEqual(self.service.index.conn.execute(
            "SELECT event_type FROM audit_events WHERE session_id='existing'").fetchone()[0], 'PRESERVE')
        self.assertEqual((self.projects / 'restore-one/Config.toml').read_bytes(), next(iter(self.files.values())))
        stages = list(self.projects.glob('.restore-staging-*'))
        self.assertEqual(len(stages), 1)
        stage = stages[0]
        journal = self.manager._read_restore_journal(stage)
        self.assertEqual(journal['phase'], 'COMMITTED')
        self.assertIsNone(journal['intent'])
        self.assertIs(journal['index_reconciled'], True)
        self.assertEqual([item['id'] for item in journal['sessions']], result['restored_sessions'])
        self.assertIsNotNone(journal['ignored_database'])
        self.assertEqual((stage / 'index.db').read_bytes(),
                         b'ARCHIVED DATABASE MUST NOT REPLACE CURRENT INDEX')
        before = snapshot(self.projects)
        with self.manager.startup_recovery():
            pass
        self.assertEqual(snapshot(self.projects), before)

    def test_failure_at_each_publication_boundary_rolls_back_only_new_sessions(self):
        self.legacy('{"kind":"live"}')
        archive_at(self.zip, {**self.files, 'sessions/restore-two/Config.toml': b'[session]\n'},
                   sessions=('restore-one', 'restore-two'))
        original_rename = Path.rename
        for failed_name in ('restore-one', 'restore-two'):
            before = snapshot(self.projects)
            def fail_publication(source, target, failed_name=failed_name):
                if Path(target).name == failed_name:
                    raise OSError('injected publication failure')
                return original_rename(source, target)
            with self.subTest(failed_name=failed_name), patch.object(Path, 'rename', fail_publication), \
                    self.assertRaisesRegex(OSError, 'injected publication failure'):
                self.manager.restore_backup(self.zip)
            self.assertEqual(snapshot(self.projects), before)

    def test_concurrent_destination_appearance_does_not_remove_other_writer(self):
        archive_at(self.zip, {**self.files, 'sessions/restore-two/Config.toml': b'[session]\n'},
                   sessions=('restore-one', 'restore-two'))
        original_rename = Path.rename
        def competing_writer(source, target):
            result = original_rename(source, target)
            if Path(target).name == 'restore-one':
                other = self.projects / 'restore-two'
                other.mkdir()
                (other / 'owner.txt').write_text('OTHER WRITER')
            return result
        with patch.object(Path, 'rename', competing_writer), self.assertRaises(BackupConflictError):
            self.manager.restore_backup(self.zip)
        self.assertFalse((self.projects / 'restore-one').exists())
        self.assertEqual((self.projects / 'restore-two/owner.txt').read_text(), 'OTHER WRITER')
        self.assertFalse(list(self.projects.glob('.restore-staging-*')))

    @unittest.skipUnless(os.name == 'nt', 'Windows junction check')
    def test_backup_directory_junction_rejected_before_archive_access(self):
        outside = self.root / 'outside'
        outside.mkdir()
        archive_at(outside / 'valid.zip', self.files)
        link = self.projects / 'backups'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(os.rmdir, link)
        original = snapshot(outside)
        with self.assertRaisesRegex(ValueError, 'BACKUP_NAME_INVALID'):
            self.service.restore_backup('valid.zip', confirm=True)
        self.assertFalse((self.projects / 'restore-one').exists())
        self.assertEqual(snapshot(outside), original)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction check')
    def test_backup_junction_to_a_sibling_directory_is_still_refused(self):
        target = self.projects / 'other-backups'
        target.mkdir()
        archive_at(target / 'valid.zip', self.files)
        link = self.projects / 'backups'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(os.rmdir, link)
        with self.assertRaisesRegex(ValueError, 'BACKUP_NAME_INVALID'):
            self.service.restore_backup('valid.zip', confirm=True)
        self.assertFalse((self.projects / 'restore-one').exists())

    def test_rollback_does_not_delete_a_replacement_owned_by_another_writer(self):
        archive_at(self.zip, {**self.files, 'sessions/restore-two/Config.toml': b'[session]\n'},
                   sessions=('restore-one', 'restore-two'))
        original_rename = Path.rename
        def replace_after_publication(source, target):
            if Path(target).name == 'restore-two':
                first = self.projects / 'restore-one'
                original_rename(first, self.root / 'moved-by-other-writer')
                first.mkdir()
                (first / 'owner.txt').write_text('OTHER WRITER')
                raise OSError('injected failure after competing replacement')
            return original_rename(source, target)
        with patch.object(Path, 'rename', replace_after_publication), \
                self.assertRaisesRegex(OSError, 'injected failure'):
            self.manager.restore_backup(self.zip)
        self.assertTrue((self.projects / 'restore-one/owner.txt').is_file())
        self.assertEqual((self.projects / 'restore-one/owner.txt').read_text(), 'OTHER WRITER')
        self.assertFalse((self.projects / 'restore-two').exists())

    def test_http_auth_live_legacy_and_restore_boundaries(self):
        self.legacy('{"kind":"live"}')
        backups = self.projects / 'backups'
        backups.mkdir()
        archive_at(backups / 'valid.zip', self.files)
        (backups / 'broken.zip').write_bytes(b'BROKEN SYNTHETIC ZIP')
        dist = self.root / 'dist'
        dist.mkdir()
        (dist / 'index.html').write_text('<h1>Synthetic acceptance fixture</h1>')
        token = 'fixture-only-' * 5
        server = make_server(self.service, token=token, dist=dist, samples=self.root / 'samples', port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def request(method, path, body=None, headers=None):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                conn.request(method, path, json.dumps(body) if body is not None else None,
                             headers or {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                                         'Origin': f'http://127.0.0.1:{server.server_port}'})
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()
        self.assertEqual(request('GET', '/api/v1/health', headers={'Host': f'127.0.0.1:{server.server_port}'})[0], 401)
        self.assertEqual(request('GET', '/api/v1/health')[0], 200)
        self.assertEqual(request('GET', '/api/v1/health', headers={'Host': 'outside.invalid'})[0], 400)
        before = snapshot(self.projects)
        for method, path, body, reason in (
            ('POST', '/api/v1/sessions/live-set', {'source': 'camera'}, 'LIVE_ACQUISITION_UNVERIFIED'),
            ('GET', '/api/v1/sessions/legacy-live/motion', None, 'EVIDENCE_UNVERIFIED'),
            ('GET', '/api/v1/sessions/legacy-live/artifact/exports/legacy-research-report.pdf', None, 'EVIDENCE_UNVERIFIED'),
            ('POST', '/api/v1/sessions/legacy-live/reports/generate', {'confirm': True}, 'EVIDENCE_UNVERIFIED'),
            ('POST', '/api/v1/backup/restore', {'confirm': True, 'backup_name': '../escape.zip'}, 'BACKUP_NAME_INVALID'),
            ('POST', '/api/v1/backup/restore', {'confirm': True, 'backup_name': 'broken.zip'}, 'BACKUP_CORRUPT'),
            ('POST', '/api/v1/backup/restore', {'confirm': True, 'backup_name': 'valid.zip', 'overwrite': True}, 'RESTORE_OVERWRITE_UNAVAILABLE')):
            with self.subTest(path=path, reason=reason):
                status, body = request(method, path, body)
                self.assertEqual(status, 409)
                self.assertIn(reason, body['error'])
                self.assertEqual(snapshot(self.projects), before)
        status, body = request('POST', '/api/v1/backup/restore', {'confirm': True, 'backup_name': 'valid.zip', 'overwrite': False})
        self.assertEqual(status, 200)
        self.assertEqual(body['restored_sessions'], ['restore-one'])
        self.assertFalse(body['database_restored'])
        self.assertEqual(request('POST', '/api/v1/backup/restore', {'confirm': True, 'backup_name': 'valid.zip'})[0], 409)
