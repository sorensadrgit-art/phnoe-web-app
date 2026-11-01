#!/usr/bin/env python3
"""Portable offline evidence verifier for KineLab PT backup archives (N05).

Read-only and standard-library only. This tool never imports, launches or
shares state with the KineLab application, never writes to the input archive,
and extracts the indexed database and, for native report prerequisites, the
two pinned normalized trial videos into fresh private temporary directories.
Native report prerequisites require an independent FFprobe decode; absence or
decoder errors refuse verification. Original camera frame equality is UNVERIFIED.

Supported input: kinelab.backup.v2 archives (current generated format) whose
index snapshot uses schema 3. Legacy kinelab.backup.v1 archives are reported
as unsupported for offline verification.

Package/hash integrity is verified. Source authenticity is NOT established:
the manifest is self-asserted and unsigned. Physical, biomechanical and
clinical correctness are separate validation questions and are never implied.

Exit codes: 0 valid, 1 invalid evidence, 2 unsupported evidence or I/O error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from statistics import median

SUPPORTED_BACKUP_SCHEMA = "kinelab.backup.v2"
SUPPORTED_INDEX_SCHEMA = 3
ROLES = ("cam01_intrinsics", "cam02_intrinsics", "cam01_board", "cam02_board", "cam01_trial", "cam02_trial")
INDEXED_EVIDENCE_FILES = ("session.json", "normalization.json", "preflight.json", "sync-observations.json",
                          "sync.json", "run.json", "board-measurement.json")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)},
                    *{f"LPT{i}" for i in range(1, 10)}}
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
GENERATION_RE = re.compile(r"report-[0-9a-f]{32}")
REPORT_INPUT_POLICY_V2 = "kinelab.report-inputs.v2"
REPORT_ADMINISTRATIVE_ANCHOR = "takes/.acceptance-lease/t6-startup.lock"

MAX_MEMBERS = 10_000
MAX_MEMBER_BYTES = 1024 ** 3
MAX_TOTAL_BYTES = 10 * (1024 ** 3)
MAX_RATIO = 100
MAX_MANIFEST_BYTES = 8 * 1024 * 1024

MAX_CHUNK_FRAMES = 16
MAX_CHUNK_BYTES = 48 * 1024
MAX_FRAMES = 54_000
MAX_DURATION_MS = 30 * 60 * 1000
SYNTHETIC_MODEL_SHA256 = "143e89f07ab2fbedb23ca2008c78f58913bc1ff12c67c81b64664307fcfc4b24"
PROTOCOLS = {name: name + "-research-v1" for name in ("squat", "lunge", "knee-extension", "balance")}
REASONS = {"NO_POSE", "LOW_CONFIDENCE", "OCCLUDED", "STALE", "DEVICE_LOST", "GAP", "MODEL_UNAVAILABLE",
           "INVALID_GEOMETRY", "MULTIPLE_PEOPLE", "PAUSED", "BACKPRESSURE", "INFERENCE_ERROR"}
REQUIRED_JOINTS = (11, 12, 23, 24, 25, 26, 27, 28)

LIMITS = [
    "Supported evidence: kinelab.backup.v2 archives with index schema 3 only; legacy v1 fails as unsupported.",
    "Only index.db is extracted, into a newly generated temporary directory, opened read-only/immutable.",
    "The input archive is never modified, restored or merged anywhere.",
    "Recording validation covers the synthetic kinelab.recording.v1 contract; no other source kind exists.",
    "Legacy reports without input_policy retain strict input binding; a later administrative anchor requires explicit migration.",
    "V2 report metadata/history and generated manual agreement are independently checked; declarations do not authenticate reviewers or trajectory derivation.",
    "Package/hash integrity does not establish source authenticity: manifests are self-asserted and unsigned.",
    "Physical accuracy and clinical validation are out of scope and remain UNVERIFIED.",
]

CHECK_IDS = ("zip.structure", "manifest.schema", "manifest.inventory", "member.digests",
             "database.integrity", "audit.lineage", "evidence.crosscheck",
             "recording.sequence", "report.lineage")


class VerifyError(ValueError):
    def __init__(self, code, message, check):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.check = check


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

    def finite(item, field="$"):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON_INVALID: nonfinite number at " + field)
        if isinstance(item, dict):
            for key, child in item.items():
                finite(child, field + "." + key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                finite(child, f"{field}[{index}]")

    result = json.loads(value, object_pairs_hook=unique, parse_constant=constant)
    finite(result)
    return result


def canonical_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("MEASUREMENT_INVALID: not finite standard JSON") from error


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def safe_member_name(name, check):
    """A portable non-traversing path, without Windows aliases or reparse tricks."""
    if (not isinstance(name, str) or len(name) > 4096 or not name
            or name.startswith("/") or "\\" in name or ":" in name
            or unicodedata.normalize("NFC", name) != name
            or unicodedata.normalize("NFKC", name) != name):
        raise VerifyError("EVIDENCE_PATH_INVALID", f"unsafe archive path {name!r}", check)
    parts = name.split("/")
    if any(not p or p in (".", "..") or p.rstrip(" .") != p
           or p.split(".", 1)[0].upper() in WINDOWS_RESERVED
           or any(ord(ch) < 32 or ord(ch) == 127 or ch in '<>"|?*' for ch in p)
           for p in parts):
        raise VerifyError("EVIDENCE_PATH_INVALID", f"unsafe archive component in {name!r}", check)
    return tuple(parts)


def _invalid(field, reason):
    raise ValueError(f"MEASUREMENT_INVALID: {field}: {reason}")


def _object(value, keys, field):
    if not isinstance(value, dict) or set(value) != set(keys):
        _invalid(field, "expected exactly " + ", ".join(keys))


def _number(value, field, minimum=None, maximum=None, integer=False):
    if (type(value) not in ((int,) if integer else (int, float)) or
            abs(value) > sys.float_info.max or (type(value) is float and not math.isfinite(value))):
        _invalid(field, "expected finite " + ("integer" if integer else "number"))
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        _invalid(field, "outside supported range")


def _text(value, pattern, field):
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        _invalid(field, "unsupported identifier or format")
def validate_header(value):
    _object(value, ("schema", "session_id", "operation_id", "subject_id", "operator_id", "source", "protocol", "coordinates"), "header")
    if value["schema"] != "kinelab.recording.v1":
        _invalid("schema", "expected kinelab.recording.v1")
    for key in ("session_id", "subject_id", "operator_id"):
        _text(value[key], r"synthetic-[A-Za-z0-9][A-Za-z0-9_-]{0,70}", key)
    _text(value["operation_id"], r"[a-f0-9]{32}", "operation_id")
    source = value["source"]
    _object(source, ("kind", "capture_id", "model_id", "model_version", "model_sha256"), "source")
    if source["kind"] != "synthetic":
        _invalid("source.kind", "participant and measured recording remain blocked")
    if source["model_id"] != "kinelab-synthetic-33" or source["model_version"] != "1":
        _invalid("source.model_id/version", "unsupported model")
    _text(source["capture_id"], r"[a-f0-9]{32}", "source.capture_id")
    _text(source["model_sha256"], r"[a-f0-9]{64}", "source.model_sha256")
    if source["model_sha256"] != SYNTHETIC_MODEL_SHA256:
        _invalid("source.model_sha256", "generator digest differs from the registered version")
    protocol = value["protocol"]
    _object(protocol, ("id", "version", "exercise", "side", "target_angle_degrees", "target_hold_ms"), "protocol")
    if not isinstance(protocol["exercise"], str) or PROTOCOLS.get(protocol["exercise"]) != protocol["id"]:
        _invalid("protocol.id/exercise", "unsupported protocol")
    if type(protocol["version"]) is not int or protocol["version"] != 1:
        _invalid("protocol.version", "unsupported version")
    allowed_sides = ("left", "right", "bilateral") if protocol["exercise"] == "squat" else ("left", "right")
    if protocol["side"] not in allowed_sides:
        _invalid("protocol.side", "explicit supported laterality required")
    if protocol["exercise"] == "balance":
        if protocol["target_angle_degrees"] is not None:
            _invalid("protocol.target_angle_degrees", "balance uses elapsed time")
        _number(protocol["target_hold_ms"], "protocol.target_hold_ms", 1, MAX_DURATION_MS, integer=True)
    else:
        _number(protocol["target_angle_degrees"], "protocol.target_angle_degrees", 0, 180)
        if protocol["target_hold_ms"] is not None:
            _invalid("protocol.target_hold_ms", "repetition protocol uses angle target")
    coordinates = value["coordinates"]
    _object(coordinates, ("space", "units", "z_units", "width", "height", "mirrored"), "coordinates")
    if (coordinates["space"], coordinates["units"], coordinates["z_units"]) != ("image-normalized", "normalized", "relative"):
        _invalid("coordinates", "image-normalized x/y and relative z required; not measured metres")
    for key in ("width", "height"):
        _number(coordinates[key], "coordinates." + key, 1, 16384, integer=True)
    if type(coordinates["mirrored"]) is not bool:
        _invalid("coordinates.mirrored", "explicit boolean required")
    canonical_json(value)
    return value


def validate_frames(frames):
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_CHUNK_FRAMES:
        _invalid("frames", f"expected 1..{MAX_CHUNK_FRAMES} frames")
    previous_sequence, previous_time = None, None
    for index, frame in enumerate(frames):
        field = f"frames[{index}]"
        _object(frame, ("sequence", "time_ms", "valid", "reasons", "landmarks"), field)
        _number(frame["sequence"], field + ".sequence", 1, MAX_FRAMES, integer=True)
        _number(frame["time_ms"], field + ".time_ms", 0, MAX_DURATION_MS)
        if previous_sequence is not None and frame["sequence"] != previous_sequence + 1:
            _invalid(field + ".sequence", "noncontiguous or duplicate sequence")
        if previous_time is not None and frame["time_ms"] <= previous_time:
            _invalid(field + ".time_ms", "timestamps must strictly increase")
        previous_sequence, previous_time = frame["sequence"], frame["time_ms"]
        if type(frame["valid"]) is not bool:
            _invalid(field + ".valid", "boolean required")
        reasons = frame["reasons"]
        if (not isinstance(reasons, list) or any(not isinstance(reason, str) or reason not in REASONS for reason in reasons)
                or len(set(reasons)) != len(reasons) or bool(reasons) == frame["valid"]):
            _invalid(field + ".reasons", "invalid, missing or contradictory validity reasons")
        points = frame["landmarks"]
        if points is None:
            if frame["valid"]:
                _invalid(field + ".landmarks", "missing observation cannot be valid")
            continue
        if not isinstance(points, list) or len(points) != 33:
            _invalid(field + ".landmarks", "expected 33 points or null")
        for joint, point in enumerate(points):
            if point is None:
                continue
            if not isinstance(point, list) or len(point) != 4:
                _invalid(f"{field}.landmarks[{joint}]", "expected x,y,z,confidence or null")
            for axis, number in enumerate(point):
                _number(number, f"{field}.landmarks[{joint}][{axis}]", None if axis == 2 else 0, None if axis == 2 else 1)
        if frame["valid"]:
            if any(points[joint] is None or points[joint][3] < .5 for joint in REQUIRED_JOINTS):
                _invalid(field + ".valid", "required joint missing or confidence below 0.5")
            for a, b in ((11, 23), (12, 24), (23, 25), (24, 26), (25, 27), (26, 28)):
                if points[a][:2] == points[b][:2]:
                    _invalid(field + ".valid", "degenerate image geometry")
    if len(canonical_json(frames).encode("utf-8")) > MAX_CHUNK_BYTES:
        _invalid("frames", "encoded chunk exceeds 48 KiB")
    return frames


def _check_structure(archive):
    infos = archive.infolist()
    check = "zip.structure"
    if not infos or len(infos) > MAX_MEMBERS:
        raise VerifyError("EVIDENCE_LIMIT_EXCEEDED", "too many archive members", check)
    members = {}
    aliases = set()
    path_components = {}
    directories = set()
    total = 0
    for info in infos:
        parts = safe_member_name(info.filename, check)
        if info.is_dir():
            raise VerifyError("EVIDENCE_PATH_INVALID", "directory ZIP members unsupported", check)
        key = "/".join(parts).casefold()
        if key in aliases or key in directories:
            raise VerifyError("EVIDENCE_PATH_INVALID", "duplicate or case-alias member", check)
        for length in range(1, len(parts) + 1):
            component = "/".join(parts[:length])
            folded = component.casefold()
            if path_components.setdefault(folded, component) != component:
                raise VerifyError("EVIDENCE_PATH_INVALID", "case-alias directory", check)
            if length < len(parts):
                if folded in aliases:
                    raise VerifyError("EVIDENCE_PATH_INVALID", "file/directory collision", check)
                directories.add(folded)
        aliases.add(key)
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or info.external_attr & 0x400:
            raise VerifyError("EVIDENCE_PATH_INVALID", "linked or nonregular member", check)
        if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise VerifyError("EVIDENCE_FORMAT_INVALID", "encrypted or unsupported compression", check)
        if info.file_size < 0 or info.compress_size < 0 or info.file_size > MAX_MEMBER_BYTES:
            raise VerifyError("EVIDENCE_LIMIT_EXCEEDED", "member exceeds 1 GiB", check)
        if info.file_size > 0 and (info.compress_size == 0 or info.file_size > info.compress_size * MAX_RATIO):
            raise VerifyError("EVIDENCE_LIMIT_EXCEEDED", "suspicious compression ratio", check)
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise VerifyError("EVIDENCE_LIMIT_EXCEEDED", "archive exceeds 10 GiB", check)
        members[info.filename] = info
    return members
def _check_manifest(archive, members):
    check = "manifest.schema"
    manifest_info = members.get("backup_manifest.json")
    if manifest_info is None or manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise VerifyError("EVIDENCE_MANIFEST_INVALID", "missing or oversized manifest", check)
    try:
        manifest = strict_json_loads(archive.read(manifest_info).decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise VerifyError("EVIDENCE_MANIFEST_INVALID", f"unreadable JSON: {exc}", check) from exc
    if not isinstance(manifest, dict):
        raise VerifyError("EVIDENCE_MANIFEST_INVALID", "object required", check)
    schema = manifest.get("schema")
    if schema != SUPPORTED_BACKUP_SCHEMA:
        raise VerifyError("EVIDENCE_UNSUPPORTED_SCHEMA",
                          f"schema {schema!r}; offline verification supports {SUPPORTED_BACKUP_SCHEMA} "
                          "(legacy v1 archives are inspectable only inside the application)", check)
    generation = manifest.get("generation")
    if (not isinstance(generation, dict)
            or set(generation) != {"id", "index_schema", "audit_tip", "recording_count"}
            or not isinstance(generation["id"], str) or re.fullmatch(r"[0-9a-f]{32}", generation["id"]) is None
            or type(generation["index_schema"]) is not int
            or not isinstance(generation["audit_tip"], str)
            or re.fullmatch(r"[0-9a-f]{64}", generation["audit_tip"]) is None
            or type(generation["recording_count"]) is not int or generation["recording_count"] < 0
            or manifest.get("database_included") is not True):
        raise VerifyError("EVIDENCE_MANIFEST_INVALID", "recovery generation required", check)
    if generation["index_schema"] != SUPPORTED_INDEX_SCHEMA:
        raise VerifyError("EVIDENCE_UNSUPPORTED_SCHEMA",
                          f"index schema {generation['index_schema']}; supported {SUPPORTED_INDEX_SCHEMA}", check)
    return manifest


def _check_inventory(manifest, members):
    check = "manifest.inventory"
    sessions = manifest.get("sessions")
    files = manifest.get("files")
    database_included = manifest.get("database_included")
    file_count = manifest.get("file_count")
    if (not isinstance(sessions, list) or not isinstance(files, list)
            or type(database_included) is not bool or type(file_count) is not int
            or file_count != len(files) or file_count > MAX_MEMBERS - 1):
        raise VerifyError("EVIDENCE_MANIFEST_INVALID", "inventory fields inconsistent", check)
    sid_set = set()
    for sid in sessions:
        if not isinstance(sid, str) or not SAFE_ID.fullmatch(sid) or sid.endswith(".") \
                or sid.split(".")[0].upper() in WINDOWS_RESERVED:
            raise VerifyError("EVIDENCE_MANIFEST_INVALID", f"unsafe session id {sid!r}", check)
        folded = sid.casefold()
        if folded in sid_set:
            raise VerifyError("EVIDENCE_MANIFEST_INVALID", "repeated session alias", check)
        sid_set.add(folded)
    listed = set()
    listed_aliases = set()
    config_roles = set()
    for item in files:
        if not isinstance(item, dict):
            raise VerifyError("EVIDENCE_MANIFEST_INVALID", "file objects required", check)
        rel = item.get("path")
        parts = safe_member_name(rel, check)
        if len(parts) == 1 and rel == "index.db":
            if not database_included:
                raise VerifyError("EVIDENCE_MANIFEST_INVALID", "undeclared database", check)
        elif len(parts) >= 3 and parts[0] == "sessions" and parts[1] in sessions:
            if len(parts) == 3 and parts[2] == "Config.toml":
                config_roles.add(parts[1])
        else:
            raise VerifyError("EVIDENCE_MANIFEST_INVALID", f"undeclared session file {rel!r}", check)
        if rel in listed or rel.casefold() in listed_aliases:
            raise VerifyError("EVIDENCE_MANIFEST_INVALID", "duplicate file entries", check)
        listed.add(rel)
        listed_aliases.add(rel.casefold())
        nbytes = item.get("bytes")
        checksum = item.get("sha256")
        if (type(nbytes) is not int or nbytes < 0 or nbytes > MAX_MEMBER_BYTES
                or not isinstance(checksum, str) or re.fullmatch(r"[0-9a-fA-F]{64}", checksum) is None):
            raise VerifyError("EVIDENCE_MANIFEST_INVALID", "size or digest invalid", check)
        info = members.get(rel)
        if info is None:
            raise VerifyError("EVIDENCE_INVENTORY_INCOMPLETE", f"listed file absent: {rel}", check)
        if info.file_size != nbytes:
            raise VerifyError("EVIDENCE_MANIFEST_INVALID", f"listed size differs: {rel}", check)
    if ("index.db" in listed) != database_included:
        raise VerifyError("EVIDENCE_MANIFEST_INVALID", "database inventory mismatch", check)
    if set(sessions) != config_roles:
        raise VerifyError("EVIDENCE_MANIFEST_INVALID", "missing session Config.toml", check)
    unexpected = set(members) - (listed | {"backup_manifest.json"})
    if unexpected:
        raise VerifyError("EVIDENCE_INVENTORY_UNEXPECTED_MEMBER",
                          "unlisted archive member(s): " + ", ".join(sorted(unexpected)), check)
    return manifest["files"]


def _check_digests(archive, manifest, members):
    check = "member.digests"
    digests = {}
    for item in manifest["files"]:
        hasher = hashlib.sha256()
        size = 0
        with archive.open(members[item["path"]]) as source:
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > item["bytes"] or size > MAX_MEMBER_BYTES:
                    raise VerifyError("EVIDENCE_CORRUPT", f"expanded size mismatch: {item['path']}", check)
                hasher.update(block)
        observed = hasher.hexdigest()
        if size != item["bytes"] or observed != item["sha256"].lower():
            raise VerifyError("EVIDENCE_DIGEST_MISMATCH",
                              f"{item['path']}: expected sha256 {item['sha256']}/{item['bytes']} bytes, "
                              f"observed {observed}/{size} bytes", check)
        digests[item["path"]] = {"sha256": observed, "bytes": size}
    return digests


def _event_hash(event):
    fields = ("event_id", "session_id", "event_type", "details_json", "timestamp_utc",
              "actor", "revision", "outcome", "previous_hash")
    data = json.dumps({key: event[key] for key in fields}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def _verify_audit_chain(conn):
    previous = "0" * 64
    count = 0
    for row in conn.execute("SELECT * FROM audit_events ORDER BY id"):
        event = dict(row)
        if event["previous_hash"] != previous or event["event_hash"] != _event_hash(event):
            raise VerifyError("AUDIT_CHAIN_INVALID",
                              f"audit event id={event['id']} fails hash-chain verification", "audit.lineage")
        previous = event["event_hash"]
        count += 1
    return previous, count


def _verify_crosscheck(conn, manifest, digests):
    check = "evidence.crosscheck"
    present = sorted(row[0] for row in conn.execute("SELECT id FROM sessions WHERE present=1"))
    if present != sorted(manifest["sessions"]):
        raise VerifyError("EVIDENCE_INVENTORY_INCOMPLETE", "session index and file inventory differ", check)
    for sid in present:
        for table in ("sources", "artifacts"):
            rows = conn.execute(f"SELECT * FROM {table} WHERE session_id=?", (sid,)).fetchall()
            if table == "sources":
                candidates = {"raw/" + role + ".mp4" for role in ROLES}
                indexed = {"raw/" + row["role"] + ".mp4" for row in rows}
            else:
                candidates = set(INDEXED_EVIDENCE_FILES)
                prefix = f"sessions/{sid}/exports/"
                candidates.update(p[len(f"sessions/{sid}/"):] for p in digests
                                  if p.startswith(prefix) and p.count("/") == 3 and p.endswith(".motion.json"))
                indexed = {row["artifact_key"] for row in rows}
            for name in candidates - indexed:
                if f"sessions/{sid}/{name}" in digests:
                    raise VerifyError("EVIDENCE_INVENTORY_INCOMPLETE",
                                      f"file evidence missing from the index snapshot: {sid}/{name}", check)
            for row in rows:
                if table == "sources" and row["role"] not in ROLES:
                    raise VerifyError("EVIDENCE_MANIFEST_INVALID", "unknown source role", check)
                name = "raw/" + row["role"] + ".mp4" if table == "sources" else row["artifact_key"]
                safe_member_name(f"sessions/{sid}/{name}", check)
                if row["filename"] != name.split("/")[-1] or re.fullmatch(r"[0-9a-f]{64}", row["sha256"] or "") is None:
                    raise VerifyError("EVIDENCE_MANIFEST_INVALID", "invalid indexed reference", check)
                entry = digests.get(f"sessions/{sid}/{name}")
                observed = entry["sha256"] if entry else None
                state = "missing" if observed is None else "unchanged" if observed == row["sha256"] else "changed"
                if row["observed_sha256"] != observed or row["integrity_state"] != state:
                    raise VerifyError("EVIDENCE_CORRUPT",
                                      f"indexed observation and file snapshot differ: {sid}/{name}", check)
def _verify_recording(conn, row):
    check = "recording.sequence"

    def corrupt(reason):
        raise VerifyError("RECORDING_CORRUPT", f"{row['session_id']}: {reason}", check)

    sid = row["session_id"]
    try:
        header = validate_header(strict_json_loads(row["header_json"]))
    except ValueError as exc:
        corrupt(f"header: {exc}")
    if (digest(header) != row["header_sha256"] or header["session_id"] != sid
            or header["operation_id"] != row["operation_id"]
            or header["source"]["capture_id"] != row["capture_id"]):
        corrupt("header identity")
    if row["state"] not in ("RECORDING", "FINALIZED"):
        corrupt(f"unsupported state {row['state']!r}")
    chunks = conn.execute("""SELECT chunk_id, first_sequence, last_sequence,
        first_time_ms, last_time_ms, frames_json, sha256 FROM recording_chunks
        WHERE session_id=? ORDER BY first_sequence""", (sid,)).fetchall()
    parsed = []
    saved = received = 0
    for part in chunks:
        raw = part["frames_json"]
        if len(raw.encode("utf-8")) > MAX_CHUNK_BYTES:
            corrupt("chunk exceeds 48 KiB")
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != part["sha256"]:
            corrupt(f"chunk {part['chunk_id']} digest")
        try:
            frames = validate_frames(strict_json_loads(raw))
        except ValueError as exc:
            corrupt(f"chunk {part['chunk_id']} frames: {exc}")
        if (frames[0]["sequence"] != part["first_sequence"] or frames[-1]["sequence"] != part["last_sequence"]
                or frames[0]["time_ms"] != part["first_time_ms"] or frames[-1]["time_ms"] != part["last_time_ms"]):
            corrupt(f"chunk {part['chunk_id']} sequence/time bounds")
        if part["first_sequence"] == saved + 1:
            saved = part["last_sequence"]
        received = part["last_sequence"]
        parsed.append((part, frames))
    events = conn.execute("""SELECT * FROM audit_events WHERE session_id=? AND event_type IN
        ('RECORDING_CREATED','RECORDING_CHUNK_SAVED','RECORDING_FINALIZED') ORDER BY id""", (sid,)).fetchall()
    finalized = row["state"] == "FINALIZED"
    if len(events) != row["revision"]:
        corrupt(f"audit receipt count {len(events)} != revision {row['revision']}")
    parts_by_id = {part["chunk_id"]: part for part, _ in parsed}
    seen = set()
    for revision, event in enumerate(events, 1):
        try:
            details = strict_json_loads(event["details_json"])
        except ValueError as exc:
            corrupt(f"audit receipt JSON: {exc}")
        kind = event["event_type"]
        if revision == 1:
            expected, expected_kind = {"header_sha256": row["header_sha256"]}, "RECORDING_CREATED"
        elif finalized and revision == len(events):
            expected, expected_kind = {"manifest_sha256": row["manifest_sha256"]}, "RECORDING_FINALIZED"
        else:
            part = parts_by_id.get(details.get("chunk_id") if isinstance(details, dict) else None)
            if part is None or part["chunk_id"] in seen:
                corrupt("chunk audit identity")
            seen.add(part["chunk_id"])
            expected = {key: part[key] for key in ("chunk_id", "sha256", "first_sequence", "last_sequence")}
            expected_kind = "RECORDING_CHUNK_SAVED"
        if details != expected or kind != expected_kind or event["revision"] != revision:
            corrupt(f"audit receipt mismatch at revision {revision}")
    if row["manifest_json"] is None:
        if finalized:
            corrupt("finalized recording has no manifest")
        return {"session_id": sid, "state": row["state"], "saved_through": saved,
                "received_through": received, "frames": sum(len(f) for _, f in parsed)}
    try:
        stored = strict_json_loads(row["manifest_json"])
    except ValueError as exc:
        corrupt(f"manifest: {exc}")
    if digest(stored) != row["manifest_sha256"]:
        corrupt("manifest digest")
    if not finalized:
        corrupt("unfinalized recording carries a manifest")
    end_reason = stored.get("end_reason") if isinstance(stored, dict) else None
    if end_reason not in ("operator_finished", "recovered_prefix", "capture_interrupted"):
        corrupt("end_reason")
    count = valid = 0
    last_sequence = 0
    first_time = last_time = None
    for part, frames in parsed:
        for frame in frames:
            if frame["sequence"] != last_sequence + 1 or (last_time is not None and frame["time_ms"] <= last_time):
                corrupt("sequence or timestamp")
            last_sequence = frame["sequence"]
            count += 1
            valid += int(frame["valid"])
            if first_time is None:
                first_time = frame["time_ms"]
            last_time = frame["time_ms"]
    recomputed = {"schema": "kinelab.recording-manifest.v1", "session_id": sid,
                  "operation_id": row["operation_id"], "header_sha256": row["header_sha256"],
                  "source_kind": "synthetic", "frame_count": count, "valid_frame_count": valid,
                  "last_sequence": last_sequence, "first_time_ms": first_time, "last_time_ms": last_time,
                  "end_reason": end_reason,
                  "unacknowledged_tail": "NONE_REPORTED" if end_reason == "operator_finished" else "UNKNOWN",
                  "chunks": [{key: part[key] for key in ("chunk_id", "first_sequence", "last_sequence",
                                                         "first_time_ms", "last_time_ms", "sha256")}
                             for part, _ in parsed],
                  "physical_accuracy_verified": False, "clinical_validation": "UNVERIFIED"}
    if stored != recomputed:
        corrupt("final manifest differs from stored frames")
    return {"session_id": sid, "state": row["state"], "frame_count": count,
            "valid_frame_count": valid, "last_sequence": last_sequence}


def _verify_recordings(conn, expected_count):
    check = "recording.sequence"
    rows = conn.execute("SELECT * FROM recordings ORDER BY session_id").fetchall()
    if len(rows) != expected_count:
        raise VerifyError("RECORDING_CORRUPT",
                          f"recording count {len(rows)} != declared {expected_count}", check)
    return [_verify_recording(conn, row) for row in rows]


def _report_object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("exact report evidence fields required")
    return value


def _report_sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid report evidence digest")
    return value


def _report_reference(value):
    _report_object(value, ("sha256", "bytes"))
    _report_sha(value["sha256"])
    if type(value["bytes"]) is not int or value["bytes"] < 0:
        raise ValueError("invalid report evidence size")
    return value


def _report_document(archive, members, digests, path, limit=64 * 1024):
    safe_member_name(path, "report.lineage")
    entry = digests.get(path)
    if entry is None or entry["bytes"] > limit:
        raise ValueError("missing or oversized report evidence document")
    value = strict_json_loads(archive.read(members[path]).decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError("report evidence object required")
    return value


def _report_timestamp(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).utcoffset() is None:
        raise ValueError("timezone-aware report evidence timestamp required")


def _report_metadata(value):
    _report_object(value, ("schema", "subject_id", "operator_id", "task_id", "protocol_id",
                           "protocol_version", "laterality", "confirmed", "confirmed_at"))
    if value["schema"] != "kinelab.session-metadata.v1" or value["confirmed"] is not True:
        raise ValueError("invalid confirmed metadata contract")
    for key, prefix in (("subject_id", "sub-"), ("operator_id", "op-")):
        if not isinstance(value[key], str) or re.fullmatch(prefix + r"[0-9a-f]{32}", value[key]) is None:
            raise ValueError("invalid metadata identity")
    for key in ("task_id", "protocol_id", "protocol_version"):
        if not isinstance(value[key], str) or SAFE_ID.fullmatch(value[key]) is None:
            raise ValueError("invalid metadata protocol")
    if value["laterality"] not in ("left", "right", "bilateral", "not_applicable"):
        raise ValueError("invalid metadata laterality")
    _report_timestamp(value["confirmed_at"])
    return value


def _report_metadata_history(conn, archive, members, digests, sid):
    """Independently reconstruct metadata authority, never trust a report's hashes alone."""
    prefix = f"sessions/{sid}/"
    origin = {"path": "session.json", "sha256": digests[prefix + "session.json"]["sha256"]}
    row = conn.execute("SELECT sha256,bytes,filename FROM artifacts WHERE session_id=? AND artifact_key='session.json'",
                       (sid,)).fetchone()
    if (row is None or row["filename"] != "session.json" or type(row["bytes"]) is not int
            or not 0 < row["bytes"] <= 64 * 1024
            or row["sha256"] != origin["sha256"] or row["bytes"] != digests[prefix + "session.json"]["bytes"]):
        raise ValueError("immutable indexed report origin differs")
    session = _report_document(archive, members, digests, prefix + "session.json")
    indexed = conn.execute("SELECT kind FROM sessions WHERE id=?", (sid,)).fetchone()
    if (session.get("schema") != "kinelab.session.v1" or session.get("session_id") != sid
            or session.get("kind") not in ("real", "demo") or indexed is None
            or indexed["kind"] != session["kind"] or type(session.get("subject_count")) is not int
            or session["subject_count"] != 1 or session.get("camera_ids") != ["cam01", "cam02"]):
        raise ValueError("registered report origin identity differs")
    _report_timestamp(session.get("created_at"))
    initial = _report_metadata(session.get("metadata"))
    captures = session.get("captures")
    sources = {item["role"]: item for item in conn.execute(
        "SELECT role,filename,sha256,bytes FROM sources WHERE session_id=?", (sid,))}
    if not isinstance(captures, dict) or set(captures) != set(ROLES) or set(sources) != set(ROLES):
        raise ValueError("six immutable report capture baselines required")
    bindings = {}
    for role in ROLES:
        path = "raw/" + role + ".mp4"
        source, capture = sources[role], captures[role]
        observed = digests.get(prefix + path)
        if (not isinstance(capture, dict) or capture.get("path") != path
                or source["filename"] != role + ".mp4" or type(source["bytes"]) is not int
                or source["bytes"] < 1 or capture.get("sha256") != source["sha256"]
                or observed != {"sha256": source["sha256"], "bytes": source["bytes"]}):
            raise ValueError("immutable report capture binding differs")
        _report_sha(source["sha256"])
        bindings[role] = {"path": path, "sha256": source["sha256"], "bytes": source["bytes"]}
    baseline = {"origin": origin, "origin_bytes": row["bytes"], "captures": bindings}

    def context(head):
        return digest({"schema": "kinelab.session-metadata-context.v1", "session_id": sid,
                       "origin": origin, "head": head})

    history, operations, authority = [(0, context(None))], {}, {}
    rows = conn.execute("SELECT id,details_json FROM audit_events WHERE session_id=? AND event_type='METADATA_REVISION_PUBLISHED' ORDER BY id LIMIT 513",
                        (sid,)).fetchall()
    if len(rows) > 512:
        raise ValueError("metadata revision verification limit exceeded")
    head = None
    for event in rows:
        record = _report_object(strict_json_loads(event["details_json"]), ("operation_id", "descriptor", "receipt"))
        operation = record["operation_id"]
        if not isinstance(operation, str) or re.fullmatch(r"[0-9a-f]{32}", operation) is None or operation in operations:
            raise ValueError("invalid or duplicate metadata operation")
        reference = _report_object(record["descriptor"], ("path", "sha256"))
        _report_sha(reference["sha256"])
        path = reference["path"]
        if not isinstance(path, str) or re.fullmatch(r"metadata-revisions/revision-[0-9a-f]{32}/revision\.json", path) is None:
            raise ValueError("invalid metadata descriptor path")
        descriptor = _report_document(archive, members, digests, prefix + path)
        if digests[prefix + path]["sha256"] != reference["sha256"]:
            raise ValueError("metadata descriptor changed")
        _report_object(descriptor, ("schema", "session_id", "operation_id", "revision_id", "metadata",
                                    "initial_metadata", "origin", "baseline", "previous", "reason_code", "created_at"))
        revision = descriptor["revision_id"]
        if (not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{32}", revision) is None
                or descriptor["schema"] != "kinelab.session-metadata-revision.v1"
                or descriptor["session_id"] != sid or descriptor["operation_id"] != operation
                or path != f"metadata-revisions/revision-{revision}/revision.json"
                or descriptor["initial_metadata"] != initial or descriptor["origin"] != origin
                or canonical_json(descriptor["baseline"]) != canonical_json(baseline) or descriptor["previous"] != head
                or descriptor["reason_code"] != "operator_correction"):
            raise ValueError("metadata predecessor or immutable baseline differs")
        _report_timestamp(descriptor["created_at"])
        _report_metadata(descriptor["metadata"])
        receipt = {"schema": "kinelab.session-metadata-revision-receipt.v1", "session_id": sid,
                   "operation_id": operation, "revision_id": revision, "descriptor": reference,
                   "context_sha256": context(reference)}
        if record["receipt"] != receipt:
            raise ValueError("metadata publication receipt differs")
        operations[operation] = (descriptor, receipt, event["id"])
        authority[path] = (digests[prefix + path], event["id"])
        head = reference
        history.append((event["id"], context(head)))
    for path in digests:
        if not path.startswith(prefix + "metadata-revisions/"):
            continue
        relative = path[len(prefix):]
        name = relative.removeprefix("metadata-revisions/")
        if name.startswith("pending-"):
            raise ValueError("pending metadata revision requires explicit recovery")
        if name.startswith("resolved-"):
            match = re.fullmatch(r"resolved-([0-9a-f]{32})-committed\.json", name)
            if match is None or match[1] not in operations:
                raise ValueError("unsupported or unaudited metadata terminal witness")
            descriptor, receipt, event_id = operations[match[1]]
            expected = {"schema": "kinelab.session-metadata-revision-intent.v1", "session_id": sid,
                        "operation_id": match[1], "descriptor": descriptor, "receipt": receipt}
            if _report_document(archive, members, digests, path) != expected:
                raise ValueError("retained metadata commit witness differs")
            authority[relative] = (digests[path], event_id)
        elif relative not in authority:
            raise ValueError("unaudited metadata revision member")
    return origin, history, authority


