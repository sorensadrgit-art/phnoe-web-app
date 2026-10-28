"""Local-first session lifecycle for KineLab PT.

Session folders and their verified manifests are authoritative. The index is
rebuilt from disk each time. No network access, cameras, or processing runs are
started by these functions. The mixed online sample is never registered as real.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

from capture_station import check_readiness, probe_clip
from session_contract import ROLES, sha256_file, load_session
from setup_project import register_captures

ROOT = Path(__file__).resolve().parent
DEFAULT_ROOT = ROOT / "projects"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)},
                    *{f"LPT{i}" for i in range(1, 10)}}


class SessionError(ValueError):
    """Operation refused without changing any registered camera originals."""


def _check_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not SAFE_ID.fullmatch(session_id):
        raise SessionError("SESSION_ID_INVALID: use letters, digits, dots, underscores or hyphens")
    if session_id.endswith(".") or session_id.split(".")[0].upper() in WINDOWS_RESERVED:
        raise SessionError("SESSION_ID_INVALID: Windows-reserved folder name")
    return session_id


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _test_only(path: Path) -> bool:
    return ((path / "SAMPLE-PROVENANCE.json").exists()
            or (path / "TEST-ONLY-NOT-CALIBRATED.txt").exists()
            or (path / "TEST-STATUS.md").exists())


def _copy_verified(source: Path, dest: Path) -> None:
    """Copy atomically within one filesystem, never overwrite an existing file."""
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"Destination exists: {dest}")
    partial = dest.with_name(dest.name + "." + uuid4().hex + ".partial")
    try:
        with source.open("rb") as src, partial.open("xb") as target:
            shutil.copyfileobj(src, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if sha256_file(partial) != sha256_file(source):
            raise SessionError("INPUT_CHANGED: staged copy does not match original")
        # Same local volume; link creation fails if the destination exists.
        os.link(partial, dest)
    finally:
        partial.unlink(missing_ok=True)


class SessionLibrary:
    def __init__(self, projects_root: Path = DEFAULT_ROOT) -> None:
        self.projects_root = Path(projects_root).resolve()
        if not self.projects_root.is_dir():
            raise SessionError("SESSION_ROOT_MISSING: expected projects directory")

    def _path(self, session_id: str) -> Path:
        candidate = self.projects_root / _check_id(session_id)
        if candidate.is_symlink():
            raise SessionError("SESSION_PATH_INVALID: symlink session folders are not supported")
        resolved = candidate.resolve()
        if resolved.parent != self.projects_root:
            raise SessionError("SESSION_PATH_INVALID: session must stay inside projects")
        return candidate

    def open_session(self, session_id: str) -> Path:
        path = self._path(session_id)
        if not path.is_dir() or not (path / "Config.toml").is_file():
            raise SessionError("SESSION_MISSING: no valid local KineLab session configuration")
        return path

    def _describe(self, path: Path) -> dict:
        template = _read_json(path / "session-template.json")
        registered = (path / "session.json").exists()
        recorded = _read_json(path / "session.json") if registered else None
        test_only = _test_only(path)
        count = sum((path / "raw" / (role + ".mp4")).is_file() for role in ROLES)
        if test_only:
            kind, status = "test-only", "test-only"
        elif registered:
            kind = recorded.get("kind", "unknown") if recorded else "unknown"
            try:
                validated = load_session(path)
                kind, status = validated["kind"], "registered"
            except (ValueError, OSError):
                status = "invalid"
        elif template is not None:
            kind, status = template.get("kind", "unknown"), "draft"
        else:
            kind, status = "legacy", "legacy"
        return {
            "id": path.name, "path": str(path), "kind": kind, "status": status,
            "captured_roles": count, "total_roles": len(ROLES),
            "can_register": status == "draft" and kind == "real" and not registered,
            "has_board_measurement": (path / "board-measurement.json").is_file(),
        }

    def list_sessions(self) -> list[dict]:
        result = []
        for path in sorted(self.projects_root.iterdir(), key=lambda p: p.name.casefold()):
            if not path.is_dir() or path.is_symlink() or not SAFE_ID.fullmatch(path.name):
                continue
            if not (path / "Config.toml").is_file():
                continue
            # Normalize descriptions consistently with explicit open path validation.
            result.append(self._describe(self.open_session(path.name)))
        return result

    def describe_session(self, session_id: str) -> dict:
        return self._describe(self.open_session(session_id))

    def create_session(self, session_id: str, *, kind: str = "real") -> Path:
        session_id = _check_id(session_id)
        if kind not in ("real", "demo"):
            raise SessionError("SESSION_KIND_INVALID: only real or demo sessions")
        path = self._path(session_id)
        if path.exists():
            raise SessionError("SESSION_EXISTS: select existing session instead of overwriting")
        script = ROOT / "setup_project.py"
        args = [sys.executable, "-B", str(script), "--project", str(path),
                "--session-id", session_id, "--kind", kind]
        result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=120)
        if result.returncode:
            # Deliberately preserve any partial folder for inspection, not deletion.
            raise SessionError("SESSION_CREATE_FAILED: " + (result.stderr.strip() or result.stdout.strip())[-600:])
        return self.open_session(session_id)

    def registration_readiness(self, session_id: str) -> dict:
        path = self.open_session(session_id)
        info = self._describe(path)
        if info["status"] != "draft" or info["kind"] != "real":
            message = ("SESSION_TEST_ONLY: mixed online recordings are not a real capture"
                       if info["kind"] == "test-only" else
                       "SESSION_LOCKED: only unregistered real sessions can be registered")
            return {"ready_to_register": False, "missing": [], "issues": [message], "session": str(path)}
        result = check_readiness(path, inspect_existing=True)
        if (path / "session.json").exists():
            result["issues"].append("SESSION_LOCKED: already registered")
            result["ready_to_register"] = False
        return result

    def register_session(self, session_id: str) -> dict:
        preflight = self.registration_readiness(session_id)
        if not preflight.get("ready_to_register"):
            raise SessionError("SESSION_NOT_READY: " + "; ".join(
                preflight.get("issues") or ["missing " + ", ".join(preflight.get("missing", []))]))
        path = self.open_session(session_id)
        if (path / "session.json").exists():
            raise SessionError("SESSION_LOCKED: registered media cannot be replaced")
        try:
            return register_captures(path, session_id, "real")
        except (OSError, ValueError) as error:
            raise SessionError("SESSION_REGISTER_FAILED: " + str(error)) from error

    def _require_editable(self, session_id: str) -> Path:
        path = self.open_session(session_id)
        info = self._describe(path)
        if info["status"] != "draft" or info["kind"] != "real":
            raise SessionError("SESSION_LOCKED: only unregistered real sessions can take new footage")
        return path

    def stage_take(self, session_id: str, role: str, source: Path) -> Path:
        path = self._require_editable(session_id)
        if role not in ROLES:
            raise SessionError("TAKE_ROLE_INVALID: select one of the six camera roles")
        source_path = Path(source)
        if source_path.is_symlink():
            raise SessionError("TAKE_INPUT_INVALID: source symlinks not accepted")
        source = source_path.resolve()
        if not source.is_file() or source.suffix.lower() != ".mp4" or source.stat().st_size == 0:
            raise SessionError("TAKE_INPUT_INVALID: select a nonempty MP4")
        # Reject unreadable clips before copying; registration still requires six proper roles.
        probe_clip(source)
        target_dir = path / "takes" / role
        target_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.is_symlink() or not target_dir.resolve().is_relative_to(path):
            raise SessionError("TAKE_PATH_INVALID: alternate footage folder must be local")
        dest = target_dir / (uuid4().hex + ".mp4")
        _copy_verified(source, dest)
        return dest

    def accept_take(self, session_id: str, role: str, take_file: Path) -> Path:
        project = self._require_editable(session_id)
        if role not in ROLES:
            raise SessionError("TAKE_ROLE_INVALID: invalid camera role")
        staged_parent = project / "takes" / role
        staged_dir = staged_parent.resolve()
        if staged_parent.is_symlink() or not staged_dir.is_relative_to(project) or Path(take_file).is_symlink():
            raise SessionError("TAKE_PATH_INVALID: staged take cannot escape the session")
        staged = Path(take_file).resolve()
        if staged.parent != staged_dir or staged.suffix.lower() != ".mp4" or not staged.is_file():
            raise SessionError("TAKE_PATH_INVALID: choose a staged take for this role")
        probe_clip(staged)
        destination = project / "raw" / (role + ".mp4")
        takes_dir = project / "takes"
        takes_dir.mkdir(exist_ok=True)
        lock = takes_dir / "accept.lock"
        try:
            with lock.open("x", encoding="utf-8") as stream:
                stream.write(str(os.getpid()))
        except FileExistsError as error:
            raise SessionError("TAKE_BUSY: inspect an existing acceptance process/lock") from error
        try:
            self._require_editable(session_id)
            archive = takes_dir / "archive"
            archive.mkdir(exist_ok=True)
            if destination.is_symlink():
                raise SessionError("TAKE_PATH_INVALID: canonical capture symlink")
            if destination.exists():
                archive_name = archive / (role + "-" + uuid4().hex + ".mp4")
                _copy_verified(destination, archive_name)
                if sha256_file(destination) != sha256_file(archive_name):
                    raise SessionError("TAKE_ARCHIVE_INVALID: original capture was changed")
            temp = destination.with_name("." + role + "-" + uuid4().hex + ".replacement")
            try:
                _copy_verified(staged, temp)
                self._require_editable(session_id)
                # Atomic publication. Existing originals were independently archived first.
                os.replace(temp, destination)
            finally:
                temp.unlink(missing_ok=True)
            return destination
        finally:
            lock.unlink(missing_ok=True)
