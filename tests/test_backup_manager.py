"""Tests for local backup creation, manifest verification, and staged restore."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backup_manager import BackupConflictError, BackupCorruptError, BackupManager
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
        self.assertEqual(manifest["schema"], "kinelab.backup.v2")
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
                restore_mgr.restore_generation(tampered_zip, self.root / "new-generation")
            # Verify no corrupt session was published into target
            self.assertFalse((self.root / "new-generation").exists())
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
            self.mgr.restore_generation(zip_dest, self.projects)

        # Approved M1 containment: overwrite is unavailable and bytes are untouched.
        before = (s_folder / "file.txt").read_bytes()
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_OVERWRITE_UNAVAILABLE"):
            self.mgr.restore_backup(zip_dest, overwrite=True)
        self.assertEqual((s_folder / "file.txt").read_bytes(), before)

V1_SESSION_FILES = {"Config.toml": b"# legacy v1 config\n", "notes.txt": b"legacy bytes"}


def build_v1_archive(zip_path: Path, sessions: dict[str, dict[str, bytes]]) -> dict:
    """Build a genuine kinelab.backup.v1 archive in the layout the pre-v2 creator wrote."""
    import hashlib
    import json
    import zipfile
    files = []
    members = []
    for sid, contents in sessions.items():
        for name, data in contents.items():
            relative = f"sessions/{sid}/{name}"
            files.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            members.append((relative, data))
    manifest = {
        "schema": "kinelab.backup.v1",
        "created_at_utc": "2025-01-01T00:00:00+00:00",
        "host": "legacy-host",
        "sessions": sorted(sessions),
        "database_included": False,
        "file_count": len(files),
        "files": files,
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup_manifest.json", json.dumps(manifest, indent=2))
        for relative, data in members:
            archive.writestr(relative, data)
    return manifest


class LegacyV1BackupTests(unittest.TestCase):
    """Regression coverage for reading archives written by the kinelab.backup.v1 creator."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.index = SessionIndex(self.root / "index.db", self.projects)
        self.library = SessionLibrary(self.projects)
        self.mgr = BackupManager(self.projects, self.index)

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def _v1_zip(self, name: str = "legacy.zip") -> Path:
        zip_path = self.root / name
        build_v1_archive(zip_path, {"v1sess": dict(V1_SESSION_FILES)})
        return zip_path

    def test_v1_inspect_and_import_into_fresh_root(self):
        zip_path = self._v1_zip()
        inspection = self.mgr.inspect_backup(zip_path)
        self.assertEqual(inspection["schema"], "kinelab.backup.v1")
        self.assertEqual(inspection["recovery_scope"], "legacy_session_import")
        self.assertEqual(inspection["sessions"], ["v1sess"])
        self.assertEqual(inspection["file_count"], 2)
        self.assertFalse(inspection["database_included"])

        result = self.mgr.restore_backup(zip_path)
        self.assertTrue(result["ok"])
        self.assertEqual(result["restored_sessions"], ["v1sess"])
        self.assertFalse(result["database_restored"])
        restored = self.projects / "v1sess"
        self.assertEqual((restored / "Config.toml").read_bytes(), V1_SESSION_FILES["Config.toml"])
        self.assertEqual((restored / "notes.txt").read_bytes(), b"legacy bytes")

    def test_v1_import_preserves_unrelated_existing_sessions(self):
        existing = self.library.create_session("existing-sess", kind="real")
        (existing / "data.txt").write_text("keep me", encoding="utf-8")
        self.index.reindex()

        result = self.mgr.restore_backup(self._v1_zip())
        self.assertTrue(result["ok"])
        self.assertEqual((existing / "data.txt").read_text(encoding="utf-8"), "keep me")
        self.assertTrue((self.projects / "v1sess" / "Config.toml").is_file())

    def test_v1_conflicting_session_is_never_overwritten(self):
        conflict = self.library.create_session("v1sess", kind="real")
        before = (conflict / "Config.toml").read_bytes()

        with self.assertRaises(BackupConflictError):
            self.mgr.restore_backup(self._v1_zip())
        self.assertEqual((conflict / "Config.toml").read_bytes(), before)
        self.assertFalse((conflict / "notes.txt").exists())

    def test_v1_restore_generation_refused_explicitly(self):
        with self.assertRaisesRegex(BackupCorruptError, "legacy archive has no complete recovery generation"):
            self.mgr.restore_generation(self._v1_zip(), self.root / "new-generation")
        self.assertFalse((self.root / "new-generation").exists())

    def test_tampered_v1_member_fails_hash_verification(self):
        import zipfile
        zip_path = self._v1_zip()
        with zipfile.ZipFile(zip_path) as source:
            manifest_bytes = source.read("backup_manifest.json")
            config_bytes = source.read("sessions/v1sess/Config.toml")
        tampered = self.root / "tampered-v1.zip"
        with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("backup_manifest.json", manifest_bytes)
            archive.writestr("sessions/v1sess/Config.toml", config_bytes)
            archive.writestr("sessions/v1sess/notes.txt", b"tampered bytes!!")

        with self.assertRaises(BackupCorruptError):
            self.mgr.restore_backup(tampered)
        self.assertFalse((self.projects / "v1sess").exists())

if __name__ == "__main__":
    unittest.main()