_MA_GAIT_ALGORITHM_VERSION = "kinelab-t5-foot-extrema-2d-v1"
_MA_SOURCE_SCHEMA = "kinelab.testonly.fullseq.halpe26.v1"
_MA_GAIT_CANDIDATES_SCHEMA = "kinelab.2d-gait-candidates.v1"
_MA_GAIT_REFERENCE_SCHEMA = "kinelab.manual-gait-reference.v1"
_MA_GAIT_SCORE_THRESHOLD = 0.43
_MA_GAIT_SMOOTH_HALF_WINDOW = 3
_MA_GAIT_PROMINENCE_WINDOW = 16
_MA_GAIT_MIN_PROMINENCE = 0.0075
_MA_GAIT_MIN_SPACING = 18
_MA_EXPECTED_FPS = 30
_MA_LANDMARKS = 26
_MA_GAIT_LANDMARK_INDICES = {
    "left_heel": 24, "right_heel": 25,
    "left_big_toe": 20, "right_big_toe": 21,
}
_MA_PELVIS_INDEX = 19
_MA_SOURCE_HASH = re.compile(r"[a-f0-9]{64}\Z")
_MA_EVIDENCE_CLASSIFICATION = "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION"
_MA_UNSUPPORTED_GAIT_METRICS = (
    ("cadence", "No validated step detection, timing reference or walking-bout segmentation."),
    ("stride_length", "2D image pixels without calibration or scale; metric length is not measurable."),
    ("step_length", "2D image pixels without calibration or scale; metric length is not measurable."),
    ("gait_speed", "No physical scale or calibrated time-distance reference."),
    ("stance_swing_durations", "Extrema are unvalidated contact/toe-off hypotheses, not measured phases."),
)

