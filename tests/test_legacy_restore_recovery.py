"""Generated legacy-import crash recovery; no production data or native launch."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from backup_manager import BackupConflictError, BackupCorruptError, BackupManager
from runtime_config import startup_lock
from session_index import SessionIndex
from t6_service import IntegratedService
from test_backup_manager import build_v1_archive


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_snapshot(folder: Path) -> dict[str, str]:
    return {path.relative_to(folder).as_posix(): _digest(path)
            for path in folder.rglob("*") if path.is_file()}


def _worker_root(projects: Path, archive: Path, checkpoint: Path) -> Path:
    projects = projects.resolve()
    if (not projects.parent.name.startswith("kinelab-legacy-restore-recovery-")
            or projects.name != "projects" or archive.resolve().parent != projects / "backups"
            or checkpoint.resolve().parent != projects.parent):
        raise ValueError("Worker accepts only the generated test fixture")
    return projects


def _checkpoint(path: Path, state: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())


def _crash_worker(projects: Path, archive: Path, checkpoint: Path) -> None:
    """Exit after a real first rename, bypassing restore's in-memory finally."""
    projects = _worker_root(projects, archive, checkpoint)
    index = SessionIndex(projects / ".kinelab_index.db", projects)
    original_rename = Path.rename

    def stop_after_first_publication(source: Path, target: Path) -> Path:
        result = original_rename(source, target)
        if Path(target) == projects / "restore-one":
            state = {
                "phase": "first-real-rename-returned-before-rollback-registration",
                "first_published": (projects / "restore-one/Config.toml").is_file(),
                "second_published": (projects / "restore-two").exists(),
                "second_staged": (source.parent / "restore-two/Config.toml").is_file(),
            }
            _checkpoint(checkpoint, state)
            os._exit(86)
        return result

    with patch.object(Path, "rename", stop_after_first_publication):
        BackupManager(projects, index).restore_backup(archive)
    raise AssertionError("The first legacy-session publication boundary was not reached")


def _recovery_crash_worker(projects: Path, archive: Path, checkpoint: Path) -> None:
    """Exit after recovery really moves an owned session into hidden quarantine."""
    projects = _worker_root(projects, archive, checkpoint)
    original_rename = Path.rename

    def stop_after_recovery_move(source: Path, target: Path) -> Path:
        result = original_rename(source, target)
        target = Path(target)
        if (Path(source) == projects / "restore-one" and target.name == "restore-one"
                and target.parent.name == "quarantine"
                and target.parent.parent.name.startswith(".restore-staging-")
                and target.parent.parent.parent == projects):
            _checkpoint(checkpoint, {
                "phase": "first-real-recovery-move-returned-before-progress-acknowledgement",
                "first_no_longer_published": not (projects / "restore-one").exists(),
                "first_quarantined": (target / "Config.toml").is_file(),
            })
            os._exit(87)
        return result

    with patch.object(Path, "rename", stop_after_recovery_move):
        service = IntegratedService(projects)
        service.close()
    raise AssertionError("The real interrupted-import recovery move was not reached")


def _complete_crash_worker(projects: Path, archive: Path, checkpoint: Path, *, after_index=False) -> None:
    projects = _worker_root(projects, archive, checkpoint)
    index = SessionIndex(projects / ".kinelab_index.db", projects)
    real_rename = Path.rename
    real_reindex = index.reindex

    def after_last_rename(source, destination):
        result = real_rename(source, destination)
        if Path(destination) == projects / "restore-two" and not after_index:
            _checkpoint(checkpoint, {"phase": "last-publication-before-progress-acknowledgement"})
            os._exit(89)
        return result

    def after_index_commit():
        result = real_reindex()
        if after_index:
            _checkpoint(checkpoint, {"phase": "index-commit-before-journal-acknowledgement"})
            os._exit(90)
        return result

    with patch.object(Path, "rename", after_last_rename), patch.object(index, "reindex", after_index_commit):
        BackupManager(projects, index).restore_backup(archive)
    raise AssertionError("The complete-import crash boundary was not reached")


def _after_index_crash_worker(projects: Path, archive: Path, checkpoint: Path) -> None:
    _complete_crash_worker(projects, archive, checkpoint, after_index=True)


