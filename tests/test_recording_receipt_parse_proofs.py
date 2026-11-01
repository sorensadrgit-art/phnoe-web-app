"""Generated SQLite receipts: exact parse facts never replace a fresh integrity decision."""
import json
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import recording_store
import session_contract
import test_recording_ack_integrity as integrity_fixtures
import test_recording_semantic_proofs as semantic_fixtures
from recording_store import RecordingStore
from session_index import SessionIndex
from test_recording_contract import header
from test_recording_store import chunk


class RecordingReceiptParseProofTests(unittest.TestCase):
    recording = semantic_fixtures.RecordingSemanticProofTests.recording
    payload = staticmethod(semantic_fixtures.RecordingSemanticProofTests.payload)

    @contextmanager
    def parse_work(self, index):
        values = {row[0] for row in index.conn.execute("SELECT details_json FROM audit_events")}
        code, work, previous = session_contract.strict_json_loads.__code__, [], sys.getprofile()
        def observe(frame, event, arg):
            value = frame.f_locals.get("value")
            if event == "call" and frame.f_code is code and type(value) is str and value in values:
                work.append(value)
        sys.setprofile(observe)
        try:
            yield work
        finally:
            sys.setprofile(previous)

    def test_eight_warm_chunks_status_reparses_zero_receipts(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            expected = store.status(sid)
            with self.parse_work(index) as work:
                actual = store.status(sid)
            self.assertEqual(actual, expected)
            self.assertEqual(len(work), 0, "Baseline parses all nine exact unchanged receipt strings")
            self.assertFalse(actual["physical_accuracy_verified"])
            self.assertEqual(actual["clinical_validation"], "UNVERIFIED")

    def test_append_nine_only_parses_new_receipt(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            code, work, previous = session_contract.strict_json_loads.__code__, [], sys.getprofile()
            def observe(frame, event, arg):
                value = frame.f_locals.get("value")
                if event == "call" and frame.f_code is code and type(value) is str and '"chunk_id"' in value:
                    work.append(value)
            sys.setprofile(observe)
            try:
                ack = store.append(sid, self.payload(129, 144))
            finally:
                sys.setprofile(previous)
            self.assertEqual(len(work), 1)
            self.assertEqual((ack["saved_through"], ack["received_through"], ack["revision"]), (144, 144, 10))
            self.assertEqual(ack["missing_ranges"], [])
            index.verify_audit()

    def test_materialization_verify_and_finalize_still_parse_all_receipts(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            for action in (lambda: list(store.iter_frames(sid)), lambda: store.verify(sid),
                           lambda: store.finalize(sid, header()["operation_id"], 32)):
                with self.parse_work(index) as work:
                    action()
                self.assertGreaterEqual(len(work), 3)
            self.assertEqual(store.verify(sid)["manifest"]["frame_count"], 32)

    def test_new_store_reopen_and_connection_replacement_are_cold(self):
        sid = header()["session_id"]
        with self.recording(2) as (root, index, store):
            with self.parse_work(index) as work:
                RecordingStore(index).status(sid)
            self.assertEqual(len(work), 3)
            other = SessionIndex(root / "index.db", root / "projects")
            try:
                store.index = other
                with self.parse_work(other) as work:
                    store.status(sid)
                self.assertEqual(len(work), 3)
                self.assertIs(store._receipt_connection, other.conn)
            finally:
                store.index = index
                other.close()

    def test_parser_binding_defaults_and_decoder_helpers_disable_reuse(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            original = recording_store.strict_json_loads
            real_decode = session_contract.json.JSONDecoder.raw_decode
            def decode(instance, value, idx=0):
                return real_decode(instance, value, idx)
            def delegate(value):
                return original(value)
            changes = (
                patch.object(recording_store, "strict_json_loads", new=delegate),
                patch.object(original, "__defaults__", new=(None,)),
                patch.object(session_contract.json.JSONDecoder, "raw_decode", new=decode),
                patch.object(session_contract.json.scanner, "make_scanner",
                             new=session_contract.json.scanner.py_make_scanner),
            )
            for change in changes:
                store.status(sid)
                with change, self.parse_work(index) as work:
                    self.assertEqual(store.status(sid)["saved_through"], 32)
                    self.assertGreaterEqual(len(work), 3)
                    self.assertEqual(store._receipt_proofs, {})

    def test_parser_code_change_is_not_admitted_as_a_new_pure_profile(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, _, store):
            original = recording_store.strict_json_loads
            saved_code = original.__code__
            saved = types.FunctionType(saved_code, original.__globals__)
            def replacement(value):
                return globals()["_receipt_original"](value)
            with patch.dict(original.__globals__, {"_receipt_original": saved}):
                try:
                    original.__code__ = replacement.__code__
                    self.assertEqual(store.status(sid)["saved_through"], 32)
                    self.assertEqual(store._receipt_proofs, {})
                finally:
                    original.__code__ = saved_code
                    self.assertIs(original.__code__, saved_code)

    def test_decoder_scanner_alias_change_reaches_receipt_parser_and_clears(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            expected = store.status(sid)
            decoder = session_contract.json.decoder
            saved_scanner = decoder.scanner
            native_make_scanner = saved_scanner.make_scanner
            receipts = [row[0] for row in index.conn.execute("SELECT details_json FROM audit_events ORDER BY id")]
            observed = []
            def make_scanner(context):
                native_scan = native_make_scanner(context)
                def scan_once(raw, position):
                    if raw in receipts:
                        observed.append(raw)
                        raise ValueError("RECEIPT_SCANNER_REPLACED")
                    return native_scan(raw, position)
                return scan_once
            try:
                decoder.scanner = types.SimpleNamespace(make_scanner=make_scanner)
                self.assertIs(session_contract.json.scanner, saved_scanner)
                with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT: audit receipt JSON"):
                    store.status(sid)
                self.assertEqual(observed, [receipts[0]])
                self.assertEqual(store._receipt_proofs, {})
            finally:
                decoder.scanner = saved_scanner
                self.assertIs(decoder.scanner, saved_scanner)
            self.assertEqual(store.status(sid), expected)

    def test_mid_scan_parser_change_refuses_and_clears(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            original_audit, original_parse = index.verify_audit, recording_store.strict_json_loads
            def altered(value):
                return original_parse(value)
            def change():
                result = original_audit()
                recording_store.strict_json_loads = altered
                return result
            try:
                with patch.object(index, "verify_audit", new=change), self.assertRaisesRegex(
                        ValueError, "receipt validation context changed"):
                    store.status(sid)
                self.assertEqual(store._receipt_proofs, {})
            finally:
                recording_store.strict_json_loads = original_parse

    def test_mid_scan_connection_change_refuses_and_clears(self):
        sid = header()["session_id"]
        with self.recording(2) as (root, index, store):
            other = SessionIndex(root / "index.db", root / "projects")
            original_conn, original_audit = index.conn, index.verify_audit
            def change():
                result = original_audit()
                index.conn = other.conn
                return result
            try:
                with patch.object(index, "verify_audit", new=change), self.assertRaisesRegex(
                        ValueError, "receipt validation context changed"):
                    store.status(sid)
                self.assertEqual(store._receipt_proofs, {})
            finally:
                index.conn = original_conn
                other.close()

    def test_fifo_limit_changes_eviction_and_invalid_limits_are_safe(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            with patch.object(recording_store, "_RECEIPT_MEMO_MAX_ENTRIES", new=2):
                with self.parse_work(index) as work:
                    self.assertEqual(store.status(sid)["saved_through"], 128)
                self.assertEqual(len(work), 9)
                self.assertLessEqual(len(store._receipt_proofs), 2)
                with self.parse_work(index) as work:
                    store.status(sid)
                self.assertGreaterEqual(len(work), 7)
            for invalid in (0, -1, True, 4097):
                with patch.object(recording_store, "_RECEIPT_MEMO_MAX_ENTRIES", new=invalid), self.parse_work(index) as work:
                    self.assertEqual(store.status(sid)["saved_through"], 128)
                    self.assertEqual(len(work), 9)
                    self.assertEqual(store._receipt_proofs, {})

    def test_exact_whitespace_large_raw_and_scalar_equality_preserve_semantics(self):
        sid = header()["session_id"]
        with self.recording(1) as (_, index, store):
            integrity_fixtures.RecordingAckIntegrityTests.allow_fixture_damage(index)
            event = index.conn.execute("SELECT * FROM audit_events WHERE event_type='RECORDING_CHUNK_SAVED'").fetchone()
            details = json.loads(event["details_json"])
            details["first_sequence"] = 1.0
            raw = " " * 257 + json.dumps(details)
            index.conn.execute("UPDATE audit_events SET details_json=? WHERE id=?", (raw, event["id"]))
            integrity_fixtures.RecordingAckIntegrityTests.rechain_fixture(index)
            for _ in range(2):
                with self.parse_work(index) as work:
                    self.assertEqual(store.status(sid)["saved_through"], 16)
                self.assertIn(raw, work)
                self.assertNotIn(raw, store._receipt_proofs)
            compact = json.dumps(details, separators=(",", ":"))
            index.conn.execute("UPDATE audit_events SET details_json=? WHERE id=?", (compact, event["id"]))
            integrity_fixtures.RecordingAckIntegrityTests.rechain_fixture(index)
            self.assertEqual(store.status(sid)["saved_through"], 16)
            self.assertIn(compact, store._receipt_proofs)
            self.assertNotEqual(compact, event["details_json"])

    def test_warm_memo_never_accepts_receipt_or_audit_damage(self):
        sid = header()["session_id"]
        for coherent in (False, True):
            for damage in ("identity", "metadata", "kind", "revision", "missing", "invalid", "duplicate", "nonfinite"):
                with self.subTest(coherent=coherent, damage=damage), self.recording(1) as (_, index, store):
                    integrity_fixtures.RecordingAckIntegrityTests.allow_fixture_damage(index)
                    row = index.conn.execute("SELECT * FROM audit_events WHERE event_type='RECORDING_CHUNK_SAVED'").fetchone()
                    details = json.loads(row["details_json"])
                    if damage == "identity":
                        details["chunk_id"] = "f" * 32
                    elif damage == "metadata":
                        details["last_sequence"] += 1
                    if damage in ("identity", "metadata"):
                        index.conn.execute("UPDATE audit_events SET details_json=? WHERE id=?", (json.dumps(details), row["id"]))
                    elif damage == "kind":
                        index.conn.execute("UPDATE audit_events SET event_type='RECORDING_FINALIZED' WHERE id=?", (row["id"],))
                    elif damage == "revision":
                        index.conn.execute("UPDATE audit_events SET revision=99 WHERE id=?", (row["id"],))
                    elif damage == "missing":
                        index.conn.execute("DELETE FROM audit_events WHERE id=?", (row["id"],))
                    else:
                        raw = {"invalid": "[", "duplicate": '{"chunk_id":"a","chunk_id":"b"}',
                               "nonfinite": '{"value":1e999}'}[damage]
                        index.conn.execute("UPDATE audit_events SET details_json=? WHERE id=?", (raw, row["id"]))
                    if coherent:
                        integrity_fixtures.RecordingAckIntegrityTests.rechain_fixture(index)
                    index.conn.commit()
                    before = list(index.conn.iterdump())
                    for action in (lambda: store.status(sid), lambda: list(store.iter_frames(sid)),
                                   lambda: store.append(sid, chunk(17))):
                        with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT|AUDIT_INVALID"):
                            action()
                        self.assertEqual(list(index.conn.iterdump()), before)
                    for raw in ("[", '{"chunk_id":"a","chunk_id":"b"}', '{"value":1e999}'):
                        self.assertNotIn(raw, store._receipt_proofs)


    @contextmanager
    def receipt_admission_work(self):
        # Observe real helpers without changing any parser/profile binding.
        codes = (recording_store._receipt_flat.__code__,
                 RecordingStore._receipt_details.__code__, SessionIndex.verify_audit.__code__)
        work = {"eligibility": 0, "details": 0, "audit": 0}
        previous = sys.getprofile()
        def observe(frame, event, _arg):
            if event == "call":
                if frame.f_code is codes[0]:
                    work["eligibility"] += 1
                elif frame.f_code is codes[1]:
                    work["details"] += 1
                elif frame.f_code is codes[2]:
                    work["audit"] += 1
        sys.setprofile(observe)
        try:
            yield work
        finally:
            sys.setprofile(previous)

    def test_warm_receipts_do_not_repeat_cache_admission_eligibility(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            expected = store.status(sid)
            facts = dict(store._receipt_proofs)
            before = list(index.conn.iterdump())
            with self.receipt_admission_work() as work:
                actual = store.status(sid)
            self.assertEqual(actual, expected)
            self.assertEqual(work, {"eligibility": 0, "details": 9, "audit": 1})
            self.assertEqual(store._receipt_proofs, facts)
            self.assertEqual(list(index.conn.iterdump()), before)
            index.verify_audit()

    def test_append_nine_checks_cache_admission_only_for_new_receipt(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            with self.receipt_admission_work() as work:
                ack = store.append(sid, self.payload(129, 144))
            self.assertEqual(work, {"eligibility": 1, "details": 10, "audit": 1})
            self.assertEqual((ack["saved_through"], ack["received_through"], ack["revision"]), (144, 144, 10))
            self.assertEqual(ack["missing_ranges"], [])
            self.assertFalse(ack["physical_accuracy_verified"])
            self.assertEqual(ack["clinical_validation"], "UNVERIFIED")
            self.assertEqual(index.conn.execute("SELECT count(*) FROM recording_chunks").fetchone()[0], 9)
            self.assertEqual(index.conn.execute("SELECT count(*) FROM audit_events").fetchone()[0], 10)
            index.verify_audit()

    def test_cold_receipts_still_check_every_cache_admission(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            expected = store.status(sid)
            cold = RecordingStore(index)
            with self.receipt_admission_work() as work:
                actual = cold.status(sid)
            self.assertEqual(actual, expected)
            self.assertEqual(work, {"eligibility": 3, "details": 3, "audit": 1})
            self.assertEqual(len(cold._receipt_proofs), 3)
            index.verify_audit()


if __name__ == "__main__":
    unittest.main()