_MA_SQUAT_CANDIDATES_SCHEMA = "kinelab.2d-squat-candidates.v1"
_MA_SQUAT_REFERENCE_SCHEMA = "kinelab.manual-2d-squat-reference.v1"
_MA_SQUAT_ALGORITHM_VERSION = "kinelab-t5-squat-2d-phase-v1"
_MA_SQUAT_FPS = 30
_MA_SQUAT_CONFIDENCE_SCORE_THRESHOLD = .43
_MA_SQUAT_SMOOTH_HALF_WINDOW = 2
_MA_SQUAT_BASELINE_FRAMES = 20
_MA_SQUAT_REQUIRED_INDICES = (5, 6, 11, 12, 13, 14, 15, 16)
_MA_SQUAT_BEGIN_FLEX_DEGREES = 16.
_MA_SQUAT_BEGIN_HIP_DROP = .10
_MA_SQUAT_BOTTOM_FLEX_DEGREES = 45.
_MA_SQUAT_BOTTOM_HIP_DROP = .33
_MA_SQUAT_END_FLEX_DEGREES = 18.
_MA_SQUAT_END_HIP_DROP = .14
_MA_SQUAT_MIN_REP_DURATION = 20
_MA_SQUAT_MAX_REP_DURATION = 240
_MA_SQUAT_EXCLUSION_REASONS = ("no_person", "ambiguous_person", "low_score_or_occluded",
                               "outside_image", "degenerate_geometry")
_MA_UNSUPPORTED_SQUAT_METRICS = (
    ("physical_knee_flexion_rom", "2D image-plane angle; no calibrated 3D sagittal-plane kinematics."),
    ("squat_depth_meters", "Pelvis displacement is in torso-normalized image units, not meters."),
    ("clinical_repetition_quality", "No validated scoring rubric or clinical reference."),
    ("movement_velocity", "No physical scale; image-unit derivatives are not physical velocity."),
)

_MA_TRIAL_ROLES = ("cam01_trial", "cam02_trial")
_MA_REQUEST_ANNOTATION_ORIGIN = "human_observed_video_frames"
# The producer emits datetime.now(UTC).isoformat(); microseconds are omitted when zero.
_MA_RECORDED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00\Z")


class _MAManualArithmeticError(ValueError):
    """Offline manual arithmetic refused; never a fallback success."""


class _MAGaitEvidenceError(_MAManualArithmeticError):
    """Port of gait_events.GaitEvidenceError."""


class _MASquatEvidenceError(_MAManualArithmeticError):
    """Port of squat_events.SquatEvidenceError."""


def _ma_fail(message):
    raise _MAManualArithmeticError("MANUAL_ARITHMETIC_INVALID: " + message)


def _ma_canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise _MAManualArithmeticError("MANUAL_ARITHMETIC_INVALID: not finite standard JSON") from error


# --- gait_events.py port -----------------------------------------------------

def _ma_finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _ma_gait_require(cond, message):
    if not cond:
        raise _MAGaitEvidenceError(message)


def _ma_validate_2d_trajectories(evidence, expected_role, expected_source_sha256):
    _ma_gait_require(isinstance(evidence, dict), "Missing 2D source evidence")
    _ma_gait_require(evidence.get("schema") == _MA_SOURCE_SCHEMA and evidence.get("test_only") is True,
                     "Only explicitly test-only HALPE26 2D observations accepted")
    _ma_gait_require(evidence.get("role") == expected_role and expected_role in (
        "cam01_trial", "cam02_trial"), "Wrong original camera/role")
    _ma_gait_require(type(expected_source_sha256) is str and
                     _MA_SOURCE_HASH.fullmatch(expected_source_sha256) is not None and
                     evidence.get("source_sha256") == expected_source_sha256,
                     "Original registered test-video hash mismatch")
    _ma_gait_require(evidence.get("fps") == _MA_EXPECTED_FPS and
                     evidence.get("coordinates") == "unscaled source-video 2D image pixels; not meters",
                     "Only exact 30 FPS and raw 2D image coordinates accepted")
    _ma_gait_require(evidence.get("model_score_threshold") == _MA_GAIT_SCORE_THRESHOLD,
                     "Unexpected model-score threshold")
    frames = evidence.get("frames")
    if not isinstance(frames, list) or not 40 <= len(frames) <= 24000:
        raise _MAGaitEvidenceError("Video observations must be complete and bounded")
    for index, row in enumerate(frames):
        _ma_gait_require(isinstance(row, dict) and row.get("frame_index") == index
                         and type(row.get("frame_index")) is int,
                         "Missing, duplicate, or out-of-order video frame")
        _ma_gait_require(_ma_finite(row.get("time_seconds")) and
                         abs(row["time_seconds"] - index / _MA_EXPECTED_FPS) <= .0002,
                         "Frame timeline must preserve original video frame time")
        n = row.get("people_detected")
        _ma_gait_require(type(n) is int and n >= 0, "Invalid detected-person count")
        xy = row.get("xy_pixels")
        scores = row.get("confidence")
        if n == 0:
            _ma_gait_require(xy is None and scores is None,
                             "Missing person must not have invented marker coordinates")
            continue
        _ma_gait_require(isinstance(xy, list) and isinstance(scores, list) and
                         len(xy) == _MA_LANDMARKS and len(scores) == _MA_LANDMARKS,
                         "Missing HALPE26 coordinates or model scores")
        for point, score in zip(xy, scores):
            _ma_gait_require(_ma_finite(score), "Model scores must be finite; scores may exceed 1")
            if point is None:
                continue
            _ma_gait_require(isinstance(point, list) and len(point) == 2 and
                             all(_ma_finite(v) for v in point),
                             "Each observed marker must have finite 2D pixel coordinates")
    return frames


def _ma_single_person(frame):
    return frame["people_detected"] == 1 and frame["confidence"] is not None and frame["xy_pixels"] is not None


def _ma_observed(frame, index):
    if not _ma_single_person(frame):
        return False
    conf, pts = frame["confidence"], frame["xy_pixels"]
    return (conf[_MA_PELVIS_INDEX] >= _MA_GAIT_SCORE_THRESHOLD and conf[index] >= _MA_GAIT_SCORE_THRESHOLD and
            pts[_MA_PELVIS_INDEX] is not None and pts[index] is not None)


def _ma_raw_foot_signal(frames, index, height):
    values = []
    scores = []
    for f in frames:
        if _ma_observed(f, index):
            conf, pts = f["confidence"], f["xy_pixels"]
            values.append(float((pts[index][0] - pts[_MA_PELVIS_INDEX][0]) / height))
            scores.append(float(min(conf[_MA_PELVIS_INDEX], conf[index])))
        else:
            values.append(None)
            scores.append(None)
    return values, scores


def _ma_complete(values):
    observed = [v for v in values if v is not None and math.isfinite(v)]
    return observed if len(observed) == len(values) else None


def _ma_smoothed(values):
    result = [None] * len(values)
    for index in range(_MA_GAIT_SMOOTH_HALF_WINDOW, len(values)-_MA_GAIT_SMOOTH_HALF_WINDOW):
        window = _ma_complete(values[index-_MA_GAIT_SMOOTH_HALF_WINDOW:index+_MA_GAIT_SMOOTH_HALF_WINDOW+1])
        if window is not None:
            result[index] = sum(window) / len(window)
    return result


def _ma_detectable(values, i):
    return (_MA_GAIT_PROMINENCE_WINDOW <= i < len(values) - _MA_GAIT_PROMINENCE_WINDOW and
            _ma_complete(values[i-_MA_GAIT_PROMINENCE_WINDOW:i+_MA_GAIT_PROMINENCE_WINDOW+1]) is not None)


def _ma_extrema(values, kind):
    candidates = []
    size = len(values)
    for i in range(_MA_GAIT_PROMINENCE_WINDOW, size-_MA_GAIT_PROMINENCE_WINDOW):
        before = _ma_complete(values[i-_MA_GAIT_PROMINENCE_WINDOW:i])
        after = _ma_complete(values[i+1:i+_MA_GAIT_PROMINENCE_WINDOW+1])
        center = values[i]
        if before is None or after is None or center is None:
            continue
        left, right = before[-1], after[0]
        if kind == "max":
            is_turn = center > left and center >= right
            prominence = min(center - min(before), center - min(after))
        else:
            is_turn = center < left and center <= right
            prominence = min(max(before) - center, max(after) - center)
        if is_turn and prominence >= _MA_GAIT_MIN_PROMINENCE:
            candidates.append({"frame_index": i, "prominence": round(prominence, 7)})
    selected = []
    for row in sorted(candidates, key=lambda item: (-item["prominence"], item["frame_index"])):
        if all(abs(row["frame_index"] - existing["frame_index"]) >= _MA_GAIT_MIN_SPACING for existing in selected):
            selected.append(row)
    return sorted(selected, key=lambda item: item["frame_index"])


def _ma_propose_extrema(evidence, role, source_sha256, *, image_width, image_height):
    _ma_gait_require(type(image_width) is int and 80 <= image_width <= 16384 and
                     type(image_height) is int and 80 <= image_height <= 16384,
                     "Invalid original image geometry")
    frames = _ma_validate_2d_trajectories(evidence, role, source_sha256)
    names = {
        "left": {"heel": "left_heel", "big_toe": "left_big_toe"},
        "right": {"heel": "right_heel", "big_toe": "right_big_toe"},
    }
    signals = {}
    quality = {}
    candidates = []
    n = len(frames)
    support = _MA_GAIT_PROMINENCE_WINDOW + _MA_GAIT_SMOOTH_HALF_WINDOW
    single = [_ma_single_person(f) for f in frames]
    low_score = {}
    for side, points in names.items():
        for foot_point, label in points.items():
            raw, scores = _ma_raw_foot_signal(frames, _MA_GAIT_LANDMARK_INDICES[label], image_height)
            smooth = _ma_smoothed(raw)
            signals[label] = [round(v, 7) if v is not None else None for v in smooth]
            quality[label] = sum(v is not None for v in raw) / n
            low_score[label] = sum(ok and v is None for ok, v in zip(single, raw, strict=True))
            for kind in ("max", "min"):
                for result in _ma_extrema(smooth, kind):
                    index = result["frame_index"]
                    window = [s for s in scores[max(0, index-support):index+support+1] if s is not None]
                    candidates.append({
                        "id": f"{role}:{side}:{foot_point}:{kind}:{index}",
                        "role": role, "side": side, "foot_point": foot_point,
                        "extremum": kind, "event_type": "unassigned_extremum",
                        "frame_index": index, "time_seconds": round(index / _MA_EXPECTED_FPS, 6),
                        "prominence_image_height_units": result["prominence"],
                        "image_x_relative_hip_height_units": signals[label][index],
                        "mean_raw_landmark_score": scores[index],
                        "window_min_raw_landmark_score": min(window),
                        "window_min_score_margin_over_threshold": round(min(window) - _MA_GAIT_SCORE_THRESHOLD, 7),
                        "window_observed_frames": len(window),
                        "model_score_is_probability": False,
                        "method": "image-x-relative-to-hip",
                        "interpolated": False,
                    })
    candidates.sort(key=lambda row: (row["frame_index"], row["side"], row["foot_point"], row["extremum"]))
    return {
        "schema": _MA_GAIT_CANDIDATES_SCHEMA,
        "algorithm_version": _MA_GAIT_ALGORITHM_VERSION,
        "source_schema": _MA_SOURCE_SCHEMA,
        "classification": "UNVALIDATED_EVENT_CANDIDATES",
        "evidence_classification": _MA_EVIDENCE_CLASSIFICATION,
        "test_only": True, "role": role, "source_sha256": source_sha256,
        "fps": _MA_EXPECTED_FPS, "image_size": [image_width, image_height],
        "observed_frames": n, "duration_seconds": n / _MA_EXPECTED_FPS,
        "screen_forward": None, "manual_validation_status": "not_reviewed",
        "has_manually_validated_events": False,
        "frames_with_required_hip_and_both_feet": sum(
            all(_ma_observed(f, idx) for idx in (20, 21, 24, 25)) for f in frames
        ),
        "required_landmark_coverage": quality,
        "sample_exclusions": {
            "no_person_frames": sum(f["people_detected"] == 0 for f in frames),
            "ambiguous_person_frames": sum(f["people_detected"] > 1 for f in frames),
            "low_score_or_occluded_frames": low_score,
            "policy": "Frames without exactly one detected person, or below the raw-score gate, "
                      "are excluded from every signal; nothing is interpolated.",
        },
        "unsupported_metrics": _ma_unsupported_gait_metrics(),
        "event_confidence_description": (
            "window_min_raw_landmark_score is the weakest raw pelvis/landmark score over the "
            "frames supporting the smoothed prominence window; raw scores are not probabilities"
        ),
        "signal_description": (
            "strict seven-frame local average of observed heel or big-toe "
            "horizontal image displacement relative to pelvis; divided by image height"
        ),
        "signals": signals,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "limitations": [
            "No native calibration, physical scale, 3D trajectories or force-plate reference.",
            "Frame-extrema are periodic 2D foot motion, not independently observed initial contact/toe-off.",
            "Forward direction in each camera is unknown until the reviewer chooses it.",
            "Raw RTMPose scores are not probabilities; low-score gaps are not interpolated.",
            "No stride length, clinical gait cadence, diagnosis, accuracy, or patient identifiers.",
        ],
    }


def _ma_unsupported_gait_metrics():
    return [{"metric": name, "status": "UNSUPPORTED", "value": None, "reason": reason}
            for name, reason in _MA_UNSUPPORTED_GAIT_METRICS]


