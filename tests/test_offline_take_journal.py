"""Generated real take journals; standalone archive authority must be checked."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import zipfile
from contextlib import contextmanager
from unittest.mock import patch

import test_offline_manual_report as manual
import test_offline_report_v2 as portable
import test_report_current_context as reports
import test_take_acceptance_recovery as faults
from session_library import SessionLibrary
from take_acceptance import inspect_acceptance
from workflow_recovery import recover_take_acceptance


class OfflineTakeJournalTests(unittest.TestCase):
    def setUp(self):
        self.portable = portable.OfflineReportV2Tests(
            "test_00_initial_actual_v2_passes_isolated_verifier")

    @contextmanager
    def fixture(self, mode="committed", *, manual_entry=True):
        original_register = reports.register_captures

        def register(project, session_id, **kwargs):
            library = SessionLibrary(project.parent)
            for number in range(2 if mode == "reused" else 1):
                selected = project.parent.parent / f"TEST_ONLY-selected-{number}.mp4"
                selected.write_bytes(b"TEST_ONLY generated take; no patient data " + str(number).encode())
                with patch("session_library.probe_clip", return_value=faults.PROBE):
                    staged = library.stage_take(session_id, faults.ROLE, selected)
                if mode in ("previous", "selected"):
                    boundary = "after-replacement" if mode == "previous" else "after-replace"
                    checkpoint = project.parent.parent / "TEST_ONLY-acceptance-checkpoint.json"
                    child = subprocess.run(
                        [sys.executable, "-X", "utf8", "-B", "-c", faults.WORKER,
                         str(project.parent), session_id, faults.ROLE, str(staged),
                         boundary, str(checkpoint)], cwd=faults.ROOT,
                        env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
                        capture_output=True, text=True, encoding="utf-8", timeout=45, check=False)
                    self.assertEqual(child.returncode, 73, child.stdout + child.stderr)
                    self.assertEqual(json.loads(checkpoint.read_text(encoding="utf-8"))["boundary"], boundary)
                    state = inspect_acceptance(project)
                    self.assertEqual(state["state"], "recovery-required", state)
                    with patch("session_library.probe_clip", return_value=faults.PROBE):
                        result = recover_take_acceptance(project, state["transaction_id"], confirmed=True)
                    self.assertEqual(result["outcome"], "previous-preserved" if mode == "previous"
                                     else "selected-verified")
                else:
                    with patch("session_library.probe_clip", return_value=faults.PROBE):
                        library.accept_take(session_id, faults.ROLE, staged)
                self.assertEqual(inspect_acceptance(project)["state"], "clear")
            return original_register(project, session_id, **kwargs)

        with patch("test_report_current_context.register_captures", side_effect=register):
            if manual_entry:
                fixture = manual.OfflineManualReportTests(
                    "test_00_actual_gait_manual_v2_requires_semantic_acceptance")
                fixture.setUp()
                try:
                    with fixture.fixture() as (case, archive, _files, _receipts):
                        yield case, archive
                finally:
                    fixture.doCleanups()
            else:
                with self.portable.fixture() as case:
                    archive, _files = self.portable.archive(case)
                    try:
                        yield case, archive
                    finally:
                        case.assert_originals()

    def accept(self, case, archive):
        standalone = case.base / "TEST_ONLY-standalone-take-verifier"
        standalone.mkdir(exist_ok=True)
        tool = standalone / "verify_evidence.py"
        original = portable.TOOL.read_bytes()
        shutil.copyfile(portable.TOOL, tool)
        before = hashlib.sha256(archive.read_bytes()).hexdigest()
        run = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-B", str(tool), str(archive)],
            cwd=standalone, capture_output=True, text=True, encoding="utf-8",
            timeout=120, check=False)
        self.assertEqual(run.stderr, "", run.stderr)
        self.assertEqual(run.returncode, 0, run.stdout)
        result = json.loads(run.stdout)
        self.assertIs(result["ok"], True, run.stdout)
        self.assertEqual(next(row["status"] for row in result["checks"]
                              if row["id"] == "report.lineage"), "pass")
        self.assertFalse(result["scope"]["physical_accuracy_verified"])
        self.assertEqual(result["scope"]["clinical_validation"], "UNVERIFIED")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), before)
        self.assertEqual(tool.read_bytes(), original)
        self.assertEqual(portable.TOOL.read_bytes(), original)
        case.assert_originals()

    def records(self, payload):
        prefix = f"sessions/{reports.SID}/"
        intents = sorted(name for name in payload
                         if name.startswith(prefix + "takes/acceptance/") and name.endswith("/intent.json"))
        self.assertTrue(intents, "Valid control must contain real producer intent")
        intent_name = intents[0]
        directory = intent_name.rsplit("/", 1)[0] + "/"
        terminal = next(name for name in (directory + "commit.json", directory + "recovery.json")
                        if name in payload)
        return prefix, directory, intent_name, terminal, directory + "accept.lock.archived"

    @staticmethod
    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

    def rebind_intent(self, payload, intent_name, terminal_name, marker_name, record):
        payload[intent_name] = self.encode(record)
        digest = hashlib.sha256(payload[intent_name]).hexdigest()
        for name in (terminal_name, marker_name):
            value = json.loads(payload[name])
            value["intent_sha256"] = digest
            payload[name] = self.encode(value)

    def reject(self, case, archive, mutate, code):
        changed = self.portable.rewrite(case, archive, mutate)
        result = self.portable.verify(changed, valid=False)
        self.assertEqual([(row["check"], row["code"]) for row in result["failures"]],
                         [("report.lineage", code)], result)
        case.assert_originals()

    def test_00_committed_take_manual_archive_accepts(self):
        with self.fixture() as (case, archive):
            self.accept(case, archive)

    def test_01_recovered_previous_with_quarantine_manual_archive_accepts(self):
        with self.fixture("previous") as (case, archive):
            with zipfile.ZipFile(archive) as zipped:
                payload = {name: zipped.read(name) for name in zipped.namelist()}
            _prefix, _directory, intent_name, terminal_name, _marker = self.records(payload)
            intent, terminal = json.loads(payload[intent_name]), json.loads(payload[terminal_name])
            self.assertEqual(terminal["outcome"], "previous-preserved")
            self.assertEqual(len(terminal["artifacts_quarantined"]), 1)
            raw = payload[f"sessions/{reports.SID}/" + terminal["artifacts_quarantined"][0]]
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             (intent["staged_bytes"], intent["staged_sha256"]))
            self.accept(case, archive)

    def test_02_recovered_selected_manual_archive_accepts(self):
        with self.fixture("selected") as (case, archive):
            self.accept(case, archive)

    def test_03_historical_journals_allow_later_canonical_reuse(self):
        with self.fixture("reused") as (case, archive):
            with zipfile.ZipFile(archive) as zipped:
                commits = [json.loads(zipped.read(name)) for name in zipped.namelist()
                           if "/takes/acceptance/" in name and name.endswith("/commit.json")]
            self.assertEqual(len(commits), 2)
            self.assertEqual(len({item["canonical_sha256"] for item in commits}), 2)
            self.accept(case, archive)

    def test_04_nonmanual_v2_uses_same_take_fence(self):
        with self.fixture(manual_entry=False) as (case, archive):
            self.accept(case, archive)
            def mutate(payload, _connection):
                prefix, _directory, _intent, _terminal, marker = self.records(payload)
                payload[prefix + "takes/accept.lock"] = payload[marker]
            self.reject(case, archive, mutate, "REPORT_TAKE_JOURNAL_PENDING")

    def test_05_pending_and_unknown_journals_refuse(self):
        with self.fixture() as (case, archive):
            self.accept(case, archive)
            for attack, code in (("no-terminal", "REPORT_TAKE_JOURNAL_PENDING"),
                                 ("active-terminal", "REPORT_TAKE_JOURNAL_PENDING"),
                                 ("marker-no-intent", "REPORT_TAKE_JOURNAL_UNKNOWN"),
                                 ("multiple-unfinished", "REPORT_TAKE_JOURNAL_UNKNOWN")):
                with self.subTest(attack=attack):
                    def mutate(payload, _connection, attack=attack):
                        prefix, directory, intent, terminal, marker = self.records(payload)
                        payload[prefix + "takes/accept.lock"] = payload[marker]
                        if attack in ("no-terminal", "multiple-unfinished"):
                            del payload[terminal]
                            del payload[marker]
                        if attack == "marker-no-intent":
                            for name in list(payload):
                                if name.startswith(directory):
                                    del payload[name]
                        if attack == "multiple-unfinished":
                            record = json.loads(payload[intent])
                            record["transaction_id"] = "e" * 32
                            payload[prefix + "takes/acceptance/" + "e" * 32 + "/intent.json"] = self.encode(record)
                    self.reject(case, archive, mutate, code)

    def test_06_terminal_and_retired_marker_bindings_refuse(self):
        with self.fixture() as (case, archive):
            self.accept(case, archive)
            for attack, code in (("both-terminals", "REPORT_TAKE_JOURNAL_UNKNOWN"),
                                 ("intent-digest", "REPORT_TAKE_JOURNAL_IDENTITY"),
                                 ("canonical", "REPORT_TAKE_JOURNAL_IDENTITY"),
                                 ("missing-marker", "REPORT_TAKE_JOURNAL_UNKNOWN"),
                                 ("marker-transaction", "REPORT_TAKE_JOURNAL_IDENTITY"),
                                 ("marker-extra", "REPORT_TAKE_JOURNAL_UNKNOWN")):
                with self.subTest(attack=attack):
                    def mutate(payload, _connection, attack=attack):
                        _prefix, directory, _intent, terminal, marker = self.records(payload)
                        record = json.loads(payload[terminal])
                        if attack == "both-terminals":
                            record["schema"] = "kinelab.take-acceptance-recovery.v1"
                            payload[directory + "recovery.json"] = self.encode(record)
                        elif attack == "missing-marker":
                            del payload[marker]
                        elif attack.startswith("marker-"):
                            record = json.loads(payload[marker])
                            record["transaction_id" if attack == "marker-transaction" else "extra"] = "f" * 32
                            payload[marker] = self.encode(record)
                        else:
                            record["intent_sha256" if attack == "intent-digest" else "canonical_sha256"] = "0" * 64
                            payload[terminal] = self.encode(record)
                    self.reject(case, archive, mutate, code)

    def test_07_strict_record_decoding_and_typed_fields_refuse(self):
        with self.fixture() as (case, archive):
            self.accept(case, archive)
            for attack in ("bom", "duplicate", "nan", "overflow", "utf8", "truncated", "oversize",
                           "nonobject", "bool-size", "zero-size", "unsafe-name", "wrong-session", "prior-pair"):
                with self.subTest(attack=attack):
                    def mutate(payload, _connection, attack=attack):
                        _prefix, _directory, intent, terminal, marker = self.records(payload)
                        record = json.loads(payload[intent])
                        if attack in ("bool-size", "zero-size", "unsafe-name", "wrong-session", "prior-pair"):
                            key, value = {"bool-size": ("staged_bytes", True), "zero-size": ("staged_bytes", 0),
                                          "unsafe-name": ("staged_name", "../outside.mp4"),
                                          "wrong-session": ("session_id", "TEST_ONLY-other"),
                                          "prior-pair": ("prior_bytes", None)}[attack]
                            record[key] = value
                            self.rebind_intent(payload, intent, terminal, marker, record)
                        else:
                            raw = payload[intent]
                            payload[intent] = {"bom": b"\xef\xbb\xbf" + raw,
                                "duplicate": b'{"schema":"duplicate",' + raw[1:],
                                "nan": b'{"value":NaN}', "overflow": b'{"value":1e999}',
                                "utf8": b"\xff", "truncated": raw[:-1],
                                "oversize": b" " * 65537, "nonobject": b"[]"}[attack]
                    self.reject(case, archive, mutate, "REPORT_TAKE_JOURNAL_UNKNOWN")

    def test_08_quarantine_inventory_and_staged_content_refuse(self):
        with self.fixture("previous") as (case, archive):
            self.accept(case, archive)
            for attack, code in (("missing", "REPORT_TAKE_JOURNAL_IDENTITY"),
                                 ("changed", "REPORT_TAKE_JOURNAL_IDENTITY"),
                                 ("length", "REPORT_TAKE_JOURNAL_IDENTITY"),
                                 ("empty-declaration", "REPORT_TAKE_JOURNAL_UNKNOWN"),
                                 ("wrong-role", "REPORT_TAKE_JOURNAL_UNKNOWN"),
                                 ("nested", "REPORT_TAKE_JOURNAL_UNKNOWN"),
                                 ("extra", "REPORT_TAKE_JOURNAL_UNKNOWN")):
                with self.subTest(attack=attack):
                    def mutate(payload, _connection, attack=attack):
                        prefix, directory, _intent, terminal, _marker = self.records(payload)
                        record = json.loads(payload[terminal])
                        name = prefix + record["artifacts_quarantined"][0]
                        if attack == "missing":
                            del payload[name]
                        elif attack == "changed":
                            payload[name] = b"x" * len(payload[name])
                        elif attack == "length":
                            payload[name] += b"x"
                        elif attack == "empty-declaration":
                            record["artifacts_quarantined"] = []
                            payload[terminal] = self.encode(record)
                        elif attack == "wrong-role":
                            renamed = name.replace(faults.ROLE, "cam02_trial")
                            payload[renamed] = payload.pop(name)
                            record["artifacts_quarantined"] = [renamed[len(prefix):]]
                            payload[terminal] = self.encode(record)
                        elif attack == "nested":
                            payload[directory + "quarantine/nested/extra.replacement"] = b"TEST_ONLY"
                        else:
                            payload[directory + "quarantine/extra.replacement"] = b"TEST_ONLY"
                    self.reject(case, archive, mutate, code)

    def test_09_windows_case_alias_and_nested_replacement_refuse(self):
        with self.fixture() as (case, archive):
            self.accept(case, archive)
            for attack in ("takes", "acceptance", "active", "intent", "commit", "suffix", "nested", "directory"):
                with self.subTest(attack=attack):
                    def mutate(payload, _connection, attack=attack):
                        prefix, _directory, intent, terminal, marker = self.records(payload)
                        if attack in ("takes", "acceptance"):
                            old, new = ("takes/", "Takes/") if attack == "takes" else ("acceptance/", "Acceptance/")
                            for name in list(payload):
                                if name.startswith(prefix + ("takes/" if attack == "takes" else "takes/acceptance/")):
                                    payload[name.replace(old, new, 1)] = payload.pop(name)
                        elif attack == "active":
                            payload[prefix + "takes/ACCEPT.LOCK"] = payload[marker]
                        elif attack in ("intent", "commit"):
                            name = intent if attack == "intent" else terminal
                            payload[name.rsplit("/", 1)[0] + "/" + name.rsplit("/", 1)[1].upper()] = payload.pop(name)
                        else:
                            name = {"suffix": "raw/TEST_ONLY.REPLACEMENT",
                                    "nested": "raw/nested/TEST_ONLY.replacement",
                                    "directory": "raw/TEST_ONLY.replacement/child"}[attack]
                            payload[prefix + name] = b"TEST_ONLY unresolved replacement"
                    self.reject(case, archive, mutate, "REPORT_TAKE_JOURNAL_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
