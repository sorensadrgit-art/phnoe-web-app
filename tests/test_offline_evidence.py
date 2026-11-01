"""Regressions for tools/verify_evidence.py (N05 portable offline evidence verifier).

All fixtures are generated synthetic data in temporary directories. No existing
projects, session folders, databases, credentials or network are touched.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from backup_manager import BackupManager
from recording_contract import SYNTHETIC_MODEL_SHA256, canonical_json
from recording_contract import digest as recording_digest
from recording_store import RecordingStore
from session_index import SessionIndex
from session_library import SessionLibrary
from tools import verify_evidence

HEADER = {
    "schema": "kinelab.recording.v1",
    "session_id": "synthetic-verifier-rec",
    "operation_id": "a" * 32,
    "subject_id": "synthetic-subject-01",
    "operator_id": "synthetic-operator-01",
    "source": {"kind": "synthetic", "capture_id": "b" * 32, "model_id": "kinelab-synthetic-33",
               "model_version": "1", "model_sha256": SYNTHETIC_MODEL_SHA256},
    "protocol": {"id": "squat-research-v1", "version": 1, "exercise": "squat", "side": "left",
                 "target_angle_degrees": 90, "target_hold_ms": None},
    "coordinates": {"space": "image-normalized", "units": "normalized", "z_units": "relative",
                    "width": 640, "height": 480, "mirrored": False},
}
SESSION = "verifier-demo-1"


def _landmarks():
    return [[round(0.05 + (j % 8) * 0.1, 6), round(0.05 + (j // 8) * 0.2, 6), 0.0, 0.9]
            for j in range(33)]


def _frames(first, count, valid):
    frames = []
    for i in range(count):
        sequence = first + i
        frames.append({"sequence": sequence, "time_ms": sequence * 50, "valid": valid,
                       "reasons": [] if valid else ["NO_POSE"],
                       "landmarks": _landmarks() if valid else None})
    return frames


def _append(store, session_id, chunk_id, frames):
    raw = canonical_json(frames)
    store.append(session_id, {"operation_id": HEADER["operation_id"],
                              "header_sha256": recording_digest(HEADER),
                              "chunk_id": chunk_id, "frames_json": raw,
                              "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()})


def _event_hash(event):
    fields = ("event_id", "session_id", "event_type", "details_json", "timestamp_utc",
              "actor", "revision", "outcome", "previous_hash")
    data = json.dumps({key: event[key] for key in fields}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _rechain(conn):
    """Recompute a self-consistent audit chain after a fixture mutation."""
    previous = "0" * 64
    for row in conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall():
        event = dict(row)
        event["previous_hash"] = previous
        previous = _event_hash(event)
        conn.execute("UPDATE audit_events SET previous_hash=?, event_hash=? WHERE id=?",
                     (event["previous_hash"], previous, event["id"]))
    return previous


class VerifyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        projects = root / "projects"
        projects.mkdir()
        index = SessionIndex(root / "index.db", projects)
        library = SessionLibrary(projects)
        folder = library.create_session(SESSION, kind="demo")
        (folder / "notes.txt").write_text("synthetic evidence note", encoding="utf-8")
        store = RecordingStore(index)
        store.create(dict(HEADER))
        _append(store, HEADER["session_id"], "c" * 32, _frames(1, 2, valid=True))
        _append(store, HEADER["session_id"], "d" * 32, _frames(3, 2, valid=False))
        store.finalize(HEADER["session_id"], HEADER["operation_id"], 4)
        index.reindex()
        cls.zip_path = root / "backups" / "valid.kinelab.zip"
        BackupManager(projects, index).create_backup(cls.zip_path)
        cls.archive_bytes = cls.zip_path.read_bytes()
        index.close()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.case = Path(self.tmp.name) / "case.kinelab.zip"

    def _repack(self, transform=None, extra=None, manifest_edit=None):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.archive_bytes)) as src, \
                zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as dst:
            for info in src.infolist():
                name, data = info.filename, src.read(info.filename)
                if name == "backup_manifest.json" and manifest_edit is not None:
                    data = manifest_edit(data)
                if transform is not None:
                    result = transform(name, data)
                    if result is None:
                        continue
                    name, data = result
                dst.writestr(name, data)
            for name, data in (extra or {}).items():
                dst.writestr(name, data)
        return out.getvalue()

    def _manifest_edit(self, mutate):
        def edit(data):
            document = json.loads(data.decode("utf-8"))
            mutate(document)
            return json.dumps(document).encode("utf-8")
        return edit

    def _db_tampered_archive(self, mutate):
        """Rebuild the archive with a mutated index.db; the fixture attacker then
        updates the manifest listing/generation so only deep checks can catch it."""
        members = {}
        with zipfile.ZipFile(io.BytesIO(self.archive_bytes)) as src:
            for info in src.infolist():
                members[info.filename] = src.read(info.filename)
        db_path = Path(self.tmp.name) / "tamper-index.db"
        db_path.write_bytes(members["index.db"])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
                conn.execute(f"DROP TRIGGER {trigger}")
            new_tip = mutate(conn)
            conn.commit()
        finally:
            conn.close()
        members["index.db"] = db_path.read_bytes()

        def edit(data):
            document = json.loads(data.decode("utf-8"))
            for item in document["files"]:
                if item["path"] == "index.db":
                    item["sha256"] = hashlib.sha256(members["index.db"]).hexdigest()
                    item["bytes"] = len(members["index.db"])
            if new_tip is not None:
                document["generation"]["audit_tip"] = new_tip
            return json.dumps(document).encode("utf-8")
        return self._repack(manifest_edit=edit, extra=None,
                            transform=lambda n, d: (n, d if n == "backup_manifest.json" else members[n]))

    def _run(self, data):
        self.case.write_bytes(data)
        return verify_evidence.verify_archive(self.case)

    def _assert_fails(self, result, code):
        self.assertFalse(result["ok"], json.dumps(result, indent=2))
        codes = [failure["code"] for failure in result["failures"]]
        self.assertIn(code, codes, json.dumps(result["failures"], indent=2))

    def test_valid_archive_passes_and_input_untouched(self):
        before = hashlib.sha256(self.archive_bytes).hexdigest()
        result = self._run(self.archive_bytes)
        self.assertTrue(result["ok"], json.dumps(result, indent=2))
        self.assertEqual(result["archive_sha256"], before)
        self.assertEqual(hashlib.sha256(self.case.read_bytes()).hexdigest(), before)
        statuses = {check["id"]: check["status"] for check in result["checks"]}
        for check_id in ("zip.structure", "manifest.schema", "manifest.inventory", "member.digests",
                         "database.integrity", "audit.lineage", "evidence.crosscheck",
                         "recording.sequence", "report.lineage"):
            self.assertEqual(statuses.get(check_id), "pass", statuses)
        self.assertEqual(result["scope"]["authenticity"].split(":")[0], "UNESTABLISHED")
        self.assertFalse(result["scope"]["physical_accuracy_verified"])
        self.assertEqual(result["scope"]["clinical_validation"], "UNVERIFIED")

    def test_tampered_member_bytes_fail(self):
        def transform(name, data):
            if name == f"sessions/{SESSION}/notes.txt":
                return name, bytes(byte ^ 0xFF for byte in data)
            return name, data
        self._assert_fails(self._run(self._repack(transform=transform)), "EVIDENCE_DIGEST_MISMATCH")

    def test_omitted_listed_member_fails(self):
        def transform(name, data):
            if name == f"sessions/{SESSION}/notes.txt":
                return None
            return name, data
        self._assert_fails(self._run(self._repack(transform=transform)), "EVIDENCE_INVENTORY_INCOMPLETE")

    def test_unlisted_extra_member_fails(self):
        data = self._repack(extra={f"sessions/{SESSION}/unexpected.txt": b"unlisted"})
        self._assert_fails(self._run(data), "EVIDENCE_INVENTORY_UNEXPECTED_MEMBER")

    def test_unsupported_schema_fails(self):
        data = self._repack(manifest_edit=self._manifest_edit(
            lambda doc: doc.update(schema="kinelab.backup.v9")))
        result = self._run(data)
        self._assert_fails(result, "EVIDENCE_UNSUPPORTED_SCHEMA")

    def test_legacy_v1_schema_reported_unsupported(self):
        def mutate(doc):
            doc["schema"] = "kinelab.backup.v1"
        data = self._repack(manifest_edit=self._manifest_edit(mutate))
        self._assert_fails(self._run(data), "EVIDENCE_UNSUPPORTED_SCHEMA")

    def test_path_traversal_member_fails(self):
        data = self._repack(extra={"sessions/../../escape.txt": b"traversal"})
        self._assert_fails(self._run(data), "EVIDENCE_PATH_INVALID")

    def test_manifest_listed_traversal_fails(self):
        payload = b"listed traversal"
        digest = hashlib.sha256(payload).hexdigest()
        def mutate(doc):
            doc["files"].append({"path": f"sessions/{SESSION}/../escape.txt",
                                 "sha256": digest, "bytes": len(payload)})
            doc["file_count"] = len(doc["files"])
        data = self._repack(extra={f"sessions/{SESSION}/escape.txt": payload},
                            manifest_edit=self._manifest_edit(mutate))
        self._assert_fails(self._run(data), "EVIDENCE_PATH_INVALID")

    def test_duplicate_json_key_fails(self):
        def edit(data):
            text = data.decode("utf-8")
            return text.replace('"schema":', '"schema": "kinelab.backup.v2", "schema":', 1).encode("utf-8")
        self._assert_fails(self._run(self._repack(manifest_edit=edit)), "EVIDENCE_MANIFEST_INVALID")

    def test_gapped_recording_fails(self):
        def mutate(conn):
            conn.execute("DELETE FROM recording_chunks WHERE first_sequence=3")
            return _rechain(conn)
        self._assert_fails(self._run(self._db_tampered_archive(mutate)), "RECORDING_CORRUPT")

    def test_reordered_audit_events_fail(self):
        def mutate(conn):
            ids = [row[0] for row in conn.execute("SELECT id FROM audit_events ORDER BY id").fetchall()]
            self.assertGreaterEqual(len(ids), 2)
            first, second = ids[0], ids[1]
            conn.execute("UPDATE audit_events SET id=-1 WHERE id=?", (first,))
            conn.execute("UPDATE audit_events SET id=? WHERE id=?", (first, second))
            conn.execute("UPDATE audit_events SET id=? WHERE id=-1", (second,))
            # chain left broken on purpose
        self._assert_fails(self._run(self._db_tampered_archive(mutate)), "AUDIT_CHAIN_INVALID")

    def test_recomputed_recording_manifest_mismatch_fails(self):
        def mutate(conn):
            conn.execute("UPDATE recording_chunks SET last_sequence=99 WHERE first_sequence=3")
            return _rechain(conn)
        self._assert_fails(self._run(self._db_tampered_archive(mutate)), "RECORDING_CORRUPT")

    def test_forged_report_receipt_fails(self):
        generation = "report-" + "e" * 32
        def mutate(conn):
            tip = _rechain(conn)
            document = {"generation": generation, "manifest_sha256": "0" * 64}
            event = {"event_id": "f" * 32, "session_id": SESSION, "event_type": "REPORT_PUBLISHED",
                     "details_json": json.dumps(document, sort_keys=True),
                     "timestamp_utc": "2026-10-29T00:00:00+00:00", "actor": "system",
                     "revision": 0, "outcome": "recorded", "previous_hash": tip}
            event["event_hash"] = _event_hash(event)
            keys = ",".join(event)
            conn.execute(f"INSERT INTO audit_events (id,{keys}) VALUES (NULL,{','.join('?' for _ in event)})",
                         list(event.values()))
            return _rechain(conn)
        self._assert_fails(self._run(self._db_tampered_archive(mutate)), "REPORT_INVALID")

    def test_cli_subprocess_valid_and_altered(self):
        valid = Path(self.tmp.name) / "valid.zip"
        valid.write_bytes(self.archive_bytes)
        tool = ROOT / "tools" / "verify_evidence.py"
        good = subprocess.run([sys.executable, "-I", "-X", "utf8", str(tool), str(valid)],
                              capture_output=True, text=True, cwd=self.tmp.name, timeout=120, check=False)
        self.assertEqual(good.returncode, 0, good.stderr + good.stdout)
        payload = json.loads(good.stdout)
        self.assertTrue(payload["ok"])
        self.assertNotIn(str(ROOT), good.stderr)

        def transform(name, data):
            if name == f"sessions/{SESSION}/notes.txt":
                return name, bytes(byte ^ 0xFF for byte in data)
            return name, data
        altered = Path(self.tmp.name) / "altered.zip"
        altered.write_bytes(self._repack(transform=transform))
        bad = subprocess.run([sys.executable, "-I", "-X", "utf8", str(tool), str(altered)],
                             capture_output=True, text=True, cwd=self.tmp.name, timeout=120, check=False)
        self.assertEqual(bad.returncode, 1, bad.stderr + bad.stdout)
        failure = json.loads(bad.stdout)
        self.assertFalse(failure["ok"])
        self.assertIn("EVIDENCE_DIGEST_MISMATCH", [f["code"] for f in failure["failures"]])

        missing = subprocess.run([sys.executable, "-I", "-X", "utf8", str(tool),
                                  str(Path(self.tmp.name) / "absent.zip")],
                                 capture_output=True, text=True, cwd=self.tmp.name, timeout=120, check=False)
        self.assertEqual(missing.returncode, 2)


if __name__ == "__main__":
    unittest.main()