def _ma_orient_event_candidates(base, *, screen_forward):
    _ma_gait_require(screen_forward in ("left", "right"), "Choose visible on-screen forward direction")
    _ma_gait_require(isinstance(base, dict) and base.get("schema") == _MA_GAIT_CANDIDATES_SCHEMA and
                     base.get("test_only") is True,
                     "Invalid unvalidated extrema report")
    sign = "max" if screen_forward == "right" else "min"
    other = "min" if sign == "max" else "max"
    events = []
    for event in base.get("candidates", []):
        row = dict(event)
        row["event_type"] = (
            "candidate_initial_contact" if row["foot_point"] == "heel" and row["extremum"] == sign
            else "candidate_toe_off" if row["foot_point"] == "big_toe" and row["extremum"] == other
            else "unassigned_extremum"
        )
        events.append(row)
    return {
        **base, "screen_forward": screen_forward, "candidates": events,
        "unsupported_metrics": _ma_unsupported_gait_metrics(),
        "manual_validation_status": "not_reviewed",
        "has_manually_validated_events": False,
        "interpretation": "Operator-selected screen direction is an assumption. Gait event names are hypotheses, not measured contacts.",
    }


def _ma_make_manual_reference(base, labels, *, reviewer, confirmed):
    _ma_gait_require(isinstance(base, dict) and base.get("schema") == _MA_GAIT_CANDIDATES_SCHEMA,
                     "Unrecognized trajectory evidence")
    _ma_gait_require(isinstance(reviewer, str) and 2 <= len(reviewer.strip()) <= 90,
                     "A named operator/reviewer is required")
    _ma_gait_require(confirmed is True, "The operator must explicitly confirm observed video frames")
    _ma_gait_require(isinstance(labels, list) and 1 <= len(labels) <= 1000,
                     "Human reference requires one or more actually reviewed events")
    cleaned = []
    used = set()
    n = base["observed_frames"]
    for item in labels:
        _ma_gait_require(isinstance(item, dict), "Invalid manual event entry")
        frame, side, kind = item.get("frame_index"), item.get("side"), item.get("event_type")
        if not (type(frame) is int and 0 <= frame < n and
                side in ("left", "right") and kind in ("initial_contact", "toe_off")):
            raise _MAGaitEvidenceError("Manual events require exact source frame, side and event type")
        key = (side, kind, frame)
        _ma_gait_require(key not in used, "Duplicate manual reference event")
        used.add(key)
        cleaned.append({"frame_index": frame,
                        "time_seconds": round(frame / _MA_EXPECTED_FPS, 6),
                        "side": side, "event_type": kind})
    cleaned.sort(key=lambda e: (e["frame_index"], e["side"], e["event_type"]))
    return {
        "schema": _MA_GAIT_REFERENCE_SCHEMA, "test_only": True,
        "status": "MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH",
        "role": base["role"], "source_sha256": base["source_sha256"],
        "fps": _MA_EXPECTED_FPS, "frames": n,
        "annotation_origin": "human_observed_video_frames",
        "operator_confirmed": True, "reviewer": reviewer.strip(),
        "algorithm_events_shown_during_annotation": False,
        "clinical_accuracy_validated": False,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "labels": cleaned,
        "limitations": (
            "Human review in browser player, without frame-exact external ground truth. "
            "No instrumented gait-event or clinical accuracy validation."
        ),
    }


def _ma_reference_observable(oriented, side, kind, frame, tolerance):
    label = f"{side}_{'heel' if kind == 'initial_contact' else 'big_toe'}"
    signal = oriented.get("signals", {}).get(label)
    if not isinstance(signal, list) or len(signal) != oriented["observed_frames"]:
        raise _MAGaitEvidenceError("Oriented candidates lack the source-bound signal needed to score references")
    return any(_ma_detectable(signal, i) for i in range(frame - tolerance, frame + tolerance + 1))


def _ma_score_manual_reference(oriented, reference, *, tolerance_frames=3):
    _ma_gait_require(type(tolerance_frames) is int and 0 <= tolerance_frames <= 15,
                     "Invalid manual-event tolerance")
    _ma_gait_require(isinstance(oriented, dict) and oriented.get("schema") == _MA_GAIT_CANDIDATES_SCHEMA and
                     oriented.get("screen_forward") in ("left", "right"),
                     "Event comparison requires explicitly oriented candidate proposals")
    proposed = [p for p in oriented["candidates"]
                if p["event_type"] in ("candidate_initial_contact", "candidate_toe_off")]
    provenance = {"test_only": oriented.get("test_only") is True,
                  "evidence_classification": _MA_EVIDENCE_CLASSIFICATION}
    if reference is None:
        return {"status": "NO_MANUAL_REFERENCE", "reference_count": 0,
                "candidate_count": len(proposed), "matched_count": 0,
                "precision": None, "recall": None,
                "missed_reference_count": None, "false_candidate_count": None,
                "unscorable_reference_count": None,
                "absolute_frame_errors": [], "tolerance_frames": tolerance_frames, **provenance,
                "claim": "Manual events have not been provided; no agreement can be measured."}
    _ma_gait_require(isinstance(reference, dict) and reference.get("schema") == _MA_GAIT_REFERENCE_SCHEMA and
                     reference.get("test_only") is True and reference.get("operator_confirmed") is True and
                     reference.get("status") == "MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH" and
                     reference.get("algorithm_events_shown_during_annotation") is False and
                     reference.get("clinical_accuracy_validated") is False and
                     reference.get("annotation_origin") == "human_observed_video_frames" and
                     reference.get("source_sha256") == oriented.get("source_sha256") and
                     reference.get("role") == oriented.get("role") and
                     reference.get("fps") == _MA_EXPECTED_FPS and
                     reference.get("frames") == oriented.get("observed_frames") and
                     isinstance(reference.get("reviewer"), str) and
                     len(reference["reviewer"].strip()) >= 2,
                     "Manual reference does not belong to this exact video session")
    refs = reference.get("labels")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 1000:
        raise _MAGaitEvidenceError("Manual reference contains no bounded reviewed events")
    seen = set()
    for label in refs:
        _ma_gait_require(isinstance(label, dict) and
                         type(label.get("frame_index")) is int and
                         0 <= label["frame_index"] < oriented["observed_frames"] and
                         label.get("side") in ("left", "right") and
                         label.get("event_type") in ("initial_contact", "toe_off") and
                         _ma_finite(label.get("time_seconds")) and
                         abs(label["time_seconds"] - round(label["frame_index"] / _MA_EXPECTED_FPS, 6)) < .0001,
                         "Manual reference contains invalid source frames or event time")
        key = (label["frame_index"], label["side"], label["event_type"])
        _ma_gait_require(key not in seen, "Duplicate human reference label")
        seen.add(key)
    candidates = [(p["frame_index"], p["side"], p["event_type"].removeprefix("candidate_"))
                  for p in proposed]
    comparison = []
    for i, ref in enumerate(refs):
        for j, (frame, side, kind) in enumerate(candidates):
            if side == ref["side"] and kind == ref["event_type"]:
                error = abs(ref["frame_index"]-frame)
                if error <= tolerance_frames:
                    comparison.append((error, i, j))
    matched = {}
    matched_candidate = set()
    for error, i, j in sorted(comparison):
        if i not in matched and j not in matched_candidate:
            matched[i] = (j, error)
            matched_candidate.add(j)
    errors = [error for _, error in matched.values()]
    outcomes = []
    by_type = {}
    for i, ref in enumerate(refs):
        side, kind, frame = ref["side"], ref["event_type"], ref["frame_index"]
        if i in matched:
            outcome = "matched"
        elif _ma_reference_observable(oriented, side, kind, frame, tolerance_frames):
            outcome = "missed"
        else:
            outcome = "unscorable_unobserved_source"
        outcomes.append({"frame_index": frame, "side": side, "event_type": kind, "outcome": outcome,
                         "absolute_frame_error": matched[i][1] if i in matched else None})
        counts = by_type.setdefault(f"{side}:{kind}", {"reference": 0, "matched": 0, "missed": 0,
                                                       "unscorable": 0, "false_candidates": 0})
        counts["reference"] += 1
        counts["unscorable" if outcome.startswith("unscorable") else outcome] += 1
    false_candidates = []
    for j, (frame, side, kind) in enumerate(candidates):
        if j not in matched_candidate:
            false_candidates.append({"id": proposed[j]["id"], "frame_index": frame,
                                     "side": side, "event_type": kind})
            by_type.setdefault(f"{side}:{kind}", {"reference": 0, "matched": 0, "missed": 0,
                                                  "unscorable": 0, "false_candidates": 0})
            by_type[f"{side}:{kind}"]["false_candidates"] += 1
    return {
        "status": "EXPLORATORY_REVIEWER_AGREEMENT_ONLY",
        "reference_count": len(refs), "candidate_count": len(candidates),
        "matched_count": len(errors), "precision": len(errors)/len(candidates) if candidates else None,
        "recall": len(errors)/len(refs),
        "unmatched_reference_count": len(refs)-len(errors),
        "unmatched_candidate_count": len(candidates)-len(errors),
        "missed_reference_count": sum(o["outcome"] == "missed" for o in outcomes),
        "unscorable_reference_count": sum(o["outcome"] == "unscorable_unobserved_source" for o in outcomes),
        "false_candidate_count": len(false_candidates),
        "reference_outcomes": outcomes, "false_candidates": false_candidates,
        "by_event_type": by_type,
        "tolerance_frames": tolerance_frames, "absolute_frame_errors": sorted(errors),
        "median_absolute_error_frames": median(errors) if errors else None,
        **provenance,
        "claim": "Agreement with unvalidated human video annotations only; not instrumented ground truth or clinical accuracy.",
    }


# --- squat_events.py port ----------------------------------------------------

def _ma_squat_require(predicate, reason):
    if not predicate:
        raise _MASquatEvidenceError(reason)


def _ma_angle(hip, knee, ankle):
    ax, ay = float(hip[0]-knee[0]), float(hip[1]-knee[1])
    bx, by = float(ankle[0]-knee[0]), float(ankle[1]-knee[1])
    norm = math.hypot(ax, ay)*math.hypot(bx, by)
    if not math.isfinite(norm) or norm < 16:
        return None
    value = (ax*bx+ay*by)/norm
    return math.degrees(math.acos(max(-1., min(1., value))))


def _ma_feature(record, image_width, image_height):
    index = record["frame_index"]
    scores = record["confidence"]
    xy = record["xy_pixels"]
    result = {"frame_index": index, "time_seconds": round(index/_MA_SQUAT_FPS, 6),
              "knee_angle_image_degrees": None,
              "left_knee_image_degrees": None, "right_knee_image_degrees": None,
              "hip_y_pixels": None, "torso_length_pixels": None,
              "flexion_image_degrees": None, "hip_descent_torso_units": None,
              "phase": "unavailable", "measured": False,
              "unavailable_reason": None, "min_required_raw_score": None}
    if record["people_detected"] > 1:
        return {**result, "unavailable_reason": "ambiguous_person"}
    if record["people_detected"] != 1 or scores is None or xy is None:
        return {**result, "unavailable_reason": "no_person"}
    for idx in _MA_SQUAT_REQUIRED_INDICES:
        if scores[idx] < _MA_SQUAT_CONFIDENCE_SCORE_THRESHOLD or xy[idx] is None:
            return {**result, "unavailable_reason": "low_score_or_occluded"}
    for idx in _MA_SQUAT_REQUIRED_INDICES:
        point = xy[idx]
        if not (0 <= point[0] <= image_width and 0 <= point[1] <= image_height):
            return {**result, "unavailable_reason": "outside_image"}
    left = _ma_angle(xy[11], xy[13], xy[15])
    right = _ma_angle(xy[12], xy[14], xy[16])
    if left is None or right is None:
        return {**result, "unavailable_reason": "degenerate_geometry"}
    hips_y = (xy[11][1]+xy[12][1])/2
    shoulder_y = (xy[5][1]+xy[6][1])/2
    torso_len = math.hypot(
        (xy[5][0]+xy[6][0]-xy[11][0]-xy[12][0])/2,
        shoulder_y-hips_y,
    )
    if not 12 <= torso_len <= max(image_width, image_height):
        return {**result, "unavailable_reason": "degenerate_geometry"}
    result.update(
        min_required_raw_score=float(min(scores[idx] for idx in _MA_SQUAT_REQUIRED_INDICES)),
        knee_angle_image_degrees=round((left+right)/2, 5),
        left_knee_image_degrees=round(left, 5),
        right_knee_image_degrees=round(right, 5),
        hip_y_pixels=float(hips_y), torso_length_pixels=float(torso_len),
        measured=True,
    )
    return result


def _ma_baseline(features):
    early = [f for f in features[:_MA_SQUAT_BASELINE_FRAMES] if f["measured"]]
    _ma_squat_require(len(early) >= _MA_SQUAT_BASELINE_FRAMES-2,
                      "Stable standing baseline missing: >=18 usable frames needed at start")
    angles = [f["knee_angle_image_degrees"] for f in early]
    hips = [f["hip_y_pixels"] for f in early]
    torso = [f["torso_length_pixels"] for f in early]
    baseline_angle = median(angles)
    torso_scale = median(torso)
    _ma_squat_require(145 <= baseline_angle <= 185,
                      "Standing baseline knee angle not extended enough for squat image analysis")
    _ma_squat_require(max(angles)-min(angles) <= 10,
                      "Standing baseline unstable: initial pose varies excessively")
    _ma_squat_require((max(hips)-min(hips))/torso_scale <= .15,
                      "Standing baseline unstable: pelvis moved during baseline")
    return baseline_angle, median(hips), torso_scale


def _ma_median_without_interpolation(values):
    smooth = [None]*len(values)
    for i in range(_MA_SQUAT_SMOOTH_HALF_WINDOW, len(values)-_MA_SQUAT_SMOOTH_HALF_WINDOW):
        neighborhood = values[i-_MA_SQUAT_SMOOTH_HALF_WINDOW:i+_MA_SQUAT_SMOOTH_HALF_WINDOW+1]
        if all(v is not None and math.isfinite(v) for v in neighborhood):
            smooth[i] = float(median(neighborhood))
    return smooth


