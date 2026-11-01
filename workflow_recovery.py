"""Conservative local diagnostics and optional archival of *orphaned* run locks.

Never deletes camera media, run manifests or processing outputs. Archiving a
lock does not make unfinished native artifacts valid; the next native run must
re-check its full recorded inventory and all measured quality gates.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psutil

from session_library import SessionLibrary
from take_acceptance import TakeAcceptanceError, checked_path, inspect_acceptance

LOCK_FORMATS = {
    "run.lock": re.compile(r"([1-9][0-9]{0,11})\Z"),
    "workflow.lock": re.compile(r"([1-9][0-9]{0,11}):([0-9a-f]{32})\Z"),
}
KNOWN_NATIVE_SCRIPTS = (
    "run_pipeline.py", "normalize_capture.py", "export_motion.py",
)


class RecoveryBlocked(ValueError):
    """A lock cannot safely be archived or assessed."""


def _session(project: Path) -> Path:
    path = Path(project)
    if path.is_symlink():
        raise RecoveryBlocked("Session paths must not be symlinks")
    path = path.resolve()
    try:
        SessionLibrary(path.parent).open_session(path.name)
    except (OSError, ValueError) as error:
        raise RecoveryBlocked("Cannot verify this session folder") from error
    return path


def _related_processes(project: Path) -> list[int]:
    """Look for all identifiable workers for the same local project."""
    project_text = str(project).casefold()
    pids = []
    for proc in psutil.process_iter(attrs=("pid", "cmdline")):
        try:
            args = proc.info.get("cmdline") or []
            line = " ".join(str(arg).casefold() for arg in args)
            if project_text in line and any(script in line for script in KNOWN_NATIVE_SCRIPTS):
                pids.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            # Unknown processes cannot be used as affirmative evidence.
            continue
    return sorted(set(pids))


def _inspect_lock(path: Path, related: list[int]) -> dict:
    if not path.exists() and not path.is_symlink():
        return {"state": "absent", "pid": None}
    if not path.is_file() or path.is_symlink():
        return {"state": "unknown", "pid": None}
    try:
        if path.stat().st_size > 200:
            return {"state": "unknown", "pid": None}
        owner = path.read_text(encoding="utf-8").strip()
        match = LOCK_FORMATS[path.name].fullmatch(owner)
        if match is None:
            return {"state": "unknown", "pid": None}
        pid = int(match.group(1))
        if psutil.pid_exists(pid):
            return {"state": "active", "pid": pid}
        if related:
            return {"state": "unsafe-related-process", "pid": pid,
                    "related_process_count": len(related)}
        return {"state": "orphaned", "pid": pid}
    except (OSError, UnicodeError, ValueError, psutil.Error):
        return {"state": "unknown", "pid": None}


def inspect_recovery(project: Path) -> dict:
    """Read-only status. No cleanup, file writes or guessed success states."""
    project = _session(project)
    try:
        related = _related_processes(project)
    except (OSError, psutil.Error) as error:
        raise RecoveryBlocked("Unable to inspect related processing processes") from error
    locks = {name: _inspect_lock(project / name, related) for name in LOCK_FORMATS}
    acceptance = inspect_acceptance(project)
    if acceptance["state"] != "clear":
        locks["takes/accept.lock"] = acceptance
    record_path = project / "run.json"
    statuses = []
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict) or record.get("schema") != "kinelab.run.v1":
                raise ValueError("Unexpected native run schema")
            stages = record.get("stages")
            if not isinstance(stages, list):
                raise TypeError("No list of stages")
            statuses = [s for s in stages if isinstance(s, dict) and s.get("status") in ("running", "failed")]
            native = "incomplete" if statuses else "recorded-stages-not-revalidated"
        except (OSError, ValueError, KeyError, TypeError):
            native = "invalid-manifest"
    else:
        native = "not-run"
    return {
        "session": str(project), "locks": locks,
        "native_run": native, "native_run_passed": False,
        "incomplete_stages": [s.get("name", "?") for s in statuses],
        "related_worker_count": len(related),
        "next_step": (
            "Never assume that an archived lock makes partial artifacts usable. "
            "Inspect run.json and stage output hashes; follow RUNBOOK.md. "
            "If old outputs conflict, preserve them and create a clean session."
        ),
    }


def recover_take_acceptance(project: Path, transaction_id: str, *, confirmed: bool) -> dict:
    """Direct operator action; never infer permission, stale ownership or validity."""
    if confirmed is not True:
        raise RecoveryBlocked("TAKE_RECOVERY_CONFIRMATION_REQUIRED: explicitly confirm this exact transaction")
    try:
        project = _session(checked_path(project))
        return SessionLibrary(project.parent)._recover_take_acceptance(project.name, transaction_id)
    except (OSError, ValueError) as error:
        if isinstance(error, TakeAcceptanceError):
            reason = str(error)
            if reason.startswith("TAKE_BUSY:"):
                reason = reason.replace("TAKE_BUSY:", "TAKE_RECOVERY_BUSY:", 1)
            elif reason.startswith(("TAKE_INPUT_CHANGED:", "TAKE_TRANSACTION_CHANGED:")):
                reason = "TAKE_RECOVERY_CHANGED: " + reason.partition(":")[2].strip()
            raise RecoveryBlocked(reason) from error
        raise RecoveryBlocked("TAKE_RECOVERY_UNKNOWN: session or transaction evidence is unavailable") from error


def archive_orphaned_lock(project: Path, lock_name: str, *, confirmed: bool) -> Path:
    """Require explicit operator approval and an absent owner process."""
    if lock_name not in LOCK_FORMATS:
        raise RecoveryBlocked("Only run.lock and workflow.lock may be archived")
    if confirmed is not True:
        raise RecoveryBlocked("Operator must explicitly confirm archiving the abandoned lock")
    project = _session(project)
    lock = project / lock_name
    if lock.is_symlink():
        raise RecoveryBlocked("Refusing to archive a symlink lock")
    status = inspect_recovery(project)["locks"][lock_name]
    if status["state"] != "orphaned":
        raise RecoveryBlocked("Lock is not proven orphaned: " + status["state"])
    initial = lock.read_bytes()
    if len(initial) > 200 or not initial:
        raise RecoveryBlocked("Invalid lock content")
    # Perform owner/related-process checks again immediately before renaming.
    if psutil.pid_exists(status["pid"]) or _related_processes(project):
        raise RecoveryBlocked("A related worker appeared; refusing archive")
    if lock.read_bytes() != initial:
        raise RecoveryBlocked("Lock changed during inspection")
    recovery = project / "recovery" / "abandoned-locks"
    recovery.mkdir(parents=True, exist_ok=True)
    if recovery.is_symlink() or not recovery.resolve().is_relative_to(project):
        raise RecoveryBlocked("Recovery archive escaped the session")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = recovery / f"{lock_name}.{timestamp}.{uuid4().hex}.archived"
    if dest.exists():
        raise RecoveryBlocked("Recovery archive destination already exists")
    os.rename(lock, dest)
    return dest
