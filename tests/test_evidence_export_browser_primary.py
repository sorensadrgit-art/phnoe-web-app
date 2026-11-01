"""Generated callback-only regression; no real browser, HTTP, project or device."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import verify_evidence_export_browser as harness


class EvidenceExportBrowserPrimaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="TEST_ONLY-r08-primary-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "TEST_ONLY-output"
        self.output.mkdir()
        self.primary = RuntimeError("TEST_ONLY scenario readiness failure")
        self.teardown = RuntimeError("TEST_ONLY transport teardown failure")
        self.evidence_io = OSError("TEST_ONLY cleanup evidence write failure")
        self.diagnostics = LookupError("TEST_ONLY diagnostics failure")

    def invoke(self, *, fail_teardown, fail_record, fail_diagnostics=False, fail_diagnostic_record=False):
        cleanup_calls = []
        record_attempts = []
        original_write_text = Path.write_text
        original_open = Path.open
        checks = {}

        def browser(*_args):
            return True

        def evaluate(expression):
            if "window.fetch=s.original;" in expression:
                cleanup_calls.append(True)
                if fail_teardown:
                    raise self.teardown
                return True
            if "panel_present:" in expression:
                if fail_diagnostics:
                    raise self.diagnostics
                return {"panel_present": True, "generated": True}
            return True

        def wait_for(expression):
            if "Download verified export" in expression:
                raise self.primary
            return True

        def write_text(path, data, *args, **kwargs):
            if path == self.output / "transport-cleanup-failure.json":
                record_attempts.append(True)
                if fail_record:
                    raise self.evidence_io
            return original_write_text(path, data, *args, **kwargs)

        def open_file(path, *args, **kwargs):
            if fail_diagnostic_record and path == self.output / "scenario-diagnostics-failure.json":
                raise self.evidence_io
            return original_open(path, *args, **kwargs)

        caught = None
        with patch.object(Path, "write_text", new=write_text), patch.object(Path, "open", new=open_file):
            try:
                harness.run_checks(
                    browser, evaluate, wait_for,
                    SimpleNamespace(projects_root=self.root / "TEST_ONLY-projects"),
                    self.output, checks, None,
                )
            except RuntimeError as error:
                caught = error
        self.assertEqual(checks, {}, "No mounted acceptance case reached completion")
        self.assertEqual(cleanup_calls, [True], "Actual helper teardown must execute once")
        return caught, record_attempts

    def test_scenario_error_survives_teardown_and_evidence_io_failure(self):
        caught, record_attempts = self.invoke(fail_teardown=True, fail_record=True)
        self.assertEqual(record_attempts, [True])
        self.assertIs(caught, self.primary)
        self.assertFalse((self.output / "transport-cleanup-failure.json").exists())

    def test_scenario_error_survives_successful_cleanup(self):
        caught, record_attempts = self.invoke(fail_teardown=False, fail_record=False)
        self.assertIs(caught, self.primary)
        self.assertEqual(record_attempts, [])
        self.assertFalse((self.output / "transport-cleanup-failure.json").exists())

    def test_teardown_fault_record_does_not_replace_scenario_error(self):
        caught, record_attempts = self.invoke(fail_teardown=True, fail_record=False)
        self.assertIs(caught, self.primary)
        self.assertEqual(record_attempts, [True])
        recorded = json.loads((self.output / "transport-cleanup-failure.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded, {
            "status": "FAIL", "type": "RuntimeError", "primary_preserved": True,
        })


    def test_cleanup_and_evidence_failures_remain_visible_on_primary(self):
        caught, record_attempts = self.invoke(fail_teardown=True, fail_record=True)
        self.assertIs(caught, self.primary)
        self.assertEqual(record_attempts, [True])
        self.assertEqual(getattr(caught, "__notes__", []), [
            "Transport cleanup failed: RuntimeError",
            "Transport cleanup evidence write failed: OSError",
        ])

    def test_diagnostics_and_record_failure_preserve_primary_and_cleanup(self):
        caught, record_attempts = self.invoke(
            fail_teardown=False, fail_record=False,
            fail_diagnostics=True, fail_diagnostic_record=True,
        )
        self.assertIs(caught, self.primary)
        self.assertEqual(record_attempts, [])
        self.assertEqual(getattr(caught, "__notes__", []), [
            "Scenario diagnostics failed: LookupError",
            "Scenario diagnostics evidence write failed: OSError",
        ])

    def test_diagnostics_failure_stays_visible_when_record_succeeds(self):
        caught, record_attempts = self.invoke(
            fail_teardown=False, fail_record=False, fail_diagnostics=True,
        )
        self.assertIs(caught, self.primary)
        self.assertEqual(record_attempts, [])
        self.assertEqual(getattr(caught, "__notes__", []), ["Scenario diagnostics failed: LookupError"])
        recorded = json.loads((self.output / "scenario-diagnostics-failure.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded, {"status": "FAIL", "type": "LookupError", "primary_preserved": True})


if __name__ == "__main__":
    unittest.main()
