"""Synthetic-only incremental recording; frames and audit share one SQLite commit."""
import hashlib
import re
from datetime import UTC, datetime

import recording_contract as frame_contract
import session_contract as json_contract
from recording_contract import MAX_CHUNK_BYTES, canonical_json, digest, validate_frames, validate_header
from session_contract import strict_json_loads

_SEMANTIC_PROOF_LIMIT = 4096

_RECEIPT_MEMO_MAX_ENTRIES = 4096
_RECEIPT_MEMO_MAX_CHARS = 256


def _receipt_function(function):
    defaults = getattr(function, "__kwdefaults__", None)
    return (function, getattr(function, "__code__", None), getattr(function, "__defaults__", None),
            defaults, tuple(defaults.items()) if type(defaults) is dict else None)


def _receipt_same(left, right):
    if type(left) is tuple and type(right) is tuple:
        return len(left) == len(right) and all(_receipt_same(a, b) for a, b in zip(left, right, strict=True))
    return left is right


def _receipt_bindings():
    """Only the original pure project parser and native stdlib decoder can lend facts."""
    module = json_contract.json
    decoder = module.decoder
    scanner = module.scanner
    if (getattr(decoder, "scanner", None) is not scanner
            or getattr(scanner, "c_make_scanner", None) is None
            or scanner.make_scanner is not scanner.c_make_scanner
            or getattr(decoder, "c_scanstring", None) is None
            or decoder.scanstring is not decoder.c_scanstring):
        return None
    functions = (strict_json_loads, json_contract.strict_json_loads, module.loads,
                 module.JSONDecoder.__init__, module.JSONDecoder.decode, module.JSONDecoder.raw_decode,
                 decoder.JSONObject, decoder.JSONArray, decoder.py_scanstring, scanner.py_make_scanner,
                 json_contract.math.isfinite, _receipt_function, _receipt_same, _receipt_bindings,
                 _receipt_limits, _receipt_flat, RecordingStore._receipt_details)
    # Nested unique/constant/finite helper code is retained in strict_json_loads.__code__.co_consts.
    globals_used = []
    for function in functions:
        namespace = getattr(function, "__globals__", {})
        builtins = getattr(function, "__builtins__", {})
        globals_used.append(tuple(namespace.get(name, builtins.get(name)) for name in
                                  ("json", "math", "isinstance", "float", "dict", "list", "enumerate",
                                   "str", "int", "bool", "ValueError", "TypeError", "StopIteration")))
    return (json_contract, module, json_contract.math, module.JSONDecoder, decoder, scanner,
            tuple(_receipt_function(function) for function in functions), tuple(globals_used),
            tuple(_receipt_function(getattr(decoder, name, None)) for name in
                  ("JSONObject", "JSONArray", "scanstring", "c_scanstring", "py_scanstring")),
            tuple(getattr(decoder, name, None) for name in ("WHITESPACE", "WHITESPACE_STR", "NaN", "PosInf", "NegInf")),
            tuple(getattr(decoder, "_CONSTANTS", {}).items()),
            tuple(_receipt_function(getattr(scanner, name, None)) for name in
                  ("make_scanner", "c_make_scanner", "py_make_scanner")), getattr(scanner, "NUMBER_RE", None))


def _receipt_limits():
    entries, chars = _RECEIPT_MEMO_MAX_ENTRIES, _RECEIPT_MEMO_MAX_CHARS
    if type(entries) is int and type(chars) is int and 0 < entries <= 4096 and 0 < chars <= 256:
        return entries, chars
    return None


def _receipt_flat(details):
    # No mutable tree, subclass or unbounded string is retained; caller already bounded exact raw text.
    return type(details) is dict and bool(details) and all(
        type(key) is str and type(value) in (str, int, float, bool, type(None))
        for key, value in details.items())



