"""Participant acquisition is refused before hardware or filesystem effects."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from capture_station import prepare_recording
from capture_station_gui import CaptureApp
from t6_service import IntegratedService, IntegrationBlocked
from unified_service import AppCore, AppError, make_handler


class CaptureContainmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / 'projects').mkdir()
        self.service = IntegratedService(Path(self.tmp.name) / 'projects')
        self.service.create_session('capture-blocked')
        self.project = self.service.projects_root / 'capture-blocked'

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes()
                for p in self.project.rglob('*') if p.is_file()}

    def test_confirmed_capture_refuses_before_poll_or_process(self):
        before = self.snapshot()
        with patch.object(self.service, '_poll_webcam') as poll, patch('t6_service.subprocess.Popen') as process:
            with self.assertRaisesRegex(IntegrationBlocked, 'PARTICIPANT_RECORDING_BLOCKED'):
                self.service.record_webcam('capture-blocked', 'cam02_trial', seconds=12, confirm=True)
            process.assert_not_called()
            poll.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.service.webcam)

    def test_shared_preparation_refuses_valid_session_without_writing(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'PARTICIPANT_RECORDING_BLOCKED'):
            prepare_recording(self.project, 'cam02_trial', 12)
        self.assertEqual(self.snapshot(), before)

    def test_native_record_control_refuses_before_prompt_or_process(self):
        before = self.snapshot()
        app = SimpleNamespace(process=None, job=None, project=self.project,
                              _workflow_running=Mock(return_value=False),
                              _ensure_editable=Mock(return_value=True), stop_btn=Mock(), _poll=Mock())
        with patch('capture_station_gui.messagebox.askyesno', return_value=True) as consent, \
             patch('capture_station_gui.messagebox.showerror') as error, \
             patch('capture_station_gui.subprocess.Popen') as process:
            CaptureApp.record_webcam(app, 'cam02_trial')
            error.assert_called_once()
            self.assertIn('PARTICIPANT_RECORDING_BLOCKED', error.call_args.args[1])
            consent.assert_not_called()
            process.assert_not_called()
            app._ensure_editable.assert_not_called()
            app._poll.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(app.process)

    def test_capture_window_cannot_bypass_service_containment(self):
        before = self.snapshot()
        with patch('t6_service.subprocess.Popen') as process:
            with self.assertRaisesRegex(IntegrationBlocked, 'PARTICIPANT_RECORDING_BLOCKED'):
                self.service.open_native('capture-blocked', 'capture', confirm=True)
            process.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_legacy_service_refuses_before_session_polling(self):
        app = SimpleNamespace(mutex=threading.RLock(), _record_status=Mock(return_value={'state': 'idle'}),
                              jobs={}, editable=Mock(return_value=self.project))
        with self.assertRaisesRegex(AppError, 'PARTICIPANT_RECORDING_BLOCKED'):
            AppCore.record_start(app, 'capture-blocked', 'cam02_trial', 12, True)
        app._record_status.assert_not_called()
        app.editable.assert_not_called()

    def test_legacy_capture_shortcut_refuses_before_launch(self):
        handler = object.__new__(make_handler(SimpleNamespace()))
        with patch('unified_service.launch_shortcut') as launch:
            with self.assertRaisesRegex(AppError, 'PARTICIPANT_RECORDING_BLOCKED') as blocked:
                handler.open_legacy({'key': 'capture', 'confirmed': True})
            self.assertEqual(blocked.exception.status, 409)
            launch.assert_not_called()

    def test_service_trial_import_refuses_before_session_or_copy(self):
        source = Path(self.tmp.name) / 'generated-source.mp4'
        source.write_bytes(b'generated-not-participant-footage')
        before = self.snapshot()
        with patch('t6_service.import_phone_mp4') as low_level, \
             patch.object(self.service, '_editable') as editable:
            for confirm in (True, False):
                with self.subTest(confirm=confirm), \
                     self.assertRaisesRegex(IntegrationBlocked, 'PARTICIPANT_RECORDING_BLOCKED'):
                    self.service.import_phone('capture-blocked', 'cam01_trial', source, confirm=confirm)
            low_level.assert_not_called()
            editable.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(source.read_bytes(), b'generated-not-participant-footage')

    def test_legacy_trial_upload_refuses_before_pending_write(self):
        stream = Mock()
        app = SimpleNamespace(mutex=threading.RLock(), _record_status=Mock(return_value={'state': 'idle'}),
                              editable=Mock(return_value=self.project))
        before = self.snapshot()
        with patch('unified_service.import_phone_mp4') as low_level:
            with self.assertRaisesRegex(AppError, 'PARTICIPANT_RECORDING_BLOCKED') as blocked:
                AppCore.upload(app, 'capture-blocked', 'cam01_trial', stream, 16, True)
            low_level.assert_not_called()
        self.assertEqual(blocked.exception.status, 409)
        app.editable.assert_not_called()
        app._record_status.assert_not_called()
        stream.read.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_native_trial_import_refuses_before_dialog_or_copy(self):
        before = self.snapshot()
        app = SimpleNamespace(project=self.project, _ensure_editable=Mock(return_value=True),
                              current=Mock(), update_idletasks=Mock(), refresh=Mock())
        with patch('capture_station_gui.filedialog.askopenfilename',
                   return_value=str(self.project / 'generated.mp4')) as pick, \
             patch('capture_station_gui.messagebox.askyesno', return_value=True) as consent, \
             patch('capture_station_gui.messagebox.showinfo') as info, \
             patch('capture_station_gui.messagebox.showerror') as error, \
             patch('capture_station_gui.import_phone_mp4') as low_level:
            CaptureApp.import_phone(app, 'cam01_trial')
            error.assert_called_once()
            self.assertIn('PARTICIPANT_RECORDING_BLOCKED', error.call_args.args[1])
            pick.assert_not_called()
            consent.assert_not_called()
            info.assert_not_called()
            low_level.assert_not_called()
            app._ensure_editable.assert_not_called()
            app.current.configure.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_legacy_non_capture_launch_and_validation_preserved(self):
        handler = object.__new__(make_handler(SimpleNamespace()))
        with patch('unified_service.launch_shortcut') as launch:
            for data, status in (({'key': 'motion', 'confirmed': False}, 409),
                                 ({'key': 'unknown', 'confirmed': True}, 400)):
                with self.subTest(data=data), self.assertRaises(AppError) as blocked:
                    handler.open_legacy(data)
                self.assertEqual(blocked.exception.status, status)
            launch.assert_not_called()
            handler.open_legacy({'key': 'motion', 'confirmed': True})
            launch.assert_called_once_with('motion')

    def test_native_trial_take_controls_refuse_before_dialog_or_library(self):
        before = self.snapshot()
        for role in ('cam01_trial', 'cam02_trial'):
            for method, title in ((CaptureApp.stage_alternate, 'Cannot stage take'),
                                  (CaptureApp.accept_alternate, 'Take selection refused')):
                app = SimpleNamespace(project=self.project, _ensure_editable=Mock(return_value=True),
                                      library=Mock(), refresh=Mock())
                with self.subTest(role=role, method=method.__name__), \
                     patch('capture_station_gui.filedialog.askopenfilename',
                           return_value=str(self.project / 'generated.mp4')) as pick, \
                     patch('capture_station_gui.messagebox.askyesno', return_value=True) as consent, \
                     patch('capture_station_gui.messagebox.showinfo') as info, \
                     patch('capture_station_gui.messagebox.showerror') as error:
                    method(app, role)
                    error.assert_called_once()
                    self.assertEqual(error.call_args.args[0], title)
                    self.assertIn('PARTICIPANT_RECORDING_BLOCKED', error.call_args.args[1])
                    pick.assert_not_called()
                    consent.assert_not_called()
                    info.assert_not_called()
                    app._ensure_editable.assert_not_called()
                    app.library.stage_take.assert_not_called()
                    app.library.accept_take.assert_not_called()
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
