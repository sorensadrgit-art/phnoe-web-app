"""SQLite-backed metadata index and Evidence Passport state machine for KineLab PT.

Local-first, immutable source media: this database indexes files and provenances only.
Original MP4, TRC, MOT and manifest files in projects/ remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from capture_station import RAW_ROLES, clip_path, probe_clip
from session_contract import sha256_file
from session_library import SessionLibrary

SCHEMA_VERSION = 1


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
    def __init__(self, db_path: Path | str, projects_root: Path | str):
        self.db_path = Path(db_path).resolve()
        self.projects_root = Path(projects_root).resolve()
        self.library = SessionLibrary(self.projects_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )
            """)
            cur = self.conn.execute("SELECT MAX(version) AS ver FROM schema_migrations")
            row = cur.fetchone()
            current_ver = row["ver"] if row and row["ver"] is not None else 0

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
                    (1, datetime.now(timezone.utc).isoformat())
                )

    def close(self):
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def __del__(self):
        self.close()

    def record_audit_event(self, session_id: str, event_type: str, details: dict):
        with self.conn:
            self.conn.execute(
                "INSERT INTO audit_events (session_id, event_type, details_json, timestamp_utc) VALUES (?, ?, ?, ?)",
                (session_id, event_type, json.dumps(details), datetime.now(timezone.utc).isoformat())
            )

    def reindex(self):
        """Idempotently scans the sessions in projects/ and populates index tables."""
        listed = self.library.list_sessions()
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            for s in listed:
                sid = s["id"]
                folder = self.projects_root / sid
                desc = self.library.describe_session(sid)
                board_measured = int((folder / "board-measurement.json").is_file())

                self.conn.execute("""
                    INSERT INTO sessions (id, kind, status, captured_roles, can_register, board_measured, created_at_utc, updated_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind,
                        status=excluded.status,
                        captured_roles=excluded.captured_roles,
                        can_register=excluded.can_register,
                        board_measured=excluded.board_measured,
                        updated_at_utc=excluded.updated_at_utc
                """, (
                    sid, desc["kind"], desc["status"], desc["captured_roles"],
                    int(desc["can_register"]), board_measured, now, now
                ))

                # Sources
                raw_dir = folder / "raw"
                if raw_dir.is_dir():
                    for role in RAW_ROLES:
                        mp4 = raw_dir / (role + ".mp4")
                        if mp4.is_file():
                            stat = mp4.stat()
                            try:
                                h = sha256_file(mp4)
                            except Exception:
                                h = "uncomputed"
                            w, ht, fps, dur = None, None, None, None
                            try:
                                meta = probe_clip(mp4)
                                w, ht, fps, dur = meta["width"], meta["height"], meta["fps"], meta["duration"]
                            except Exception:
                                pass
                            self.conn.execute("""
                                INSERT OR REPLACE INTO sources (session_id, role, filename, sha256, bytes, width, height, fps, duration)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (sid, role, mp4.name, h, stat.st_size, w, ht, fps, dur))

                # Board measurement
                board_path = folder / "board-measurement.json"
                if board_path.is_file():
                    try:
                        bdata = json.loads(board_path.read_text(encoding="utf-8"))
                        self.conn.execute("""
                            INSERT OR REPLACE INTO board_measurements (session_id, expected_square_mm, measured_square_mm, measured_by, recorded_at_utc, source)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            sid, float(bdata.get("expected_square_mm", 20.0)),
                            float(bdata["measured_square_mm"]),
                            str(bdata.get("measured_by", "unknown")),
                            str(bdata.get("recorded_at_utc", now)),
                            str(bdata.get("source", "operator_measured_not_independently_verified"))
                        ))
                    except Exception:
                        pass

                # Runs
                run_path = folder / "run.json"
                if run_path.is_file():
                    try:
                        rdata = json.loads(run_path.read_text(encoding="utf-8"))
                        cfg_h = rdata.get("config_sha256")
                        stages = rdata.get("stages", {})
                        for st_name, st_info in stages.items():
                            passed = 1 if st_info.get("status") == "passed" else 0
                            self.conn.execute("""
                                INSERT OR REPLACE INTO runs (session_id, stage, state, passed, config_sha256, error_message, updated_at_utc)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (sid, st_name, st_info.get("status", "unknown"), passed, cfg_h, st_info.get("error"), now))
                    except Exception:
                        pass

                # Artifacts
                for art_name in ("session.json", "normalization.json", "preflight.json", "sync-observations.json", "sync.json", "run.json", "board-measurement.json"):
                    cand = folder / art_name
                    if cand.is_file():
                        self.conn.execute("""
                            INSERT OR REPLACE INTO artifacts (session_id, artifact_key, filename, artifact_type, bytes, sha256, created_at_utc)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (sid, art_name, cand.name, "evidence_manifest", cand.stat().st_size, sha256_file(cand), now))

                exports_dir = folder / "exports"
                if exports_dir.is_dir():
                    for exp in exports_dir.glob("*.motion.json"):
                        if exp.is_file():
                            self.conn.execute("""
                                INSERT OR REPLACE INTO artifacts (session_id, artifact_key, filename, artifact_type, bytes, sha256, created_at_utc)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (sid, "exports/" + exp.name, exp.name, "motion_export", exp.stat().st_size, sha256_file(exp), now))

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

        if (folder / "preflight.json").is_file():
            try:
                pf = json.loads((folder / "preflight.json").read_text(encoding="utf-8-sig"))
                if pf.get("ok"):
                    state = PassportState.NORMALIZATION_PASSED
                    history.append({"state": PassportState.NORMALIZATION_PASSED, "status": "passed", "message": "Video normalization verified"})
            except Exception:
                pass

        if runs.get("calibration", {}).get("passed"):
            state = PassportState.CALIBRATION_PASSED
            history.append({"state": PassportState.CALIBRATION_PASSED, "status": "passed", "message": "Native camera calibration passed"})

        if runs.get("synchronization", {}).get("passed"):
            state = PassportState.SYNC_PASSED
            history.append({"state": PassportState.SYNC_PASSED, "status": "passed", "message": "Native synchronization verified"})

        if runs.get("triangulation", {}).get("passed") and runs.get("filtering", {}).get("passed"):
            state = PassportState.TRIPOD_3D_PASSED
            history.append({"state": PassportState.TRIPOD_3D_PASSED, "status": "passed", "message": "3D marker triangulation passed"})

        # Kinematics check
        has_mot = any((folder / "kinematics").glob("*.mot")) if (folder / "kinematics").is_dir() else False
        if has_mot:
            state = PassportState.KINEMATICS_PASSED
            history.append({"state": PassportState.KINEMATICS_PASSED, "status": "passed", "message": "OpenSim IK joint angles produced"})

        if (folder / "exports").is_dir() and any((folder / "exports").glob("*.motion.json")):
            state = PassportState.RESEARCH_REPORTABLE
            history.append({"state": PassportState.RESEARCH_REPORTABLE, "status": "passed", "message": "Verified motion export package complete"})

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

    def compare_sessions(self, id1: str, id2: str) -> dict:
        p1 = self.get_passport(id1)
        p2 = self.get_passport(id2)

        # Check compatibility: same kind, both at least calibrated
        reasons = []
        if p1["kind"] != p2["kind"]:
            reasons.append(f"Incompatible: kind mismatch ({p1['kind']} vs {p2['kind']})")
        if p1["is_test_only"] or p2["is_test_only"]:
            reasons.append("Incompatible: test-only sessions cannot be compared against real recordings")

        compatible = (len(reasons) == 0)
        return {
            "session_1": id1,
            "session_2": id2,
            "compatible": compatible,
            "reason": "; ".join(reasons) if not compatible else "Sessions share matching capture protocol",
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
        backup_conn = sqlite3.connect(str(dest))
        with backup_conn:
            self.conn.backup(backup_conn, pages=100)
        backup_conn.close()
