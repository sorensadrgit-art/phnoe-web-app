"""Bounded cache invalidation observations, never native or clinical verification."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

import take_acceptance as takes
from export_motion import bound_path, validate_motion
from pipeline_quality import FRAME_DIAGNOSTICS_SCHEMA, _validate_frame_document
from run_pipeline import OUTPUTS, STAGES
from session_contract import ROLES, strict_json_loads, validate_session_metadata

SCHEMA = "kinelab.comparison-source-observation.v1"
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 64
MAX_ARTIFACTS = 256
MAX_DIRECTORY_ENTRIES = 512
ALLOWED_SUFFIXES = {".json", ".toml", ".trc", ".mot", ".osim", ".xml", ".sto", ".txt"}


class ObservationError(ValueError):
    pass


def _identity(value: os.stat_result) -> tuple:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _manifest(raw: bytes, project: Path) -> dict:
    """Check cache identity without repeating the caller's full capture hashing."""
    session = strict_json_loads(raw.decode("utf-8-sig"))
    if (not isinstance(session, dict) or session.get("schema") != "kinelab.session.v1"
            or session.get("session_id") != project.name or session.get("kind") not in ("real", "demo")
            or type(session.get("subject_count")) is not int or session["subject_count"] != 1
            or session.get("camera_ids") != ["cam01", "cam02"]):
        raise ObservationError("SOURCE_INVALID: unsupported session identity")
    if datetime.fromisoformat(session["created_at"]).utcoffset() is None:
        raise ObservationError("SOURCE_INVALID: session timestamp requires timezone")
    validate_session_metadata(session.get("metadata"))
    captures = session.get("captures")
    if not isinstance(captures, dict) or set(captures) != set(ROLES):
        raise ObservationError("SOURCE_INVALID: unsupported capture declarations")
    paths = set()
    for entry in captures.values():
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or not isinstance(entry.get("sha256"), str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])):
            raise ObservationError("SOURCE_INVALID: malformed capture declaration")
        path = takes.local_path(project, entry["path"])
        if path in paths or not path.is_file():
            raise ObservationError("SOURCE_INVALID: duplicate or missing capture path")
        paths.add(path)
    return session


def _read_source(project: Path, relative: str, budget: list[int]) -> tuple[bytes, os.stat_result]:
    spelling = takes.local_path(project, relative)
    before = spelling.stat(follow_symlinks=False)
    path = bound_path(project, relative)
    if path != spelling or path.suffix.casefold() not in ALLOWED_SUFFIXES or relative.split("/")[0].casefold() in {
        "raw", "videos", "videos_raw", "takes",
    }:
        raise ObservationError("SOURCE_INVALID: unsupported native artifact path")
    if not stat.S_ISREG(before.st_mode):
        raise ObservationError("SOURCE_INVALID: regular source required")
    if before.st_size > MAX_FILE_BYTES or budget[0] + before.st_size > MAX_TOTAL_BYTES:
        raise ObservationError("LIMIT: bounded source bytes exceeded")
    with spelling.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - budget[0]) + 1)
        closed = os.fstat(stream.fileno())
    after = takes.checked_path(spelling).stat(follow_symlinks=False)
    if (len(data) > MAX_FILE_BYTES or budget[0] + len(data) > MAX_TOTAL_BYTES):
        raise ObservationError("LIMIT: growing source exceeded byte limit")
    if (_identity(before) != _identity(opened) or _identity(opened) != _identity(closed)
            or _identity(before) != _identity(after) or before.st_ctime_ns != after.st_ctime_ns
            or opened.st_ctime_ns != closed.st_ctime_ns or len(data) != before.st_size):
        raise ObservationError("CHANGED: native source changed while read")
    budget[0] += len(data)
    return data, after


def _candidates(project: Path) -> list[str]:
    directory = takes.local_path(project, "exports")
    before = directory.stat(follow_symlinks=False)
    names = []
    # Bound the directory scan as well as matching candidates.
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_CANDIDATES:
                raise ObservationError("LIMIT: export directory entries exceeded")
            match = entry.name.casefold().endswith(".motion.json") if os.name == "nt" else entry.name.endswith(".motion.json")
            if match:
                takes.checked_path(Path(entry.path))
                names.append("exports/" + entry.name)
    after = takes.checked_path(directory).stat(follow_symlinks=False)
    if _identity(before) != _identity(after) or before.st_ctime_ns != after.st_ctime_ns:
        raise ObservationError("CHANGED: export candidate inventory changed")
    if len(names) != 1:
        raise ObservationError("AMBIGUOUS: exactly one native motion candidate required")
    return sorted(names)


