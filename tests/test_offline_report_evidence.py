"""Independent positive proof for actual generated reports in an offline backup."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from backup_manager import BackupManager
from report_builder import ReportBuilder
from session_index import SessionIndex
from session_library import SessionLibrary


class OfflineGeneratedReportTests(unittest.TestCase):
    def test_actual_report_generation_passes_standalone_verifier(self):
        with tempfile.TemporaryDirectory(prefix="kinelab-offline-report-") as temporary:
            root = Path(temporary)
            projects = root / "generated-projects"
            projects.mkdir()
            index = SessionIndex(root / "generated-index.db", projects)
            try:
                SessionLibrary(projects).create_session("generated-report", kind="demo")
                index.reindex()
                reports = ReportBuilder(projects, index).generate_reports("generated-report")
                self.assertEqual(set(reports), {"pdf", "csv", "json"})
                archive = root / "generated-with-reports.zip"
                BackupManager(projects, index).create_backup(archive)
                before = hashlib.sha256(archive.read_bytes()).hexdigest()
                with zipfile.ZipFile(archive) as zipped:
                    for report in reports.values():
                        member = "sessions/" + report.relative_to(projects).as_posix()
                        self.assertEqual(zipped.read(member), report.read_bytes())
                tool = Path(__file__).resolve().parents[1] / "tools" / "verify_evidence.py"
                run = subprocess.run(
                    [sys.executable, "-I", "-X", "utf8", "-B", str(tool), str(archive)],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
                )
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                result = json.loads(run.stdout)
                self.assertTrue(result["ok"], result.get("failures"))
                self.assertEqual(next(c["status"] for c in result["checks"]
                                      if c["id"] == "report.lineage"), "pass")
                self.assertEqual(result["archive_sha256"], before)
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), before)
                self.assertFalse(result["scope"]["physical_accuracy_verified"])
                self.assertEqual(result["scope"]["clinical_validation"], "UNVERIFIED")
            finally:
                index.close()
