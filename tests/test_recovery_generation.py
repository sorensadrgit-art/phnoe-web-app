"""Generated-only full generation backups; no real media or existing databases."""
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event
from unittest.mock import patch

from backup_manager import BackupConflictError, BackupCorruptError, BackupManager
from recording_store import RecordingStore
from session_index import SessionIndex
from session_library import SessionLibrary
from test_recording_contract import frame, header
from test_recording_store import chunk


class RecoveryGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"; self.projects.mkdir()
        self.library = SessionLibrary(self.projects)
        self.folder = self.library.create_session("demo-recovery", kind="demo")
        (self.folder / "fixture.txt").write_text("immutable generated fixture", encoding="utf-8")
        self.index = SessionIndex(self.projects / ".kinelab_index.db", self.projects)
        self.addCleanup(self.index.close)
        self.index.reindex()
        self.store = RecordingStore(self.index)
        self.store.create(header()); self.store.append(header()["session_id"], chunk(1))
        self.manager = BackupManager(self.projects, self.index)
        self.archive = self.root / "recovery.zip"

    def recover(self, target):
        self.assertTrue(callable(getattr(self.manager, "restore_generation", None)),
                        "whole database/audit/file generation recovery is required")
        return self.manager.restore_generation(self.archive, target)

    def test_new_root_recovers_exact_database_audit_and_acknowledged_frames(self):
        manifest = self.manager.create_backup(self.archive)
        self.assertEqual(manifest["schema"], "kinelab.backup.v2")
        self.assertNotIn("host", manifest)
        self.assertEqual(manifest["generation"]["audit_tip"], self.index.verify_audit())
        target = self.root / "recovered"
        result = self.recover(target)
        self.assertTrue(result["database_restored"])
        self.assertFalse(result["active_workspace_changed"])
        self.assertEqual((target / "demo-recovery/fixture.txt").read_text(), "immutable generated fixture")
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual((target / ".kinelab_index.db").read_bytes(), archive.read("index.db"))
        recovered = SessionIndex(target / ".kinelab_index.db", target)
        try:
            self.assertEqual(recovered.verify_audit(), manifest["generation"]["audit_tip"])
            self.assertEqual(list(RecordingStore(recovered).iter_frames(header()["session_id"])), [frame()])
            self.assertEqual(RecordingStore(recovered).status(header()["session_id"])["state"], "RECORDING")
        finally:
            recovered.close()
        self.assertTrue((self.folder / "fixture.txt").is_file())

    def test_partial_selection_cannot_leak_other_sessions_or_recordings(self):
        self.library.create_session("demo-other", kind="demo")
        with self.assertRaisesRegex(BackupCorruptError, "BACKUP_SCOPE_INVALID"):
            self.manager.create_backup(self.archive, session_ids=["demo-recovery"])
        self.assertFalse(self.archive.exists())

    def test_file_and_index_from_different_revisions_cannot_form_recovery_generation(self):
        evidence = self.folder / "preflight.json"
        evidence.write_text('{"fixture_revision":1}', encoding="utf-8")
        reindex = self.index.reindex
        def change_after_index():
            reindex()
            evidence.write_text('{"fixture_revision":2}', encoding="utf-8")
        with patch.object(self.index, "reindex", side_effect=change_after_index), self.assertRaisesRegex(BackupCorruptError, "BACKUP_(DATABASE_INVALID|SOURCE_CHANGED)"):
            self.manager.create_backup(self.archive)
        self.assertFalse(self.archive.exists())

    def test_detected_changed_evidence_keeps_original_reference_and_invalid_state(self):
        evidence = self.folder / "preflight.json"
        evidence.write_text('{"fixture_revision":1}', encoding="utf-8")
        expected = hashlib.sha256(evidence.read_bytes()).hexdigest()
        self.index.reindex()
        evidence.write_text('{"fixture_revision":2}', encoding="utf-8")
        observed = hashlib.sha256(evidence.read_bytes()).hexdigest()
        self.manager.create_backup(self.archive)
        target = self.root / "recovered"; self.recover(target)
        with closing(sqlite3.connect(target / ".kinelab_index.db")) as db:
            record = db.execute("SELECT sha256,observed_sha256,integrity_state FROM artifacts WHERE artifact_key='preflight.json'").fetchone()
            self.assertEqual(record, (expected, observed, "changed"))
        self.assertEqual((target / "demo-recovery/preflight.json").read_bytes(), evidence.read_bytes())

    def test_new_evidence_after_indexing_cannot_escape_generation_validation(self):
        reindex = self.index.reindex
        def add_after_index():
            reindex()
            (self.folder / "preflight.json").write_text('{"fixture_revision":1}', encoding="utf-8")
        with patch.object(self.index, "reindex", side_effect=add_after_index), self.assertRaisesRegex(BackupCorruptError, "BACKUP_(DATABASE_INVALID|SOURCE_CHANGED)"):
            self.manager.create_backup(self.archive)
        self.assertFalse(self.archive.exists())

    def test_archive_sync_failure_has_no_published_archive(self):
        with patch("backup_manager.os.fsync", side_effect=OSError("injected disk sync failure")), self.assertRaisesRegex(OSError, "injected disk sync"):
            self.manager.create_backup(self.archive)
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.root.glob("*.partial")))

    def test_process_exit_at_publication_never_exposes_partial_generation(self):
        self.manager.create_backup(self.archive)
        prior = self.archive.read_bytes()
        scratch = self.root / "scratch"; scratch.mkdir()
        worker = '''
import os, sys, tempfile
from pathlib import Path
from backup_manager import BackupManager
from session_index import SessionIndex
projects, target, archive, scratch, action, moment = sys.argv[1:]
tempfile.tempdir = scratch
index = SessionIndex(Path(projects) / ".kinelab_index.db", projects)
manager = BackupManager(projects, index)
if action == "backup":
    original = os.link
    def interrupt(src, dst):
        if moment == "after": original(src, dst)
        os._exit(86)
    os.link = interrupt
    manager.create_backup(target)
else:
    original = Path.rename
    def interrupt(src, dst):
        if Path(dst) == Path(target):
            if moment == "after": original(src, dst)
            os._exit(86)
        return original(src, dst)
    Path.rename = interrupt
    manager.restore_generation(archive, target)
raise AssertionError("publication interruption was not reached")
'''
        for action in ("backup", "restore"):
            for moment in ("before", "after"):
                with self.subTest(action=action, moment=moment):
                    target = self.root / (action + "-" + moment + (".zip" if action == "backup" else ""))
                    result = subprocess.run([sys.executable, "-B", "-c", worker, str(self.projects), str(target),
                                             str(self.archive), str(scratch), action, moment],
                                            capture_output=True, text=True, timeout=15, check=False)
                    self.assertEqual(result.returncode, 86, result.stderr)
                    self.assertEqual(target.exists(), moment == "after")
                    if moment == "after":
                        if action == "backup":
                            recovered = self.root / "recovered-backup"
                            self.manager.restore_generation(target, recovered)
                        else:
                            recovered = target
                        index = SessionIndex(recovered / ".kinelab_index.db", recovered, read_only=True)
                        try:
                            self.assertEqual(list(RecordingStore(index).iter_frames(header()["session_id"])), [frame()])
                            self.assertEqual(index.verify_audit(), self.index.verify_audit())
                        finally: index.close()
                    self.assertEqual(self.archive.read_bytes(), prior)
        self.assertEqual(list(self.store.iter_frames(header()["session_id"])), [frame()])

    def test_manifest_rejects_overflow_in_unknown_nested_fields(self):
        self.manager.create_backup(self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["backup_manifest.json"] = entries["backup_manifest.json"][:-1] + b',"extra":{"number":1e999}}'
        bad = self.root / "nonfinite.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            for name, data in entries.items(): archive.writestr(name, data)
        with self.assertRaisesRegex(BackupCorruptError, "BACKUP_MANIFEST_INVALID"):
            self.manager.inspect_backup(bad)
        self.assertFalse((self.root / "recovered").exists())

    def test_rehashed_file_cannot_disagree_with_archived_index_observation(self):
        (self.folder / "preflight.json").write_text('{"fixture_revision":1}', encoding="utf-8")
        self.manager.create_backup(self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        name = "sessions/demo-recovery/preflight.json"
        entries[name] = b'{"fixture_revision":2}'
        manifest = json.loads(entries["backup_manifest.json"])
        item = next(f for f in manifest["files"] if f["path"] == name)
        item.update(bytes=len(entries[name]), sha256=hashlib.sha256(entries[name]).hexdigest())
        entries["backup_manifest.json"] = json.dumps(manifest).encode()
        bad = self.root / "mismatched-generation.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            for name, data in entries.items(): archive.writestr(name, data)
        with self.assertRaisesRegex(BackupCorruptError, "BACKUP_DATABASE_INVALID"):
            self.manager.restore_generation(bad, self.root / "recovered")
        self.assertFalse((self.root / "recovered").exists())

    def test_directory_publication_fails_closed_on_unverified_platform(self):
        self.manager.create_backup(self.archive)
        with patch("backup_manager.sys.platform", "unverified"), self.assertRaisesRegex(BackupConflictError, "RESTORE_PLATFORM_UNVERIFIED"):
            self.manager.restore_generation(self.archive, self.root / "recovered")
        self.assertFalse((self.root / "recovered").exists())

    def test_changed_source_during_copy_never_publishes_mixed_generation(self):
        original = shutil.copy2
        source = self.folder / "fixture.txt"
        def mutate_after_copy(src, dst, *args, **kwargs):
            result = original(src, dst, *args, **kwargs)
            if Path(src) == source:
                source.write_text("changed after copy", encoding="utf-8")
            return result
        with patch("backup_manager.shutil.copy2", side_effect=mutate_after_copy), self.assertRaisesRegex(BackupCorruptError, "BACKUP_SOURCE_CHANGED"):
            self.manager.create_backup(self.archive)
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.root.glob("recovery.zip.*.partial")))

    def test_backup_never_overwrites_existing_archive_or_ignores_inflight_files(self):
        self.archive.write_bytes(b"prior archive evidence")
        with self.assertRaises(BackupConflictError):
            self.manager.create_backup(self.archive)
        self.assertEqual(self.archive.read_bytes(), b"prior archive evidence")
        self.archive = self.root / "new.zip"
        for name in ("workflow.lock", "run.lock", "capture.partial", "copy.copying.mp4"):
            partial = self.folder / name; partial.write_text("in progress")
            original_index = self.index.db_path.read_bytes()
            try:
                with self.subTest(name=name), self.assertRaisesRegex(BackupCorruptError, "BACKUP_BUSY"):
                    self.manager.create_backup(self.archive)
                self.assertFalse(self.archive.exists())
                self.assertEqual(self.index.db_path.read_bytes(), original_index)
            finally:
                partial.unlink()

    def test_backup_destination_link_is_refused_without_touching_link_target(self):
        external = self.root / "external"; external.mkdir()
        link = self.root / "linked"
        try:
            os.symlink(external, link, target_is_directory=True)
        except OSError as error:
            self.skipTest("Directory symlinks unavailable: " + str(error))
        with self.assertRaisesRegex(BackupCorruptError, "BACKUP_PATH_INVALID"):
            self.manager.create_backup(link / "unexpected.zip")
        self.assertEqual(list(external.iterdir()), [])

    def test_corrupt_audit_rehashed_archive_is_rejected_before_publication(self):
        self.manager.create_backup(self.archive)
        self.assertTrue(callable(getattr(self.manager, "restore_generation", None)), "generation recovery required")
        with zipfile.ZipFile(self.archive) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        db = self.root / "tampered.db"; db.write_bytes(entries["index.db"])
        conn = sqlite3.connect(db)
        try:
            conn.execute("DROP TRIGGER audit_no_update")
            conn.execute("UPDATE audit_events SET details_json='{}' WHERE event_type='RECORDING_CHUNK_SAVED'")
            conn.commit()
        finally:
            conn.close()
        entries["index.db"] = db.read_bytes()
        manifest = json.loads(entries["backup_manifest.json"])
        item = next(f for f in manifest["files"] if f["path"] == "index.db")
        item.update(bytes=len(entries["index.db"]), sha256=hashlib.sha256(entries["index.db"]).hexdigest())
        entries["backup_manifest.json"] = json.dumps(manifest).encode()
        bad = self.root / "corrupt.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            for name, content in entries.items(): archive.writestr(name, content)
        with self.assertRaisesRegex(BackupCorruptError, "BACKUP_DATABASE_INVALID"):
            self.manager.restore_generation(bad, self.root / "recovered")
        self.assertFalse((self.root / "recovered").exists())

    def test_restore_conflict_and_publication_failure_preserve_active_workspace(self):
        self.manager.create_backup(self.archive)
        destination = self.root / "recovered"; destination.mkdir()
        (destination / "owner.txt").write_text("prior owner data")
        with self.assertRaises(BackupConflictError): self.recover(destination)
        self.assertEqual((destination / "owner.txt").read_text(), "prior owner data")
        with patch.object(Path, "rename", side_effect=OSError("injected publication failure")), self.assertRaisesRegex(OSError, "injected publication"):
            self.recover(self.root / "new-root")
        self.assertFalse((self.root / "new-root").exists())
        self.assertEqual(list(self.store.iter_frames(header()["session_id"])), [frame()])

    def test_concurrent_chunk_waits_and_snapshot_has_one_audit_generation(self):
        other = SessionIndex(self.index.db_path, self.projects); self.addCleanup(other.close)
        copying, release, writing = Event(), Event(), Event()
        original = shutil.copy2
        def slow_copy(src, dst, *args, **kwargs):
            if Path(src).name == "fixture.txt":
                copying.set()
                if not release.wait(4): raise TimeoutError("fixture release missing")
            return original(src, dst, *args, **kwargs)
        def append():
            writing.set()
            return RecordingStore(other).append(header()["session_id"], chunk(2))
        with ThreadPoolExecutor(2) as pool, patch("backup_manager.shutil.copy2", side_effect=slow_copy):
            backup = pool.submit(self.manager.create_backup, self.archive)
            try:
                self.assertTrue(copying.wait(4))
                writer = pool.submit(append)
                self.assertTrue(writing.wait(2))
                with self.assertRaises(TimeoutError, msg="recording write must wait for the backup snapshot"):
                    writer.result(timeout=.15)
            finally:
                release.set()
            manifest = backup.result(timeout=5)
            self.assertEqual(writer.result(timeout=5)["saved_through"], 2)
        target = self.root / "recovered"; self.recover(target)
        recovered = SessionIndex(target / ".kinelab_index.db", target)
        try:
            self.assertEqual(RecordingStore(recovered).status(header()["session_id"])["saved_through"], 1)
            self.assertEqual(recovered.verify_audit(), manifest["generation"]["audit_tip"])
        finally: recovered.close()


