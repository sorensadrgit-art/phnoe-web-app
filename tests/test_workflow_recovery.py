"""Stale native lock recovery is explicit, logged and never fakes a passed stage."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_library import SessionLibrary
from workflow_recovery import (
    RecoveryBlocked,
    archive_orphaned_lock,
    inspect_recovery,
)


class WorkflowRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "projects"
        root.mkdir()
        self.project = SessionLibrary(root).create_session("recover-01")

    def tearDown(self):
        self.temp.cleanup()

    def test_clean_session_remains_unmodified_on_inspection(self):
        before = {p.relative_to(self.project) for p in self.project.rglob("*")}
        result = inspect_recovery(self.project)
        self.assertEqual(result["locks"]["run.lock"]["state"], "absent")
        self.assertEqual(result["locks"]["workflow.lock"]["state"], "absent")
        self.assertEqual(result["native_run"], "not-run")
        after = {p.relative_to(self.project) for p in self.project.rglob("*")}
        self.assertEqual(before, after)

    def test_orphaned_lock_requires_confirmed_explicit_archive(self):
        lock = self.project / "run.lock"
        lock.write_text("987654321")
        with patch("workflow_recovery.psutil.pid_exists", return_value=False), \
             patch("workflow_recovery._related_processes", return_value=[]):
            state = inspect_recovery(self.project)
            self.assertEqual(state["locks"]["run.lock"]["state"], "orphaned")
            with self.assertRaisesRegex(RecoveryBlocked, "confirm"):
                archive_orphaned_lock(self.project, "run.lock", confirmed=False)
            self.assertEqual(lock.read_text(), "987654321")
            result = archive_orphaned_lock(self.project, "run.lock", confirmed=True)
        self.assertFalse(lock.exists())
        self.assertTrue(result.is_file())
        self.assertEqual(result.read_text(), "987654321")
        self.assertTrue(result.parent.is_relative_to(self.project))
        self.assertEqual(inspect_recovery(self.project)["locks"]["run.lock"]["state"], "absent")

    def test_process_still_running_blocks_orphan_archive(self):
        (self.project / "workflow.lock").write_text("987654321:abcdef0123456789abcdef0123456789")
        with patch("workflow_recovery.psutil.pid_exists", return_value=True), \
             patch("workflow_recovery._related_processes", return_value=[]):
            self.assertEqual(inspect_recovery(self.project)["locks"]["workflow.lock"]["state"], "active")
            with self.assertRaises(RecoveryBlocked):
                archive_orphaned_lock(self.project, "workflow.lock", confirmed=True)
        self.assertTrue((self.project / "workflow.lock").exists())

    def test_related_process_blocks_archive_even_if_lock_pid_is_dead(self):
        (self.project / "run.lock").write_text("987654321")
        with patch("workflow_recovery.psutil.pid_exists", return_value=False), \
             patch("workflow_recovery._related_processes", return_value=[1234]):
            status = inspect_recovery(self.project)
            self.assertEqual(status["locks"]["run.lock"]["state"], "unsafe-related-process")
            with self.assertRaises(RecoveryBlocked):
                archive_orphaned_lock(self.project, "run.lock", confirmed=True)
        self.assertTrue((self.project / "run.lock").is_file())

    def test_malformed_lock_cannot_be_archived(self):
        (self.project / "run.lock").write_text("unknown-secret-process")
        with patch("workflow_recovery._related_processes", return_value=[]):
            self.assertEqual(inspect_recovery(self.project)["locks"]["run.lock"]["state"], "unknown")
            with self.assertRaises(RecoveryBlocked):
                archive_orphaned_lock(self.project, "run.lock", confirmed=True)

    def test_only_exact_workflow_or_native_locks_allowed(self):
        with self.assertRaises(RecoveryBlocked):
            archive_orphaned_lock(self.project, "../session.json", confirmed=True)

    def test_failed_or_running_native_stages_remain_untrusted(self):
        (self.project / "run.json").write_text(json.dumps({
            "schema": "kinelab.run.v1", "stages": [
                {"name": "calibration", "status": "passed"},
                {"name": "poseEstimation", "status": "running"},
                {"name": "synchronization", "status": "failed"},
            ],
        }))
        result = inspect_recovery(self.project)
        self.assertEqual(result["native_run"], "incomplete")
        self.assertIn("poseEstimation", result["incomplete_stages"])
        self.assertIn("synchronization", result["incomplete_stages"])
        self.assertFalse(result["native_run_passed"])


if __name__ == "__main__":
    unittest.main()
