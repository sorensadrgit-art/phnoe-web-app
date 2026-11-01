"""Tests for SQLite session indexing, Evidence Passport state machine, and session comparison."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from session_index import SessionIndex
from session_library import SessionLibrary


class SessionIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.db_path = self.root / "index.db"
        self.index = SessionIndex(self.db_path, self.projects)
        self.library = SessionLibrary(self.projects)

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def test_schema_initialized_and_idempotent(self):
        self.assertTrue(self.db_path.is_file())
        # Re-opening does not fail or duplicate tables
        idx2 = SessionIndex(self.db_path, self.projects)
        self.assertEqual(len(idx2.query_sessions()), 0)
        idx2.close()

    def test_reindex_empty_and_draft_sessions(self):
        self.library.create_session("draft-01", kind="real")
        self.index.reindex()
        sessions = self.index.query_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], "draft-01")
        self.assertEqual(sessions[0]["kind"], "real")
        self.assertEqual(sessions[0]["status"], "draft")
        self.assertEqual(sessions[0]["captured_roles"], 0)

    def test_passport_state_empty_and_draft(self):
        self.library.create_session("draft-02", kind="real")
        self.index.reindex()
        passport = self.index.get_passport("draft-02")
        self.assertEqual(passport["state"], "EMPTY")
        self.assertFalse(passport["ready_to_register"])
        self.assertFalse(passport["clinically_validated"])
        self.assertIn("cam01_intrinsics", passport["missing_roles"])

    def test_passport_test_only_session_isolated(self):
        self.library.create_session("demo-01", kind="demo")
        self.index.reindex()
        passport = self.index.get_passport("demo-01")
        self.assertTrue(passport["is_test_only"])
        self.assertFalse(passport["can_register_real"])
        self.assertEqual(passport["badge"], "TEST ONLY")

    def test_session_comparison_requires_compatible_sessions(self):
        self.library.create_session("s1", kind="real")
        self.library.create_session("s2", kind="demo")
        self.index.reindex()
        comp = self.index.compare_sessions("s1", "s2")
        self.assertFalse(comp["compatible"])
        self.assertIn("incompatible", comp["reason"].lower())

    def test_two_empty_real_sessions_are_not_compatible_measurements(self):
        self.library.create_session("empty-a", kind="real")
        self.library.create_session("empty-b", kind="real")
        self.index.reindex()
        comparison = self.index.compare_sessions("empty-a", "empty-b")
        self.assertFalse(comparison["compatible"])
        self.assertIn("evidence", comparison["reason"].lower())

    def test_backup_database_produces_consistent_copy(self):
        self.library.create_session("backup-test", kind="real")
        self.index.reindex()
        backup_file = self.root / "backup.db"
        self.index.backup_database(backup_file)
        self.assertTrue(backup_file.is_file())
        idx_backup = SessionIndex(backup_file, self.projects)
        self.assertEqual(len(idx_backup.query_sessions()), 1)
        idx_backup.close()


if __name__ == "__main__":
    unittest.main()
