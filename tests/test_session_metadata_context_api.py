"""TEST_ONLY generated B10 consumer contracts; no physical/native-run proof.

The loopback server, registration, immutable metadata publisher and source
verification are real. Only codec readiness/probing of generated clip bytes is
isolated. No draft/current metadata or raw SQL is substituted for authority.
"""

import copy
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from export_motion import motion
from native_evidence_fixture import complete_native_fixture
from session_contract import ROLES, sha256_file
from session_metadata_revision import publish_metadata_revision, read_metadata_state
from t6_server import make_server
from t6_service import IntegratedService
from test_export_motion import trc_text
from test_t6_session_metadata_api import generated_metadata


class InterruptedMetadataPublication(BaseException):
    """Leave actual durable intent at the publisher's existing fault seam."""


class SessionMetadataContextApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-B10-context-TEST_ONLY-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.projects = self.base / "projects"
        self.projects.mkdir()
        self.service = IntegratedService(projects_root=self.projects)
        self.addCleanup(self.service.close)
        probe = patch("session_index.probe_clip", return_value={
            "width": 640, "height": 480, "fps": 30, "duration": 1,
        })
        probe.start()
        self.addCleanup(probe.stop)
        dist, samples = self.base / "dist", self.base / "samples"
        dist.mkdir()
        samples.mkdir()
        (dist / "index.html").write_text("<title>TEST_ONLY generated API</title>", encoding="utf-8")
        self.server = make_server(self.service, token="a" * 50, dist=dist, samples=samples, port=0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.initial = generated_metadata()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=4)

    def request(self, method, path, body=None, *, authenticated=True):
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if authenticated:
            headers.update({"Authorization": "Bearer " + "a" * 50,
                            "Origin": f"http://127.0.0.1:{self.port}"})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        try:
            connection.request(method, path, None if body is None else json.dumps(body).encode("utf-8"), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def registered(self, sid, *, native=False):
        status, payload = self.request("POST", "/api/v1/sessions", {
            "id": sid, "kind": "real", "metadata": copy.deepcopy(self.initial),
        })
        self.assertEqual(status, 201, payload)
        root = self.projects / sid
        for role in ROLES:
            (root / "raw" / (role + ".mp4")).write_bytes(("TEST_ONLY generated " + role).encode("ascii"))
        with patch("session_library._check_readiness_locked", return_value={"ready_to_register": True, "issues": []}):
            status, payload = self.request("POST", f"/api/v1/sessions/{sid}/register", {"confirm": True})
        self.assertEqual(status, 200, payload)
        self.assertEqual(json.loads((root / "session.json").read_text(encoding="utf-8"))["metadata"], self.initial)
        if native:
            self.native_contract(root)
        self.service.index.reindex()
        state = read_metadata_state(self.service.index, sid)
        self.assertEqual(state["status"], "AVAILABLE", state)
        return root

    @staticmethod
    def native_contract(root, *, source_trc=None, downstream_trc=None, angles=(0.2, 0.8, 0.5)):
        source_trc = trc_text() if source_trc is None else source_trc
        downstream_trc = trc_text() if downstream_trc is None else downstream_trc
        times = [float(row.split("\t")[1]) for row in downstream_trc.splitlines()[5:] if row.strip()]
        mot = (f"TEST_ONLY generated\nnRows={len(times)}\nnColumns=3\ninDegrees=yes\nendheader\n"
               "time knee_angle_r pelvis_tx\n" + "".join(
                   f"{stamp} {angle} {translation}\n"
                   for stamp, angle, translation in zip(times, angles, (0.1, 0.2, 0.3))))
        manifest, _trc, mot_path = complete_native_fixture(
            root, source_trc, mot, through="kinematics", downstream_trc_text=downstream_trc)
        augmented = root / "pose-3d/fixture_filt_LSTM.trc"
        augmented.write_text(downstream_trc.replace("factory_trial", "generated_augmented").replace(
            "TEST_ONLY-timing.trc", "TEST_ONLY-augmented-timing.trc"), encoding="utf-8")
        run = json.loads(manifest.read_text(encoding="utf-8"))
        run["stages"][6]["artifacts"][0]["sha256"] = sha256_file(augmented)
        run["stages"][7]["quality"]["consumed_trc"] = copy.deepcopy(run["stages"][6]["artifacts"][0])
        manifest.write_text(json.dumps(run), encoding="utf-8")
        exported = motion(augmented, mot_path, run_manifest=manifest)
        (root / "exports").mkdir(exist_ok=True)
        (root / "exports/generated.motion.json").write_text(json.dumps(exported), encoding="utf-8")

    def publish(self, sid, *, metadata=None):
        root = self.projects / sid
        changed = copy.deepcopy(self.initial if metadata is None else metadata)
        if metadata is None:
            changed.update({"subject_id": "sub-" + "3" * 32,
                            "confirmed_at": "2026-10-29T17:00:00+00:00"})
        return publish_metadata_revision(
            self.service.index, sid, metadata=changed,
            expected_origin_sha256=hashlib.sha256((root / "session.json").read_bytes()).hexdigest(),
            expected_head_sha256=None, operation_id="b" * 32,
            reason_code="operator_correction", confirm=True,
        )

    def detail(self, sid):
        status, payload = self.request("GET", f"/api/v1/sessions/{sid}")
        self.assertEqual(status, 200, payload)
        return payload

    def row(self, sid):
        status, payload = self.request("GET", "/api/v1/sessions")
        self.assertEqual(status, 200, payload)
        return next(row for row in payload["sessions"] if row["id"] == sid)

    def comparison(self):
        status, payload = self.request("GET", "/api/v1/compare?s1=a&s2=b")
        self.assertEqual(status, 200, payload)
        return payload

    @staticmethod
    def project_bytes(root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def assert_context(self, payload, state):
        self.assertIn("metadata_state", payload, "B10 public consumer omits verified metadata state")
        self.assertEqual(payload["metadata_state"], state)
        self.assertIn("effective_metadata", payload)
        self.assertIn("metadata_context_sha256", payload)
        self.assertEqual(payload["effective_metadata"], state["metadata"])
        self.assertEqual(payload["metadata_context_sha256"], state["context_sha256"])
        if state["status"] == "UNAVAILABLE":
            self.assertTrue(state["reason"])
            self.assertIsNone(payload["effective_metadata"])
            self.assertIsNone(payload["metadata_context_sha256"])

    def test_B10_CTX_01_initial_registered_state_is_separate_from_confirmation(self):
        root = self.registered("a")
        before = self.project_bytes(root)
        detail = self.detail("a")
        confirmation = self.service.library.metadata_confirmation("a")
        self.assertEqual(detail["metadata_confirmation"], confirmation)
        self.assertEqual(confirmation["metadata"], self.initial)
        state = read_metadata_state(self.service.index, "a")
        self.assertIsNone(state["head"])
        self.assert_context(detail, state)
        self.assert_context(self.row("a"), state)
        self.assertEqual(self.project_bytes(root), before)

    def test_B10_CTX_02_published_correction_updates_list_detail_without_rebinding_origin(self):
        root = self.registered("a")
        originals = self.project_bytes(root)
        origin = (root / "session.json").read_bytes()
        initial_detail, initial_row = self.detail("a"), self.row("a")
        initial_state = read_metadata_state(self.service.index, "a")
        self.publish("a")
        state = read_metadata_state(self.service.index, "a")
        self.assertEqual(state["status"], "AVAILABLE", state)
        self.assertNotEqual(state["context_sha256"], initial_state["context_sha256"])
        self.assertEqual(state["origin"], initial_state["origin"])
        detail, row = self.detail("a"), self.row("a")
        self.assertEqual(detail["metadata_confirmation"], initial_detail["metadata_confirmation"])
        self.assertEqual(row["research_source_revision"], initial_row["research_source_revision"])
        self.assertEqual((root / "session.json").read_bytes(), origin)
        for name, raw in originals.items():
            self.assertEqual((root / name).read_bytes(), raw, name)
        self.assert_context(detail, state)
        self.assert_context(row, state)

    def test_B10_CTX_03_pending_publication_is_unavailable_and_reads_do_not_heal(self):
        root = self.registered("a")
        def interrupt(phase, *_context):
            if phase == "after_descriptor_publish":
                raise InterruptedMetadataPublication()
        with (patch("session_metadata_revision._checkpoint", side_effect=interrupt),
              self.assertRaises(InterruptedMetadataPublication)):
            self.publish("a")
        state = read_metadata_state(self.service.index, "a")
        self.assertEqual(state["status"], "UNAVAILABLE", state)
        before = self.project_bytes(root)
        audit = self.service.index.verify_audit()
        self.assert_context(self.detail("a"), state)
        self.assert_context(self.row("a"), state)
        self.assertEqual(self.project_bytes(root), before)
        self.assertEqual(self.service.index.verify_audit(), audit)

    def test_B10_CTX_04_tampered_revision_has_no_initial_or_draft_fallback(self):
        root = self.registered("a")
        receipt = self.publish("a")
        descriptor = root / receipt["descriptor"]["path"]
        document = json.loads(descriptor.read_text(encoding="utf-8"))
        document["metadata"]["protocol_id"] = "TEST_ONLY-tampered-unverified-protocol"
        descriptor.write_text(json.dumps(document), encoding="utf-8")
        state = read_metadata_state(self.service.index, "a")
        self.assertEqual(state["status"], "UNAVAILABLE", state)
        before = self.project_bytes(root)
        audit = self.service.index.verify_audit()
        detail = self.detail("a")
        self.assertEqual(detail["metadata_confirmation"]["metadata"], self.initial)
        self.assert_context(detail, state)
        self.assert_context(self.row("a"), state)
        self.assertEqual(self.project_bytes(root), before)
        self.assertEqual(self.service.index.verify_audit(), audit)

    def test_B10_CTX_05_original_native_pair_remains_compatible_with_separate_contexts(self):
        self.registered("a", native=True)
        self.registered("b", native=True)
        result = self.comparison()
        self.assertTrue(result["compatible"], result["reason"])
        self.assertEqual(result["research_measurements"]["status"], "AVAILABLE")
        for source in result["research_measurements"]["sessions"]:
            state = read_metadata_state(self.service.index, source["session_id"])
            self.assertIn("metadata_context_sha256", source, "B10 comparison source lacks separate metadata context")
            self.assertEqual(source["metadata_context_sha256"], state["context_sha256"])
            self.assertEqual(source["metadata"], state["metadata"])
            self.assertNotIn("metadata_context_sha256", source["source_revision"])

    def test_B10_CTX_06_correction_invalidates_old_compatibility_without_changing_sources(self):
        roots = [self.registered(sid, native=True) for sid in ("a", "b")]
        original_bytes = {root.name: (root / "session.json").read_bytes() for root in roots}
        before = self.comparison()
        self.assertTrue(before["compatible"], before["reason"])
        old = {source["session_id"]: source for source in before["research_measurements"]["sessions"]}
        self.publish("b")
        result = self.comparison()
        self.assertFalse(result["compatible"], "B10 corrected subject must refuse the formerly compatible selection")
        self.assertEqual(result["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(result["research_measurements"]["coordinates"], [])
        current = {source["session_id"]: source for source in result["research_measurements"]["sessions"]}
        self.assertEqual(set(current), {"a", "b"})
        for sid in ("a", "b"):
            self.assertEqual(current[sid]["source_revision"], old[sid]["source_revision"])
            self.assertIn("metadata_context_sha256", current[sid])
            self.assertEqual(current[sid]["metadata"], read_metadata_state(self.service.index, sid)["metadata"])
            self.assertEqual((self.projects / sid / "session.json").read_bytes(), original_bytes[sid])
        self.assertNotEqual(current["b"]["metadata_context_sha256"], old["b"]["metadata_context_sha256"])

    def test_B10_CTX_07_tampered_metadata_refuses_previously_compatible_comparison(self):
        self.registered("a", native=True)
        root = self.registered("b", native=True)
        self.assertTrue(self.comparison()["compatible"])
        receipt = self.publish("b", metadata=self.initial)
        (root / receipt["descriptor"]["path"]).write_bytes(b"TEST_ONLY corrupt metadata revision")
        before = self.project_bytes(root)
        result = self.comparison()
        self.assertFalse(result["compatible"], "B10 unavailable metadata must not reuse original compatibility")
        self.assertEqual(result["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(result["research_measurements"]["coordinates"], [])
        self.assertTrue(result["reason"])
        self.assertEqual(self.project_bytes(root), before)

    def test_B10_CTX_08_metadata_context_routes_remain_authenticated(self):
        self.registered("a")
        for path in ("/api/v1/sessions", "/api/v1/sessions/a", "/api/v1/compare?s1=a&s2=a"):
            with self.subTest(path=path):
                status, payload = self.request("GET", path, authenticated=False)
                self.assertEqual(status, 401, payload)
                self.assertNotIn("effective_metadata", payload)
                self.assertNotIn("metadata_context_sha256", payload)

    def test_B10_CTX_09_pending_metadata_refuses_previously_compatible_comparison(self):
        self.registered("a", native=True)
        root = self.registered("b", native=True)
        self.assertTrue(self.comparison()["compatible"])
        def interrupt(phase, *_context):
            if phase == "after_descriptor_publish":
                raise InterruptedMetadataPublication()
        with (patch("session_metadata_revision._checkpoint", side_effect=interrupt),
              self.assertRaises(InterruptedMetadataPublication)):
            self.publish("b")
        before = self.project_bytes(root)
        result = self.comparison()
        self.assertFalse(result["compatible"], "B10 pending metadata cannot reuse original compatibility")
        self.assertEqual(result["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(result["research_measurements"]["coordinates"], [])
        self.assertTrue(result["reason"])
        self.assertEqual(self.project_bytes(root), before)

    def test_B10_CTX_10_identical_metadata_revision_refuses_stale_expected_http_context_pair(self):
        roots = [self.registered(sid, native=True) for sid in ("a", "b")]
        contexts = {sid: read_metadata_state(self.service.index, sid)["context_sha256"]
                    for sid in ("a", "b")}

        def endpoint(pair):
            return ("/api/v1/compare?s1=a&s2=b"
                    f"&expected_metadata_context_s1={pair['a']}"
                    f"&expected_metadata_context_s2={pair['b']}")

        status, current = self.request("GET", endpoint(contexts))
        self.assertEqual(status, 200, current)
        self.assertTrue(current["compatible"], current["reason"])
        self.assertEqual(current["research_measurements"]["status"], "AVAILABLE")
        self.publish("b", metadata=self.initial)
        refreshed = {sid: read_metadata_state(self.service.index, sid)["context_sha256"]
                     for sid in ("a", "b")}
        self.assertEqual(refreshed["a"], contexts["a"])
        self.assertNotEqual(refreshed["b"], contexts["b"])
        self.assertEqual(read_metadata_state(self.service.index, "b")["metadata"], self.initial)
        before = {root.name: self.project_bytes(root) for root in roots}
        status, fresh = self.request("GET", endpoint(refreshed))
        self.assertEqual(status, 200, fresh)
        self.assertTrue(fresh["compatible"], fresh["reason"])
        status, stale = self.request("GET", endpoint(contexts))
        self.assertEqual(status, 200, stale)
        self.assertFalse(stale["compatible"], "B10 stale metadata context must refuse even identical effective values")
        self.assertEqual(stale["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(stale["research_measurements"]["coordinates"], [])
        self.assertRegex(stale["reason"].lower(), "metadata|context|stale")
        for root in roots:
            self.assertEqual(self.project_bytes(root), before[root.name])

    def test_B10_CTX_11_partial_malformed_duplicate_expected_http_context_pairs_refused(self):
        roots = [self.registered(sid, native=True) for sid in ("a", "b")]
        first, second = (read_metadata_state(self.service.index, sid)["context_sha256"]
                         for sid in ("a", "b"))
        key1, key2 = "expected_metadata_context_s1", "expected_metadata_context_s2"
        queries = {
            "partial_first": f"{key1}={first}",
            "partial_second": f"{key2}={second}",
            "empty_first": f"{key1}=&{key2}={second}",
            "empty_both": f"{key1}=&{key2}=",
            "short": f"{key1}={'0' * 63}&{key2}={second}",
            "uppercase": f"{key1}={'A' * 64}&{key2}={second}",
            "nonhex": f"{key1}={'g' * 64}&{key2}={second}",
            "whitespace": f"{key1}=%20{first}&{key2}={second}",
            "duplicate_first": f"{key1}={first}&{key1}={first}&{key2}={second}",
            "duplicate_second": f"{key1}={first}&{key2}={second}&{key2}={second}",
        }
        before = {root.name: self.project_bytes(root) for root in roots}
        for case, query in queries.items():
            with self.subTest(case=case):
                status, payload = self.request("GET", "/api/v1/compare?s1=a&s2=b&" + query)
                self.assertEqual(status, 409, payload)
                self.assertTrue(payload.get("error"), "B10 invalid context pair needs an explicit API error")
                self.assertNotIn("research_measurements", payload)
                for root in roots:
                    self.assertEqual(self.project_bytes(root), before[root.name])

