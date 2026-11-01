"""Generated strict state boundaries; no production scheduler activation."""
from __future__ import annotations

import copy
import unittest

import test_backup_schedule_engine as fixture_module
from backup_schedule import BackupScheduleError


class BackupScheduleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.BackupScheduleEngineTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.engine

    def test_00_numeric_bool_nonfinite_schedule_identity_refuses_before_publication(self):
        before = self.fixture.snapshot()
        for identity in (int("1" * 32), True, False, float("nan"), float("inf"), None):
            with self.subTest(identity=repr(identity)):
                with self.assertRaisesRegex(BackupScheduleError, "BACKUP_SCHEDULE_STATE_INVALID"):
                    self.engine.install_test_plan(schedule_id=identity, first_due=100, interval=10, grace=2, now=90)
                self.assertEqual(self.fixture.snapshot(), before)

    def test_01_numeric_receipt_identities_refuse_actual_success_replay(self):
        self.fixture.plan()
        self.assertEqual(self.engine.tick(now=100)["last_job"]["status"], "SUCCEEDED")
        events = self.engine._load()
        before = self.fixture.snapshot()
        for field, number in (("generation_id", int("1" * 32)), ("sha256", int("1" * 64))):
            for value in (number, True, float("nan"), float("inf")):
                with self.subTest(field=field, value=repr(value)):
                    changed = copy.deepcopy(events)
                    changed[-1]["data"]["verification"][field] = value
                    with self.assertRaisesRegex(BackupScheduleError, "BACKUP_SCHEDULE_STATE_INVALID"):
                        self.engine._state(changed)
                    self.assertEqual(self.fixture.snapshot(), before)

    def test_02_timestamps_reject_bool_nonfinite_fractional_and_out_of_range(self):
        before = self.fixture.snapshot()
        for field in ("first_due", "now"):
            for value in (True, False, float("nan"), float("inf"), 1.5, -1, 253402300800):
                with self.subTest(field=field, value=repr(value)):
                    arguments = {"schedule_id": "a" * 32, "first_due": 100, "interval": 10, "grace": 2, "now": 90}
                    arguments[field] = value
                    with self.assertRaisesRegex(BackupScheduleError, "BACKUP_SCHEDULE_STATE_INVALID"):
                        self.engine.install_test_plan(**arguments)
                    self.assertEqual(self.fixture.snapshot(), before)
