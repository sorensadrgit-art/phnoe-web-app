"""Local offline backup creation, manifest hashing, and staged restore for KineLab PT.

Complete generations preserve the database, audit history and inventoried files.
Legacy archives import new session folders only. Destructive overwrite is disabled.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import unicodedata
import zipfile
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from runtime_config import ensure_directory, is_reparse, startup_lock
from session_contract import ROLES, sha256_file, strict_json_loads
from session_index import INDEXED_EVIDENCE_FILES, SCHEMA_VERSION, SessionIndex
from session_library import WINDOWS_RESERVED, _check_id
from take_acceptance import TakeAcceptanceError, acceptance_lease, require_no_pending


class BackupCorruptError(ValueError):
    """The backup archive failed hash verification or manifest integrity check."""


class BackupConflictError(FileExistsError):
    """One or more sessions in the backup already exist in the target projects directory."""


class BackupManager:
    def __init__(self, projects_root: Path | str, index: SessionIndex | None = None):
        self.projects_root = ensure_directory(Path(projects_root).absolute())
        self.index = index
        # Keep one OS-held anchor for this root; never unlink or replace it.
        with self._restore_lock():
            pass

    @contextmanager
    def _restore_lock(self):
        with ExitStack() as stack:
            try:
                stack.enter_context(startup_lock(self.projects_root, timeout=0.0))
            except TimeoutError as exc:
                raise BackupConflictError("RESTORE_BUSY: another root operation is in progress") from exc
            yield

    @contextmanager
    def startup_recovery(self):
        """Reconcile process-death journals before the service exposes its catalog."""
        with self._restore_lock():
            pending = self._recover_legacy_stages()
            yield
            self._finish_legacy_recovery(pending)

    JOURNAL_NAME = "legacy-restore-journal.json"
    JOURNAL_SCHEMA = "kinelab.legacy-restore-journal.v1"
    JOURNAL_PHASES = frozenset({
        "VERIFIED", "PUBLISHING", "ALL_PUBLISHED", "INDEX_PENDING",
        "RECOVERING_ROLLBACK", "RECOVERED_ROLLBACK", "COMMITTED",
    })

    @staticmethod
    def _recovery_required(reason: str):
        raise BackupConflictError(f"RESTORE_RECOVERY_REQUIRED: {reason}; evidence preserved")

    @staticmethod
    def _directory_identity(path: Path) -> list[int]:
        for part in (*reversed(path.parents), path):
            if is_reparse(part) or not stat.S_ISDIR(part.lstat().st_mode):
                BackupManager._recovery_required("ordinary directories required")
        info = path.stat(follow_symlinks=False)
        return [info.st_dev, info.st_ino]

    def _restore_inventory(self, folder: Path) -> tuple[dict, list[str]]:
        self._directory_identity(folder)
        files = {}
        directories = []
        total = 0
        for root, dirs, names in os.walk(folder):
            for name in sorted(dirs + names):
                path = Path(root) / name
                relative = path.relative_to(folder).as_posix()
                self._safe_member_name(relative)
                info = path.lstat()
                if is_reparse(path):
                    self._recovery_required("linked restore content")
                if stat.S_ISDIR(info.st_mode):
                    directories.append(relative)
                elif stat.S_ISREG(info.st_mode) and info.st_size <= self.MAX_MEMBER_BYTES:
                    digest = sha256_file(path)
                    after = path.stat(follow_symlinks=False)
                    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        self._recovery_required("restore content changed while hashing")
                    files[relative] = {"sha256": digest, "bytes": info.st_size}
                    total += info.st_size
                else:
                    self._recovery_required("unsupported restore content")
                if len(files) + len(directories) > self.MAX_MEMBERS or total > self.MAX_TOTAL_BYTES:
                    self._recovery_required("restore inventory exceeds limits")
        return files, sorted(directories)

    def _restore_journal_bytes(self, journal: dict) -> bytes:
        payload = json.dumps(journal, sort_keys=True).encode("utf-8")
        if len(payload) > self.MAX_MANIFEST_BYTES:
            raise BackupCorruptError("RESTORE_JOURNAL_LIMIT: recovery journal exceeds bounded size")
        return payload

    def _check_restore_journal_capacity(self, journal: dict) -> None:
        longest_id = max((item["id"] for item in journal["sessions"]),
                         key=lambda value: len(json.dumps(value).encode("utf-8")))
        self._restore_journal_bytes({
            **journal, "phase": "RECOVERING_ROLLBACK", "index_reconciled": False,
            "intent": {"kind": "quarantine", "session_id": longest_id},
        })

    def _write_restore_journal(self, stage: Path, journal: dict) -> None:
        if (self._directory_identity(self.projects_root) != journal["root_identity"]
                or self._directory_identity(stage) != journal["stage_identity"]):
            self._recovery_required("root or stage identity changed")
        payload = self._restore_journal_bytes(journal)
        temporary = stage / f".legacy-restore-journal-{uuid4().hex}.tmp"
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, stage / self.JOURNAL_NAME)

    def _read_restore_journal(self, stage: Path) -> dict:
        self._directory_identity(stage)
        path = stage / self.JOURNAL_NAME
        if is_reparse(path) or not path.is_file() or path.stat().st_size > self.MAX_MANIFEST_BYTES:
            self._recovery_required("missing or unsafe restore journal")
        journal = self._decode_manifest(path.read_bytes())
        if (set(journal) != {"schema", "operation_id", "stage_name", "root_identity", "stage_identity",
                             "archive", "ignored_database", "sessions", "phase", "intent", "index_reconciled"}
                or journal["schema"] != self.JOURNAL_SCHEMA
                or not isinstance(journal["operation_id"], str)
                or re.fullmatch(r"[0-9a-f]{32}", journal["operation_id"]) is None
                or journal["stage_name"] != stage.name
                or journal["phase"] not in self.JOURNAL_PHASES
                or type(journal["index_reconciled"]) is not bool):
            self._recovery_required("invalid restore journal schema")
        for key, folder in (("root_identity", self.projects_root), ("stage_identity", stage)):
            identity = journal[key]
            if (not isinstance(identity, list) or len(identity) != 2
                    or any(type(value) is not int or value < 0 for value in identity)
                    or self._directory_identity(folder) != identity):
                self._recovery_required("restore directory identity changed")
        archive = journal["archive"]
        if (not isinstance(archive, dict) or set(archive) != {"sha256", "bytes"}
                or not isinstance(archive["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", archive["sha256"]) is None
                or type(archive["bytes"]) is not int or archive["bytes"] < 0):
            self._recovery_required("invalid archive identity")
        ignored = journal["ignored_database"]
        if ignored is not None and (not isinstance(ignored, dict) or set(ignored) != {"sha256", "bytes", "identity"}
                                    or not isinstance(ignored["sha256"], str)
                                    or re.fullmatch(r"[0-9a-f]{64}", ignored["sha256"]) is None
                                    or type(ignored["bytes"]) is not int
                                    or not 0 <= ignored["bytes"] <= self.MAX_MEMBER_BYTES
                                    or not isinstance(ignored["identity"], list) or len(ignored["identity"]) != 2
                                    or any(type(value) is not int or value < 0 for value in ignored["identity"])):
            self._recovery_required("invalid ignored legacy database inventory")
        sessions = journal["sessions"]
        if not isinstance(sessions, list) or not sessions or len(sessions) > self.MAX_MEMBERS:
            self._recovery_required("invalid restore session inventory")
        ids = []
        count = total = 0
        for item in sessions:
            if not isinstance(item, dict) or set(item) != {"id", "identity", "files", "directories"}:
                self._recovery_required("invalid session journal entry")
            _check_id(item["id"])
            ids.append(item["id"])
            identity = item["identity"]
            if (not isinstance(identity, list) or len(identity) != 2
                    or any(type(value) is not int or value < 0 for value in identity)
                    or not isinstance(item["files"], dict) or "Config.toml" not in item["files"]
                    or not isinstance(item["directories"], list)):
                self._recovery_required("invalid session identity or inventory")
            for relative, entry in item["files"].items():
                self._safe_member_name(relative)
                if (not isinstance(entry, dict) or set(entry) != {"sha256", "bytes"}
                        or not isinstance(entry["sha256"], str)
                        or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
                        or type(entry["bytes"]) is not int or not 0 <= entry["bytes"] <= self.MAX_MEMBER_BYTES):
                    self._recovery_required("invalid restore file inventory")
                total += entry["bytes"]
            for relative in item["directories"]:
                self._safe_member_name(relative)
            if len(set(item["directories"])) != len(item["directories"]):
                self._recovery_required("duplicate restore directories")
            count += len(item["files"]) + len(item["directories"])
        if len({sid.casefold() for sid in ids}) != len(ids) or count > self.MAX_MEMBERS or total > self.MAX_TOTAL_BYTES:
            self._recovery_required("duplicate or oversized restore inventory")
        intent = journal["intent"]
        if intent is not None and (not isinstance(intent, dict) or set(intent) != {"kind", "session_id"}
                                   or intent["kind"] not in {"publish", "quarantine"}
                                   or intent["session_id"] not in ids):
            self._recovery_required("invalid restore move intent")
        if journal["phase"] in {"COMMITTED", "RECOVERED_ROLLBACK"} and intent is not None:
            self._recovery_required("terminal restore journal contains a pending move")
        return journal

    def _restore_locations(self, stage: Path, journal: dict, *, terminal: bool = False) -> dict[str, Path]:
        if (self._directory_identity(self.projects_root) != journal["root_identity"]
                or self._directory_identity(stage) != journal["stage_identity"]):
            self._recovery_required("root or stage identity changed")
        ids = {item["id"] for item in journal["sessions"]}
        ignored = journal["ignored_database"]
        database = stage / "index.db"
        if ignored is not None:
            if is_reparse(database) or not database.is_file():
                self._recovery_required("ignored legacy database missing or unsafe")
            info = database.stat(follow_symlinks=False)
            if ([info.st_dev, info.st_ino] != ignored["identity"] or info.st_size != ignored["bytes"]
                    or sha256_file(database) != ignored["sha256"]):
                self._recovery_required("ignored legacy database changed")
        for child in stage.iterdir():
            if child.name in {"sessions", "quarantine"}:
                self._directory_identity(child)
                if any(entry.name not in ids for entry in child.iterdir()):
                    self._recovery_required("undeclared staged session")
            elif child.name == "index.db" and ignored is not None:
                continue
            elif (child.name != self.JOURNAL_NAME
                  and re.fullmatch(r"\.legacy-restore-journal-[0-9a-f]{32}\.tmp", child.name) is None):
                self._recovery_required("undeclared restore stage content")
            elif is_reparse(child) or not stat.S_ISREG(child.lstat().st_mode):
                self._recovery_required("unsafe restore journal content")
        locations = {}
        for item in journal["sessions"]:
            sid = item["id"]
            candidates = [stage / "sessions" / sid, stage / "quarantine" / sid]
            # A terminal journal has no authority over a later reuse of a root name.
            if not terminal:
                candidates.append(self.projects_root / sid)
            present = [path for path in candidates if os.path.lexists(path)]
            if terminal and journal["phase"] == "COMMITTED":
                if present:
                    self._recovery_required("committed restore still contains unpublished sessions")
                continue
            if len(present) != 1:
                self._recovery_required("ambiguous or missing restore session")
            path = present[0]
            if not terminal:
                try:
                    require_no_pending(path)
                except TakeAcceptanceError as exc:
                    raise BackupConflictError("RESTORE_RECOVERY_REQUIRED: unfinished take acceptance; evidence preserved") from exc
            if (self._directory_identity(path) != item["identity"]
                    or self._restore_inventory(path) != (item["files"], item["directories"])):
                self._recovery_required("restore session identity or inventory changed")
            locations[sid] = path
        return locations

    def _recover_legacy_stages(self) -> list[tuple[Path, dict]]:
        pending = []
        try:
            for stage in sorted(self.projects_root.glob(".restore-staging-*")):
                journal = self._read_restore_journal(stage)
                terminal = journal["phase"] in {"COMMITTED", "RECOVERED_ROLLBACK"}
                locations = self._restore_locations(stage, journal, terminal=terminal)
                if terminal:
                    continue
                if all(path.parent == self.projects_root for path in locations.values()):
                    journal.update(phase="INDEX_PENDING", intent=None)
                    self._write_restore_journal(stage, journal)
                    pending.append((stage, journal))
                    continue
                journal.update(phase="RECOVERING_ROLLBACK", intent=None)
                self._write_restore_journal(stage, journal)
                quarantine = stage / "quarantine"
                quarantine.mkdir(exist_ok=True)
                for item in reversed(journal["sessions"]):
                    locations = self._restore_locations(stage, journal)
                    source = locations[item["id"]]
                    if source.parent != self.projects_root:
                        continue
                    destination = quarantine / item["id"]
                    if os.path.lexists(destination):
                        self._recovery_required("quarantine destination exists")
                    journal["intent"] = {"kind": "quarantine", "session_id": item["id"]}
                    self._write_restore_journal(stage, journal)
                    self._restore_locations(stage, journal)
                    source.rename(destination)
                    journal["intent"] = None
                    self._write_restore_journal(stage, journal)
                journal.update(phase="RECOVERED_ROLLBACK", intent=None)
                self._restore_locations(stage, journal)
                self._write_restore_journal(stage, journal)
        except BackupConflictError:
            raise
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise BackupConflictError("RESTORE_RECOVERY_REQUIRED: unreadable recovery state; evidence preserved") from exc
        return pending

    def _finish_legacy_recovery(self, pending: list[tuple[Path, dict]]) -> None:
        for stage, journal in pending:
            self._restore_locations(stage, journal)
        if pending and self.index is not None:
            self.index.reindex()
        for stage, journal in pending:
            locations = self._restore_locations(stage, journal)
            if not all(path.parent == self.projects_root for path in locations.values()):
                self._recovery_required("complete restore changed during index reconciliation")
            journal.update(phase="COMMITTED", intent=None, index_reconciled=self.index is not None)
            self._write_restore_journal(stage, journal)

    def create_backup(self, zip_path: Path | str, session_ids: list[str] | None = None) -> dict:
        target_zip = Path(zip_path).absolute()
        if any(p.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(str(p))
               for p in (target_zip, *target_zip.parents)):
            raise BackupCorruptError("BACKUP_PATH_INVALID: archive destination must not follow links")
        target_zip = target_zip.resolve()
        if os.path.lexists(target_zip):
            raise BackupConflictError("BACKUP_CONFLICT: archive already exists")
        if self.index is None:
            raise BackupCorruptError("BACKUP_SCOPE_INVALID: full recovery requires the authoritative index")
        all_sessions = self._session_ids()
        session_ids = all_sessions if session_ids is None else session_ids
        if not isinstance(session_ids, list) or any(not isinstance(s, str) for s in session_ids):
            raise BackupCorruptError("BACKUP_SOURCE_INVALID: session IDs must be a list")
        if len({s.casefold() for s in session_ids}) != len(session_ids):
            raise BackupCorruptError("BACKUP_SOURCE_INVALID: duplicate session id aliases")
        for sid in session_ids:
            try:
                _check_id(sid)
            except ValueError as exc:
                raise BackupCorruptError("BACKUP_SOURCE_INVALID: unsafe session id") from exc
        if sorted(session_ids) != all_sessions:
            raise BackupCorruptError("BACKUP_SCOPE_INVALID: select all sessions for a complete recovery generation")
        if any(target_zip.is_relative_to(self.projects_root / sid) for sid in session_ids):
            raise BackupCorruptError("BACKUP_PATH_INVALID: archive cannot be inside a session")
        with ExitStack() as leases:
            lease_streams: dict[str, BinaryIO] = {}
            for sid in sorted(session_ids):
                project = self.projects_root / sid
                try:
                    require_no_pending(project)
                    stream = leases.enter_context(acceptance_lease(project))
                except TakeAcceptanceError as exc:
                    raise BackupCorruptError("BACKUP_BUSY: finish or recover take acceptance first") from exc
                lease_streams[f"sessions/{sid}/takes/.acceptance-lease/t6-startup.lock"] = stream
            target_zip.parent.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix="kinelab-backup-"))
            staging_zip = target_zip.with_name(f"{target_zip.name}.{uuid4().hex}.partial")
            try:
                before = self._source_inventory(session_ids, lease_streams)
                self.index.reindex()
                with self.index.transaction():
                    if self._source_inventory(session_ids, lease_streams) != before:
                        raise BackupCorruptError("BACKUP_SOURCE_CHANGED: source changed while indexing")
                    self.index.backup_database(temp_dir / "index.db")
                    (temp_dir / "sessions").mkdir()
                    for relative, item in before.items():
                        source = self.projects_root / relative.removeprefix("sessions/")
                        dest = temp_dir / relative
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if relative in lease_streams:
                            with dest.open("xb") as copied:
                                copied.write(self._lease_anchor_bytes(source, lease_streams[relative]))
                        else:
                            shutil.copy2(source, dest)
                        if sha256_file(dest) != item["sha256"]:
                            raise BackupCorruptError("BACKUP_SOURCE_CHANGED: copied bytes differ")
                    if (self._session_ids() != all_sessions
                            or self._source_inventory(session_ids, lease_streams) != before):
                        raise BackupCorruptError("BACKUP_SOURCE_CHANGED: source inventory changed during snapshot")
                    generation = self._database_generation(temp_dir / "index.db", temp_dir / "sessions", session_ids)
                    files = [{"path": rel, "sha256": item["sha256"], "bytes": item["bytes"]}
                             for rel, item in before.items()]
                    files.append({"path": "index.db", "sha256": sha256_file(temp_dir / "index.db"),
                                  "bytes": (temp_dir / "index.db").stat().st_size})
                    manifest = {"schema": "kinelab.backup.v2", "created_at_utc": datetime.now(UTC).isoformat(),
                                "generation": {"id": uuid4().hex, **generation}, "sessions": all_sessions,
                                "database_included": True, "file_count": len(files), "files": files}
                # Stored members avoid producing a valid backup rejected as a compression bomb.
                with zipfile.ZipFile(staging_zip, "x", compression=zipfile.ZIP_STORED) as archive:
                    archive.writestr("backup_manifest.json", json.dumps(manifest, allow_nan=False))
                    for item in files:
                        relative = item["path"]
                        if relative in lease_streams:
                            source = self.projects_root / relative.removeprefix("sessions/")
                            content = self._lease_anchor_bytes(source, lease_streams[relative])
                            if len(content) != item["bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                                raise BackupCorruptError("BACKUP_SOURCE_CHANGED: lease anchor changed before archive")
                            archive.writestr(relative, content)
                        else:
                            archive.write(temp_dir / relative, relative)
                with staging_zip.open("r+b") as staged:
                    os.fsync(staged.fileno())
                with zipfile.ZipFile(staging_zip) as archive:
                    checked, members = self._preflight(archive)
                    self._verify_members(archive, checked, members)
                # Link publication is atomic and fails if another writer owns the destination.
                os.link(staging_zip, target_zip)
                return manifest
            finally:
                staging_zip.unlink(missing_ok=True)
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _session_ids(self):
        result = []
        for folder in sorted(self.projects_root.iterdir()):
            if folder.name.startswith(".") or folder.name in {"backups", "recovery-generations"}:
                continue
            if folder.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(str(folder)):
                raise BackupCorruptError("BACKUP_SOURCE_INVALID: linked session entry")
            if folder.is_dir() and (folder / "Config.toml").is_file():
                _check_id(folder.name)
                result.append(folder.name)
        return result

    def _lease_anchor_bytes(self, path: Path, stream: BinaryIO) -> bytes:
        """Read only the exact bounded anchor through its OS-lock owning stream."""
        try:
            if os.path.normcase(os.path.abspath(stream.name)) != os.path.normcase(str(path.absolute())):
                raise BackupCorruptError("BACKUP_SOURCE_INVALID: lease stream names another file")
            for parent in path.parents:
                if is_reparse(parent) or not stat.S_ISDIR(parent.lstat().st_mode):
                    raise BackupCorruptError("BACKUP_SOURCE_INVALID: lease anchor parent is unsafe")
            before = path.lstat()
            fd_before = os.fstat(stream.fileno())
            if (is_reparse(path) or not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(fd_before.st_mode)
                    or before.st_size > self.MAX_MANIFEST_BYTES):
                raise BackupCorruptError("BACKUP_SOURCE_INVALID: unsupported lease anchor")
            common = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            identity = lambda info: (*common(info), info.st_ctime_ns, info.st_mode)
            if common(before) != common(fd_before):
                raise BackupCorruptError("BACKUP_SOURCE_INVALID: lease stream and path differ")
            position = stream.tell()
            try:
                stream.seek(0)
                content = stream.read(before.st_size + 1)
            finally:
                stream.seek(position)
            after = path.lstat()
            fd_after = os.fstat(stream.fileno())
            # Windows path stat and fstat expose different ctime semantics; each must remain stable.
            if (identity(before) != identity(after) or identity(fd_before) != identity(fd_after)
                    or common(after) != common(fd_after) or is_reparse(path)
                    or not isinstance(content, bytes) or len(content) != before.st_size):
                raise BackupCorruptError("BACKUP_SOURCE_INVALID: lease anchor changed while reading")
            return content
        except (OSError, TypeError, ValueError) as exc:
            if isinstance(exc, BackupCorruptError):
                raise
            raise BackupCorruptError("BACKUP_SOURCE_INVALID: unreadable lease anchor") from exc

    def _source_inventory(self, sessions, lease_streams: dict[str, BinaryIO] | None = None):
        result = {}
        for sid in sessions:
            folder = self.projects_root / sid
            try:
                require_no_pending(folder)
            except TakeAcceptanceError as exc:
                raise BackupCorruptError("BACKUP_BUSY: finish or recover take acceptance first") from exc
            for root, dirs, files in os.walk(folder):
                for name in dirs + files:
                    path = Path(root) / name
                    if path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(str(path)):
                        raise BackupCorruptError("BACKUP_SOURCE_INVALID: linked source entry")
                    if (name in {"workflow.lock", "run.lock", "import-staging"} or name.startswith('.report-staging-')
                            or name.endswith((".partial", ".copying.mp4", ".tmp"))):
                        raise BackupCorruptError("BACKUP_BUSY: finish or recover in-flight native work first")
                for name in sorted(files):
                    path = Path(root) / name
                    relative = "sessions/" + path.relative_to(self.projects_root).as_posix()
                    self._safe_member_name(relative)
                    before = path.stat(follow_symlinks=False)
                    if not stat.S_ISREG(before.st_mode) or before.st_size > self.MAX_MEMBER_BYTES:
                        raise BackupCorruptError("BACKUP_SOURCE_INVALID: unsupported source file")
                    if lease_streams is not None and relative in lease_streams:
                        digest = hashlib.sha256(self._lease_anchor_bytes(path, lease_streams[relative])).hexdigest()
                    else:
                        digest = sha256_file(path)
                    after = path.stat(follow_symlinks=False)
                    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                    if identity(before) != identity(after):
                        raise BackupCorruptError("BACKUP_SOURCE_CHANGED: file changed while hashing")
                    result[relative] = {"sha256": digest, "bytes": before.st_size, "identity": identity(before)}
        if len(result) > self.MAX_MEMBERS - 2 or sum(i["bytes"] for i in result.values()) > self.MAX_TOTAL_BYTES:
            raise BackupCorruptError("BACKUP_LIMIT_EXCEEDED: source inventory exceeds archive limits")
        return result

    @staticmethod
    def _database_generation(database, projects, sessions):
        from recording_store import RecordingStore
        index = None
        try:
            index = SessionIndex(database, projects, read_only=True)
            if (index.conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or index.conn.execute("PRAGMA foreign_key_check").fetchone() is not None):
                raise ValueError("database integrity check")
            present = sorted(row[0] for row in index.conn.execute("SELECT id FROM sessions WHERE present=1"))
            if present != sorted(sessions):
                raise ValueError("session index and file inventory differ")
            for sid in present:
                folder = Path(projects) / sid
                from report_generation import committed_reports
                committed_reports(index, sid, check_inputs=False)
                for table in ("sources", "artifacts"):
                    rows = index.conn.execute(f"SELECT * FROM {table} WHERE session_id=?", (sid,)).fetchall()
                    if table == "sources":
                        candidates = {"raw/" + role + ".mp4" for role in ROLES}
                        indexed = {"raw/" + row["role"] + ".mp4" for row in rows}
                    else:
                        candidates = set(INDEXED_EVIDENCE_FILES)
                        candidates.update("exports/" + p.name for p in (folder / "exports").glob("*.motion.json"))
                        indexed = {row["artifact_key"] for row in rows}
                    if any((folder / name).is_file() for name in candidates - indexed):
                        raise ValueError("file evidence missing from the index snapshot")
                    for row in rows:
                        if table == "sources" and row["role"] not in ROLES:
                            raise ValueError("unknown source role")
                        name = "raw/" + row["role"] + ".mp4" if table == "sources" else row["artifact_key"]
                        BackupManager._safe_member_name("sessions/" + sid + "/" + name)
                        if row["filename"] != Path(name).name or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None:
                            raise ValueError("invalid indexed reference")
                        observed = index._contained_digest(folder, folder / name)
                        state = "missing" if observed is None else "unchanged" if observed == row["sha256"] else "changed"
                        if row["observed_sha256"] != observed or row["integrity_state"] != state:
                            raise ValueError("indexed observation and file snapshot differ")
            recordings = RecordingStore(index)
            rows = index.conn.execute("SELECT session_id FROM recordings ORDER BY session_id").fetchall()
            for row in rows:
                recordings.verify(row[0])
            return {"index_schema": SCHEMA_VERSION, "audit_tip": index.verify_audit(),
                    "recording_count": len(rows)}
        except (ValueError, sqlite3.Error, KeyError, TypeError, OSError) as exc:
            raise BackupCorruptError("BACKUP_DATABASE_INVALID: index/audit/recording generation failed validation") from exc
        finally:
            if index is not None: index.close()

    MAX_MEMBERS = 10_000
    MAX_MEMBER_BYTES = 1024 ** 3
    MAX_TOTAL_BYTES = 10 * (1024 ** 3)
    MAX_RATIO = 100
    MAX_MANIFEST_BYTES = 8 * 1024 * 1024

    @staticmethod
    def _safe_member_name(name: object) -> tuple[str, ...]:
        """A portable non-traversing path, without Windows aliases or reparse tricks."""
        if (not isinstance(name, str) or len(name) > 4096 or not name
                or name.startswith("/") or "\\" in name or ":" in name
                or unicodedata.normalize("NFC", name) != name
                or unicodedata.normalize("NFKC", name) != name):
            raise BackupCorruptError("BACKUP_PATH_INVALID: unsafe archive path")
        parts = name.split("/")
        if any(not p or p in (".", "..") or p.rstrip(" .") != p
               or p.split(".", 1)[0].upper() in WINDOWS_RESERVED
               or any(ord(ch) < 32 or ord(ch) == 127 or ch in '<>"|?*' for ch in p)
               for p in parts):
            raise BackupCorruptError("BACKUP_PATH_INVALID: unsafe archive component")
        return tuple(parts)

    @staticmethod
    def _decode_manifest(data: bytes) -> dict:
        try:
            result = strict_json_loads(data.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: unreadable JSON") from exc
        if not isinstance(result, dict):
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: object required")
        return result

    def _preflight(self, archive: zipfile.ZipFile) -> tuple[dict, dict[str, zipfile.ZipInfo]]:
        infos = archive.infolist()
        if not infos or len(infos) > self.MAX_MEMBERS:
            raise BackupCorruptError("BACKUP_LIMIT_EXCEEDED: too many archive members")
        members: dict[str, zipfile.ZipInfo] = {}
        aliases = set()
        path_components: dict[str, str] = {}
        directories = set()
        total = 0
        for info in infos:
            parts = self._safe_member_name(info.filename)
            if info.is_dir():
                raise BackupCorruptError("BACKUP_PATH_INVALID: directory ZIP members unsupported")
            key = "/".join(parts).casefold()
            if key in aliases or key in directories:
                raise BackupCorruptError("BACKUP_PATH_INVALID: duplicate or case-alias member")
            for length in range(1, len(parts) + 1):
                component = "/".join(parts[:length])
                folded = component.casefold()
                if path_components.setdefault(folded, component) != component:
                    raise BackupCorruptError("BACKUP_PATH_INVALID: case-alias directory")
                if length < len(parts):
                    if folded in aliases:
                        raise BackupCorruptError("BACKUP_PATH_INVALID: file/directory collision")
                    directories.add(folded)
            aliases.add(key)
            mode = info.external_attr >> 16
            if (stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or info.external_attr & 0x400):
                raise BackupCorruptError("BACKUP_PATH_INVALID: linked or nonregular member")
            if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise BackupCorruptError("BACKUP_FORMAT_INVALID: encrypted or unsupported compression")
            if (info.file_size < 0 or info.compress_size < 0
                    or info.file_size > self.MAX_MEMBER_BYTES):
                raise BackupCorruptError("BACKUP_LIMIT_EXCEEDED: member exceeds 1 GiB")
            if info.file_size > 0 and (
                info.compress_size == 0 or info.file_size > info.compress_size * self.MAX_RATIO
            ):
                raise BackupCorruptError("BACKUP_LIMIT_EXCEEDED: suspicious compression ratio")
            total += info.file_size
            if total > self.MAX_TOTAL_BYTES:
                raise BackupCorruptError("BACKUP_LIMIT_EXCEEDED: archive exceeds 10 GiB")
            members[info.filename] = info

        manifest_info = members.get("backup_manifest.json")
        if manifest_info is None or manifest_info.file_size > self.MAX_MANIFEST_BYTES:
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: missing or oversized manifest")
        manifest = self._decode_manifest(archive.read(manifest_info))
        if manifest.get("schema") not in {"kinelab.backup.v1", "kinelab.backup.v2"}:
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: unsupported schema")
        if manifest["schema"] == "kinelab.backup.v2":
            generation = manifest.get("generation")
            if (not isinstance(generation, dict)
                    or set(generation) != {"id", "index_schema", "audit_tip", "recording_count"}
                    or not isinstance(generation["id"], str) or re.fullmatch(r"[0-9a-f]{32}", generation["id"]) is None
                    or type(generation["index_schema"]) is not int or generation["index_schema"] != SCHEMA_VERSION
                    or not isinstance(generation["audit_tip"], str) or re.fullmatch(r"[0-9a-f]{64}", generation["audit_tip"]) is None
                    or type(generation["recording_count"]) is not int or generation["recording_count"] < 0
                    or manifest.get("database_included") is not True):
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: recovery generation required")
        sessions = manifest.get("sessions")
        files = manifest.get("files")
        database_included = manifest.get("database_included")
        file_count = manifest.get("file_count")
        if (not isinstance(sessions, list) or not isinstance(files, list)
                or type(database_included) is not bool or type(file_count) is not int
                or file_count != len(files) or file_count > self.MAX_MEMBERS - 1):
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: inventory fields inconsistent")
        sid_set = set()
        for sid in sessions:
            try:
                _check_id(sid)
            except (ValueError, TypeError) as exc:
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: unsafe session id") from exc
            folded = sid.casefold()
            if folded in sid_set:
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: repeated session alias")
            sid_set.add(folded)

        listed = set()
        listed_aliases = set()
        config_roles = set()
        for item in files:
            if not isinstance(item, dict):
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: file objects required")
            rel = item.get("path")
            if not isinstance(rel, str):
                raise BackupCorruptError("BACKUP_PATH_INVALID: unsafe archive path")
            parts = self._safe_member_name(rel)
            if len(parts) == 1 and rel == "index.db":
                if not database_included:
                    raise BackupCorruptError("BACKUP_MANIFEST_INVALID: undeclared database")
            elif (len(parts) >= 3 and parts[0] == "sessions"
                  and parts[1] in sessions):
                if len(parts) == 3 and parts[2] == "Config.toml":
                    config_roles.add(parts[1])
            else:
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: undeclared session file")
            if rel in listed or rel.casefold() in listed_aliases:
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: duplicate file entries")
            listed.add(rel)
            listed_aliases.add(rel.casefold())
            nbytes = item.get("bytes")
            digest = item.get("sha256")
            if (type(nbytes) is not int or nbytes < 0 or nbytes > self.MAX_MEMBER_BYTES
                    or not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None):
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: size or digest invalid")
            listed_info = members.get(rel)
            if listed_info is None or listed_info.file_size != nbytes:
                raise BackupCorruptError("BACKUP_MANIFEST_INVALID: listed file absent or different size")
        if ("index.db" in listed) != database_included:
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: database inventory mismatch")
        if set(sessions) != config_roles:
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: missing session Config.toml")
        if set(members) != (listed | {"backup_manifest.json"}):
            raise BackupCorruptError("BACKUP_MANIFEST_INVALID: unexpected ZIP member")
        return manifest, members

    def _verify_members(self, archive, manifest, members, stage=None):
        """Stream the complete bounded inventory; extraction is optional."""
        for item in manifest["files"]:
            digest = hashlib.sha256()
            size = 0
            output = None
            try:
                if stage is not None:
                    dest = stage.joinpath(*item["path"].split("/"))
                    if not dest.resolve().is_relative_to(stage):
                        raise BackupCorruptError("BACKUP_PATH_INVALID: staging traversal")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    output = dest.open("xb")
                with archive.open(members[item["path"]]) as source:
                    while block := source.read(1024 * 1024):
                        size += len(block)
                        if size > item["bytes"] or size > self.MAX_MEMBER_BYTES:
                            raise BackupCorruptError("BACKUP_CORRUPT: expanded size mismatch")
                        digest.update(block)
                        if output is not None: output.write(block)
                if size != item["bytes"] or digest.hexdigest() != item["sha256"].lower():
                    raise BackupCorruptError("BACKUP_CORRUPT: inventory hash or size mismatch")
                if output is not None:
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                if output is not None: output.close()

    def restore_generation(self, zip_path: Path | str, destination: Path | str) -> dict:
        """Publish a verified full generation to a new root; never activate or merge it."""
        if sys.platform != "win32":
            raise BackupConflictError("RESTORE_PLATFORM_UNVERIFIED: atomic directory recovery is verified for Windows only")
        target = Path(destination).absolute()
        if (any(p.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(str(p))
                for p in (target, *target.parents))
                or not target.parent.is_dir()):
            raise BackupCorruptError("BACKUP_PATH_INVALID: recovery requires an existing unlinked parent")
        target = target.resolve()
        self._validate_existing_target(target, target.parent)
        if target.is_relative_to(self.projects_root) and target.parent != self.projects_root / "recovery-generations":
            raise BackupConflictError("RESTORE_CONFLICT: recovery cannot publish inside active sessions")
        stage = None
        try:
            with zipfile.ZipFile(zip_path) as archive:
                manifest, members = self._preflight(archive)
                if manifest["schema"] != "kinelab.backup.v2":
                    raise BackupCorruptError("BACKUP_MANIFEST_INVALID: legacy archive has no complete recovery generation")
                stage = Path(tempfile.mkdtemp(prefix=".restore-generation-", dir=target.parent))
                (stage / "sessions").mkdir()
                self._verify_members(archive, manifest, members, stage)
            for sid in manifest["sessions"]:
                try:
                    require_no_pending(stage / "sessions" / sid)
                except TakeAcceptanceError as exc:
                    raise BackupCorruptError("BACKUP_CORRUPT: unfinished take acceptance in recovery generation") from exc
            actual = self._database_generation(stage / "index.db", stage / "sessions", manifest["sessions"])
            if actual != {key: value for key, value in manifest["generation"].items() if key != "id"}:
                raise BackupCorruptError("BACKUP_DATABASE_INVALID: declared generation differs")
            (stage / "index.db").rename(stage / "sessions/.kinelab_index.db")
            with (stage / "sessions/.recovery-manifest.json").open("x", encoding="utf-8") as receipt:
                json.dump(manifest, receipt, allow_nan=False)
                receipt.flush(); os.fsync(receipt.fileno())
            self._validate_existing_target(target, target.parent)
            for sid in manifest["sessions"]:
                try:
                    require_no_pending(stage / "sessions" / sid)
                except TakeAcceptanceError as exc:
                    raise BackupCorruptError("BACKUP_CORRUPT: unfinished take acceptance in recovery generation") from exc
            # On supported Windows, rename of a directory never replaces an existing target.
            (stage / "sessions").rename(target)
            return {"ok": True, "restored_sessions": manifest["sessions"], "database_restored": True,
                    "active_workspace_changed": False, "overwrite_permitted": False,
                    "generation_id": manifest["generation"]["id"],
                    "message": "Verified recovery generation published to a new isolated root; active workspace unchanged"}
        except (zipfile.BadZipFile, EOFError) as exc:
            raise BackupCorruptError("BACKUP_CORRUPT: truncated or malformed ZIP") from exc
        finally:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)

    @staticmethod
    def _validate_existing_target(path: Path, base: Path) -> None:
        if path.parent.resolve() != base:
            raise BackupCorruptError("BACKUP_PATH_INVALID: restore must stay inside projects")
        if (os.path.lexists(str(path))
                or getattr(os.path, "isjunction", lambda _: False)(str(path))):
            raise BackupConflictError("RESTORE_CONFLICT: destination exists; originals preserved")

    def inspect_backup(self, zip_path: Path | str) -> dict:
        target_zip = Path(zip_path).resolve()
        if not target_zip.is_file():
            raise FileNotFoundError(f"Backup file not found: {target_zip}")
        try:
            with zipfile.ZipFile(target_zip, "r") as archive:
                manifest, _ = self._preflight(archive)
            return {
                "schema": manifest["schema"],
                "created_at_utc": manifest.get("created_at_utc"),
                "host": manifest.get("host"),
                "session_count": len(manifest["sessions"]),
                "sessions": manifest["sessions"],
                "database_included": manifest["database_included"],
                "file_count": len(manifest["files"]),
                "recovery_scope": "new_root_full_generation" if manifest["schema"] == "kinelab.backup.v2" else "legacy_session_import",
                "hashes_verified": False, "validation": "structure_only",
            }
        except (zipfile.BadZipFile, EOFError, OSError) as exc:
            raise BackupCorruptError("BACKUP_CORRUPT: unreadable archive") from exc

    def restore_backup(self, zip_path: Path | str, overwrite: bool = False) -> dict:
        with self._restore_lock():
            self._finish_legacy_recovery(self._recover_legacy_stages())
            return self._restore_backup_locked(zip_path, overwrite)

    def _restore_backup_locked(self, zip_path: Path | str, overwrite: bool = False) -> dict:
        if overwrite is not False:
            raise BackupConflictError(
                "RESTORE_OVERWRITE_UNAVAILABLE: destructive restoration is disabled; "
                "existing sessions are immutable in this release"
            )
        target_zip = Path(zip_path).resolve()
        if not target_zip.is_file():
            raise FileNotFoundError(f"Backup file not found: {target_zip}")
        stage = None
        published: list[tuple[Path, os.stat_result]] = []
        committed = False
        try:
            with zipfile.ZipFile(target_zip, "r") as archive:
                manifest, members = self._preflight(archive)
                if manifest["schema"] == "kinelab.backup.v2":
                    raise BackupConflictError("RESTORE_NEW_ROOT_REQUIRED: complete generations cannot merge into an active workspace")
                sessions = manifest["sessions"]
                for sid in sessions:
                    self._validate_existing_target(self.projects_root / sid, self.projects_root)
                stage = Path(tempfile.mkdtemp(prefix=".restore-staging-", dir=self.projects_root))
                for item in manifest["files"]:
                    relative = item["path"]
                    dest = stage.joinpath(*relative.split("/"))
                    if not dest.resolve().is_relative_to(stage):
                        raise BackupCorruptError("BACKUP_PATH_INVALID: staging traversal")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open(members[relative], "r") as inp, dest.open("xb") as out:
                        while True:
                            block = inp.read(1024 * 1024)
                            if not block:
                                break
                            size += len(block)
                            if size > item["bytes"] or size > self.MAX_MEMBER_BYTES:
                                raise BackupCorruptError("BACKUP_CORRUPT: expanded size mismatch")
                            digest.update(block)
                            out.write(block)
                        out.flush()
                        os.fsync(out.fileno())
                    if size != item["bytes"] or digest.hexdigest() != item["sha256"].lower():
                        raise BackupCorruptError(f"BACKUP_CORRUPT: verified hash or size mismatch for {relative}")
                for sid in sessions:
                    source = stage / "sessions" / sid
                    if not source.is_dir() or not (source / "Config.toml").is_file():
                        raise BackupCorruptError("BACKUP_MANIFEST_INVALID: incomplete staged session")
                    try:
                        require_no_pending(source)
                    except TakeAcceptanceError as exc:
                        raise BackupCorruptError("BACKUP_CORRUPT: unfinished take acceptance in legacy import") from exc
                journal: dict = {
                    "schema": self.JOURNAL_SCHEMA, "operation_id": uuid4().hex,
                    "stage_name": stage.name, "root_identity": self._directory_identity(self.projects_root),
                    "stage_identity": self._directory_identity(stage),
                    "archive": {"sha256": sha256_file(target_zip), "bytes": target_zip.stat().st_size},
                    "ignored_database": None,
                    "sessions": [], "phase": "VERIFIED", "intent": None, "index_reconciled": False,
                }
                for sid in sessions:
                    source = stage / "sessions" / sid
                    files, directories = self._restore_inventory(source)
                    journal["sessions"].append({"id": sid, "identity": self._directory_identity(source),
                                                "files": files, "directories": directories})
                ignored_database = stage / "index.db"
                if ignored_database.is_file():
                    info = ignored_database.stat(follow_symlinks=False)
                    journal["ignored_database"] = {"sha256": sha256_file(ignored_database), "bytes": info.st_size,
                                                   "identity": [info.st_dev, info.st_ino]}
                self._check_restore_journal_capacity(journal)
                self._write_restore_journal(stage, journal)
                for sid in sessions:
                    target = self.projects_root / sid
                    self._validate_existing_target(target, self.projects_root)
                    source = stage / "sessions" / sid
                    journal.update(phase="PUBLISHING", intent={"kind": "publish", "session_id": sid})
                    self._write_restore_journal(stage, journal)
                    self._restore_locations(stage, journal)
                    identity = source.stat(follow_symlinks=False)
                    source.rename(target)
                    published.append((target, identity))
                    journal["intent"] = None
                    self._write_restore_journal(stage, journal)
                journal.update(phase="ALL_PUBLISHED", intent=None)
                self._write_restore_journal(stage, journal)
                if self.index:
                    self._restore_locations(stage, journal)
                    self.index.reindex()
                journal.update(phase="COMMITTED", index_reconciled=self.index is not None)
                self._write_restore_journal(stage, journal)
                self._restore_locations(stage, journal, terminal=True)
                committed = True
                return {
                    "ok": True, "restored_sessions": sessions,
                    "database_restored": False, "overwrite_permitted": False,
                    "message": f"Safely restored {len(sessions)} nonconflicting session(s)",
                }
        except (zipfile.BadZipFile, EOFError) as exc:
            raise BackupCorruptError("BACKUP_CORRUPT: truncated or malformed ZIP") from exc
        finally:
            if stage is not None and not committed:
                for dest, identity in reversed(published):
                    if (dest.is_dir() and not dest.is_symlink()
                            and not getattr(os.path, "isjunction", lambda _: False)(str(dest))
                            and dest.resolve().parent == self.projects_root
                            and os.path.samestat(identity, dest.stat(follow_symlinks=False))):
                        shutil.rmtree(dest)
                shutil.rmtree(stage, ignore_errors=True)