def create_schema(conn):
    conn.execute("""CREATE TABLE recordings (
        session_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
        capture_id TEXT NOT NULL UNIQUE, header_json TEXT NOT NULL, header_sha256 TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('RECORDING','FINALIZED')),
        revision INTEGER NOT NULL, created_at_utc TEXT NOT NULL,
        manifest_json TEXT, manifest_sha256 TEXT
    )""")
    conn.execute("""CREATE TABLE recording_chunks (
        chunk_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES recordings(session_id),
        first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
        first_time_ms REAL NOT NULL, last_time_ms REAL NOT NULL,
        frames_json TEXT NOT NULL, sha256 TEXT NOT NULL,
        UNIQUE(session_id, first_sequence)
    )""")
    for action in ("UPDATE", "DELETE"):
        conn.execute(f"CREATE TRIGGER recording_chunk_no_{action.lower()} BEFORE {action} ON recording_chunks "
                     "BEGIN SELECT RAISE(ABORT, 'RECORDING_IMMUTABLE'); END")
    conn.execute("""CREATE TRIGGER recording_no_delete BEFORE DELETE ON recordings
                    BEGIN SELECT RAISE(ABORT, 'RECORDING_IMMUTABLE'); END""")
    conn.execute("""CREATE TRIGGER recording_header_immutable BEFORE UPDATE ON recordings
        WHEN NEW.session_id != OLD.session_id OR NEW.operation_id != OLD.operation_id
          OR NEW.capture_id != OLD.capture_id OR NEW.header_json != OLD.header_json
          OR NEW.header_sha256 != OLD.header_sha256 OR NEW.created_at_utc != OLD.created_at_utc
          OR OLD.state = 'FINALIZED'
        BEGIN SELECT RAISE(ABORT, 'RECORDING_IMMUTABLE'); END""")