def _index_recovery_crash_worker(projects: Path, archive: Path, checkpoint: Path) -> None:
    projects = _worker_root(projects, archive, checkpoint)
    real_reindex = SessionIndex.reindex

    def after_commit(index):
        real_reindex(index)
        _checkpoint(checkpoint, {"phase": "recovery-index-commit-before-terminal-journal"})
        os._exit(91)

    with patch.object(SessionIndex, "reindex", after_commit):
        service = IntegratedService(projects)
        service.close()
    raise AssertionError("The recovery-index crash boundary was not reached")


def _committed_cleanup_crash_worker(projects: Path, archive: Path, checkpoint: Path) -> None:
    """Exit at the committed return boundary, exposing a real torn cleanup if entered."""
    projects = _worker_root(projects, archive, checkpoint)
    index = SessionIndex(projects / ".kinelab_index.db", projects)
    original_cleanup = shutil.rmtree

    def stop_during_success_cleanup(folder, *args, **kwargs):
        stage = Path(folder)
        journal = stage / BackupManager.JOURNAL_NAME
        if stage.parent == projects and stage.name.startswith(".restore-staging-") and journal.is_file():
            state = json.loads(journal.read_text(encoding="utf-8"))
            if state["phase"] == "COMMITTED":
                journal.unlink()
                _checkpoint(checkpoint, {"phase": "torn-success-cleanup", "journal_removed": True})
                os._exit(92)
        return original_cleanup(folder, *args, **kwargs)

    with patch("backup_manager.shutil.rmtree", stop_during_success_cleanup):
        result = BackupManager(projects, index).restore_backup(archive)
    _checkpoint(checkpoint, {"phase": "committed-return-before-process-exit", "ok": result["ok"]})
    os._exit(92)


def _busy_worker(projects: Path, archive: Path, checkpoint: Path) -> None:
    projects = _worker_root(projects, archive, checkpoint)
    try:
        result = BackupManager(projects).restore_backup(archive)
    except BackupConflictError as error:
        _checkpoint(checkpoint, {"ok": False, "error": str(error)})
        if str(error).startswith("RESTORE_BUSY"):
            raise SystemExit(88) from error
        raise
    _checkpoint(checkpoint, result)


class LegacyRestoreRecoveryTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-legacy-restore-recovery-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        projects = root / "projects"
        projects.mkdir()
        existing = projects / "existing-generated"
        existing.mkdir()
        (existing / "Config.toml").write_bytes(b"# GENERATED EXISTING SESSION\n")
        (existing / "sentinel.txt").write_bytes(b"GENERATED ORIGINAL MUST BE PRESERVED")
        prior_files = _file_snapshot(existing)
        index = SessionIndex(projects / ".kinelab_index.db", projects)
        try:
            index.reindex()
            index.record_audit_event("existing-generated", "PRESERVE", {"synthetic": True})
            prior_audit = [dict(row) for row in index.conn.execute(
                "SELECT * FROM audit_events WHERE event_type='PRESERVE' ORDER BY id",
            ).fetchall()]
        finally:
            index.close()
        backups = projects / "backups"
        backups.mkdir()
        archive = backups / "legacy-v1.zip"
        build_v1_archive(archive, {
            "restore-one": {"Config.toml": b"# GENERATED FIRST SESSION\n", "fixture.txt": b"first"},
            "restore-two": {"Config.toml": b"# GENERATED SECOND SESSION\n", "fixture.txt": b"second"},
        })
        archive_digest = _digest(archive)
        return root, projects, existing, prior_files, prior_audit, archive, archive_digest

    def worker(self, mode: str, projects: Path, archive: Path, checkpoint: Path):
        repository = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()),
             mode, str(projects), str(archive), str(checkpoint)],
            cwd=repository,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPATH": str(repository)},
            capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
        )

    def capacity_fixture(self, projects: Path, archive: Path) -> tuple[Path, Path, dict, int]:
        """Bind the initial journal length to real directory identities before extraction."""
        prepared = projects.parent / "prepared-capacity-stage"
        prepared.mkdir()
        stage = projects / ".restore-staging-capacity"
        with zipfile.ZipFile(archive) as source:
            manifest_bytes = source.read("backup_manifest.json")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        journal: dict = {
            "schema": BackupManager.JOURNAL_SCHEMA, "operation_id": "0" * 32,
            "stage_name": stage.name, "root_identity": BackupManager._directory_identity(projects),
            "stage_identity": BackupManager._directory_identity(prepared),
            "archive": {"sha256": _digest(archive), "bytes": archive.stat().st_size},
            "ignored_database": None, "sessions": [], "phase": "VERIFIED", "intent": None,
            "index_reconciled": False,
        }
        for sid in manifest["sessions"]:
            folder = prepared / "sessions" / sid
            folder.mkdir(parents=True)
            prefix = f"sessions/{sid}/"
            files = {item["path"][len(prefix):]: {"sha256": item["sha256"], "bytes": item["bytes"]}
                     for item in manifest["files"] if item["path"].startswith(prefix)}
            journal["sessions"].append({"id": sid, "identity": BackupManager._directory_identity(folder),
                                        "files": files, "directories": []})
        cap = len(json.dumps(journal, sort_keys=True).encode("utf-8"))
        self.assertLess(len(manifest_bytes), cap, "Fixture archive manifest must fit the reduced cap")
        return prepared, stage, journal, cap

    def test_process_death_at_success_cleanup_boundary_retains_complete_catalog(self):
        root, projects, existing, prior_files, prior_audit, archive, archive_digest = self.fixture()
        checkpoint = root / "committed-cleanup.json"
        result = self.worker("--crash-at-committed-cleanup", projects, archive, checkpoint)
        self.assertEqual(result.returncode, 92, result.stdout + result.stderr)
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertIn(state["phase"], {"torn-success-cleanup", "committed-return-before-process-exit"})
        try:
            restarted = IntegratedService(projects)
        except BackupConflictError as error:
            self.fail(f"A successful import's cleanup boundary must remain restartable: {error}")
        try:
            self.assertEqual({item["id"] for item in restarted.sessions()},
                             {"existing-generated", "restore-one", "restore-two"})
            self.assertEqual([dict(row) for row in restarted.index.conn.execute(
                "SELECT * FROM audit_events WHERE event_type='PRESERVE' ORDER BY id").fetchall()], prior_audit)
        finally:
            restarted.close()
        journals = list(projects.glob(".restore-staging-*/legacy-restore-journal.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text(encoding="utf-8"))["phase"], "COMMITTED")
        (projects / "restore-one/fixture.txt").write_bytes(b"GENERATED LATER MODIFICATION")
        later = _file_snapshot(projects / "restore-one")
        again = IntegratedService(projects)
        again.close()
        self.assertEqual(_file_snapshot(projects / "restore-one"), later)
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)

    def test_future_journal_capacity_is_refused_before_first_session_publication(self):
        _, projects, existing, prior_files, _, archive, archive_digest = self.fixture()
        manager = BackupManager(projects)
        prepared, stage, journal, cap = self.capacity_fixture(projects, archive)
        future = {**journal, "phase": "RECOVERING_ROLLBACK",
                  "intent": {"kind": "quarantine", "session_id": "restore-one"}}
        self.assertGreater(len(json.dumps(future, sort_keys=True).encode("utf-8")), cap)
        original_rename = Path.rename
        publications = []

        def tracked_rename(source: Path, target: Path) -> Path:
            target = Path(target)
            if target.parent == projects and target.name in {"restore-one", "restore-two"}:
                publications.append(target.name)
            return original_rename(source, target)

        def prepared_stage(*, prefix, dir):
            self.assertEqual(prefix, ".restore-staging-")
            self.assertEqual(Path(dir), projects)
            original_rename(prepared, stage)
            return str(stage)

        with (patch.object(BackupManager, "MAX_MANIFEST_BYTES", cap),
              patch("backup_manager.tempfile.mkdtemp", prepared_stage),
              patch.object(Path, "rename", tracked_rename),
              self.assertRaisesRegex(BackupCorruptError, "RESTORE_JOURNAL_LIMIT")):
            manager.restore_backup(archive)
        self.assertEqual(publications, [], "Capacity must be checked before any session rename")
        self.assertFalse(stage.exists(), "Caught-error cleanup must retain its existing behavior")
        self.assertFalse((projects / "restore-one").exists())
        self.assertFalse((projects / "restore-two").exists())
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)

    def test_journal_writer_exact_limit_and_oversize_preserve_previous_evidence(self):
        _, projects, _, _, _, archive, _ = self.fixture()
        manager = BackupManager(projects)
        prepared, stage, journal, cap = self.capacity_fixture(projects, archive)
        prepared.rename(stage)
        with patch.object(BackupManager, "MAX_MANIFEST_BYTES", cap):
            manager._write_restore_journal(stage, journal)
            original = (stage / BackupManager.JOURNAL_NAME).read_bytes()
            self.assertEqual(len(original), cap)
            before = _file_snapshot(stage)
            future = {**journal, "phase": "RECOVERING_ROLLBACK",
                      "intent": {"kind": "quarantine", "session_id": "restore-one"}}
            with self.assertRaisesRegex(BackupCorruptError, "RESTORE_JOURNAL_LIMIT"):
                manager._write_restore_journal(stage, future)
            self.assertEqual((stage / BackupManager.JOURNAL_NAME).read_bytes(), original)
            self.assertEqual(_file_snapshot(stage), before)
            self.assertEqual(list(stage.glob(".legacy-restore-journal-*.tmp")), [])

    def test_abrupt_exit_after_first_publication_recovers_prior_or_complete_import(self):
        root, projects, existing, prior_files, prior_audit, archive, archive_digest = self.fixture()
        checkpoint = root / "crash-checkpoint.json"
        result = self.worker("--crash-after-first-publication", projects, archive, checkpoint)
        self.assertEqual(result.returncode, 86, result.stdout + result.stderr)
        crash = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertTrue(crash["first_published"])
        self.assertFalse(crash["second_published"])
        self.assertTrue(crash["second_staged"])
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)

        # Reopen the actual service; a bare manager-only retry misses catalog exposure.
        restarted = IntegratedService(projects)
        self.addCleanup(restarted.close)
        imported = {"restore-one", "restore-two"}
        visible_after_restart = sorted(item["id"] for item in restarted.sessions()
                                       if item["id"] in imported)
        try:
            retry = restarted.restore_backup(archive.name, confirm=True, overwrite=False)
        except BackupConflictError as error:
            retry = {"ok": False, "error": str(error)}
        observation = {
            "crash_checkpoint": crash,
            "visible_after_restart": visible_after_restart,
            "retry": retry,
            "staging_after_restart": sorted(path.name for path in projects.glob(".restore-staging-*")),
            "archive_unchanged": _digest(archive) == archive_digest,
            "existing_files_unchanged": _file_snapshot(existing) == prior_files,
        }
        print("LEGACY_RESTORE_RECOVERY_OBSERVATION=" + json.dumps(observation, sort_keys=True), flush=True)
        self.assertIn(
            visible_after_restart, ([], sorted(imported)),
            "Restart must reconcile a crashed import before exposing an incomplete session set",
        )
        if not visible_after_restart:
            self.assertTrue(retry.get("ok"), retry)
        else:
            self.assertFalse(retry.get("ok"), "A complete recovered import must retain no-overwrite refusal")
        self.assertEqual(sorted(item["id"] for item in restarted.sessions()
                                if item["id"] in imported), sorted(imported))
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)
        current_audit = [dict(row) for row in restarted.index.conn.execute(
            "SELECT * FROM audit_events WHERE event_type='PRESERVE' ORDER BY id",
        ).fetchall()]
        self.assertEqual(current_audit, prior_audit)


    def test_second_process_death_during_recovery_resumes_without_exposing_partial_import(self):
        root, projects, existing, prior_files, prior_audit, archive, archive_digest = self.fixture()
        first = self.worker("--crash-after-first-publication", projects, archive, root / "first.json")
        self.assertEqual(first.returncode, 86, first.stdout + first.stderr)
        anchor = projects / "t6-startup.lock"
        anchor_identity = anchor.stat() if anchor.exists() else None
        second = self.worker("--crash-during-recovery", projects, archive, root / "second.json")
        self.assertEqual(second.returncode, 87, second.stdout + second.stderr)
        checkpoint = json.loads((root / "second.json").read_text(encoding="utf-8"))
        self.assertTrue(checkpoint["first_no_longer_published"])
        self.assertTrue(checkpoint["first_quarantined"])
        self.assertIsNotNone(anchor_identity, "Import must initialize a permanent OS-lock anchor")
        self.assertTrue(os.path.samestat(anchor_identity, anchor.stat()), "Lock anchor was replaced")
        restarted = IntegratedService(projects)
        self.addCleanup(restarted.close)
        imported = {"restore-one", "restore-two"}
        self.assertEqual([item["id"] for item in restarted.sessions() if item["id"] in imported], [])
        result = restarted.restore_backup(archive.name, confirm=True, overwrite=False)
        self.assertTrue(result["ok"], result)
        self.assertEqual(sorted(result["restored_sessions"]), sorted(imported))
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)
        self.assertEqual([dict(row) for row in restarted.index.conn.execute(
            "SELECT * FROM audit_events WHERE event_type='PRESERVE' ORDER BY id",
        ).fetchall()], prior_audit)
        self.assertTrue(os.path.samestat(anchor_identity, anchor.stat()), "Recovery recreated the lock")

    def test_last_publication_and_index_commit_crashes_recover_complete_without_overwrite(self):
        for mode, code in (("--crash-after-last-publication", 89), ("--crash-after-index-commit", 90)):
            with self.subTest(mode=mode):
                root, projects, existing, prior_files, prior_audit, archive, archive_digest = self.fixture()
                result = self.worker(mode, projects, archive, root / "complete.json")
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                restarted = IntegratedService(projects)
                try:
                    imported = {"restore-one", "restore-two"}
                    self.assertEqual({item["id"] for item in restarted.sessions()} & imported, imported)
                    indexed = {row[0] for row in restarted.index.conn.execute(
                        "SELECT id FROM sessions WHERE present=1").fetchall()}
                    self.assertTrue(imported <= indexed)
                    with self.assertRaisesRegex(BackupConflictError, "RESTORE_CONFLICT"):
                        restarted.restore_backup(archive.name, confirm=True, overwrite=False)
                    self.assertEqual([dict(row) for row in restarted.index.conn.execute(
                        "SELECT * FROM audit_events WHERE event_type='PRESERVE' ORDER BY id").fetchall()], prior_audit)
                finally:
                    restarted.close()
                journals = list(projects.glob(".restore-staging-*/legacy-restore-journal.json"))
                self.assertEqual(len(journals), 1)
                self.assertEqual(json.loads(journals[0].read_text(encoding="utf-8"))["phase"], "COMMITTED")
                again = IntegratedService(projects)
                again.close()
                self.assertEqual(_file_snapshot(existing), prior_files)
                self.assertEqual(_digest(archive), archive_digest)

    def test_second_exit_after_recovery_index_commit_repeats_reconciliation(self):
        root, projects, existing, prior_files, prior_audit, archive, archive_digest = self.fixture()
        first = self.worker("--crash-after-last-publication", projects, archive, root / "first.json")
        self.assertEqual(first.returncode, 89, first.stdout + first.stderr)
        second = self.worker("--crash-during-index-recovery", projects, archive, root / "second.json")
        self.assertEqual(second.returncode, 91, second.stdout + second.stderr)
        restarted = IntegratedService(projects)
        try:
            self.assertTrue({"restore-one", "restore-two"} <= {item["id"] for item in restarted.sessions()})
            self.assertEqual([dict(row) for row in restarted.index.conn.execute(
                "SELECT * FROM audit_events WHERE event_type='PRESERVE' ORDER BY id").fetchall()], prior_audit)
        finally:
            restarted.close()
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)

    def test_ignored_legacy_database_survives_crash_recovery_without_replacing_live_index(self):
        root, projects, _, _, prior_audit, archive, _ = self.fixture()
        payload = b"GENERATED ARCHIVED DATABASE MUST NEVER BECOME THE LIVE INDEX"
        with zipfile.ZipFile(archive) as source:
            entries = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(entries["backup_manifest.json"].decode("utf-8"))
        manifest["database_included"] = True
        manifest["files"].append({"path": "index.db", "sha256": hashlib.sha256(payload).hexdigest(),
                                   "bytes": len(payload)})
        manifest["file_count"] = len(manifest["files"])
        entries["backup_manifest.json"] = json.dumps(manifest).encode("utf-8")
        entries["index.db"] = payload
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as target:
            for name, data in entries.items():
                target.writestr(name, data)
        archive_digest = _digest(archive)
        result = self.worker("--crash-after-first-publication", projects, archive, root / "first.json")
        self.assertEqual(result.returncode, 86, result.stdout + result.stderr)
        restarted = IntegratedService(projects)
        try:
            self.assertEqual([dict(row) for row in restarted.index.conn.execute(
                "SELECT * FROM audit_events WHERE event_type='PRESERVE' ORDER BY id").fetchall()], prior_audit)
            self.assertFalse({"restore-one", "restore-two"} & {item["id"] for item in restarted.sessions()})
            staged_database = next(projects.glob(".restore-staging-*/index.db"))
            self.assertEqual(staged_database.read_bytes(), payload)
            self.assertTrue(restarted.restore_backup(archive.name, confirm=True, overwrite=False)["ok"])
        finally:
            restarted.close()
        self.assertEqual(_digest(archive), archive_digest)

    def test_terminal_rollback_journal_has_no_authority_over_reused_root_names(self):
        root, projects, _, _, _, archive, _ = self.fixture()
        result = self.worker("--crash-after-first-publication", projects, archive, root / "first.json")
        self.assertEqual(result.returncode, 86, result.stdout + result.stderr)
        restarted = IntegratedService(projects)
        try:
            self.assertTrue(restarted.restore_backup(archive.name, confirm=True, overwrite=False)["ok"])
        finally:
            restarted.close()
        reused = projects / "restore-one/Config.toml"
        reused.write_bytes(b"# GENERATED LATER OWNER OF REUSED ROOT NAME\n")
        before = _file_snapshot(projects / "restore-one")
        again = IntegratedService(projects)
        again.close()
        self.assertEqual(_file_snapshot(projects / "restore-one"), before)

    def test_tampered_inventory_identity_and_foreign_replacement_are_preserved_and_refused(self):
        for variant in ("inventory", "root-identity", "foreign-replacement", "undeclared-file", "terminal-phase"):
            with self.subTest(variant=variant):
                root, projects, _, _, _, archive, _ = self.fixture()
                result = self.worker("--crash-after-first-publication", projects, archive, root / "first.json")
                self.assertEqual(result.returncode, 86, result.stdout + result.stderr)
                if variant == "inventory":
                    (projects / "restore-one/Config.toml").write_bytes(b"# GENERATED CHANGED FILE\n")
                elif variant in {"root-identity", "terminal-phase"}:
                    journal_path = next(projects.glob(".restore-staging-*/legacy-restore-journal.json"))
                    journal = json.loads(journal_path.read_text(encoding="utf-8"))
                    if variant == "root-identity":
                        journal["root_identity"][1] += 1
                    else:
                        journal.update(phase="COMMITTED", intent=None)
                    journal_path.write_text(json.dumps(journal), encoding="utf-8")
                elif variant == "foreign-replacement":
                    original = projects / "restore-one"
                    original.rename(projects / ".preserved-original")
                    original.mkdir()
                    (original / "Config.toml").write_bytes(b"# GENERATED FOREIGN WRITER\n")
                else:
                    (projects / "restore-one/undeclared.txt").write_bytes(b"GENERATED UNDECLARED")
                before = _file_snapshot(projects)
                with self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
                    IntegratedService(projects)
                self.assertEqual(_file_snapshot(projects), before)
                with self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
                    BackupManager(projects).restore_backup(archive)
                self.assertEqual(_file_snapshot(projects), before)

    def test_unjournaled_legacy_stage_is_preserved_and_refuses_startup_and_direct_import(self):
        _, projects, _, _, _, archive, _ = self.fixture()
        manager = BackupManager(projects)
        stage = projects / ".restore-staging-pre-fix"
        stage.mkdir()
        (stage / "unowned.txt").write_bytes(b"GENERATED OLD STAGING EVIDENCE")
        before = _file_snapshot(projects)
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
            IntegratedService(projects)
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
            manager.restore_backup(archive)
        self.assertEqual(_file_snapshot(projects), before)

    def test_recovery_journal_write_refusal_does_not_publish_or_remove_evidence(self):
        root, projects, _, _, _, archive, _ = self.fixture()
        result = self.worker("--crash-after-first-publication", projects, archive, root / "first.json")
        self.assertEqual(result.returncode, 86, result.stdout + result.stderr)
        before = _file_snapshot(projects)
        real_open = Path.open

        def refuse_journal_write(path, mode="r", *args, **kwargs):
            if path.name.startswith(".legacy-restore-journal-") and mode == "xb":
                raise PermissionError("GENERATED read-only recovery fault")
            return real_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", refuse_journal_write), \
                self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
            IntegratedService(projects)
        self.assertEqual(_file_snapshot(projects), before)
        restarted = IntegratedService(projects)
        try:
            self.assertFalse({"restore-one", "restore-two"} & {item["id"] for item in restarted.sessions()})
        finally:
            restarted.close()

    def test_actual_os_held_root_lock_blocks_another_process_without_staging(self):
        root, projects, existing, prior_files, _prior_audit, archive, archive_digest = self.fixture()
        BackupManager(projects)
        anchor = projects / "t6-startup.lock"
        with startup_lock(projects, timeout=0.0):
            pass
        before = _file_snapshot(projects)
        with startup_lock(projects, timeout=0.0):
            anchor_identity = anchor.stat()
            result = self.worker("--try-import-while-busy", projects, archive, root / "busy.json")
            self.assertEqual(result.returncode, 88, result.stdout + result.stderr)
            busy = json.loads((root / "busy.json").read_text(encoding="utf-8"))
            self.assertTrue(busy["error"].startswith("RESTORE_BUSY"), busy)
        self.assertEqual(_file_snapshot(projects), before)
        self.assertTrue(os.path.samestat(anchor_identity, anchor.stat()))
        result = BackupManager(projects).restore_backup(archive)
        self.assertTrue(result["ok"])
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)
        self.assertTrue(os.path.samestat(anchor_identity, anchor.stat()))