def _native_candidates(project: Path) -> tuple[dict[str, list[str]], dict[Path, os.stat_result]]:
    """Bound traversal before matching the producer's existing output patterns."""
    roots: dict[str, bool] = {}
    for patterns in OUTPUTS.values():
        for pattern in patterns:
            root = pattern.split("/", 1)[0]
            roots[root] = roots.get(root, False) or "**" in pattern
    paths, directories, count = [], {}, 0
    for root, recursive in sorted(roots.items()):
        pending = [takes.local_path(project, root)]
        while pending:
            directory = takes.checked_path(pending.pop())
            before = directory.stat(follow_symlinks=False)
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > MAX_DIRECTORY_ENTRIES:
                        raise ObservationError("LIMIT: native directory entries exceeded")
                    path = takes.checked_path(Path(entry.path))
                    if entry.is_dir(follow_symlinks=False) and recursive:
                        pending.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        paths.append(path.relative_to(project).as_posix())
            after = takes.checked_path(directory).stat(follow_symlinks=False)
            if _identity(before) != _identity(after) or before.st_ctime_ns != after.st_ctime_ns:
                raise ObservationError("CHANGED: native directory changed during scan")
            directories[directory] = after
    result = {}
    for name, patterns in OUTPUTS.items():
        selected = [relative for relative in paths if _matches_candidate(relative, patterns)]
        if name == "triangulation":
            selected = [relative for relative in selected if "filt" not in Path(relative).name and "LSTM" not in Path(relative).name]
        elif name == "filtering":
            selected = [relative for relative in selected if "LSTM" not in Path(relative).name]
        result[name] = sorted(selected)
    return result, directories


def _matches_candidate(relative: str, patterns: tuple[str, ...]) -> bool:
    candidate = relative.casefold() if os.name == "nt" else relative
    for pattern in patterns:
        for variant in (pattern, pattern.replace("/**/", "/")):
            if fnmatch.fnmatchcase(candidate, variant.casefold() if os.name == "nt" else variant):
                return True
    return False


