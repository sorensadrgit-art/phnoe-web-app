"""Generated corruption fixtures: no ACK may promote damaged stored evidence."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from recording_contract import MAX_CHUNK_BYTES, canonical_json
from recording_store import RecordingStore
from session_index import SessionIndex
from test_recording_contract import frame, header
from test_recording_store import chunk


class RecordingAckIntegrityTests(unittest.TestCase):
    @contextmanager
    def recording(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "projects").mkdir()
            index = SessionIndex(root / "index.db", root / "projects")
            try:
                store = RecordingStore(index)
                store.create(header())
                store.append(header()["session_id"], chunk(1))
                yield root, index, store
            finally:
                index.close()

    @staticmethod
    def allow_fixture_damage(index):
        # These triggers are bypassed only in generated, disposable corruption fixtures.
        index.conn.execute("DROP TRIGGER IF EXISTS recording_chunk_no_update")
        index.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        index.conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")

    @staticmethod
    def rechain_fixture(index):
        previous = "0" * 64
        for row in index.conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall():
            event = dict(row)
            event["previous_hash"] = previous
            event["event_hash"] = index._event_hash(event)
            index.conn.execute("UPDATE audit_events SET previous_hash=?,event_hash=? WHERE id=?",
                               (previous, event["event_hash"], event["id"]))
            previous = event["event_hash"]

    def replace_chunk(self, index, payload):
        frames = json.loads(payload["frames_json"])
        index.conn.execute("""UPDATE recording_chunks SET frames_json=?,sha256=?,
            first_sequence=?,last_sequence=?,first_time_ms=?,last_time_ms=? WHERE chunk_id=?""",
            (payload["frames_json"], payload["sha256"], frames[0]["sequence"], frames[-1]["sequence"],
             frames[0]["time_ms"], frames[-1]["time_ms"], payload["chunk_id"]))
        event = index.conn.execute("SELECT * FROM audit_events WHERE event_type='RECORDING_CHUNK_SAVED' ORDER BY id DESC").fetchone()
        details = {"chunk_id": payload["chunk_id"], "sha256": payload["sha256"],
                   "first_sequence": frames[0]["sequence"], "last_sequence": frames[-1]["sequence"]}
        index.conn.execute("UPDATE audit_events SET details_json=? WHERE id=?", (canonical_json(details), event["id"]))
        self.rechain_fixture(index)

    def damage(self, index, kind):
        self.allow_fixture_damage(index)
        if kind == "malformed_bytes":
            index.conn.execute("UPDATE recording_chunks SET frames_json='['")
        elif kind == "digest":
            index.conn.execute("UPDATE recording_chunks SET sha256=?", ("0" * 64,))
        elif kind == "range":
            index.conn.execute("UPDATE recording_chunks SET first_sequence=2,last_sequence=2")
        elif kind == "time":
            index.conn.execute("UPDATE recording_chunks SET first_time_ms=15,last_time_ms=15")
        elif kind == "replaced_bytes":
            changed = chunk(1, time_ms=15)
            index.conn.execute("UPDATE recording_chunks SET frames_json=?,sha256=?,first_time_ms=15,last_time_ms=15",
                               (changed["frames_json"], changed["sha256"]))
        elif kind == "missing_receipt":
            index.conn.execute("DELETE FROM audit_events WHERE event_type='RECORDING_CHUNK_SAVED'")
        elif kind == "mismatched_receipt":
            index.conn.execute("UPDATE audit_events SET details_json='{}' WHERE event_type='RECORDING_CHUNK_SAVED'")
            self.rechain_fixture(index)
        elif kind == "wrong_receipt_revision":
            index.conn.execute("UPDATE audit_events SET revision=99 WHERE event_type='RECORDING_CHUNK_SAVED'")
            self.rechain_fixture(index)
        elif kind == "malformed_receipt":
            index.conn.execute("UPDATE audit_events SET details_json='[' WHERE event_type='RECORDING_CHUNK_SAVED'")
            self.rechain_fixture(index)
        elif kind == "scalar_receipt":
            index.conn.execute("UPDATE audit_events SET details_json='null' WHERE event_type='RECORDING_CHUNK_SAVED'")
            self.rechain_fixture(index)
        elif kind == "broken_audit_chain":
            index.conn.execute("UPDATE audit_events SET details_json='{}' WHERE event_type='RECORDING_CHUNK_SAVED'")
        elif kind == "oversized_wire":
            payload = chunk(1)
            payload["frames_json"] += " " * MAX_CHUNK_BYTES
            payload["sha256"] = hashlib.sha256(payload["frames_json"].encode("utf-8")).hexdigest()
            self.replace_chunk(index, payload)
        else:
            raise AssertionError(kind)
        index.conn.commit()

    def test_all_ack_paths_refuse_prior_damaged_bytes_metadata_or_receipts(self):
        cases = ("malformed_bytes", "digest", "range", "time", "replaced_bytes",
                 "missing_receipt", "mismatched_receipt", "wrong_receipt_revision", "oversized_wire",
                 "malformed_receipt", "scalar_receipt", "broken_audit_chain")
        for kind in cases:
            for action in ("status", "list", "create_retry", "chunk_retry", "new_chunk", "finalize", "verify"):
                with self.subTest(damage=kind, action=action), self.recording() as (_, index, store):
                    self.damage(index, kind)
                    before = self.database_state(index)
                    sid = header()["session_id"]
                    calls = {"status": lambda store=store, sid=sid: store.status(sid), "list": store.list_recordings,
                             "create_retry": lambda store=store: store.create(header()),
                             "chunk_retry": lambda store=store, sid=sid: store.append(sid, chunk(1)),
                             "new_chunk": lambda store=store, sid=sid: store.append(sid, chunk(2)),
                             "finalize": lambda store=store, sid=sid: store.finalize(sid, header()["operation_id"], 1),
                             "verify": lambda store=store, sid=sid: store.verify(sid)}
                    with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT|AUDIT_INVALID"):
                        calls[action]()
                    self.assertEqual(self.database_state(index), before,
                                     "Rejected corruption must not commit a new chunk, revision or receipt")

    @staticmethod
    def database_state(index):
        return {table: [tuple(row) for row in index.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("recordings", "recording_chunks", "audit_events")}

    def test_corrupt_out_of_order_tail_blocks_gap_filling_ack(self):
        with self.recording() as (_, index, store):
            sid = header()["session_id"]
            store.append(sid, chunk(3))
            self.allow_fixture_damage(index)
            index.conn.execute("UPDATE recording_chunks SET frames_json='[' WHERE first_sequence=3")
            index.conn.commit()
            before = self.database_state(index)
            with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT"):
                store.append(sid, chunk(2))
            self.assertEqual(self.database_state(index), before)

    def test_cross_chunk_time_corruption_is_refused_even_with_consistent_local_receipts(self):
        with self.recording() as (_, index, store):
            sid = header()["session_id"]
            store.append(sid, chunk(2))
            self.allow_fixture_damage(index)
            self.replace_chunk(index, chunk(2, time_ms=0))
            index.conn.commit()
            index.verify_audit()
            before = self.database_state(index)
            with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT"):
                store.status(sid)
            with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT"):
                store.append(sid, chunk(3))
            self.assertEqual(self.database_state(index), before)

    def test_cross_chunk_overlapping_ranges_are_not_acknowledged(self):
        with self.recording() as (_, index, store):
            sid = header()["session_id"]
            self.allow_fixture_damage(index)
            first = chunk(1)
            first["frames_json"] = canonical_json([frame(1, 0), frame(2, 30)])
            first["sha256"] = hashlib.sha256(first["frames_json"].encode("utf-8")).hexdigest()
            self.replace_chunk(index, first)
            index.conn.commit()
            store.append(sid, chunk(3))
            self.replace_chunk(index, chunk(2, time_ms=60, chunk_id=f"{3:032x}"))
            index.conn.commit()
            index.verify_audit()
            before = self.database_state(index)
            with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT"):
                store.status(sid)
            with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT"):
                store.append(sid, chunk(4))
            self.assertEqual(self.database_state(index), before)

    def test_finalize_process_exit_before_commit_and_after_commit_before_response(self):
        worker = r'''
import os, sys
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, 'tests')
from session_index import SessionIndex
from recording_store import RecordingStore
from test_recording_contract import header
root, boundary = Path(sys.argv[1]), sys.argv[2]
index = SessionIndex(root / 'index.db', root / 'projects')
if boundary == 'before-commit':
    original = index._append_audit
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        if args[1] == 'RECORDING_FINALIZED': os._exit(31)
    index._append_audit = fail
else:
    original_transaction = index.transaction
    @contextmanager
    def fail_after_commit():
        with original_transaction(): yield
        os._exit(32)
    index.transaction = fail_after_commit
RecordingStore(index).finalize(header()['session_id'], header()['operation_id'], 1)
raise AssertionError('process boundary was not reached')
'''
        for boundary, exit_code, state, revision in (("before-commit", 31, "RECORDING", 2),
                                                      ("after-commit-before-response", 32, "FINALIZED", 3)):
            with self.subTest(boundary=boundary), self.recording() as (root, _index, _):
                result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", worker, str(root), boundary],
                                        cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                        timeout=15, check=False)
                self.assertEqual(result.returncode, exit_code, result.stderr.decode("utf-8"))
                # Open a fresh connection to exercise SQLite recovery, not the old connection's view.
                reopened = SessionIndex(root / "index.db", root / "projects")
                try:
                    store = RecordingStore(reopened)
                    sid = header()["session_id"]
                    status = store.status(sid)
                    self.assertEqual((status["state"], status["revision"]), (state, revision))
                    receipt = store.finalize(sid, header()["operation_id"], 1)
                    before = self.database_state(reopened)
                    self.assertEqual(store.finalize(sid, header()["operation_id"], 1), receipt)
                    self.assertEqual(self.database_state(reopened), before)
                    self.assertEqual(receipt["revision"], 3)
                    self.assertEqual(list(store.iter_frames(sid)), [frame()])
                    self.assertFalse(receipt["manifest"]["physical_accuracy_verified"])
                    self.assertEqual(receipt["manifest"]["clinical_validation"], "UNVERIFIED")
                finally:
                    reopened.close()


if __name__ == "__main__":
    unittest.main()
