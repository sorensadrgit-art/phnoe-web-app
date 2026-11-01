"""Proposed report context/CAS HTTP contract on owned generated TEST_ONLY roots.

Uses existing registration/native/report fixtures and the actual loopback server.
No future module is imported; absent GET and ignored POST CAS are business RED.
Source preparation only: execution requires the root's separate heavy grant.
"""
import copy
import http.client
import json
import threading
import unittest

import report_generation
import test_report_current_context as report_fixture
from session_contract import sha256_file
from session_metadata_revision import read_metadata_state
from t6_server import make_server
from t6_service import IntegratedService

SID = report_fixture.SID
TOKEN = "TEST_ONLY_report_context_" + "a" * 50
SCHEMA = "kinelab.report-generation-context.v1"
STATE_FIELDS = {"schema", "session_id", "status", "report_context_sha256", "head", "reason"}


class ReportContextApiTests(unittest.TestCase):
    # Reuse existing generated fixture construction, without inheriting or
    # rediscovering its six tests. Its codec-only probe patch remains active.
    write = staticmethod(report_fixture.ReportCurrentContextTests.write)
    tree = staticmethod(report_fixture.ReportCurrentContextTests.tree)
    head = report_fixture.ReportCurrentContextTests.head
    correct_metadata = report_fixture.ReportCurrentContextTests.correct_metadata
    assert_originals = report_fixture.ReportCurrentContextTests.assert_originals

    def setUp(self):
        report_fixture.ReportCurrentContextTests.setUp(self)
        # The service owns its real generated index/report publisher. The fixture
        # index stays untouched and is closed by its already registered cleanup.
        self.service = IntegratedService(projects_root=self.projects)
        self.addCleanup(self.service.close)
        self.index = self.service.index
        self.builder = self.service.report_builder
        self.index.reindex()
        self.assertEqual(read_metadata_state(self.index, SID)["status"], "AVAILABLE")
        dist = self.base / "TEST_ONLY-http-dist"
        dist.mkdir()
        (dist / "index.html").write_text("<title>TEST_ONLY</title>", encoding="utf-8")
        samples = dist / "TEST_ONLY-samples"
        samples.mkdir()
        self.server = make_server(self.service, token=TOKEN, dist=dist, samples=samples, port=0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=4)

    def request(self, method, action, body=None, *, session_id=SID, authenticated=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if authenticated:
            headers.update(Authorization="Bearer " + TOKEN, Origin=f"http://127.0.0.1:{self.port}")
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, allow_nan=False).encode("utf-8")
        try:
            connection.request(method, f"/api/v1/sessions/{session_id}/{action}", payload, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def frozen(self):
        return self.tree(self.folder), [tuple(row) for row in self.index.conn.execute(
            "SELECT * FROM audit_events ORDER BY id")]

    def assert_unchanged(self, frozen):
        self.assertEqual(self.frozen(), frozen, "refusal/context GET must preserve every path, byte and audit row")
        self.assert_originals()

    def context(self):
        before = self.frozen()
        status, value = self.request("GET", "report-context")
        self.assertEqual(status, 200, ("REPORT_CONTEXT_HTTP_MISSING business RED", value))
        self.assertEqual(set(value), STATE_FIELDS)
        self.assertEqual((value["schema"], value["session_id"], value["status"]), (SCHEMA, SID, "AVAILABLE"))
        self.assertRegex(value["report_context_sha256"], r"^[0-9a-f]{64}$")
        self.assertIsNone(value["reason"])
        observed = report_generation.current_report_context(self.index, SID)
        self.assertEqual(value["report_context_sha256"], observed["report_context_sha256"])
        self.assert_unchanged(before)
        return value

    def cas(self, head=None):
        context = report_generation.current_report_context(self.index, SID)
        return {"confirm": True, "expected_report_head": head,
                "expected_report_context_sha256": context["report_context_sha256"]}

    def first(self):
        # Existing first-publication path is deliberately preserved.
        status, result = self.request("POST", "reports/generate", {"confirm": True})
        self.assertEqual(status, 201, result)
        history = list((self.folder / "exports").glob("report-*/manifest.json"))
        self.assertEqual(len(history), 1)
        document = json.loads(history[0].read_bytes())
        self.assertEqual(document["schema"], "kinelab.report-generation.v2")
        return history[0], {"generation": history[0].parent.name, "manifest_sha256": sha256_file(history[0])}

    def refuse(self, body, expected_status=400):
        before = self.frozen()
        status, result = self.request("POST", "reports/generate", body)
        self.assertEqual(status, expected_status, ("strict report CAS refusal required", result))
        self.assert_unchanged(before)
        return result

    def test_00_context_GET_is_available_exact_bound_and_has_no_write_or_anchor_effect(self):
        self.assertIsNone(self.context()["head"])

    def test_01_metadata_HTTP_correction_and_report_HTTP_supersession_preserve_history(self):
        old_manifest, old_head = self.first()
        old_tree = self.tree(old_manifest.parent)
        initial = self.context()
        self.assertEqual(initial["head"], old_head)
        state = read_metadata_state(self.index, SID)
        changed = copy.deepcopy(state["metadata"])
        changed.update(laterality="left", confirmed_at="2026-10-29T16:01:00+00:00")
        status, result = self.request("POST", "metadata-revisions", {
            "metadata": changed, "expected_origin_sha256": state["origin"]["sha256"],
            "expected_head_sha256": None if state["head"] is None else state["head"]["sha256"],
            "operation_id": "7" * 32, "reason_code": "operator_correction", "confirm": True})
        self.assertEqual(status, 200, result)
        current = self.context()
        self.assertEqual(current["head"], old_head)
        self.assertNotEqual(current["report_context_sha256"], initial["report_context_sha256"])
        status, result = self.request("POST", "reports/generate", {
            "confirm": True, "expected_report_head": current["head"],
            "expected_report_context_sha256": current["report_context_sha256"]})
        self.assertEqual(status, 201, result)
        self.assertEqual(self.tree(old_manifest.parent), old_tree)
        manifests = list((self.folder / "exports").glob("report-*/manifest.json"))
        self.assertEqual(len(manifests), 2)
        new_manifest = next(path for path in manifests if path != old_manifest)
        self.assertEqual(json.loads(new_manifest.read_bytes())["supersedes"], old_head)
        self.assertEqual(self.context()["head"], {
            "generation": new_manifest.parent.name, "manifest_sha256": sha256_file(new_manifest)})
        self.assert_originals()

    def test_02_wrong_initial_context_CAS_is_not_ignored_and_creates_nothing(self):
        body = self.cas()
        body["expected_report_context_sha256"] = "0" * 64
        self.refuse(body, expected_status=409)

    def test_03_wrong_initial_head_CAS_is_not_ignored_and_creates_nothing(self):
        body = self.cas()
        body["expected_report_head"] = {"generation": "report-" + "8" * 32, "manifest_sha256": "8" * 64}
        self.refuse(body, expected_status=409)

    def test_04_unknown_generation_body_field_is_rejected_before_any_publication(self):
        body = self.cas()
        body["invented_context"] = "TEST_ONLY must not be ignored"
        self.refuse(body)

    def test_05_existing_registered_history_requires_both_CAS_fields_without_writes(self):
        _, head = self.first()
        self.correct_metadata()
        current = self.cas(head)
        for body in ({"confirm": True}, {"confirm": True, "expected_report_head": head},
                     {"confirm": True, "expected_report_context_sha256": current["expected_report_context_sha256"]}):
            with self.subTest(body=body):
                self.refuse(body, expected_status=409 if set(body) == {"confirm"} else 400)

    def test_06_actual_core_verified_current_CAS_reaches_HTTP_publisher(self):
        # Independent of the absent GET: a valid CAS POST currently fails because
        # the handler/service discard both already-supported publisher arguments.
        old_manifest, head = self.first()
        old_tree = self.tree(old_manifest.parent)
        self.correct_metadata()
        status, result = self.request("POST", "reports/generate", self.cas(head))
        self.assertEqual(status, 201, ("HTTP must forward exact verified head and context", result))
        self.assertEqual(self.tree(old_manifest.parent), old_tree)
        self.assertEqual(len(list((self.folder / "exports").glob("report-*/manifest.json"))), 2)
        self.assert_originals()

    def test_07_malformed_head_and_context_types_are_refused_without_writes(self):
        # Fresh initial state ensures ignored malformed data would publish and
        # trigger a business assertion, rather than an unrelated history guard.
        body = self.cas()
        body["expected_report_head"] = "TEST_ONLY invalid head type"
        body["expected_report_context_sha256"] = 42
        self.refuse(body)

    def test_08_tampered_old_generation_makes_context_unavailable_without_new_evidence(self):
        manifest, _ = self.first()
        pdf = next(manifest.parent.glob("*.pdf"))
        pdf.write_bytes(pdf.read_bytes() + b"TEST_ONLY deliberate tamper")
        before = self.frozen()
        status, value = self.request("GET", "report-context")
        self.assertEqual(status, 200, value)
        self.assertEqual(set(value), STATE_FIELDS)
        self.assertEqual((value["schema"], value["session_id"], value["status"]), (SCHEMA, SID, "UNAVAILABLE"))
        self.assertIsNone(value["report_context_sha256"])
        self.assertIsNone(value["head"])
        self.assertTrue(value["reason"].startswith("REPORT_"))
        self.assert_unchanged(before)

    def test_09_report_context_and_generation_retain_token_gate(self):
        before = self.frozen()
        for method, action, body in (("GET", "report-context", None), ("POST", "reports/generate", {"confirm": True})):
            with self.subTest(method=method):
                status, _ = self.request(method, action, body, authenticated=False)
                self.assertEqual(status, 401)
        self.assert_unchanged(before)

    def test_10_legacy_demo_first_report_remains_compatible_without_CAS(self):
        folder = self.service.library.create_session("TEST_ONLY-legacy-report", kind="demo")
        self.index.reindex()
        status, value = self.request("POST", "reports/generate", {"confirm": True}, session_id=folder.name)
        self.assertEqual(status, 201, value)
        self.assertEqual(len(list((folder / "exports").glob("report-*/manifest.json"))), 1)

    def test_11_stale_context_and_wrong_head_on_changed_history_create_nothing(self):
        _, head = self.first()
        old_context = report_generation.current_report_context(self.index, SID)["report_context_sha256"]
        self.correct_metadata()
        current = self.cas(head)
        stale = dict(current, expected_report_context_sha256=old_context)
        wrong_head = dict(current, expected_report_head={
            "generation": "report-" + "9" * 32, "manifest_sha256": "9" * 64})
        for body in (stale, wrong_head):
            with self.subTest(body=body):
                self.refuse(body, expected_status=409)


if __name__ == "__main__":
    unittest.main()