class GenerationSurvivingFaultTests(unittest.TestCase):
    """Generated surviving write faults over a real fixture, index, recording and archive."""

    setUp = RecoveryGenerationTests.setUp
    recover = RecoveryGenerationTests.recover

    def _session_snapshot(self):
        return {path.relative_to(self.folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.folder.rglob("*")
                if path.is_file() and ".acceptance-lease" not in path.parts}

    def _backup_with_fault(self, target, error):
        real_mkdtemp = tempfile.mkdtemp
        created = []

        def tracked_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created.append(Path(path))
            return path

        before = self._session_snapshot()
        with patch("backup_manager.tempfile.mkdtemp", tracked_mkdtemp), \
                patch(target, side_effect=error) as injected, self.assertRaises(OSError) as raised:
            self.manager.create_backup(self.archive)
        self.assertTrue(injected.called)
        self.assertEqual((type(raised.exception), raised.exception.errno, str(raised.exception)),
                         (type(error), error.errno, str(error)))
        self.assertFalse(os.path.lexists(self.archive))
        self.assertEqual(list(self.root.glob("*.partial")), [])
        snapshots = [path for path in created if path.name.startswith("kinelab-backup-")]
        self.assertEqual(len(snapshots), 1, created)
        self.assertFalse(os.path.lexists(snapshots[0]))
        self.assertEqual(self._session_snapshot(), before)
        self.assertEqual(list(self.store.iter_frames(header()["session_id"])), [frame()])

    def test_g3_destination_only_rename_failure_preserves_workspace_and_removes_stage(self):
        self.manager.create_backup(self.archive)
        target = self.root / "new-root"
        before_root = sorted(path.name for path in self.root.iterdir())
        before = self._session_snapshot()
        original_rename = Path.rename
        renames = []

        def rename(source, destination):
            renames.append((Path(source).name, Path(destination).name))
            if Path(destination).resolve() == target.resolve():
                raise OSError(errno.EACCES, "GENERATED locked destination publication")
            return original_rename(source, destination)

        with patch.object(Path, "rename", rename), \
                self.assertRaisesRegex(OSError, "GENERATED locked destination publication"):
            self.recover(target)
        self.assertIn(("index.db", ".kinelab_index.db"), renames)
        self.assertEqual(renames[-1], ("sessions", "new-root"))
        self.assertFalse(os.path.lexists(target))
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), before_root)
        self.assertEqual(self._session_snapshot(), before)
        self.assertEqual(list(self.store.iter_frames(header()["session_id"])), [frame()])
        self.assertTrue(self.recover(target)["ok"])

    def test_g4_enospc_during_snapshot_copy_leaves_no_archive_or_staging(self):
        self._backup_with_fault("backup_manager.shutil.copy2",
                                OSError(errno.ENOSPC, "GENERATED no space during snapshot copy"))

    def test_g4_enospc_during_archive_member_write_leaves_no_archive_or_staging(self):
        self._backup_with_fault("backup_manager.zipfile.ZipFile.write",
                                OSError(errno.ENOSPC, "GENERATED no space during archive write"))

    def test_g4_enospc_at_link_publication_leaves_no_archive_or_staging(self):
        self._backup_with_fault("backup_manager.os.link",
                                OSError(errno.ENOSPC, "GENERATED no space at link publication"))

    def test_g5_unsupported_hard_link_publication_cleans_up_and_retry_publishes(self):
        self._backup_with_fault("backup_manager.os.link",
                                OSError(errno.EPERM, "GENERATED hard links unsupported"))
        self.manager.create_backup(self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertEqual(list(self.root.glob("*.partial")), [])
        target = self.root / "after-retry"
        self.assertTrue(self.recover(target)["ok"])
        recovered = SessionIndex(target / ".kinelab_index.db", target)
        try:
            self.assertEqual(RecordingStore(recovered).status(header()["session_id"])["saved_through"], 1)
        finally:
            recovered.close()


if __name__ == "__main__": unittest.main()
