"""Local capture identity and runtime validation shared by pipeline stages."""
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import NoReturn

ROLES = ("cam01_intrinsics", "cam02_intrinsics", "cam01_board", "cam02_board", "cam01_trial", "cam02_trial")


def strict_json_loads(value):
    """Reject ambiguous JSON and non-finite values, including exponent overflow."""
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("JSON_INVALID: duplicate key " + key)
            result[key] = item
        return result

    def constant(value):
        raise ValueError("JSON_INVALID: nonfinite number " + value)

    def finite(item):
        if isinstance(item, float):
            return None if math.isfinite(item) else ""
        if isinstance(item, dict):
            for key, child in item.items():
                suffix = finite(child)
                if suffix is not None:
                    return "." + key + suffix
        elif isinstance(item, list):
            for index, child in enumerate(item):
                suffix = finite(child)
                if suffix is not None:
                    return f"[{index}]" + suffix

    result = json.loads(value, object_pairs_hook=unique, parse_constant=constant)
    suffix = finite(result)
    if suffix is not None:
        raise ValueError("JSON_INVALID: nonfinite number at $" + suffix)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_session_metadata(metadata: object) -> dict:
    """Validate explicit set confirmation; opaque IDs are not identity/authentication proof."""
    fields = {"schema", "subject_id", "operator_id", "task_id", "protocol_id",
              "protocol_version", "laterality", "confirmed", "confirmed_at"}
    def invalid(message: str) -> NoReturn:
        raise ValueError("SESSION_METADATA_INVALID: " + message)
    if not isinstance(metadata, dict) or set(metadata) != fields:
        invalid("expected exactly the versioned confirmation fields")
    if metadata["schema"] != "kinelab.session-metadata.v1":
        invalid("unsupported schema")
    for key, prefix in (("subject_id", "sub-"), ("operator_id", "op-")):
        if not isinstance(metadata[key], str) or not re.fullmatch(prefix + r"[0-9a-f]{32}", metadata[key]):
            invalid(key + " must be an explicitly supplied opaque identifier")
    for key in ("task_id", "protocol_id", "protocol_version"):
        if not isinstance(metadata[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", metadata[key]):
            invalid(key + " must be a bounded identifier")
    if metadata["laterality"] not in ("left", "right", "bilateral", "not_applicable"):
        invalid("explicit laterality required")
    if metadata["confirmed"] is not True:
        invalid("explicit confirmation required")
    try:
        confirmed = datetime.fromisoformat(metadata["confirmed_at"])
        if confirmed.utcoffset() is None:
            invalid("confirmed_at requires a timezone")
    except (TypeError, ValueError):
        invalid("confirmed_at must be an ISO timestamp with timezone")
    return metadata


def validate_session(data: object, project: Path) -> dict:
    # Read-only fence: callers may already hold the one shared publication lease.
    from take_acceptance import require_no_pending

    require_no_pending(project)
    def invalid(message: str) -> NoReturn:
        raise ValueError("SESSION_INVALID: " + message)

    if not isinstance(data, dict) or data.get("schema") != "kinelab.session.v1":
        invalid("expected kinelab.session.v1")
    if not isinstance(data.get("session_id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", data["session_id"]):
        invalid("session_id must be a safe local name")
    if data.get("kind") not in ("real", "demo") or type(data.get("subject_count")) is not int or data["subject_count"] != 1:
        invalid("expected real/demo kind and one subject")
    if data.get("camera_ids") != ["cam01", "cam02"]:
        invalid("camera_ids must be cam01 and cam02 in that order")
    try:
        created = datetime.fromisoformat(data["created_at"])
        if created.utcoffset() is None:
            invalid("created_at requires a timezone")
    except (KeyError, TypeError, ValueError):
        invalid("created_at must be an ISO timestamp with timezone")
    captures = data.get("captures")
    if not isinstance(captures, dict) or set(captures) != set(ROLES):
        invalid("provide exactly the six camera capture roles")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        invalid("metadata must be an object")
    # Historical metadata remains readable, but cannot authorize comparison.
    if "schema" in data.get("metadata", {}):
        validate_session_metadata(data["metadata"])
    root = Path(project).resolve()
    seen = set()
    for role in ROLES:
        entry = captures[role]
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
            invalid("missing capture path for " + role)
        relative = Path(entry["path"])
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            invalid("capture paths must stay inside the session")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path in seen:
            invalid("capture paths must be distinct files inside the session")
        seen.add(path)
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            invalid("invalid SHA-256 for " + role)
        if not path.is_file():
            raise ValueError("INPUT_MISSING: " + role + ": " + str(relative))
        if sha256_file(path) != checksum:
            raise ValueError("INPUT_CHANGED: " + role)
    return data


def load_session(project: Path) -> dict:
    path = Path(project) / "session.json"
    try:
        data = strict_json_loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError("INPUT_MISSING: session.json; register all six raw captures first") from error
    except (ValueError, UnicodeError) as error:
        raise ValueError("SESSION_INVALID: " + str(error)) from error
    return validate_session(data, project)