class RecordingStore:
    def __init__(self, index):
        self.index = index
        self._semantic_connection = None
        self._semantic_profile = None
        self._semantic_proofs = {}
        self._receipt_proofs = {}
        self._receipt_connection = None
        self._receipt_limits_used = None

    def _row(self, session_id):
        row = self.index.conn.execute("SELECT * FROM recordings WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise ValueError("RECORDING_NOT_FOUND")
        header = strict_json_loads(row["header_json"])
        validate_header(header)
        if (digest(header) != row["header_sha256"] or header["session_id"] != session_id or
                header["operation_id"] != row["operation_id"] or header["source"]["capture_id"] != row["capture_id"]):
            raise ValueError("RECORDING_CORRUPT: header")
        return row

    def _chunks(self, session_id):
        return self.index.conn.execute("""SELECT chunk_id, first_sequence, last_sequence,
            first_time_ms, last_time_ms, sha256 FROM recording_chunks
            WHERE session_id=? ORDER BY first_sequence""", (session_id,)).fetchall()

    def status(self, session_id):
        with self.index.read_snapshot():
            row = self._row(session_id)
            saved, received, gaps = 0, 0, []
            for part in self._checked_frames(session_id, status_only=True):
                if part["first_sequence"] > received + 1:
                    gaps.append([received + 1, part["first_sequence"] - 1])
                if part["first_sequence"] == saved + 1:
                    saved = part["last_sequence"]
                received = part["last_sequence"]
            manifest = strict_json_loads(row["manifest_json"]) if row["manifest_json"] else None
            if manifest is not None and digest(manifest) != row["manifest_sha256"]:
                raise ValueError("RECORDING_CORRUPT: manifest")
            return {"schema": "kinelab.recording-status.v1", "session_id": session_id,
                    "header": strict_json_loads(row["header_json"]),
                    "operation_id": row["operation_id"], "header_sha256": row["header_sha256"],
                    "source_kind": "synthetic", "state": row["state"], "revision": row["revision"],
                    "saved_through": saved, "received_through": received, "missing_ranges": gaps,
                    "manifest": manifest, "manifest_sha256": row["manifest_sha256"],
                    "physical_accuracy_verified": False, "clinical_validation": "UNVERIFIED"}

    def list_recordings(self):
        with self.index.read_snapshot():
            return [self.status(row[0]) for row in self.index.conn.execute("SELECT session_id FROM recordings ORDER BY created_at_utc DESC")]

    def create(self, header):
        validate_header(header)
        sid, checksum = header["session_id"], digest(header)
        with self.index.transaction():
            existing = self.index.conn.execute("""SELECT session_id, header_sha256 FROM recordings
                WHERE session_id=? OR operation_id=? OR capture_id=?""",
                (sid, header["operation_id"], header["source"]["capture_id"])).fetchone()
            if existing:
                if existing["session_id"] != sid or existing["header_sha256"] != checksum:
                    raise ValueError("RECORDING_CONFLICT: immutable identity already exists")
            else:
                if (self.index.projects_root / sid).exists():
                    raise ValueError("RECORDING_CONFLICT: native session identity already exists")
                self.index.conn.execute("""INSERT INTO recordings
                    (session_id, operation_id, capture_id, header_json, header_sha256, state, revision, created_at_utc)
                    VALUES (?,?,?,?,?,'RECORDING',1,?)""", (sid, header["operation_id"], header["source"]["capture_id"],
                        canonical_json(header), checksum, datetime.now(UTC).isoformat()))
                self.index._append_audit(sid, "RECORDING_CREATED", {"header_sha256": checksum},
                                         actor=header["operator_id"], revision=1)
            result = self.status(sid)
        return result

    def append(self, session_id, payload):
        if not isinstance(payload, dict) or set(payload) != {"operation_id", "header_sha256", "chunk_id", "frames_json", "sha256"}:
            raise ValueError("MEASUREMENT_INVALID: chunk envelope")
        if not isinstance(payload["chunk_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", payload["chunk_id"]):
            raise ValueError("MEASUREMENT_INVALID: chunk_id")
        raw = payload["frames_json"]
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_CHUNK_BYTES:
            raise ValueError("MEASUREMENT_INVALID: bounded frames_json required")
        frames = validate_frames(strict_json_loads(raw))
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if checksum != payload["sha256"]:
            raise ValueError("RECORDING_CONFLICT: chunk digest")
        first, last = frames[0], frames[-1]
        with self.index.transaction():
            row = self._row(session_id)
            if payload["operation_id"] != row["operation_id"] or payload["header_sha256"] != row["header_sha256"]:
                raise ValueError("RECORDING_CONFLICT: operation or header")
            try:
                duplicate = self.index.conn.execute("SELECT * FROM recording_chunks WHERE chunk_id=?", (payload["chunk_id"],)).fetchone()
                if duplicate:
                    if duplicate["session_id"] != session_id or duplicate["sha256"] != checksum:
                        raise ValueError("RECORDING_CONFLICT: chunk identity")
                    if duplicate["frames_json"] != raw:
                        raise ValueError("RECORDING_CORRUPT: stored retry differs")
                else:
                    if row["state"] != "RECORDING":
                        raise ValueError("RECORDING_FINALIZED: completed data is immutable")
                    for existing in self._chunks(session_id):
                        if first["sequence"] <= existing["last_sequence"] and last["sequence"] >= existing["first_sequence"]:
                            raise ValueError("RECORDING_CONFLICT: overlapping sequence")
                        if (existing["last_sequence"] < first["sequence"] and existing["last_time_ms"] >= first["time_ms"] or
                                existing["first_sequence"] > last["sequence"] and existing["first_time_ms"] <= last["time_ms"]):
                            raise ValueError("MEASUREMENT_INVALID: cross-chunk timestamps")
            except (ValueError, TypeError):
                # Preserve integrity-error precedence for rejected read-only preflight.
                for _ in self.iter_frames(session_id):
                    pass
                raise
            if not duplicate:
                self.index.conn.execute("INSERT INTO recording_chunks VALUES (?,?,?,?,?,?,?,?)",
                    (payload["chunk_id"], session_id, first["sequence"], last["sequence"],
                     first["time_ms"], last["time_ms"], raw, checksum))
                revision = row["revision"] + 1
                self.index.conn.execute("UPDATE recordings SET revision=? WHERE session_id=?", (revision, session_id))
                self.index._append_audit(session_id, "RECORDING_CHUNK_SAVED",
                    {"chunk_id": payload["chunk_id"], "sha256": checksum,
                     "first_sequence": first["sequence"], "last_sequence": last["sequence"]}, revision=revision)
            result = self.status(session_id)
        return result

    @staticmethod
    def _current_semantic_profile():
        # Retain callable objects (not recycled ids), code and immutable contract facts.
        functions = (validate_frames, strict_json_loads, frame_contract.validate_frames,
                     frame_contract._object, frame_contract._number, frame_contract.invalid,
                     frame_contract.canonical_json, json_contract.strict_json_loads,
                     json_contract.json.loads, frame_contract.json.dumps,
                     json_contract.json.JSONDecoder, json_contract.json.JSONDecoder.__init__,
                     json_contract.json.JSONDecoder.decode, json_contract.json.JSONDecoder.raw_decode,
                     frame_contract.json.JSONEncoder, frame_contract.json.JSONEncoder.__init__,
                     frame_contract.json.JSONEncoder.encode, frame_contract.json.JSONEncoder.iterencode,
                     frame_contract.math.isfinite)
        implementations = tuple((function, getattr(function, "__code__", None),
                                 getattr(function, "__defaults__", None),
                                 tuple(sorted((getattr(function, "__kwdefaults__", None) or {}).items())))
                                for function in functions)
        return ("kinelab.recording-semantic-proof.v1", implementations, MAX_CHUNK_BYTES,
                frame_contract.MAX_CHUNK_BYTES, frame_contract.MAX_CHUNK_FRAMES,
                frame_contract.MAX_FRAMES, frame_contract.MAX_DURATION_MS,
                frame_contract.sys.float_info.max, tuple(sorted(frame_contract.REASONS)),
                tuple(frame_contract.REQUIRED_JOINTS), _SEMANTIC_PROOF_LIMIT)

    def iter_frames(self, session_id):
        # Materialization and manifests always independently decode and validate.
        yield from self._checked_frames(session_id)

    def _checked_frames(self, session_id, *, status_only=False):
        with self.index.read_snapshot():
            recording = self._row(session_id)
            self._verify_receipts(session_id, status_only=status_only)
            context = None
            if status_only:
                profile = self._current_semantic_profile()
                if self._semantic_connection is not self.index.conn or self._semantic_profile != profile:
                    self._semantic_proofs.clear()
                    self._semantic_connection, self._semantic_profile = self.index.conn, profile
                context = (session_id, recording["operation_id"], recording["capture_id"],
                           recording["header_sha256"],
                           hashlib.sha256(recording["header_json"].encode("utf-8")).hexdigest())
            previous_sequence = previous_time = None
            for row in self.index.conn.execute("SELECT * FROM recording_chunks WHERE session_id=? ORDER BY first_sequence", (session_id,)):
                raw = row["frames_json"]
                wire_bytes = raw.encode("utf-8") if type(raw) is str else None
                if (not isinstance(raw, str) or
                        len(wire_bytes if wire_bytes is not None else raw.encode("utf-8")) > MAX_CHUNK_BYTES):
                    raise ValueError("RECORDING_CORRUPT: stored chunk exceeds byte bound")
                checksum = hashlib.sha256(wire_bytes if wire_bytes is not None else raw.encode("utf-8")).hexdigest()
                key = (context, hashlib.sha256(row["chunk_id"].encode("utf-8")).digest(), checksum) if status_only else None
                facts = self._semantic_proofs.get(key) if status_only and checksum == row["sha256"] else None
                frames = None
                if facts is None:
                    try:
                        frames = validate_frames(strict_json_loads(raw))
                    except ValueError as error:
                        raise ValueError("RECORDING_CORRUPT: stored chunk frames") from error
                    facts = (frames[0]["sequence"], frames[-1]["sequence"],
                             frames[0]["time_ms"], frames[-1]["time_ms"])
                if (checksum != row["sha256"] or facts[0] != row["first_sequence"] or
                        facts[1] != row["last_sequence"] or
                        facts[2] != row["first_time_ms"] or facts[3] != row["last_time_ms"]):
                    raise ValueError("RECORDING_CORRUPT: chunk")
                if previous_sequence is not None and (facts[0] <= previous_sequence or facts[2] <= previous_time):
                    raise ValueError("RECORDING_CORRUPT: cross-chunk sequence or timestamps")
                previous_sequence, previous_time = facts[1], facts[3]
                if status_only:
                    # Semantic facts attest only these exact bytes, never a commit or ACK.
                    if key not in self._semantic_proofs:
                        if len(self._semantic_proofs) >= _SEMANTIC_PROOF_LIMIT:
                            self._semantic_proofs.pop(next(iter(self._semantic_proofs)))
                        self._semantic_proofs[key] = facts
                    yield row
                else:
                    yield from frames

    def _receipt_details(self, raw, memo, limits):
        if memo is not None and type(raw) is str and len(raw) <= limits[1]:
            facts = memo.get(raw)
            if facts is not None:
                return dict(facts)
        return strict_json_loads(raw)

    def _verify_receipts(self, session_id, *, status_only=False):
        conn, limits = self.index.conn, _receipt_limits()
        bindings = _receipt_bindings()
        enabled = (status_only and limits is not None and _RECEIPT_PARSE_PROFILE is not None
                   and _receipt_same(bindings, _RECEIPT_PARSE_PROFILE))
        if (not enabled or self._receipt_connection is not conn or self._receipt_limits_used != limits):
            self._receipt_proofs.clear()
            self._receipt_connection, self._receipt_limits_used = conn if enabled else None, limits if enabled else None
        memo = self._receipt_proofs if enabled else None
        try:
            self._verify_receipts_scan(session_id, memo, limits)
        finally:
            # Refuse a changed validation context even when every details lookup was a hit.
            if memo is not None and (self.index.conn is not conn or _receipt_limits() != limits
                                     or not _receipt_same(_receipt_bindings(), _RECEIPT_PARSE_PROFILE)):
                self._receipt_proofs.clear()
                self._receipt_connection, self._receipt_limits_used = None, None
                raise ValueError("RECORDING_CORRUPT: receipt validation context changed")

    def _verify_receipts_scan(self, session_id, memo=None, limits=None):
        row = self._row(session_id)
        parts = {part["chunk_id"]: dict(part) for part in self._chunks(session_id)}
        self.index.verify_audit()
        events = self.index.conn.execute("SELECT * FROM audit_events WHERE session_id=? AND event_type LIKE 'RECORDING_%' ORDER BY id",
                                         (session_id,)).fetchall()
        finalized = row["state"] == "FINALIZED"
        if len(events) != len(parts) + 1 + int(finalized) or row["revision"] != len(events):
            raise ValueError("RECORDING_CORRUPT: audit generation")
        seen = set()
        for revision, event in enumerate(events, 1):
            try:
                details = self._receipt_details(event["details_json"], memo, limits)
            except ValueError as error:
                raise ValueError("RECORDING_CORRUPT: audit receipt JSON") from error
            if not isinstance(details, dict) or not details:
                raise ValueError("RECORDING_CORRUPT: audit receipt object")
            kind = event["event_type"]
            if revision == 1:
                expected = {"header_sha256": row["header_sha256"]}
                expected_kind = "RECORDING_CREATED"
            elif finalized and revision == len(events):
                expected = {"manifest_sha256": row["manifest_sha256"]}
                expected_kind = "RECORDING_FINALIZED"
            else:
                chunk_id = details.get("chunk_id")
                part = parts.get(chunk_id) if isinstance(chunk_id, str) else None
                if part is None or part["chunk_id"] in seen:
                    raise ValueError("RECORDING_CORRUPT: chunk audit identity")
                seen.add(part["chunk_id"])
                expected = {key: part[key] for key in ("chunk_id", "sha256", "first_sequence", "last_sequence")}
                expected_kind = "RECORDING_CHUNK_SAVED"
            if details != expected or kind != expected_kind or event["revision"] != revision:
                raise ValueError("RECORDING_CORRUPT: audit receipt mismatch")
            raw = event["details_json"]
            if memo is not None and type(raw) is str and len(raw) <= limits[1] and raw not in memo and _receipt_flat(details):
                if len(memo) >= limits[0]:
                    memo.pop(next(iter(memo)))
                memo[raw] = tuple(details.items())

    def _manifest(self, session_id, end_reason):
        if end_reason not in ("operator_finished", "recovered_prefix", "capture_interrupted"):
            raise ValueError("MEASUREMENT_INVALID: end_reason")
        row = self._row(session_id)
        count = valid = 0
        first_time = last_time = None
        last_sequence = 0
        for frame in self.iter_frames(session_id):
            if frame["sequence"] != last_sequence + 1 or (last_time is not None and frame["time_ms"] <= last_time):
                raise ValueError("RECORDING_CORRUPT: sequence or timestamp")
            last_sequence = frame["sequence"]
            count += 1; valid += int(frame["valid"])
            if first_time is None:
                first_time = frame["time_ms"]
            last_time = frame["time_ms"]
        return {"schema": "kinelab.recording-manifest.v1", "session_id": session_id,
                "operation_id": row["operation_id"], "header_sha256": row["header_sha256"], "source_kind": "synthetic",
                "frame_count": count, "valid_frame_count": valid, "last_sequence": last_sequence,
                "first_time_ms": first_time, "last_time_ms": last_time,
                "end_reason": end_reason, "unacknowledged_tail": "NONE_REPORTED" if end_reason == "operator_finished" else "UNKNOWN",
                "chunks": [dict(part) for part in self._chunks(session_id)],
                "physical_accuracy_verified": False, "clinical_validation": "UNVERIFIED"}

    def verify(self, session_id):
        with self.index.read_snapshot():
            status = self.status(session_id)
            if status["state"] == "FINALIZED":
                if status["manifest"] != self._manifest(session_id, status["manifest"].get("end_reason")):
                    raise ValueError("RECORDING_CORRUPT: final manifest differs from stored frames")
            else:
                for _ in self.iter_frames(session_id):
                    pass
            return status

    def finalize(self, session_id, operation_id, last_sequence, *, end_reason="operator_finished"):
        if type(last_sequence) is not int or last_sequence < 1:
            raise ValueError("MEASUREMENT_INVALID: last_sequence")
        with self.index.transaction():
            row = self._row(session_id)
            status = self.status(session_id)
            if operation_id != row["operation_id"]:
                raise ValueError("RECORDING_CONFLICT: operation")
            if row["state"] == "FINALIZED":
                if status["saved_through"] != last_sequence or status["manifest"]["end_reason"] != end_reason:
                    raise ValueError("RECORDING_CONFLICT: finalized length")
                if status["manifest"] != self._manifest(session_id, status["manifest"].get("end_reason")):
                    raise ValueError("RECORDING_CORRUPT: final manifest differs from stored frames")
                result = status
            else:
                if status["saved_through"] != last_sequence or status["received_through"] != last_sequence:
                    raise ValueError("RECORDING_INCOMPLETE: sequence gaps or unexpected final length")
                manifest = self._manifest(session_id, end_reason)
                checksum, revision = digest(manifest), row["revision"] + 1
                self.index.conn.execute("""UPDATE recordings SET state='FINALIZED', revision=?,
                    manifest_json=?, manifest_sha256=? WHERE session_id=?""",
                    (revision, canonical_json(manifest), checksum, session_id))
                self.index._append_audit(session_id, "RECORDING_FINALIZED", {"manifest_sha256": checksum}, revision=revision)
                result = self.status(session_id)
        return result


# Snapshot once; a changed parser is used uncached, never admitted as another pure profile.
_RECEIPT_PARSE_PROFILE = _receipt_bindings()