def observe_comparison_source(project: Path) -> dict:
    result: dict = {"schema": SCHEMA, "status": "UNAVAILABLE", "token": None,
                    "reason": None, "evidence_verified": False}
    try:
        project = takes.checked_path(project)
        takes.require_no_pending(project)
        budget = [0]
        observed: dict[str, tuple[str, os.stat_result]] = {}

        def read(relative: str, expected: str | None = None) -> bytes:
            if relative in observed:
                raise ObservationError("SOURCE_INVALID: duplicate native source path")
            raw, proof = _read_source(project, relative, budget)
            digest = hashlib.sha256(raw).hexdigest()
            if expected is not None and digest != expected:
                raise ObservationError("SOURCE_INVALID: native artifact bytes differ from run binding")
            observed[relative] = digest, proof
            return raw

        session = _manifest(read("session.json"), project)
        read("Config.toml")
        for relative, schema in (("preflight.json", "kinelab.preflight.v1"),
                                 ("normalization.json", "kinelab.normalization.v1")):
            prerequisite = strict_json_loads(read(relative).decode("utf-8-sig"))
            if (not isinstance(prerequisite, dict) or prerequisite.get("schema") != schema
                    or prerequisite.get("session_id") != session["session_id"]
                    or prerequisite.get("config_sha256") != observed["Config.toml"][0]
                    or prerequisite.get("inputs") != {role: value["sha256"] for role, value in session["captures"].items()}
                    or (relative == "preflight.json" and (prerequisite.get("ok") is not True or prerequisite.get("errors")))):
                raise ObservationError("SOURCE_INVALID: incompatible native prerequisite")
        run = strict_json_loads(read("run.json").decode("utf-8-sig"))
        names = _candidates(project)
        native = validate_motion(strict_json_loads(read(names[0]).decode("utf-8-sig")))
        if (not isinstance(run, dict) or run.get("schema") != "kinelab.run.v1"
                or run.get("session_id") != session["session_id"]
                or run.get("config_sha256") != observed["Config.toml"][0]
                or run.get("inputs") != {role: value["sha256"] for role, value in session["captures"].items()}
                or native.get("schema") != "kinelab.motion.v2" or native.get("sessionId") != session["session_id"]
                or native.get("provenance", {}).get("runManifestSha256") != observed["run.json"][0]):
            raise ObservationError("SOURCE_INVALID: incompatible session/run/motion binding")
        stages = run.get("stages")
        if not isinstance(stages, list) or len(stages) != len(STAGES):
            raise ObservationError("SOURCE_INVALID: unsupported native stage count")
        inventory, directories = _native_candidates(project)
        count, logs = 0, set()
        for name, stage in zip(STAGES, stages):
            if (not isinstance(stage, dict) or stage.get("name") != name or stage.get("status") != "passed"
                    or not isinstance(stage.get("artifacts"), list) or not stage["artifacts"]):
                raise ObservationError("SOURCE_INVALID: malformed/duplicate native stage")
            bound = []
            quality = stage.get("quality")
            if not isinstance(quality, dict) or quality.get("ok") is not True:
                raise ObservationError("SOURCE_INVALID: missing native quality declaration")
            if isinstance(quality.get("log"), dict):
                log = quality["log"].get("path")
                if not isinstance(log, str):
                    raise ObservationError("SOURCE_INVALID: malformed quality log path")
                logs.add(log)
            for artifact in stage["artifacts"]:
                count += 1
                if count > MAX_ARTIFACTS:
                    raise ObservationError("LIMIT: bound native artifacts exceeded")
                if (not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str)
                        or not isinstance(artifact.get("sha256"), str)):
                    raise ObservationError("SOURCE_INVALID: malformed native artifact")
                read(artifact["path"], artifact["sha256"])
                bound.append(artifact["path"])
            if sorted(bound) != inventory[name]:
                raise ObservationError("SOURCE_INVALID: unrecorded or missing native candidate")
            if name == "triangulation" and "frame_diagnostics" in quality:
                binding = quality["frame_diagnostics"]
                if (not isinstance(binding, dict) or set(binding) != {
                    "path", "sha256", "schema", "source_trc", "calibration", "frames",
                } or not isinstance(binding.get("path"), str)
                        or not isinstance(binding.get("sha256"), str)
                        or not re.fullmatch("[0-9a-f]{64}", binding["sha256"])
                        or binding["path"] != "diagnostics/reconstruction-frames." + binding["sha256"] + ".json"
                        or binding.get("source_trc") not in stage["artifacts"]
                        or binding.get("calibration") not in stages[0]["artifacts"]):
                    raise ObservationError("SOURCE_INVALID: malformed or unbound frame diagnostics")
                document = _validate_frame_document(strict_json_loads(
                    read(binding["path"], binding["sha256"]).decode("utf-8")))
                if (binding["schema"] != FRAME_DIAGNOSTICS_SCHEMA or document["session_id"] != session["session_id"]
                        or document["source_trc"] != binding["source_trc"] or document["calibration"] != binding["calibration"]
                        or type(binding["frames"]) is not int or len(document["frames"]) != binding["frames"]):
                    raise ObservationError("SOURCE_INVALID: frame diagnostics contradict their binding")
        for relative in sorted(logs):
            read(relative)
        if _candidates(project) != names:
            raise ObservationError("CHANGED: native candidate inventory changed")
        if _native_candidates(project)[0] != inventory:
            raise ObservationError("CHANGED: native candidate inventory changed")
        takes.require_no_pending(project)
        for directory, proof in directories.items():
            after = takes.checked_path(directory).stat(follow_symlinks=False)
            if _identity(proof) != _identity(after) or proof.st_ctime_ns != after.st_ctime_ns:
                raise ObservationError("CHANGED: native directory changed during observation")
        for relative, (_, proof) in observed.items():
            after = takes.local_path(project, relative).stat(follow_symlinks=False)
            if _identity(proof) != _identity(after) or proof.st_ctime_ns != after.st_ctime_ns:
                raise ObservationError("CHANGED: source changed during observation")
        token = hashlib.sha256(json.dumps([(name, digest, proof.st_size) for name, (digest, proof)
                                          in sorted(observed.items())], separators=(",", ":")).encode()).hexdigest()
        return {**result, "status": "AVAILABLE", "token": token}
    except FileNotFoundError:
        result["reason"] = "COMPARISON_SOURCE_UNAVAILABLE: required source missing"
    except ObservationError as error:
        result["reason"] = "COMPARISON_" + str(error)
    except (OSError, ValueError, UnicodeError, KeyError, TypeError, RecursionError, OverflowError):
        result["reason"] = "COMPARISON_SOURCE_INVALID: unreadable, unsupported, unsafe or pending native source"
    return result
