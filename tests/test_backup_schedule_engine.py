"""SOURCE-ONLY R18 candidates; generated projects, actual BackupManager, no devices."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backup_manager import BackupManager
from backup_schedule import (
    TEST_DECLARATION,
    BackupSchedule,
    BackupScheduleError,
    BackupSchedulePump,
    canonical,
)
from runtime_config import startup_lock
from session_index import SessionIndex
from session_library import SessionLibrary


class BackupScheduleEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="TEST_ONLY-R18-engine-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "projects"
        self.root.mkdir()
        (self.root / "TEST_ONLY_SCHEDULER.json").write_bytes(canonical(TEST_DECLARATION))
        self.index = SessionIndex(self.root / ".kinelab_index.db", self.root)
        self.addCleanup(self.index.close)
        self.library = SessionLibrary(self.root)
        session = self.library.create_session("TEST_ONLY-scheduler-demo", kind="demo")
        (session / "TEST_ONLY.txt").write_bytes(b"Generated scheduler test fixture; no recording")
        self.manager = BackupManager(self.root, self.index)
        self.engine = BackupSchedule(self.manager, test_only=True)

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file()}

    def plan(self, *, first_due=100, interval=10, grace=2):
        self.engine.install_test_plan(schedule_id="a" * 32, first_due=first_due, interval=interval, grace=grace, now=90)

    def test_00_default_disabled_and_public_activation_pruning_refuse_without_writes(self):
        engine = BackupSchedule(self.manager)
        before = self.snapshot()
        self.assertEqual(engine.status()["state"], "DISABLED")
        self.assertIs(engine.status()["enabled"], False)
        self.assertIsNone(engine.status()["last_verified_recovery_point"])
        engine.configure({"enabled": False, "confirm": True})
        with self.assertRaisesRegex(BackupScheduleError, "POLICY_REQUIRED"):
            engine.configure({"enabled": True, "confirm": True})
        with self.assertRaisesRegex(BackupScheduleError, "PRUNING_UNAVAILABLE"):
            engine.prune()
        self.assertEqual(before, self.snapshot())

    def test_01_generated_tick_completely_verifies_archive_and_replay_is_no_write(self):
        self.plan()
        result = self.engine.tick(now=100)
        self.assertEqual(result["last_job"]["status"], "SUCCEEDED")
        proof = result["last_verified_archive"]
        archive = self.root / "backups" / proof["archive"]
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), proof["sha256"])
        self.assertEqual(archive.stat().st_size, proof["bytes"])
        self.assertEqual(proof["verification_kind"], "CREATED_AND_MEMBER_HASH_VERIFIED")
        self.assertIsNone(result["last_verified_recovery_point"])
        self.assertIs(self.manager.inspect_backup(archive)["hashes_verified"], False)
        before = self.snapshot()
        self.assertEqual(self.engine.tick(now=100), result)
        self.assertEqual(before, self.snapshot())

    def test_02_restart_retains_failed_and_missed_jobs_without_adopting_success(self):
        self.plan()
        self.engine.tick(now=100, busy=True)
        restarted = BackupSchedule(self.manager, test_only=True)
        restarted.recover(now=101)
        self.assertEqual(restarted.status()["last_job"]["status"], "FAILED")
        restarted.tick(now=125)
        again = BackupSchedule(self.manager, test_only=True).status()
        self.assertEqual(again["last_job"]["status"], "MISSED")
        self.assertEqual(again["missed_count"], 2)
        self.assertIsNone(again["last_verified_archive"])
        self.assertFalse((self.root / "backups").exists())

    def test_03_real_process_death_retains_archive_and_recovery_is_idempotent(self):
        self.plan()
        self.index.close()
        program = (
            "import os,sys; from pathlib import Path; from backup_manager import BackupManager; "
            "from session_index import SessionIndex; from backup_schedule import BackupSchedule; "
            "r=Path(sys.argv[1]); i=SessionIndex(r/'.kinelab_index.db',r); "
            "e=BackupSchedule(BackupManager(r,i),test_only=True); "
            "e.tick(now=100,checkpoint=lambda p: os._exit(71) if p=='after_archive' else None)"
        )
        completed = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", program, str(self.root)],
                                   capture_output=True, text=True, timeout=45, check=False)
        self.assertEqual(completed.returncode, 71, completed.stderr)
        archives = list((self.root / "backups").glob("*.zip"))
        self.assertEqual(len(archives), 1)
        original = archives[0].read_bytes()
        restarted = BackupSchedule(self.manager, test_only=True)
        restarted.recover(now=101)
        self.assertEqual(restarted.status()["last_job"]["status"], "INTERRUPTED")
        self.assertIsNone(restarted.status()["last_verified_archive"])
        before = self.snapshot()
        restarted.recover(now=102)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(archives[0].read_bytes(), original)

    def test_04_one_os_lease_and_busy_guard_precede_archive_creation(self):
        self.plan()
        with startup_lock(self.engine.control, timeout=0.0), self.assertRaises(TimeoutError):
            self.engine.tick(now=100)
        self.assertFalse((self.root / "backups").exists())
        self.engine.tick(now=100, busy=True)
        self.assertEqual(self.engine.status()["last_job"]["reason"], "BUSY")
        self.assertFalse((self.root / "backups").exists())

    def test_05_failed_complete_verification_never_acknowledges_success(self):
        self.plan()
        original_verify = self.manager._verify_members
        calls = []
        def refuse_second(*args, **kwargs):
            calls.append(None)
            if len(calls) == 2:
                raise ValueError("TEST_ONLY injected postpublication verification failure")
            return original_verify(*args, **kwargs)
        with patch.object(self.manager, "_verify_members", side_effect=refuse_second):
            result = self.engine.tick(now=100)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["last_job"]["status"], "FAILED")
        self.assertIsNone(result["last_verified_archive"])
        self.assertEqual(len(list((self.root / "backups").glob("*.zip"))), 1)

    def test_06_tampered_truncated_unknown_history_refuses_without_healing(self):
        self.plan()
        path = self.engine.events / "00000001.json"
        path.write_bytes(b"{TEST_ONLY interrupted write")
        before = self.snapshot()
        with self.assertRaisesRegex(BackupScheduleError, "STATE_INVALID"):
            self.engine.recover(now=100)
        self.assertEqual(before, self.snapshot())

    def test_07_capacity_is_reserved_before_any_archive_publication(self):
        self.plan()
        before = self.snapshot()
        with patch("backup_schedule.LIMIT", 4), self.assertRaisesRegex(BackupScheduleError, "CAPACITY"):
            self.engine.tick(now=100)
        self.assertEqual(before, self.snapshot())

    def test_08_test_only_engine_requires_persistent_exact_declaration(self):
        declaration = self.root / "TEST_ONLY_SCHEDULER.json"
        declaration.write_bytes(json.dumps({**TEST_DECLARATION, "enabled": True}).encode())
        before = self.snapshot()
        with self.assertRaisesRegex(BackupScheduleError, "TEST_ROOT_REQUIRED"):
            BackupSchedule(self.manager, test_only=True)
        self.assertEqual(before, self.snapshot())

    def test_09_pump_stops_owned_thread_and_retains_failure(self):
        reached = __import__("threading").Event()
        def fail_tick():
            reached.set()
            raise BackupScheduleError("TEST_ONLY failure")
        pump = BackupSchedulePump(fail_tick, interval=0.01)
        pump.start(test_engine=self.engine)
        self.assertTrue(reached.wait(2))
        with self.assertRaisesRegex(BackupScheduleError, "PUMP_FAILED"):
            pump.close()
        self.assertFalse(pump.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