class LegacyRestoreSurvivingFaultTests(unittest.TestCase):
    """Generated in-process faults after a real first publication; the process survives."""

    fixture = LegacyRestoreRecoveryTests.fixture
    GENERATED_SESSIONS = frozenset({"restore-one", "restore-two"})

    @staticmethod
    def _stages(projects: Path) -> list[Path]:
        return sorted(projects.glob(".restore-staging-*"))

    @staticmethod
    def _journal(stage: Path) -> dict:
        return json.loads((stage / BackupManager.JOURNAL_NAME).read_text(encoding="utf-8"))

    def _fail_second_root_publication(self, projects: Path):
        original_rename = Path.rename
        root = projects.resolve()
        attempts: list[str] = []

        def rename(source: Path, target) -> Path:
            destination = Path(target)
            if destination.name in self.GENERATED_SESSIONS and destination.parent.resolve() == root:
                attempts.append(destination.name)
                if len(attempts) == 2:
                    raise PermissionError("GENERATED locked second publication")
            return original_rename(source, target)

        return rename, attempts

    def _refuse_rollback_removal(self, projects: Path, remove_member: str | None):
        original_rmtree = shutil.rmtree
        root = projects.resolve()
        refused: list[str] = []

        def rmtree(path, *args, **kwargs):
            candidate = Path(path)
            if candidate.name in self.GENERATED_SESSIONS and candidate.parent.resolve() == root:
                refused.append(candidate.name)
                if remove_member is not None:
                    (candidate / remove_member).unlink()
                raise PermissionError("GENERATED locked rollback removal")
            return original_rmtree(path, *args, **kwargs)

        return rmtree, refused

    def _fault_during_import(self, projects: Path, archive: Path, remove_member: str | None):
        rename, attempts = self._fail_second_root_publication(projects)
        rmtree, refused = self._refuse_rollback_removal(projects, remove_member)
        with patch.object(Path, "rename", rename), patch("backup_manager.shutil.rmtree", rmtree), \
                self.assertRaisesRegex(PermissionError, "GENERATED locked rollback removal"):
            BackupManager(projects).restore_backup(archive)
        self.assertEqual(len(attempts), 2, attempts)
        self.assertEqual(refused, attempts[:1])
        stages = self._stages(projects)
        self.assertEqual(len(stages), 1, stages)
        journal = self._journal(stages[0])
        self.assertEqual(journal["phase"], "PUBLISHING")
        self.assertEqual(journal["intent"], {"kind": "publish", "session_id": attempts[1]})
        self.assertTrue((stages[0] / "sessions" / attempts[1] / "Config.toml").is_file())
        return attempts[0], attempts[1], stages[0]

    def test_g1_surviving_second_publication_failure_rolls_back_owned_publication(self):
        _root, projects, existing, prior_files, _prior_audit, archive, archive_digest = self.fixture()
        BackupManager(projects)
        before_names = sorted(path.name for path in projects.iterdir())
        rename, attempts = self._fail_second_root_publication(projects)
        with patch.object(Path, "rename", rename), \
                self.assertRaisesRegex(PermissionError, "GENERATED locked second publication"):
            BackupManager(projects).restore_backup(archive)
        self.assertEqual(len(attempts), 2, attempts)
        self.assertEqual(sorted(path.name for path in projects.iterdir()), before_names)
        self.assertEqual(self._stages(projects), [])
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)
        result = BackupManager(projects).restore_backup(archive)
        self.assertTrue(result["ok"])
        self.assertEqual(sorted(result["restored_sessions"]), sorted(self.GENERATED_SESSIONS))
        self.assertEqual(_file_snapshot(existing), prior_files)

    def test_g2_rollback_removal_failure_keeps_journal_and_startup_quarantines_publication(self):
        _root, projects, existing, prior_files, _prior_audit, archive, archive_digest = self.fixture()
        BackupManager(projects)
        first, second, stage = self._fault_during_import(projects, archive, None)
        self.assertTrue((projects / first / "Config.toml").is_file())
        with BackupManager(projects).startup_recovery():
            pass
        self.assertFalse(os.path.lexists(projects / first))
        self.assertFalse(os.path.lexists(projects / second))
        self.assertTrue((stage / "quarantine" / first / "Config.toml").is_file())
        self.assertTrue((stage / "sessions" / second / "Config.toml").is_file())
        journal = self._journal(stage)
        self.assertEqual(journal["phase"], "RECOVERED_ROLLBACK")
        self.assertIsNone(journal["intent"])
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)
        result = BackupManager(projects).restore_backup(archive)
        self.assertTrue(result["ok"])
        self.assertTrue((stage / "quarantine" / first / "Config.toml").is_file())
        self.assertEqual(self._journal(stage)["phase"], "RECOVERED_ROLLBACK")
        self.assertEqual(_file_snapshot(existing), prior_files)

    def test_g2b_partial_rollback_removal_fails_closed_without_further_mutation(self):
        _root, projects, existing, prior_files, _prior_audit, archive, archive_digest = self.fixture()
        BackupManager(projects)
        first, _second, _stage = self._fault_during_import(projects, archive, "fixture.txt")
        self.assertFalse(os.path.lexists(projects / first / "fixture.txt"))
        self.assertTrue((projects / first / "Config.toml").is_file())
        before = _file_snapshot(projects)
        with (
            self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"),
            BackupManager(projects).startup_recovery(),
        ):
            self.fail("startup recovery must not expose a partially removed import")
        self.assertEqual(_file_snapshot(projects), before)
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_RECOVERY_REQUIRED"):
            BackupManager(projects).restore_backup(archive)
        self.assertEqual(_file_snapshot(projects), before)
        self.assertEqual(_file_snapshot(existing), prior_files)
        self.assertEqual(_digest(archive), archive_digest)


if __name__ == "__main__":
    workers = {
        "--crash-after-first-publication": _crash_worker,
        "--crash-during-recovery": _recovery_crash_worker,
        "--crash-after-last-publication": _complete_crash_worker,
        "--crash-after-index-commit": _after_index_crash_worker,
        "--crash-during-index-recovery": _index_recovery_crash_worker,
        "--crash-at-committed-cleanup": _committed_cleanup_crash_worker,
        "--try-import-while-busy": _busy_worker,
    }
    if len(sys.argv) == 5 and sys.argv[1] in workers:
        workers[sys.argv[1]](*(Path(value) for value in sys.argv[2:]))
    else:
        unittest.main()
