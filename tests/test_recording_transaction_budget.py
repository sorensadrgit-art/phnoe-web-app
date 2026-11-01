"""Synthetic SQLite transaction checks; performance and runtime remain unverified."""
import hashlib
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import recording_store
from recording_contract import canonical_json, digest
from recording_store import RecordingStore
from session_index import SessionIndex
from test_recording_contract import frame, header


class RecordingTransactionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        self.index = SessionIndex(self.root / "index.db", self.root / "projects")
        self.addCleanup(lambda: self.index.close())
        self.store = RecordingStore(self.index)
        self.sid = header()["session_id"]
        self.store.create(header())
        self.first, self.second = self.payload(1, 16), self.payload(17, 32)
        self.store.append(self.sid, self.first)
        self.prior_ack = self.store.append(self.sid, self.second)

    @staticmethod
    def payload(first, last, *, chunk_id=None, time_shift=0):
        frames = [frame(i, (i - 1) * 30 + time_shift) for i in range(first, last + 1)]
        raw = canonical_json(frames)
        return {"operation_id": header()["operation_id"], "header_sha256": digest(header()),
                "chunk_id": chunk_id or f"{first:032x}", "frames_json": raw,
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()}

    @staticmethod
    def state(index):
        return {table: [tuple(row) for row in index.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("recordings", "recording_chunks", "audit_events")}

    @contextmanager
    def fresh(self):
        index = SessionIndex(self.root / "index.db", self.root / "projects")
        try:
            yield index, RecordingStore(index)
        finally:
            index.close()

    @contextmanager
    def validation_work(self):
        original = recording_store.validate_frames
        work = []
        def delegate(frames):
            result = original(frames)
            work.append(len(frames))
            return result
        with patch.object(recording_store, "validate_frames", side_effect=delegate):
            yield work

    def assert_ack(self, ack, last, revision):
        self.assertEqual((ack["saved_through"], ack["received_through"], ack["revision"]), (last, last, revision))
        self.assertEqual(ack["missing_ranges"], [])
        self.assertEqual(ack["header_sha256"], digest(header()))
        self.assertEqual(ack["operation_id"], header()["operation_id"])
        self.assertFalse(ack["physical_accuracy_verified"])
        self.assertEqual(ack["clinical_validation"], "UNVERIFIED")

    def assert_raw(self, index, payload):
        row = index.conn.execute("SELECT * FROM recording_chunks WHERE chunk_id=?", (payload["chunk_id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["frames_json"], payload["frames_json"])
        self.assertEqual(row["sha256"], hashlib.sha256(row["frames_json"].encode("utf-8")).hexdigest())

    def test_append_ack_validation_work_is_single_postwrite_prefix_pass(self):
        payload, before = self.payload(33, 48), self.state(self.index)
        with self.validation_work() as work:
            ack = self.store.append(self.sid, payload)
        self.assertGreater(sum(work), 0)
        self.assertLessEqual(sum(work), 64, work)
        self.assert_ack(ack, 48, 4)
        self.assertEqual(ack["state"], "RECORDING")
        self.assertIsNone(ack["manifest"])
        with self.fresh() as (index, store):
            self.assertEqual(store.status(self.sid), ack)
            self.assertEqual(list(store.iter_frames(self.sid)), [frame(i, (i - 1) * 30) for i in range(1, 49)])
            for part in (self.first, self.second, payload):
                self.assert_raw(index, part)
            after = self.state(index)
            self.assertEqual(len(after["recording_chunks"]), len(before["recording_chunks"]) + 1)
            self.assertEqual(len(after["audit_events"]), len(before["audit_events"]) + 1)
            index.verify_audit()

    def test_retry_ack_validation_work_rechecks_prefix_once(self):
        before = self.state(self.index)
        with self.validation_work() as work:
            ack = self.store.append(self.sid, self.second)
        self.assertGreater(sum(work), 0)
        self.assertLessEqual(sum(work), 48, work)
        self.assertEqual(ack, self.prior_ack)
        self.assert_ack(ack, 32, 3)
        with self.fresh() as (index, store):
            self.assertEqual(self.state(index), before)
            self.assertEqual(store.status(self.sid), ack)
            self.assert_raw(index, self.first)
            self.assert_raw(index, self.second)
            index.verify_audit()

    def test_finalize_retry_validation_work_reuses_same_transaction_status(self):
        receipt = self.store.finalize(self.sid, header()["operation_id"], 32)
        before = self.state(self.index)
        with self.validation_work() as work:
            retry = self.store.finalize(self.sid, header()["operation_id"], 32)
        self.assertGreater(sum(work), 0)
        self.assertLessEqual(sum(work), 64, work)
        self.assertEqual(retry, receipt)
        self.assert_ack(retry, 32, 4)
        self.assertEqual(retry["state"], "FINALIZED")
        self.assertEqual(retry["manifest_sha256"], digest(retry["manifest"]))
        self.assertEqual(retry["manifest"]["frame_count"], 32)
        self.assertEqual(retry["manifest"]["last_sequence"], 32)
        self.assertEqual(retry["manifest"]["unacknowledged_tail"], "NONE_REPORTED")
        with self.fresh() as (index, store):
            self.assertEqual(self.state(index), before)
            self.assertEqual(store.verify(self.sid), retry)
            self.assertEqual(list(store.iter_frames(self.sid)), [frame(i, (i - 1) * 30) for i in range(1, 33)])
            self.assert_raw(index, self.first)
            self.assert_raw(index, self.second)
            index.verify_audit()

    def test_finalized_duplicate_append_preserves_receipt_and_all_rows(self):
        receipt = self.store.finalize(self.sid, header()["operation_id"], 32)
        before = self.state(self.index)
        with self.validation_work() as work:
            retry = self.store.append(self.sid, self.second)
        self.assertLessEqual(sum(work), 48, work)
        self.assertEqual(retry, receipt)
        with self.fresh() as (index, store):
            self.assertEqual(self.state(index), before)
            self.assertEqual(store.verify(self.sid), receipt)

    def test_postwrite_old_new_and_global_corruption_rolls_back_before_ack(self):
        for kind in ("old", "new", "global"):
            with self.subTest(kind=kind):
                if kind == "global":
                    self.index.record_audit_event("unrelated-synthetic-session", "SYNTHETIC_FIXTURE", {"fixture": True})
                before, original, injections = self.state(self.index), self.index._append_audit, []
                def insert_then_damage(*args, original=original, injections=injections, kind=kind, **kwargs):
                    original(*args, **kwargs)
                    if args[1] == "RECORDING_CHUNK_SAVED":
                        injections.append(kind)
                        if kind == "global":
                            self.index.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
                            self.index.conn.execute("UPDATE audit_events SET details_json='{}' WHERE session_id=?",
                                                    ("unrelated-synthetic-session",))
                        else:
                            self.index.conn.execute("DROP TRIGGER IF EXISTS recording_chunk_no_update")
                            target = self.first["chunk_id"] if kind == "old" else self.payload(33, 48)["chunk_id"]
                            self.index.conn.execute("UPDATE recording_chunks SET frames_json='[' WHERE chunk_id=?", (target,))
                with (
                    patch.object(self.index, "_append_audit", side_effect=insert_then_damage),
                    self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT|AUDIT_INVALID"),
                ):
                    self.store.append(self.sid, self.payload(33, 48))
                self.assertEqual(injections, [kind])
                with self.fresh() as (index, store):
                    self.assertEqual(self.state(index), before)
                    self.assertEqual(store.status(self.sid), self.prior_ack)
                    self.assert_raw(index, self.first)
                    self.assert_raw(index, self.second)
                    self.assertIsNone(index.conn.execute("SELECT 1 FROM recording_chunks WHERE first_sequence=33").fetchone())
                    index.verify_audit()

    def test_valid_and_corrupt_preflight_rejections_preserve_precedence_and_rows(self):
        for kind, reason in (("duplicate", "RECORDING_CONFLICT: chunk identity"),
                             ("overlap", "RECORDING_CONFLICT: overlapping sequence"),
                             ("time", "MEASUREMENT_INVALID: cross-chunk timestamps"),
                             ("finalized", "RECORDING_FINALIZED")):
            for corrupt in (False, True):
                with self.subTest(kind=kind, corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "projects").mkdir()
                    index = SessionIndex(root / "index.db", root / "projects")
                    try:
                        store = RecordingStore(index)
                        store.create(header())
                        store.append(self.sid, self.first)
                        store.append(self.sid, self.second)
                        if kind == "finalized":
                            store.finalize(self.sid, header()["operation_id"], 32)
                        if corrupt:
                            index.conn.execute("DROP TRIGGER IF EXISTS recording_chunk_no_update")
                            index.conn.execute("UPDATE recording_chunks SET frames_json='[' WHERE chunk_id=?",
                                               (self.first["chunk_id"],))
                            index.conn.commit()
                        payload = {"duplicate": self.payload(1, 16, time_shift=1),
                                   "overlap": self.payload(8, 23, chunk_id="f" * 32),
                                   "time": self.payload(33, 48, time_shift=-960),
                                   "finalized": self.payload(33, 48)}[kind]
                        before = self.state(index)
                        with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT" if corrupt else reason):
                            store.append(self.sid, payload)
                        reopened = SessionIndex(root / "index.db", root / "projects")
                        try:
                            self.assertEqual(self.state(reopened), before)
                        finally:
                            reopened.close()
                    finally:
                        index.close()

    def test_historical_metadata_type_corruption_keeps_integrity_error_precedence(self):
        for column in ("last_sequence", "last_time_ms"):
            with self.subTest(column=column):
                self.index.conn.execute("DROP TRIGGER IF EXISTS recording_chunk_no_update")
                raw_before = [tuple(row) for row in self.index.conn.execute(
                    "SELECT chunk_id,frames_json,sha256 FROM recording_chunks ORDER BY chunk_id")]
                receipts_before = self.state(self.index)["audit_events"]
                self.index.conn.execute(f"UPDATE recording_chunks SET {column}='malformed' WHERE chunk_id=?",
                                        (self.first["chunk_id"],))
                self.index.conn.commit()
                self.index.verify_audit()
                before = self.state(self.index)
                with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT|AUDIT_INVALID"):
                    self.store.append(self.sid, self.payload(33, 48))
                with self.fresh() as (index, _):
                    self.assertEqual(self.state(index), before)
                    self.assertEqual(self.state(index)["audit_events"], receipts_before)
                    self.assertEqual([tuple(row) for row in index.conn.execute(
                        "SELECT chunk_id,frames_json,sha256 FROM recording_chunks ORDER BY chunk_id")], raw_before)
                self.index.conn.execute(f"UPDATE recording_chunks SET {column}=? WHERE chunk_id=?",
                                        (16 if column == "last_sequence" else 450, self.first["chunk_id"]))
                self.index.conn.commit()

    def test_preflight_io_fault_is_not_replaced_by_integrity_fallback(self):
        fault, before = OSError("synthetic preflight read fault"), self.state(self.index)
        with (
            patch.object(self.store, "_chunks", side_effect=[fault, ValueError("masked read fault")]) as chunks,
            patch.object(self.store, "iter_frames", wraps=self.store.iter_frames),
        ):
            with self.assertRaises(OSError) as caught:
                self.store.append(self.sid, self.payload(33, 48))
            self.assertIs(caught.exception, fault)
            self.assertEqual(chunks.call_count, 1)
        with self.fresh() as (index, _):
            self.assertEqual(self.state(index), before)

    def test_audit_io_fault_after_real_insert_preserves_original_error_and_rolls_back(self):
        before, original, writes = self.state(self.index), self.index._append_audit, []
        fault = OSError("synthetic audit write fault")
        def insert_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            writes.append(args[1])
            raise fault
        with (
            patch.object(self.index, "_append_audit", side_effect=insert_then_fail),
            patch.object(self.store, "status", side_effect=AssertionError("unexpected final status")) as status,
        ):
            with self.assertRaises(OSError) as caught:
                self.store.append(self.sid, self.payload(33, 48))
            self.assertIs(caught.exception, fault)
            status.assert_not_called()
        self.assertEqual(writes, ["RECORDING_CHUNK_SAVED"])
        with self.fresh() as (index, store):
            self.assertEqual(self.state(index), before)
            self.assertEqual(store.status(self.sid), self.prior_ack)

    def test_transaction_exit_fault_after_real_writes_rolls_back_without_ack(self):
        before, original = self.state(self.index), self.index.transaction
        fault, statuses, actual_status = OSError("synthetic transaction exit fault before commit"), [], self.store.status
        def status_then_record(*args, **kwargs):
            result = actual_status(*args, **kwargs)
            statuses.append(result)
            return result
        @contextmanager
        def fail_exit():
            with original():
                yield
                raise fault
        with (
            patch.object(self.index, "transaction", fail_exit),
            patch.object(self.store, "status", side_effect=status_then_record),
        ):
            with self.assertRaises(OSError) as caught:
                self.store.append(self.sid, self.payload(33, 48))
            self.assertIs(caught.exception, fault)
        self.assertEqual(len(statuses), 1)
        self.assert_ack(statuses[0], 48, 4)
        with self.fresh() as (index, store):
            self.assertEqual(self.state(index), before)
            self.assertEqual(store.status(self.sid), self.prior_ack)


if __name__ == "__main__":
    unittest.main()
