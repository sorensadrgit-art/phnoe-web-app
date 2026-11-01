"""Atomic report visibility on disposable generated sessions only."""
import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backup_manager import BackupManager
from report_builder import ReportBuilder
from session_index import SessionIndex
from session_library import SessionLibrary


class ReportGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = SessionLibrary(self.root).create_session('report-fixture', kind='demo')
        self.index = SessionIndex(self.root / '.kinelab_index.db', self.root)
        self.addCleanup(self.index.close)
        self.index.reindex()
        self.builder = ReportBuilder(self.root, self.index)
        self.pdf = patch.object(self.builder, '_build_pdf', side_effect=lambda path, doc: path.write_bytes(b'%PDF-generated-test-only'))
        self.pdf.start(); self.addCleanup(self.pdf.stop)

    def generate(self):
        return self.builder.generate_reports(self.folder.name)

    def published(self):
        from report_generation import committed_reports
        return committed_reports(self.index, self.folder.name)

    def test_all_outputs_share_one_committed_manifest_and_survive_reopen(self):
        files = self.generate()
        parents = {p.parent for p in files.values()}
        self.assertEqual(len(parents), 1)
        generation = next(iter(parents))
        self.assertTrue((generation / 'manifest.json').is_file(), 'all report files need a single commit manifest')
        self.assertEqual(generation.parent, self.folder / 'exports')
        self.assertEqual(len(self.published()), 3)
        self.index.close()
        self.index = SessionIndex(self.root / '.kinelab_index.db', self.root)
        self.addCleanup(self.index.close)
        self.assertEqual(len(self.published()), 3)

    def test_render_failure_does_not_publish_partial_json_or_csv(self):
        with patch.object(self.builder, '_build_pdf', side_effect=OSError('disk full')), self.assertRaisesRegex(OSError, 'disk full'):
            self.generate()
        self.assertEqual(list((self.folder / 'exports').iterdir()), [])
        self.assertEqual(self.index.conn.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='REPORT_PUBLISHED'").fetchone()[0], 0)

    def test_source_change_during_render_is_rejected(self):
        def change(path, doc):
            path.write_bytes(b'%PDF-generated-test-only')
            (self.folder / 'Config.toml').write_text('# changed during report render')
        with patch.object(self.builder, '_build_pdf', side_effect=change), self.assertRaisesRegex(ValueError, 'REPORT_SOURCE_CHANGED'):
            self.generate()
        self.assertEqual(self.published(), [])

    def test_uncommitted_flat_and_orphan_files_never_become_reports(self):
        exports = self.folder / 'exports'; exports.mkdir(exist_ok=True)
        (exports / 'legacy-research-report.pdf').write_bytes(b'%PDF-preserved-legacy')
        orphan = exports / ('report-' + '0' * 32); orphan.mkdir()
        (orphan / 'partial.csv').write_text('unpublished')
        self.assertEqual(self.published(), [])
        self.index.reindex()
        self.assertEqual(self.published(), [])
        self.assertTrue((orphan / 'partial.csv').is_file())

    def test_changed_output_or_manifest_fails_closed(self):
        files = self.generate()
        for target in (files['pdf'], files['json'].parent / 'manifest.json'):
            before = target.read_bytes()
            target.write_bytes(before + b'changed')
            with self.assertRaisesRegex(ValueError, 'REPORT_INVALID'):
                self.published()
            target.write_bytes(before)
        self.assertEqual(len(self.published()), 3)

    def test_changed_inputs_block_existing_report_access(self):
        self.generate()
        (self.folder / 'Config.toml').write_text('# newer source revision')
        with self.assertRaisesRegex(ValueError, 'REPORT_SOURCE_CHANGED'):
            self.published()

    def test_csv_treats_formula_shaped_metadata_as_literal_text(self):
        passport = self.index.get_passport(self.folder.name)
        operator = '=1+1; "generated fixture"'
        passport['board_measurement'] = {'measured_square_mm': 35.0, 'measured_by': operator}
        with patch.object(self.index, 'get_passport', return_value=passport):
            files = self.generate()
        with files['csv'].open(newline='', encoding='utf-8') as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[1][5], 'Text: ' + operator)
        self.assertEqual(json.loads(files['json'].read_text())['board_measurement']['measured_by'], operator)

    def test_audit_failure_rolls_back_registration_and_visibility(self):
        append = self.index._append_audit
        def reject(sid, kind, details, **kw):
            if kind == 'REPORT_PUBLISHED': raise sqlite3.OperationalError('commit unavailable')
            return append(sid, kind, details, **kw)
        with patch.object(self.index, '_append_audit', side_effect=reject), self.assertRaisesRegex(sqlite3.OperationalError, 'commit unavailable'):
            self.generate()
        self.assertEqual(self.published(), [])
        self.assertEqual(self.index.conn.execute("SELECT COUNT(*) FROM artifacts WHERE artifact_type='research_report'").fetchone()[0], 0)

    def test_complete_backup_restores_committed_report_authority(self):
        self.generate()
        archive_temp = tempfile.TemporaryDirectory(prefix='kinelab-report-backup-')
        self.addCleanup(archive_temp.cleanup)
        archive = Path(archive_temp.name) / 'generated-with-reports.zip'
        manager = BackupManager(self.root, self.index)
        manager.create_backup(archive)
        restored = self.root / 'recovery-generations' / 'copy'
        restored.parent.mkdir()
        manager.restore_generation(archive, restored)
        index = SessionIndex(restored / '.kinelab_index.db', restored)
        try:
            from report_generation import committed_reports
            self.assertEqual(len(committed_reports(index, self.folder.name)), 3)
        finally:
            index.close()

    def test_flush_and_rename_failures_never_register_or_publish(self):
        for boundary in ('fsync', 'rename'):
            with self.subTest(boundary=boundary):
                with patch('report_generation.os.' + boundary, side_effect=OSError('injected storage failure')), self.assertRaisesRegex(OSError, 'injected storage failure'):
                    self.generate()
                self.assertEqual(self.published(), [])
                self.assertEqual(list((self.folder / 'exports').iterdir()), [])

    def test_commit_failure_keeps_unpublished_orphan_and_retry_is_safe(self):
        transaction = self.index.transaction
        @contextmanager
        def fail_commit():
            with transaction():
                yield
                if self.index.conn.execute("SELECT 1 FROM audit_events WHERE event_type='REPORT_PUBLISHED'").fetchone():
                    raise sqlite3.OperationalError('injected commit failure')
        with patch.object(self.index, 'transaction', fail_commit), self.assertRaisesRegex(sqlite3.OperationalError, 'injected commit failure'):
            self.generate()
        self.assertEqual(self.published(), [])
        orphans = list((self.folder / 'exports').glob('report-*'))
        self.assertEqual(len(orphans), 1)
        before = {p.name: p.read_bytes() for p in orphans[0].iterdir()}
        self.generate()
        self.assertEqual(len(self.published()), 3)
        self.assertEqual({p.name: p.read_bytes() for p in orphans[0].iterdir()}, before)

    def test_source_change_at_directory_publication_rolls_back_commit(self):
        rename = os.rename
        def change(source, target):
            rename(source, target)
            (self.folder / 'Config.toml').write_text('# changed at publication')
        with patch('report_generation.os.rename', side_effect=change), self.assertRaisesRegex(ValueError, 'REPORT_SOURCE_CHANGED'):
            self.generate()
        self.assertEqual(self.published(), [])

    def test_actual_process_exit_recovers_none_or_complete_generation(self):
        script = r'''
from contextlib import contextmanager
from pathlib import Path
import os, sys
from unittest.mock import patch
from session_index import SessionIndex
from report_builder import ReportBuilder
root=Path(sys.argv[1]); boundary=sys.argv[2]
index=SessionIndex(root/'.kinelab_index.db', root)
builder=ReportBuilder(root,index)
builder._build_pdf=lambda path,doc:path.write_bytes(b'%PDF-process-fixture')
rename=os.rename
def crash_rename(source,target):
    if boundary=='before-rename':os._exit(73)
    rename(source,target)
    os._exit(73)
transaction=index.transaction
@contextmanager
def crash_commit():
    with transaction():yield
    if index.conn.execute("SELECT 1 FROM audit_events WHERE event_type='REPORT_PUBLISHED'").fetchone():os._exit(73)
if boundary=='after-commit':index.transaction=crash_commit
with patch('report_generation.os.rename', crash_rename if boundary!='after-commit' else rename):
    builder.generate_reports('process-report')
'''
        for boundary in ('before-rename', 'after-rename', 'after-commit'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                SessionLibrary(root).create_session('process-report', kind='demo')
                index = SessionIndex(root / '.kinelab_index.db', root); index.reindex(); index.close()
                result = subprocess.run([sys.executable, '-B', '-c', script, str(root), boundary],
                                        capture_output=True, text=True, timeout=60, check=False)
                self.assertEqual(result.returncode, 73, result.stderr)
                index = SessionIndex(root / '.kinelab_index.db', root)
                try:
                    from report_generation import committed_reports
                    self.assertEqual(len(committed_reports(index, 'process-report')), 3 if boundary == 'after-commit' else 0)
                    index.verify_audit()
                finally:
                    index.close()


if __name__ == '__main__':
    unittest.main()