def _ma_analyze_squats(evidence, role, source_sha256, *,
                       camera_view, activity_confirmed, image_width, image_height):
    _ma_squat_require(activity_confirmed is True, "Squat activity must be explicitly confirmed by operator")
    _ma_squat_require(camera_view == "side",
                      "Conservative 2D squat phase counting requires an operator-identified side view")
    _ma_squat_require(type(image_width) is int and 320 <= image_width <= 8192 and
                      type(image_height) is int and 240 <= image_height <= 8192,
                      "Invalid source video geometry")
    try:
        frames = _ma_validate_2d_trajectories(evidence, role, source_sha256)
    except _MAGaitEvidenceError as exc:
        raise _MASquatEvidenceError("Invalid source-bound 2D observation: "+str(exc)) from exc
    _ma_squat_require(len(frames) >= 60, "At least two seconds of full source observations required")
    features = [_ma_feature(row, image_width, image_height) for row in frames]
    baseline_knee, baseline_hip, torso_scale = _ma_baseline(features)
    raw_flex = []
    raw_drop = []
    for feature in features:
        if feature["measured"]:
            raw_flex.append(baseline_knee-feature["knee_angle_image_degrees"])
            raw_drop.append((feature["hip_y_pixels"]-baseline_hip)/torso_scale)
        else:
            raw_flex.append(None)
            raw_drop.append(None)
    flex_smooth = _ma_median_without_interpolation(raw_flex)
    hip_smooth = _ma_median_without_interpolation(raw_drop)
    for i, feature in enumerate(features):
        if flex_smooth[i] is not None and hip_smooth[i] is not None:
            feature["flexion_image_degrees"] = round(flex_smooth[i], 5)
            feature["hip_descent_torso_units"] = round(hip_smooth[i], 6)
            feature["phase"] = "standing"
        else:
            feature["phase"] = "unavailable"

    phase = "standing"
    entry = None
    bottom_streak = 0
    peak_flex = -float("inf")
    peak_drop = -float("inf")
    peak_frame = None
    reps = []
    incomplete = 0
    for i, feature in enumerate(features):
        flex = flex_smooth[i]
        drop = hip_smooth[i]
        if flex is None or drop is None:
            if phase != "standing":
                incomplete += 1
            phase = "standing"
            entry = None
            bottom_streak = 0
            continue
        if phase == "standing":
            if flex >= _MA_SQUAT_BEGIN_FLEX_DEGREES and drop >= _MA_SQUAT_BEGIN_HIP_DROP:
                phase = "descending"
                entry = i
                peak_flex = flex
                peak_drop = drop
                peak_frame = i
                bottom_streak = 0
        elif phase in ("descending", "bottom", "ascending"):
            if flex > peak_flex or drop > peak_drop:
                peak_flex = max(peak_flex, flex)
                peak_drop = max(peak_drop, drop)
                peak_frame = i
            if i-entry > _MA_SQUAT_MAX_REP_DURATION:
                incomplete += 1
                phase = "standing"
                entry = None
                bottom_streak = 0
            elif phase == "descending":
                if flex >= _MA_SQUAT_BOTTOM_FLEX_DEGREES and drop >= _MA_SQUAT_BOTTOM_HIP_DROP:
                    bottom_streak += 1
                    if bottom_streak >= 3:
                        phase = "bottom"
                else:
                    bottom_streak = 0
                if flex <= _MA_SQUAT_END_FLEX_DEGREES and drop <= _MA_SQUAT_END_HIP_DROP:
                    incomplete += 1
                    phase = "standing"
                    entry = None
                    bottom_streak = 0
            elif phase == "bottom":
                if flex <= peak_flex-12 and drop <= peak_drop-.08:
                    phase = "ascending"
            elif phase == "ascending":
                if flex <= _MA_SQUAT_END_FLEX_DEGREES and drop <= _MA_SQUAT_END_HIP_DROP:
                    if (i-entry >= _MA_SQUAT_MIN_REP_DURATION and peak_flex >= _MA_SQUAT_BOTTOM_FLEX_DEGREES
                            and peak_drop >= _MA_SQUAT_BOTTOM_HIP_DROP):
                        span = features[entry:i+1]
                        observed = [f["min_required_raw_score"] for f in span if f["measured"]]
                        reps.append({
                            "number": len(reps)+1,
                            "start_frame": entry, "bottom_frame": peak_frame, "end_frame": i,
                            "start_seconds": round(entry/_MA_SQUAT_FPS, 6),
                            "bottom_seconds": round(peak_frame/_MA_SQUAT_FPS, 6),
                            "end_seconds": round(i/_MA_SQUAT_FPS, 6),
                            "duration_seconds": round((i-entry)/_MA_SQUAT_FPS, 6),
                            "peak_estimated_knee_flexion_degrees": round(peak_flex, 3),
                            "peak_hip_descent_torso_units": round(peak_drop, 4),
                            "classification": "2d_candidate_requires_human_review",
                            "min_required_landmark_raw_score": min(observed),
                            "unmeasured_frames_within_rep": len(span)-len(observed),
                            "model_score_is_probability": False,
                        })
                    else:
                        incomplete += 1
                    phase = "standing"
                    entry = None
                    bottom_streak = 0
        feature["phase"] = phase

    if phase != "standing":
        incomplete += 1
    valid = sum(bool(feature["measured"]) for feature in features)
    smoothed = sum(feature["flexion_image_degrees"] is not None for feature in features)
    return {
        "schema": _MA_SQUAT_CANDIDATES_SCHEMA,
        "algorithm_version": _MA_SQUAT_ALGORITHM_VERSION,
        "classification": "UNVALIDATED_2D_SQUAT_CANDIDATES",
        "evidence_classification": _MA_EVIDENCE_CLASSIFICATION,
        "status": "CANDIDATES_PENDING_HUMAN_REVIEW" if reps else "NO_SQUAT_CANDIDATES",
        "role": role, "source_sha256": source_sha256, "test_only": True,
        "activity_assumption": "operator_confirmed_squat",
        "camera_view_assumption": camera_view,
        "observed_frames": len(frames), "fps": _MA_SQUAT_FPS, "image_size": [image_width, image_height],
        "candidate_repetition_count": len(reps),
        "repetitions": reps, "incomplete_attempts": incomplete,
        "baseline": {
            "first_frames_required": _MA_SQUAT_BASELINE_FRAMES,
            "standing_knee_angle_image_degrees": round(baseline_knee, 5),
            "standing_hip_y_pixels": round(baseline_hip, 5),
            "standing_torso_scale_pixels": round(torso_scale, 5),
        },
        "quality": {
            "complete_required_pose_frames": valid,
            "missing_required_pose_frames": len(frames)-valid,
            "usable_smoothed_frames": smoothed,
            "usable_smoothed_fraction": smoothed/len(frames),
            "exclusion_reasons": {reason: sum(f["unavailable_reason"] == reason for f in features)
                                  for reason in _MA_SQUAT_EXCLUSION_REASONS},
        },
        "unsupported_metrics": [
            {"metric": name, "status": "UNSUPPORTED", "value": None, "reason": reason}
            for name, reason in _MA_UNSUPPORTED_SQUAT_METRICS
        ],
        "count_is_clinically_validated": False,
        "score_interpretation": "Raw model score, not a probability; .43 is a heuristic threshold only.",
        "knee_angle_interpretation": "2D image-plane joint-angle estimate, NOT true sagittal-plane physical ROM.",
        "hip_depth_interpretation": "Normalized pelvis image displacement relative to standing torso pixels, NOT meters.",
        "frame_features": features,
        "phases_present": sorted({f["phase"] for f in features}),
        "limitations": [
            "Only operator-confirmed side-view squat footage; no automatic exercise recognition.",
            "Full valid first-standing baseline and bilateral keypoints required; missing samples abort active reps.",
            "No 3D calibration, anatomy/kinematic ground truth, diagnosis or treatment recommendation.",
            "Manual event review needed before accepting any repetition count.",
        ],
    }


def _ma_make_manual_rep_reference(result, labels, *, reviewer, confirmed):
    _ma_squat_require(isinstance(result, dict) and result.get("schema") == _MA_SQUAT_CANDIDATES_SCHEMA
                      and result.get("test_only") is True,
                      "Invalid 2D squat detector result")
    _ma_squat_require(isinstance(reviewer, str) and 2 <= len(reviewer.strip()) <= 90,
                      "Manually observed repetitions require named reviewer")
    _ma_squat_require(confirmed is True, "Explicit manual video-frame review confirmation required")
    _ma_squat_require(isinstance(labels, list) and 1 <= len(labels) <= 500,
                      "Manual reference requires actual reviewed squat repetitions")
    cleaned = []
    known = set()
    for label in labels:
        _ma_squat_require(isinstance(label, dict), "Invalid manually observed squat")
        start, bottom, end = (label.get(k) for k in ("start_frame", "bottom_frame", "end_frame"))
        _ma_squat_require(all(type(x) is int for x in (start, bottom, end)) and
                          0 <= start < bottom < end < result["observed_frames"],
                          "Manual squat sequence must be start < bottom < end within source frames")
        key = (start, bottom, end)
        _ma_squat_require(key not in known, "Duplicate manual squat reference")
        known.add(key)
        cleaned.append({"start_frame": start, "bottom_frame": bottom, "end_frame": end})
    cleaned.sort(key=lambda x: x["start_frame"])
    for earlier, later in pairwise(cleaned):
        _ma_squat_require(earlier["end_frame"] < later["start_frame"],
                          "Manually reviewed squat repetitions cannot overlap")
    return {
        "schema": _MA_SQUAT_REFERENCE_SCHEMA,
        "status": "HUMAN_OBSERVED_UNINSTRUMENTED_REFERENCE",
        "test_only": True, "source_sha256": result["source_sha256"],
        "role": result["role"], "frames": result["observed_frames"],
        "algorithm_version": result["algorithm_version"],
        "reviewer": reviewer.strip(), "operator_confirmed": True,
        "annotation_origin": "human_video_frame_review",
        "clinical_accuracy_validated": False,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "repetitions": cleaned,
    }


def _ma_compare_manual_reps(result, reference, tolerance_frames=3):
    _ma_squat_require(type(tolerance_frames) is int and 0 <= tolerance_frames <= 15,
                      "Manual timing tolerance is invalid")
    _ma_squat_require(isinstance(result, dict) and result.get("schema") == _MA_SQUAT_CANDIDATES_SCHEMA
                      and result.get("test_only") is True,
                      "Unrecognized 2D squat candidate report")
    candidates = result["repetitions"]
    provenance = {"test_only": True, "evidence_classification": _MA_EVIDENCE_CLASSIFICATION}
    if reference is None:
        return {
            "status": "NO_HUMAN_REFERENCE", "reference_count": 0,
            "candidate_count": len(candidates), "matched_count": 0,
            "precision": None, "recall": None,
            "missed_reference_count": None, "false_candidate_count": None,
            "unscorable_reference_count": None,
            "incomplete_attempts": result.get("incomplete_attempts"),
            "clinical_accuracy_validated": False, **provenance,
        }
    _ma_squat_require(isinstance(reference, dict) and
                      reference.get("schema") == _MA_SQUAT_REFERENCE_SCHEMA and
                      reference.get("status") == "HUMAN_OBSERVED_UNINSTRUMENTED_REFERENCE" and
                      reference.get("test_only") is True and
                      reference.get("role") == result["role"] and
                      reference.get("source_sha256") == result["source_sha256"] and
                      reference.get("algorithm_version") == result["algorithm_version"] and
                      reference.get("frames") == result["observed_frames"] and
                      reference.get("annotation_origin") == "human_video_frame_review" and
                      reference.get("operator_confirmed") is True and
                      reference.get("clinical_accuracy_validated") is False and
                      isinstance(reference.get("reviewer"), str) and len(reference["reviewer"].strip()) >= 2,
                      "Manual reference belongs to a different, unconfirmed or falsely validated recording")
    refs = reference.get("repetitions")
    _ma_squat_require(isinstance(refs, list) and 1 <= len(refs) <= 500, "Invalid human reference records")
    features = result.get("frame_features")
    _ma_squat_require(isinstance(features, list) and len(features) == result["observed_frames"],
                      "Squat result lacks the per-frame source observations needed for scoring")
    observed = set()
    for mark in refs:
        _ma_squat_require(isinstance(mark, dict), "Malformed human rep")
        start, bottom, end = (mark.get(k) for k in ("start_frame", "bottom_frame", "end_frame"))
        _ma_squat_require(all(type(n) is int for n in (start, bottom, end)) and
                          0 <= start < bottom < end < result["observed_frames"] and
                          (start, bottom, end) not in observed,
                          "Human reference frames invalid or duplicated")
        observed.add((start, bottom, end))
    ordered = sorted(refs, key=lambda mark: mark["start_frame"])
    for first, second in pairwise(ordered):
        _ma_squat_require(first["end_frame"] < second["start_frame"],
                          "Manual observed squat repetitions overlap; cannot score this reference")
    options = []
    for i, ref in enumerate(refs):
        for j, pred in enumerate(candidates):
            dist = abs(ref["bottom_frame"]-pred["bottom_frame"])
            if dist <= tolerance_frames:
                options.append((dist, i, j))
    matched = {}
    used_p = set()
    for dist, i, j in sorted(options):
        if i in matched or j in used_p:
            continue
        matched[i] = j
        used_p.add(j)
    pairs = []
    outcomes = []
    for i, ref in enumerate(refs):
        if i in matched:
            pred = candidates[matched[i]]
            start_error = abs(pred["start_frame"]-ref["start_frame"])
            end_error = abs(pred["end_frame"]-ref["end_frame"])
            pairs.append({
                "reference_index": i, "candidate_number": pred["number"],
                "bottom_frame_error": abs(pred["bottom_frame"]-ref["bottom_frame"]),
                "start_frame_error": start_error, "end_frame_error": end_error,
                "phase_boundaries_within_tolerance": start_error <= tolerance_frames and end_error <= tolerance_frames,
            })
            outcome = "matched"
        elif all(f["measured"] for f in features[ref["start_frame"]:ref["end_frame"]+1]):
            outcome = "missed"
        else:
            outcome = "unscorable_unobserved_source"
        outcomes.append({**{k: ref[k] for k in ("start_frame", "bottom_frame", "end_frame")}, "outcome": outcome})
    errors = [pair["bottom_frame_error"] for pair in pairs]
    false_candidates = [pred["number"] for j, pred in enumerate(candidates) if j not in used_p]
    return {
        "status": "EXPLORATORY_HUMAN_AGREEMENT_ONLY",
        "reference_count": len(refs), "candidate_count": len(candidates),
        "matched_count": len(errors),
        "precision": len(errors)/len(candidates) if candidates else None,
        "recall": len(errors)/len(refs),
        "absolute_bottom_frame_errors": errors,
        "matched_pairs": pairs, "reference_outcomes": outcomes,
        "missed_reference_count": sum(o["outcome"] == "missed" for o in outcomes),
        "unscorable_reference_count": sum(o["outcome"] == "unscorable_unobserved_source" for o in outcomes),
        "false_candidate_count": len(false_candidates), "false_candidate_numbers": false_candidates,
        "phase_boundary_disagreement_count": sum(not p["phase_boundaries_within_tolerance"] for p in pairs),
        "incomplete_attempts": result.get("incomplete_attempts"),
        "tolerance_frames": tolerance_frames,
        "clinical_accuracy_validated": False, **provenance,
        "interpretation": "Manual video annotation agreement, not instrumented or clinical squat accuracy.",
    }


# --- manual_assessment.py / manual_assessment_entry.py dispatch ---------------

def _ma_require(condition, message):
    if not condition:
        _ma_fail(message)


def _ma_arithmetic(trajectory, candidates, reference, source_sha256, tolerance_frames):
    # Order and gates follow manual_assessment._prepare plus the stricter
    # manual_assessment_entry._input_sets gates every published entry also passed.
    _ma_require(type(tolerance_frames) is int and 0 <= tolerance_frames <= 15,
                "explicit frame tolerance is invalid")
    _ma_require(isinstance(trajectory, dict) and isinstance(candidates, dict) and isinstance(reference, dict),
                "trajectory, candidates and reference must be JSON objects")
    _ma_require(type(source_sha256) is str and _MA_SOURCE_HASH.fullmatch(source_sha256) is not None,
                "independent source digest is invalid")
    role = candidates.get("role")
    _ma_require(role in _MA_TRIAL_ROLES, "select an actual registered trial camera role")
    _ma_require(candidates.get("source_sha256") == source_sha256, "selected capture hash differs from candidates")
    _ma_require(trajectory.get("source_sha256") == source_sha256 and trajectory.get("role") == role,
                "trajectory source identity differs from the selected capture")
    image_size = candidates.get("image_size")
    _ma_require(isinstance(image_size, list) and len(image_size) == 2
                and all(type(n) is int and 80 <= n <= 16384 for n in image_size),
                "explicit source image size is required")
    if candidates.get("schema") == _MA_GAIT_CANDIDATES_SCHEMA:
        kind = "gait"
        reproduced = _ma_orient_event_candidates(_ma_propose_extrema(
            trajectory, role, source_sha256, image_width=image_size[0], image_height=image_size[1],
        ), screen_forward=candidates.get("screen_forward"))
        score = _ma_score_manual_reference(reproduced, reference, tolerance_frames=tolerance_frames)
    elif candidates.get("schema") == _MA_SQUAT_CANDIDATES_SCHEMA:
        kind = "squat"
        _ma_require(candidates.get("activity_assumption") == "operator_confirmed_squat"
                    and candidates.get("camera_view_assumption") == "side",
                    "explicit squat/view assumptions required")
        reproduced = _ma_analyze_squats(
            trajectory, role, source_sha256, camera_view="side", activity_confirmed=True,
            image_width=image_size[0], image_height=image_size[1],
        )
        score = _ma_compare_manual_reps(reproduced, reference, tolerance_frames=tolerance_frames)
    else:
        _ma_fail("unsupported candidate schema")
    _ma_require(_ma_canonical(reproduced) == _ma_canonical(candidates),
                "candidates do not reproduce from the bound trajectory")
    _ma_require(type(candidates.get("observed_frames")) is int, "candidate frame count is invalid")
    # Implied by exact reproduction; restated so a future producer change cannot pass silently.
    _ma_require(candidates.get("test_only") is True
                and candidates.get("evidence_classification") == _MA_EVIDENCE_CLASSIFICATION,
                "candidates are not TEST_ONLY generated evidence")
    if kind == "gait":
        _ma_require(candidates.get("screen_forward") in ("left", "right")
                    and candidates.get("manual_validation_status") == "not_reviewed"
                    and candidates.get("has_manually_validated_events") is False,
                    "gait candidate assumptions or validation literals differ")
        _ma_require(score.get("status") == "EXPLORATORY_REVIEWER_AGREEMENT_ONLY",
                    "gait agreement status differs")
    else:
        _ma_require(candidates.get("count_is_clinically_validated") is False,
                    "squat candidate validation literal differs")
        _ma_require(score.get("status") == "EXPLORATORY_HUMAN_AGREEMENT_ONLY"
                    and score.get("clinical_accuracy_validated") is False,
                    "squat agreement status differs")
    _ma_require(score.get("test_only") is True
                and score.get("evidence_classification") == _MA_EVIDENCE_CLASSIFICATION
                and score.get("tolerance_frames") == tolerance_frames,
                "score provenance differs")
    return kind, score


def _offline_manual_arithmetic(trajectory, candidates, reference, *, source_sha256, tolerance_frames):
    """Recompute candidates and agreement exactly as the producer; (kind, score) or ValueError."""
    try:
        kind, score = _ma_arithmetic(trajectory, candidates, reference, source_sha256, tolerance_frames)
        _ma_canonical(score)
        return kind, score
    except ValueError:
        raise
    except (TypeError, KeyError, IndexError, AttributeError, ArithmeticError, RecursionError) as error:
        raise _MAManualArithmeticError("MANUAL_ARITHMETIC_INVALID: malformed evidence") from error


