"""Native sync stays in the serving runtime without launching any real process."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from capture_station import PARTICIPANT_RECORDING_BLOCKED
from sync_evidence import SyncEvidenceError
from t6_service import IntegratedService, IntegrationBlocked


class NativeSyncRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-native-runtime-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.install = self.root / "candidate-app"
        self.data_root = self.root / "isolated-data"
        self.project = self.data_root / "sync-fixture"
        self.interpreter = Path(sys.executable)
        self.assertTrue(self.interpreter.is_file())
        self.service = SimpleNamespace(
            mutex=threading.RLock(), projects_root=self.data_root,
            _project=Mock(return_value=self.project),
        )
        self.addCleanup(patch.stopall)
        patch("t6_service.ROOT", self.install).start()
        self.process = patch("t6_service.subprocess.Popen").start()
        self.observations = patch("sync_evidence.normalized_videos", return_value=({}, {})).start()

    def open_sync(self, *, confirm=True):
        return IntegratedService.open_native(self.service, "sync-fixture", "sync", confirm=confirm)

    def add_obsolete_interpreter(self):
        legacy = self.install / ".venv" / "Scripts" / "pythonw.exe"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"TEST FIXTURE: never executed")
        return legacy

    def test_sync_uses_running_interpreter_without_source_venv(self):
        self.assertFalse((self.install / ".venv").exists())

        def spawn_after_validation(*args, **kwargs):
            self.observations.assert_called_once_with(self.project)

        self.process.side_effect = spawn_after_validation
        try:
            result = self.open_sync()
        except IntegrationBlocked as error:
            self.fail(f"Running interpreter must support a candidate without app/.venv: {error}")
        self.assertEqual(result, {
            "opened": True, "target": "sync", "message": "Frame-review window opened",
        })
        self.service._project.assert_called_once_with("sync-fixture")
        self.process.assert_called_once_with(
            [str(self.interpreter), str(self.install / "launch_sync_review.py"),
             "--session-id", "sync-fixture", "--data-root", str(self.data_root)],
            cwd=str(self.install), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_obsolete_source_venv_cannot_replace_running_interpreter(self):
        legacy = self.add_obsolete_interpreter()
        self.open_sync()
        command = self.process.call_args.args[0]
        self.assertEqual(command[0], str(self.interpreter))
        self.assertNotEqual(command[0], str(legacy))

    def test_only_literal_confirmation_permits_native_launch(self):
        for confirm in (False, None, 1, "true"):
            with self.subTest(confirm=confirm), self.assertRaisesRegex(
                IntegrationBlocked, "Explicit operator request required",
            ):
                self.open_sync(confirm=confirm)
        self.service._project.assert_not_called()
        self.observations.assert_not_called()
        self.process.assert_not_called()

    def test_confirmed_capture_stays_blocked(self):
        with self.assertRaisesRegex(IntegrationBlocked, PARTICIPANT_RECORDING_BLOCKED):
            IntegratedService.open_native(self.service, "sync-fixture", "capture", confirm=True)
        self.service._project.assert_not_called()
        self.process.assert_not_called()

    def test_invalid_session_never_validates_or_spawns(self):
        self.service._project.side_effect = ValueError("Invalid session")
        with self.assertRaisesRegex(ValueError, "Invalid session"):
            self.open_sync()
        self.observations.assert_not_called()
        self.process.assert_not_called()

    def test_observation_failure_never_spawns(self):
        self.add_obsolete_interpreter()
        self.observations.side_effect = SyncEvidenceError("Normalized evidence unavailable")
        with self.assertRaisesRegex(SyncEvidenceError, "Normalized evidence unavailable"):
            self.open_sync()
        self.process.assert_not_called()

    def test_missing_current_interpreter_retains_blocked_error(self):
        self.add_obsolete_interpreter()
        with patch.object(sys, "executable", str(self.root / "missing-python.exe")), self.assertRaisesRegex(
            IntegrationBlocked, "Local Python GUI environment missing",
        ):
            self.open_sync()
        self.observations.assert_not_called()
        self.process.assert_not_called()

    def test_spawn_failure_is_still_reported_to_caller(self):
        self.add_obsolete_interpreter()
        self.process.side_effect = OSError("Synthetic process creation failure")
        with self.assertRaisesRegex(OSError, "Synthetic process creation failure"):
            self.open_sync()
        self.observations.assert_called_once_with(self.project)

    def test_other_native_actions_do_not_require_a_gui_interpreter(self):
        with patch.object(sys, "executable", str(self.root / "missing-python.exe")), patch(
            "t6_service.os.startfile", create=True,
        ) as startfile:
            for target, path in (
                ("folder", self.project),
                ("runbook", self.install / "RUNBOOK.md"),
                ("board", self.install / "assets" / "checkerboard_20mm.svg"),
            ):
                with self.subTest(target=target):
                    result = IntegratedService.open_native(
                        self.service, "sync-fixture", target, confirm=True,
                    )
                    self.assertTrue(result["opened"])
                    startfile.assert_called_with(str(path))
        self.observations.assert_not_called()
        self.process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
