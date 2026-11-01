"""Registered-session metadata corrections; audit commits are the only authority.

This local software provenance contract does not authenticate an operator, validate
an assessment, or change original recording/session bytes. Drafts use their existing
initial setup path. Callers must use the returned context for subsequent work.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn
from uuid import uuid4

import take_acceptance as takes
from session_contract import ROLES, strict_json_loads, validate_session_metadata

if TYPE_CHECKING:
    from session_index import SessionIndex

JSON_LIMIT = 64 * 1024
REVISION_LIMIT = 512
EVENT = "METADATA_REVISION_PUBLISHED"
HEX_ID = re.compile(r"[0-9a-f]{32}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
STATE_SCHEMA = "kinelab.session-metadata-state.v1"
DESCRIPTOR_SCHEMA = "kinelab.session-metadata-revision.v1"
RECEIPT_SCHEMA = "kinelab.session-metadata-revision-receipt.v1"
INTENT_SCHEMA = "kinelab.session-metadata-revision-intent.v1"


class MetadataRevisionError(ValueError):
    """Evidence is unavailable, changed, malformed, or awaiting recovery."""


def _fail(reason: str) -> NoReturn:
    raise MetadataRevisionError(reason)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hex(value: object, pattern: re.Pattern, label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail("METADATA_INVALID: " + label)
    return value


def _timestamp(value: object) -> None:
    if not isinstance(value, str):
        _fail("METADATA_INVALID: timestamp requires text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MetadataRevisionError("METADATA_INVALID: timestamp") from error
    if parsed.utcoffset() is None:
        _fail("METADATA_INVALID: timestamp requires timezone")


def _metadata(value: object) -> dict:
    try:
        validate_session_metadata(value)
    except ValueError as error:
        raise MetadataRevisionError("METADATA_UNAVAILABLE: " + str(error)) from error
    # Detach the request from mutable caller-owned objects before acquiring a lease.
    raw = _canonical(value)
    if len(raw) > JSON_LIMIT:
        _fail("METADATA_INVALID: metadata exceeds JSON size limit")
    return strict_json_loads(raw.decode("ascii"))


def _project(index: SessionIndex, session_id: str) -> Path:
    _hex(session_id, SESSION_ID, "session identifier")
    parent = takes.checked_path(index.projects_root)
    project = takes.local_path(parent, session_id)
    if not project.is_dir():
        _fail("METADATA_REGISTERED_SESSION_REQUIRED: session directory missing")
    return project


def _identity(item: os.stat_result) -> tuple:
    # Match the house path/descriptor rule. Windows ctime precision can differ
    # across interfaces, so ctime is compared only within the same interface.
    return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_mode)


def _read_file(path: Path, *, limit: int, expected_size: int | None = None,
               collect: bool = True) -> tuple[bytes, str]:
    checked = takes.checked_path(path)
    before = checked.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        _fail("METADATA_SOURCE_INVALID: regular file required")
    if before.st_size > limit:
        _fail("METADATA_SOURCE_TOO_LARGE: size exceeds bounded read limit")
    if expected_size is not None and before.st_size != expected_size:
        _fail("METADATA_SOURCE_CHANGED: indexed byte count differs")
    digest = hashlib.sha256()
    parts: list[bytes] = []
    remaining = before.st_size
    with checked.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(opened) != _identity(before):
            _fail("METADATA_SOURCE_CHANGED: opened file differs")
        while remaining:
            block = stream.read(min(64 * 1024, remaining))
            if not block:
                _fail("METADATA_SOURCE_CHANGED: truncated during read")
            remaining -= len(block)
            digest.update(block)
            if collect:
                parts.append(block)
        if stream.read(1):
            _fail("METADATA_SOURCE_CHANGED: grew during bounded read")
        after_read = os.fstat(stream.fileno())
    after = takes.checked_path(path).stat(follow_symlinks=False)
    if (_identity(before) != _identity(after_read)
            or _identity(before) != _identity(after)
            or before.st_ctime_ns != after.st_ctime_ns
            or opened.st_ctime_ns != after_read.st_ctime_ns):
        _fail("METADATA_SOURCE_CHANGED: unstable file identity")
    return b"".join(parts), digest.hexdigest()


def _document(path: Path) -> tuple[dict, str]:
    raw, digest = _read_file(path, limit=JSON_LIMIT)
    try:
        value = strict_json_loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise MetadataRevisionError("METADATA_INVALID: ambiguous or invalid JSON") from error
    if not isinstance(value, dict):
        _fail("METADATA_INVALID: JSON object required")
    return value, digest


def _keys(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("METADATA_INVALID: exact " + label + " fields required")
    return value


def _baseline(index: SessionIndex, session_id: str, project: Path) -> tuple[dict, dict]:
    origin_path = takes.local_path(project, "session.json")
    if not origin_path.exists():
        _fail("METADATA_REGISTERED_SESSION_REQUIRED: drafts cannot publish revisions")
    takes.require_no_pending(project)
    row = index.conn.execute(
        "SELECT sha256, bytes, filename FROM artifacts WHERE session_id=? AND artifact_key='session.json'",
        (session_id,),
    ).fetchone()
    if row is None:
        _fail("METADATA_UNAVAILABLE: immutable indexed origin baseline missing")
    expected = _hex(row["sha256"], SHA256, "indexed origin digest")
    size = row["bytes"]
    if type(size) is not int or size < 1 or size > JSON_LIMIT or row["filename"] != "session.json":
        _fail("METADATA_UNAVAILABLE: indexed origin size limit or identity invalid")
    raw, actual = _read_file(origin_path, limit=JSON_LIMIT, expected_size=size)
    if actual != expected:
        _fail("METADATA_SOURCE_CHANGED: immutable indexed origin differs")
    try:
        document = strict_json_loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise MetadataRevisionError("METADATA_UNAVAILABLE: registered origin JSON invalid") from error
    if (not isinstance(document, dict) or document.get("schema") != "kinelab.session.v1"
            or document.get("session_id") != session_id or document.get("kind") not in ("real", "demo")
            or type(document.get("subject_count")) is not int or document.get("subject_count") != 1
            or document.get("camera_ids") != ["cam01", "cam02"]):
        _fail("METADATA_UNAVAILABLE: registered session identity or contract invalid")
    _timestamp(document.get("created_at"))
    initial = _metadata(document.get("metadata"))
    indexed = index.conn.execute("SELECT kind FROM sessions WHERE id=?", (session_id,)).fetchone()
    if indexed is None or indexed["kind"] != document["kind"]:
        _fail("METADATA_UNAVAILABLE: indexed session identity differs")
    captures = document.get("captures")
    if not isinstance(captures, dict) or set(captures) != set(ROLES):
        _fail("METADATA_UNAVAILABLE: six registered captures required")
    sources = {row["role"]: dict(row) for row in index.conn.execute(
        "SELECT role,filename,sha256,bytes FROM sources WHERE session_id=?", (session_id,))}
    if set(sources) != set(ROLES):
        _fail("METADATA_UNAVAILABLE: immutable indexed capture baselines missing")
    bindings = {}
    for role in ROLES:
        entry = captures[role]
        if (not isinstance(entry, dict) or entry.get("path") != "raw/" + role + ".mp4"):
            _fail("METADATA_UNAVAILABLE: registered capture path differs")
        source = sources[role]
        checksum = _hex(source["sha256"], SHA256, "indexed capture digest")
        count = source["bytes"]
        if (source["filename"] != role + ".mp4" or type(count) is not int or count < 1
                or entry.get("sha256") != checksum):
            _fail("METADATA_UNAVAILABLE: indexed and registered capture binding differs")
        _, observed = _read_file(takes.local_path(project, "raw", role + ".mp4"),
                                 limit=count, expected_size=count, collect=False)
        if observed != checksum:
            _fail("METADATA_SOURCE_CHANGED: immutable indexed capture differs")
        bindings[role] = {"path": entry["path"], "sha256": checksum, "bytes": count}
    # A second bounded origin read catches edits during the capture verification.
    if _read_file(origin_path, limit=JSON_LIMIT, expected_size=size)[1] != expected:
        _fail("METADATA_SOURCE_CHANGED: origin changed during verification")
    takes.require_no_pending(project)
    return initial, {"origin": {"path": "session.json", "sha256": expected},
                     "origin_bytes": size, "captures": bindings}


def _context(session_id: str, origin: dict, head: dict | None) -> str:
    return _digest({"schema": "kinelab.session-metadata-context.v1", "session_id": session_id,
                    "origin": origin, "head": head})


def _reference(value: object) -> dict:
    reference = _keys(value, {"path", "sha256"}, "descriptor reference")
    if (not isinstance(reference["path"], str) or
            re.fullmatch(r"metadata-revisions/revision-[0-9a-f]{32}/revision\.json", reference["path"]) is None):
        _fail("METADATA_INVALID: descriptor path")
    _hex(reference["sha256"], SHA256, "descriptor digest")
    return reference


def _verify_audit(index: SessionIndex) -> None:
    try:
        index.verify_audit()
    except ValueError as error:
        raise MetadataRevisionError("METADATA_UNAVAILABLE: " + str(error)) from error


def _chain(index: SessionIndex, session_id: str, project: Path, initial: dict,
           baseline: dict) -> tuple[dict | None, dict, dict[str, tuple[dict, dict]]]:
    _verify_audit(index)
    rows = index.conn.execute(
        "SELECT details_json FROM audit_events WHERE session_id=? AND event_type=? ORDER BY id LIMIT ?",
        (session_id, EVENT, REVISION_LIMIT + 1),
    ).fetchall()
    if len(rows) > REVISION_LIMIT:
        _fail("METADATA_UNAVAILABLE: revision verification limit exceeded")
    head = None
    effective = initial
    operations: dict[str, tuple[dict, dict]] = {}
    for row in rows:
        try:
            details = strict_json_loads(row["details_json"])
        except ValueError as error:
            raise MetadataRevisionError("METADATA_UNAVAILABLE: audit details invalid") from error
        _keys(details, {"operation_id", "descriptor", "receipt"}, "publication audit")
        operation = _hex(details["operation_id"], HEX_ID, "audit operation")
        if operation in operations:
            _fail("METADATA_UNAVAILABLE: duplicate publication operation")
        reference = _reference(details["descriptor"])
        descriptor, actual = _document(takes.local_path(project, reference["path"]))
        if actual != reference["sha256"]:
            _fail("METADATA_UNAVAILABLE: published descriptor changed")
        _keys(descriptor, {"schema", "session_id", "operation_id", "revision_id", "metadata",
                           "initial_metadata", "origin", "baseline", "previous", "reason_code",
                           "created_at"}, "revision descriptor")
        revision_id = _hex(descriptor["revision_id"], HEX_ID, "revision identifier")
        if (descriptor["schema"] != DESCRIPTOR_SCHEMA or descriptor["session_id"] != session_id
                or descriptor["operation_id"] != operation
                or reference["path"] != f"metadata-revisions/revision-{revision_id}/revision.json"
                or descriptor["initial_metadata"] != initial or descriptor["origin"] != baseline["origin"]
                or descriptor["baseline"] != baseline or descriptor["previous"] != head
                or descriptor["reason_code"] != "operator_correction"):
            _fail("METADATA_UNAVAILABLE: descriptor chain or immutable baseline differs")
        _timestamp(descriptor["created_at"])
        effective = _metadata(descriptor["metadata"])
        receipt = {"schema": RECEIPT_SCHEMA, "session_id": session_id, "operation_id": operation,
                   "revision_id": revision_id, "descriptor": reference,
                   "context_sha256": _context(session_id, baseline["origin"], reference)}
        if details["receipt"] != receipt:
            _fail("METADATA_UNAVAILABLE: audited receipt differs")
        operations[operation] = (descriptor, receipt)
        head = reference
    return head, effective, operations


def _pending(project: Path, operations: dict[str, tuple[dict, dict]]) -> list[Path]:
    directory = takes.local_path(project, "metadata-revisions")
    if not directory.exists():
        return []
    if not directory.is_dir():
        _fail("METADATA_UNAVAILABLE: revision directory invalid")
    pending = []
    # The directory consists of additive evidence; never promote unaudited files.
    with os.scandir(directory) as entries:
        for number, entry in enumerate(entries):
            if number >= 4 * REVISION_LIMIT:
                _fail("METADATA_UNAVAILABLE: revision directory entry limit exceeded")
            path = takes.local_path(directory, entry.name)
            if entry.name.startswith("pending-"):
                if re.fullmatch(r"pending-[0-9a-f]{32}\.json", entry.name) is None:
                    _fail("METADATA_UNAVAILABLE: unknown pending revision intent")
                pending.append(path)
            elif entry.name.startswith("resolved-"):
                match = re.fullmatch(r"resolved-([0-9a-f]{32})-(committed|aborted)\.json", entry.name)
                if match is None:
                    _fail("METADATA_UNAVAILABLE: unknown terminal revision intent")
                terminal, _ = _document(path)
                _keys(terminal, {"schema", "session_id", "operation_id", "descriptor", "receipt"},
                      "terminal intent")
                operation, outcome = match.groups()
                if (terminal["schema"] != INTENT_SCHEMA or terminal["session_id"] != project.name
                        or terminal["operation_id"] != operation):
                    _fail("METADATA_UNAVAILABLE: terminal intent identity differs")
                if outcome == "committed":
                    if operations.get(operation) != (terminal["descriptor"], terminal["receipt"]):
                        _fail("METADATA_UNAVAILABLE: retained commit witness differs from audit")
                elif operation in operations:
                    _fail("METADATA_UNAVAILABLE: aborted operation unexpectedly has a commit")
    if len(pending) > 1:
        _fail("METADATA_UNAVAILABLE: multiple pending revision intents")
    return pending


def _resolved(index: SessionIndex, session_id: str, project: Path, *, allow_pending: bool = False):
    initial, baseline = _baseline(index, session_id, project)
    head, effective, operations = _chain(index, session_id, project, initial, baseline)
    pending = _pending(project, operations)
    if pending and not allow_pending:
        _fail("METADATA_UNAVAILABLE: pending revision requires explicit recovery")
    state = {"schema": STATE_SCHEMA, "session_id": session_id, "status": "AVAILABLE",
             "metadata": effective, "initial_metadata": initial, "origin": baseline["origin"],
             "head": head, "context_sha256": _context(session_id, baseline["origin"], head),
             "reason": "Verified immutable origin and audited revision chain"}
    return state, baseline, operations, pending


def _unavailable(session_id: str, error: Exception) -> dict:
    return {"schema": STATE_SCHEMA, "session_id": session_id, "status": "UNAVAILABLE",
            "metadata": None, "initial_metadata": None, "origin": None, "head": None,
            "context_sha256": None, "reason": str(error)}


def read_metadata_state(index: SessionIndex, session_id: str) -> dict:
    """Read only; registered immutable baselines and verified audit are mandatory."""
    try:
        project = _project(index, session_id)
        with index.read_snapshot():
            return _resolved(index, session_id, project)[0]
    except (MetadataRevisionError, takes.TakeAcceptanceError, OSError, sqlite3.DatabaseError) as error:
        return _unavailable(session_id, error)


def _verify_new(path: Path, raw: bytes, created: os.stat_result) -> None:
    """Bind newly created evidence to its original ordinary identity and bytes."""
    before = takes.checked_path(path).stat(follow_symlinks=False)
    if (_identity(before) != _identity(created)
            or before.st_ctime_ns != created.st_ctime_ns):
        _fail("METADATA_SOURCE_CHANGED: publication identity differs")
    observed, digest = _read_file(path, limit=JSON_LIMIT, expected_size=len(raw))
    after = takes.checked_path(path).stat(follow_symlinks=False)
    if (observed != raw or digest != hashlib.sha256(raw).hexdigest()
            or _identity(after) != _identity(created)
            or after.st_ctime_ns != created.st_ctime_ns):
        _fail("METADATA_SOURCE_CHANGED: publication bytes or identity differ")


def _write_new(path: Path, raw: bytes) -> os.stat_result:
    if len(raw) > JSON_LIMIT:
        _fail("METADATA_INVALID: publication exceeds JSON size limit")
    checked = takes.checked_path(path)
    with checked.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
        opened = os.fstat(stream.fileno())
    created = takes.checked_path(checked).stat(follow_symlinks=False)
    if _identity(created) != _identity(opened):
        _fail("METADATA_SOURCE_CHANGED: created publication identity differs")
    _verify_new(checked, raw, created)
    return created


def _checkpoint(phase: str, *context: object) -> None:
    """Fault-injection seam; no physical process/power-loss proof is implied."""


def _retire(project: Path, intent_path: Path, operation_id: str, outcome: str) -> None:
    target = takes.local_path(project, "metadata-revisions", f"resolved-{operation_id}-{outcome}.json")
    if target.exists():
        _fail("METADATA_UNAVAILABLE: recovery destination already exists")
    # Windows rename refuses an existing target; both names are in the same
    # checked directory. Retain every intent/candidate byte, including aborts.
    os.rename(takes.checked_path(intent_path), target)


def publish_metadata_revision(index: SessionIndex, session_id: str, *, metadata: dict,
                              expected_origin_sha256: str, expected_head_sha256: str | None,
                              operation_id: str, reason_code: str, confirm: bool) -> dict:
    """Publish one additive revision under the existing session OS lease.

    An exact committed retry returns its original receipt before comparing the
    now-stale expected head. Any changed request for that operation is refused.
    """
    if confirm is not True:
        _fail("METADATA_CONFIRMATION_REQUIRED: explicit confirmation required")
    replacement = _metadata(metadata)
    _hex(expected_origin_sha256, SHA256, "expected origin")
    if expected_head_sha256 is not None:
        _hex(expected_head_sha256, SHA256, "expected head")
    _hex(operation_id, HEX_ID, "operation identifier")
    if reason_code != "operator_correction":
        _fail("METADATA_INVALID: supported correction reason required")
    project = _project(index, session_id)
    if not takes.local_path(project, "session.json").exists():
        _fail("METADATA_REGISTERED_SESSION_REQUIRED: drafts cannot publish revisions")
    with takes.acceptance_lease(project):
        with index.transaction():
            state, baseline, operations, _ = _resolved(index, session_id, project)
            if operation_id in operations:
                old, receipt = operations[operation_id]
                old_head = old["previous"]["sha256"] if old["previous"] else None
                if (replacement != old["metadata"] or expected_origin_sha256 != old["origin"]["sha256"]
                        or expected_head_sha256 != old_head or reason_code != old["reason_code"]):
                    _fail("METADATA_OPERATION_CONFLICT: operation request differs")
                return receipt
            if len(operations) >= REVISION_LIMIT:
                _fail("METADATA_UNAVAILABLE: revision publication limit exceeded")
            current_head = state["head"]["sha256"] if state["head"] else None
            if expected_origin_sha256 != state["origin"]["sha256"] or expected_head_sha256 != current_head:
                _fail("METADATA_CONTEXT_CHANGED: expected origin or head differs")
            if takes.local_path(project, "metadata-revisions", f"resolved-{operation_id}-aborted.json").exists():
                _fail("METADATA_OPERATION_CONFLICT: recovered aborted operation requires a new identifier")
            directory = takes.local_path(project, "metadata-revisions")
            if directory.exists():
                with os.scandir(directory) as entries:
                    for number, _entry in enumerate(entries):
                        # Intent plus candidate directory must both fit; terminal
                        # retirement renames the intent without adding an entry.
                        if number >= 4 * REVISION_LIMIT - 2:
                            _fail("METADATA_UNAVAILABLE: revision directory publication limit exceeded")
            revision_id = uuid4().hex
            descriptor = {"schema": DESCRIPTOR_SCHEMA, "session_id": session_id,
                          "operation_id": operation_id, "revision_id": revision_id,
                          "metadata": replacement, "initial_metadata": state["initial_metadata"],
                          "origin": state["origin"], "baseline": baseline, "previous": state["head"],
                          "reason_code": reason_code, "created_at": datetime.now(UTC).isoformat()}
            raw = _canonical(descriptor)
            reference = {"path": f"metadata-revisions/revision-{revision_id}/revision.json",
                         "sha256": hashlib.sha256(raw).hexdigest()}
            receipt = {"schema": RECEIPT_SCHEMA, "session_id": session_id, "operation_id": operation_id,
                       "revision_id": revision_id, "descriptor": reference,
                       "context_sha256": _context(session_id, state["origin"], reference)}
            intent = {"schema": INTENT_SCHEMA, "session_id": session_id, "operation_id": operation_id,
                      "descriptor": descriptor, "receipt": receipt}
            directory.mkdir(exist_ok=True)
            intent_path = takes.local_path(directory, f"pending-{operation_id}.json")
            intent_raw = _canonical(intent)
            intent_identity = _write_new(intent_path, intent_raw)
            _checkpoint("after_intent_fsync", intent_path)
            candidate = takes.local_path(directory, "revision-" + revision_id)
            candidate.mkdir()
            candidate_path = takes.local_path(candidate, "revision.json")
            candidate_identity = _write_new(candidate_path, raw)
            _checkpoint("after_descriptor_publish", reference)
            # No index refresh/reindex: verify against the immutable original
            # baselines again before committing the sole authority.
            checked, checked_baseline, _, _ = _resolved(index, session_id, project, allow_pending=True)
            if checked["context_sha256"] != state["context_sha256"] or checked_baseline != baseline:
                _fail("METADATA_CONTEXT_CHANGED: evidence changed before commit")
            _verify_new(intent_path, intent_raw, intent_identity)
            _verify_new(candidate_path, raw, candidate_identity)
            index._append_audit(session_id, EVENT, {"operation_id": operation_id,
                                                 "descriptor": reference, "receipt": receipt})
            _checkpoint("before_audit_commit", receipt)
            _verify_new(intent_path, intent_raw, intent_identity)
            _verify_new(candidate_path, raw, candidate_identity)
        _checkpoint("after_audit_commit", receipt)
        # Re-read the committed chain before retiring its crash fence.
        with index.read_snapshot():
            _, _, committed, pending = _resolved(index, session_id, project, allow_pending=True)
            if committed.get(operation_id, (None, None))[1] != receipt or pending != [intent_path]:
                _fail("METADATA_UNAVAILABLE: committed publication requires recovery")
            _verify_new(intent_path, intent_raw, intent_identity)
            _verify_new(candidate_path, raw, candidate_identity)
        _retire(project, intent_path, operation_id, "committed")
        return receipt


def recover_metadata_revision(index: SessionIndex, session_id: str) -> dict:
    """Retire only a fully understood intent; never promote an unaudited file."""
    try:
        project = _project(index, session_id)
        with takes.acceptance_lease(project), index.transaction():
            state, baseline, operations, pending = _resolved(index, session_id, project, allow_pending=True)
            if not pending:
                return state
            path = pending[0]
            intent, _ = _document(path)
            _keys(intent, {"schema", "session_id", "operation_id", "descriptor", "receipt"}, "intent")
            operation = _hex(intent["operation_id"], HEX_ID, "intent operation")
            descriptor = intent["descriptor"]
            receipt = intent["receipt"]
            if (intent["schema"] != INTENT_SCHEMA or intent["session_id"] != session_id
                    or path.name != f"pending-{operation}.json" or not isinstance(descriptor, dict)
                    or not isinstance(receipt, dict)):
                _fail("METADATA_UNAVAILABLE: unknown revision intent")
            _keys(descriptor, {"schema", "session_id", "operation_id", "revision_id", "metadata",
                               "initial_metadata", "origin", "baseline", "previous", "reason_code",
                               "created_at"}, "intent descriptor")
            revision_id = _hex(descriptor["revision_id"], HEX_ID, "intent revision")
            _metadata(descriptor["metadata"])
            _timestamp(descriptor["created_at"])
            reference = {"path": f"metadata-revisions/revision-{revision_id}/revision.json",
                         "sha256": _digest(descriptor)}
            expected_receipt = {"schema": RECEIPT_SCHEMA, "session_id": session_id,
                                "operation_id": operation, "revision_id": revision_id,
                                "descriptor": reference,
                                "context_sha256": _context(session_id, baseline["origin"], reference)}
            if (descriptor["schema"] != DESCRIPTOR_SCHEMA or descriptor["session_id"] != session_id
                    or descriptor["operation_id"] != operation or descriptor["baseline"] != baseline
                    or descriptor["origin"] != baseline["origin"]
                    or descriptor["initial_metadata"] != state["initial_metadata"]
                    or descriptor["reason_code"] != "operator_correction" or receipt != expected_receipt):
                _fail("METADATA_UNAVAILABLE: intent does not bind immutable current evidence")
            candidate = takes.local_path(project, reference["path"])
            if candidate.exists() and _document(candidate)[1] != reference["sha256"]:
                _fail("METADATA_UNAVAILABLE: pending candidate changed")
            if operation in operations:
                if operations[operation] != (descriptor, receipt):
                    _fail("METADATA_UNAVAILABLE: committed intent differs from audit")
                outcome = "committed"
            else:
                if descriptor["previous"] != state["head"]:
                    _fail("METADATA_UNAVAILABLE: uncommitted intent has unknown previous head")
                outcome = "aborted"
            _retire(project, path, operation, outcome)
            return _resolved(index, session_id, project)[0]
    except (MetadataRevisionError, takes.TakeAcceptanceError, OSError, sqlite3.DatabaseError) as error:
        return _unavailable(session_id, error)