def _ma_reference(candidates, reviewer, labels, annotation_origin):
    # Request-level gates of manual_assessment_entry._request that apply to these fields.
    _ma_require(isinstance(reviewer, str) and 2 <= len(reviewer.strip()) <= 90
                and reviewer == reviewer.strip() and not any(ord(char) < 32 for char in reviewer),
                "reviewer declaration is invalid")
    _ma_require(annotation_origin == _MA_REQUEST_ANNOTATION_ORIGIN, "annotation origin declaration is invalid")
    _ma_require(isinstance(labels, list) and 1 <= len(labels) <= 256, "labels must be 1..256 declared entries")
    # The producer replays the request through canonical JSON before use.
    labels = json.loads(_ma_canonical(labels))
    _ma_require(isinstance(candidates, dict), "candidates must be a JSON object")
    if candidates.get("schema") == _MA_GAIT_CANDIDATES_SCHEMA:
        kind = "gait"
    elif candidates.get("schema") == _MA_SQUAT_CANDIDATES_SCHEMA:
        kind = "squat"
    else:
        _ma_fail("unsupported candidate schema")
    # manual_assessment_entry._reference
    fields = ({"frame_index", "side", "event_type"} if kind == "gait"
              else {"start_frame", "bottom_frame", "end_frame"})
    _ma_require(not (len(labels) > (256 if kind == "gait" else 128) or any(
        not isinstance(label, dict) or set(label) != fields for label in labels)),
        "label fields are invalid")
    if kind == "gait":
        return _ma_make_manual_reference(candidates, labels, reviewer=reviewer, confirmed=True)
    return _ma_make_manual_rep_reference(candidates, labels, reviewer=reviewer, confirmed=True)


def _offline_manual_reference(candidates, *, reviewer, labels, annotation_origin):
    """Rebuild the producer reference from declared request fields; compare all but recorded_at_utc."""
    try:
        reference = _ma_reference(candidates, reviewer, labels, annotation_origin)
        _ma_canonical(reference)
        return reference
    except ValueError:
        raise
    except (TypeError, KeyError, IndexError, AttributeError, ArithmeticError, RecursionError) as error:
        raise _MAManualArithmeticError("MANUAL_ARITHMETIC_INVALID: malformed evidence") from error


def _offline_manual_recorded_at(value):
    """Validate the one excluded producer field: datetime.now(UTC).isoformat()."""
    if not isinstance(value, str) or _MA_RECORDED_AT.fullmatch(value) is None:
        _ma_fail("reference timestamp must be producer UTC isoformat")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise _MAManualArithmeticError("MANUAL_ARITHMETIC_INVALID: reference timestamp is not a real time") from error
    _ma_require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0
                and parsed.isoformat() == value, "reference timestamp must be producer UTC isoformat")
    return value


MANUAL_CONTEXT_INPUTS = {"session": "session.json", "config": "Config.toml", "run": "run.json",
                         "preflight": "preflight.json", "normalization": "normalization.json"}
MANUAL_CLASSIFICATION = "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION"
MANUAL_LIMITATIONS = (
    "TEST_ONLY source-byte association and reproducible stored arithmetic only. "
    "Reviewer, confirmation and blinding fields are declarations, not authenticated identity. "
    "No proof of native trajectory derivation, independent annotation, physical accuracy or clinical validity."
)


def _offline_take_journals(archive, members, digests, sid):
    """Validate historical take intent/terminal bindings; never authorize current paths."""
    prefix = f"sessions/{sid}/"
    inventory = {path[len(prefix):]: value for path, value in digests.items() if path.startswith(prefix)}

    def refuse(kind, message):
        raise VerifyError("REPORT_TAKE_JOURNAL_" + kind, f"{sid}: {message}", "report.lineage")

    def sha(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    def identifier(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None

    def record(relative):
        info = inventory.get(relative)
        if info is None or type(info["bytes"]) is not int or not 0 < info["bytes"] <= 64 * 1024:
            refuse("UNKNOWN", "missing or oversized take record")
        try:
            raw = archive.read(members[prefix + relative])
            if len(raw) != info["bytes"]:
                refuse("IDENTITY", "take record byte count differs")
            value = strict_json_loads(raw.decode("utf-8"))
        except VerifyError:
            raise
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
            raise VerifyError("REPORT_TAKE_JOURNAL_UNKNOWN", f"{sid}: invalid take record encoding",
                              "report.lineage") from error
        if not isinstance(value, dict):
            refuse("UNKNOWN", "take record object required")
        return value

    def marker(value):
        if (set(value) != {"schema", "transaction_id", "intent_sha256"}
                or value["schema"] != "kinelab.take-acceptance-lock.v1"
                or not identifier(value["transaction_id"]) or not sha(value["intent_sha256"])):
            refuse("UNKNOWN", "invalid take marker")

    transactions, replacements = {}, []
    active_path = "takes/accept.lock"
    for relative in inventory:
        parts = relative.split("/")
        if parts[0].casefold() == "raw":
            replacement = any(part.casefold().endswith(".replacement") for part in parts[1:])
            if replacement:
                if parts[0] != "raw" or len(parts) != 2 or not parts[1].endswith(".replacement"):
                    refuse("UNKNOWN", "noncanonical or nested take replacement")
                replacements.append(relative)
        if parts[0].casefold() != "takes":
            continue
        if parts[0] != "takes" or len(parts) < 2:
            refuse("UNKNOWN", "noncanonical take path")
        if parts[1].casefold() == "accept.lock":
            if relative != active_path:
                refuse("UNKNOWN", "noncanonical active take marker")
        elif parts[1].casefold() == "acceptance":
            if parts[1] != "acceptance" or len(parts) < 4 or not identifier(parts[2]):
                refuse("UNKNOWN", "noncanonical take journal path")
            transactions.setdefault(parts[2], set()).add("/".join(parts[3:]))

    active = record(active_path) if active_path in inventory else None
    if active is not None:
        marker(active)
    pending, pending_replacements = [], set()
    intent_fields = {"schema", "transaction_id", "session_id", "role", "staged_name", "staged_sha256",
                     "staged_bytes", "prior_sha256", "prior_bytes"}
    terminal_fields = {"schema", "intent_sha256", "session_id", "transaction_id", "role", "outcome",
                       "canonical_sha256", "prior_sha256", "archives_retained", "artifacts_quarantined",
                       "native_run_passed", "clinical_validation"}
    for transaction_id, names in sorted(transactions.items()):
        directory = f"takes/acceptance/{transaction_id}/"
        allowed = {"intent.json", "commit.json", "recovery.json", "accept.lock.archived"}
        if any(name not in allowed and not name.startswith("quarantine/") for name in names):
            refuse("UNKNOWN", "undeclared take journal member")
        intent_path = directory + "intent.json"
        intent = record(intent_path)
        if (set(intent) != intent_fields or intent["schema"] != "kinelab.take-acceptance.v1"
                or intent["transaction_id"] != transaction_id or intent["session_id"] != sid
                or intent["role"] not in ROLES):
            refuse("UNKNOWN", "invalid take intent identity")
        staged_name = intent["staged_name"]
        if (not isinstance(staged_name, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.mp4", staged_name) is None
                or staged_name.split(".")[0].upper() in WINDOWS_RESERVED
                or not sha(intent["staged_sha256"]) or type(intent["staged_bytes"]) is not int
                or intent["staged_bytes"] <= 0):
            refuse("UNKNOWN", "invalid selected take identity")
        prior, size = intent["prior_sha256"], intent["prior_bytes"]
        if ((prior is None) != (size is None)
                or (prior is not None and (not sha(prior) or type(size) is not int or size < 0))):
            refuse("UNKNOWN", "invalid prior take identity")
        intent_digest = inventory[intent_path]["sha256"]
        expected_marker = {"schema": "kinelab.take-acceptance-lock.v1", "transaction_id": transaction_id,
                           "intent_sha256": intent_digest}
        active_here = active is not None and active["transaction_id"] == transaction_id
        if active_here and active != expected_marker:
            refuse("IDENTITY", "active take marker differs from immutable intent")
        terminals = [name for name in ("commit.json", "recovery.json") if name in names]
        if len(terminals) > 1:
            refuse("UNKNOWN", "contradictory take terminal receipts")
        terminal = record(directory + terminals[0]) if terminals else None
        quarantine_path = directory + "quarantine/." + intent["role"] + "-" + transaction_id + ".replacement"
        physical_quarantine = {directory + name for name in names if name.startswith("quarantine/")}
        if terminal is not None:
            expected_schema = "kinelab.take-acceptance-" + ("commit" if terminals[0] == "commit.json" else "recovery") + ".v1"
            if (set(terminal) != terminal_fields or terminal["schema"] != expected_schema
                    or terminal["outcome"] not in ("previous-preserved", "selected-verified")
                    or terminal["archives_retained"] is not True or terminal["native_run_passed"] is not False
                    or terminal["clinical_validation"] != "UNVERIFIED"):
                refuse("UNKNOWN", "invalid take terminal contract")
            if (any(terminal[key] != intent[key] for key in ("session_id", "transaction_id", "role", "prior_sha256"))
                    or terminal["intent_sha256"] != intent_digest):
                refuse("IDENTITY", "take terminal differs from immutable intent")
            expected_digest = intent["staged_sha256"] if terminal["outcome"] == "selected-verified" else prior
            if (terminal["canonical_sha256"] != expected_digest
                    or (terminals[0] == "commit.json" and terminal["outcome"] != "selected-verified")):
                refuse("IDENTITY", "take terminal outcome contradicts intent")
            quarantined = terminal["artifacts_quarantined"]
            if not isinstance(quarantined, list) or quarantined not in ([], [quarantine_path]):
                refuse("UNKNOWN", "invalid take quarantine declaration")
            declared = set(quarantined)
            if physical_quarantine - declared:
                refuse("UNKNOWN", "undeclared physical take quarantine member")
            if declared - physical_quarantine:
                refuse("IDENTITY", "declared take quarantine member missing")
        else:
            if physical_quarantine - {quarantine_path}:
                refuse("UNKNOWN", "undeclared unfinished take quarantine member")
        for path in physical_quarantine:
            content = inventory[path]
            if content["sha256"] != intent["staged_sha256"] or content["bytes"] != intent["staged_bytes"]:
                refuse("IDENTITY", "quarantine bytes differ from selected take")
        retired_path = directory + "accept.lock.archived"
        if retired_path in inventory:
            retired = record(retired_path)
            marker(retired)
            if terminal is None:
                refuse("UNKNOWN", "retired take marker has no terminal receipt")
            if retired != expected_marker:
                refuse("IDENTITY", "retired take marker differs from immutable intent")
        elif terminal is not None and not active_here:
            refuse("UNKNOWN", "terminal take receipt lacks retired marker")
        if active_here or terminal is None:
            pending.append(transaction_id)
            pending_replacements.add("raw/." + intent["role"] + "-" + transaction_id + ".replacement")
    if active is not None and active["transaction_id"] not in transactions:
        refuse("UNKNOWN", "active take marker has no immutable intent")
    if len(pending) > 1:
        refuse("UNKNOWN", "multiple unfinished take transactions")
    if set(replacements) - pending_replacements:
        refuse("UNKNOWN", "unbound take replacement")
    if pending:
        refuse("PENDING", "unfinished take acceptance requires explicit operator recovery")



def _offline_generated_provenance(archive, members, digests, sid, session):
    """Independent demo declaration consistency; never physical observation proof."""
    if session.get("kind") == "real":
        return
    if session.get("kind") != "demo" or not sid.startswith("TEST_ONLY-"):
        raise ValueError("manual generated-demo identity required")
    prefix = f"sessions/{sid}/"
    relative = "generated-fixture-provenance.json"
    value = _report_document(archive, members, digests, prefix + relative, 16384)
    producers = value.get("producers_sha256")
    expected = {
        "schema": "kinelab.generated-assessment-fixture.v1", "session_id": sid, "kind": "demo",
        "test_only": True, "source_video_decoded": False, "human_observation": "NOT_PERFORMED",
        "native_compute": "NOT_PERFORMED", "physical_accuracy": "UNVERIFIED",
        "clinical_validation": "UNVERIFIED",
        "captures_sha256": {role: source["sha256"] for role, source in session["captures"].items()},
        "producers_sha256": producers,
    }
    if (value != expected or value.get("test_only") is not True
            or value.get("source_video_decoded") is not False or not isinstance(producers, dict)
            or set(producers) != {"tools/verify_report_browser.py", "tests/native_evidence_fixture.py",
                                 "tests/test_manual_assessment_provenance.py", "tests/test_squat_events.py"}
            or any(not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None
                   for item in producers.values())):
        raise ValueError("manual generated-demo declaration invalid")
    config_path = prefix + "Config.toml"
    if digests.get(config_path, {}).get("bytes", 4 * 1024 * 1024 + 1) > 4 * 1024 * 1024:
        raise ValueError("manual generated-demo config exceeds read limit")
    raw = archive.read(members[config_path])
    marker = b"# kinelab-generated-provenance-sha256="
    digest = digests[prefix + relative]["sha256"].encode("ascii")
    if [line for line in raw.splitlines() if line.startswith(marker)] != [marker + digest]:
        raise ValueError("manual generated-demo declaration binding differs")


_PROBE_STDOUT_LIMIT = 64 * 1024 * 1024
_PROBE_STDERR_LIMIT = 64 * 1024
_PROBE_TIMEOUT_S = 120


def _offline_probe_output(command):
    """Bound decoder wall time and both pipes before parsing any output."""
    def limited(stream, cap):
        data = stream.read(cap + 1)
        if len(data) > cap:
            raise ValueError("VIDEO_TIMING_INVALID: decoder output limit exceeded")
        return data

    deadline = time.monotonic() + _PROBE_TIMEOUT_S
    with (subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False) as process,
          ThreadPoolExecutor(max_workers=2) as pool):
        readers = [pool.submit(limited, process.stdout, _PROBE_STDOUT_LIMIT),
                   pool.submit(limited, process.stderr, _PROBE_STDERR_LIMIT)]
        try:
            done, pending = wait(readers, timeout=_PROBE_TIMEOUT_S, return_when=FIRST_EXCEPTION)
            for future in done:
                future.result()
            if pending:
                raise ValueError("VIDEO_TIMING_INVALID: decoder timed out")
            code = process.wait(timeout=max(.001, deadline - time.monotonic()))
            stdout, stderr = (future.result() for future in readers)
            if code != 0 or stderr.strip():
                raise ValueError("VIDEO_TIMING_INVALID: decoder failed or reported an error")
            return stdout.decode("utf-8")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def _offline_decoded_pose(archive, members, digests, prefix, identity, run, outputs, pose_stage):
    """Independently decode pinned normalized archive bytes; never trust a rehashed count."""
    policy = {"schema": "kinelab.native-frame-policy.v1", "raw": "all-decoded-trial-frames",
              "synchronization": "native-source-minus-offset-positive",
              "association": "derived-common-positive-range",
              "triangulation": "derived-common-positive-range", "frame_rate": 30}
    normalized = {"path": "normalization.json", "sha256": digests[prefix + "normalization.json"]["sha256"]}
    if (run.get("normalization") != normalized or run.get("native_frame_policy") != policy
            or any(run.get(key) != value for key, value in identity.items())):
        raise ValueError("manual captured normalization/native frame policy differs")
    import tomllib
    config = tomllib.loads(archive.read(members[prefix + "Config.toml"]).decode("utf-8-sig"))
    if config.get("project", {}).get("frame_range", []) not in ([], "all", "auto"):
        raise ValueError("manual configured raw frame crop unsupported")
    cameras = {}
    with tempfile.TemporaryDirectory(prefix="kinelab-offline-decoded-") as temporary:
        for camera in ("cam01", "cam02"):
            item = outputs[camera + "_trial"]
            relative = item["path"]
            indexed = digests[prefix + relative]
            target = Path(temporary) / (camera + ".mp4")
            digest, size = hashlib.sha256(), 0
            with archive.open(members[prefix + relative]) as source, target.open("xb") as output:
                while block := source.read(1024 * 1024):
                    size += len(block)
                    if size > indexed["bytes"]:
                        raise ValueError("manual normalized media exceeds verified size")
                    digest.update(block)
                    output.write(block)
            if size != indexed["bytes"] or digest.hexdigest() != item["sha256"]:
                raise ValueError("manual normalized decoder bytes differ")
            command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
                       "-show_frames", "-show_format", "-of", "json", str(target)]
            try:
                decoded = strict_json_loads(_offline_probe_output(command))
                stream = decoded["streams"][0]
                times = [float(frame.get("best_effort_timestamp_time", frame.get("pts_time")))
                         for frame in decoded["frames"] if frame.get("media_type") == "video"]
                rotation = int(stream.get("tags", {}).get("rotate", 0))
                for side in stream.get("side_data_list", []):
                    if "rotation" in side:
                        rotation = int(side["rotation"])
                duration = float(stream.get("duration", decoded.get("format", {}).get("duration", 0)))
                if (not times or any(not math.isfinite(t) for t in times)
                        or any(b <= a or abs(b - a - 1 / 30) > .001 for a, b in pairwise(times))
                        or abs(times[0]) > .001 or not math.isfinite(duration) or duration <= 0
                        or (int(stream["width"]), int(stream["height"])) != (1280, 720)
                        or Fraction(stream.get("avg_frame_rate", "0/1")) != 30 or rotation != 0
                        or type(item.get("frame_count")) is not int or item["frame_count"] != len(times)
                        or item.get("timestamps") != times or item.get("fps") != stream.get("avg_frame_rate")
                        or item.get("width") != int(stream["width"]) or item.get("height") != int(stream["height"])):
                    raise ValueError("decoded count/timestamps/geometry differ")
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, IndexError, AttributeError, ZeroDivisionError) as error:
                raise ValueError("manual independent normalized decode unavailable or invalid") from error
            if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("manual normalized snapshot changed during decode")
            cameras[camera] = {"path": relative, "sha256": item["sha256"], "decoded_frame_count": len(times),
                               "source_range": [0, len(times)], "offset_frames": None, "synchronized_range": None}
    actual = {camera: set() for camera in cameras}
    for artifact in pose_stage["artifacts"]:
        relative = artifact["path"]
        match = re.fullmatch(r"pose/(cam0[12])_json/(cam0[12])_([0-9]{6,})\.json", relative)
        if match is None or match[1] != match[2]:
            raise ValueError("manual raw pose native filename required")
        camera, index = match[1], int(match[3])
        if relative != f"pose/{camera}_json/{camera}_{index:06d}.json" or index in actual[camera]:
            raise ValueError("manual raw pose native padding/index ambiguous")
        actual[camera].add(index)
    if any(actual[camera] != set(range(cameras[camera]["decoded_frame_count"])) for camera in cameras):
        raise ValueError("manual raw pose membership differs from independent decoded extent")
    summary = {"schema": "kinelab.decoded-source-coverage.v1", "normalization": normalized,
               "native_frame_policy": policy, "cameras": cameras, "common_range": None,
               "associated_missing_frames": {"cam01": [], "cam02": []},
               "physical_source_frame_equality": "UNVERIFIED"}
    if (pose_stage["quality"].get("policy") != "kinelab.pipeline-quality.v4"
            or pose_stage["quality"].get("source_coverage") != summary):
        raise ValueError("manual decoded source coverage differs from native prerequisites")


