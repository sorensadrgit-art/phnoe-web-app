"""Real SQLite wire-work counts; generated fixtures, no parser or digest replacements."""
import hashlib
import sys
import unittest
from contextlib import contextmanager

import recording_store
import test_recording_semantic_proofs as semantic_fixtures
from recording_contract import MAX_CHUNK_BYTES
from recording_store import RecordingStore
from test_recording_contract import frame, header


class RecordingWireEncodingTests(unittest.TestCase):
    recording = semantic_fixtures.RecordingSemanticProofTests.recording
    payload = staticmethod(semantic_fixtures.RecordingSemanticProofTests.payload)
    state = staticmethod(semantic_fixtures.RecordingSemanticProofTests.state)

    @contextmanager
    def wire_work(self, index, *, extra_wires=()):
        wires = {row[0] for row in index.conn.execute("SELECT frames_json FROM recording_chunks")} | set(extra_wires)
        checked = RecordingStore._checked_frames.__code__
        validate = recording_store.validate_frames.__code__
        decode = recording_store.strict_json_loads.__code__
        real_sha256, previous = hashlib.sha256, sys.getprofile()
        work = {"encodes": [], "hashes": [], "decodes": [], "validated": []}

        def observe(current, event, arg):
            if event == "call":
                if current.f_code is validate:
                    work["validated"].append(len(current.f_locals["frames"]))
                elif (current.f_code is decode and current.f_back is not None and
                      current.f_back.f_code is checked and current.f_locals.get("value") in wires):
                    work["decodes"].append(current.f_locals["value"])
            elif event == "c_call" and (arg is real_sha256 or getattr(arg, "__name__", None) == "encode"):
                origin = current
                while origin is not None and origin.f_code is not checked:
                    origin = origin.f_back
                raw = origin.f_locals.get("raw") if origin is not None else None
                if isinstance(raw, str) and raw in wires:
                    if getattr(arg, "__name__", None) == "encode" and getattr(arg, "__self__", None) is raw:
                        work["encodes"].append(raw)
                    elif arg is real_sha256 and current.f_code is checked:
                        # The real loop hashes the current wire and its current chunk identity.
                        work["hashes"].append(raw)

        sys.setprofile(observe)
        try:
            yield work
        finally:
            sys.setprofile(previous)
        self.assertIs(sys.getprofile(), previous)

    @contextmanager
    def subclass_wire(self, index, wire, *, fail_second=False):
        calls, previous = [], index.conn.text_factory
        fault = OSError("TEST_ONLY second wire encode")

        class DelegatingWire(str):
            def encode(self, encoding="utf-8", errors="strict"):
                calls.append((encoding, errors))
                if fail_second and len(calls) == 2:
                    raise fault
                return super().encode(encoding, errors)

        def factory(data):
            value = data.decode("utf-8")
            return DelegatingWire(value) if value == wire else value

        index.conn.text_factory = factory
        try:
            yield calls, fault
        finally:
            index.conn.text_factory = previous
        self.assertIs(index.conn.text_factory, previous)

    def assert_work(self, work, wires, *, hashes_per_wire, decoded=0, validated=()):
        self.assertEqual(len(work["encodes"]), len(wires))
        self.assertEqual(len(work["hashes"]), hashes_per_wire * len(wires))
        for wire in wires:
            self.assertEqual(work["encodes"].count(wire), 1)
            self.assertEqual(work["hashes"].count(wire), hashes_per_wire)
        self.assertEqual(len(work["decodes"]), decoded)
        self.assertEqual(work["validated"], list(validated))

    def test_warm_eight_chunks_status_encodes_each_fresh_wire_once(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            expected, before = store.status(sid), self.state(index)
            wires = [row[0] for row in index.conn.execute("SELECT frames_json FROM recording_chunks")]
            for _ in range(2):
                with self.wire_work(index) as work:
                    actual = store.status(sid)
                self.assertEqual(actual, expected)
                self.assert_work(work, wires, hashes_per_wire=2)
            self.assertEqual(self.state(index), before)
            self.assertFalse(actual["physical_accuracy_verified"])
            self.assertEqual(actual["clinical_validation"], "UNVERIFIED")

    def test_append_nine_encodes_all_nine_fresh_wires_once(self):
        sid = header()["session_id"]
        with self.recording(8) as (_, index, store):
            payload, before = self.payload(129, 144), self.state(index)
            # Include the incoming wire without replacing any encoder, parser, validator or hash.
            with self.wire_work(index, extra_wires=(payload["frames_json"],)) as work:
                ack = store.append(sid, payload)
            wires = [row[0] for row in index.conn.execute("SELECT frames_json FROM recording_chunks")]
            self.assert_work(work, wires, hashes_per_wire=2, decoded=1, validated=(16, 16))
            self.assertEqual((ack["saved_through"], ack["received_through"], ack["revision"]), (144, 144, 10))
            self.assertEqual(ack["missing_ranges"], [])
            self.assertEqual(len(self.state(index)["audit_events"]), len(before["audit_events"]) + 1)
            for row in index.conn.execute("SELECT frames_json,sha256 FROM recording_chunks"):
                self.assertEqual(row[1], hashlib.sha256(row[0].encode("utf-8")).hexdigest())
            with self.wire_work(index) as work:
                self.assertEqual(store.status(sid), ack)
            self.assert_work(work, wires, hashes_per_wire=2)
            index.verify_audit()

    def test_full_materialization_encodes_once_and_fully_revalidates(self):
        sid = header()["session_id"]
        with self.recording(2) as (_, index, store):
            before = self.state(index)
            wires = [row[0] for row in index.conn.execute("SELECT frames_json FROM recording_chunks")]
            with self.wire_work(index) as work:
                actual = list(store.iter_frames(sid))
            self.assertEqual(actual, [frame(i, (i - 1) * 30) for i in range(1, 33)])
            self.assert_work(work, wires, hashes_per_wire=1, decoded=2, validated=(16, 16))
            self.assertEqual(self.state(index), before)

    def test_subclass_still_delegates_two_encodes_and_real_hashes(self):
        sid = header()["session_id"]
        with self.recording(1) as (_, index, store):
            expected, before = store.status(sid), self.state(index)
            wire = index.conn.execute("SELECT frames_json FROM recording_chunks").fetchone()[0]
            with self.subclass_wire(index, wire) as (calls, _), self.wire_work(index) as work:
                self.assertEqual(store.status(sid), expected)
            self.assertEqual(calls, [("utf-8", "strict"), ("utf-8", "strict")])
            self.assertEqual(work["encodes"], [wire, wire])
            self.assertEqual(work["hashes"], [wire, wire])
            self.assertEqual(work["decodes"], [])
            self.assertEqual(work["validated"], [])
            self.assertEqual(self.state(index), before)

    def test_subclass_second_encode_error_precedes_hash_and_is_preserved(self):
        sid = header()["session_id"]
        with self.recording(1) as (_, index, store):
            before = self.state(index)
            wire = index.conn.execute("SELECT frames_json FROM recording_chunks").fetchone()[0]
            with (
                self.subclass_wire(index, wire, fail_second=True) as (calls, fault),
                self.wire_work(index) as work,
                self.assertRaises(OSError) as caught,
            ):
                store.status(sid)
            self.assertIs(caught.exception, fault)
            self.assertEqual(calls, [("utf-8", "strict"), ("utf-8", "strict")])
            self.assertEqual(work["encodes"], [wire])
            self.assertEqual(work["hashes"], [])
            self.assertEqual(work["decodes"], [])
            self.assertEqual(work["validated"], [])
            self.assertEqual(self.state(index), before)

    def test_oversized_utf8_and_nonstr_refuse_before_hash_or_decode(self):
        sid = header()["session_id"]
        oversized = "\u00e9" * (MAX_CHUNK_BYTES // 2 + 1)
        self.assertLessEqual(len(oversized), MAX_CHUNK_BYTES)
        self.assertGreater(len(oversized.encode("utf-8")), MAX_CHUNK_BYTES)
        for value, subclass in ((oversized, False), (oversized, True), (b"[", False)):
            with self.subTest(subclass=subclass, binary=isinstance(value, bytes)), self.recording(1) as (_, index, store):
                index.conn.execute("DROP TRIGGER recording_chunk_no_update")
                index.conn.execute("UPDATE recording_chunks SET frames_json=?", (value,))
                index.conn.commit()
                before = self.state(index)
                with (
                    self.subclass_wire(index, value if subclass else "never-a-wire") as (calls, _),
                    self.wire_work(index) as work,
                    self.assertRaisesRegex(ValueError, "^RECORDING_CORRUPT: stored chunk exceeds byte bound$"),
                ):
                    store.status(sid)
                self.assertEqual(calls, [("utf-8", "strict")] if subclass else [])
                self.assertEqual(work["hashes"], [])
                self.assertEqual(work["decodes"], [])
                self.assertEqual(work["validated"], [])
                self.assertEqual(self.state(index), before)

    def test_warm_status_reads_changed_wire_and_refuses_without_publication(self):
        sid = header()["session_id"]
        with self.recording(1) as (_, index, store):
            store.status(sid)
            index.conn.execute("DROP TRIGGER recording_chunk_no_update")
            index.conn.execute("UPDATE recording_chunks SET frames_json=frames_json || ' '")
            index.conn.commit()
            before = self.state(index)
            wire = index.conn.execute("SELECT frames_json FROM recording_chunks").fetchone()[0]
            with self.wire_work(index) as work, self.assertRaisesRegex(ValueError, "^RECORDING_CORRUPT: chunk$"):
                store.status(sid)
            self.assert_work(work, [wire], hashes_per_wire=2, decoded=1, validated=(16,))
            self.assertEqual(self.state(index), before)
