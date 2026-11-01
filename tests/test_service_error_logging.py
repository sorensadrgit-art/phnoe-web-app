"""Generated-only failure cases for local error reporting and catalog integrity."""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import t6_server
from backup_manager import BackupCorruptError
from t6_server import MAX_JSON, make_server
from t6_service import IntegratedService


class ServiceErrorLoggingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = IntegratedService.__new__(IntegratedService)
        self.service.projects_root = self.root
        self.service.mutex = threading.RLock()
        self.service.backup_mgr = Mock()
        self.addCleanup(self.service.close)

    def archive(self):
        directory = self.root / 'backups'
        directory.mkdir(exist_ok=True)
        path = directory / 'generated.zip'
        path.write_bytes(b'generated catalog test only')
        return path

    def test_declared_catalog_failures_are_logged_and_archive_is_preserved(self):
        archive = self.archive()
        before = archive.read_bytes()
        for error in [BackupCorruptError('generated corrupt archive'), OSError('generated read failure')]:
            with self.subTest(error=type(error).__name__):
                self.service.backup_mgr.inspect_backup.side_effect = error
                with self.assertLogs('t6_service', level='WARNING'):
                    self.assertEqual(self.service.backups(), [])
                self.assertEqual(archive.read_bytes(), before)

    def test_unexpected_catalog_defect_is_not_hidden_as_empty_history(self):
        self.archive()
        self.service.backup_mgr.inspect_backup.side_effect = RuntimeError('generated defect')
        with self.assertRaisesRegex(RuntimeError, 'generated defect'):
            self.service.backups()

    def test_valid_catalog_result_keeps_filename(self):
        self.archive()
        self.service.backup_mgr.inspect_backup.return_value = {'validation': 'structure_only'}
        self.assertEqual(self.service.backups(), [{'validation': 'structure_only', 'filename': 'generated.zip'}])

    def test_finalizer_reports_failed_cleanup_without_raising(self):
        with (patch.object(self.service, 'close', side_effect=RuntimeError('generated cleanup failure')),
              self.assertLogs('t6_service', level='ERROR') as log):
            self.service.__del__()
        self.assertIn('cleanup', '\n'.join(log.output).lower())

    def handler(self, error):
        (self.root / 'index.html').write_text('Generated HTTP fixture only', encoding='utf-8')
        with patch('t6_server.ThreadingHTTPServer', side_effect=lambda address, handler:
                   SimpleNamespace(server_port=address[1], RequestHandlerClass=handler)):
            server = make_server(SimpleNamespace(), token='generated-error-test-token-0000000000000000',
                                 dist=self.root, samples=self.root, port=18372)
        handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
        handler.headers = {'Content-Length': str(MAX_JSON + 1)}
        handler.rfile = SimpleNamespace(read=Mock(side_effect=error))
        return handler

    def test_oversized_body_io_failure_is_logged_and_remains_413(self):
        handler = self.handler(OSError('generated drain failure'))
        with self.assertLogs('t6_server', level='WARNING'), self.assertRaisesRegex(OverflowError, 'too large'):
            handler._body()

    def test_unexpected_body_reader_defect_is_not_hidden_as_size_error(self):
        handler = self.handler(RuntimeError('generated reader defect'))
        with self.assertRaisesRegex(RuntimeError, 'generated reader defect'):
            handler._body()

    def private_error(self, error_type):
        # Generated canaries only; no real token, request, session or user path.
        text = ('B19_PRIVATE_SYNTHETIC token=generated-private-token '
                'body={generated-private-body} session=generated-private-session.zip '
                r'C:\Users\GeneratedPrivateUser\generated-private-recording.mp4')
        error = error_type(text)
        error.add_note('B19_PRIVATE_SYNTHETIC_NOTE')
        error.__cause__ = ValueError('B19_PRIVATE_SYNTHETIC_CAUSE')
        return error

    def assert_private_diagnostic(self, log, *, event, error_type, module):
        text = '\n'.join(log.output)
        for forbidden in ('B19_PRIVATE_SYNTHETIC', 'generated-private-token',
                          'generated-private-body', 'generated-private-session.zip',
                          'GeneratedPrivateUser', 'generated-private-recording.mp4',
                          str(self.root), 'test_service_error_logging.py',
                          'Traceback (most recent call last)', 'raise effect'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)
        self.assertIn('event=' + event, text)
        self.assertIn('exception_type=' + error_type, text)
        self.assertRegex(text, r'location=' + module + r'\.py:\d+')
        for record in log.records:
            self.assertIsNone(record.exc_info, 'Do not retain arbitrary exception objects in log records')
            self.assertIsNone(record.stack_info, 'Do not attach source-bearing stack text')
            self.assertEqual(record.pathname, module + '.py', 'Record metadata must not retain absolute paths')

    def test_cleanup_diagnostic_omits_sensitive_exception_and_traceback(self):
        error = self.private_error(RuntimeError)
        with (patch.object(self.service, 'close', side_effect=error),
              self.assertLogs('t6_service', level='ERROR') as log):
            self.service.__del__()
        self.assert_private_diagnostic(log, event='local_service_cleanup_failed',
                                       error_type='RuntimeError', module='t6_service')

    def test_backup_diagnostic_omits_sensitive_exception_and_keeps_archive(self):
        archive = self.archive()
        before = archive.read_bytes()
        for error_type in (BackupCorruptError, OSError):
            with self.subTest(error_type=error_type.__name__):
                self.service.backup_mgr.inspect_backup.side_effect = self.private_error(error_type)
                with self.assertLogs('t6_service', level='WARNING') as log:
                    self.assertEqual(self.service.backups(), [])
                self.assertEqual(archive.read_bytes(), before)
                self.assert_private_diagnostic(log, event='local_backup_inspection_failed',
                                               error_type=error_type.__name__, module='t6_service')

    def test_oversize_diagnostic_omits_sensitive_exception_and_keeps_size_error(self):
        handler = self.handler(self.private_error(OSError))
        with (self.assertLogs('t6_server', level='WARNING') as log,
              self.assertRaisesRegex(OverflowError, 'JSON body too large')):
            handler._body()
        self.assert_private_diagnostic(log, event='oversize_body_drain_failed',
                                       error_type='OSError', module='t6_server')

    def test_api_diagnostic_omits_sensitive_exception_and_keeps_generic_500(self):
        handler = self.handler(OSError('unused generated read failure'))
        handler.path = '/api/v1/sessions'
        handler._check_host = Mock(return_value=True)
        handler._authorized = Mock(return_value=True)
        handler._body = Mock(side_effect=self.private_error(RuntimeError))
        handler._error = Mock()
        with self.assertLogs('t6_server', level='ERROR') as log:
            handler.do_POST()
        handler._error.assert_called_once_with(
            500, 'Unexpected local API error; inspect the local application log')
        self.assert_private_diagnostic(log, event='unexpected_local_api_error',
                                       error_type='RuntimeError', module='t6_server')

    def test_server_loop_diagnostic_omits_sensitive_exception_and_closes_server(self):
        state = self.root / 'generated-state.json'
        state.write_text(json.dumps({'port': 18372, 'token': 'generated-local-token-' * 3,
                                     'runtime_id': 'generated-runtime'}), encoding='utf-8')
        args = SimpleNamespace(port=18372, state=state, data_root=self.root)
        server = Mock()
        server.serve_forever.side_effect = self.private_error(RuntimeError)
        local_sys = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())
        with (patch('t6_server.argparse.ArgumentParser.parse_args', return_value=args),
              patch('t6_server.ensure_data_root', return_value=self.root),
              patch('t6_server.ensure_directory', return_value=self.root),
              patch('t6_server.is_reparse', return_value=False),
              patch('t6_server.runtime_identity', return_value='generated-runtime'),
              patch('t6_server.IntegratedService', return_value=Mock()),
              patch('t6_server.make_server', return_value=server),
              patch('t6_server.sys', local_sys),
              self.assertLogs('t6_server', level='ERROR') as log):
            try:
                t6_server.main()
            finally:
                local_sys.stdout.close()
        server.serve_forever.assert_called_once_with(poll_interval=0.5)
        server.server_close.assert_called_once_with()
        self.assert_private_diagnostic(log, event='local_server_failed',
                                       error_type='RuntimeError', module='t6_server')


if __name__ == '__main__':
    unittest.main()