def _offline_manual_native(archive, members, digests, sid):
    """Port only validate_run_evidence's reachable calibration/pose prerequisites."""
    prefix, dependencies, inputs = f"sessions/{sid}/", {}, {}

    def bind(relative):
        safe_member_name(relative, "report.lineage")
        observed = digests.get(prefix + relative)
        if observed is None:
            raise ValueError("manual native dependency missing")
        dependencies[relative] = observed["sha256"]
        return {"path": relative, "sha256": observed["sha256"]}

    for name, relative in MANUAL_CONTEXT_INPUTS.items():
        if digests.get(prefix + relative, {}).get("bytes", 4 * 1024 * 1024 + 1) > 4 * 1024 * 1024:
            raise ValueError("manual context input exceeds independent read limit")
        inputs[name] = bind(relative)
    session = _report_document(archive, members, digests, prefix + "session.json", 4 * 1024 * 1024)
    if session.get("session_id") != sid:
        raise ValueError("manual registered session identity required")
    _offline_generated_provenance(archive, members, digests, sid, session)
    captures = session["captures"]
    for capture in captures.values():
        if bind(capture["path"])["sha256"] != capture["sha256"]:
            raise ValueError("manual source capture changed")
    identity = {"session_id": sid, "config_sha256": inputs["config"]["sha256"],
                "inputs": {role: item["sha256"] for role, item in captures.items()}}
    run = _report_document(archive, members, digests, prefix + "run.json", 4 * 1024 * 1024)
    policy = "kinelab.pipeline-quality.v4"
    names = ("calibration", "poseEstimation", "synchronization", "personAssociation",
             "triangulation", "filtering", "markerAugmentation", "kinematics")
    stages = run.get("stages")
    if (run.get("schema") != "kinelab.run.v1" or run.get("coordinateSystem") != "opensim_y_up"
            or run.get("quality_policy") != policy or any(run.get(key) != value for key, value in identity.items())
            or not isinstance(stages, list) or len(stages) != len(names)
            or any(not isinstance(item, dict) or item.get("name") != name for item, name in zip(stages, names))
            or any("rejected_evidence" in item and (item["name"] != "triangulation" or item.get("status") != "failed")
                   for item in stages)):
        raise ValueError("manual native run identity or ordered stages differ")
    relatives = {path[len(prefix):] for path in digests if path.startswith(prefix)}
    for item in stages[:2]:
        name, quality, artifacts = item["name"], item.get("quality"), item.get("artifacts")
        if (item.get("status") != "passed" or not isinstance(quality, dict) or quality.get("ok") is not True
                or not isinstance(artifacts, list) or not artifacts):
            raise ValueError("manual prerequisite stage not passed")
        if isinstance(quality.get("log"), dict):
            bind(quality["log"].get("path"))
        if name == "calibration":
            if quality.get("policy") != policy:
                raise ValueError("manual calibration quality policy differs")
            log = _report_object(quality.get("log"), ("path", "start", "end", "sha256"))
            start, end = log["start"], log["end"]
            if (log["path"] != "logs.txt" or type(start) is not int or type(end) is not int
                    or not 0 <= start < end or end > digests.get(prefix + "logs.txt", {}).get("bytes", 0)):
                raise ValueError("manual calibration log window unbound")
            _report_sha(log["sha256"])
            with archive.open(members[prefix + "logs.txt"]) as stream:
                stream.seek(start)
                remaining, observed = end - start, hashlib.sha256()
                while remaining:
                    block = stream.read(min(remaining, 1024 * 1024))
                    if not block:
                        raise ValueError("manual calibration log truncated")
                    observed.update(block)
                    remaining -= len(block)
            if observed.hexdigest() != log["sha256"]:
                raise ValueError("manual calibration log bytes changed")
            bind("logs.txt")
            actual = {path for path in relatives if path.startswith("calibration/")
                      and path.count("/") == 1 and path.endswith(".toml")}
        else:
            actual = {path for path in relatives if path.startswith("pose/") and path.endswith(".json")}
        bound = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                raise TypeError("manual native artifact binding invalid")
            relative = artifact["path"]
            if relative in bound or bind(relative)["sha256"] != artifact.get("sha256"):
                raise ValueError("manual native artifact changed or duplicated")
            bound.add(relative)
            if relative.endswith(".json"):
                pose = _report_document(archive, members, digests, prefix + relative, 4 * 1024 * 1024)
                if not isinstance(pose.get("people"), list):
                    raise TypeError("manual native pose people invalid")
                for person in pose["people"]:
                    values = person.get("pose_keypoints_2d") if isinstance(person, dict) else None
                    if (not isinstance(values, list) or not values or len(values) % 3
                            or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                            or any(not 0 <= value <= 1 for value in values[2::3])):
                        raise ValueError("manual native pose coordinates/confidence invalid")
        if actual != bound:
            raise ValueError("manual native output inventory differs")
    preflight = _report_document(archive, members, digests, prefix + "preflight.json", 4 * 1024 * 1024)
    if (preflight.get("schema") != "kinelab.preflight.v1" or preflight.get("ok") is not True
            or preflight.get("errors") or any(preflight.get(key) != value for key, value in identity.items())):
        raise ValueError("manual preflight identity differs")
    normalized = _report_document(archive, members, digests, prefix + "normalization.json", 4 * 1024 * 1024)
    output_paths = {
        "cam01_intrinsics": "calibration/intrinsics/cam01/intrinsics.mp4",
        "cam02_intrinsics": "calibration/intrinsics/cam02/intrinsics.mp4",
        "cam01_board": "calibration/extrinsics/cam01.mp4", "cam02_board": "calibration/extrinsics/cam02.mp4",
        "cam01_trial": "videos/cam01.mp4", "cam02_trial": "videos/cam02.mp4"}
    outputs = normalized.get("outputs")
    if (normalized.get("schema") != "kinelab.normalization.v1"
            or any(normalized.get(key) != value for key, value in identity.items())
            or not isinstance(outputs, dict) or set(outputs) != set(output_paths)):
        raise ValueError("manual normalization identity differs")
    for role, relative in output_paths.items():
        output = outputs[role]
        if (not isinstance(output, dict) or output.get("path") != relative
                or bind(relative)["sha256"] != output.get("sha256")):
            raise ValueError("manual normalized output binding differs")
    _offline_decoded_pose(archive, members, digests, prefix, identity, run, outputs, stages[1])
    return session, inputs, dependencies


def _offline_manual_request(value):
    _report_object(value, ("operation_id", "context_sha256", "metadata_context_sha256", "input_id",
                           "source_sha256", "reviewer", "annotation_origin", "labels", "tolerance_frames", "confirm"))
    if len(canonical_json(value).encode("utf-8")) > 65536:
        raise ValueError("manual request exceeds limit")
    if not isinstance(value["operation_id"], str) or re.fullmatch(r"[0-9a-f]{32}", value["operation_id"]) is None:
        raise ValueError("manual operation identity invalid")
    for name in ("context_sha256", "metadata_context_sha256", "input_id", "source_sha256"):
        _report_sha(value[name])
    reviewer, labels, tolerance = value["reviewer"], value["labels"], value["tolerance_frames"]
    if (not isinstance(reviewer, str) or reviewer != reviewer.strip() or not 2 <= len(reviewer) <= 90
            or any(ord(ch) < 32 for ch in reviewer) or value["confirm"] is not True
            or value["annotation_origin"] != "human_observed_video_frames"
            or type(tolerance) is not int or not 0 <= tolerance <= 15
            or not isinstance(labels, list) or not 1 <= len(labels) <= 256):
        raise ValueError("manual request declaration invalid")
    return value


def _offline_manual_catalog(archive, members, digests, sid, session):
    """Reproduce the complete bounded input catalog used by entry publication."""
    prefix, groups, total = f"sessions/{sid}/", {}, 0
    for path, observed in digests.items():
        if not path.startswith(prefix + "assessment-inputs/"):
            continue
        relative = path[len(prefix):]
        parts = relative.split("/")
        if len(parts) != 3 or parts[2] not in ("trajectory.json", "candidates.json"):
            raise ValueError("manual catalog contains undeclared members")
        total += observed["bytes"]
        if observed["bytes"] > 4 * 1024 * 1024 or total > 8 * 1024 * 1024:
            raise ValueError("manual catalog byte limit exceeded")
        groups.setdefault(parts[1], {})[parts[2]] = relative
    if not 1 <= len(groups) <= 16:
        raise ValueError("manual catalog set limit exceeded")
    for files in groups.values():
        if set(files) != {"trajectory.json", "candidates.json"}:
            raise ValueError("manual catalog pair incomplete")
        trajectory, candidates = (_report_document(archive, members, digests, prefix + files[name], 4 * 1024 * 1024)
                                  for name in ("trajectory.json", "candidates.json"))
        role, size = candidates.get("role"), candidates.get("image_size")
        capture = session["captures"].get(role) if isinstance(role, str) else None
        if (role not in ("cam01_trial", "cam02_trial") or capture is None
                or candidates.get("source_sha256") != capture["sha256"]
                or not isinstance(size, list) or len(size) != 2
                or any(type(value) is not int or not 80 <= value <= 16384 for value in size)):
            raise ValueError("manual catalog source/image binding invalid")
        if candidates.get("schema") == _MA_GAIT_CANDIDATES_SCHEMA:
            reproduced = _ma_orient_event_candidates(_ma_propose_extrema(
                trajectory, role, capture["sha256"], image_width=size[0], image_height=size[1]),
                screen_forward=candidates.get("screen_forward"))
        elif candidates.get("schema") == _MA_SQUAT_CANDIDATES_SCHEMA:
            if candidates.get("activity_assumption") != "operator_confirmed_squat" or candidates.get("camera_view_assumption") != "side":
                raise ValueError("manual catalog squat assumptions differ")
            reproduced = _ma_analyze_squats(trajectory, role, capture["sha256"], camera_view="side",
                                           activity_confirmed=True, image_width=size[0], image_height=size[1])
        else:
            raise ValueError("manual catalog candidate schema unsupported")
        if canonical_json(reproduced) != canonical_json(candidates) or type(candidates.get("observed_frames")) is not int:
            raise ValueError("manual catalog candidates do not reproduce")


def _offline_manual_history(conn, archive, members, digests, sid, metadata_history):
    """Validate every audited entry, including entries stale in later projections."""
    prefix, receipts, authority, operations = f"sessions/{sid}/", [], {}, set()
    rows = conn.execute("SELECT id,details_json FROM audit_events WHERE session_id=? AND event_type='MANUAL_ASSESSMENT_ENTRY_PUBLISHED' ORDER BY id LIMIT 513", (sid,)).fetchall()
    if len(rows) > 512:
        raise ValueError("manual entry verification limit exceeded")
    first_report = conn.execute("SELECT MIN(id) FROM audit_events WHERE session_id=? AND event_type='REPORT_PUBLISHED'", (sid,)).fetchone()[0]
    native = _offline_manual_native(archive, members, digests, sid) if rows else None
    if native is not None:
        _offline_manual_catalog(archive, members, digests, sid, native[0])
    for event in rows:
        if first_report is None or event["id"] >= first_report or len(event["details_json"].encode("utf-8")) > 131072:
            raise ValueError("manual entry must precede first report publication")
        record = _report_object(strict_json_loads(event["details_json"]), ("request", "receipt"))
        request = _offline_manual_request(record["request"])
        operation = request["operation_id"]
        latest = next(value for event_id, value in reversed(metadata_history) if event_id < event["id"])
        if operation in operations or request["metadata_context_sha256"] != latest:
            raise ValueError("manual duplicate operation or stale entry-time metadata context")
        operations.add(operation)
        relative = f"exports/manual-entry-{operation}.manual-assessment.json"
        descriptor = _report_document(archive, members, digests, prefix + relative, 4 * 1024 * 1024)
        expected_receipt = {"schema": "kinelab.manual-assessment-entry-receipt.v1", "session_id": sid,
                            "operation_id": operation, "metadata_context_sha256": latest,
                            "descriptor": {"path": relative, "sha256": digests[prefix + relative]["sha256"]},
                            "test_only": True, "clinical_accuracy_validated": False}
        if canonical_json(record["receipt"]) != canonical_json(expected_receipt):
            raise ValueError("manual audit receipt differs")
        _report_object(descriptor, ("schema", "kind", "test_only", "evidence_classification", "clinical_accuracy_validated",
                                    "session_id", "source", "inputs", "dependencies", "run", "tolerance_frames",
                                    "score", "recorded_at_utc", "limitations"))
        if (descriptor["schema"] != "kinelab.manual-assessment.v1" or descriptor["session_id"] != sid
                or descriptor["test_only"] is not True or descriptor["clinical_accuracy_validated"] is not False
                or descriptor["evidence_classification"] != MANUAL_CLASSIFICATION
                or descriptor["limitations"] != MANUAL_LIMITATIONS
                or type(descriptor["tolerance_frames"]) is not int
                or descriptor["tolerance_frames"] != request["tolerance_frames"]):
            raise ValueError("manual descriptor identity or declaration differs")
        _offline_manual_recorded_at(descriptor["recorded_at_utc"])
        session, base_inputs, base_dependencies = native
        bindings = _report_object(descriptor["inputs"], (*MANUAL_CONTEXT_INPUTS, "trajectory", "candidates", "reference"))
        dependencies, documents, owned = dict(base_dependencies), {}, {relative}
        revision = f"exports/manual-entry-{operation}.manual-assessment-inputs"
        for name, binding in bindings.items():
            _report_object(binding, ("path", "sha256", "snapshot"))
            path = binding["path"]
            safe_member_name(path, "report.lineage")
            _report_sha(binding["sha256"])
            observed = digests.get(prefix + path)
            if observed is None or observed["sha256"] != binding["sha256"]:
                raise ValueError("manual original input changed")
            if name in base_inputs:
                if {"path": path, "sha256": binding["sha256"]} != base_inputs[name]:
                    raise ValueError("manual context input binding differs")
            elif path in dependencies:
                raise ValueError("manual input paths must be distinct")
            dependencies[path] = binding["sha256"]
            snapshot = _report_object(binding["snapshot"], ("path", "sha256"))
            expected_path = f"{revision}/{name}{Path(path).suffix}"
            if snapshot != {"path": expected_path, "sha256": binding["sha256"]} or digests.get(prefix + expected_path) != observed:
                raise ValueError("manual immutable input snapshot differs")
            owned.add(expected_path)
            if name in ("trajectory", "candidates", "reference"):
                documents[name] = _report_document(archive, members, digests, prefix + path, 4 * 1024 * 1024)
        if canonical_json(descriptor["dependencies"]) != canonical_json(dependencies):
            raise ValueError("manual exact dependency inventory differs")
        if descriptor["run"] != {"schema": "kinelab.run.v1", "through": "poseEstimation", "sha256": base_inputs["run"]["sha256"]}:
            raise ValueError("manual native run binding differs")
        reference_path = f"assessment-entries/entry-{operation}/reference.json"
        trajectory_path, candidates_path = bindings["trajectory"]["path"], bindings["candidates"]["path"]
        parts = trajectory_path.split("/")
        if (len(parts) != 3 or parts[0] != "assessment-inputs" or parts[2] != "trajectory.json"
                or candidates_path != "/".join((*parts[:2], "candidates.json"))
                or bindings["reference"]["path"] != reference_path):
            raise ValueError("manual discovered input/reference paths differ")
        candidates, reference = documents["candidates"], documents["reference"]
        role, size = candidates.get("role"), candidates.get("image_size")
        capture = session["captures"].get(role) if isinstance(role, str) else None
        if (role not in ("cam01_trial", "cam02_trial") or capture is None
                or not isinstance(size, list) or len(size) != 2
                or any(type(value) is not int or not 80 <= value <= 16384 for value in size)
                or type(candidates.get("observed_frames")) is not int
                or candidates.get("source_sha256") != capture["sha256"]
                or request["source_sha256"] != capture["sha256"]
                or descriptor["source"] != {"role": role, "path": capture["path"], "sha256": capture["sha256"]}):
            raise ValueError("manual selected source binding differs")
        # Live context/input CAS digests contain original filesystem identities. They
        # remain opaque declarations in a portable copy, never content-proof substitutes.
        arithmetic, make_reference = globals().get("_offline_manual_arithmetic"), globals().get("_offline_manual_reference")
        if not callable(arithmetic) or not callable(make_reference):
            raise TypeError("REPORT_MANUAL_UNSUPPORTED: reviewed independent arithmetic helpers unavailable")
        expected_reference = make_reference(candidates, reviewer=request["reviewer"], labels=request["labels"],
                                            annotation_origin=request["annotation_origin"])
        _offline_manual_recorded_at(reference.get("recorded_at_utc"))
        expected_reference = {key: value for key, value in expected_reference.items() if key != "recorded_at_utc"}
        if canonical_json({key: value for key, value in reference.items() if key != "recorded_at_utc"}) != canonical_json(expected_reference):
            raise ValueError("manual reference differs from audited labels")
        kind, score = arithmetic(documents["trajectory"], candidates, reference,
                                 source_sha256=capture["sha256"], tolerance_frames=request["tolerance_frames"])
        if descriptor["kind"] != kind or canonical_json(descriptor["score"]) != canonical_json(score):
            raise ValueError("manual recomputed candidates/score differ")
        copied = revision + "/descriptor.json"
        if digests.get(prefix + copied) != digests[prefix + relative]:
            raise ValueError("manual descriptor snapshot differs")
        owned.update((reference_path, copied))
        for path in owned:
            authority[path] = (digests[prefix + path], event["id"])
        receipts.append((event["id"], expected_receipt))
    for path in digests:
        if not path.startswith(prefix):
            continue
        relative = path[len(prefix):]
        if relative.startswith(("assessment-entries/", "exports/manual-entry-")) and relative not in authority:
            raise ValueError("unaudited manual authority member")
    return receipts, authority


