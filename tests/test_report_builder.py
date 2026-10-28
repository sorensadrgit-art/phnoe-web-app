"""Tests for truthful offline research PDF, CSV, and JSON report generation."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from report_builder import ReportBuilder
from session_index import SessionIndex
from session_library import SessionLibrary


class ReportBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.db_path = self.root / "index.db"
        self.index = SessionIndex(self.db_path, self.projects)
        self.library = SessionLibrary(self.projects)
        self.builder = ReportBuilder(self.projects, self.index)

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def test_generate_reports_for_draft_session(self):
        s_folder = self.library.create_session("report-draft", kind="real")
        self.index.reindex()

        artifacts = self.builder.generate_reports("report-draft")
        self.assertTrue(artifacts["pdf"].is_file())
        self.assertTrue(artifacts["json"].is_file())
        self.assertTrue(artifacts["csv"].is_file())

        # Check JSON content
        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        self.assertEqual(doc["session_id"], "report-draft")
        self.assertFalse(doc["clinical_accuracy_verified"])
        self.assertIn("internal research software only", doc["limitations"].lower())

        # Check CSV content
        csv_text = artifacts["csv"].read_text(encoding="utf-8")
        self.assertIn("session_id", csv_text)
        self.assertIn("report-draft", csv_text)

        # Check PDF file size > 0 and header
        pdf_bytes = artifacts["pdf"].read_bytes()
        self.assertTrue(len(pdf_bytes) > 500)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_test_only_session_receives_test_only_watermark(self):
        s_folder = self.library.create_session("report-demo", kind="demo")
        self.index.reindex()

        artifacts = self.builder.generate_reports("report-demo")
        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        self.assertTrue(doc["is_test_only"])
        self.assertEqual(doc["watermark"], "TEST ONLY - NOT PHYSICAL VALIDATION")

    def test_generate_reports_for_live_session(self):
        s_folder = self.projects / "live-report-01"
        s_folder.mkdir(parents=True)
        (s_folder / "Config.toml").write_text("# KineLab Live Session\n", encoding="utf-8")
        session_meta = {
            "schema": "kinelab.live-session.v1",
            "id": "live-report-01",
            "kind": "live",
            "status": "completed",
            "exercise_type": "squats",
            "patient_id": "PT-REPORT-001",
            "total_reps": 3,
            "valid_reps": 2,
            "summary": {
                "totalReps": 3,
                "validReps": 2,
                "averageDepth": 82.5,
                "targetDepth": 80,
                "averageSymmetry": 88.0,
                "durationSeconds": 20,
                "faultsLog": [{"fault": "KNEE_VALGUS", "count": 1, "percentage": 33}],
            },
        }
        (s_folder / "session.json").write_text(json.dumps(session_meta), encoding="utf-8")
        telemetry = {
            "exercise_type": "squats",
            "patient_id": "PT-REPORT-001",
            "reps": [
                {"repNumber": 1, "durationMs": 1400, "peakDepth": 85.0, "targetDepth": 80, "minSymmetry": 90.0, "valid": True, "faults": []},
                {"repNumber": 2, "durationMs": 1300, "peakDepth": 75.0, "targetDepth": 80, "minSymmetry": 80.0, "valid": False, "faults": ["KNEE_VALGUS"]},
                {"repNumber": 3, "durationMs": 1500, "peakDepth": 87.5, "targetDepth": 80, "minSymmetry": 94.0, "valid": True, "faults": []},
            ],
            "summary_metrics": session_meta["summary"],
        }
        (s_folder / "live_telemetry.json").write_text(json.dumps(telemetry), encoding="utf-8")
        self.index.reindex()

        artifacts = self.builder.generate_reports("live-report-01")
        self.assertTrue(artifacts["pdf"].is_file())
        self.assertTrue(artifacts["json"].is_file())
        self.assertTrue(artifacts["csv"].is_file())

        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], "kinelab.live-biofeedback-report.v1")
        self.assertEqual(doc["session_id"], "live-report-01")
        self.assertEqual(doc["kind"], "live")
        self.assertEqual(doc["exercise_type"], "squats")
        self.assertEqual(doc["total_reps"], 3)
        self.assertEqual(doc["valid_reps"], 2)
        self.assertFalse(doc["clinical_accuracy_verified"])

        csv_text = artifacts["csv"].read_text(encoding="utf-8")
        self.assertIn("rep_number,duration_ms,peak_depth_deg", csv_text)
        self.assertIn("KNEE_VALGUS", csv_text)

        pdf_bytes = artifacts["pdf"].read_bytes()
        self.assertTrue(len(pdf_bytes) > 500)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
