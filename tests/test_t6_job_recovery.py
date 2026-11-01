"""Main service journal wiring with synthetic sessions and fake native workers."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from t6_service import IntegratedService, IntegrationBlocked
from workflow_controller import WorkflowPlan, WorkflowStatus


class T6JobRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.service = self.open_service()
        self.service.create_session("job-fixture")
        self.project = self.root / "job-fixture"
        self.running = WorkflowStatus("normalize", "running", "Synthetic running", False)
        self.worker = Mock()
        self.worker.plan.return_value = WorkflowPlan("normalize", (), "Synthetic plan")
        self.worker.start.return_value = self.running
        self.worker.poll.return_value = self.running

    def open_service(self):
        service = IntegratedService(self.root)
        self.addCleanup(service.close)
        return service

    def start(self):
        with patch("t6_service.WorkflowController", return_value=self.worker):
            return self.service.start_processing("job-fixture", "normalize", confirm=True)

    def events(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.project / "workflow-journal").glob("*.json"))]

    def test_restart_exposes_operation_and_blocks_native_retry_and_cancel(self):
        started = self.start()
        fresh = self.open_service()
        recovered = fresh.processing_status("job-fixture")
        self.assertEqual(recovered["state"], "recovery-required")
        self.assertEqual(recovered["operation_id"], started["operation_id"])
        with patch("t6_service.WorkflowController") as worker, self.assertRaises(IntegrationBlocked):
            fresh.start_processing("job-fixture", "normalize", confirm=True)
        worker.assert_not_called()
        with self.assertRaises(IntegrationBlocked):
            fresh.cancel_processing("job-fixture", confirm=True)

    def test_legacy_lock_is_not_idle_or_removed(self):
        lock = self.project / "workflow.lock"
        lock.write_text("generated-owner", encoding="utf-8")
        self.assertEqual(self.service.processing_status("job-fixture")["state"], "recovery-required")
        self.assertEqual(lock.read_text(encoding="utf-8"), "generated-owner")

    def test_persistence_failure_prevents_native_start(self):
        with (patch("t6_service.WorkflowController", return_value=self.worker),
              patch("unified_service.os.fsync", side_effect=OSError("synthetic disk fault")),
              self.assertRaises(OSError)):
            self.service.start_processing("job-fixture", "normalize", confirm=True)
        self.worker.start.assert_not_called()

    def test_close_interrupts_only_owned_work_and_preserves_history(self):
        self.start()
        before = self.events()
        other = self.open_service()
        other.processing_status("job-fixture")
        other.close()
        self.assertEqual(self.events(), before)
        self.service.close()
        self.worker.cancel_now.assert_not_called()
        self.assertEqual([event["state"] for event in self.events()], ["starting", "running", "interrupted"])
        self.assertEqual(self.events()[:2], before)
        self.service.close()
        self.assertEqual(len(self.events()), 3)

    def test_prior_completion_is_observed_before_next_operation(self):
        self.start()
        self.worker.poll.return_value = WorkflowStatus("normalize", "passed", "Synthetic pass", True)
        second = self.start()
        self.assertEqual(second["state"], "running")
        self.assertEqual([event["state"] for event in self.events()], ["starting", "running", "passed", "starting", "running"])

    def test_restart_does_not_inherit_prior_pass(self):
        self.start()
        self.worker.poll.return_value = WorkflowStatus("normalize", "passed", "Synthetic pass", True)
        self.assertTrue(self.service.processing_status("job-fixture")["passed"])
        fresh = self.open_service().processing_status("job-fixture")
        self.assertEqual(fresh["state"], "completed-unverified")
        self.assertFalse(fresh["passed"])

    def test_failed_launch_is_interrupted_without_retaining_worker(self):
        self.worker.start.side_effect = OSError("synthetic launch failure")
        with self.assertRaises(OSError):
            self.start()
        self.assertNotIn("job-fixture", self.service.jobs)
        self.assertEqual([event["state"] for event in self.events()], ["starting", "interrupted"])

    def test_close_surfaces_interruption_failure_but_closes_index(self):
        self.start()
        journal = self.service.job_journals["job-fixture"]
        with patch.object(journal, "interrupt", side_effect=OSError("synthetic flush failure")), patch.object(self.service.index, "close", wraps=self.service.index.close) as close:
            with self.assertRaisesRegex(OSError, "synthetic flush failure"):
                self.service.close()
            close.assert_called_once_with()
        self.assertIsNone(self.service.index.conn)
