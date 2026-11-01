"""TEST_ONLY public registration lifecycle; no camera/video/clinical proof."""
from __future__ import annotations

import http.client
import json
import unittest
from unittest.mock import patch

import test_t6_session_metadata_api as api_fixture
from session_contract import ROLES, sha256_file


class RegistrationIndexLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.api = api_fixture.SessionMetadataApiTests(
            "test_http_metadata_roundtrips_into_draft_and_immutable_registration")
        self.addCleanup(self.api.doCleanups)
        self.api.setUp()

    def get(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=6)
        try:
            headers = {"Host": f"127.0.0.1:{self.api.port}", **self.api.auth()}
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def prepare(self, sid, *, metadata):
        status, value = self.api.create(sid, metadata=metadata)
        self.assertEqual(status, 201, value)
        root = self.api.projects / sid
        for role in ROLES:
            (root / "raw" / (role + ".mp4")).write_bytes(
                ("TEST_ONLY generated registration " + sid + role).encode("ascii"))
        return root

    def register(self, sid):
        # Only codec/readiness is isolated; real HTTP/service/registration/index remain.
        with patch("session_library._check_readiness_locked", return_value={
                "ready_to_register": True, "issues": [], "missing": []}), patch(
                "session_index.probe_clip", return_value={
                    "width": 640, "height": 480, "fps": 30.0, "duration": 1.0}):
            return self.api.post(f"/api/v1/sessions/{sid}/register",
                                 {"confirm": True}, headers=self.api.auth())

    def test_00_registration_immediately_exposes_indexed_metadata_without_passport_get(self):
        metadata = api_fixture.generated_metadata()
        root = self.prepare("lifecycle-confirmed", metadata=metadata)
        status, value = self.register(root.name)
        self.assertEqual(status, 200, value)
        before = (root / "session.json").read_bytes()
        status, rows = self.get("/api/v1/sessions")
        self.assertEqual(status, 200, rows)
        selected = next(row for row in rows["sessions"] if row["id"] == root.name)
        self.assertEqual(selected["metadata_state"]["status"], "AVAILABLE", selected)
        self.assertEqual(selected["effective_metadata"], metadata)
        self.assertRegex(selected["metadata_context_sha256"], r"^[0-9a-f]{64}$")
        status, detail = self.get(f"/api/v1/sessions/{root.name}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["metadata_state"]["status"], "AVAILABLE", detail)
        self.assertEqual((root / "session.json").read_bytes(), before)
        for role in ROLES:
            row = self.api.service.index.conn.execute(
                "SELECT sha256 FROM sources WHERE session_id=? AND role=?",
                (root.name, role)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["sha256"], sha256_file(root / "raw" / (role + ".mp4")))

    def test_01_legacy_missing_metadata_keeps_registration_but_never_available_context(self):
        root = self.prepare("lifecycle-legacy", metadata=None)
        status, value = self.register(root.name)
        self.assertEqual(status, 200, value)
        before = (root / "session.json").read_bytes()
        status, rows = self.get("/api/v1/sessions")
        self.assertEqual(status, 200, rows)
        selected = next(row for row in rows["sessions"] if row["id"] == root.name)
        self.assertEqual(selected["metadata_state"]["status"], "UNAVAILABLE", selected)
        self.assertIsNone(selected["effective_metadata"])
        self.assertIsNone(selected["metadata_context_sha256"])
        self.assertEqual((root / "session.json").read_bytes(), before)

    def test_02_later_registration_does_not_replace_earlier_changed_capture_baseline(self):
        first = self.prepare("lifecycle-old", metadata=api_fixture.generated_metadata())
        self.assertEqual(self.register(first.name)[0], 200)
        role = ROLES[0]
        path = first / "raw" / (role + ".mp4")
        original_digest = sha256_file(path)
        original_manifest = (first / "session.json").read_bytes()
        path.write_bytes(b"TEST_ONLY changed original after registration")
        second = self.prepare("lifecycle-new", metadata=api_fixture.generated_metadata())
        self.assertEqual(self.register(second.name)[0], 200)
        row = self.api.service.index.conn.execute(
            "SELECT sha256,observed_sha256,integrity_state FROM sources WHERE session_id=? AND role=?",
            (first.name, role)).fetchone()
        self.assertEqual(row["sha256"], original_digest)
        self.assertNotEqual(row["observed_sha256"], original_digest)
        self.assertEqual(row["integrity_state"], "changed")
        self.assertEqual((first / "session.json").read_bytes(), original_manifest)
        status, rows = self.get("/api/v1/sessions")
        self.assertEqual(status, 200, rows)
        selected = next(row for row in rows["sessions"] if row["id"] == first.name)
        self.assertEqual(selected["metadata_state"]["status"], "UNAVAILABLE", selected)
        self.assertIsNone(selected["effective_metadata"])

    def test_03_index_failure_never_reports_success_or_replaces_registered_sources_on_retry(self):
        root = self.prepare("lifecycle-index-fault", metadata=api_fixture.generated_metadata())
        originals = {p: p.read_bytes() for p in (root / "raw").glob("*.mp4")}
        with patch.object(self.api.service.index, "reindex", side_effect=ValueError("TEST_ONLY_INDEX_UNAVAILABLE")):
            status, value = self.register(root.name)
        self.assertEqual(status, 409, value)
        self.assertTrue((root / "session.json").is_file())
        manifest = (root / "session.json").read_bytes()
        status, value = self.register(root.name)
        self.assertEqual(status, 409, value)
        self.assertEqual((root / "session.json").read_bytes(), manifest)
        self.assertEqual({p: p.read_bytes() for p in originals}, originals)
