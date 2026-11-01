"""T2 guarded, operator-triggered local workflow; no physical measurements invented."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_contract import ROLES, sha256_file
from session_library import SessionLibrary
from workflow_controller import WorkflowBlocked, WorkflowController


class WorkflowControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.root.mkdir()
        lib = SessionLibrary(self.root)
        self.project = lib.create_session("work-a")
        self.controller = WorkflowController(self.project)
        self.raw = self.project / "raw"

    def tearDown(self):
        self.temp.cleanup()

    def register_fixture(self):
        for role in ROLES:
            (self.raw / (role + ".mp4")).write_bytes((role + "_fixture").encode())
        from setup_project import register_captures
        register_captures(self.project, "work-a", "real")

    def test_unregistered_files_never_start_a_workflow(self):
        with self.assertRaisesRegex(WorkflowBlocked, "registered"):
            self.controller.plan("normalize")
        self.assertFalse((self.project / "workflow.lock").exists())

    def test_registered_normalization_command_is_local_and_explicit(self):
        self.register_fixture()
        plan = self.controller.plan("normalize")
        self.assertIn("normalize_capture.py", " ".join(plan.command))
        self.assertIn("--project", plan.command)
        self.assertNotIn("--overwrite", plan.command)
        self.assertEqual(plan.action, "normalize")
        self.assertFalse((self.project / "workflow.lock").exists())

    def test_cannot_continue_without_verified_preflight_or_cues(self):
        self.register_fixture()
        with self.assertRaisesRegex(WorkflowBlocked, "preflight"):
            self.controller.plan("calibrate_pose")
        with patch.object(self.controller, "_verify_preflight", return_value=None), self.assertRaisesRegex(WorkflowBlocked, "sync-observations"):
            self.controller.plan("reconstruct")

    def test_export_refuses_unknown_or_unpassed_trc(self):
        self.register_fixture()
        with self.assertRaises(WorkflowBlocked):
            self.controller.plan("export_markers")
        from native_evidence_fixture import complete_native_fixture
        from test_export_motion import trc_text
        path, trc, _ = complete_native_fixture(self.project, trc_text())
        manifest = json.loads(path.read_text())
        manifest["stages"][5]["status"] = "failed"
        (self.project / "run.json").write_text(json.dumps(manifest))
        with patch.object(self.controller, "_verify_preflight", return_value=None):
            with self.assertRaisesRegex(WorkflowBlocked, "passed"):
                self.controller.plan("export_markers")
            manifest["stages"][5]["status"] = "passed"
            (self.project / "run.json").write_text(json.dumps(manifest))
            plan = self.controller.plan("export_markers")
            self.assertIn("--no-mot", plan.command)
            self.assertEqual(plan.action, "export_markers")
            self.assertEqual(Path(plan.command[plan.command.index("--trc")+1]), trc)
            out = Path(plan.command[plan.command.index("--out")+1])
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(b"old")
            with self.assertRaisesRegex(WorkflowBlocked, "exists"):
                self.controller.plan("export_markers")

    def test_missing_stage_quality_is_never_a_pass(self):
        self.register_fixture()
        from native_evidence_fixture import complete_native_fixture
        from test_export_motion import trc_text
        path, _, _ = complete_native_fixture(self.project, trc_text())
        run = json.loads(path.read_text())
        run["stages"][0].pop("quality")
        (self.project / "run.json").write_text(json.dumps(run))
        with patch.object(self.controller, "_verify_preflight", return_value=None), self.assertRaisesRegex(WorkflowBlocked, "quality"):
            self.controller.plan("export_markers")

    def test_mixed_sample_fixture_never_passes_as_real(self):
        self.register_fixture()
        (self.project / "SAMPLE-PROVENANCE.json").write_text("{}")
        with self.assertRaisesRegex(WorkflowBlocked, "test-only"):
            self.controller.plan("normalize")

    def test_invalid_action_fails_without_starting_camera_or_process(self):
        self.register_fixture()
        with self.assertRaisesRegex(WorkflowBlocked, "Unknown"):
            self.controller.plan("delete-all")
        self.assertFalse((self.project / "workflow.lock").exists())

    def test_native_failed_process_cannot_be_recorded_as_passed(self):
        self.register_fixture()
        class FakeProcess:
            def __init__(self): self.pid=99
            def poll(self): return 0
        with patch("workflow_controller.subprocess.Popen", return_value=FakeProcess()):
            self.controller.start("normalize")
        status = self.controller.poll()
        self.assertEqual(status.state, "failed")
        self.assertFalse(status.passed)
        self.assertFalse((self.project / "workflow.lock").exists())

    def test_real_native_failure_stays_failed_and_unlocks(self):
        import shutil
        if not shutil.which("ffprobe"):
            self.skipTest("FFprobe unavailable for native child integration")
        self.register_fixture()
        before = {role: sha256_file(self.raw / (role + ".mp4")) for role in ROLES}
        started = self.controller.start("normalize")
        self.assertEqual(started.state, "running")
        self.controller.process.wait(timeout=25)
        result = self.controller.poll()
        self.assertEqual(result.state, "failed")
        self.assertFalse(result.passed)
        self.assertFalse((self.project / "workflow.lock").exists())
        self.assertFalse((self.project / "preflight.json").exists())
        self.assertEqual(before, {role: sha256_file(self.raw / (role + ".mp4")) for role in ROLES})

    def test_cancel_request_only_stops_after_current_action(self):
        self.register_fixture()
        class FakeProcess:
            def __init__(self): self.pid=99
            def poll(self): return None
        with patch("workflow_controller.subprocess.Popen", return_value=FakeProcess()):
            self.controller.start("normalize")
        self.assertEqual(self.controller.request_cancel(), "Stop requested after current action")
        self.assertTrue(self.controller.cancel_requested)
        self.assertTrue((self.project / "workflow.lock").is_file())
        self.controller._cleanup_lock()  # Test-created fake process only.

    def test_explicit_cancel_stops_only_expected_process_tree_and_marks_unverified(self):
        self.register_fixture()
        script = str(Path(__file__).resolve().parents[1] / "normalize_capture.py")
        class FakeProcess:
            pid = 9876
            returncode = None
            def poll(self): return self.returncode
        process = FakeProcess()
        class FakePsProcess:
            def cmdline(self): return ["python.exe", script, "--project", str(self.project)]
            def children(self, recursive=False): return []
            def terminate(self): process.returncode = 1
        fake_ps = FakePsProcess()
        fake_ps.project = self.project
        with patch("workflow_controller.subprocess.Popen", return_value=process):
            self.controller.start("normalize")
        with patch("workflow_controller.psutil.Process", return_value=fake_ps) as lookup, patch("workflow_controller.psutil.wait_procs", return_value=([fake_ps], [])):
            message = self.controller.cancel_now()
        self.assertIn("cancel", message.lower())
        lookup.assert_called_once_with(9876)
        outcome = self.controller.poll()
        self.assertEqual(outcome.state, "cancelled")
        self.assertFalse(outcome.passed)
        self.assertFalse((self.project / "workflow.lock").exists())

    def test_real_child_process_cancel_does_not_touch_originals(self):
        import sys
        import time

        from workflow_controller import WorkflowPlan
        self.register_fixture()
        sleeper = Path(self.temp.name) / "safe-test-sleeper.py"
        sleeper.write_text("import time; time.sleep(15)", encoding="utf-8")
        plan = WorkflowPlan("normalize", (sys.executable, "-B", str(sleeper),
                                          "--project", str(self.project)), "test sleeper")
        original_hashes = {role: sha256_file(self.raw / (role + ".mp4")) for role in ROLES}
        with patch.object(self.controller, "plan", return_value=plan):
            self.controller.start("normalize")
        try:
            deadline = time.monotonic() + 5
            while self.controller.process.poll() is None:
                try:
                    note = self.controller.cancel_now()
                    self.assertIn("unverified", note.lower())
                    break
                except WorkflowBlocked as error:
                    if "exited" not in str(error) and "identity" not in str(error):
                        raise
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)
            self.controller.process.wait(timeout=10)
            status = self.controller.poll()
            self.assertEqual(status.state, "cancelled")
            self.assertFalse(status.passed)
            self.assertFalse((self.project / "workflow.lock").exists())
            self.assertEqual(original_hashes,
                             {role: sha256_file(self.raw / (role + ".mp4")) for role in ROLES})
        finally:
            if self.controller.process is not None and self.controller.process.poll() is None:
                self.controller.process.kill()
            self.controller._cleanup_lock()

    def test_cancel_refuses_unidentified_foreign_pid(self):
        self.register_fixture()
        class FakeProcess:
            pid = 9876
            def poll(self): return None
        with patch("workflow_controller.subprocess.Popen", return_value=FakeProcess()):
            self.controller.start("normalize")
        class Foreign:
            def cmdline(self): return ["notepad.exe", "somewhere-else.txt"]
        with patch("workflow_controller.psutil.Process", return_value=Foreign()), self.assertRaisesRegex(WorkflowBlocked, "identity"):
            self.controller.cancel_now()
        self.assertTrue((self.project / "workflow.lock").exists())
        self.controller._cleanup_lock()

    def test_cannot_double_start_or_reuse_same_running_lock(self):
        self.register_fixture()
        class FakeProcess:
            def __init__(self): self.pid=99
            def poll(self): return None
        with patch("workflow_controller.subprocess.Popen", return_value=FakeProcess()):
            self.controller.start("normalize")
        with self.assertRaisesRegex(WorkflowBlocked, "busy"):
            self.controller.start("normalize")
        other = WorkflowController(self.project)
        with self.assertRaisesRegex(WorkflowBlocked, "busy"):
            other.start("normalize")
        self.controller._cleanup_lock()


if __name__ == "__main__":
    unittest.main()
