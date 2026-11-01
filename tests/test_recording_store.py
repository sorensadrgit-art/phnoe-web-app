"""Generated frames only: acknowledgment, retries and atomic durable publication."""
import hashlib
import importlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

from recording_contract import canonical_json, digest
from session_index import SessionIndex
from test_recording_contract import frame, header


def chunk(sequence, *, time_ms=None, chunk_id=None):
    frames = [frame(sequence, (sequence - 1) * 30 if time_ms is None else time_ms)]
    return {"operation_id": header()["operation_id"], "header_sha256": digest(header()),
            "chunk_id": chunk_id or f"{sequence:032x}", "frames_json": canonical_json(frames), "sha256": digest(frames)}


class RecordingStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("recording_store"), "durable recording store is required")
        self.module = importlib.import_module("recording_store")
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        self.index = SessionIndex(self.root / "index.db", self.root / "projects")
        self.addCleanup(lambda: self.index.close())
        self.store = self.module.RecordingStore(self.index)
        self.sid = header()["session_id"]

    def reopen(self):
        self.index.close()
        self.index = SessionIndex(self.root / "index.db", self.root / "projects")
        self.store = self.module.RecordingStore(self.index)

    def test_out_of_order_chunks_only_acknowledge_contiguous_saved_prefix(self):
        self.store.create(header())
        self.assertEqual(self.store.append(self.sid, chunk(1))["saved_through"], 1)
        receipt = self.store.append(self.sid, chunk(3))
        self.assertEqual(receipt["saved_through"], 1)
        self.assertEqual(receipt["missing_ranges"], [[2, 2]])
        self.assertEqual(self.store.append(self.sid, chunk(2))["saved_through"], 3)
        self.reopen()
        self.assertEqual(list(self.store.iter_frames(self.sid)), [frame(i, (i - 1) * 30) for i in range(1, 4)])
        self.assertEqual(self.store.status(self.sid)["saved_through"], 3)

    def test_lost_ack_retry_is_idempotent_and_conflicting_identity_is_rejected(self):
        initial = self.store.create(header())
        self.assertEqual(self.store.create(header()), initial)
        ack = self.store.append(self.sid, chunk(1))
        before = self.index.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.reopen()
        self.assertEqual(self.store.append(self.sid, chunk(1)), ack)
        self.assertEqual(self.index.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], before)
        altered = chunk(1, time_ms=1)
        with self.assertRaisesRegex(ValueError, "RECORDING_CONFLICT"):
            self.store.append(self.sid, altered)
        changed = header(); changed["coordinates"]["mirrored"] = True
        with self.assertRaisesRegex(ValueError, "RECORDING_CONFLICT"):
            self.store.create(changed)

    def test_cross_chunk_time_overlap_hash_and_operation_binding_rejected(self):
        self.store.create(header()); self.store.append(self.sid, chunk(1, time_ms=40))
        cases = [chunk(2, time_ms=30), chunk(1, chunk_id="f" * 32)]
        bad = chunk(2); bad["sha256"] = "0" * 64; cases.append(bad)
        bad = chunk(2); bad["operation_id"] = "e" * 32; cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad["chunk_id"]), self.assertRaises(ValueError):
                self.store.append(self.sid, bad)
        self.assertEqual(self.store.status(self.sid)["saved_through"], 1)

    def test_finalization_requires_every_frame_and_preserves_immutable_manifest(self):
        self.store.create(header()); self.store.append(self.sid, chunk(1)); self.store.append(self.sid, chunk(3))
        with self.assertRaisesRegex(ValueError, "RECORDING_INCOMPLETE"):
            self.store.finalize(self.sid, header()["operation_id"], 3)
        self.store.append(self.sid, chunk(2))
        result = self.store.finalize(self.sid, header()["operation_id"], 3)
        self.assertEqual(result["state"], "FINALIZED")
        self.assertEqual(result["manifest"]["frame_count"], 3)
        self.assertFalse(result["manifest"]["physical_accuracy_verified"])
        self.reopen()
        self.assertEqual(self.store.finalize(self.sid, header()["operation_id"], 3), result)
        with self.assertRaisesRegex(ValueError, "RECORDING_FINALIZED"):
            self.store.append(self.sid, chunk(4))
        with self.assertRaisesRegex(ValueError, "RECORDING_CONFLICT"):
            self.store.finalize(self.sid, header()["operation_id"], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.index.conn.execute("UPDATE recording_chunks SET frames_json='[]'")

    def test_audit_failure_rolls_back_chunk_and_finalize_without_ack(self):
        self.store.create(header())
        with patch.object(self.index, "_append_audit", side_effect=sqlite3.OperationalError("simulated I/O fault")), self.assertRaises(sqlite3.OperationalError):
            self.store.append(self.sid, chunk(1))
        self.reopen()
        self.assertEqual(self.store.status(self.sid)["saved_through"], 0)
        self.store.append(self.sid, chunk(1))
        with patch.object(self.index, "_append_audit", side_effect=sqlite3.OperationalError("simulated I/O fault")), self.assertRaises(sqlite3.OperationalError):
            self.store.finalize(self.sid, header()["operation_id"], 1)
        self.reopen()
        self.assertEqual(self.store.status(self.sid)["state"], "RECORDING")
        self.assertIsNone(self.store.status(self.sid)["manifest"])

    def test_disk_full_never_returns_acknowledgment(self):
        self.store.create(header())
        pages = self.index.conn.execute("PRAGMA page_count").fetchone()[0]
        self.index.conn.execute(f"PRAGMA max_page_count={pages}")
        frames = [frame(i + 1, i * 30) for i in range(16)]
        payload = chunk(1); payload.update(frames_json=canonical_json(frames), sha256=digest(frames))
        with self.assertRaisesRegex(sqlite3.OperationalError, "full"):
            self.store.append(self.sid, payload)
        self.reopen()
        self.assertEqual(self.store.status(self.sid)["saved_through"], 0)

    def test_process_death_before_commit_rolls_back_and_after_ack_survives(self):
        self.store.create(header())
        script = """
import os, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from session_index import SessionIndex
from recording_store import RecordingStore
from test_recording_store import chunk
from test_recording_contract import header
root = Path(sys.argv[1])
index = SessionIndex(root / 'index.db', root / 'projects')
if sys.argv[2] == 'before':
    index._append_audit = lambda *a, **k: os._exit(17)
receipt = RecordingStore(index).append(header()['session_id'], chunk(1))
assert receipt['saved_through'] == 1
os._exit(18)
"""
        for stage, code, expected in (("before", 17, 0), ("after", 18, 1)):
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", script, str(self.root), stage],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15, check=False)
            self.assertEqual(result.returncode, code, result.stderr.decode())
            self.reopen()
            self.assertEqual(self.store.status(self.sid)["saved_through"], expected)
        self.assertEqual(list(self.store.iter_frames(self.sid)), [frame()])

    def test_independent_duplicate_writers_store_one_chunk_and_one_audit_event(self):
        self.store.create(header())
        other = SessionIndex(self.root / "index.db", self.root / "projects")
        try:
            second = self.module.RecordingStore(other)
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(store.append, self.sid, chunk(1)) for store in (self.store, second)]
                self.assertEqual(pending[0].result(), pending[1].result())
            self.assertEqual(self.index.conn.execute("SELECT COUNT(*) FROM recording_chunks").fetchone()[0], 1)
            self.assertEqual(self.index.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 2)
            self.index.verify_audit()
        finally:
            other.close()

    def test_corruption_cannot_be_rebaselined_or_retried_as_success(self):
        self.store.create(header()); self.store.append(self.sid, chunk(1))
        self.store.finalize(self.sid, header()["operation_id"], 1)
        # Emulate storage corruption, bypassing normal SQL immutability protections.
        self.index.conn.execute("DROP TRIGGER recording_chunk_no_update")
        changed = chunk(1, time_ms=5)
        self.index.conn.execute("UPDATE recording_chunks SET frames_json=?, sha256=?, first_time_ms=5,last_time_ms=5",
                                (changed["frames_json"], changed["sha256"]))
        self.index.conn.commit()
        with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT"):
            self.store.finalize(self.sid, header()["operation_id"], 1)

    def test_failed_v2_migration_preserves_old_schema_and_audit(self):
        self.index.record_audit_event("fixture", "MIGRATION_FIXTURE", {})
        expected = self.index.verify_audit()
        self.index.conn.execute("DROP TABLE recording_chunks")
        self.index.conn.execute("DROP TABLE recordings")
        self.index.conn.execute("DELETE FROM schema_migrations WHERE version=3")
        self.index.conn.commit(); self.index.close()
        def interrupted(conn):
            conn.execute("CREATE TABLE recordings (partial TEXT)")
            raise OSError("simulated migration interruption")
        with patch.object(self.module, "create_schema", side_effect=interrupted), self.assertRaises(OSError):
            SessionIndex(self.root / "index.db", self.root / "projects")
        with sqlite3.connect(self.root / "index.db") as conn:
            self.assertEqual(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 2)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='recordings'").fetchone())
        conn.close()
        self.reopen()
        self.assertEqual(self.index.verify_audit(), expected)

    def test_exact_wire_bytes_round_trip_without_number_reserialization(self):
        self.store.create(header())
        value = frame(); value["landmarks"][0][2] = 1e-7
        # JavaScript uses e-7 where Python uses e-07; preserve the actual producer bytes.
        raw = json.dumps([value], indent=1).replace("1e-07", "1e-7")
        payload = chunk(1); payload.update(frames_json=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.store.append(self.sid, payload)
        stored = self.index.conn.execute("SELECT frames_json FROM recording_chunks").fetchone()[0]
        self.assertEqual(stored, raw)
        self.assertEqual(list(self.store.iter_frames(self.sid)), [value])

    def test_recovered_prefix_remains_marked_as_an_unknown_unacknowledged_tail(self):
        self.store.create(header()); self.store.append(self.sid, chunk(1))
        self.assertIn("end_reason", __import__('inspect').signature(self.store.finalize).parameters,
                      "recovery must preserve its incomplete-capture provenance")
        result = self.store.finalize(self.sid, header()["operation_id"], 1, end_reason="recovered_prefix")
        self.assertEqual(result["manifest"]["unacknowledged_tail"], "UNKNOWN")
        self.assertEqual(result["manifest"]["end_reason"], "recovered_prefix")
        with self.assertRaisesRegex(ValueError, "RECORDING_CONFLICT"):
            self.store.finalize(self.sid, header()["operation_id"], 1, end_reason="operator_finished")


class AuditWriterTests(unittest.TestCase):
    def test_independent_writers_cannot_fork_the_audit_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "projects").mkdir()
            first = SessionIndex(root / "index.db", root / "projects")
            second = SessionIndex(root / "index.db", root / "projects")
            paused, release = Event(), Event()
            original = first._event_hash
            def pause_hash(event):
                paused.set()
                if not release.wait(3):
                    raise TimeoutError("test writer did not release")
                return original(event)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool, patch.object(first, "_event_hash", side_effect=pause_hash):
                    a = pool.submit(first.record_audit_event, "fixture", "FIRST", {})
                    self.assertTrue(paused.wait(2))
                    b = pool.submit(second.record_audit_event, "fixture", "SECOND", {})
                    # In the old implementation, B commits while A has already read the old tip.
                    try:
                        b.result(timeout=.2)
                    except TimeoutError:
                        pass
                    release.set(); a.result(); b.result()
                self.assertEqual(first.verify_audit(), second.verify_audit())
            finally:
                release.set(); first.close(); second.close()
