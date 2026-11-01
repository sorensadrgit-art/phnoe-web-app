"""Generated local fixtures only; no native worker, network, or process discovery."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_library import SessionLibrary
from unified_service import AppCore, AppError, WorkflowJobJournal
from workflow_controller import WorkflowPlan, WorkflowStatus


class JobRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.project = SessionLibrary(self.projects).create_session("job-fixture")
        self.core = self.new_core()
        self.plan = WorkflowPlan("normalize", (), "Synthetic worker fixture")
        self.running = WorkflowStatus("normalize", "running", "Fixture running", False)

    def new_core(self):
        return AppCore(self.projects, self.root / "dist", self.root / "samples", token="fixture")

    def start(self):
        with patch("unified_service.WorkflowController.plan", return_value=self.plan), \
             patch("unified_service.WorkflowController.start", return_value=self.running):
            return self.core.job_start("job-fixture", "normalize", True)["job"]

    def events(self):
        return sorted((self.project / "workflow-journal").glob("*.json"))

    def test_fresh_session_is_idle_without_writing(self):
        self.assertEqual(self.core.job("job-fixture")["job"]["state"], "idle")
        self.assertFalse((self.project / "workflow-journal").exists())

    def test_restart_keeps_identity_and_blocks_blind_retry_and_cancel(self):
        started = self.start()
        before = {p.name: p.read_bytes() for p in self.events()}
        fresh = self.new_core()
        state = fresh.job("job-fixture")["job"]
        self.assertEqual(state["state"], "recovery-required")
        self.assertEqual(state["operation_id"], started["operation_id"])
        self.assertEqual(state["session_id"], "job-fixture")
        self.assertFalse(state["passed"])
        self.assertTrue(state["recovery_required"])
        with patch("unified_service.WorkflowController.start") as start:
            with self.assertRaisesRegex(AppError, "recovery"):
                fresh.job_start("job-fixture", "normalize", True)
            start.assert_not_called()
        with self.assertRaises(AppError):
            fresh.job_cancel("job-fixture", True)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.events()})

    def test_legacy_native_lock_or_evidence_is_never_idle_or_cleared(self):
        for name in ("workflow.lock", "run.lock", "run.json", "normalization.json"):
            with self.subTest(name=name):
                target = self.project / name
                target.write_text("generated ambiguous evidence", encoding="utf-8")
                self.assertEqual(self.core.job("job-fixture")["job"]["state"], "recovery-required")
                self.assertEqual(target.read_text(encoding="utf-8"), "generated ambiguous evidence")
                target.unlink()  # Only generated test fixture.

    def test_torn_or_corrupt_journal_is_preserved_and_blocks_start(self):
        self.start()
        events = self.events()
        self.assertGreaterEqual(len(events), 2)
        for content in (b'{"torn":', b'{}', events[-1].read_bytes().replace(b'normalize', b'reconstruct')):
            with self.subTest(content=content[:20]):
                events[-1].write_bytes(content)
                fresh = self.new_core()
                state = fresh.job("job-fixture")["job"]
                self.assertEqual(state["state"], "recovery-required")
                self.assertFalse(state["passed"])
                with patch("unified_service.WorkflowController.start") as start:
                    with self.assertRaises(AppError):
                        fresh.job_start("job-fixture", "normalize", True)
                    start.assert_not_called()
                self.assertEqual(events[-1].read_bytes(), content)

    def test_terminal_observation_appends_and_restart_does_not_revalidate_success(self):
        started = self.start()
        before = {p.name: p.read_bytes() for p in self.events()}
        passed = WorkflowStatus("normalize", "passed", "Fixture evidence verified", True)
        with patch.object(self.core.jobs["job-fixture"], "poll", return_value=passed):
            current = self.core.job("job-fixture")["job"]
            self.assertTrue(current["passed"])
            self.core.job("job-fixture")
        self.assertEqual(len(self.events()), len(before) + 1)
        for name, contents in before.items():
            self.assertEqual((self.project / "workflow-journal" / name).read_bytes(), contents)
        recovered = self.new_core().job("job-fixture")["job"]
        self.assertEqual(recovered["operation_id"], started["operation_id"])
        self.assertEqual(recovered["state"], "completed-unverified")
        self.assertFalse(recovered["passed"])

    def test_journal_flush_failure_prevents_native_start(self):
        with patch("unified_service.WorkflowController.plan", return_value=self.plan), \
             patch("unified_service.WorkflowController.start") as start, \
             patch("unified_service.os.fsync", side_effect=OSError("generated disk fault")):
            with self.assertRaises((OSError, AppError)):
                self.core.job_start("job-fixture", "normalize", True)
            start.assert_not_called()
        self.assertEqual(self.new_core().job("job-fixture")["job"]["state"], "recovery-required")

    def test_explicit_interruption_preserves_owned_operation_without_terminating(self):
        started = self.start()
        with patch.object(self.core.jobs["job-fixture"], "cancel_now") as cancel:
            states = self.core.interrupt_jobs()
            cancel.assert_not_called()
        self.assertEqual(states[0]["operation_id"], started["operation_id"])
        self.assertEqual(self.new_core().job("job-fixture")["job"]["state"], "recovery-required")

    def test_replaced_session_source_identity_is_not_reused(self):
        self.start()
        with (self.project / "Config.toml").open("a", encoding="utf-8") as stream:
            stream.write("\n# changed generated identity\n")
        state = self.new_core().job("job-fixture")["job"]
        self.assertEqual(state["state"], "recovery-required")
        self.assertIn("identity", state["message"].lower())

    def test_confirmation_and_real_registration_gates_are_unchanged(self):
        with self.assertRaises(AppError):
            self.core.job_start("job-fixture", "normalize", False)
        with self.assertRaises(ValueError):
            self.core.job_start("job-fixture", "normalize", True)
        self.assertFalse((self.project / "workflow-journal").exists())

    def test_other_instance_cannot_append_observation_or_interruption(self):
        started = self.start()
        before = {p.name: p.read_bytes() for p in self.events()}
        other = WorkflowJobJournal(self.project, "different-service-instance")
        other.operation_id = started["operation_id"]
        with self.assertRaisesRegex(AppError, "own"):
            other.observe(self.running)
        other.interrupt()
        with self.assertRaises(AppError):
            other.begin("normalize")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.events()})

    def test_generation_gap_fails_closed_without_removing_remaining_history(self):
        self.start()
        events = self.events()
        first = events[0].read_bytes()
        events[0].unlink()  # Generated missing-event fault; production never removes entries.
        before = {p.name: p.read_bytes() for p in self.events()}
        state = self.new_core().job("job-fixture")["job"]
        self.assertEqual(state["state"], "recovery-required")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.events()})
        self.assertTrue(first)

    def test_stale_generation_cannot_race_a_new_operation(self):
        journal = WorkflowJobJournal(self.project, "first-owner")
        stale = WorkflowJobJournal(self.project, "second-owner")
        self.assertFalse(stale.status()["recovery_required"])
        journal.begin("normalize")
        with patch.object(stale, "status", return_value={"recovery_required": False}), self.assertRaisesRegex(AppError, "own"):
            stale.begin("normalize")
        self.assertEqual(len(self.events()), 1)

    def test_failed_native_start_is_interrupted_without_replaying(self):
        with (patch("unified_service.WorkflowController.plan", return_value=self.plan),
              patch("unified_service.WorkflowController.start", side_effect=OSError("generated launch fault")),
              self.assertRaises(OSError)):
            self.core.job_start("job-fixture", "normalize", True)
        self.assertNotIn("job-fixture", self.core.jobs)
        state = self.new_core().job("job-fixture")["job"]
        self.assertEqual(state["state"], "recovery-required")
        events = [json.loads(p.read_bytes()) for p in self.events()]
        self.assertEqual([e["state"] for e in events], ["starting", "interrupted"])

    def test_every_journal_event_flushes_before_start_is_acknowledged(self):
        observed = []
        with patch("unified_service.WorkflowController.plan", return_value=self.plan), \
             patch("unified_service.os.fsync", side_effect=lambda fd: observed.append("flush")), \
             patch("unified_service.WorkflowController.start", side_effect=lambda action: (observed.append("start") or self.running)):
            self.core.job_start("job-fixture", "normalize", True)
        self.assertEqual(observed, ["flush", "start", "flush"])

    def test_new_explicit_action_preserves_terminal_history_without_prior_status_poll(self):
        first = self.start()
        passed = WorkflowStatus("normalize", "passed", "Fixture verified", True)
        worker = self.core.jobs["job-fixture"]
        with patch.object(worker, "poll", return_value=passed):
            second = self.start()
        self.assertNotEqual(first["operation_id"], second["operation_id"])
        events = [json.loads(p.read_bytes()) for p in self.events()]
        self.assertEqual([e["state"] for e in events], ["starting", "running", "passed", "starting", "running"])


if __name__ == "__main__":
    unittest.main()
