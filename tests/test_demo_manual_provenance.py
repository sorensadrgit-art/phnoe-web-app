"""PROPOSED generated-only provenance regressions; no physical observations."""
import copy
import csv
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_offline_report_v2 as portable
from backup_manager import BackupManager
from manual_assessment_entry import manual_assessment_context, publish_manual_assessment_entry
from report_builder import ReportBuilder
from session_contract import load_session, sha256_file
from session_metadata_revision import publish_metadata_revision, read_metadata_state
from t6_service import IntegratedService
from tools import verify_report_browser as reports


class DemoManualProvenanceTests(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(prefix="TEST_ONLY-demo-manual-provenance-")
        self.addCleanup(owned.cleanup)
        self.base = Path(owned.name)
        self.projects = self.base / "TEST_ONLY-projects"
        self.projects.mkdir()
        self.service = IntegratedService(projects_root=self.projects)
        self.addCleanup(self.service.close)
        self.fixture = reports.prepare_fixture(self.service)
        self.index = self.service.index
        self.folder = self.projects / reports.SID

    @staticmethod
    def tree(folder):
        return {path.relative_to(folder).as_posix():
                (path.stat().st_dev, path.stat().st_ino,
                 hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
                for path in folder.rglob("*")}

    def request(self, context, operation="5" * 32):
        item = next(item for item in context["input_sets"] if item["kind"] == "gait")
        return {"operation_id": operation, "context_sha256": context["context_sha256"],
                "metadata_context_sha256": context["metadata_context_sha256"],
                "input_id": item["input_id"], "source_sha256": item["source_sha256"],
                "reviewer": "TEST_ONLY automation; no human reviewer",
                "annotation_origin": "human_observed_video_frames",
                "labels": [{"frame_index": 50, "side": "left", "event_type": "initial_contact"}],
                "tolerance_frames": 3, "confirm": True}

    def publish(self):
        context = manual_assessment_context(self.index, reports.SID)
        return publish_manual_assessment_entry(self.index, reports.SID, self.request(context))

    def test_00_generated_report_is_persistently_demo_and_never_measured(self):
        # Baseline reaches the real publisher before the classification business RED.
        receipt = self.publish()
        files = ReportBuilder(self.projects, self.index).generate_reports(reports.SID)
        summary = json.loads(files["json"].read_bytes())
        self.assertIs(summary["is_test_only"], True)
        self.assertEqual(load_session(self.folder)["kind"], "demo")
        self.assertEqual(summary["passport"]["kind"], "demo")
        self.assertIs(summary["passport"]["is_test_only"], True)
        self.assertIs(summary["physical_accuracy_verified"], False)
        self.assertIs(summary["clinical_accuracy_verified"], False)
        self.assertEqual(summary["measurement_count"], 0)
        with files["csv"].open(encoding="utf-8-sig", newline="") as stream:
            exported = next(csv.DictReader(stream))
        self.assertEqual(exported["kind"], "demo")
        self.assertEqual(exported["is_test_only"], "True")
        self.assertIs(receipt["test_only"], True)
        self.assertIs(receipt["clinical_accuracy_validated"], False)
        provenance = self.folder / "generated-fixture-provenance.json"
        declaration = json.loads(provenance.read_bytes())
        self.assertEqual(declaration["human_observation"], "NOT_PERFORMED")
        self.assertEqual(declaration["native_compute"], "NOT_PERFORMED")
        self.assertIs(declaration["source_video_decoded"], False)
        manifest = json.loads((files["json"].parent / "manifest.json").read_bytes())
        self.assertEqual(manifest["schema"], "kinelab.report-generation.v2")
        self.assertEqual(manifest["inputs"][provenance.name], {
            "sha256": sha256_file(provenance), "bytes": provenance.stat().st_size})
        for name, digest in self.fixture["originals_sha256"].items():
            self.assertEqual(sha256_file(self.folder / name), digest, name)

    def test_demo_still_enforces_current_metadata_cas_without_new_reference(self):
        context = manual_assessment_context(self.index, reports.SID)
        request = self.request(context)
        state = read_metadata_state(self.index, reports.SID)
        changed = dict(state["metadata"], operator_id="op-" + "4" * 32)
        publish_metadata_revision(self.index, reports.SID, metadata=changed,
            expected_origin_sha256=state["origin"]["sha256"],
            expected_head_sha256=state["head"]["sha256"], operation_id="b" * 32,
            reason_code="operator_correction", confirm=True)
        before, audit = self.tree(self.folder), self.index.verify_audit()
        with self.assertRaisesRegex(ValueError, "CONTEXT_CHANGED"):
            publish_manual_assessment_entry(self.index, reports.SID, request)
        self.assertEqual(self.tree(self.folder), before)
        self.assertEqual(self.index.verify_audit(), audit)
        self.assertFalse((self.folder / "assessment-entries").exists())

    def test_malformed_or_rebound_generated_declaration_is_not_healed(self):
        context = manual_assessment_context(self.index, reports.SID)
        request = self.request(context)
        path = self.folder / "generated-fixture-provenance.json"
        original = path.read_bytes()
        declaration = json.loads(original)
        attacks = []
        for key, value in (("human_observation", "PERFORMED"), ("test_only", 1),
                           ("kind", "real"), ("source_video_decoded", True)):
            altered = copy.deepcopy(declaration)
            altered[key] = value
            attacks.append((key, altered))
        altered = copy.deepcopy(declaration)
        altered["producers_sha256"]["tools/verify_report_browser.py"] = "f" * 64
        attacks.append(("valid-looking different producer digest", altered))
        altered = copy.deepcopy(declaration)
        altered["captures_sha256"]["cam01_trial"] = "f" * 64
        attacks.append(("different source binding", altered))
        altered = copy.deepcopy(declaration)
        altered["undeclared"] = True
        attacks.append(("extra field", altered))
        for label, altered in attacks:
            with self.subTest(label=label):
                path.write_text(json.dumps(altered, sort_keys=True, separators=(",", ":")), encoding="utf-8")
                before, audit = self.tree(self.folder), self.index.verify_audit()
                with self.assertRaises(ValueError):
                    manual_assessment_context(self.index, reports.SID)
                with self.assertRaises(ValueError):
                    publish_manual_assessment_entry(self.index, reports.SID, request)
                self.assertEqual(self.tree(self.folder), before)
                self.assertEqual(self.index.verify_audit(), audit)
                path.write_bytes(original)

        # Missing and same-byte linked declarations must fail before new evidence.
        for label in ("missing declaration", "same-byte symlink declaration"):
            with self.subTest(label=label):
                retained = self.base / "TEST_ONLY-retained-declaration.json"
                self.assertFalse(retained.exists())
                path.rename(retained)
                try:
                    if label == "same-byte symlink declaration":
                        try:
                            os.symlink(retained, path)
                        except (PermissionError, NotImplementedError) as error:
                            self.skipTest(f"owned symlink unavailable: {error}")
                        link_identity = (path.lstat().st_dev, path.lstat().st_ino)
                    before, audit = self.tree(self.folder), self.index.verify_audit()
                    with self.assertRaises(ValueError):
                        manual_assessment_context(self.index, reports.SID)
                    with self.assertRaises(ValueError):
                        publish_manual_assessment_entry(self.index, reports.SID, request)
                    self.assertEqual(self.tree(self.folder), before)
                    self.assertEqual(self.index.verify_audit(), audit)
                    self.assertEqual(retained.read_bytes(), original)
                    if path.is_symlink():
                        self.assertEqual((path.lstat().st_dev, path.lstat().st_ino), link_identity)
                finally:
                    if path.is_symlink():
                        path.unlink()
                    if not path.exists():
                        retained.rename(path)

        # Produce a new fully bound fixture with valid JSON plus trailing whitespace.
        # Only its fixture serializer is doubled; application guards remain real.
        with self.subTest(label="bound declaration exceeds 16 KiB"):
            projects = self.base / "TEST_ONLY-oversized-projects"
            projects.mkdir()
            service = IntegratedService(projects_root=projects)
            self.addCleanup(service.close)
            serializer = json.dumps

            def oversized_declaration(value, *args, **kwargs):
                encoded = serializer(value, *args, **kwargs)
                if (isinstance(value, dict)
                        and value.get("schema") == "kinelab.generated-assessment-fixture.v1"):
                    return encoded + " " * 16385
                return encoded

            with patch.object(reports.json, "dumps", side_effect=oversized_declaration):
                reports.prepare_fixture(service)
            folder = projects / reports.SID
            oversized = folder / "generated-fixture-provenance.json"
            self.assertGreater(oversized.stat().st_size, 16384)
            self.assertEqual(json.loads(oversized.read_bytes())["schema"],
                             "kinelab.generated-assessment-fixture.v1")
            self.assertIn("# kinelab-generated-provenance-sha256=" + sha256_file(oversized),
                          (folder / "Config.toml").read_text(encoding="utf-8").splitlines())
            self.assertEqual(read_metadata_state(service.index, reports.SID)["status"], "AVAILABLE")
            before, audit = self.tree(folder), service.index.verify_audit()
            with self.assertRaises(ValueError):
                manual_assessment_context(service.index, reports.SID)
            self.assertEqual(self.tree(folder), before)
            self.assertEqual(service.index.verify_audit(), audit)

    def test_exact_replay_still_checks_bound_generated_declaration(self):
        context = manual_assessment_context(self.index, reports.SID)
        request = self.request(context)
        receipt = publish_manual_assessment_entry(self.index, reports.SID, request)
        self.assertEqual(publish_manual_assessment_entry(self.index, reports.SID, request), receipt)
        path = self.folder / "generated-fixture-provenance.json"
        declaration = json.loads(path.read_bytes())
        declaration["producers_sha256"]["tools/verify_report_browser.py"] = "e" * 64
        path.write_text(json.dumps(declaration, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        before, audit = self.tree(self.folder), self.index.verify_audit()
        with self.assertRaises(ValueError):
            publish_manual_assessment_entry(self.index, reports.SID, request)
        with self.assertRaises(ValueError):
            ReportBuilder(self.projects, self.index).generate_reports(reports.SID)
        self.assertEqual(self.tree(self.folder), before)
        self.assertEqual(self.index.verify_audit(), audit)

    def test_backup_and_isolated_verifier_retain_generated_demo_designation(self):
        self.publish()
        files = ReportBuilder(self.projects, self.index).generate_reports(reports.SID)
        archive = self.base / "TEST_ONLY-generated-demo-report.zip"
        BackupManager(self.projects, self.index).create_backup(archive)
        checker = portable.OfflineReportV2Tests("test_00_initial_actual_v2_passes_isolated_verifier")
        checker.verify(archive, valid=True)
        prefix = f"sessions/{reports.SID}/"
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(json.loads(zipped.read(prefix + "session.json"))["kind"], "demo")
            declaration = json.loads(zipped.read(prefix + "generated-fixture-provenance.json"))
            self.assertIs(declaration["test_only"], True)
            self.assertEqual(declaration["human_observation"], "NOT_PERFORMED")
            summary = json.loads(zipped.read(prefix + files["json"].relative_to(self.folder).as_posix()))
            self.assertIs(summary["is_test_only"], True)
            self.assertIs(summary["physical_accuracy_verified"], False)
            exported = next(csv.DictReader(zipped.read(
                prefix + files["csv"].relative_to(self.folder).as_posix()).decode("utf-8-sig").splitlines()))
            self.assertEqual(exported["kind"], "demo")
            self.assertEqual(exported["is_test_only"], "True")
        def mutate(payload, _connection):
            member = prefix + "generated-fixture-provenance.json"
            value = json.loads(payload[member])
            value["human_observation"] = "PERFORMED"
            payload[member] = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        forged = checker.rewrite(self, archive, mutate)
        checker.verify(forged, valid=False)
