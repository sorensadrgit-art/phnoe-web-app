"""Unexecuted R18 generated boundary regressions; no production activation."""
from __future__ import annotations

import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import test_backup_schedule_engine as fixture_module
from backup_schedule import BackupSchedule, BackupScheduleError, BackupSchedulePump


class BackupScheduleBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.BackupScheduleEngineTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.engine
        self.manager = self.fixture.manager

    def test_00_backward_clock_before_due_is_durable_and_restart_stays_disabled(self):
        self.fixture.plan()
        with self.assertRaisesRegex(BackupScheduleError, "CLOCK_UNCERTAIN"):
            self.engine.tick(now=80)
        status = BackupSchedule(self.manager, test_only=True).status()
        self.assertEqual(status["clock_health"], {"observed_utc": 80, "reference_utc": 90})
        self.assertIs(status["enabled"], False)
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(BackupScheduleError, "RECOVERY_REQUIRED"):
            self.engine.tick(now=100)
        self.assertEqual(before, self.fixture.snapshot())
        self.assertFalse((self.fixture.root / "backups").exists())

    def test_01_torn_final_record_retains_prior_success_and_refuses_healing(self):
        self.fixture.plan()
        success = self.engine.tick(now=100)["last_verified_archive"]
        (self.engine.events / "00000005.json").write_bytes(b'{"TEST_ONLY":')
        before = self.fixture.snapshot()
        status = BackupSchedule(self.manager, test_only=True).status()
        self.assertEqual(status["journal_health"], "RECOVERY_REQUIRED")
        self.assertEqual(status["last_verified_archive"], success)
        self.assertIs(status["historical_prefix_only"], True)
        with self.assertRaisesRegex(BackupScheduleError, "STATE_INVALID"):
            self.engine.recover(now=110)
        with self.assertRaisesRegex(BackupScheduleError, "STATE_INVALID"):
            self.engine.tick(now=110)
        self.assertEqual(before, self.fixture.snapshot())

    def test_02_process_death_before_link_preserves_success_and_preparation(self):
        self.fixture.plan()
        success = self.engine.tick(now=100)["last_verified_archive"]
        self.fixture.index.close()
        program = (
            "import os,sys; from pathlib import Path; from unittest.mock import patch; "
            "from backup_manager import BackupManager; from session_index import SessionIndex; "
            "from backup_schedule import BackupSchedule; r=Path(sys.argv[1]); "
            "i=SessionIndex(r/'.kinelab_index.db',r); e=BackupSchedule(BackupManager(r,i),test_only=True); "
            "p=patch('backup_schedule.os.link',side_effect=lambda *a,**k:os._exit(72)); "
            "p.start(); e.tick(now=110)"
        )
        completed = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", program, str(self.fixture.root)],
                                   capture_output=True, text=True, timeout=45, check=False)
        self.assertEqual(completed.returncode, 72, completed.stderr)
        self.assertTrue((self.engine.control / "prepared" / "00000005.json").exists())
        self.assertFalse((self.engine.events / "00000005.json").exists())
        before = self.fixture.snapshot()
        status = BackupSchedule(self.manager, test_only=True).status()
        self.assertEqual(status["last_verified_archive"], success)
        self.assertEqual(status["journal_health"], "RECOVERY_REQUIRED")
        with self.assertRaisesRegex(BackupScheduleError, "STATE_INVALID"):
            self.engine.recover(now=111)
        self.assertEqual(before, self.fixture.snapshot())

    def test_03_completed_preparations_are_retained_and_replay_is_no_write(self):
        self.fixture.plan()
        original = self.engine.tick(now=100)
        prepared = self.engine.control / "prepared"
        self.assertEqual(sorted(p.name for p in prepared.iterdir()), [f"{i:08d}.json" for i in range(1, 5)])
        before = self.fixture.snapshot()
        self.assertEqual(BackupSchedule(self.manager, test_only=True).tick(now=100), original)
        self.assertEqual(before, self.fixture.snapshot())

    def test_04_pump_failure_without_job_survives_restart_and_blocks_work(self):
        self.fixture.plan()
        reached = threading.Event()
        def fail():
            reached.set()
            raise RuntimeError("TEST_ONLY generated pump failure")
        pump = BackupSchedulePump(fail, interval=0.01)
        pump.start(test_engine=self.engine)
        self.assertTrue(reached.wait(2))
        with self.assertRaisesRegex(BackupScheduleError, "PUMP_FAILED"):
            pump.close()
        status = BackupSchedule(self.manager, test_only=True).status()
        self.assertEqual(status["pump_health"]["reason"], "TICK_FAILED")
        self.assertEqual(status["engine_health"], "REVIEW_REQUIRED")
        self.assertIsNone(status["last_job"])
        self.assertIs(status["enabled"], False)
        with self.assertRaisesRegex(BackupScheduleError, "RECOVERY_REQUIRED"):
            self.engine.tick(now=status["pump_health"]["observed_utc"])

    def test_05_health_write_failure_preserves_primary_failure(self):
        reached = threading.Event()
        original = RuntimeError("TEST_ONLY primary failure")
        def fail():
            reached.set()
            raise original
        pump = BackupSchedulePump(fail, interval=0.01)
        with patch.object(self.engine, "record_pump_failure", side_effect=OSError("TEST_ONLY full disk")):
            pump.start(test_engine=self.engine)
            self.assertTrue(reached.wait(2))
            with self.assertRaisesRegex(BackupScheduleError, "HEALTH_UNRECORDED") as caught:
                pump.close()
        self.assertIs(pump.failure, original)
        self.assertIs(caught.exception.__cause__, original)
        self.assertIsInstance(pump.health_failure, OSError)
        self.assertIsNone(self.engine.status()["pump_health"])

    def test_06_readonly_startup_does_not_heal_torn_history_or_start_worker(self):
        self.fixture.plan()
        (self.engine.events / "00000002.json").write_bytes(b"TEST_ONLY torn")
        before = self.fixture.snapshot()
        with patch("backup_schedule.threading.Thread.start") as start:
            readonly = BackupSchedule(self.manager)
            readonly.recover(now=100, strict=False)
            self.assertEqual(readonly.status()["journal_health"], "RECOVERY_REQUIRED")
            start.assert_not_called()
        self.assertEqual(before, self.fixture.snapshot())

    def test_07_partial_preparation_never_discards_success_or_adopts_archive(self):
        self.fixture.plan()
        success = self.engine.tick(now=100)["last_verified_archive"]
        (self.engine.control / "prepared" / "00000005.json").write_bytes(b'{"TEST_ONLY":')
        before = self.fixture.snapshot()
        status = self.engine.status()
        self.assertEqual(status["last_verified_archive"], success)
        self.assertEqual(status["journal_health"], "RECOVERY_REQUIRED")
        self.assertIsNone(status["last_verified_recovery_point"])
        with self.assertRaisesRegex(BackupScheduleError, "STATE_INVALID"):
            self.engine.tick(now=110)
        self.assertEqual(before, self.fixture.snapshot())

