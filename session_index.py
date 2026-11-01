"""SQLite-backed metadata index and Evidence Passport state machine for KineLab PT.

Local-first, immutable source media: this database indexes files and provenances only.
Original MP4, TRC, MOT and manifest files in projects/ remain authoritative.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from capture_station import RAW_ROLES, probe_clip
from session_contract import load_session, sha256_file, strict_json_loads, validate_session_metadata
from session_library import SessionLibrary
from take_acceptance import checked_path

SCHEMA_VERSION = 3
INDEXED_EVIDENCE_FILES = ("session.json", "normalization.json", "preflight.json", "sync-observations.json",
                          "sync.json", "run.json", "board-measurement.json")

# Private process-local memo of pure _event_hash results, consulted only by verify_audit. A key holds the
# exact nine hashed inputs; a hit replaces one digest computation, never a row read, link or hash check.
_AUDIT_HASH_FIELDS = ("event_id", "session_id", "event_type", "details_json", "timestamp_utc",
                      "actor", "revision", "outcome", "previous_hash")
_AUDIT_REVISION_FIELD = 6
# One budget covers retained and in-flight pending facts together.
_AUDIT_MEMO_MAX_ENTRIES = 4096
_AUDIT_MEMO_MAX_BYTES = 8 * 1024 * 1024
_AUDIT_MEMO_MAX_ENTRY_BYTES = 64 * 1024
# Conservative charge for the key tuple, its objects, the digest and the dict slot; text is charged at four
# bytes per code point, the widest CPython string storage. A retained-memory bound, not an RSS claim.
_AUDIT_MEMO_ENTRY_OVERHEAD = 1024
_AUDIT_DIGEST_CHARACTERS = frozenset("0123456789abcdef")
_JSON_ENCODER_BINDINGS = ("JSONEncoder", "INFINITY", "c_make_encoder", "_make_iterencode", "encode_basestring",
                          "encode_basestring_ascii", "c_encode_basestring", "c_encode_basestring_ascii",
                          "py_encode_basestring", "py_encode_basestring_ascii")
_JSON_ENCODER_METHODS = ("__init__", "encode", "iterencode", "default")


def _function_facts(function: object) -> tuple[object, ...]:
    kwdefaults = getattr(function, "__kwdefaults__", None)
    return (function, getattr(function, "__code__", None), getattr(function, "__defaults__", None), kwdefaults,
            tuple(kwdefaults.items()) if type(kwdefaults) is dict else None)


def _audit_hash_bindings(hash_function: object) -> tuple[object, ...]:
    """Every binding the pure audit digest reaches; any identity difference disables the memo."""
    module = globals()
    encoder_module = getattr(json, "encoder", None)
    encoder_class = getattr(json, "JSONEncoder", None)
    methods = getattr(encoder_class, "__dict__", {})
    return (_function_facts(hash_function), module.get("json"), module.get("hashlib"),
            _function_facts(getattr(json, "dumps", None)), getattr(json, "_default_encoder", None), encoder_class,
            encoder_module, tuple(_function_facts(getattr(encoder_module, name, None)) for name in _JSON_ENCODER_BINDINGS),
            tuple(_function_facts(methods.get(name)) for name in _JSON_ENCODER_METHODS),
            getattr(hashlib, "sha256", None))


def _supported_audit_hash_profile() -> tuple[object, ...] | None:
    """Enable the memo only when the audit digest uses the native JSON encoder path at import."""
    encoder_module = getattr(json, "encoder", None)
    native = getattr(encoder_module, "c_encode_basestring_ascii", None)
    if (getattr(encoder_module, "c_make_encoder", None) is None or native is None
            or getattr(encoder_module, "encode_basestring_ascii", None) is not native):
        return None
    return _audit_hash_bindings(SessionIndex.__dict__["_event_hash"].__func__)


def _same_binding(left: object, right: object) -> bool:
    if type(left) is tuple and type(right) is tuple:
        return len(left) == len(right) and all(_same_binding(a, b) for a, b in zip(left, right, strict=True))
    return left is right


def _audit_memo_limits() -> tuple[int, int, int] | None:
    limits = (_AUDIT_MEMO_MAX_ENTRIES, _AUDIT_MEMO_MAX_BYTES, _AUDIT_MEMO_MAX_ENTRY_BYTES)
    return limits if all(type(limit) is int and limit > 0 for limit in limits) else None


def _audit_memo_key(event: dict) -> tuple[object, ...] | None:
    """Exact builtin str/int inputs only, so equal-comparing bool/float/subclass values never alias."""
    try:
        key = tuple(event[name] for name in _AUDIT_HASH_FIELDS)
    except KeyError:
        return None
    revision = key[_AUDIT_REVISION_FIELD]
    if type(revision) is not int or not -(2 ** 63) <= revision < 2 ** 63:
        return None
    if any(type(value) is not str for position, value in enumerate(key) if position != _AUDIT_REVISION_FIELD):
        return None
    return key


def _audit_memo_cost(key: tuple[object, ...]) -> int:
    return _AUDIT_MEMO_ENTRY_OVERHEAD + 4 * sum(len(value) for value in key if type(value) is str)


def _audit_digest_admissible(digest: object) -> bool:
    return type(digest) is str and len(digest) == 64 and _AUDIT_DIGEST_CHARACTERS.issuperset(digest)


class PassportState:
    EMPTY = "EMPTY"
    DRAFT = "DRAFT"
    SIX_FILES_PROBED = "SIX_FILES_PROBED"
    REGISTERED_ORIGINALS = "REGISTERED_ORIGINALS"
    NORMALIZATION_PASSED = "NORMALIZATION_PASSED"
    CALIBRATION_PASSED = "CALIBRATION_PASSED"
    SYNC_PASSED = "SYNC_PASSED"
    TRIPOD_3D_PASSED = "3D_PASSED"
    KINEMATICS_PASSED = "KINEMATICS_PASSED"
    RESEARCH_REPORTABLE = "RESEARCH_REPORTABLE"


class SessionIndex:
    def __init__(self, db_path: Path | str, projects_root: Path | str, *, read_only=False, existing_only=False):
        if read_only and existing_only:
            raise ValueError("INDEX_OPEN_MODE_INVALID")
        self.db_path = checked_path(Path(db_path)).resolve()
        self.projects_root = checked_path(Path(projects_root)).resolve()
        self.library = SessionLibrary(self.projects_root)
        if not (read_only or existing_only):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "ro" if read_only else "rw" if existing_only else None
        self.conn = sqlite3.connect(
            self.db_path.as_uri() + "?mode=" + mode if mode else str(self.db_path),
            uri=mode is not None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA trusted_schema=OFF")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=FULL")
        self._lock = RLock()
        self._reset_audit_memo(None, None)
        self._audit_hash_pending: deque[tuple[tuple[object, ...], str, int]] | None = None
        self._audit_hash_pending_bytes = 0
        try:
            if read_only or existing_only:
                version = self.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                if version != SCHEMA_VERSION:
                    raise ValueError("SCHEMA_UNSUPPORTED: recovery requires the current index schema")
                self.verify_audit()
            else:
                self._init_schema()
        except Exception:
            self.close()
            raise

    def _init_schema(self):
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )
            """)
            cur = self.conn.execute("SELECT MAX(version) AS ver FROM schema_migrations")
            row = cur.fetchone()
            current_ver = row["ver"] if row and row["ver"] is not None else 0
            if current_ver > SCHEMA_VERSION:
                raise ValueError(f"SCHEMA_UNSUPPORTED: index version {current_ver}; supported {SCHEMA_VERSION}")

            if current_ver < 1:
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        status TEXT NOT NULL,
                        captured_roles INTEGER NOT NULL DEFAULT 0,
                        can_register INTEGER NOT NULL DEFAULT 0,
                        board_measured INTEGER NOT NULL DEFAULT 0,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS sources (
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        bytes INTEGER NOT NULL,
                        width INTEGER,
                        height INTEGER,
                        fps REAL,
                        duration REAL,
                        PRIMARY KEY (session_id, role),
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS board_measurements (
                        session_id TEXT PRIMARY KEY,
                        expected_square_mm REAL NOT NULL,
                        measured_square_mm REAL NOT NULL,
                        measured_by TEXT NOT NULL,
                        recorded_at_utc TEXT NOT NULL,
                        source TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS runs (
                        session_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        state TEXT NOT NULL,
                        passed INTEGER NOT NULL,
                        config_sha256 TEXT,
                        error_message TEXT,
                        updated_at_utc TEXT NOT NULL,
                        PRIMARY KEY (session_id, stage),
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS artifacts (
                        session_id TEXT NOT NULL,
                        artifact_key TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        artifact_type TEXT NOT NULL,
                        bytes INTEGER NOT NULL,
                        sha256 TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        PRIMARY KEY (session_id, artifact_key),
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        timestamp_utc TEXT NOT NULL
                    )
                """)
                self.conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at_utc) VALUES (?, ?)",
                    (1, datetime.now(UTC).isoformat())
                )

            if current_ver < 2:
                self.conn.execute("ALTER TABLE sessions ADD COLUMN evidence_errors_json TEXT NOT NULL DEFAULT '[]'")
                self.conn.execute("ALTER TABLE sessions ADD COLUMN present INTEGER NOT NULL DEFAULT 1")
                for table in ("sources", "artifacts"):
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN observed_sha256 TEXT")
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN integrity_state TEXT NOT NULL DEFAULT 'unverified'")
                for definition in ("event_id TEXT", "actor TEXT NOT NULL DEFAULT 'system'",
                                   "revision INTEGER NOT NULL DEFAULT 0", "outcome TEXT NOT NULL DEFAULT 'recorded'",
                                   "previous_hash TEXT", "event_hash TEXT"):
                    self.conn.execute("ALTER TABLE audit_events ADD COLUMN " + definition)
                previous = "0" * 64
                for row in self.conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall():
                    event = dict(row)
                    event.update(event_id=uuid4().hex, previous_hash=previous)
                    previous = self._event_hash(event)
                    self.conn.execute("UPDATE audit_events SET event_id=?, previous_hash=?, event_hash=? WHERE id=?",
                                      (event["event_id"], event["previous_hash"], previous, event["id"]))
                self.conn.execute("CREATE UNIQUE INDEX audit_event_identity ON audit_events(event_id)")
                for action in ("UPDATE", "DELETE"):
                    self.conn.execute(f"CREATE TRIGGER audit_no_{action.lower()} BEFORE {action} ON audit_events "
                                      "BEGIN SELECT RAISE(ABORT, 'AUDIT_IMMUTABLE'); END")
                self.conn.execute("INSERT INTO schema_migrations VALUES (?, ?)",
                                  (2, datetime.now(UTC).isoformat()))

            if current_ver < 3:
                from recording_store import create_schema
                create_schema(self.conn)
                self.conn.execute("INSERT INTO schema_migrations VALUES (?, ?)",
                                  (3, datetime.now(UTC).isoformat()))
            self.verify_audit()

    def close(self):
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
            self.conn = None
        self._reset_audit_memo(None, None)

    def __del__(self):
        self.close()

    @staticmethod
    def _event_hash(event):
        fields = ("event_id", "session_id", "event_type", "details_json", "timestamp_utc",
                  "actor", "revision", "outcome", "previous_hash")
        data = json.dumps({key: event[key] for key in fields}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(data.encode()).hexdigest()

    def _append_audit(self, session_id, event_type, details, *, actor="system", revision=0, outcome="recorded"):
        previous = self.conn.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
        event = {"event_id": uuid4().hex, "session_id": session_id, "event_type": event_type,
                 "details_json": json.dumps(details, sort_keys=True, allow_nan=False),
                 "timestamp_utc": datetime.now(UTC).isoformat(), "actor": actor,
                 "revision": revision, "outcome": outcome, "previous_hash": previous[0] if previous else "0" * 64}
        event["event_hash"] = self._event_hash(event)
        keys = list(event)
        self.conn.execute(f"INSERT INTO audit_events ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                          [event[key] for key in keys])

    def record_audit_event(self, session_id: str, event_type: str, details: dict, **context):
        with self.transaction():
            self._append_audit(session_id, event_type, details, **context)

    @contextmanager
    def transaction(self):
        """Serialize the read of the audit tip with all writes, across connections."""
        with self._lock, self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            yield

    @contextmanager
    def read_snapshot(self):
        with self._lock:
            if self.conn.in_transaction:
                yield
            else:
                with self.conn:
                    self.conn.execute("BEGIN")
                    yield

    def _reset_audit_memo(self, conn, limits):
        self._audit_hash_memo: dict[tuple[object, ...], tuple[str, int]] = {}
        self._audit_hash_memo_conn = conn
        self._audit_hash_memo_limits = limits
        self._audit_hash_memo_bytes = 0

    def _audit_profile_intact(self):
        return _AUDIT_HASH_PROFILE is not None and _same_binding(
            _audit_hash_bindings(getattr(self, "_event_hash", None)), _AUDIT_HASH_PROFILE)

    def _audit_memo(self, conn):
        """Return the memo bound to this live connection, or None when the original pure profile is not intact."""
        if conn is None:
            return None, None
        limits = _audit_memo_limits()
        if limits is None or not self._audit_profile_intact():
            self._reset_audit_memo(None, None)
            return None, None
        if self._audit_hash_memo_conn is not conn or self._audit_hash_memo_limits != limits:
            self._reset_audit_memo(conn, limits)
        return self._audit_hash_memo, limits

    def _publish_audit_memo(self, conn, memo, limits, pending):
        if self.conn is not conn or self._audit_hash_memo is not memo or self._audit_hash_memo_limits != limits:
            return
        if not self._audit_profile_intact():
            self._reset_audit_memo(None, None)
            return
        max_entries, max_bytes, _ = limits
        # Drain each fact out of pending before retaining it, so retained+pending stays within one budget.
        while pending:
            key, digest, cost = pending.popleft()
            self._audit_hash_pending_bytes -= cost
            if key in memo:
                continue
            while memo and (len(memo) + len(pending) >= max_entries
                            or self._audit_hash_memo_bytes + self._audit_hash_pending_bytes + cost > max_bytes):
                self._audit_hash_memo_bytes -= memo.pop(next(iter(memo)))[1]
            memo[key] = (digest, cost)
            self._audit_hash_memo_bytes += cost

    def _verify_audit_uncached(self, conn):
        previous = "0" * 64
        for row in conn.execute("SELECT * FROM audit_events ORDER BY id"):
            event = dict(row)
            if event["previous_hash"] != previous or event["event_hash"] != self._event_hash(event):
                raise ValueError("AUDIT_INVALID: event " + str(event["id"]))
            previous = event["event_hash"]
        return previous

    def _replay_audit_uncached(self, conn):
        # A hash dependency changed after the opening check: drop stale facts and let one original scan decide.
        self._reset_audit_memo(None, None)
        return self._verify_audit_uncached(conn)

    def verify_audit(self):
        # The existing reentrant lock serializes memo-assisted scans, so one pending budget exists per instance.
        with self._lock:
            conn = self.conn
            memo, limits = self._audit_memo(conn)
            if memo is None or self._audit_hash_pending is not None:
                return self._verify_audit_uncached(conn)
            self._audit_hash_pending, self._audit_hash_pending_bytes = deque(), 0
            try:
                return self._verify_audit_with_memo(conn, memo, limits, self._audit_hash_pending)
            finally:
                self._audit_hash_pending, self._audit_hash_pending_bytes = None, 0

    def _verify_audit_with_memo(self, conn, memo, limits, pending):
        max_entries, max_bytes, max_entry_bytes = limits
        hits, previous = 0, "0" * 64
        for row in conn.execute("SELECT * FROM audit_events ORDER BY id"):
            event = row
            if event["previous_hash"] != previous:
                if hits and not self._audit_profile_intact():
                    return self._replay_audit_uncached(conn)
                raise ValueError("AUDIT_INVALID: event " + str(event["id"]))
            key = _audit_memo_key(event)
            fact = memo.get(key) if key is not None else None
            if fact is not None:
                hits += 1
                digest = fact[0]
            else:
                if hits and not self._audit_profile_intact():
                    return self._replay_audit_uncached(conn)
                event = dict(event)
                digest = self._event_hash(event)
                cost = _audit_memo_cost(key) if key is not None else 0
                if (key is not None and cost <= min(max_bytes, max_entry_bytes) and _audit_digest_admissible(digest)
                        and self._audit_hash_memo is memo):
                    # Evicting an old pure fact is always safe; new facts publish only after the full scan passes.
                    while (len(memo) + len(pending) >= max_entries
                           or self._audit_hash_memo_bytes + self._audit_hash_pending_bytes + cost > max_bytes):
                        if memo:
                            self._audit_hash_memo_bytes -= memo.pop(next(iter(memo)))[1]
                        else:
                            self._audit_hash_pending_bytes -= pending.popleft()[2]
                    pending.append((key, digest, cost))
                    self._audit_hash_pending_bytes += cost
            if event["event_hash"] != digest:
                if hits and not self._audit_profile_intact():
                    return self._replay_audit_uncached(conn)
                raise ValueError("AUDIT_INVALID: event " + str(event["id"]))
            previous = event["event_hash"]
        if hits and not self._audit_profile_intact():
            return self._replay_audit_uncached(conn)
        self._publish_audit_memo(conn, memo, limits, pending)
        return previous

    def reindex(self) -> set[str]:
        """Reconcile digests; return observed changes for refusal diagnostics only."""
        listed = self.library.list_sessions()
        changed_timing_sources = {
            item["id"] for item in listed
            if str(item.get("research_source_revision", {}).get("reason") or "").startswith("COMPARISON_CHANGED:")
        }
        now = datetime.now(UTC).isoformat()
        with self.transaction():
            self.verify_audit()
            present = {item["id"] for item in listed}
            for row in self.conn.execute("SELECT id FROM sessions WHERE present=1").fetchall():
                if row["id"] not in present:
                    self.conn.execute("UPDATE sessions SET present=0, status='missing', can_register=0 WHERE id=?", (row["id"],))
                    self._append_audit(row["id"], "EVIDENCE_INVALIDATED", {"reason": "session_missing"})
            for s in listed:
                sid = s["id"]
                folder = self.projects_root / sid
                desc = self.library.describe_session(sid)
                observation = desc.get("research_source_revision", {})
                if str(observation.get("reason") or "").startswith("COMPARISON_CHANGED:"):
                    changed_timing_sources.add(sid)
                previous = self.conn.execute("SELECT evidence_errors_json FROM sessions WHERE id=?", (sid,)).fetchone()
                self.conn.execute("""
                    INSERT INTO sessions (id, kind, status, captured_roles, can_register, board_measured, created_at_utc, updated_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind,
                        status=excluded.status,
                        captured_roles=excluded.captured_roles,
                        can_register=excluded.can_register,
                        board_measured=excluded.board_measured,
                        present=1,
                        updated_at_utc=excluded.updated_at_utc
                """, (
                    sid, desc["kind"], desc["status"], desc["captured_roles"],
                    int(desc["can_register"]), 0, now, now
                ))
                self.conn.execute("DELETE FROM board_measurements WHERE session_id=?", (sid,))
                self.conn.execute("DELETE FROM runs WHERE session_id=?", (sid,))
                for role in RAW_ROLES:
                    mp4 = folder / "raw" / (role + ".mp4")
                    digest = self._contained_digest(folder, mp4)
                    if digest:
                        meta = {}
                        if not self.conn.execute("SELECT 1 FROM sources WHERE session_id=? AND role=?", (sid, role)).fetchone():
                            try:
                                meta = probe_clip(mp4)
                            except (ValueError, OSError, RuntimeError):
                                pass
                        self.conn.execute("""INSERT OR IGNORE INTO sources
                            (session_id, role, filename, sha256, bytes, width, height, fps, duration)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (sid, role, mp4.name, digest, mp4.stat().st_size, meta.get("width"),
                             meta.get("height"), meta.get("fps"), meta.get("duration")))
                    self.conn.execute("""UPDATE sources SET observed_sha256=?,
                        integrity_state=CASE WHEN ? IS NULL THEN 'missing' WHEN sha256=? THEN 'unchanged' ELSE 'changed' END
                        WHERE session_id=? AND role=?""", (digest, digest, digest, sid, role))

                board_path = folder / "board-measurement.json"
                errors = []
                if board_path.is_file():
                    try:
                        bdata = strict_json_loads(board_path.read_text(encoding="utf-8-sig"))
                        for key in ("expected_square_mm", "measured_square_mm"):
                            if type(bdata.get(key)) not in (int, float) or bdata[key] <= 0:
                                raise ValueError("invalid " + key)
                        for key in ("measured_by", "recorded_at_utc", "source"):
                            if not isinstance(bdata.get(key), str) or not bdata[key].strip():
                                raise ValueError("missing " + key)
                        self.conn.execute("""
                            INSERT INTO board_measurements (session_id, expected_square_mm, measured_square_mm, measured_by, recorded_at_utc, source)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (sid, bdata["expected_square_mm"], bdata["measured_square_mm"],
                              bdata["measured_by"], bdata["recorded_at_utc"], bdata["source"]))
                        self.conn.execute("UPDATE sessions SET board_measured=1 WHERE id=?", (sid,))
                    except (OSError, ValueError, TypeError, AttributeError):
                        errors.append("BOARD_INVALID")

                run_path = folder / "run.json"
                if run_path.is_file():
                    try:
                        rdata = strict_json_loads(run_path.read_text(encoding="utf-8-sig"))
                        cfg_h = rdata.get("config_sha256")
                        stages = rdata.get("stages", [])
                        if isinstance(stages, dict):
                            stages = [dict(info, name=name) for name, info in stages.items()]
                        if not isinstance(stages, list):
                            raise TypeError("invalid stages")
                        for st_info in stages:
                            st_name = st_info["name"]
                            if not isinstance(st_name, str):
                                raise TypeError("invalid stage name")
                            self.conn.execute("""
                                INSERT INTO runs (session_id, stage, state, passed, config_sha256, error_message, updated_at_utc)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (sid, st_name, st_info.get("status", "unknown"), 0, cfg_h,
                                  st_info.get("error") or "QUALITY_UNVERIFIED: ordered run evidence required", now))
                        from run_pipeline import STAGES, validate_run_evidence
                        prefix = []
                        for name, item in zip(STAGES, stages):
                            if item.get("name") != name or item.get("status") != "passed":
                                break
                            prefix.append(name)
                        if prefix:
                            try:
                                verified = validate_run_evidence(folder, prefix[-1])
                                for name in verified["stages"]:
                                    self.conn.execute("UPDATE runs SET passed=1, error_message=NULL WHERE session_id=? AND stage=?", (sid, name))
                            except (OSError, ValueError) as error:
                                self.conn.execute("UPDATE runs SET error_message=? WHERE session_id=?", (str(error), sid))
                    except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.IntegrityError):
                        self.conn.execute("DELETE FROM runs WHERE session_id=?", (sid,))
                        errors.append("RUN_INVALID")

                names = set(INDEXED_EVIDENCE_FILES)
                names.update("exports/" + exp.name for exp in (folder / "exports").glob("*.motion.json"))
                names.update(row[0] for row in self.conn.execute("SELECT artifact_key FROM artifacts WHERE session_id=?", (sid,)))
                for art_name in sorted(names):
                    cand = folder / art_name
                    digest = self._contained_digest(folder, cand)
                    if digest:
                        self.conn.execute("""
                            INSERT OR IGNORE INTO artifacts (session_id, artifact_key, filename, artifact_type, bytes, sha256, created_at_utc)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (sid, art_name, cand.name, "motion_export" if art_name.startswith("exports/") else "evidence_manifest",
                              cand.stat().st_size, digest, now))
                    self.conn.execute("""UPDATE artifacts SET observed_sha256=?,
                        integrity_state=CASE WHEN ? IS NULL THEN 'missing' WHEN sha256=? THEN 'unchanged' ELSE 'changed' END
                        WHERE session_id=? AND artifact_key=?""", (digest, digest, digest, sid, art_name))
                errors.extend(self._integrity_issues(sid, folder, desc))
                encoded = json.dumps(sorted(set(errors)))
                self.conn.execute("UPDATE sessions SET evidence_errors_json=?, status=CASE WHEN ?='[]' THEN status ELSE 'invalid' END WHERE id=?", (encoded, encoded, sid))
                if errors and (not previous or previous[0] != encoded):
                    self._append_audit(sid, "EVIDENCE_INVALIDATED", {"reasons": sorted(set(errors))})
        return changed_timing_sources

    @staticmethod
    def _contained_digest(folder, path):
        try:
            if not path.resolve().is_relative_to(folder.resolve()):
                return None
            for part in (path, *path.parents):
                if part == folder:
                    break
                if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                    return None
            return sha256_file(path) if path.is_file() else None
        except OSError:
            return None

    def _integrity_issues(self, sid, folder, desc):
        errors = ["SESSION_INVALID"] if desc["status"] == "invalid" else []
        for table, key in (("sources", "role"), ("artifacts", "artifact_key")):
            for row in self.conn.execute(f"SELECT * FROM {table} WHERE session_id=?", (sid,)):
                name = "raw/" + row["role"] + ".mp4" if table == "sources" else row[key]
                observed = self._contained_digest(folder, folder / name)
                if observed != row["sha256"]:
                    errors.append(("INPUT_MISSING: " if observed is None else "INPUT_CHANGED: ") + name)
        return errors

    def query_sessions(self, filter_kind: str | None = None, filter_status: str | None = None, search: str | None = None) -> list[dict]:
        query = "SELECT * FROM sessions WHERE 1=1"
        params = []
        if filter_kind:
            query += " AND kind = ?"
            params.append(filter_kind)
        if filter_status:
            query += " AND status = ?"
            params.append(filter_status)
        if search:
            query += " AND id LIKE ?"
            params.append(f"%{search}%")
        query += " ORDER BY updated_at_utc DESC"
        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def get_passport(self, session_id: str) -> dict:
        folder = self.projects_root / session_id
        if not folder.is_dir():
            raise FileNotFoundError(f"Session {session_id} not found")
        desc = self.library.describe_session(session_id)
        is_test_only = (desc["kind"] in ("test-only", "demo"))
        if desc["evidence_status"] == "unverified":
            # Legacy live assets were admitted without measured camera frames.
            # Never infer their source from metadata, export presence or a cache hash.
            return {
                "session_id": session_id, "kind": desc["kind"], "badge": "UNVERIFIED",
                "state": "EVIDENCE_UNVERIFIED", "evidence_status": "unverified",
                "history": [{"state": "EVIDENCE_UNVERIFIED", "status": "blocked",
                             "message": "Original acquisition and motion are unverified"}],
                "is_test_only": is_test_only, "can_register_real": False,
                "ready_to_register": False, "captured_count": 0,
                "missing_roles": list(RAW_ROLES), "board_measurement": None,
                "sources": {}, "runs": {}, "clinically_validated": False,
                "physical_accuracy_verified": False,
                "watermark": "SOURCE UNVERIFIED — NOT MEASURED OR CLINICALLY VALIDATED",
            }

        # Check sources
        cur = self.conn.execute("SELECT * FROM sources WHERE session_id = ?", (session_id,))
        sources = [dict(r) for r in cur.fetchall()]
        sources_by_role = {s["role"]: s for s in sources}
        missing_roles = [r for r in RAW_ROLES if r not in sources_by_role]

        # Check board
        cur = self.conn.execute("SELECT * FROM board_measurements WHERE session_id = ?", (session_id,))
        board = cur.fetchone()
        board_dict = dict(board) if board else None

        # Check runs
        cur = self.conn.execute("SELECT * FROM runs WHERE session_id = ?", (session_id,))
        runs = {r["stage"]: dict(r) for r in cur.fetchall()}

        issues = self._integrity_issues(session_id, folder, desc)
        cached = self.conn.execute("SELECT evidence_errors_json FROM sessions WHERE id=?", (session_id,)).fetchone()
        if cached:
            issues = sorted(set(issues + strict_json_loads(cached[0])))
        if issues:
            return {"session_id": session_id, "kind": desc["kind"], "badge": "EVIDENCE INVALID",
                    "state": "EVIDENCE_INVALID", "history": [], "integrity_errors": issues,
                    "is_test_only": is_test_only, "can_register_real": False, "ready_to_register": False,
                    "captured_count": len(sources), "missing_roles": missing_roles,
                    "board_measurement": board_dict, "sources": sources_by_role, "runs": runs,
                    "clinically_validated": False, "physical_accuracy_verified": False,
                    "watermark": "EVIDENCE INVALID — UPSTREAM FILES CHANGED OR MISSING"}

        # Compute State Machine Progression
        state = PassportState.EMPTY
        history = [{"state": PassportState.EMPTY, "status": "passed", "message": "Initialized"}]

        if sources:
            state = PassportState.DRAFT
            history.append({"state": PassportState.DRAFT, "status": "passed", "message": f"{len(sources)}/6 roles captured"})

        if len(sources) == 6 and not missing_roles:
            state = PassportState.SIX_FILES_PROBED
            history.append({"state": PassportState.SIX_FILES_PROBED, "status": "passed", "message": "All 6 role clips probed"})

        if desc["status"] == "registered":
            state = PassportState.REGISTERED_ORIGINALS
            history.append({"state": PassportState.REGISTERED_ORIGINALS, "status": "passed", "message": "Original video hashes registered"})

        if state == PassportState.REGISTERED_ORIGINALS and runs.get("calibration", {}).get("passed"):
            state = PassportState.CALIBRATION_PASSED
            history.append({"state": PassportState.CALIBRATION_PASSED, "status": "passed", "message": "Native camera calibration passed"})

        if state == PassportState.CALIBRATION_PASSED and runs.get("synchronization", {}).get("passed"):
            state = PassportState.SYNC_PASSED
            history.append({"state": PassportState.SYNC_PASSED, "status": "passed", "message": "Native synchronization verified"})

        if state == PassportState.SYNC_PASSED and runs.get("triangulation", {}).get("passed") and runs.get("filtering", {}).get("passed"):
            state = PassportState.TRIPOD_3D_PASSED
            history.append({"state": PassportState.TRIPOD_3D_PASSED, "status": "passed", "message": "3D marker triangulation passed"})

        if state == PassportState.TRIPOD_3D_PASSED and runs.get("kinematics", {}).get("passed"):
            state = PassportState.KINEMATICS_PASSED
            history.append({"state": PassportState.KINEMATICS_PASSED, "status": "passed", "message": "OpenSim IK joint angles produced"})

        return {
            "session_id": session_id,
            "kind": desc["kind"],
            "badge": "TEST ONLY" if is_test_only else ("REGISTERED" if desc["status"] == "registered" else "DRAFT"),
            "state": state,
            "history": history,
            "is_test_only": is_test_only,
            "can_register_real": (not is_test_only and desc["status"] == "draft" and desc["can_register"]),
            "ready_to_register": desc.get("ready_to_register", False),
            "captured_count": len(sources),
            "missing_roles": missing_roles,
            "board_measurement": board_dict,
            "sources": sources_by_role,
            "runs": runs,
            "clinically_validated": False,
            "physical_accuracy_verified": False,
            "watermark": "TEST ONLY - NOT PHYSICAL VALIDATION" if is_test_only else None
        }

    def _research_timing(self, root, session_id, run, run_digest, metadata_context, session_digest, native_calibration):
        """Read-only bounded reconstruction diagnostics; never continuous physical valid time."""
        from comparison_revision import _read_source, observe_comparison_source
        from pipeline_quality import (
            FRAME_DIAGNOSTICS_SCHEMA,
            _timing_trc_times,
            _validate_frame_document,
            project_reconstruction_timing,
        )
        from session_metadata_revision import read_metadata_state

        def unavailable(code):
            return {"schema": "kinelab.reconstruction-timing.v1", "status": "UNAVAILABLE", "code": code,
                    "reason": code, "duration_s": None, "segments": [], "gaps": [], "intervals": [],
                    "physical_accuracy_verified": False, "clinical_accuracy_verified": False,
                    "clinical_validation": "UNVERIFIED"}

        triangulations = [stage for stage in run["stages"]
                          if stage["name"] == "triangulation" and stage["status"] == "passed"]
        if len(triangulations) != 1:
            return unavailable("TIMING_DIAGNOSTICS_UNAVAILABLE")
        binding = triangulations[0].get("quality", {}).get("frame_diagnostics")
        if binding is None:
            return unavailable("TIMING_DIAGNOSTICS_ABSENT")
        before = observe_comparison_source(root)
        if before["status"] != "AVAILABLE":
            return unavailable("TIMING_SOURCE_OBSERVATION_UNAVAILABLE")
        try:
            if (not isinstance(binding, dict)
                    or set(binding) != {"path", "sha256", "schema", "source_trc", "calibration", "frames"}):
                raise ValueError("TIMING_SOURCE_MISMATCH")
            sources = [item for item in triangulations[0]["artifacts"]
                       if item == binding["source_trc"] and str(item["path"]).endswith(".trc")]
            calibrations = [item for stage in run["stages"] if stage["name"] == "calibration"
                            for item in stage["artifacts"] if item == binding["calibration"]
                            and str(item["path"]).endswith(".toml")]
            if len(sources) != 1 or len(calibrations) != 1 or calibrations[0] != native_calibration:
                raise ValueError("TIMING_SOURCE_MISMATCH")
            budget = [0]
            raw, _ = _read_source(root, binding["path"], budget)
            if hashlib.sha256(raw).hexdigest() != binding["sha256"]:
                raise ValueError("TIMING_SOURCE_MISMATCH")
            document = _validate_frame_document(strict_json_loads(raw.decode("utf-8")))
            if (binding["schema"] != FRAME_DIAGNOSTICS_SCHEMA or document["session_id"] != session_id
                    or document["source_trc"] != sources[0] or document["calibration"] != calibrations[0]
                    or type(binding["frames"]) is not int or len(document["frames"]) != binding["frames"]):
                raise ValueError("TIMING_SOURCE_MISMATCH")
            trc_raw, _ = _read_source(root, sources[0]["path"], budget)
            calibration_raw, _ = _read_source(root, calibrations[0]["path"], budget)
            if (hashlib.sha256(trc_raw).hexdigest() != sources[0]["sha256"]
                    or hashlib.sha256(calibration_raw).hexdigest() != calibrations[0]["sha256"]):
                raise ValueError("TIMING_SOURCE_MISMATCH")
            result = project_reconstruction_timing(document, _timing_trc_times(trc_raw),
                                                  session_id=session_id, source_trc=sources[0],
                                                  calibration=calibrations[0])
            after = observe_comparison_source(root)
            if after["status"] != "AVAILABLE" or after["token"] != before["token"]:
                raise ValueError("TIMING_SOURCE_CHANGED")
            current = read_metadata_state(self, session_id)
            if current["status"] != "AVAILABLE" or current["context_sha256"] != metadata_context:
                raise ValueError("TIMING_METADATA_CHANGED")
            result["bindings"] = {"session_id": session_id, "session_sha256": session_digest, "run_sha256": run_digest,
                                  "source_trc": sources[0], "calibration": calibrations[0],
                                  "frame_diagnostics": {"path": binding["path"], "sha256": binding["sha256"]},
                                  "metadata_context_sha256": metadata_context,
                                  "comparison_source_observation": {"token": after["token"], "evidence_verified": False}}
            return result
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
            code = str(error).split(":", 1)[0]
            if code in {"TIMING_SOURCE_CHANGED", "TIMING_METADATA_CHANGED"}:
                raise ValueError(code) from error
            if code not in {"TIMING_SOURCE_MISMATCH", "TIMING_GRID_MISMATCH", "TIMING_LIMIT_EXCEEDED"}:
                code = "TIMING_LIMIT_EXCEEDED" if code == "LIMIT" else "TIMING_SOURCE_INVALID"
            return unavailable(code)

    def _research_source(self, session_id: str) -> dict:
        """Read descriptive angular values only through the verified native loader."""
        from export_motion import bound_path, load_verified_motion
        from session_metadata_revision import read_metadata_state

        root = self.library.open_session(session_id)
        session_digest = self._contained_digest(root, root / "session.json")
        session = load_session(root)
        if session["session_id"] != session_id:
            raise ValueError("Session identity differs from requested session")
        validate_session_metadata(session.get("metadata"))
        metadata_state = read_metadata_state(self, session_id)
        if metadata_state["status"] != "AVAILABLE":
            raise ValueError("METADATA_UNAVAILABLE: verified metadata context required")
        metadata = metadata_state["metadata"]
        candidates = sorted((root / "exports").glob("*.motion.json"))
        if len(candidates) != 1:
            raise ValueError("Exactly one immutable native motion export is required")
        motion_path = candidates[0]
        motion_digest = self._contained_digest(root, motion_path)
        run_digest = self._contained_digest(root, root / "run.json")
        if not all((session_digest, motion_digest, run_digest)):
            raise ValueError("Session/run/motion source binding unavailable")
        native = load_verified_motion(root, motion_path)
        if native["schema"] != "kinelab.motion.v2" or native.get("sessionId") != session_id:
            raise ValueError("Native motion session/revision binding unavailable")
        kin = native.get("kinematics")
        if kin is None:
            raise ValueError("Native angular kinematics unavailable; marker-only source")
        provenance = native["provenance"]
        if provenance["runManifestSha256"] != run_digest:
            raise ValueError("Run revision changed during comparison")
        run = strict_json_loads((root / "run.json").read_text(encoding="utf-8-sig"))
        artifacts = [(stage["name"], item) for stage in run["stages"]
                     if stage["status"] == "passed" for item in stage["artifacts"]]
        models = [item for stage, item in artifacts
                  if stage == "kinematics" and Path(item["path"]).suffix.lower() == ".osim"]
        mots = [item for stage, item in artifacts
                if stage == "kinematics" and item["sha256"] == provenance["motSha256"]]
        calibrations = [item for stage, item in artifacts if stage == "calibration"
                        and item["sha256"] == provenance["calibrationSha256"]
                        and Path(item["path"]).suffix.lower() == ".toml"]
        if len(models) != 1 or len(mots) != 1 or len(calibrations) != 1:
            raise ValueError("Unique model/MOT/calibration artifact binding unavailable")
        if Path(models[0]["path"]).with_suffix(".mot") != Path(mots[0]["path"]):
            raise ValueError("Fitted model is not bound to the native MOT")
        angular = {}
        for column, name in enumerate(kin["columns"]):
            if kin["columnTypes"].get(name) == "angular":
                values = [row[column] for row in kin["rows"]]
                minimum, maximum = min(values), max(values)
                excursion = maximum - minimum
                if not math.isfinite(excursion):
                    raise ValueError("Native angular excursion is nonfinite")
                angular[name] = {"min": minimum, "max": maximum, "excursion": excursion}
        if not angular:
            raise ValueError("Native angular coordinates unavailable")
        timing = self._research_timing(root, session_id, run, run_digest, metadata_state["context_sha256"],
                                       session_digest, calibrations[0])
        # Check the actual files, not equality of user-supplied hash strings.
        bindings = [(root / "session.json", session_digest), (root / "run.json", run_digest),
                    (motion_path, motion_digest), (root / "Config.toml", run["config_sha256"])]
        bindings += [(bound_path(root, entry["path"]), entry["sha256"])
                     for entry in session["captures"].values()]
        bindings += [(bound_path(root, item["path"]), item["sha256"])
                     for _, item in artifacts]
        if any(self._contained_digest(root, path) != digest for path, digest in bindings):
            raise ValueError("Immutable source revision changed during comparison")
        contract = {key: metadata[key] for key in
                    ("subject_id", "task_id", "protocol_id", "protocol_version", "laterality")}
        contract.update(model_sha256=models[0]["sha256"], calibration_sha256=calibrations[0]["sha256"],
                        units={name: kin["columnUnits"][name] for name in sorted(angular)},
                        coordinate_system=native["coordinateSystem"])
        return {"session_id": session_id, "metadata": metadata, "contract": contract, "angular": angular, "timing": timing,
                "metadata_context_sha256": metadata_state["context_sha256"],
                "source_revision": {"session_sha256": session_digest, "run_sha256": run_digest,
                    "motion_sha256": motion_digest, "model_sha256": models[0]["sha256"],
                    "calibration_sha256": calibrations[0]["sha256"],
                    "trc_sha256": provenance["trcSha256"], "mot_sha256": provenance["motSha256"],
                    "capture_sha256": {key: item["sha256"] for key, item in session["captures"].items()}}}

    def compare_sessions(self, id1: str, id2: str, *, expected_metadata_context_s1: str | None = None,
                         expected_metadata_context_s2: str | None = None) -> dict:
        from session_metadata_revision import read_metadata_state

        expected = (expected_metadata_context_s1, expected_metadata_context_s2)
        if any(value is not None for value in expected) and any(
                not isinstance(value, str) or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in expected):
            raise ValueError("METADATA_CONTEXT_INVALID: paired SHA256 contexts required")
        p1 = self.get_passport(id1)
        p2 = self.get_passport(id2)

        # Check compatibility: same kind, both at least calibrated
        reasons = []
        if p1["kind"] != p2["kind"]:
            reasons.append(f"Incompatible: kind mismatch ({p1['kind']} vs {p2['kind']})")
        if p1["is_test_only"] or p2["is_test_only"]:
            reasons.append("Incompatible: test-only sessions cannot be compared against real recordings")
        if p1.get("state") == "EVIDENCE_UNVERIFIED" or p2.get("state") == "EVIDENCE_UNVERIFIED":
            reasons.append("EVIDENCE_UNVERIFIED: comparison not supported for unverified live evidence")
        if p1.get("state") == "EVIDENCE_INVALID" or p2.get("state") == "EVIDENCE_INVALID":
            reasons.append("EVIDENCE_INVALID: changed or missing source evidence")
        comparable_states = {PassportState.TRIPOD_3D_PASSED, PassportState.KINEMATICS_PASSED, PassportState.RESEARCH_REPORTABLE}
        if any(p["state"] not in comparable_states for p in (p1, p2)):
            reasons.append("Insufficient verified reconstruction evidence for comparison")
        sources = []
        if not reasons:
            for sid in (id1, id2):
                try:
                    sources.append(self._research_source(sid))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    reasons.append("Comparison unavailable for " + sid + ": " + str(error))
            if len(sources) == 2:
                fields = ("subject_id", "task_id", "protocol_id", "protocol_version", "laterality",
                          "model_sha256", "calibration_sha256", "units", "coordinate_system")
                reasons.extend("Comparison mismatch: " + key for key in fields
                               if sources[0]["contract"][key] != sources[1]["contract"][key])

        for source in sources:
            current = read_metadata_state(self, source["session_id"])
            if (current["status"] != "AVAILABLE"
                    or current["context_sha256"] != source["metadata_context_sha256"]):
                reasons.append("METADATA_CONTEXT_CHANGED: metadata changed during comparison")
        if (all(value is not None for value in expected) and len(sources) == 2
                and any(source["metadata_context_sha256"] != value
                        for source, value in zip(sources, expected, strict=True))):
            reasons.append("METADATA_CONTEXT_CHANGED: expected metadata context is stale")

        compatible = (len(reasons) == 0)
        reason = "; ".join(reasons) if reasons else "Matching confirmed metadata and verified native source bindings"
        research = {
            "schema": "kinelab.research-comparison.v1", "status": "AVAILABLE" if compatible else "UNAVAILABLE",
            "reason": reason, "scope": "descriptive_angular_only",
            "sessions": [{key: source[key] for key in
                          ("session_id", "metadata", "contract", "source_revision", "metadata_context_sha256", "timing")}
                         for source in sources],
            "coordinates": [{"name": name, "unit": sources[0]["contract"]["units"][name],
                             "session_1": sources[0]["angular"][name], "session_2": sources[1]["angular"][name]}
                            for name in sorted(sources[0]["angular"])] if compatible else [],
            "uncertainty": {"status": "UNAVAILABLE", "reason": "No approved uncertainty model bound to these sources"},
            "meaningful_change": {"status": "UNAVAILABLE", "reason": "No approved repeatability threshold"},
        }
        return {
            "session_1": id1,
            "session_2": id2,
            "compatible": compatible,
            "clinical_accuracy_verified": False,
            "comparison_scope": "research_only",
            "reason": reason,
            "research_measurements": research,
            "passport_1": p1,
            "passport_2": p2,
            "metrics": {
                "captured_1": p1["captured_count"],
                "captured_2": p2["captured_count"],
                "state_1": p1["state"],
                "state_2": p2["state"]
            }
        }

    def backup_database(self, dest_path: Path | str):
        dest = Path(dest_path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with dest.open("xb"):
                pass
            # A distinct reader can snapshot while this writer holds BEGIN IMMEDIATE.
            source = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
            backup_conn = sqlite3.connect(str(dest))
            try:
                source.backup(backup_conn, pages=100)
            finally:
                backup_conn.close()
                source.close()


# Captured once at import: only this original module-load profile is treated as pure.
_AUDIT_HASH_PROFILE = _supported_audit_hash_profile()