def _verify_v2_report(conn, archive, members, digests, event, document, receipt, previous, inputs, state):
    sid = event["session_id"]
    _report_object(document, ("schema", "session_id", "generation", "inputs", "files", "input_policy",
                              "supersedes", "origin_sha256", "run_sha256", "metadata_context_sha256",
                              "manual_assessment_context", "report_context_sha256"))
    _report_object(receipt, ("schema", "generation", "manifest_sha256", "supersedes", "report_context_sha256"))
    if (receipt["schema"] != "kinelab.report-publication.v2" or document["input_policy"] != REPORT_INPUT_POLICY_V2
            or document["supersedes"] != previous or receipt["supersedes"] != previous
            or receipt["report_context_sha256"] != document["report_context_sha256"]):
        raise ValueError("v2 publication predecessor differs")
    if state is None:
        _offline_take_journals(archive, members, digests, sid)
        origin, metadata_history, authority = _report_metadata_history(conn, archive, members, digests, sid)
        manual_history, manual_authority = _offline_manual_history(conn, archive, members, digests, sid, metadata_history)
        state = origin, metadata_history, {**authority, **manual_authority}, manual_history
    origin, metadata_history, authority, manual_history = state
    metadata_context = next(value for event_id, value in reversed(metadata_history) if event_id < event["id"])
    manual = {"schema": "kinelab.report-manual-context.v1",
              "assessments": sorted((item for event_id, item in manual_history if event_id < event["id"]
                                     and item["metadata_context_sha256"] == metadata_context), key=lambda item: item["operation_id"]),
              "unavailable_assessments": sorted(({"operation_id": item["operation_id"], "reason": "METADATA_CONTEXT_CHANGED"}
                                                  for event_id, item in manual_history if event_id < event["id"]
                                                  and item["metadata_context_sha256"] != metadata_context), key=lambda item: item["operation_id"])}
    manual["sha256"] = digest(manual)
    if canonical_json(document["manual_assessment_context"]) != canonical_json(manual):
        raise ValueError("manual current/stale report projection differs")
    for key in ("origin_sha256", "run_sha256", "metadata_context_sha256", "report_context_sha256"):
        _report_sha(document[key])
    baseline = document["inputs"]
    if (document["origin_sha256"] != origin["sha256"] or document["metadata_context_sha256"] != metadata_context
            or baseline.get("session.json") != inputs.get("session.json")
            or baseline.get("run.json") != inputs.get("run.json")
            or baseline.get("run.json", {}).get("sha256") != document["run_sha256"]):
        raise ValueError("v2 origin, run or metadata context differs")
    projection = {"schema": "kinelab.report-context.v1", **{key: document[key] for key in (
        "session_id", "input_policy", "inputs", "origin_sha256", "run_sha256", "metadata_context_sha256", "manual_assessment_context")}}
    if digest(projection) != document["report_context_sha256"]:
        raise ValueError("v2 report context digest differs")
    for path, reference in baseline.items():
        safe_member_name(path, "report.lineage")
        _report_reference(reference)
        if inputs.get(path) != reference:
            raise ValueError("published report input changed or removed")
    for path in inputs.keys() - baseline.keys():
        authorized = authority.get(path)
        if authorized is None or authorized[0] != inputs[path] or authorized[1] <= event["id"]:
            raise ValueError("unaudited report input addition")
    # A report cannot omit evidence that had already been committed at publication.
    for path, (reference, event_id) in authority.items():
        if event_id < event["id"] and baseline.get(path) != reference:
            raise ValueError("report omitted earlier metadata evidence")
    return state


def _verify_reports(conn, archive, members, digests):
    check = "report.lineage"
    events = conn.execute("""SELECT id, session_id, details_json FROM audit_events
        WHERE event_type='REPORT_PUBLISHED' ORDER BY id""").fetchall()
    verified = 0
    heads, metadata_states, published = {}, {}, set()
    for event in events:
        sid = event["session_id"]
        try:
            receipt = strict_json_loads(event["details_json"])
            generation = receipt["generation"]
            receipt_sha = receipt["manifest_sha256"]
            if not isinstance(generation, str) or GENERATION_RE.fullmatch(generation) is None:
                raise ValueError("generation identity")
            if not isinstance(receipt_sha, str) or re.fullmatch(r"[0-9a-f]{64}", receipt_sha) is None:
                raise ValueError("receipt digest")
        except (ValueError, KeyError, TypeError) as exc:
            raise VerifyError("REPORT_INVALID", f"{sid}: audit receipt: {exc}", check) from exc
        prefix = f"sessions/{sid}/exports/{generation}/"
        manifest_path = prefix + "manifest.json"
        entry = digests.get(manifest_path)
        if entry is None or entry["sha256"] != receipt_sha or entry["bytes"] > MAX_MANIFEST_BYTES:
            raise VerifyError("REPORT_INVALID", f"{sid}: manifest digest for {generation}", check)
        try:
            document = strict_json_loads(archive.read(members[manifest_path]).decode("utf-8"))
            v2 = document.get("schema") == "kinelab.report-generation.v2"
            if (document["schema"] not in ("kinelab.report-generation.v1", "kinelab.report-generation.v2")
                    or document["session_id"] != sid or document["generation"] != generation):
                raise ValueError("manifest identity")
            identity = (sid, generation)
            if identity in published or (not v2 and sid in heads):
                raise ValueError("duplicate generation or invalid legacy publication order")
            if len([key for key in published if key[0] == sid]) >= 512:
                raise ValueError("report generation verification limit exceeded")
            if not v2:
                _report_object(receipt, ("generation", "manifest_sha256"))
                if set(document) not in ({"schema", "session_id", "generation", "inputs", "files"},
                                         {"schema", "session_id", "generation", "inputs", "files", "input_policy"}):
                    raise ValueError("legacy manifest fields")
            input_policy = document.get("input_policy")
            if "input_policy" in document and input_policy != REPORT_INPUT_POLICY_V2:
                raise ValueError("unsupported report input policy")
            if not isinstance(document["inputs"], dict):
                raise TypeError("invalid report input inventory")
            if input_policy == REPORT_INPUT_POLICY_V2 and REPORT_ADMINISTRATIVE_ANCHOR in document["inputs"]:
                raise ValueError("v2 report records an excluded administrative anchor")
            expected_names = {f"{sid}-research-report.pdf", f"{sid}-research-summary.json", f"{sid}-metrics.csv"}
            if not isinstance(document["files"], dict) or set(document["files"]) != expected_names:
                raise ValueError("incomplete report set")
            actual = {path[len(prefix):] for path in digests if path.startswith(prefix)}
            if actual != expected_names | {"manifest.json"}:
                raise ValueError("incomplete report set in archive")
            references = {**document["files"], "manifest.json": {"sha256": receipt_sha, "bytes": entry["bytes"]}}
            for name, reference in references.items():
                _report_reference(reference)
                row = conn.execute("SELECT sha256,bytes FROM artifacts WHERE session_id=? AND artifact_key=?",
                                   (sid, f"exports/{generation}/{name}")).fetchone()
                disk = digests.get(prefix + name)
                if (row is None or row["sha256"] != reference["sha256"] or row["bytes"] != reference["bytes"]
                        or disk is None or disk["sha256"] != reference["sha256"]
                        or disk["bytes"] != reference["bytes"]):
                    raise ValueError(f"report file or registration changed: {name}")
            inputs = {}
            session_prefix = f"sessions/{sid}/"
            for path, info in digests.items():
                if not path.startswith(session_prefix):
                    continue
                rel = path[len(session_prefix):]
                parts = rel.split("/")
                if len(parts) >= 2 and parts[0] == "exports" and (
                        GENERATION_RE.fullmatch(parts[1]) or parts[1].startswith(".report-staging-")):
                    continue
                # zip.structure has already refused links, reparse entries and nonregular members.
                if rel.startswith(REPORT_ADMINISTRATIVE_ANCHOR + "/"):
                    raise ValueError("nonregular administrative anchor")
                if input_policy == REPORT_INPUT_POLICY_V2 and rel == REPORT_ADMINISTRATIVE_ANCHOR:
                    continue
                inputs[rel] = {"sha256": info["sha256"], "bytes": info["bytes"]}
            if v2:
                metadata_states[sid] = _verify_v2_report(conn, archive, members, digests, event, document, receipt,
                                                        heads.get(sid), inputs, metadata_states.get(sid))
            elif inputs != document["inputs"]:
                if (input_policy is None and REPORT_ADMINISTRATIVE_ANCHOR not in document["inputs"]
                        and REPORT_ADMINISTRATIVE_ANCHOR in inputs
                        and {key: value for key, value in inputs.items()
                             if key != REPORT_ADMINISTRATIVE_ANCHOR} == document["inputs"]):
                    raise ValueError("REPORT_INPUT_POLICY_COMPATIBILITY_REQUIRED: legacy report did not bind the later administrative anchor; explicit migration is required")
                raise ValueError("report inputs no longer match their published revision")
            heads[sid] = {"generation": generation, "manifest_sha256": receipt_sha}
            published.add(identity)
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError) as exc:
            if (isinstance(exc, VerifyError) and exc.check == check and exc.code in (
                    "REPORT_TAKE_JOURNAL_PENDING", "REPORT_TAKE_JOURNAL_UNKNOWN", "REPORT_TAKE_JOURNAL_IDENTITY")):
                raise
            raise VerifyError("REPORT_INVALID", f"{sid}: {exc}", check) from exc
        verified += 1
    for path in digests:
        parts = path.split("/")
        if (len(parts) >= 4 and parts[0] == "sessions" and parts[2] == "exports"
                and GENERATION_RE.fullmatch(parts[3]) and (parts[1], parts[3]) not in published):
            raise VerifyError("REPORT_INVALID", "unregistered report generation in archive", check)
    return verified


def _verify_database(archive, members, manifest, digests):
    """Extract only index.db into a fresh temporary directory; open read-only."""
    check = "database.integrity"
    temp_dir = Path(tempfile.mkdtemp(prefix="kinelab-evidence-verify-"))
    conn = None
    try:
        db_file = temp_dir / "index.db"
        with archive.open(members["index.db"]) as source, db_file.open("xb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        if (hashlib.sha256(db_file.read_bytes()).hexdigest() != digests["index.db"]["sha256"]
                or db_file.stat().st_size != digests["index.db"]["bytes"]):
            raise VerifyError("EVIDENCE_CORRUPT", "extracted database differs from verified digest", check)
        uri = "file:" + db_file.as_posix() + "?mode=ro&immutable=1"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise VerifyError("EVIDENCE_CORRUPT", f"index.db is not a readable database: {exc}", check) from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA query_only=ON")
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.Error as exc:
            raise VerifyError("EVIDENCE_CORRUPT", f"index.db unreadable: {exc}", check) from exc
        if integrity != "ok" or violations:
            raise VerifyError("EVIDENCE_CORRUPT", "database integrity or foreign-key check failed", check)
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if version != SUPPORTED_INDEX_SCHEMA:
            raise VerifyError("EVIDENCE_UNSUPPORTED_SCHEMA",
                              f"index schema {version}; supported {SUPPORTED_INDEX_SCHEMA}", check)
        tip, audit_count = _verify_audit_chain(conn)
        if tip != manifest["generation"]["audit_tip"]:
            raise VerifyError("AUDIT_CHAIN_INVALID",
                              "declared audit tip differs from the verified chain tip", "audit.lineage")
        _verify_crosscheck(conn, manifest, digests)
        recordings = _verify_recordings(conn, manifest["generation"]["recording_count"])
        reports = _verify_reports(conn, archive, members, digests)
        return {"audit_events": audit_count, "recordings": recordings, "reports": reports}
    finally:
        if conn is not None:
            conn.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def verify_archive(path):
    """Verify one backup archive read-only; return a structured result dict."""
    path = Path(path)
    checks = []
    failures = []
    result = {"schema": "kinelab.evidence-verification.v1", "tool": "tools/verify_evidence.py",
              "archive": str(path), "archive_sha256": None, "ok": False,
              "checks": checks, "failures": failures, "limits": LIMITS,
              "scope": {
                  "package_integrity": "SHA-256 digest, size, schema, inventory, sequence and lineage checks only",
                  "authenticity": "UNESTABLISHED: the manifest is self-asserted and unsigned; this verifier "
                                  "cannot establish who created the archive or that its contents are authentic",
                  "physical_accuracy_verified": False,
                  "clinical_validation": "UNVERIFIED",
                  "note": "Package/hash integrity is independent of physical, biomechanical and clinical "
                          "correctness; those require separate validation evidence."}}
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    result["archive_sha256"] = hasher.hexdigest()

    remaining = list(CHECK_IDS)

    def phase(check_id, fn):
        remaining.remove(check_id)
        outcome = fn()
        checks.append({"id": check_id, "status": "pass", "detail": outcome if isinstance(outcome, str) else ""})
        return outcome

    archive = None
    try:
        try:
            archive = zipfile.ZipFile(path)
            members = phase("zip.structure", lambda: _check_structure(archive))
        except (zipfile.BadZipFile, EOFError) as exc:
            raise VerifyError("EVIDENCE_CORRUPT", f"truncated or malformed ZIP: {exc}", "zip.structure") from exc
        manifest = phase("manifest.schema", lambda: _check_manifest(archive, members))
        phase("manifest.inventory", lambda: _check_inventory(manifest, members))
        digests = phase("member.digests", lambda: _check_digests(archive, manifest, members))
        summary = phase("database.integrity",
                        lambda: _verify_database(archive, members, manifest, digests))
        for check_id, detail in (
                ("audit.lineage", f"{summary['audit_events']} events; chain tip matches the declared generation"),
                ("evidence.crosscheck", "index observations match the verified file snapshot"),
                ("recording.sequence", json.dumps(summary["recordings"], sort_keys=True)),
                ("report.lineage", f"{summary['reports']} committed report generation(s) verified")):
            phase(check_id, lambda detail=detail: detail)
        result["ok"] = True
    except VerifyError as exc:
        if exc.check in remaining:
            remaining.remove(exc.check)
        checks.append({"id": exc.check, "status": "fail", "detail": str(exc)})
        failures.append({"check": exc.check, "code": exc.code, "message": str(exc)})
    finally:
        if archive is not None:
            archive.close()
    for check_id in remaining:
        checks.append({"id": check_id, "status": "skipped", "detail": "not reached"})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Portable read-only verifier for KineLab PT backup evidence archives (N05).")
    parser.add_argument("archive", help="path to a .kinelab.zip / backup archive")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    args = parser.parse_args(argv)
    try:
        result = verify_archive(args.archive)
    except OSError as exc:
        result = {"schema": "kinelab.evidence-verification.v1", "ok": False,
                  "failures": [{"check": "archive.readable", "code": "EVIDENCE_IO",
                                "message": f"EVIDENCE_IO: {exc}"}]}
    print(json.dumps(result, indent=2 if args.pretty else None, allow_nan=False))
    if result["ok"]:
        return 0
    if any(f["code"] in ("EVIDENCE_UNSUPPORTED_SCHEMA", "EVIDENCE_IO") for f in result["failures"]):
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
