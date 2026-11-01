"""PROPOSED generated HTTP/bootstrap regression; fake browser is not browser proof."""
import http.client
import json
import unittest
from unittest.mock import patch

import test_browser_isolation_frontend as frontend_fixtures
from tools import verify_browser_isolation as harness
from tools import verify_report_browser as reports


class ReportBrowserRegisteredTests(unittest.TestCase):
    def test_registered_reports_fixture_has_current_metadata_and_both_manual_inputs_over_real_http(self):
        fixture = frontend_fixtures.BrowserIsolationFrontendTests(
            "test_explicit_staged_build_is_served_and_receipt_hashes_exact_bytes")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        observed = {}
        def server(*args, **kwargs):
            observed["token"] = kwargs["token"]
            return fixture.server(*args, **kwargs)
        def prepare(service):
            producer = getattr(reports, "prepare_fixture", None)
            self.assertTrue(callable(producer), "Registered/manual current-v2 browser fixture is missing")
            return producer(service)
        def scenario(browser, evaluate, wait_for, service, output, checks, reopen):
            sid = "TEST_ONLY-browser-manual-reports"
            connection = http.client.HTTPConnection("127.0.0.1", int(fixture.origin.rsplit(":", 1)[1]), timeout=5)
            try:
                connection.request("GET", f"/api/v1/sessions/{sid}/manual-assessment-context",
                                   headers={"Authorization": "Bearer " + observed["token"]})
                response = connection.getresponse()
                body = json.loads(response.read())
            finally:
                connection.close()
            self.assertEqual(response.status, 200, body)
            self.assertEqual(body["status"], "AVAILABLE")
            self.assertEqual(body["session_id"], sid)
            self.assertEqual({item["kind"] for item in body["input_sets"]}, {"gait", "squat"})
            self.assertIs(body["test_only"], True)
            self.assertIs(body["clinical_accuracy_validated"], False)
            self.assertEqual(body["assessments"], [])
            from session_metadata_revision import read_metadata_state
            metadata = read_metadata_state(service.index, sid)
            self.assertIsNotNone(metadata["head"])
            self.assertEqual(body["metadata_context_sha256"], metadata["context_sha256"])
            fixture.assert_fresh_served()
            checks["real_authenticated_registered_context"] = True
        with (patch.object(harness, "ROOT", fixture.root),
              patch.object(harness.shutil, "which", return_value="TEST_ONLY-agent-browser"),
              patch.object(harness.subprocess, "run", side_effect=fixture.browser),
              patch.object(harness, "make_server", side_effect=server)):
            try:
                harness.verify(fixture.output, scenario, frontend_dist=fixture.build, fixture=prepare)
            except TypeError as error:
                if "unexpected keyword argument 'fixture'" in str(error):
                    self.fail("Existing reports harness cannot prepare the registered fixture before HTTP startup: " + str(error))
                raise
        receipt = json.loads((fixture.output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["fixture_context"]["session_id"], "TEST_ONLY-browser-manual-reports")
        self.assertEqual(receipt["fixture_context"]["human_observation"], "NOT_PERFORMED")
        self.assertTrue(receipt["checks"]["real_authenticated_registered_context"])
        self.assertEqual(fixture.served, [fixture.build])
