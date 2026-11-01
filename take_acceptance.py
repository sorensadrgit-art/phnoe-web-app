"""Local take-acceptance identities and cooperative per-session fencing.

The persistent OS-lock file is never removed. Historical terminal receipts bind
only their immutable intent; they never authorize later bytes at reused paths.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from runtime_config import is_reparse, startup_lock

ROLES = ("cam01_intrinsics", "cam02_intrinsics", "cam01_board", "cam02_board", "cam01_trial", "cam02_trial")
HEX_ID = re.compile(r"[0-9a-f]{32}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.mp4\Z")
RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}
INTENT_FIELDS = {"schema", "transaction_id", "session_id", "role", "staged_name", "staged_sha256",
                 "staged_bytes", "prior_sha256", "prior_bytes"}
RESULT_FIELDS = {"session_id", "transaction_id", "role", "outcome", "canonical_sha256", "prior_sha256",
                 "archives_retained", "artifacts_quarantined", "native_run_passed", "clinical_validation"}


class TakeAcceptanceError(ValueError):
    """Unknown or changed transaction evidence is preserved and refused."""


@dataclass(frozen=True)
class FileProof:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    sha256: str


@dataclass(frozen=True)
class Transaction:
    project: Path
    directory: Path
    intent: dict
    intent_proof: FileProof
    marker_proof: FileProof | None
    terminal: dict | None
    terminal_name: str | None

    @property
    def transaction_id(self) -> str:
        return self.intent["transaction_id"]

    @property
    def canonical(self) -> Path:
        return self.project / "raw" / (self.intent["role"] + ".mp4")

    @property
    def staged(self) -> Path:
        return self.project / "takes" / self.intent["role"] / self.intent["staged_name"]

    @property
    def archive(self) -> Path:
        return self.project / "takes/archive" / (self.intent["role"] + "-" + self.transaction_id + ".mp4")

    @property
    def replacement(self) -> Path:
        return self.project / "raw" / ("." + self.intent["role"] + "-" + self.transaction_id + ".replacement")


def checked_path(path: Path) -> Path:
    """Check the spelling before resolving so reparse ancestors cannot disappear."""
    path = Path(path).absolute()
    if any(part == ".." or part.endswith((".", " ")) or ":" in part
           or part.split(".")[0].upper() in RESERVED for part in path.parts[1:]):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: aliased or reserved path refused")
    if any(is_reparse(item) for item in (path, *path.parents)):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: linked path refused")
    return path


def local_path(project: Path, *parts: str) -> Path:
    root = Path(project).absolute()
    path = checked_path(root.joinpath(*parts))
    if not path.is_relative_to(root):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: path escapes session")
    return path


def file_proof(path: Path) -> FileProof:
    path = checked_path(path)
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: expected regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        if identity(opened) != identity(before):
            raise TakeAcceptanceError("TAKE_RECOVERY_CHANGED: opened file identity changed")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after_read = os.fstat(stream.fileno())
    after = path.stat(follow_symlinks=False)
    # Windows stat and fstat expose different ctime values after copy2. Compare
    # each source with itself, while binding their common identity across both.
    if (identity(before) != identity(after_read) or identity(before) != identity(after)
            or before.st_ctime_ns != after.st_ctime_ns
            or opened.st_ctime_ns != after_read.st_ctime_ns):
        raise TakeAcceptanceError("TAKE_RECOVERY_CHANGED: file changed while hashing")
    return FileProof(*identity(before), before.st_ctime_ns, digest.hexdigest())


def matches_content(path: Path, digest: str | None, size: int | None) -> bool:
    path = checked_path(path)
    if digest is None:
        return not path.exists()
    if not path.is_file():
        return False
    proof = file_proof(path)
    return proof.sha256 == digest and proof.size == size


def require_same(path: Path, expected: FileProof | None) -> None:
    if expected is None:
        if checked_path(path).exists():
            raise TakeAcceptanceError("TAKE_INPUT_CHANGED: previously absent canonical file exists")
    elif file_proof(path) != expected:
        raise TakeAcceptanceError("TAKE_INPUT_CHANGED: file identity or bytes changed")


def _strict_json(data: bytes) -> dict:
    if len(data) > 65536:
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: oversized transaction record")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError("nonfinite JSON number")
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("nonfinite JSON number")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)
        finite(result)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: invalid transaction JSON") from error
    if not isinstance(result, dict):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: transaction record must be an object")
    return result


def read_record(path: Path) -> tuple[dict, FileProof]:
    path = checked_path(path)
    if path.stat(follow_symlinks=False).st_size > 65536:
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: oversized transaction record")
    before = file_proof(path)
    with path.open("rb") as stream:
        data = stream.read(65537)
    if file_proof(path) != before or hashlib.sha256(data).hexdigest() != before.sha256:
        raise TakeAcceptanceError("TAKE_RECOVERY_CHANGED: transaction record changed")
    return _strict_json(data), before


def write_record(path: Path, record: dict) -> FileProof:
    """An incomplete exclusive write remains visible and fails closed on restart."""
    path = checked_path(path)
    data = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return file_proof(path)


def validate_intent(record: dict, project: Path, transaction_id: str) -> dict:
    if (set(record) != INTENT_FIELDS or record.get("schema") != "kinelab.take-acceptance.v1"
            or not isinstance(transaction_id, str) or not HEX_ID.fullmatch(transaction_id)
            or record.get("transaction_id") != transaction_id or record.get("session_id") != project.name
            or record.get("role") not in ROLES):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: incompatible transaction intent")
    name = record["staged_name"]
    if (not isinstance(name, str) or not SAFE_NAME.fullmatch(name)
            or name.split(".")[0].upper() in RESERVED or Path(name).name != name):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: unsafe staged basename")
    if (not isinstance(record["staged_sha256"], str) or not SHA256.fullmatch(record["staged_sha256"])
            or type(record["staged_bytes"]) is not int or record["staged_bytes"] <= 0):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: invalid selected-file identity")
    prior, size = record["prior_sha256"], record["prior_bytes"]
    if ((prior is None) != (size is None)
            or (prior is not None and (not isinstance(prior, str) or not SHA256.fullmatch(prior)
                                      or type(size) is not int or size < 0))):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: invalid prior-file identity")
    return record


def marker_record(transaction_id: str, intent_sha256: str) -> dict:
    return {"schema": "kinelab.take-acceptance-lock.v1", "transaction_id": transaction_id,
            "intent_sha256": intent_sha256}


def _validate_marker(record: dict) -> None:
    if (set(record) != {"schema", "transaction_id", "intent_sha256"}
            or record.get("schema") != "kinelab.take-acceptance-lock.v1"
            or not isinstance(record.get("transaction_id"), str) or not HEX_ID.fullmatch(record["transaction_id"])
            or not isinstance(record.get("intent_sha256"), str) or not SHA256.fullmatch(record["intent_sha256"])):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: unsupported acceptance marker; never infer PID ownership")


def _validate_terminal(record: dict, intent: dict, intent_digest: str, name: str) -> None:
    expected_schema = "kinelab.take-acceptance-" + ("commit" if name == "commit.json" else "recovery") + ".v1"
    if (set(record) != RESULT_FIELDS | {"schema", "intent_sha256"} or record.get("schema") != expected_schema
            or any(record.get(key) != intent[key] for key in ("session_id", "transaction_id", "role", "prior_sha256"))
            or record.get("intent_sha256") != intent_digest
            or record.get("outcome") not in ("previous-preserved", "selected-verified")
            or record.get("archives_retained") is not True or record.get("native_run_passed") is not False
            or record.get("clinical_validation") != "UNVERIFIED"):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: incompatible terminal receipt")
    expected_digest = intent["staged_sha256"] if record["outcome"] == "selected-verified" else intent["prior_sha256"]
    if record["canonical_sha256"] != expected_digest or (name == "commit.json" and record["outcome"] != "selected-verified"):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: terminal outcome contradicts intent")
    quarantined = record["artifacts_quarantined"]
    expected = "takes/acceptance/" + intent["transaction_id"] + "/quarantine/." + intent["role"] + "-" + intent["transaction_id"] + ".replacement"
    if not isinstance(quarantined, list) or quarantined not in ([], [expected]):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: unsafe terminal quarantine paths")


def _scan(project: Path) -> list[Transaction]:
    project = checked_path(project)
    takes = local_path(project, "takes")
    marker = local_path(project, "takes/accept.lock")
    marker_value, marker_proof = read_record(marker) if marker.exists() else (None, None)
    if marker_value is not None:
        _validate_marker(marker_value)
    records: dict[str, Transaction] = {}
    pending = []
    journal = local_path(project, "takes/acceptance")
    if journal.exists():
        if not journal.is_dir():
            raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: acceptance journal is not a directory")
        for directory in sorted(journal.iterdir()):
            checked_path(directory)
            if not directory.is_dir() or not HEX_ID.fullmatch(directory.name):
                raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: unrecognized acceptance journal entry")
            for path in directory.rglob("*"):
                checked_path(path)
                relative = path.relative_to(directory).as_posix()
                if relative not in {"intent.json", "commit.json", "recovery.json", "accept.lock.archived", "quarantine"} and not relative.startswith("quarantine/"):
                    raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: undeclared transaction artifact")
                if relative != "quarantine" and not path.is_file():
                    raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: transaction artifact is not a regular file")
            intent, proof = read_record(directory / "intent.json")
            validate_intent(intent, project, directory.name)
            replacement_name = "." + intent["role"] + "-" + directory.name + ".replacement"
            quarantine = directory / "quarantine"
            if quarantine.exists() and (not quarantine.is_dir() or any(
                    path.name != replacement_name or not path.is_file() for path in quarantine.iterdir())):
                raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: undeclared quarantine content")
            terminals = [name for name in ("commit.json", "recovery.json") if (directory / name).exists()]
            if len(terminals) > 1:
                raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: contradictory terminal receipts")
            terminal_name = terminals[0] if terminals else None
            terminal = read_record(directory / terminal_name)[0] if terminal_name else None
            if terminal is not None:
                assert terminal_name is not None
                _validate_terminal(terminal, intent, proof.sha256, terminal_name)
            archived = directory / "accept.lock.archived"
            if archived.exists():
                archived_value, _ = read_record(archived)
                if archived_value != marker_record(directory.name, proof.sha256) or terminal is None:
                    raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: unbound retired marker")
            active_marker = marker_value is not None and marker_value["transaction_id"] == directory.name
            if active_marker and marker_value != marker_record(directory.name, proof.sha256):
                raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: marker/intent identity mismatch")
            transaction = Transaction(project, directory, intent, proof, marker_proof if active_marker else None,
                                      terminal, terminal_name)
            records[directory.name] = transaction
            if active_marker or terminal is None:
                pending.append(transaction)
            elif not archived.exists():
                raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: terminal receipt lacks retired-marker proof")
    if marker_value is not None and marker_value["transaction_id"] not in records:
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: marker has no immutable intent")
    raw = local_path(project, "raw")
    if raw.exists():
        for replacement in raw.glob("*.replacement"):
            checked_path(replacement)
            if not any(replacement == item.replacement for item in pending):
                raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: unbound replacement artifact")
    if len(pending) > 1:
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: multiple unfinished acceptance transactions")
    if takes.exists() and not takes.is_dir():
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: takes is not a directory")
    return pending


def inspect_acceptance(project: Path) -> dict:
    """Read-only diagnostic; no OS-lock creation and no PID or age inference."""
    try:
        pending = _scan(project)
        if pending:
            return {"state": "recovery-required", "transaction_id": pending[0].transaction_id,
                    "reason": "Incomplete take acceptance requires explicit operator recovery"}
        return {"state": "clear", "transaction_id": None, "reason": "No unfinished take acceptance"}
    except (OSError, ValueError) as error:
        reason = str(error) if isinstance(error, TakeAcceptanceError) else "TAKE_RECOVERY_UNKNOWN: unreadable acceptance evidence"
        return {"state": "unknown", "transaction_id": None, "reason": reason}


def require_no_pending(project: Path) -> None:
    state = inspect_acceptance(project)
    if state["state"] != "clear":
        raise TakeAcceptanceError("TAKE_RECOVERY_REQUIRED: " + state["reason"])


@contextmanager
def acceptance_lease(project: Path) -> Iterator[BinaryIO]:
    """Yield the actual owning stream; only its exact anchor is read through it."""
    project = checked_path(project)
    directory = local_path(project, "takes/.acceptance-lease")
    try:
        with startup_lock(directory, timeout=0.0) as stream:
            yield stream
    except TimeoutError as error:
        raise TakeAcceptanceError("TAKE_BUSY: another session publication holds the OS lease") from error


def pending_transaction(project: Path, transaction_id: str) -> Transaction:
    if not isinstance(transaction_id, str) or not HEX_ID.fullmatch(transaction_id):
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: transaction ID must be 32 lowercase hex digits")
    try:
        pending = _scan(project)
    except (OSError, ValueError) as error:
        if isinstance(error, TakeAcceptanceError):
            raise
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: incomplete transaction evidence") from error
    if not pending or pending[0].transaction_id != transaction_id:
        raise TakeAcceptanceError("TAKE_RECOVERY_NO_PENDING: exact transaction is not pending")
    return pending[0]


def require_owned_marker(transaction: Transaction) -> None:
    if transaction.marker_proof is None:
        raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: no owned marker was established")
    marker = local_path(transaction.project, "takes/accept.lock")
    value, proof = read_record(marker)
    expected = transaction.marker_proof
    # Creating a retirement hard link can legitimately change ctime/link count.
    if ((proof.device, proof.inode, proof.size, proof.modified_ns, proof.sha256)
            != (expected.device, expected.inode, expected.size, expected.modified_ns, expected.sha256)
            or value != marker_record(transaction.transaction_id, transaction.intent_proof.sha256)):
        raise TakeAcceptanceError("TAKE_TRANSACTION_CHANGED: acceptance marker owner changed; preserved")
    require_same(transaction.directory / "intent.json", transaction.intent_proof)


def retire_marker(transaction: Transaction) -> None:
    require_owned_marker(transaction)
    marker = transaction.project / "takes/accept.lock"
    archived = transaction.directory / "accept.lock.archived"
    if archived.exists():
        value, proof = read_record(archived)
        expected = transaction.marker_proof
        if (expected is None or (proof.device, proof.inode) != (expected.device, expected.inode)
                or value != marker_record(transaction.transaction_id, transaction.intent_proof.sha256)):
            raise TakeAcceptanceError("TAKE_RECOVERY_UNKNOWN: retirement path has unknown bytes")
    else:
        os.link(marker, archived)
    require_owned_marker(transaction)
    marker.unlink()
