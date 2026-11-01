"""Local-first session lifecycle for KineLab PT.

Session folders and their verified manifests are authoritative. The index is
rebuilt from disk each time. No network access, cameras, or processing runs are
started by these functions. The mixed online sample is never registered as real.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import take_acceptance as takes
from capture_station import PARTICIPANT_RECORDING_BLOCKED, PARTICIPANT_TRIAL_ROLES, _check_readiness_locked, probe_clip
from comparison_revision import observe_comparison_source
from local_diagnostics import log_local_failure
from session_contract import (
    ROLES,
    load_session,
    sha256_file,
    strict_json_loads,
    validate_session,
    validate_session_metadata,
)
from setup_project import _register_captures_locked

logger = logging.getLogger(__name__)
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
        value = strict_json_loads(path.read_text(encoding="utf-8-sig"))
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
        raise FileExistsError("Destination exists; original preserved")
    partial = dest.with_name(dest.name + "." + uuid4().hex + ".partial")
    try:
        with source.open("rb") as src, partial.open("xb") as target:
            shutil.copyfileobj(src, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if sha256_file(partial) != sha256_file(source):
            raise SessionError("INPUT_CHANGED: staged copy does not match original")
        # Same local volume; link creation fails if the destination exists.
        try:
            os.link(partial, dest)
        except FileExistsError:
            raise FileExistsError("Destination exists; original preserved") from None
    finally:
        partial.unlink(missing_ok=True)


class SessionLibrary:
    def __init__(self, projects_root: Path = DEFAULT_ROOT) -> None:
        self.projects_root = takes.checked_path(projects_root).resolve()
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
            if recorded is not None and kind == "live":
                status = recorded.get("status", "completed")
            else:
                try:
                    validated = load_session(path)
                    kind, status = validated["kind"], "registered"
                except (ValueError, OSError):
                    status = "invalid"
        elif template is not None:
            kind, status = template.get("kind", "unknown"), "draft"
        else:
            kind, status = "legacy", "legacy"
        unverified = (kind == "live" or (recorded or {}).get("kind") == "live"
                      or (registered and (not recorded or not isinstance(recorded.get("kind"), str)))
                      or (recorded or {}).get("schema") == "kinelab.live-session.v1"
                      or (path / "live_telemetry.json").exists())
        return {
            "id": path.name, "path": str(path), "kind": kind, "status": status,
            "evidence_status": "unverified" if unverified else "not_assessed",
            "captured_roles": count, "total_roles": len(ROLES),
            "can_register": status == "draft" and kind == "real" and not registered,
            "has_board_measurement": (path / "board-measurement.json").is_file(),
            "research_source_revision": observe_comparison_source(path),
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

    def metadata_confirmation(self, session_id: str) -> dict:
        """Read confirmed opaque metadata from unchanged, contained source bytes.

        Registered manifests are authoritative, including when invalid. This is
        format/provenance readback, not identity authentication or clinical proof.
        No legacy metadata is generated and no source artifact is modified.
        """
        result: dict = {
            "schema": "kinelab.session-metadata-readback.v1", "session_id": session_id,
            "status": "UNAVAILABLE", "metadata": None, "source": None,
            "reason": "METADATA_SOURCE_UNAVAILABLE",
        }
        try:
            project = takes.checked_path(self.open_session(session_id))
            takes.require_no_pending(project)
            registered = takes.local_path(project, "session.json")
            source = registered if registered.exists() else takes.local_path(project, "session-template.json")

            def bounded_read() -> tuple[bytes, tuple[int, ...]]:
                # Match the existing local JSON request/transaction 64 KiB limit.
                # Never call the unbounded full-file proof helper on metadata.
                limit = 64 * 1024
                checked = takes.checked_path(source)
                before = checked.stat(follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    raise SessionError("METADATA_SOURCE_INVALID: expected regular metadata file")
                if before.st_size > limit:
                    raise SessionError("METADATA_SOURCE_TOO_LARGE: metadata exceeds 64 KiB")

                def identity(item: os.stat_result) -> tuple[int, ...]:
                    return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_mode)

                with checked.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if identity(opened) != identity(before):
                        raise SessionError("METADATA_SOURCE_CHANGED: metadata changed before read")
                    raw = stream.read(limit + 1)
                    after_read = os.fstat(stream.fileno())
                after = takes.checked_path(source).stat(follow_symlinks=False)
                if len(raw) > limit or after_read.st_size > limit or after.st_size > limit:
                    raise SessionError("METADATA_SOURCE_TOO_LARGE: metadata grew beyond 64 KiB")
                # As in the house file proof, compare ctime within each stat
                # interface; Windows path/fd precision can legitimately differ.
                if (identity(before) != identity(after_read) or identity(before) != identity(after)
                        or before.st_ctime_ns != after.st_ctime_ns
                        or opened.st_ctime_ns != after_read.st_ctime_ns):
                    raise SessionError("METADATA_SOURCE_CHANGED: metadata changed while reading")
                return raw, (*identity(before), before.st_ctime_ns)

            raw, before = bounded_read()
            digest = hashlib.sha256(raw).hexdigest()
            data = strict_json_loads(raw.decode("utf-8-sig"))
            if (not isinstance(data, dict) or data.get("schema") != "kinelab.session.v1"
                    or data.get("session_id") != session_id or data.get("kind") not in ("real", "demo")):
                raise SessionError("METADATA_SOURCE_INVALID: session schema, identity or kind mismatch")
            if source == registered:
                validate_session(data, project)
            metadata = validate_session_metadata(data.get("metadata"))
            takes.require_no_pending(project)
            current, after = bounded_read()
            if after != before or hashlib.sha256(current).hexdigest() != digest:
                raise SessionError("METADATA_SOURCE_CHANGED: parsed bytes or file identity changed")
            if source != registered:
                takes.require_same(registered, None)
            return {**result, "status": "AVAILABLE", "metadata": metadata,
                    "source": {"path": source.name, "sha256": digest},
                    "reason": "Explicit operator format confirmation; identity, protocol approval and physical validity remain unverified"}
        except OSError as error:
            result["reason"] = "METADATA_SOURCE_READ_ERROR: " + type(error).__name__
        except (ValueError, UnicodeError) as error:
            prefix = str(error).partition(":")[0]
            code = prefix if re.fullmatch(r"[A-Z_]{1,80}", prefix) else "METADATA_SOURCE_INVALID"
            result["reason"] = code + ": " + type(error).__name__
        return result

    def create_session(self, session_id: str, *, kind: str = "real", metadata: dict | None = None) -> Path:
        session_id = _check_id(session_id)
        if kind not in ("real", "demo"):
            raise SessionError("SESSION_KIND_INVALID: only real or demo sessions")
        path = self._path(session_id)
        if path.exists():
            raise SessionError("SESSION_EXISTS: select existing session instead of overwriting")
        script = ROOT / "setup_project.py"
        args = [sys.executable, "-B", str(script), "--project", str(path),
                "--session-id", session_id, "--kind", kind]
        if metadata is not None:
            args += ["--metadata-json", json.dumps(validate_session_metadata(metadata))]
        result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=120)
        if result.returncode:
            # Deliberately preserve any partial folder for inspection, not deletion.
            raise SessionError(f"SESSION_CREATE_FAILED: setup exited with code {result.returncode}; partial folder preserved")
        return self.open_session(session_id)

    def registration_readiness(self, session_id: str) -> dict:
        path = self.open_session(session_id)
        try:
            with takes.acceptance_lease(path):
                takes.require_no_pending(path)
                return self._registration_readiness_locked(path)
        except OSError:
            return {"ready_to_register": False, "missing": [],
                    "issues": ["READINESS_UNAVAILABLE: local storage error"], "session": str(path)}
        except ValueError as error:
            return {"ready_to_register": False, "missing": [], "issues": [str(error)], "session": str(path)}

    def _registration_readiness_locked(self, path: Path) -> dict:
        info = self._describe(path)
        if info["status"] != "draft" or info["kind"] != "real":
            message = ("SESSION_TEST_ONLY: mixed online recordings are not a real capture"
                       if info["kind"] == "test-only" else
                       "SESSION_LOCKED: only unregistered real sessions can be registered")
            return {"ready_to_register": False, "missing": [], "issues": [message], "session": str(path)}
        result = _check_readiness_locked(path, inspect_existing=True)
        if (path / "session.json").exists():
            result["issues"].append("SESSION_LOCKED: already registered")
            result["ready_to_register"] = False
        return result

    def register_session(self, session_id: str) -> dict:
        path = self.open_session(session_id)
        try:
            with takes.acceptance_lease(path):
                takes.require_no_pending(path)
                preflight = self._registration_readiness_locked(path)
                if not preflight.get("ready_to_register"):
                    raise SessionError("SESSION_NOT_READY: " + "; ".join(
                        preflight.get("issues") or ["missing " + ", ".join(preflight.get("missing", []))]))
                if (path / "session.json").exists():
                    raise SessionError("SESSION_LOCKED: registered media cannot be replaced")
                template = _read_json(path / "session-template.json") or {}
                return _register_captures_locked(path, session_id, "real", metadata=template.get("metadata"))
        except OSError as error:
            log_local_failure(logger, logging.WARNING, "library_register_storage_error", error)
            raise SessionError("SESSION_REGISTER_FAILED: local storage error; source files preserved") from error
        except ValueError as error:
            raise SessionError("SESSION_REGISTER_FAILED: " + str(error)) from error

    def _require_editable(self, session_id: str) -> Path:
        path = self.open_session(session_id)
        info = self._describe(path)
        if info["status"] != "draft" or info["kind"] != "real":
            raise SessionError("SESSION_LOCKED: only unregistered real sessions can take new footage")
        return path

    def stage_take(self, session_id: str, role: str, source: Path) -> Path:
        if role in PARTICIPANT_TRIAL_ROLES:
            raise SessionError(PARTICIPANT_RECORDING_BLOCKED)
        path = self._require_editable(session_id)
        try:
            with takes.acceptance_lease(path):
                takes.require_no_pending(path)
                self._require_editable(session_id)
                return self._stage_take_locked(path, role, source)
        except OSError as error:
            log_local_failure(logger, logging.WARNING, "library_stage_storage_error", error)
            raise SessionError("TAKE_STAGE_REFUSED: local storage error; source files preserved") from error
        except ValueError as error:
            raise SessionError("TAKE_STAGE_REFUSED: " + str(error)) from error

    def _stage_take_locked(self, path: Path, role: str, source: Path) -> Path:
        if role in PARTICIPANT_TRIAL_ROLES:
            raise SessionError(PARTICIPANT_RECORDING_BLOCKED)
        if role not in ROLES:
            raise SessionError("TAKE_ROLE_INVALID: select one of the six camera roles")
        source = takes.checked_path(source)
        if not source.is_file() or source.suffix.lower() != ".mp4" or source.stat().st_size == 0:
            raise SessionError("TAKE_INPUT_INVALID: select a nonempty MP4")
        # Reject unreadable clips before copying; registration still requires six proper roles.
        proof = takes.file_proof(source)
        probe_clip(source)
        takes.require_same(source, proof)
        target_dir = takes.local_path(path, "takes", role)
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / (uuid4().hex + ".mp4")
        _copy_verified(source, dest)
        takes.require_same(source, proof)
        if not takes.matches_content(dest, proof.sha256, proof.size):
            raise SessionError("TAKE_INPUT_CHANGED: staged copy does not match inspected source")
        return dest

    def accept_take(self, session_id: str, role: str, take_file: Path) -> Path:
        if role in PARTICIPANT_TRIAL_ROLES:
            raise SessionError(PARTICIPANT_RECORDING_BLOCKED)
        project = self._require_editable(session_id)
        try:
            with takes.acceptance_lease(project):
                takes.require_no_pending(project)
                self._require_editable(session_id)
                return self._accept_take_locked(project, role, take_file)
        except OSError as error:
            log_local_failure(logger, logging.WARNING, "library_accept_storage_error", error)
            raise SessionError("TAKE_ACCEPT_REFUSED: local storage error; source files preserved") from error
        except ValueError as error:
            raise SessionError("TAKE_ACCEPT_REFUSED: " + str(error)) from error

    def _accept_take_locked(self, project: Path, role: str, take_file: Path) -> Path:
        if role in PARTICIPANT_TRIAL_ROLES:
            raise SessionError(PARTICIPANT_RECORDING_BLOCKED)
        if role not in ROLES:
            raise SessionError("TAKE_ROLE_INVALID: invalid camera role")
        staged_dir = takes.local_path(project, "takes", role)
        staged = takes.checked_path(take_file)
        if staged.parent != staged_dir or not takes.SAFE_NAME.fullmatch(staged.name) or not staged.is_file():
            raise SessionError("TAKE_PATH_INVALID: choose a staged take for this role")
        selected = takes.file_proof(staged)
        if selected.size == 0:
            raise SessionError("TAKE_INPUT_INVALID: selected take is empty")
        probe_clip(staged)
        takes.require_same(staged, selected)
        destination = takes.local_path(project, "raw", role + ".mp4")
        prior = takes.file_proof(destination) if destination.exists() else None
        transaction_id = uuid4().hex
        directory = takes.local_path(project, "takes/acceptance", transaction_id)
        directory.mkdir(parents=True, exist_ok=False)
        intent = {"schema": "kinelab.take-acceptance.v1", "transaction_id": transaction_id,
                  "session_id": project.name, "role": role, "staged_name": staged.name,
                  "staged_sha256": selected.sha256, "staged_bytes": selected.size,
                  "prior_sha256": prior.sha256 if prior else None, "prior_bytes": prior.size if prior else None}
        takes.validate_intent(intent, project, transaction_id)
        intent_proof = takes.write_record(directory / "intent.json", intent)
        takes.write_record(project / "takes/accept.lock", takes.marker_record(transaction_id, intent_proof.sha256))
        transaction = takes.pending_transaction(project, transaction_id)
        if prior is not None:
            archive = takes.local_path(project, "takes/archive")
            archive.mkdir(exist_ok=True)
            takes.require_same(destination, prior)
            _copy_verified(destination, transaction.archive)
            if not takes.matches_content(transaction.archive, prior.sha256, prior.size):
                raise SessionError("TAKE_ARCHIVE_INVALID: prior archive differs from immutable intent")
        takes.require_same(destination, prior)
        _copy_verified(staged, transaction.replacement)
        takes.require_same(staged, selected)
        takes.require_same(destination, prior)
        if not takes.matches_content(transaction.replacement, selected.sha256, selected.size):
            raise SessionError("TAKE_INPUT_CHANGED: replacement differs from inspected take")
        if takes.local_path(project, "session.json").exists():
            raise SessionError("SESSION_LOCKED: session registered during take acceptance")
        takes.require_owned_marker(transaction)
        # Only this verified transaction may publish; all earlier bytes remain archived.
        os.replace(transaction.replacement, destination)
        if not takes.matches_content(destination, selected.sha256, selected.size):
            raise SessionError("TAKE_INPUT_CHANGED: published capture differs from immutable intent")
        takes.require_owned_marker(transaction)
        result = _take_result(transaction, "selected-verified", [])
        _write_take_terminal(transaction, "commit.json", result)
        takes.retire_marker(transaction)
        return destination

    def _recover_take_acceptance(self, session_id: str, transaction_id: str) -> dict:
        """Private fixed recovery called only after explicit operator confirmation."""
        project = self.open_session(session_id)
        with takes.acceptance_lease(project):
            transaction = takes.pending_transaction(project, transaction_id)
            return _recover_take_locked(transaction)


def _take_result(transaction: takes.Transaction, outcome: str, quarantined: list[str]) -> dict:
    intent = transaction.intent
    return {"session_id": intent["session_id"], "transaction_id": transaction.transaction_id,
            "role": intent["role"], "outcome": outcome,
            "canonical_sha256": intent["staged_sha256"] if outcome == "selected-verified" else intent["prior_sha256"],
            "prior_sha256": intent["prior_sha256"], "archives_retained": True,
            "artifacts_quarantined": quarantined, "native_run_passed": False, "clinical_validation": "UNVERIFIED"}


def _write_take_terminal(transaction: takes.Transaction, name: str, result: dict) -> None:
    record = {"schema": "kinelab.take-acceptance-" + ("commit.v1" if name == "commit.json" else "recovery.v1"),
              "intent_sha256": transaction.intent_proof.sha256, **result}
    takes.write_record(transaction.directory / name, record)


def _recover_take_locked(transaction: takes.Transaction) -> dict:
    project, intent = transaction.project, transaction.intent
    takes.require_same(transaction.directory / "intent.json", transaction.intent_proof)
    if takes.local_path(project, "session.json").exists():
        raise takes.TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: registered session cannot be repaired by take recovery")
    selected = takes.file_proof(transaction.staged)
    if (selected.sha256, selected.size) != (intent["staged_sha256"], intent["staged_bytes"]):
        raise takes.TakeAcceptanceError("TAKE_RECOVERY_CHANGED: selected take changed; preserved")
    canonical = takes.file_proof(transaction.canonical) if takes.checked_path(transaction.canonical).exists() else None
    canonical_content = (canonical.sha256, canonical.size) if canonical else (None, None)
    if (transaction.terminal is not None and transaction.terminal["outcome"] == "selected-verified"
            and canonical_content == (intent["staged_sha256"], intent["staged_bytes"])):
        # The still-pending terminal receipt disambiguates identical clip bytes.
        outcome = "selected-verified"
    elif canonical_content == (intent["prior_sha256"], intent["prior_bytes"]):
        outcome = "previous-preserved"
    elif canonical_content == (intent["staged_sha256"], intent["staged_bytes"]):
        outcome = "selected-verified"
    else:
        raise takes.TakeAcceptanceError("TAKE_RECOVERY_CHANGED: canonical bytes are unknown; preserved")
    archive = takes.checked_path(transaction.archive)
    if archive.exists():
        if intent["prior_sha256"] is None or not takes.matches_content(archive, intent["prior_sha256"], intent["prior_bytes"]):
            raise takes.TakeAcceptanceError("TAKE_RECOVERY_CHANGED: prior archive differs from intent; preserved")
    elif outcome == "selected-verified" and intent["prior_sha256"] is not None:
        raise takes.TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: required prior archive is missing")
    replacement = takes.checked_path(transaction.replacement)
    quarantine = takes.local_path(project, "takes/acceptance", transaction.transaction_id, "quarantine", replacement.name)
    for candidate in (replacement, quarantine):
        if candidate.exists() and not takes.matches_content(candidate, intent["staged_sha256"], intent["staged_bytes"]):
            raise takes.TakeAcceptanceError("TAKE_RECOVERY_CHANGED: replacement/quarantine bytes are unknown; preserved")
    if transaction.terminal is not None:
        if transaction.terminal["outcome"] != outcome:
            raise takes.TakeAcceptanceError("TAKE_RECOVERY_CHANGED: canonical no longer matches terminal receipt")
        quarantined = transaction.terminal["artifacts_quarantined"]
        if bool(quarantined) != quarantine.exists() or replacement.exists():
            raise takes.TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: terminal artifact inventory changed")
        result = {key: transaction.terminal[key] for key in takes.RESULT_FIELDS}
    else:
        quarantined = [quarantine.relative_to(project).as_posix()] if replacement.exists() or quarantine.exists() else []
        result = _take_result(transaction, outcome, quarantined)
    # Finish all read-only checks before any recovery mutation.
    takes.require_same(transaction.staged, selected)
    takes.require_same(transaction.canonical, canonical)
    if transaction.marker_proof is None:
        takes.write_record(project / "takes/accept.lock", takes.marker_record(transaction.transaction_id, transaction.intent_proof.sha256))
        transaction = takes.pending_transaction(project, transaction.transaction_id)
    takes.require_owned_marker(transaction)
    if replacement.exists():
        quarantine.parent.mkdir(exist_ok=True)
        if quarantine.exists():
            old, new = takes.file_proof(replacement), takes.file_proof(quarantine)
            if (old.device, old.inode) != (new.device, new.inode):
                raise takes.TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: quarantine already contains another file")
        else:
            os.link(replacement, quarantine)
        if not takes.matches_content(quarantine, intent["staged_sha256"], intent["staged_bytes"]):
            raise takes.TakeAcceptanceError("TAKE_RECOVERY_CHANGED: quarantine copy changed")
        replacement.unlink()
    takes.require_same(transaction.staged, selected)
    takes.require_same(transaction.canonical, canonical)
    takes.require_owned_marker(transaction)
    if transaction.terminal is None:
        _write_take_terminal(transaction, "recovery.json", result)
    takes.retire_marker(transaction)
    return result
