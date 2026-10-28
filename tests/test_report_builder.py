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


if __name__ == "__main__":
    unittest.main()
