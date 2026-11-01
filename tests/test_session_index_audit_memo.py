"""Generated SQLite regressions for the private verify-only audit hash memo; no patient data."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import session_index
import test_recording_transaction_budget as budget_fixtures
from recording_contract import digest
from recording_store import RecordingStore
from session_index import SessionIndex
from test_recording_contract import frame, header
from tools.verify_evidence import _verify_audit_chain

FIELDS = ("event_id", "session_id", "event_type", "details_json", "timestamp_utc",
          "actor", "revision", "outcome", "previous_hash")
SCAN = "SELECT * FROM audit_events ORDER BY id"


class TextSubclass(str):
    __slots__ = ()


def independent_hash(event):
    # Restates the frozen digest contract without SessionIndex code or memo state.
    data = json.dumps({key: event[key] for key in FIELDS}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def independent_verify(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        previous = "0" * 64
        for row in conn.execute(SCAN):
            event = dict(row)
            if event["previous_hash"] != previous or event["event_hash"] != independent_hash(event):
                raise ValueError("AUDIT_INVALID: event " + str(event["id"]))
            previous = event["event_hash"]
        return previous
    finally:
        conn.close()


def tools_verify(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return _verify_audit_chain(conn)[0]
    finally:
        conn.close()


def outcome(call, *args):
    try:
        return "tip", call(*args)
    except ValueError as error:
        return "refused", str(error)


def rows(index):
    return [dict(row) for row in index.conn.execute(SCAN)]


def memo_cost(event):
    key = session_index._audit_memo_key(event)
    if key is None:
        raise AssertionError("fixture event must be memo-eligible")
    return session_index._audit_memo_cost(key)


def damage(conn, statements):
    # Generated disposable fixtures only: bypass immutability triggers, then commit for every reader.
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    for sql, params in statements:
        conn.execute(sql, params)
    conn.commit()


def rechain(conn):
    previous = "0" * 64
    for row in conn.execute(SCAN).fetchall():
        event = dict(row) | {"previous_hash": previous}
        previous = independent_hash(event)
        conn.execute("UPDATE audit_events SET previous_hash=?,event_hash=? WHERE id=?",
                     (event["previous_hash"], previous, event["id"]))
    conn.commit()


ORIGINAL_HASH_CODE = SessionIndex.__dict__["_event_hash"].__func__.__code__


def raise_mid_scan(event):
    raise RuntimeError("MID_SCAN_HASH_SENTINEL")


@contextmanager
def real_hash_calls(on_call=None):
    """Count executions of the unchanged original digest code, captured before any replacement."""
    calls, prior = [], sys.getprofile()

    def observe(current, event, arg):
        if event == "call" and current.f_code is ORIGINAL_HASH_CODE:
            audit_event = current.f_locals.get("event")
            calls.append(audit_event.get("id") if type(audit_event) is dict else None)
            if on_call is not None:
                on_call()

    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(prior)

@contextmanager
def replaced_code(function, code):
    """Swap a function's code object and restore it by assignment; mock cannot delete __code__."""
    original = function.__code__
    function.__code__ = code
    try:
        yield
    finally:
        function.__code__ = original

