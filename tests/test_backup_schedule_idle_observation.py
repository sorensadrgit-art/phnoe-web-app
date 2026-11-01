"""Generated TEST_ONLY durable idle observation boundaries; no production activation."""
from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch

import test_backup_schedule_engine as fixture_module
from backup_schedule import BackupSchedule, BackupScheduleError


class BackupScheduleIdleObservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.BackupScheduleEngineTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager
        self.engine = self.fixture.engine
        self.fixture.plan(first_due=200)

    def test_00_idle_tick_survives_restart_and_backward_tick_refuses(self):
        status = self.engine.tick(now=150)
        self.assertIs(status["enabled"], False)
        restarted = BackupSchedule(self.manager, test_only=True)
        with self.assertRaisesRegex(BackupScheduleError, "CLOCK_UNCERTAIN"):
            restarted.tick(now=140)
        status = restarted.status()
        self.assertEqual(status["clock_health"], {"observed_utc": 140, "reference_utc": 150})
        self.assertEqual(status["engine_health"], "REVIEW_REQUIRED")
        self.assertEqual(status["history"], [])
        self.assertIsNone(status["last_verified_archive"])
        before = self.fixture.snapshot()
        again = BackupSchedule(self.manager, test_only=True)
        with self.assertRaisesRegex(BackupScheduleError, "RECOVERY_REQUIRED"):
            again.tick(now=200)
        self.assertEqual(self.fixture.snapshot(), before)

    def test_01_equal_idle_tick_does_not_consume_more_journal(self):
        self.engine.tick(now=150)
        events = self.engine._load()
        self.assertEqual(events[-1]["type"], "CLOCK_OBSERVATION")
        self.assertEqual(events[-1]["at"], 150)
        before = self.fixture.snapshot()
        BackupSchedule(self.manager, test_only=True).tick(now=150)
        self.assertEqual(self.fixture.snapshot(), before)

    def test_02_process_death_after_observation_witness_refuses_restart(self):
        self.fixture.index.close()
        code = (
            "import os,sys; from pathlib import Path; from unittest.mock import patch; "
            "from backup_manager import BackupManager; from session_index import SessionIndex; "
            "from backup_schedule import BackupSchedule; r=Path(sys.argv[1]); "
            "i=SessionIndex(r/'.kinelab_index.db',r); e=BackupSchedule(BackupManager(r,i),test_only=True); "
            "p=patch('backup_schedule.os.link',side_effect=lambda *a,**k:os._exit(73)); "
            "p.start(); e.tick(now=150)"
        )
        completed = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code, str(self.fixture.root)],
                                   capture_output=True, text=True, timeout=45, check=False)
        self.assertEqual(completed.returncode, 73, completed.stderr)
        restarted = BackupSchedule(self.manager, test_only=True)
        self.assertEqual(restarted.status()["journal_health"], "RECOVERY_REQUIRED")
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(BackupScheduleError, "STATE_INVALID"):
            restarted.tick(now=140)
        self.assertEqual(self.fixture.snapshot(), before)

    def test_03_observation_fsync_failure_never_acknowledges_idle_tick(self):
        with patch("backup_schedule.os.fsync", side_effect=OSError("TEST_ONLY-write-failure")), self.assertRaisesRegex(OSError, "TEST_ONLY-write-failure"):
            self.engine.tick(now=150)
        restarted = BackupSchedule(self.manager, test_only=True)
        self.assertEqual(restarted.status()["journal_health"], "RECOVERY_REQUIRED")
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(BackupScheduleError, "STATE_INVALID"):
            restarted.tick(now=140)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertIsNone(restarted.status()["last_verified_archive"])
