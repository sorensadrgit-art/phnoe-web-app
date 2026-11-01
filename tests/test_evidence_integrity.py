"""Generated evidence only: changed bytes must never become a new baseline."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_contract import ROLES
from session_index import SessionIndex


class EvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.session = self.projects / "fixture"
        (self.session / "raw").mkdir(parents=True)
        (self.session / "Config.toml").write_text("# synthetic test fixture\n")
        (self.session / "session-template.json").write_text('{"kind":"real"}')
        captures = {}
        for role in ROLES:
            data = ("generated fixture " + role).encode()
            (self.session / "raw" / (role + ".mp4")).write_bytes(data)
            captures[role] = {"path": "raw/" + role + ".mp4", "sha256": hashlib.sha256(data).hexdigest()}
        self.manifest = {"schema": "kinelab.session.v1", "session_id": "fixture", "kind": "real",
                         "subject_count": 1, "camera_ids": ["cam01", "cam02"],
                         "created_at": "2026-10-28T12:00:00+00:00", "captures": captures}
        self.write("session.json", self.manifest)
        self.db = self.root / "index.db"
        self.index = SessionIndex(self.db, self.projects)
        self.addCleanup(self.index.close)
        probe = patch("session_index.probe_clip", return_value={"width": 640, "height": 480, "fps": 30, "duration": 1})
        probe.start()
        self.addCleanup(probe.stop)

    def write(self, name, data):
        (self.session / name).write_text(json.dumps(data), encoding="utf-8")

    def test_reindex_preserves_expected_digest_after_changed_or_missing_source(self):
        self.index.reindex()
        expected = self.manifest["captures"][ROLES[0]]["sha256"]
        source = self.session / "raw" / (ROLES[0] + ".mp4")
        source.write_bytes(b"changed fixture")
        self.index.reindex()
        row = self.index.conn.execute("SELECT * FROM sources WHERE role=?", (ROLES[0],)).fetchone()
        self.assertEqual(row["sha256"], expected)
        self.assertEqual(self.index.get_passport("fixture")["state"], "EVIDENCE_INVALID")
        source.unlink()
        self.index.reindex()
        self.assertEqual(self.index.get_passport("fixture")["state"], "EVIDENCE_INVALID")
        self.assertTrue(self.index.conn.execute("SELECT 1 FROM audit_events WHERE event_type='EVIDENCE_INVALIDATED'").fetchone())

    def test_changed_manifest_cannot_rebaseline_changed_capture(self):
        self.index.reindex()
        data = b"replacement fixture"
        (self.session / "raw" / (ROLES[0] + ".mp4")).write_bytes(data)
        self.manifest["captures"][ROLES[0]]["sha256"] = hashlib.sha256(data).hexdigest()
        self.write("session.json", self.manifest)
        self.index.reindex()
        self.assertEqual(self.index.get_passport("fixture")["state"], "EVIDENCE_INVALID")

    def test_reconciliation_removes_stale_valid_board_and_run_rows(self):
        self.write("board-measurement.json", {"expected_square_mm": 20, "measured_square_mm": 20,
            "measured_by": "fixture-operator", "recorded_at_utc": "2026-10-28T12:00:00Z", "source": "operator"})
        self.write("run.json", {"stages": {"calibration": {"status": "passed"}}})
        self.index.reindex()
        (self.session / "board-measurement.json").unlink()
        (self.session / "run.json").unlink()
        self.index.reindex()
        self.assertEqual(self.index.conn.execute("SELECT COUNT(*) FROM board_measurements").fetchone()[0], 0)
        self.assertEqual(self.index.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_native_stage_list_indexes_but_unbound_pass_claim_is_not_verified(self):
        self.write("run.json", {"stages": [{"name": "calibration", "status": "passed", "artifacts": []}]})
        self.index.reindex()
        row = self.index.conn.execute("SELECT * FROM runs WHERE stage='calibration'").fetchone()
        self.assertIsNotNone(row)
        self.assertFalse(row["passed"])

    def test_arbitrary_motion_file_cannot_promote_passport(self):
        (self.session / "exports").mkdir()
        (self.session / "exports" / "invented.motion.json").write_text("{}")
        (self.session / "kinematics").mkdir()
        (self.session / "kinematics" / "invented.mot").write_text("unvalidated")
        self.index.reindex()
        self.assertEqual(self.index.get_passport("fixture")["state"], "REGISTERED_ORIGINALS")

    def test_future_schema_is_refused_without_writing(self):
        self.index.conn.execute("INSERT INTO schema_migrations VALUES (999, 'future')")
        self.index.conn.commit()
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, "SCHEMA_UNSUPPORTED"):
            SessionIndex(self.db, self.projects)
        self.assertEqual(self.db.read_bytes(), before)

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.index.conn.execute("INSERT INTO sources (session_id, role, filename, sha256, bytes) VALUES ('missing','x','x','x',1)")

    def test_audit_event_cannot_be_updated_or_deleted(self):
        self.index.record_audit_event("fixture", "CHECK", {"synthetic": True})
        for statement in ("UPDATE audit_events SET event_type='FORGED'", "DELETE FROM audit_events"):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                self.index.conn.execute(statement)


if __name__ == "__main__":
    unittest.main()
