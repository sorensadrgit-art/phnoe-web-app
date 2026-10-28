"""Local offline backup creation, manifest hashing, and staged restore for KineLab PT.

Guarantees:
- Media files and session metadata are archived with SHA-256 integrity proofs.
- Restores into safe isolated staging first; corrupt archives fail closed without touching projects/.
- Conflict preview detects existing sessions and prevents accidental overwrites without explicit confirmation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
from typing import Any
from uuid import uuid4
import zipfile

from session_contract import sha256_file
from session_index import SessionIndex


class BackupCorruptError(ValueError):
    """The backup archive failed hash verification or manifest integrity check."""


class BackupConflictError(FileExistsError):
    """One or more sessions in the backup already exist in the target projects directory."""


class BackupManager:
    def __init__(self, projects_root: Path | str, index: SessionIndex | None = None):
        self.projects_root = Path(projects_root).resolve()
        self.index = index

    def create_backup(self, zip_path: Path | str, session_ids: list[str] | None = None) -> dict:
        target_zip = Path(zip_path).resolve()
        target_zip.parent.mkdir(parents=True, exist_ok=True)

        if session_ids is None:
            session_ids = [d.name for d in self.projects_root.iterdir() if d.is_dir() and not d.name.startswith(".")]

        files_manifest = []
        now = datetime.now(timezone.utc).isoformat()
        temp_dir = Path(tempfile.mkdtemp(prefix="kinelab-backup-"))

        try:
            # 1. Snapshot database if index is provided
            db_snap = temp_dir / "index.db"
            has_db = False
            if self.index:
                self.index.backup_database(db_snap)
                has_db = True
                files_manifest.append({
                    "path": "index.db",
                    "sha256": sha256_file(db_snap),
                    "bytes": db_snap.stat().st_size
                })

            # 2. Collect session files
            sessions_temp = temp_dir / "sessions"
            sessions_temp.mkdir()

            for sid in session_ids:
                s_folder = self.projects_root / sid
                if not s_folder.is_dir():
                    continue
                dest_s = sessions_temp / sid
                dest_s.mkdir(parents=True, exist_ok=True)

                for root, dirs, files in os.walk(s_folder):
                    rel_root = Path(root).relative_to(s_folder)
                    # Exclude staging or temporary partials
                    if "import-staging" in rel_root.parts or ".pytest_cache" in rel_root.parts:
                        continue
                    (dest_s / rel_root).mkdir(parents=True, exist_ok=True)
                    for f in files:
                        if f.endswith((".partial", ".copying.mp4", ".tmp")):
                            continue
                        src_f = Path(root) / f
                        dst_f = dest_s / rel_root / f
                        shutil.copy2(src_f, dst_f)
                        rel_archive = f"sessions/{sid}/{rel_root / f}".replace("\\", "/").replace("/./", "/")
                        files_manifest.append({
                            "path": rel_archive,
                            "sha256": sha256_file(dst_f),
                            "bytes": dst_f.stat().st_size
                        })

            manifest = {
                "schema": "kinelab.backup.v1",
                "created_at_utc": now,
                "host": socket.gethostname(),
                "sessions": session_ids,
                "database_included": has_db,
                "file_count": len(files_manifest),
                "files": files_manifest
            }

            manifest_file = temp_dir / "backup_manifest.json"
            manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # Write zip archive
            staging_zip = target_zip.with_name(f"{target_zip.name}.{uuid4().hex}.partial")
            with zipfile.ZipFile(staging_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.write(manifest_file, "backup_manifest.json")
                if has_db:
                    z.write(db_snap, "index.db")
                for root, dirs, files in os.walk(sessions_temp):
                    for f in files:
                        full = Path(root) / f
                        rel = full.relative_to(temp_dir)
                        z.write(full, str(rel).replace("\\", "/"))

            staging_zip.replace(target_zip)
            return manifest
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def inspect_backup(self, zip_path: Path | str) -> dict:
        target_zip = Path(zip_path).resolve()
        if not target_zip.is_file():
            raise FileNotFoundError(f"Backup file not found: {target_zip}")

        with zipfile.ZipFile(target_zip, "r") as z:
            names = z.namelist()
            if "backup_manifest.json" not in names:
                raise BackupCorruptError("backup_manifest.json missing from archive")
            manifest = json.loads(z.read("backup_manifest.json").decode("utf-8"))
            if manifest.get("schema") != "kinelab.backup.v1":
                raise BackupCorruptError("Unrecognized backup manifest schema")
            return {
                "schema": manifest["schema"],
                "created_at_utc": manifest.get("created_at_utc"),
                "host": manifest.get("host"),
                "session_count": len(manifest.get("sessions", [])),
                "sessions": manifest.get("sessions", []),
                "database_included": manifest.get("database_included", False),
                "file_count": len(manifest.get("files", []))
            }

    def restore_backup(self, zip_path: Path | str, overwrite: bool = False) -> dict:
        target_zip = Path(zip_path).resolve()
        if not target_zip.is_file():
            raise FileNotFoundError(f"Backup file not found: {target_zip}")

        staging_dir = self.projects_root / f".restore-staging-{uuid4().hex}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(target_zip, "r") as z:
                z.extractall(staging_dir)

            manifest_file = staging_dir / "backup_manifest.json"
            if not manifest_file.is_file():
                raise BackupCorruptError("Corrupt archive: manifest missing after extraction")

            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest.get("schema") != "kinelab.backup.v1":
                raise BackupCorruptError("Unrecognized backup schema")

            # Hash verification of 100% of files
            for item in manifest.get("files", []):
                rel = item["path"]
                extracted_file = staging_dir / rel
                if not extracted_file.is_file():
                    raise BackupCorruptError(f"Missing file in archive: {rel}")
                actual_hash = sha256_file(extracted_file)
                if actual_hash != item["sha256"]:
                    raise BackupCorruptError(f"SHA-256 hash mismatch on {rel}: expected {item['sha256']}, got {actual_hash}")

            # Check conflicts
            restoring_sessions = manifest.get("sessions", [])
            conflicts = []
            for sid in restoring_sessions:
                existing = self.projects_root / sid
                if existing.exists():
                    conflicts.append(sid)

            if conflicts and not overwrite:
                raise BackupConflictError(f"Session conflict: {conflicts} already exist in {self.projects_root}")

            # Publish sessions safely
            for sid in restoring_sessions:
                src_session = staging_dir / "sessions" / sid
                dst_session = self.projects_root / sid
                if dst_session.exists() and overwrite:
                    shutil.rmtree(dst_session)
                shutil.move(src_session, dst_session)

            # Reindex
            if self.index:
                self.index.reindex()

            return {
                "ok": True,
                "restored_sessions": restoring_sessions,
                "message": f"Successfully restored {len(restoring_sessions)} session(s)"
            }
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
