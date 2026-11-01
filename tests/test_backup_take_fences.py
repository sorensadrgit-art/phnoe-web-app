"""Generated backup/restore acceptance fences; no physical capture or native launch."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backup_manager import BackupConflictError, BackupCorruptError, BackupManager
from session_index import SessionIndex
from session_library import SessionLibrary
from t6_service import IntegratedService
from take_acceptance import TakeAcceptanceError, acceptance_lease, require_no_pending
from test_backup_manager import build_v1_archive


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(folder: Path) -> dict[str, tuple[bytes, int, int]]:
    return {path.relative_to(folder).as_posix(): (path.read_bytes(), path.stat().st_dev, path.stat().st_ino)
            for path in folder.rglob("*") if path.is_file()}


def _acceptance_files(session_id: str, *, terminal: bool = False) -> dict[str, bytes]:
    transaction_id = "a" * 32
    selected = b"GENERATED SELECTED TAKE BYTES"
    intent = {
        "schema": "kinelab.take-acceptance.v1", "transaction_id": transaction_id,
        "session_id": session_id, "role": "cam01_trial", "staged_name": "generated.mp4",
        "staged_sha256": _sha(selected), "staged_bytes": len(selected),
        "prior_sha256": None, "prior_bytes": None,
    }
    raw = json.dumps(intent).encode("utf-8")
    marker = json.dumps({"schema": "kinelab.take-acceptance-lock.v1", "transaction_id": transaction_id,
                         "intent_sha256": _sha(raw)}).encode("utf-8")
    prefix = f"takes/acceptance/{transaction_id}/"
    result = {prefix + "intent.json": raw}
    if terminal:
        receipt: dict[str, object] = {
            "schema": "kinelab.take-acceptance-commit.v1", "transaction_id": transaction_id,
            "session_id": session_id, "role": "cam01_trial", "outcome": "selected-verified",
            "canonical_sha256": _sha(selected), "prior_sha256": None, "archives_retained": True,
            "artifacts_quarantined": [], "native_run_passed": False, "clinical_validation": "UNVERIFIED",
            "intent_sha256": _sha(raw),
        }
        result[prefix + "commit.json"] = json.dumps(receipt).encode("utf-8")
        result[prefix + "accept.lock.archived"] = marker
    else:
        result["takes/accept.lock"] = marker
    return result


def _write_files(folder: Path, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


class BackupTakeFenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-legacy-restore-recovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.library = SessionLibrary(self.projects)
        self.project = self.library.create_session("existing-generated", kind="demo")
        (self.project / "fixture.txt").write_bytes(b"GENERATED ORIGINAL FILE")
        self.index = SessionIndex(self.projects / ".kinelab_index.db", self.projects)
        self.addCleanup(self.index.close)
        self.index.reindex()
        self.index.record_audit_event(self.project.name, "PRESERVE", {"synthetic": True})
        self.manager = BackupManager(self.projects, self.index)

    def test_public_backup_refuses_held_acceptance_lease_before_reindex(self):
        archive = self.root / "busy.zip"
        with acceptance_lease(self.project):
            pass
        sentinel = self.project / "takes/.acceptance-lease/t6-startup.lock"
        before = _snapshot(self.project)
        audit = self.index.verify_audit()
        with acceptance_lease(self.project):
            try:
                with (patch.object(self.index, "reindex", wraps=self.index.reindex) as reindex,
                      self.assertRaisesRegex(BackupCorruptError, "BACKUP_BUSY")):
                    self.manager.create_backup(archive)
            except OSError as error:
                self.fail(f"Busy acceptance must be refused before attempting locked-file reads: {error}")
            self.assertEqual(reindex.call_count, 0)
            self.assertFalse(archive.exists())
            self.assertEqual(self.index.verify_audit(), audit)
            self.assertTrue(sentinel.is_file())
        self.assertEqual(_snapshot(self.project), before)

    def test_public_backup_refuses_pending_intent_before_reindex_or_publication(self):
        with acceptance_lease(self.project):
            pass
        _write_files(self.project, _acceptance_files(self.project.name))
        before = _snapshot(self.project)
        audit = self.index.verify_audit()
        archive = self.root / "pending.zip"
        with (patch.object(self.index, "reindex", wraps=self.index.reindex) as reindex,
              self.assertRaisesRegex(BackupCorruptError, "BACKUP_BUSY")):
            self.manager.create_backup(archive)
        self.assertEqual(reindex.call_count, 0)
        self.assertFalse(archive.exists())
        self.assertEqual(_snapshot(self.project), before)
        self.assertEqual(self.index.verify_audit(), audit)

    def test_inventory_defense_is_read_only_and_refuses_unbound_marker(self):
        folder = self.library.create_session("inventory-only", kind="demo")
        _write_files(folder, {"takes/accept.lock": b"GENERATED PID-ONLY UNKNOWN MARKER"})
        before = _snapshot(folder)
        with self.assertRaisesRegex(BackupCorruptError, "BACKUP_BUSY"):
            self.manager._source_inventory([folder.name])
        self.assertEqual(_snapshot(folder), before)
        self.assertFalse((folder / "takes/.acceptance-lease").exists())

    def test_backup_acquires_sorted_leases_and_holds_them_through_archive_publication(self):
        other = self.library.create_session("alpha-generated", kind="demo")
        folders = sorted([self.project, other], key=lambda folder: folder.name)
        entered = []
        published = []
        archive = self.root / "ordered.zip"
        original_link = os.link

        @contextmanager
        def tracked_lease(folder):
            entered.append(folder.name)
            with acceptance_lease(folder) as stream:
                yield stream

        def verify_publication(source, target, *args, **kwargs):
            if Path(target) == archive:
                for folder in folders:
                    with (self.assertRaisesRegex(TakeAcceptanceError, "TAKE_BUSY"),
                          acceptance_lease(folder)):
                        self.fail("Backup publication must still hold every selected-session lease")
                published.append(True)
            return original_link(source, target, *args, **kwargs)

        with (patch("backup_manager.acceptance_lease", tracked_lease, create=True),
              patch("backup_manager.os.link", verify_publication)):
            self.manager.create_backup(archive, session_ids=[folder.name for folder in reversed(folders)])
        self.assertEqual(entered, [folder.name for folder in folders])
        self.assertEqual(published, [True])
        for folder in folders:
            with acceptance_lease(folder):
                pass

    def test_backup_preserves_actual_nondefault_anchor_bytes_and_inode(self):
        with acceptance_lease(self.project):
            pass
        anchor = self.project / "takes/.acceptance-lease/t6-startup.lock"
        anchor.write_bytes(b"GENERATED NONDEFAULT STABLE ANCHOR")
        before = _snapshot(self.project)
        actual = anchor.read_bytes()
        archive = self.root / "actual-anchor.zip"
        manifest = self.manager.create_backup(archive)
        relative = f"sessions/{self.project.name}/takes/.acceptance-lease/t6-startup.lock"
        record = next(item for item in manifest["files"] if item["path"] == relative)
        self.assertEqual(record["sha256"], _sha(actual))
        self.assertEqual(record["bytes"], len(actual))
        with zipfile.ZipFile(archive) as saved:
            self.assertEqual(saved.read(relative), actual)
        self.assertEqual(_snapshot(self.project), before)

    def test_backup_refuses_substituted_lease_handle_before_index_or_publication(self):
        with acceptance_lease(self.project):
            pass
        foreign = self.root / "foreign-anchor.bin"
        foreign.write_bytes(b"GENERATED FOREIGN ANCHOR")
        before = _snapshot(self.project)
        foreign_before = (foreign.read_bytes(), foreign.stat().st_ino)
        archive = self.root / "substituted.zip"

        @contextmanager
        def substituted_lease(folder):
            with acceptance_lease(folder), foreign.open("r+b") as wrong_stream:
                yield wrong_stream

        with (patch("backup_manager.acceptance_lease", substituted_lease, create=True),
              patch.object(self.index, "reindex", wraps=self.index.reindex) as reindex,
              self.assertRaisesRegex(BackupCorruptError, "BACKUP_SOURCE_INVALID")):
            self.manager.create_backup(archive)
        self.assertEqual(reindex.call_count, 0)
        self.assertFalse(archive.exists())
        self.assertEqual(_snapshot(self.project), before)
        self.assertEqual((foreign.read_bytes(), foreign.stat().st_ino), foreign_before)

    def test_backup_refuses_oversized_owned_anchor_before_index_or_publication(self):
        with acceptance_lease(self.project) as stream:
            stream.seek(0)
            stream.write(b"G" * (BackupManager.MAX_MANIFEST_BYTES + 1))
            stream.flush()
        before = _snapshot(self.project)
        archive = self.root / "oversized-anchor.zip"
        with (patch.object(self.index, "reindex", wraps=self.index.reindex) as reindex,
              self.assertRaisesRegex(BackupCorruptError, "BACKUP_SOURCE_INVALID")):
            self.manager.create_backup(archive)
        self.assertEqual(reindex.call_count, 0)
        self.assertFalse(archive.exists())
        self.assertEqual(_snapshot(self.project), before)

    def test_legacy_restore_refuses_pending_declared_take_before_any_session_rename(self):
        archive = self.root / "pending-legacy.zip"
        files = {"Config.toml": b"# GENERATED CONFIG\n", **_acceptance_files("restore-one")}
        build_v1_archive(archive, {"restore-one": files})
        archive_state = (archive.read_bytes(), archive.stat().st_ino)
        original = _snapshot(self.project)
        publications = []
        original_rename = Path.rename

        def track(source: Path, target: Path) -> Path:
            if Path(target) == self.projects / "restore-one":
                publications.append(str(target))
            return original_rename(source, target)

        with (patch.object(Path, "rename", track),
              patch.object(self.index, "reindex", wraps=self.index.reindex) as reindex,
              self.assertRaisesRegex(BackupCorruptError, "BACKUP_CORRUPT")):
            self.manager.restore_backup(archive)
        self.assertEqual(publications, [])
        self.assertEqual(reindex.call_count, 0)
        self.assertFalse((self.projects / "restore-one").exists())
        self.assertEqual((archive.read_bytes(), archive.stat().st_ino), archive_state)
        self.assertEqual(_snapshot(self.project), original)
        self.assertEqual(list(self.projects.glob(".restore-staging-*")), [])

    @unittest.skipUnless(sys.platform == "win32", "Actual directory publication is verified on Windows only")
    def test_full_generation_refuses_pending_take_before_database_reconciliation(self):
        clear_archive = self.root / "clear.zip"
        self.manager.create_backup(clear_archive)
        with zipfile.ZipFile(clear_archive) as source:
            entries = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(entries["backup_manifest.json"].decode("utf-8"))
        for name, content in _acceptance_files(self.project.name).items():
            relative = f"sessions/{self.project.name}/{name}"
            entries[relative] = content
            manifest["files"].append({"path": relative, "sha256": _sha(content), "bytes": len(content)})
        manifest["file_count"] = len(manifest["files"])
        entries["backup_manifest.json"] = json.dumps(manifest).encode("utf-8")
        archive = self.root / "pending-full.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as target:
            for name, content in entries.items():
                target.writestr(name, content)
        archive_state = (archive.read_bytes(), archive.stat().st_ino)
        before = _snapshot(self.project)
        destination = self.root / "recovered"
        with (patch.object(self.manager, "_database_generation", wraps=self.manager._database_generation) as reconcile,
              self.assertRaisesRegex(BackupCorruptError, "BACKUP_CORRUPT")):
            self.manager.restore_generation(archive, destination)
        self.assertEqual(reconcile.call_count, 0)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".restore-generation-*")), [])
        self.assertEqual((archive.read_bytes(), archive.stat().st_ino), archive_state)
        self.assertEqual(_snapshot(self.project), before)

    def test_interrupted_legacy_resume_refuses_declared_pending_take_without_mutation(self):
        backups = self.projects / "backups"
        backups.mkdir()
        archive = backups / "legacy-v1.zip"
        build_v1_archive(archive, {"restore-one": {"Config.toml": b"# GENERATED FIRST\n"},
                                   "restore-two": {"Config.toml": b"# GENERATED SECOND\n"}})
        self.index.close()
        repository = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(Path(__file__).with_name("test_legacy_restore_recovery.py")),
             "--crash-after-first-publication", str(self.projects), str(archive), str(self.root / "crash.json")],
            cwd=repository, capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(repository)},
        )
        self.assertEqual(result.returncode, 86, result.stdout + result.stderr)
        stage = next(self.projects.glob(".restore-staging-*"))
        folder = stage / "sessions/restore-two"
        _write_files(folder, _acceptance_files("restore-two"))
        journal_path = stage / BackupManager.JOURNAL_NAME
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        entry = next(item for item in journal["sessions"] if item["id"] == "restore-two")
        # Model an inventoried pre-fence interrupted import; no foreign identity is accepted.
        entry["files"] = {path.relative_to(folder).as_posix(): {"sha256": _sha(path.read_bytes()),
                                                              "bytes": path.stat().st_size}
                          for path in folder.rglob("*") if path.is_file()}
        entry["directories"] = sorted(path.relative_to(folder).as_posix()
                                      for path in folder.rglob("*") if path.is_dir())
        self.manager._write_restore_journal(stage, journal)
        before = _snapshot(self.projects)
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
            IntegratedService(self.projects)
        self.assertEqual(_snapshot(self.projects), before)
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
            BackupManager(self.projects).restore_backup(archive)
        self.assertEqual(_snapshot(self.projects), before)

    @unittest.skipUnless(sys.platform == "win32", "Actual directory publication is verified on Windows only")
    def test_terminal_history_and_stable_sentinel_remain_inert_after_later_source_change(self):
        with acceptance_lease(self.project):
            pass
        _write_files(self.project, _acceptance_files(self.project.name, terminal=True))
        _write_files(self.project, {"raw/cam01_trial.mp4": b"GENERATED LATER OWNER OF CANONICAL PATH"})
        require_no_pending(self.project)
        before = _snapshot(self.project)
        archive = self.root / "terminal.zip"
        self.manager.create_backup(archive)
        self.assertEqual(_snapshot(self.project), before)
        destination = self.root / "terminal-recovered"
        self.manager.restore_generation(archive, destination)
        recovered = destination / self.project.name
        require_no_pending(recovered)
        self.assertEqual({name: value[0] for name, value in _snapshot(recovered).items()},
                         {name: value[0] for name, value in before.items()})


if __name__ == "__main__":
    unittest.main()