class AuditHashMemoTests(unittest.TestCase):
    @contextmanager
    def fixture(self, count=9):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "projects").mkdir()
            index = SessionIndex(root / "index.db", root / "projects")
            try:
                for number in range(count):
                    index.record_audit_event(f"synthetic-{number % 3}", "AUDIT_MEMO_FIXTURE",
                                             {"n": number, "note": "\u00e9 \u2028 \"q\"\n  "}, revision=number)
                index.verify_audit()
                yield index, root / "index.db"
            finally:
                index.close()

    def assert_accounting(self, index, max_entries, max_bytes):
        memo = index._audit_hash_memo
        self.assertEqual(index._audit_hash_memo_bytes, sum(cost for _, cost in memo.values()))
        self.assertIsNone(index._audit_hash_pending)
        self.assertLessEqual(len(memo), max_entries)
        self.assertLessEqual(index._audit_hash_memo_bytes, max_bytes)

    def test_warm_verify_rescans_every_row_without_recomputing_unchanged_digests(self):
        with self.fixture() as (index, path):
            tip, total = index.verify_audit(), len(rows(index))
            statements: list[str] = []
            index.conn.set_trace_callback(statements.append)
            try:
                with real_hash_calls() as calls:
                    self.assertEqual(index.verify_audit(), tip)
            finally:
                index.conn.set_trace_callback(None)
            self.assertEqual(calls, [], f"Baseline recomputes all {total} unchanged audit digests")
            self.assertEqual(statements.count(SCAN), 1)
            self.assertEqual(tip, independent_verify(path))
            self.assertEqual(tip, tools_verify(path))

    def test_recording_append_after_eight_warm_chunks_hashes_only_new_events(self):
        sid = header()["session_id"]
        payload = budget_fixtures.RecordingTransactionBudgetTests.payload
        with self.fixture(count=0) as (index, path):
            store = RecordingStore(index)
            store.create(header())
            parts = [payload(first, first + 15) for first in range(1, 145, 16)]
            for part in parts[:8]:
                store.append(sid, part)
            store.status(sid)
            before = len(rows(index))
            with real_hash_calls() as calls:
                ack = store.append(sid, parts[8])
            new = len(rows(index)) - before
            self.assertEqual(new, 1)
            self.assertEqual(calls.count(None), new, "write-side digest still runs for every new event")
            self.assertLessEqual(len(calls), 2 * new, f"Baseline recomputes all {before} historical digests per scan")
            self.assertEqual((ack["saved_through"], ack["received_through"], ack["revision"]), (144, 144, 10))
            self.assertEqual(ack["missing_ranges"], [])
            self.assertEqual(ack["header_sha256"], digest(header()))
            self.assertFalse(ack["physical_accuracy_verified"])
            self.assertEqual(ack["clinical_validation"], "UNVERIFIED")
            self.assertEqual(index.verify_audit(), independent_verify(path))
            cold = SessionIndex(path, path.parent / "projects")
            try:
                cold_store = RecordingStore(cold)
                self.assertEqual(cold_store.status(sid), ack)
                self.assertEqual(list(cold_store.iter_frames(sid)), [frame(i, (i - 1) * 30) for i in range(1, 145)])
            finally:
                cold.close()

    def test_every_hashed_field_link_and_reported_hash_mutation_refuses_after_warm(self):
        changes = {"event_id": "'x' || event_id", "session_id": "session_id || 'x'",
                   "event_type": "event_type || 'x'", "details_json": "details_json || ' '",
                   "timestamp_utc": "timestamp_utc || 'Z'", "actor": "actor || 'x'", "revision": "revision + 1",
                   "outcome": "outcome || 'x'", "previous_hash": "upper(previous_hash)",
                   "event_hash": "upper(event_hash)"}
        for column, expression in changes.items():
            for position in (1, 4, -1):
                with self.subTest(column=column, position=position), self.fixture() as (index, path):
                    target = rows(index)[position]["id"]
                    damage(index.conn, [(f"UPDATE audit_events SET {column}={expression} WHERE id=?", (target,))])
                    expected = outcome(independent_verify, path)
                    self.assertEqual(expected, ("refused", f"AUDIT_INVALID: event {target}"))
                    self.assertEqual(outcome(index.verify_audit), expected)
                    self.assertEqual(outcome(index.verify_audit), expected)
                    self.assertEqual(outcome(SessionIndex, path, path.parent / "projects"), expected)

    def test_delete_reorder_and_other_connection_damage_refuse_like_independent_verifier(self):
        cases: dict[str, Callable[[list[int]], list[tuple[str, tuple[int, ...]]]]] = {
            "delete_interior": lambda ids: [("DELETE FROM audit_events WHERE id=?", (ids[4],))],
            "reorder": lambda ids: [("UPDATE audit_events SET id=? WHERE id=?", (-1, ids[3])),
                                    ("UPDATE audit_events SET id=? WHERE id=?", (ids[3], ids[4])),
                                    ("UPDATE audit_events SET id=? WHERE id=?", (ids[4], -1))],
            "earlier_other_session": lambda ids: [
                ("UPDATE audit_events SET details_json=details_json || ' ' WHERE id=?", (ids[1],))],
        }
        for name, statements in cases.items():
            for via_other_connection in (False, True):
                with self.subTest(name=name, other=via_other_connection), self.fixture() as (index, path):
                    ids = [row["id"] for row in rows(index)]
                    if via_other_connection:
                        other = sqlite3.connect(path)
                        try:
                            damage(other, statements(ids))
                        finally:
                            other.close()
                    else:
                        damage(index.conn, statements(ids))
                    expected = outcome(independent_verify, path)
                    self.assertEqual(expected[0], "refused")
                    self.assertEqual(outcome(index.verify_audit), expected)

    def test_valid_rechained_mutation_recomputes_only_changed_rows_and_returns_new_tip(self):
        with self.fixture() as (index, path):
            old_tip, events = index.verify_audit(), rows(index)
            target = events[4]["id"]
            damage(index.conn, [("UPDATE audit_events SET details_json=? WHERE id=?",
                                 ("{\"n\":\"\u00e9\u2028 changed\"}", target))])
            rechain(index.conn)
            new_tip = independent_verify(path)
            with real_hash_calls() as calls:
                self.assertEqual(index.verify_audit(), new_tip)
            self.assertNotEqual(new_tip, old_tip)
            self.assertEqual(calls, [row["id"] for row in events[4:]])
            self.assertEqual(new_tip, tools_verify(path))

    def test_unsupported_key_types_are_never_memo_keys(self):
        base: dict[str, object] = {name: "x" for name in FIELDS}
        base["revision"] = 1
        self.assertEqual(session_index._audit_memo_key(base), tuple(base[name] for name in FIELDS))
        edge = base | {"revision": -(2 ** 63)}
        self.assertEqual(session_index._audit_memo_key(edge), tuple(edge[name] for name in FIELDS))
        for name, value in (("revision", True), ("revision", False), ("revision", 1.0), ("revision", 2 ** 63),
                            ("revision", -(2 ** 63) - 1), ("revision", "1"), ("revision", None),
                            ("actor", None), ("actor", b"x"), ("actor", TextSubclass("x")), ("details_json", 1)):
            with self.subTest(name=name, value=value):
                self.assertIsNone(session_index._audit_memo_key(base | {name: value}))
        self.assertIsNone(session_index._audit_memo_key({name: base[name] for name in FIELDS[:-1]}))

    def test_sqlite_real_revision_takes_the_uncached_original_path_every_scan(self):
        with self.fixture() as (index, path):
            target = rows(index)[4]["id"]
            damage(index.conn, [("UPDATE audit_events SET revision=? WHERE id=?", (4.5, target))])
            rechain(index.conn)
            tip = independent_verify(path)
            self.assertEqual(index.verify_audit(), tip)
            with real_hash_calls() as calls:
                self.assertEqual(index.verify_audit(), tip)
            self.assertEqual(calls, [target])

    def test_reopen_and_connection_swaps_start_cold_and_never_reuse_other_connection_facts(self):
        with self.fixture() as (index, path), self.fixture() as (other_index, other_path):
            total = len(rows(index))
            with real_hash_calls() as calls:
                reopened = SessionIndex(path, path.parent / "projects")
            reopened.close()
            self.assertEqual(len(calls), total)
            target = rows(other_index)[4]["id"]
            damage(other_index.conn, [("UPDATE audit_events SET actor=actor || 'x' WHERE id=?", (target,))])
            original = index.conn
            for replacement_path, expected in ((path, ("tip", independent_verify(path))),
                                               (other_path, ("refused", f"AUDIT_INVALID: event {target}"))):
                replacement = sqlite3.connect(replacement_path, check_same_thread=False)
                replacement.row_factory = sqlite3.Row
                index.conn = replacement
                try:
                    with real_hash_calls() as calls:
                        self.assertEqual(outcome(index.verify_audit), expected)
                    if expected[0] == "tip":
                        self.assertEqual(len(calls), total, "a new connection starts cold")
                    else:
                        self.assertEqual(calls, [row["id"] for row in rows(other_index) if row["id"] <= target])
                finally:
                    index.conn = original
                    replacement.close()
            with real_hash_calls() as calls:
                self.assertEqual(index.verify_audit(), independent_verify(path))
            self.assertEqual(len(calls), total, "rebinding to the original connection is cold")

    def test_close_releases_memo_and_connection_reference(self):
        with self.fixture() as (index, _):
            self.assertTrue(index._audit_hash_memo)
            index.close()
            self.assertEqual((index._audit_hash_memo, index._audit_hash_memo_conn, index._audit_hash_memo_bytes),
                             ({}, None, 0))

    def test_changed_hash_json_or_sha_profile_bypasses_clears_and_preserves_errors(self):
        self.assertIsNotNone(session_index._AUDIT_HASH_PROFILE, "memo is enabled only for the native JSON encoder")
        with self.fixture() as (index, _):
            tip, total = index.verify_audit(), len(rows(index))
            with patch.object(index, "_event_hash", side_effect=RuntimeError("SENTINEL")), \
                    self.assertRaisesRegex(RuntimeError, "SENTINEL"):
                index.verify_audit()
            self.assertEqual(index._audit_hash_memo, {})
            index.verify_audit()
            with patch.object(SessionIndex, "_event_hash", new=staticmethod(raise_mid_scan)), \
                    self.assertRaisesRegex(RuntimeError, "MID_SCAN_HASH_SENTINEL"):
                index.verify_audit()
            self.assertEqual(index._audit_hash_memo, {})
            real_sha, real_iterencode = hashlib.sha256, json.JSONEncoder.iterencode
            real_hash = SessionIndex.__dict__["_event_hash"].__func__
            make_iterencode = vars(json.encoder)["_make_iterencode"]
            make_iterencode_code = make_iterencode.__code__
            changes = {
                "sha256": patch.object(session_index.hashlib, "sha256", new=lambda data=b"": real_sha(data)),
                "iterencode": patch.object(json.JSONEncoder, "iterencode",
                                           new=lambda self, o, _one_shot=False: real_iterencode(self, o, _one_shot)),
                "dumps_kwdefaults": patch.dict(json.dumps.__kwdefaults__ or {}, {"skipkeys": True}),
                "class_hash_delegate": patch.object(SessionIndex, "_event_hash",
                                                    new=staticmethod(lambda e: real_hash(e))),
                "make_iterencode_code": replaced_code(make_iterencode, (lambda: None).__code__),
                "unsupported_backend": patch.object(session_index, "_AUDIT_HASH_PROFILE", None),
            }
            for name, change in changes.items():
                with self.subTest(name=name):
                    index.verify_audit()
                    self.assertTrue(index._audit_hash_memo)
                    with change, real_hash_calls() as calls:
                        self.assertEqual(index.verify_audit(), tip)
                        self.assertEqual(index._audit_hash_memo, {})
                    self.assertEqual(len(calls), total)
                    with real_hash_calls() as calls:
                        self.assertEqual(index.verify_audit(), tip)
                    self.assertEqual(len(calls), total, "restored profile starts cold")
            self.assertIs(make_iterencode.__code__, make_iterencode_code, "stdlib encoder code restored exactly")

    def test_fifo_entry_and_byte_budgets_keep_newest_facts_and_verdicts(self):
        with self.fixture(count=6) as (index, path):
            events, tip = rows(index), independent_verify(path)
            with patch.object(session_index, "_AUDIT_MEMO_MAX_ENTRIES", 3):
                self.assertEqual(index.verify_audit(), tip)
                self.assertEqual([key[0] for key in index._audit_hash_memo], [e["event_id"] for e in events[-3:]])
                self.assert_accounting(index, 3, session_index._AUDIT_MEMO_MAX_BYTES)
            budget = memo_cost(events[-1]) + memo_cost(events[-2])
            with patch.object(session_index, "_AUDIT_MEMO_MAX_BYTES", budget):
                self.assertEqual(index.verify_audit(), tip)
                self.assertEqual([key[0] for key in index._audit_hash_memo], [e["event_id"] for e in events[-2:]])
                self.assert_accounting(index, session_index._AUDIT_MEMO_MAX_ENTRIES, budget)
                target = events[-1]["id"]
                damage(index.conn, [("UPDATE audit_events SET outcome=outcome || 'x' WHERE id=?", (target,))])
                expected = outcome(independent_verify, path)
                self.assertEqual(outcome(index.verify_audit), expected)
                self.assertEqual(expected, ("refused", f"AUDIT_INVALID: event {target}"))

    def test_oversized_key_is_verified_but_never_retained(self):
        with self.fixture() as (index, path):
            target = rows(index)[4]["id"]
            big = json.dumps({"blob": "x" * session_index._AUDIT_MEMO_MAX_ENTRY_BYTES})
            damage(index.conn, [("UPDATE audit_events SET details_json=? WHERE id=?", (big, target))])
            rechain(index.conn)
            tip = independent_verify(path)
            self.assertEqual(index.verify_audit(), tip)
            self.assertNotIn(big, [key[3] for key in index._audit_hash_memo])
            self.assert_accounting(index, session_index._AUDIT_MEMO_MAX_ENTRIES, session_index._AUDIT_MEMO_MAX_BYTES)
            with real_hash_calls() as calls:
                self.assertEqual(index.verify_audit(), tip)
            self.assertEqual(calls, [target])

    def test_failed_cold_scan_publishes_no_facts(self):
        with self.fixture() as (index, path):
            target = rows(index)[-1]["id"]
            damage(index.conn, [("UPDATE audit_events SET event_hash=upper(event_hash) WHERE id=?", (target,))])
            replacement = sqlite3.connect(path, check_same_thread=False)
            replacement.row_factory = sqlite3.Row
            original, index.conn = index.conn, replacement
            try:
                self.assertEqual(outcome(index.verify_audit), ("refused", f"AUDIT_INVALID: event {target}"))
                self.assertEqual((index._audit_hash_memo, index._audit_hash_memo_bytes), ({}, 0))
            finally:
                index.conn = original
                replacement.close()

    def test_rollback_after_warm_never_returns_uncommitted_tip(self):
        with self.fixture() as (index, path):
            committed_tip = index.verify_audit()
            pending_tip = None
            with self.assertRaisesRegex(RuntimeError, "ROLLBACK_FIXTURE"), index.transaction():
                index._append_audit("synthetic-rollback", "AUDIT_MEMO_FIXTURE", {"pending": True})
                pending_tip = index.verify_audit()
                raise RuntimeError("ROLLBACK_FIXTURE")
            self.assertNotEqual(pending_tip, committed_tip)
            self.assertEqual(index.verify_audit(), committed_tip)
            self.assertEqual(independent_verify(path), committed_tip)
            index.record_audit_event("synthetic-rollback", "AUDIT_MEMO_FIXTURE", {"pending": True})
            self.assertEqual(index.verify_audit(), independent_verify(path))
            self.assertEqual(index.verify_audit(), tools_verify(path))


    def assert_rechain_bound(self, attribute, limit_for, fail):
        with self.fixture(count=6) as (index, path), \
                patch.object(session_index, attribute, limit_for(rows(index))):
            max_entries, max_bytes = session_index._AUDIT_MEMO_MAX_ENTRIES, session_index._AUDIT_MEMO_MAX_BYTES
            index.verify_audit()
            warm = set(index._audit_hash_memo)
            self.assertTrue(warm)
            damage(index.conn, [("UPDATE audit_events SET details_json=details_json || ' ' WHERE id=?",
                                 (rows(index)[0]["id"],))])
            rechain(index.conn)
            if fail:
                damage(index.conn, [("UPDATE audit_events SET event_hash=upper(event_hash) WHERE id=?",
                                     (rows(index)[-1]["id"],))])
            samples, published = [], []

            def sample():
                pending = getattr(index, "_audit_hash_pending", None) or ()
                samples.append((len(index._audit_hash_memo) + len(pending),
                                index._audit_hash_memo_bytes + getattr(index, "_audit_hash_pending_bytes", 0)))

            publish = index._publish_audit_memo

            def observe_publication(memo, pending):
                # Charged from the actual arguments, so any implementation of the pending store is measured.
                published.append((len(memo) + len(pending),
                                  sum(cost for _, cost in memo.values()) + sum(fact[2] for fact in pending)))

            def forward(conn, memo, limits, pending):
                observe_publication(memo, pending)
                result = publish(conn, memo, limits, pending)
                observe_publication(memo, pending)
                return result

            with patch.object(index, "_publish_audit_memo", new=forward), real_hash_calls(sample) as calls:
                result = outcome(index.verify_audit)
            self.assertEqual(result, outcome(independent_verify, path))
            self.assertEqual(len(calls), len(rows(index)), "every rechained row is a fresh miss")
            self.assertLessEqual(max(entries for entries, _ in samples), max_entries)
            self.assertLessEqual(max(charged for _, charged in samples), max_bytes)
            if fail:
                self.assertEqual(published, [], "an invalid scan never reaches publication")
            else:
                self.assertEqual(len(published), 2, "publication observed before and after")
                self.assertLessEqual(max(entries for entries, _ in published), max_entries)
                self.assertLessEqual(max(charged for _, charged in published), max_bytes)
            self.assertIsNone(index._audit_hash_pending)
            if fail:
                self.assertLessEqual(set(index._audit_hash_memo), warm, "a failed scan publishes no new fact")
            else:
                keys = [tuple(row[name] for name in FIELDS) for row in rows(index)]
                self.assertTrue(index._audit_hash_memo)
                self.assertEqual(list(index._audit_hash_memo), keys[-len(index._audit_hash_memo):])
            self.assert_accounting(index, max_entries, max_bytes)

    def test_full_rechain_keeps_retained_plus_pending_within_one_aggregate_budget(self):
        def three_entries(events):
            return 3

        def three_keys_of_bytes(events):
            return 3 * max(memo_cost(event) for event in events)

        for attribute, limit_for in (("_AUDIT_MEMO_MAX_ENTRIES", three_entries),
                                     ("_AUDIT_MEMO_MAX_BYTES", three_keys_of_bytes)):
            for fail in (False, True):
                with self.subTest(attribute=attribute, fail=fail):
                    self.assert_rechain_bound(attribute, limit_for, fail)

    def assert_trace_change_replays(self, apply, restore, error, message, prepare=None):
        with self.fixture() as (index, path):
            if prepare is not None:
                prepare(index)
            armed = [True]

            def change(statement):
                if statement == SCAN and armed:
                    armed.clear()
                    apply(index)

            index.conn.set_trace_callback(change)
            try:
                with self.assertRaisesRegex(error, message):
                    index.verify_audit()
            finally:
                index.conn.set_trace_callback(None)
                restore(index)
            self.assertEqual(armed, [])
            self.assertEqual(index._audit_hash_memo, {})
            self.assertIsNone(index._audit_hash_pending)
            with real_hash_calls() as calls:
                self.assertEqual(outcome(index.verify_audit), outcome(independent_verify, path))
            self.assertEqual(len(calls), len(rows(index)), "restored profile starts cold")

    def test_sqlite_trace_dependency_change_after_opening_check_replays_uncached_once(self):
        real_sha = hashlib.sha256
        changed_sha = patch.object(session_index.hashlib, "sha256", new=lambda data=b"": real_sha(data + b"!"))

        def raising_instance(index):
            vars(index)["_event_hash"] = raise_mid_scan

        def restore_instance(index):
            vars(index).pop("_event_hash", None)

        def start_sha(index):
            changed_sha.start()

        def stop_sha(index):
            changed_sha.stop()

        def change_middle_row(index):
            target = rows(index)[4]["id"]
            damage(index.conn, [("UPDATE audit_events SET details_json=details_json || ' ' WHERE id=?", (target,))])
            rechain(index.conn)

        with self.subTest(path="all_warm_raising_instance"):
            self.assert_trace_change_replays(raising_instance, restore_instance, RuntimeError,
                                             "^MID_SCAN_HASH_SENTINEL$")
        with self.subTest(path="all_warm_changed_sha"):
            self.assert_trace_change_replays(start_sha, stop_sha, ValueError, "^AUDIT_INVALID: event 1$")
        with self.subTest(path="mixed_hits_then_miss_changed_sha"):
            self.assert_trace_change_replays(start_sha, stop_sha, ValueError, "^AUDIT_INVALID: event 1$",
                                             prepare=change_middle_row)
        with self.subTest(path="mixed_hits_then_miss_raising_instance"):
            self.assert_trace_change_replays(raising_instance, restore_instance, RuntimeError,
                                             "^MID_SCAN_HASH_SENTINEL$", prepare=change_middle_row)

if __name__ == "__main__":
    unittest.main()
