"""Generated-only actual CLI publication contracts; no native/device or clinical proof."""
import contextlib
import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import export_motion as exporter
from native_evidence_fixture import complete_native_fixture
from session_contract import ROLES
from session_index import SCHEMA_VERSION, SessionIndex
from session_metadata_revision import read_metadata_state
from setup_project import register_captures
from test_export_motion import trc_text
from test_session_metadata import confirmed_metadata

PROJECT = Path(__file__).resolve().parents[1]
PRIVATE = "TEST_ONLY_PRIVATE_FILENAME_TOKEN_DO_NOT_RETURN"


class CliMotionExportAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name) / "generated-library"
        self.project = self.data_root / "generated-cli"
        (self.project / "raw").mkdir(parents=True)
        (self.project / "Config.toml").write_text("[project]\n", encoding="utf-8")
        for role in ROLES:
            (self.project / "raw" / (role + ".mp4")).write_bytes(
                ("TEST_ONLY generated " + role).encode())
        register_captures(self.project, self.project.name, metadata=confirmed_metadata())
        self.manifest, self.trc, _ = complete_native_fixture(
            self.project, trc_text(), through="filtering")
        self.database = self.data_root / ".kinelab_index.db"
        with patch("session_index.probe_clip", return_value={
                "width": 640, "height": 480, "fps": 30, "duration": 1}):
            index = SessionIndex(self.database, self.data_root)
            try:
                index.reindex()
                self.initial = read_metadata_state(index, self.project.name)
                self.assertEqual(self.initial["status"], "AVAILABLE", self.initial)
            finally:
                index.close()
        self.out = self.project / "exports" / "generated-cli.motion.json"
        self.inputs = {path: path.read_bytes() for path in self.project.rglob("*")
                       if path.is_file() and not path.name.startswith(".")}

    def argv(self, *, explicit=True):
        args = ["export_motion.py", "--project", str(self.project),
                "--trc", str(self.trc), "--no-mot",
                "--run-manifest", str(self.manifest), "--out", str(self.out)]
        if explicit:
            args.extend(("--data-root", str(self.data_root)))
        return args

    def invoke(self, *, explicit=True):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = 0
        with patch.object(sys, "argv", self.argv(explicit=explicit)), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                exporter.main()
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def events(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
            return [(kind, json.loads(details), outcome) for kind, details, outcome in
                    connection.execute(
                        "SELECT event_type,details_json,outcome FROM audit_events "
                        "WHERE session_id=? AND event_type IN (?,?) ORDER BY id",
                        (self.project.name, "motion_export_started", "motion_export_published"))]

    def unchanged(self):
        for path, raw in self.inputs.items():
            with self.subTest(input=path.relative_to(self.project).as_posix()):
                self.assertEqual(path.read_bytes(), raw)

    def test_01_actual_native_v2_subprocess_records_bound_intent_and_publication(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(PROJECT / "export_motion.py"),
             *self.argv(explicit=False)[1:]], capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EXPORT_OK", result.stdout)
        raw = self.out.read_bytes()
        self.assertEqual(json.loads(raw)["schema"], "kinelab.motion.v2")
        events = self.events()
        self.assertEqual([event[0] for event in events],
                         ["motion_export_started", "motion_export_published"])
        self.assertNotIn(str(self.data_root), result.stdout + result.stderr)
        self.assertIn("EXPORT_OK=", result.stdout)
        self.assertEqual([event[2] for event in events], ["started", "published"])
        for _, details, _ in events:
            self.assertEqual(details["schema"], "kinelab.motion-export-audit.v1")
            self.assertEqual(details["session_id"], self.project.name)
            self.assertEqual(details["origin"], self.initial["origin"])
            self.assertEqual(details["metadata_context_sha256"], self.initial["context_sha256"])
            self.assertEqual(details["native_provenance"], json.loads(raw)["provenance"])
            self.assertEqual(details["output"], {
                "path": self.out.relative_to(self.project).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            self.assertEqual(details["operator_authentication"], "UNVERIFIED")
        self.assertEqual(events[0][1]["operation_id"], events[1][1]["operation_id"])
        self.assertRegex(events[0][1]["operation_id"], r"^[0-9a-f]{32}$")
        self.assertRegex(events[1][1]["started_event_id"], r"^[0-9a-f]{32}$")
        self.unchanged()

    def test_02_native_v2_missing_existing_index_refuses_without_creating_one(self):
        self.database.unlink()
        status, stdout, stderr = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.database.exists())
        self.assertIn("EXPORT_INDEX_REQUIRED:", stderr)
        self.assertNotIn(str(self.data_root), stderr)
        self.unchanged()

    def test_03_valid_json_origin_mutation_does_not_replace_indexed_baseline(self):
        changed = json.loads((self.project / "session.json").read_text(encoding="utf-8"))
        changed["metadata"]["protocol_version"] = "2"
        raw = json.dumps(changed).encode()
        (self.project / "session.json").write_bytes(raw)
        status, stdout, stderr = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertIn("EXPORT_CONTEXT_UNAVAILABLE:", stderr)
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertFalse(self.out.exists())
        self.assertEqual((self.project / "session.json").read_bytes(), raw)
        self.assertEqual(self.events(), [])
        with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
            baseline = connection.execute(
                "SELECT sha256 FROM artifacts WHERE session_id=? AND artifact_key=?",
                (self.project.name, "session.json")).fetchone()
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline[0], self.initial["origin"]["sha256"])

    def test_04_intent_failure_prevents_file_and_redacts_exception(self):
        with patch.object(SessionIndex, "_append_audit",
                          side_effect=sqlite3.OperationalError(PRIVATE)):
            status, stdout, stderr = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertFalse(self.out.exists())
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertNotIn(PRIVATE, stdout + stderr)
        self.assertEqual(self.events(), [])
        self.unchanged()

    def test_05_publication_audit_failure_retains_intent_and_output_without_success(self):
        append = SessionIndex._append_audit
        def fail_publication(index, sid, kind, details, **context):
            if kind == "motion_export_published":
                raise sqlite3.OperationalError(PRIVATE)
            return append(index, sid, kind, details, **context)
        with patch.object(SessionIndex, "_append_audit", fail_publication):
            status, stdout, stderr = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertTrue(self.out.is_file())
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertNotIn(PRIVATE, stdout + stderr)
        self.assertEqual([event[0] for event in self.events()], ["motion_export_started"])
        retained = self.out.read_bytes()
        retry_status, retry_stdout, _ = self.invoke(explicit=False)
        self.assertNotEqual(retry_status, 0)
        self.assertNotIn("EXPORT_OK", retry_stdout)
        self.assertEqual(self.out.read_bytes(), retained)
        self.assertEqual(len(self.events()), 1)
        self.unchanged()

    def test_06_existing_destination_preserved_without_new_audit(self):
        self.out.parent.mkdir()
        self.out.write_bytes(b"TEST_ONLY prior destination")
        status, stdout, _ = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertEqual(self.out.read_bytes(), b"TEST_ONLY prior destination")
        self.assertEqual(self.events(), [])
        self.unchanged()

    def test_07_existing_workflow_argv_uses_only_immediate_parent_index(self):
        status, stdout, stderr = self.invoke(explicit=False)
        self.assertEqual(status, 0, stderr)
        self.assertIn("EXPORT_OK", stdout)
        self.assertEqual([event[0] for event in self.events()],
                         ["motion_export_started", "motion_export_published"])
        self.assertFalse((self.project / ".kinelab_index.db").exists())
        self.unchanged()

    def test_08_exploratory_v1_cli_remains_unbound_without_index(self):
        self.database.unlink()
        output = Path(self.temporary.name) / "exploratory.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["export_motion.py", "--project", str(self.project), "--trc", str(self.trc), "--no-mot", "--out", str(output)]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exporter.main()
        data = json.loads(output.read_bytes())
        self.assertEqual(data["schema"], "kinelab.motion.v1")
        self.assertIn("Exploratory only; not clinically validated", data["notes"])
        self.assertFalse(self.database.exists())
        self.unchanged()

    def test_09_changed_origin_during_publication_retains_intent_and_refuses_success(self):
        write = exporter.write_motion
        changed = None
        def change_origin(out, data):
            nonlocal changed
            write(out, data)
            document = json.loads((self.project / "session.json").read_bytes())
            document["metadata"]["protocol_version"] = "2"
            changed = json.dumps(document).encode()
            (self.project / "session.json").write_bytes(changed)
        with patch.object(exporter, "write_motion", change_origin):
            status, stdout, stderr = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertNotIn(str(self.data_root), stderr)
        self.assertTrue(self.out.is_file())
        self.assertEqual((self.project / "session.json").read_bytes(), changed)
        self.assertEqual([event[0] for event in self.events()], ["motion_export_started"])

    def test_10_publication_link_race_preserves_prior_bytes_and_intent(self):
        def destination_race(_source, destination):
            Path(destination).write_bytes(b"TEST_ONLY race winner")
            raise FileExistsError(PRIVATE)
        with patch.object(exporter.os, "link", destination_race):
            status, stdout, stderr = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertNotIn(PRIVATE, stdout + stderr)
        self.assertEqual(self.out.read_bytes(), b"TEST_ONLY race winner")
        self.assertEqual([event[0] for event in self.events()], ["motion_export_started"])
        self.unchanged()


    def test_11_unclosed_intent_cannot_be_bypassed_with_different_output(self):
        append = SessionIndex._append_audit
        def fail_publication(index, sid, kind, details, **context):
            if kind == "motion_export_published":
                raise sqlite3.OperationalError(PRIVATE)
            return append(index, sid, kind, details, **context)
        with patch.object(SessionIndex, "_append_audit", fail_publication):
            first_status, first_stdout, _ = self.invoke(explicit=False)
        self.assertNotEqual(first_status, 0)
        self.assertNotIn("EXPORT_OK", first_stdout)
        original = self.out
        retained = original.read_bytes()
        self.out = self.out.with_name("different.motion.json")
        status, stdout, _ = self.invoke(explicit=False)
        self.assertNotEqual(status, 0)
        self.assertNotIn("EXPORT_OK", stdout)
        self.assertFalse(self.out.exists())
        self.assertEqual(original.read_bytes(), retained)
        self.assertEqual([event[0] for event in self.events()], ["motion_export_started"])
        self.unchanged()



    def test_12_explicit_local_root_native_v2_subprocess_is_audited(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(PROJECT / "export_motion.py"),
             *self.argv()[1:]], capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EXPORT_OK=1", result.stdout)
        self.assertNotIn(str(self.data_root), result.stdout + result.stderr)
        self.assertEqual(json.loads(self.out.read_bytes())["schema"], "kinelab.motion.v2")
        self.assertEqual([row[0] for row in self.events()],
                         ["motion_export_started", "motion_export_published"])
        self.unchanged()

    def test_13_existing_only_missing_database_never_creates_files(self):
        self.database.unlink()
        before = {p.relative_to(self.data_root): p.read_bytes()
                  for p in self.data_root.rglob("*") if p.is_file()}
        with self.assertRaises(sqlite3.Error):
            SessionIndex(self.database, self.data_root, existing_only=True)
        self.assertFalse(self.database.exists())
        after = {p.relative_to(self.data_root): p.read_bytes()
                 for p in self.data_root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.unchanged()

    def test_14_existing_only_old_and_future_schemas_are_not_migrated(self):
        original = self.database.read_bytes()
        for version in (SCHEMA_VERSION - 1, SCHEMA_VERSION + 1):
            with self.subTest(version=version):
                database = self.data_root / ("schema-" + str(version) + ".db")
                database.write_bytes(original)
                with contextlib.closing(sqlite3.connect(database)) as connection, connection:
                    connection.execute("DELETE FROM schema_migrations")
                    connection.execute("INSERT INTO schema_migrations VALUES (?,?)",
                                       (version, "2026-10-30T00:00:00+00:00"))
                before = {p.name: p.read_bytes() for p in self.data_root.glob(database.name + "*")
                          if p.is_file()}
                with self.assertRaisesRegex(ValueError, "^SCHEMA_UNSUPPORTED:"):
                    SessionIndex(database, self.data_root, existing_only=True)
                after = {p.name: p.read_bytes() for p in self.data_root.glob(database.name + "*")
                         if p.is_file()}
                self.assertEqual(after, before)
        self.assertEqual(self.database.read_bytes(), original)
        self.unchanged()

    def test_15_existing_only_corrupt_audit_refuses_without_side_effect(self):
        index = SessionIndex(self.database, self.data_root)
        try:
            index.record_audit_event(self.project.name, "TEST_ONLY_constructor_control",
                                     {"test_only": True})
        finally:
            index.close()
        with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("DROP TRIGGER audit_no_update")
            connection.execute("UPDATE audit_events SET details_json=? WHERE id=(SELECT MIN(id) FROM audit_events)",
                               ('{"TEST_ONLY":"tampered"}',))
        before = {p.name: p.read_bytes() for p in self.data_root.glob(self.database.name + "*")
                  if p.is_file()}
        with self.assertRaisesRegex(ValueError, "^AUDIT_INVALID:"):
            SessionIndex(self.database, self.data_root, existing_only=True)
        after = {p.name: p.read_bytes() for p in self.data_root.glob(self.database.name + "*")
                 if p.is_file()}
        self.assertEqual(after, before)
        self.unchanged()

    def test_16_closed_validation_codes_retain_precise_safe_causes(self):
        for code in ("TRC_INVALID", "MOT_INVALID", "ARTIFACT_MISMATCH", "MOTION_INVALID"):
            with self.subTest(code=code):
                with patch.object(exporter, "motion", side_effect=ValueError(code + ": " + PRIVATE)):
                    status, stdout, stderr = self.invoke(explicit=False)
                self.assertNotEqual(status, 0)
                self.assertIn(code + ":", stderr)
                self.assertNotIn(PRIVATE, stdout + stderr)
                self.assertNotIn(str(self.data_root), stdout + stderr)
                self.assertNotIn("EXPORT_OK", stdout)
                self.assertFalse(self.out.exists())
                self.assertEqual(self.events(), [])
        self.unchanged()

    def test_17_unknown_private_errors_and_prefix_extensions_are_redacted(self):
        for error, expected in (
                (ValueError(PRIVATE), "EXPORT_REFUSED:"),
                (ValueError("TRC_INVALID_PRIVATE: " + PRIVATE), "EXPORT_REFUSED:"),
                (OSError("TRC_INVALID: " + PRIVATE), "EXPORT_IO_UNAVAILABLE:"),
                (sqlite3.OperationalError(PRIVATE), "EXPORT_AUDIT_UNAVAILABLE:"),
                (ImportError(PRIVATE), "EXPORT_RUNTIME_UNAVAILABLE:")):
            with self.subTest(error_type=type(error).__name__, expected=expected):
                with patch.object(exporter, "motion", side_effect=error):
                    status, stdout, stderr = self.invoke(explicit=False)
                self.assertNotEqual(status, 0)
                self.assertIn(expected, stderr)
                self.assertNotIn(PRIVATE, stdout + stderr)
                self.assertNotIn(str(self.data_root), stdout + stderr)
                self.assertNotIn("EXPORT_OK", stdout)
                self.assertFalse(self.out.exists())
                self.assertEqual(self.events(), [])
        self.unchanged()

if __name__ == "__main__":
    unittest.main()
