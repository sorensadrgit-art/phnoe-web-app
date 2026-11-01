"""Generated SQLite semantic-fact regressions; no patient data or timing thresholds."""
import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import recording_contract
import recording_store
import test_recording_ack_integrity as integrity_fixtures
import test_recording_transaction_budget as budget_fixtures
from recording_contract import canonical_json, digest
from recording_store import RecordingStore
from session_index import SessionIndex
from test_recording_contract import frame, header


class RecordingSemanticProofTests(unittest.TestCase):
    payload = staticmethod(budget_fixtures.RecordingTransactionBudgetTests.payload)
    state = staticmethod(budget_fixtures.RecordingTransactionBudgetTests.state)

    @contextmanager
    def recording(self, chunks=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "projects").mkdir()
            index = SessionIndex(root / "index.db", root / "projects")
            try:
                store = RecordingStore(index)
                store.create(header())
                for first in range(1, chunks * 16 + 1, 16):
                    store.append(header()["session_id"], self.payload(first, first + 15))
                yield root, index, store
            finally:
                index.close()

    @contextmanager
    def validation_work(self):
        original, work = recording_store.validate_frames, []
        def delegate(frames):
            result = original(frames)
            work.append(len(frames))
            return result
        # Observe the real validator under one stable callable identity while warming.
        with patch.object(recording_store, "validate_frames", new=delegate):
            yield work

    def test_eight_warm_chunks_append_nine_validates_exactly_32_frames(self):
        sid = header()["session_id"]
        with self.validation_work() as work, self.recording() as (root, index, store):
            parts = [self.payload(first, first + 15) for first in range(1, 145, 16)]
            for part in parts[:8]:
                store.append(sid, part)
            before = self.state(index)
            work.clear()
            ack = store.append(sid, parts[8])
            self.assertEqual(work, [16, 16], "Baseline repeats 160 frame validations; no accepting validator double")
            self.assertEqual((ack["saved_through"], ack["received_through"], ack["revision"]), (144, 144, 10))
            self.assertEqual(ack["missing_ranges"], [])
            self.assertEqual(ack["header_sha256"], digest(header()))
            self.assertFalse(ack["physical_accuracy_verified"])
            self.assertEqual(ack["clinical_validation"], "UNVERIFIED")
            self.assertEqual(len(self.state(index)["audit_events"]), len(before["audit_events"]) + 1)
            for part, row in zip(parts, index.conn.execute("SELECT * FROM recording_chunks ORDER BY first_sequence"), strict=True):
                self.assertEqual(row["frames_json"], part["frames_json"])
                self.assertEqual(row["sha256"], hashlib.sha256(row["frames_json"].encode()).hexdigest())
            index.verify_audit()
            cold_index = SessionIndex(root / "index.db", root / "projects")
            try:
                cold = RecordingStore(cold_index)
                self.assertEqual(cold.status(sid), ack)
                self.assertEqual(list(cold.iter_frames(sid)), [frame(i, (i - 1) * 30) for i in range(1, 145)])
                self.assertEqual(self.state(cold_index), self.state(index))
                cold_index.verify_audit()
            finally:
                cold_index.close()

    def test_warm_status_freshly_hashes_every_wire_and_verifies_global_audit(self):
        sid = header()["session_id"]
        with self.validation_work() as work, self.recording(8) as (_, index, store):
            expected = store.status(sid)
            wires = [row[0].encode() for row in index.conn.execute("SELECT frames_json FROM recording_chunks ORDER BY first_sequence")]
            original, observed = hashlib.sha256, []
            def hash_real(data=b"", **kwargs):
                observed.append(data)
                return original(data, **kwargs)
            work.clear()
            with patch.object(recording_store.hashlib, "sha256", new=hash_real), patch.object(index, "verify_audit", wraps=index.verify_audit) as audit:
                self.assertEqual(store.status(sid), expected)
                self.assertEqual(audit.call_count, 1)
            self.assertEqual(work, [])
            for wire in wires:
                self.assertEqual(observed.count(wire), 1)
            self.assertEqual(store.status(sid), expected)

    def test_materialized_mutation_and_manifest_use_full_fresh_validation(self):
        sid = header()["session_id"]
        with self.validation_work() as work, self.recording(2) as (_, index, store):
            ack, before = store.status(sid), self.state(index)
            work.clear()
            materialized = list(store.iter_frames(sid))
            self.assertEqual(work, [16, 16])
            materialized[0]["landmarks"][0][0] = .99
            materialized[0]["sequence"] = 999
            work.clear()
            self.assertEqual(store.status(sid), ack)
            self.assertEqual(work, [])
            self.assertEqual(list(store.iter_frames(sid)), [frame(i, (i - 1) * 30) for i in range(1, 33)])
            work.clear()
            manifest = store._manifest(sid, "operator_finished")
            self.assertEqual(work, [16, 16])
            self.assertEqual((manifest["frame_count"], manifest["last_sequence"]), (32, 32))
            self.assertEqual(self.state(index), before)

    def test_exact_wire_exponent_and_whitespace_survive_warm_status_and_replay(self):
        sid = header()["session_id"]
        with self.recording() as (_, index, store):
            value = frame()
            value["landmarks"][0][2] = 1e-7
            raw = json.dumps([value], indent=1).replace("1e-07", "1e-7") + " \n"
            part = self.payload(1, 1)
            part.update(frames_json=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())
            ack = store.append(sid, part)
            before = self.state(index)
            self.assertEqual(store.status(sid), ack)
            self.assertEqual(store.append(sid, part), ack)
            self.assertEqual(index.conn.execute("SELECT frames_json FROM recording_chunks").fetchone()[0], raw)
            self.assertEqual(list(store.iter_frames(sid)), [value])
            self.assertEqual(self.state(index), before)

    def test_active_validator_and_decoder_identity_change_are_cold(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, _, store):
            original_frames, original_decode = recording_store.validate_frames, recording_store.strict_json_loads
            for target in ("validate_frames", "strict_json_loads"):
                calls = []
                if target == "validate_frames":
                    def delegate(value, calls=calls):
                        calls.append(len(value))
                        return original_frames(value)
                else:
                    def delegate(value, calls=calls):
                        decoded = original_decode(value)
                        if isinstance(decoded, list):
                            calls.append(len(decoded))
                        return decoded
                with self.subTest(target=target), patch.object(recording_store, target, new=delegate):
                    store.status(sid)
                    self.assertEqual(calls, [16, 16])
                    calls.clear()
                    store.status(sid)
                    self.assertEqual(calls, [])

    def test_contract_limit_change_invalidates_previous_semantics(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            before = self.state(index)
            store.status(sid)
            with patch.object(recording_contract, "MAX_FRAMES", 16), self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT: stored chunk frames"):
                store.status(sid)
            self.assertEqual(self.state(index), before)
            self.assertEqual(store.status(sid)["saved_through"], 32)

    def test_new_store_reopen_and_replaced_connection_are_cold(self):
        sid = header()["session_id"]
        with self.validation_work() as work, self.recording(2) as (root, index, store):
            ack = store.status(sid)
            work.clear()
            self.assertEqual(RecordingStore(index).status(sid), ack)
            self.assertEqual(work, [16, 16])
            replacement = SessionIndex(root / "index.db", root / "projects")
            try:
                work.clear()
                store.index = replacement
                self.assertEqual(store.status(sid), ack)
                self.assertEqual(work, [16, 16])
                work.clear()
                self.assertEqual(store.status(sid), ack)
                self.assertEqual(work, [])
            finally:
                store.index = index
                replacement.close()
            work.clear()
            self.assertEqual(store.status(sid), ack)
            self.assertEqual(work, [16, 16])

    def test_bounded_eviction_falls_back_to_full_validation(self):
        sid = header()["session_id"]
        with patch.object(recording_store, "_SEMANTIC_PROOF_LIMIT", 2), self.validation_work() as work, self.recording(3) as (_, _, store):
            self.assertLessEqual(len(store._semantic_proofs), 2)
            work.clear()
            self.assertEqual(store.status(sid)["saved_through"], 48)
            self.assertEqual(work, [16, 16, 16])
            self.assertLessEqual(len(store._semantic_proofs), 2)

    def test_all_warm_ack_paths_refuse_prior_damage_without_publication(self):
        fixture = integrity_fixtures.RecordingAckIntegrityTests()
        cases = ("malformed_bytes", "digest", "range", "time", "replaced_bytes", "missing_receipt",
                 "mismatched_receipt", "wrong_receipt_revision", "oversized_wire", "malformed_receipt",
                 "scalar_receipt", "broken_audit_chain")
        for kind in cases:
            for action in ("status", "list", "create_retry", "chunk_retry", "new_chunk", "finalize", "verify"):
                with self.subTest(kind=kind, action=action), fixture.recording() as (_, index, store):
                    sid = header()["session_id"]
                    store.status(sid)
                    fixture.damage(index, kind)
                    before = self.state(index)
                    calls = {"status": lambda store=store, sid=sid: store.status(sid), "list": store.list_recordings,
                             "create_retry": lambda store=store: store.create(header()),
                             "chunk_retry": lambda store=store, sid=sid: store.append(sid, integrity_fixtures.chunk(1)),
                             "new_chunk": lambda store=store, sid=sid: store.append(sid, integrity_fixtures.chunk(2)),
                             "finalize": lambda store=store, sid=sid: store.finalize(sid, header()["operation_id"], 1),
                             "verify": lambda store=store, sid=sid: store.verify(sid)}
                    with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT|AUDIT_INVALID"):
                        calls[action]()
                    self.assertEqual(self.state(index), before)

    def test_changed_self_consistent_wire_is_fully_validated_on_miss(self):
        fixture = integrity_fixtures.RecordingAckIntegrityTests()
        for kind in ("duplicate_key", "exponent_overflow", "shape", "internal_sequence", "invalid_reason", "geometry"):
            with self.subTest(kind=kind), fixture.recording() as (_, index, store):
                sid = header()["session_id"]
                store.status(sid)
                fixture.allow_fixture_damage(index)
                values = [frame()]
                if kind == "shape":
                    values[0]["landmarks"] = []
                elif kind == "internal_sequence":
                    values.append(frame(3, 30))
                elif kind == "invalid_reason":
                    values[0].update(valid=False, reasons=["UNKNOWN_REASON"])
                elif kind == "geometry":
                    values[0]["landmarks"][23] = values[0]["landmarks"][11][:]
                raw = canonical_json(values)
                if kind == "duplicate_key":
                    raw = raw.replace('"sequence":1', '"sequence":1,"sequence":1')
                elif kind == "exponent_overflow":
                    raw = raw.replace('"time_ms":0', '"time_ms":1e400')
                part = integrity_fixtures.chunk(1)
                part.update(frames_json=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())
                fixture.replace_chunk(index, part)
                index.conn.commit()
                index.verify_audit()
                before = self.state(index)
                with self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT: stored chunk frames"):
                    store.status(sid)
                self.assertEqual(self.state(index), before)

    def test_warm_postwrite_old_new_and_global_damage_rolls_back_before_ack(self):
        sid = header()["session_id"]
        for kind in ("old", "new", "global"):
            with self.subTest(kind=kind), self.validation_work(), self.recording(8) as (_, index, store):
                index.record_audit_event("unrelated-synthetic", "TEST_ONLY", {"fixture": True})
                store.status(sid)
                before, original, injected = self.state(index), index._append_audit, []
                def damage_after_write(*args, original=original, kind=kind, index=index, injected=injected, **kwargs):
                    original(*args, **kwargs)
                    if args[1] == "RECORDING_CHUNK_SAVED":
                        injected.append(kind)
                        if kind == "global":
                            index.conn.execute("DROP TRIGGER audit_no_update")
                            index.conn.execute("UPDATE audit_events SET details_json='{}' WHERE session_id='unrelated-synthetic'")
                        else:
                            index.conn.execute("DROP TRIGGER recording_chunk_no_update")
                            target = self.payload(1, 16)["chunk_id"] if kind == "old" else self.payload(129, 144)["chunk_id"]
                            index.conn.execute("UPDATE recording_chunks SET frames_json='[' WHERE chunk_id=?", (target,))
                with patch.object(index, "_append_audit", new=damage_after_write), self.assertRaisesRegex(ValueError, "RECORDING_CORRUPT|AUDIT_INVALID"):
                    store.append(sid, self.payload(129, 144))
                self.assertEqual(injected, [kind])
                self.assertEqual(self.state(index), before)
                self.assertEqual(store.status(sid)["saved_through"], 128)
                self.assertIsNone(index.conn.execute("SELECT 1 FROM recording_chunks WHERE first_sequence=129").fetchone())
                index.verify_audit()


    def test_failed_transaction_exit_cannot_promote_a_semantic_fact_to_ack(self):
        sid = header()["session_id"]
        with self.validation_work(), self.recording(8) as (_, index, store):
            before, original = self.state(index), index.transaction
            fault = OSError("TEST_ONLY transaction exit before commit")
            @contextmanager
            def fail_exit():
                with original():
                    yield
                    raise fault
            with patch.object(index, "transaction", new=fail_exit), self.assertRaises(OSError) as caught:
                store.append(sid, self.payload(129, 144))
            self.assertIs(caught.exception, fault)
            self.assertEqual(self.state(index), before)
            self.assertEqual(store.status(sid)["saved_through"], 128)
            self.assertIsNone(index.conn.execute("SELECT 1 FROM recording_chunks WHERE first_sequence=129").fetchone())
            ack = store.append(sid, self.payload(129, 144))
            self.assertEqual((ack["saved_through"], ack["revision"]), (144, 10))
            self.assertEqual(len(self.state(index)["audit_events"]), len(before["audit_events"]) + 1)
            index.verify_audit()

if __name__ == "__main__":
    unittest.main()
