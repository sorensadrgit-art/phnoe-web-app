"""Tests for local backup creation, manifest verification, and staged restore."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from backup_manager import BackupManager, BackupCorruptError, BackupConflictError
from session_index import SessionIndex
from session_library import SessionLibrary


class BackupManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.db_path = self.root / "index.db"
        self.index = SessionIndex(self.db_path, self.projects)
        self.library = SessionLibrary(self.projects)
        self.mgr = BackupManager(self.projects, self.index)

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def test_create_and_inspect_backup(self):
        s_folder = self.library.create_session("sess-backup-1", kind="real")
        (s_folder / "test_data.txt").write_text("Hello backup", encoding="utf-8")
        self.index.reindex()

        zip_dest = self.root / "backups" / "sess-backup-1.kinelab.zip"
        manifest = self.mgr.create_backup(zip_dest, session_ids=["sess-backup-1"])
        self.assertTrue(zip_dest.is_file())
        self.assertEqual(manifest["schema"], "kinelab.backup.v1")
        self.assertIn("sess-backup-1", manifest["sessions"])

        inspection = self.mgr.inspect_backup(zip_dest)
        self.assertEqual(inspection["session_count"], 1)
        self.assertTrue(inspection["database_included"])

    def test_corrupted_backup_fails_closed_in_staging(self):
        s_folder = self.library.create_session("sess-corrupt", kind="real")
        (s_folder / "orig.txt").write_text("Immutable content", encoding="utf-8")
        self.index.reindex()

        zip_dest = self.root / "corrupt.zip"
        self.mgr.create_backup(zip_dest, session_ids=["sess-corrupt"])

        # Tamper with the zip contents
        import zipfile
        staging_dir = self.root / "tamper"
        staging_dir.mkdir()
        with zipfile.ZipFile(zip_dest, "r") as z:
            z.extractall(staging_dir)
        # Modify a session file
        (staging_dir / "sessions" / "sess-corrupt" / "orig.txt").write_text("Tampered!", encoding="utf-8")
        tampered_zip = self.root / "tampered.zip"
        with zipfile.ZipFile(tampered_zip, "w") as z:
            for f in staging_dir.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(staging_dir))

        restore_target = self.root / "restored_projects"
        restore_target.mkdir()
        res_idx = SessionIndex(self.root / "res_idx.db", restore_target)
        restore_mgr = BackupManager(restore_target, res_idx)
        try:
            with self.assertRaises(BackupCorruptError):
                restore_mgr.restore_backup(tampered_zip)
            # Verify no corrupt session was published into target
            self.assertFalse((restore_target / "sess-corrupt").exists())
        finally:
            res_idx.close()

    def test_restore_conflict_detection_and_confirmed_overwrite(self):
        s_folder = self.library.create_session("sess-conflict", kind="real")
        (s_folder / "file.txt").write_text("Version A", encoding="utf-8")
        self.index.reindex()

        zip_dest = self.root / "conflict.zip"
        self.mgr.create_backup(zip_dest, session_ids=["sess-conflict"])

        # Attempt to restore into same projects directory without overwrite -> Conflict
        with self.assertRaises(BackupConflictError):
            self.mgr.restore_backup(zip_dest, overwrite=False)

        # Restoring with overwrite=True succeeds and preserves integrity
        result = self.mgr.restore_backup(zip_dest, overwrite=True)
        self.assertTrue(result["ok"])
        self.assertIn("sess-conflict", result["restored_sessions"])


if __name__ == "__main__":
    unittest.main()
