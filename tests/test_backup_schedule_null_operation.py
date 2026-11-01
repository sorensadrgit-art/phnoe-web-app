"""Generated journal trust-boundary regression; no scheduler activation."""
from __future__ import annotations

import unittest

import test_backup_schedule_engine as fixture_module
from backup_schedule import SCHEMA, BackupScheduleError, canonical


class BackupScheduleNullOperationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.BackupScheduleEngineTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.engine

    def test_00_null_running_id_refuses_as_domain_error_without_journal_writes(self):
        event = {
            "schema": SCHEMA,
            "sequence": 1,
            "previous_sha256": None,
            "type": "RUNNING",
            "at": 100,
            "data": {"operation_id": None},
        }
        self.engine.events.mkdir(parents=True)
        journal = self.engine.events / "00000001.json"
        raw = canonical(event)
        with journal.open("xb") as stream:
            self.assertEqual(stream.write(raw), len(raw))
        before = self.fixture.snapshot()

        # Persisted untrusted input reaches the shared validator. Public reads
        # already fail closed; they must neither heal it nor create a lock.
        status = self.engine.status()
        self.assertEqual(status["journal_health"], "RECOVERY_REQUIRED")
        self.assertIs(status["historical_prefix_only"], True)
        self.assertIsNone(status["last_job"])
        self.assertIsNone(status["last_verified_archive"])
        self.engine.recover(now=100, strict=False)
        self.assertEqual(self.fixture.snapshot(), before)

        # Classify the actual shared refusal rather than letting the existing
        # KeyError be mistaken for a fixture/import failure in the RED run.
        try:
            with self.assertRaises((ValueError, KeyError)) as caught:
                self.engine._state([event])
            self.assertIsInstance(caught.exception, BackupScheduleError)
            self.assertEqual(
                str(caught.exception),
                "BACKUP_SCHEDULE_STATE_INVALID: running transition",
            )
        finally:
            self.assertEqual(self.fixture.snapshot(), before)
            self.assertEqual(journal.read_bytes(), raw)
