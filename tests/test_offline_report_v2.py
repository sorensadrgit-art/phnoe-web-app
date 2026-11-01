"""Generated publisher fixtures; independent isolated stdlib consumer is the oracle.

Real publisher fixtures exercise the independent consumer. Existing v1
coverage remains in test_offline_report_evidence and test_offline_evidence.
Manual-positive authority is checked by an isolated byte-exact standalone copy.
"""
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

import test_report_current_context as fixtures
from backup_manager import BackupManager

TOOL = Path(__file__).resolve().parents[1] / "tools" / "verify_evidence.py"
AUDIT_FIELDS = ("event_id", "session_id", "event_type", "details_json", "timestamp_utc",
                "actor", "revision", "outcome", "previous_hash")


class OfflineReportV2Tests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        case = fixtures.ReportCurrentContextTests(
            "test_00_R1_registered_initial_publication_is_v2_with_exact_receipt_and_three_files")
        try:
            case.setUp()
            yield case
        finally:
            case.doCleanups()

    def archive(self, case, *, supersede=False):
        first, _ = case.generate_v2()
        if supersede:
            case.correct_metadata()
            context = case.context()
            case.generate_v2(expected_report_head=case.head(first),
                expected_report_context_sha256=context["report_context_sha256"])
        path = case.base / "TEST_ONLY-real-publisher.zip"
        BackupManager(case.projects, case.index).create_backup(path)
        return path, first

    def verify(self, archive, *, valid):
        before = hashlib.sha256(archive.read_bytes()).hexdigest()
        run = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-B", str(TOOL), str(archive)],
            cwd=archive.parent, capture_output=True, text=True, encoding="utf-8",
            timeout=120, check=False)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), before)
        self.assertEqual(run.stderr, "", run.stderr)
        result = json.loads(run.stdout)
        self.assertIs(result["ok"], valid, run.stdout)
        self.assertEqual(run.returncode, 0 if valid else 1, run.stdout)
        self.assertFalse(result["scope"]["physical_accuracy_verified"])
        self.assertEqual(result["scope"]["clinical_validation"], "UNVERIFIED")
        if valid:
            self.assertEqual(next(item["status"] for item in result["checks"]
                if item["id"] == "report.lineage"), "pass")
        else:
            self.assertTrue(any(item["check"] == "report.lineage"
                for item in result["failures"]), run.stdout)
        return result

    def rewrite(self, case, archive, mutate):
        """Rebuild outer digests; adversaries must reach semantic report checks."""
        with zipfile.ZipFile(archive) as zipped:
            payload = {name: zipped.read(name) for name in zipped.namelist()}
        manifest = json.loads(payload.pop("backup_manifest.json"))
        database = case.base / "TEST_ONLY-adversarial-index.db"
        database.write_bytes(payload["index.db"])
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            # This connection owns only the disposable archive-derived adversary DB.
            triggers = [(row["name"], row["sql"]) for row in connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='audit_events' ORDER BY name").fetchall()]
            for name, _ in triggers:
                connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
            try:
                mutate(payload, connection)
                # Refresh only observations in this disposable archive-derived DB.
                for table, key in (("sources", "role"), ("artifacts", "artifact_key")):
                    for row in connection.execute(f"SELECT * FROM {table}").fetchall():
                        name = f"raw/{row['role']}.mp4" if table == "sources" else row["artifact_key"]
                        raw = payload.get(f"sessions/{row['session_id']}/{name}")
                        observed = None if raw is None else hashlib.sha256(raw).hexdigest()
                        state = ("missing" if observed is None else
                                 "unchanged" if observed == row["sha256"] else "changed")
                        connection.execute(
                            f"UPDATE {table} SET observed_sha256=?,integrity_state=? "
                            f"WHERE session_id=? AND {key}=?",
                            (observed, state, row["session_id"], row[key]))
                previous = "0" * 64
                for row in connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall():
                    event = dict(row)
                    event["previous_hash"] = previous
                    checksum = fixtures.digest({key: event[key] for key in AUDIT_FIELDS})
                    connection.execute("UPDATE audit_events SET previous_hash=?,event_hash=? WHERE id=?",
                                       (previous, checksum, event["id"]))
                    previous = checksum
            finally:
                for _, sql in triggers:
                    connection.execute(sql)
                restored = [(row["name"], row["sql"]) for row in connection.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
                    "AND tbl_name='audit_events' ORDER BY name").fetchall()]
                if restored != triggers:
                    raise RuntimeError("Disposable adversary audit triggers were not restored exactly")
            connection.commit()
            manifest["generation"]["audit_tip"] = previous
        finally:
            connection.close()
        payload["index.db"] = database.read_bytes()
        manifest["files"] = [{"path": name, "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw)} for name, raw in sorted(payload.items())]
        manifest["file_count"] = len(manifest["files"])
        destination = case.base / "TEST_ONLY-self-consistent-adversary.zip"
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as zipped:
            zipped.writestr("backup_manifest.json", fixtures.canonical(manifest))
            for name, raw in payload.items():
                zipped.writestr(name, raw)
        return destination

    @staticmethod
    def forge_manifest(payload, connection, generation, change):
        relative = f"exports/{generation}/manifest.json"
        member = f"sessions/{fixtures.SID}/{relative}"
        document = json.loads(payload[member])
        change(document)
        raw = fixtures.canonical(document)
        payload[member] = raw
        checksum = hashlib.sha256(raw).hexdigest()
        connection.execute("UPDATE artifacts SET sha256=?,bytes=? WHERE session_id=? AND artifact_key=?",
            (checksum, len(raw), fixtures.SID, relative))
        for row in connection.execute("SELECT id,details_json FROM audit_events WHERE event_type='REPORT_PUBLISHED'").fetchall():
            receipt = json.loads(row["details_json"])
            if receipt["generation"] == generation:
                receipt["manifest_sha256"] = checksum
                receipt["supersedes"] = document["supersedes"]
                receipt["report_context_sha256"] = document["report_context_sha256"]
                connection.execute("UPDATE audit_events SET details_json=? WHERE id=?",
                    (fixtures.canonical(receipt).decode(), row["id"]))

    def test_00_initial_actual_v2_passes_isolated_verifier(self):
        with self.fixture() as case:
            archive, _ = self.archive(case)
            self.verify(archive, valid=True)

    def test_01_metadata_supersession_accepts_exact_audited_delta(self):
        with self.fixture() as case:
            archive, first = self.archive(case, supersede=True)
            self.assertEqual(len(list(first["json"].parent.parent.glob("*/manifest.json"))), 2)
            self.verify(archive, valid=True)

    def test_02_copied_archive_root_remains_portable(self):
        with self.fixture() as case:
            archive, _ = self.archive(case, supersede=True)
            destination = case.base / "TEST_ONLY-another-root"
            destination.mkdir()
            copied = destination / "copied.zip"
            shutil.copyfile(archive, copied)
            self.assertEqual(copied.read_bytes(), archive.read_bytes())
            self.verify(copied, valid=True)

    def test_03_valid_metadata_delta_does_not_authorize_sibling(self):
        with self.fixture() as case:
            archive, _ = self.archive(case, supersede=True)
            self.verify(archive, valid=True)
            def mutate(payload, _connection):
                payload[f"sessions/{fixtures.SID}/metadata-revisions/TEST_ONLY-unaudited.json"] = b"{}"
            self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_04_historical_artifact_remains_bound_after_supersession(self):
        for kind in ("pdf", "json", "csv", "manifest"):
            with self.subTest(kind=kind), self.fixture() as case:
                archive, first = self.archive(case, supersede=True)
                self.verify(archive, valid=True)
                target = first["json"].parent / "manifest.json" if kind == "manifest" else first[kind]
                member = "sessions/" + target.relative_to(case.projects).as_posix()
                def mutate(payload, _connection, member=member):
                    payload[member] += b"\nTEST_ONLY historical corruption"
                self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_05_wrong_predecessor_refuses_even_with_rehashed_audit_and_artifacts(self):
        with self.fixture() as case:
            archive, first = self.archive(case, supersede=True)
            self.verify(archive, valid=True)
            generation = next(path.parent.name for path in first["json"].parent.parent.glob("*/manifest.json")
                if path.parent != first["json"].parent)
            def mutate(payload, connection):
                self.forge_manifest(payload, connection, generation,
                    lambda document: document.update(supersedes=None))
            self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_06_forged_metadata_context_cannot_be_self_authorized(self):
        with self.fixture() as case:
            archive, first = self.archive(case)
            self.verify(archive, valid=True)
            def change(document):
                document["metadata_context_sha256"] = "f" * 64
                projection = {"schema": "kinelab.report-context.v1", **{key: document[key]
                    for key in ("session_id", "input_policy", "inputs", "origin_sha256", "run_sha256",
                                "metadata_context_sha256", "manual_assessment_context")}}
                document["report_context_sha256"] = fixtures.digest(projection)
            def mutate(payload, connection):
                self.forge_manifest(payload, connection, first["json"].parent.name, change)
            self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_07_omitted_publication_cannot_hide_committed_generation(self):
        with self.fixture() as case:
            archive, _ = self.archive(case, supersede=True)
            self.verify(archive, valid=True)
            def mutate(_payload, connection):
                connection.execute("DELETE FROM audit_events WHERE id=(SELECT MIN(id) FROM audit_events WHERE event_type='REPORT_PUBLISHED')")
            self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_08_reordered_publications_cannot_rewrite_predecessor_order(self):
        with self.fixture() as case:
            archive, _ = self.archive(case, supersede=True)
            self.verify(archive, valid=True)
            def mutate(_payload, connection):
                rows = connection.execute("SELECT id,details_json FROM audit_events WHERE event_type='REPORT_PUBLISHED' ORDER BY id").fetchall()
                self.assertEqual(len(rows), 2)
                connection.execute("UPDATE audit_events SET details_json=? WHERE id=?", (rows[1]["details_json"], rows[0]["id"]))
                connection.execute("UPDATE audit_events SET details_json=? WHERE id=?", (rows[0]["details_json"], rows[1]["id"]))
            self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_09_declared_extra_generation_member_refuses(self):
        with self.fixture() as case:
            archive, first = self.archive(case)
            self.verify(archive, valid=True)
            def mutate(payload, _connection):
                prefix = "sessions/" + first["json"].parent.relative_to(case.projects).as_posix()
                payload[prefix + "/TEST_ONLY-extra.txt"] = b"TEST_ONLY extra committed member"
            self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_10_missing_original_input_refuses(self):
        with self.fixture() as case:
            archive, _ = self.archive(case)
            self.verify(archive, valid=True)
            def mutate(payload, _connection):
                del payload[f"sessions/{fixtures.SID}/session-template.json"]
            self.verify(self.rewrite(case, archive, mutate), valid=False)

    def test_11_manual_v2_positive_requires_independent_validation(self):
        import test_offline_manual_report as manual_fixtures

        fixture = manual_fixtures.OfflineManualReportTests(
            "test_00_actual_gait_manual_v2_requires_semantic_acceptance")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with fixture.fixture() as (case, archive, _files, _receipts):
            standalone = case.base / "TEST_ONLY-standalone-verifier"
            standalone.mkdir()
            copied = standalone / "verify_evidence.py"
            verifier_bytes = TOOL.read_bytes()
            shutil.copyfile(TOOL, copied)
            self.assertEqual(copied.read_bytes(), verifier_bytes)
            archive_before = hashlib.sha256(archive.read_bytes()).hexdigest()
            run = subprocess.run(
                [sys.executable, "-I", "-X", "utf8", "-B", str(copied), str(archive)],
                cwd=standalone, capture_output=True, text=True, encoding="utf-8",
                timeout=120, check=False)
            self.assertEqual(run.stderr, "", run.stderr)
            self.assertEqual(run.returncode, 0, run.stdout)
            result = json.loads(run.stdout)
            self.assertIs(result["ok"], True, run.stdout)
            self.assertEqual(next(item["status"] for item in result["checks"]
                if item["id"] == "report.lineage"), "pass")
            self.assertFalse(result["scope"]["physical_accuracy_verified"])
            self.assertEqual(result["scope"]["clinical_validation"], "UNVERIFIED")
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), archive_before)
            self.assertEqual(copied.read_bytes(), verifier_bytes)
            self.assertEqual(TOOL.read_bytes(), verifier_bytes)
            case.assert_originals()
