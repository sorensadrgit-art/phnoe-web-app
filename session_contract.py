"""Local capture identity and runtime validation shared by pipeline stages."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

ROLES = ("cam01_intrinsics", "cam02_intrinsics", "cam01_board", "cam02_board", "cam01_trial", "cam02_trial")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_session(data: object, project: Path) -> dict:
    def invalid(message):
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
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("SESSION_INVALID: duplicate JSON key " + key)
            result[key] = value
        return result

    path = Path(project) / "session.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    except FileNotFoundError as error:
        raise ValueError("INPUT_MISSING: session.json; register all six raw captures first") from error
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("SESSION_INVALID: unreadable session.json") from error
    return validate_session(data, project)
