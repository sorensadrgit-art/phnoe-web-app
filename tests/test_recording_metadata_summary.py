"""Generated SQLite summary regressions; physical and clinical validation remain unverified."""
import re
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import test_recording_ack_integrity as integrity_fixtures
import test_recording_semantic_proofs as semantic_fixtures
from recording_store import RecordingStore
from session_index import SessionIndex
from test_recording_contract import frame, header
from test_recording_store import chunk


class RecordingMetadataSummaryTests(unittest.TestCase):
    recording = semantic_fixtures.RecordingSemanticProofTests.recording
    payload = staticmethod(semantic_fixtures.RecordingSemanticProofTests.payload)
    state = staticmethod(semantic_fixtures.RecordingSemanticProofTests.state)

    @contextmanager
    def chunk_scans(self, index):
        scans = {"metadata": [], "wire": []}

        def observe(statement):
            sql = " ".join(statement.lower().split())
            if not re.match(r"select\b", sql) or not re.search(r"\bfrom recording_chunks\b", sql):
                return
            where = sql.partition(" where ")[2].partition(" order by ")[0]
            if not re.search(r"\bsession_id\s*=", where) or re.search(r"\bchunk_id\s*=", where):
                return
            projection = sql.partition(" from ")[0]
            kind = "wire" if "*" in projection or "frames_json" in projection else "metadata"
            scans[kind].append(sql)

        # Each generated fixture owns a fresh connection with no pre-existing trace callback.
        index.conn.set_trace_callback(observe)
        try:
            yield scans
        finally:
            index.conn.set_trace_callback(None)

    def assert_summary(self, status, saved, received, gaps):
        self.assertEqual((status["saved_through"], status["received_through"], status["missing_ranges"]),
                         (saved, received, gaps))
        self.assertEqual(status["source_kind"], "synthetic")
        self.assertFalse(status["physical_accuracy_verified"])
        self.assertEqual(status["clinical_validation"], "UNVERIFIED")

    def test_warm_status_uses_one_metadata_and_one_wire_scan(self):
        sid = header()["session_id"]
        with self.recording(8) as (root, index, store):
            expected, before = store.status(sid), self.state(index)
            with self.chunk_scans(index) as scans:
                actual = store.status(sid)
            self.assertEqual(actual, expected)
            self.assert_summary(actual, 128, 128, [])
            self.assertEqual(self.state(index), before)
            cold_index = SessionIndex(root / "index.db", root / "projects")
            try:
                self.assertEqual(RecordingStore(cold_index).status(sid), expected)
                self.assertEqual(self.state(cold_index), before)
            finally:
                cold_index.close()
            self.assertEqual(len(scans["wire"]), 1, scans)
            self.assertEqual(len(scans["metadata"]), 1, scans)

    def test_ninth_append_uses_two_metadata_and_one_wire_scan(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            payload, before = self.payload(129, 144), self.state(index)
            with self.chunk_scans(index) as scans:
                ack = store.append(sid, payload)
            self.assert_summary(ack, 144, 144, [])
            self.assertEqual(ack["revision"], 10)
            after = self.state(index)
            self.assertEqual(len(after["recording_chunks"]), len(before["recording_chunks"]) + 1)
            self.assertEqual(len(after["audit_events"]), len(before["audit_events"]) + 1)
            row = index.conn.execute("SELECT frames_json,sha256 FROM recording_chunks WHERE chunk_id=?",
                                     (payload["chunk_id"],)).fetchone()
            self.assertEqual(tuple(row), (payload["frames_json"], payload["sha256"]))
            self.assertEqual(len(scans["wire"]), 1, scans)
            self.assertEqual(len(scans["metadata"]), 2, scans)

    def test_public_summary_gaps_retries_cold_rows_and_full_materialization(self):
        sid = header()["session_id"]
        with self.recording() as (root, index, store):
            initial = store.status(sid)
            self.assert_summary(initial, 0, 0, [])
            self.assertEqual(store.create(header()), initial)
            for sequence, saved, received, gaps in (
                    (1, 1, 1, []), (5, 1, 5, [[2, 4]]),
                    (3, 1, 5, [[2, 2], [4, 4]]),
                    (2, 3, 5, [[4, 4]]), (4, 5, 5, [])):
                ack = store.append(sid, chunk(sequence))
                self.assert_summary(ack, saved, received, gaps)
                self.assertEqual(store.status(sid), ack)
                before = self.state(index)
                self.assertEqual(store.append(sid, chunk(sequence)), ack)
                self.assertEqual(self.state(index), before)
                cold_index = SessionIndex(root / "index.db", root / "projects")
                try:
                    cold = RecordingStore(cold_index)
                    self.assertEqual(cold.status(sid), ack)
                    expected = [frame(i, (i - 1) * 30) for i in sorted(
                        row[0] for row in index.conn.execute("SELECT first_sequence FROM recording_chunks"))]
                    self.assertEqual(list(cold.iter_frames(sid)), expected)
                    self.assertEqual(self.state(cold_index), before)
                finally:
                    cold_index.close()
            finalized = store.finalize(sid, header()["operation_id"], 5)
            self.assert_summary(finalized, 5, 5, [])
            self.assertEqual(finalized["state"], "FINALIZED")
            before = self.state(index)
            self.assertEqual(store.finalize(sid, header()["operation_id"], 5), finalized)
            self.assertEqual(store.append(sid, chunk(5)), finalized)
            self.assertEqual(store.status(sid), finalized)
            self.assertEqual(list(store.iter_frames(sid)), [frame(i, (i - 1) * 30) for i in range(1, 6)])
            self.assertEqual(self.state(index), before)

    def test_late_tail_damage_refuses_summary_and_closes_snapshot(self):
        sid = header()["session_id"]
        for warm in (False, True):
            with self.subTest(warm=warm), self.recording(3) as (_, index, store):
                store.status(sid)
                if not warm:
                    store = RecordingStore(index)
                integrity_fixtures.RecordingAckIntegrityTests.allow_fixture_damage(index)
                index.conn.execute("UPDATE recording_chunks SET frames_json='[' WHERE first_sequence=33")
                index.conn.commit()
                before = self.state(index)
                with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT: stored chunk frames"):
                    store.status(sid)
                self.assertFalse(index.conn.in_transaction)
                self.assertEqual(self.state(index), before)

    def test_manifest_damage_refuses_summary_and_closes_snapshot(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            store.finalize(sid, header()["operation_id"], 32)
            index.conn.execute("DROP TRIGGER recording_header_immutable")
            index.conn.execute("UPDATE recordings SET manifest_json='{}' WHERE session_id=?", (sid,))
            index.conn.commit()
            before = self.state(index)
            with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT: manifest"):
                store.status(sid)
            self.assertFalse(index.conn.in_transaction)
            self.assertEqual(self.state(index), before)

    def test_receipt_metadata_io_error_preserves_identity_and_closes_snapshot(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            before = self.state(index)
            fault = OSError("TEST_ONLY receipt metadata read")
            with (patch.object(store, "_chunks", side_effect=fault) as chunks,
                  self.assertRaises(OSError) as caught):
                store.status(sid)
            self.assertIs(caught.exception, fault)
            chunks.assert_called_once_with(sid)
            self.assertFalse(index.conn.in_transaction)
            self.assertEqual(self.state(index), before)
            self.assert_summary(store.status(sid), 32, 32, [])


if __name__ == "__main__":
    unittest.main()
