"""W2.4 proposed real-handler contract over owned TEST_ONLY generated projects.

Source-only preparation. No test, import, syntax or runtime result is claimed.
Only codec probing of generated non-codec bytes is doubled; route, publisher,
audit, current metadata, OS lease and readback use their actual implementations.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import take_acceptance as takes
from native_evidence_fixture import complete_native_fixture
from session_contract import ROLES, load_session, sha256_file
from session_metadata_revision import RECEIPT_SCHEMA, read_metadata_state
from setup_project import register_captures
from t6_server import make_server
from t6_service import IntegratedService

SID = "TEST_ONLY-B10-revision-api"
TOKEN = "TEST_ONLY-B10-" + "a" * 50
ANCHOR = "takes/.acceptance-lease/t6-startup.lock"


def generated_metadata():
    return {"schema": "kinelab.session-metadata.v1", "subject_id": "sub-" + "1" * 32,
            "operator_id": "op-" + "2" * 32, "task_id": "TEST_ONLY-task",
            "protocol_id": "TEST_ONLY-protocol", "protocol_version": "1", "laterality": "bilateral",
            "confirmed": True, "confirmed_at": "2026-10-29T16:00:00+00:00"}


class SessionMetadataRevisionApiTests(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(prefix="TEST_ONLY-B10-revision-api-")
        self.addCleanup(owned.cleanup)
        self.base = Path(owned.name)
        self.projects = self.base / "TEST_ONLY-projects"
        self.folder = self.projects / SID
        (self.folder / "raw").mkdir(parents=True)
        (self.folder / "Config.toml").write_text("# TEST_ONLY generated\n[project]\n", encoding="utf-8")
        self.initial = generated_metadata()
        self.write(self.folder / "session-template.json", {
            "schema": "kinelab.session-template.v1", "session_id": SID, "kind": "real", "metadata": self.initial})
        for role in ROLES:
            (self.folder / "raw" / (role + ".mp4")).write_bytes(("TEST_ONLY non-codec " + role).encode())
        register_captures(self.folder, SID, metadata=self.initial)
        self.assertEqual(load_session(self.folder)["metadata"], self.initial)
        complete_native_fixture(self.folder, "", through="poseEstimation")
        probe = patch("session_index.probe_clip", return_value={
            "width": 1024, "height": 576, "fps": 30, "duration": 8})
        probe.start()
        self.addCleanup(probe.stop)
        self.service = IntegratedService(projects_root=self.projects)
        self.addCleanup(self.service.close)
        self.service.index.reindex()
        state = read_metadata_state(self.service.index, SID)
        self.assertEqual(state["status"], "AVAILABLE", ("Generated fixture setup", state))
        self.origin = (self.folder / "session.json").read_bytes()
        self.origin_sha256 = sha256_file(self.folder / "session.json")
        # Registration already established this persistent administrative anchor.
        # Refusal snapshots never delete/recreate it or infer missing-anchor policy.
        self.assertTrue((self.folder / ANCHOR).is_file())
        dist, samples = self.base / "TEST_ONLY-dist", self.base / "TEST_ONLY-samples"
        dist.mkdir()
        samples.mkdir()
        (dist / "index.html").write_text("<title>TEST_ONLY B10 API</title>", encoding="utf-8")
        self.server = make_server(self.service, token=TOKEN, dist=dist, samples=samples, port=0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=4)

    def request(self, method, path, body=None, *, authenticated=True, origin=None):
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if authenticated:
            headers.update(Authorization="Bearer " + TOKEN,
                           Origin=origin or f"http://127.0.0.1:{self.port}")
        payload = json.dumps(body, allow_nan=False).encode("utf-8") if isinstance(body, dict) else body
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        try:
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def post(self, body, **options):
        return self.request("POST", f"/api/v1/sessions/{SID}/metadata-revisions", body, **options)

    def body(self, operation="1" * 32, *, laterality="left", current=False):
        state = read_metadata_state(self.service.index, SID)
        changed = copy.deepcopy(self.initial)
        changed.update(laterality=laterality, confirmed_at="2026-10-29T16:01:00+00:00")
        return {"metadata": changed, "expected_origin_sha256": self.origin_sha256,
                "expected_head_sha256": state["head"]["sha256"] if current and state["head"] else None,
                "operation_id": operation, "reason_code": "operator_correction", "confirm": True}

    def snapshot(self, *, held=None):
        result = {}
        for path in sorted(self.projects.rglob("*")):
            relative = path.relative_to(self.projects).as_posix()
            identity = path.stat()
            if path.is_file():
                if held is not None and path == self.folder / ANCHOR:
                    position = held.tell()
                    try:
                        held.seek(0)
                        raw = held.read()
                    finally:
                        held.seek(position)
                else:
                    raw = path.read_bytes()
                result[relative] = (identity.st_dev, identity.st_ino, hashlib.sha256(raw).hexdigest())
            else:
                result[relative + "/"] = (identity.st_dev, identity.st_ino)
        return result

    def refused(self, body, *, code=None, held=None, status=409, path=None, **options):
        before, audit = self.snapshot(held=held), self.service.index.verify_audit()
        actual, response = (self.post(body, **options) if path is None
                            else self.request("POST", path, body, **options))
        self.assertEqual(actual, status, response)
        if code is not None:
            self.assertIn(code, json.dumps(response))
        self.assertEqual(self.snapshot(held=held), before, "Refusal changed generated evidence or identities")
        self.assertEqual(self.service.index.verify_audit(), audit)
        return response

    def published(self, body):
        status, receipt = self.post(body)
        self.assertEqual(status, 200, ("W2.4 authenticated route/publisher business assertion", receipt))
        self.assertEqual(receipt["schema"], RECEIPT_SCHEMA)
        self.assertEqual((receipt["session_id"], receipt["operation_id"]), (SID, body["operation_id"]))
        relative = Path(receipt["descriptor"]["path"])
        self.assertFalse(relative.is_absolute())
        self.assertNotIn("..", relative.parts)
        self.assertEqual(sha256_file(self.folder / receipt["descriptor"]["path"]), receipt["descriptor"]["sha256"])
        return receipt

    def test_B10_WRITE_00_authenticated_publication_and_existing_readback_preserve_origins(self):
        before = self.snapshot()
        body = self.body()
        receipt = self.published(body)
        state = read_metadata_state(self.service.index, SID)
        self.assertEqual(state["status"], "AVAILABLE", state)
        self.assertEqual(state["metadata"], body["metadata"])
        self.assertEqual(state["head"], receipt["descriptor"])
        self.assertEqual(state["context_sha256"], receipt["context_sha256"])
        self.assertEqual((self.folder / "session.json").read_bytes(), self.origin)
        after = self.snapshot()
        database = self.service.index.db_path.relative_to(self.projects).as_posix()
        self.assertEqual({key: after[key] for key in before if key != database},
                         {key: value for key, value in before.items() if key != database})
        self.assertEqual(after[database][:2], before[database][:2], "Index database identity changed")
        self.service.index.verify_audit()
        events = list(self.service.index.conn.execute(
            "SELECT details_json FROM audit_events WHERE session_id=? AND event_type=? ORDER BY id",
            (SID, "METADATA_REVISION_PUBLISHED")))
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events[0]["details_json"]), {
            "operation_id": body["operation_id"], "descriptor": receipt["descriptor"], "receipt": receipt})
        status, detail = self.request("GET", f"/api/v1/sessions/{SID}")
        self.assertEqual(status, 200, detail)
        status, listing = self.request("GET", "/api/v1/sessions")
        self.assertEqual(status, 200, listing)
        row = next(item for item in listing["sessions"] if item["id"] == SID)
        for payload in (detail, row):
            self.assertEqual(payload["metadata_state"], state, "Depends on verified W2.1 read-only integration")
            self.assertEqual(payload["effective_metadata"], body["metadata"])
            self.assertEqual(payload["metadata_context_sha256"], receipt["context_sha256"])
        self.assertEqual(detail["metadata_confirmation"]["metadata"], self.initial)

    def test_B10_WRITE_01_exact_replay_precedes_stale_head_and_conflict_is_immutable(self):
        first = self.body()
        receipt = self.published(first)
        self.published(self.body("2" * 32, laterality="right", current=True))
        before, audit = self.snapshot(), self.service.index.verify_audit()
        self.assertEqual(self.post(first), (200, receipt))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service.index.verify_audit(), audit)
        changed = copy.deepcopy(first)
        changed["metadata"]["laterality"] = "right"
        self.refused(changed, code="METADATA_OPERATION_CONFLICT")

    def test_B10_WRITE_02_stale_origin_and_head_refuse_without_new_evidence(self):
        body = self.body()
        self.refused({**body, "expected_origin_sha256": "0" * 64}, code="METADATA_CONTEXT_CHANGED")
        self.published(body)
        self.refused(self.body("3" * 32), code="METADATA_CONTEXT_CHANGED")
        self.refused({**self.body("4" * 32, current=True), "expected_head_sha256": "f" * 64},
                     code="METADATA_CONTEXT_CHANGED")

    def test_B10_WRITE_03_strict_envelope_metadata_confirmation_json_and_transport(self):
        body = self.body()
        variants = [{**body, "confirm": value} for value in (False, None, 1, "true")]
        variants += [{**body, "operation_id": value} for value in (True, "A" * 32, "x", "../escape")]
        variants += [{**body, "reason_code": value} for value in (None, "backfill", True)]
        variants += [{**body, "expected_head_sha256": value} for value in (False, "x", 1)]
        variants += [{**body, "metadata": value} for value in (None, [], True)]
        variants += [{**body, "clinical_accuracy_validated": True}, {**body, "output_path": "../escape"}]
        for field, value in (("confirmed", 1), ("subject_id", "name"), ("laterality", "unknown"),
                             ("confirmed_at", "2026-10-29T16:00:00"), ("unexpected", "TEST_ONLY")):
            altered = copy.deepcopy(body)
            altered["metadata"][field] = value
            variants.append(altered)
        for missing in body:
            altered = copy.deepcopy(body)
            del altered[missing]
            variants.append(altered)
        for number, value in enumerate(variants):
            with self.subTest(case=number):
                self.refused(value)
        for raw in (b'{"confirm":true,"confirm":false}', b'{"metadata":{"confirmed":NaN}}',
                    b'{"metadata":{"confirmed":Infinity}}', b'{"metadata":{"confirmed":1e999}}', b'[]'):
            with self.subTest(raw=raw):
                self.refused(raw)
        self.refused(b"x" * 65537, status=413)

    def test_B10_WRITE_04_authentication_and_foreign_origin_refuse_without_writes(self):
        self.refused(self.body(), authenticated=False, status=401)
        self.refused(self.body(), origin="https://example.invalid", status=403)

    def test_B10_WRITE_05_active_work_actual_os_lease_and_bound_pending_take_refuse(self):
        body = self.body()
        self.service.webcam = {"session": SID, "TEST_ONLY": True}
        try:
            self.refused(body, code="METADATA_BUSY")
        finally:
            self.service.webcam = None
        self.service.jobs[SID] = SimpleNamespace(poll=lambda: SimpleNamespace(state="running"))
        try:
            self.refused(body, code="METADATA_BUSY")
        finally:
            self.service.jobs.pop(SID)
        with takes.acceptance_lease(self.folder) as held:
            self.refused(body, held=held)
        operation, role = "e" * 32, "cam01_trial"
        staged = self.folder / "takes" / role / "TEST_ONLY-selected.mp4"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"TEST_ONLY staged pending take")
        canonical = self.folder / "raw" / (role + ".mp4")
        journal = self.folder / "takes/acceptance" / operation
        journal.mkdir(parents=True)
        proof = takes.write_record(journal / "intent.json", {
            "schema": "kinelab.take-acceptance.v1", "transaction_id": operation, "session_id": SID,
            "role": role, "staged_name": staged.name, "staged_sha256": sha256_file(staged),
            "staged_bytes": staged.stat().st_size, "prior_sha256": sha256_file(canonical),
            "prior_bytes": canonical.stat().st_size})
        takes.write_record(self.folder / "takes/accept.lock", takes.marker_record(operation, proof.sha256))
        pending = takes.inspect_acceptance(self.folder)
        self.assertEqual((pending["state"], pending["transaction_id"]), ("recovery-required", operation))
        self.refused(body)

    def test_B10_WRITE_06_tampered_origin_is_preserved_and_drafts_have_no_fallback(self):
        body = self.body()
        changed = json.loads(self.origin)
        changed["metadata"]["laterality"] = "right"
        self.write(self.folder / "session.json", changed)
        self.refused(body, code="METADATA_")
        draft = self.service.library.create_session("TEST_ONLY-draft", metadata=self.initial)
        self.assertFalse((draft / "session.json").exists())
        self.refused(body, path=f"/api/v1/sessions/{draft.name}/metadata-revisions",
                     code="METADATA_REGISTERED_SESSION_REQUIRED")
        self.assertFalse((draft / "session.json").exists())

    def test_B10_WRITE_07_tampered_committed_revision_is_not_healed_or_replayed(self):
        first = self.body()
        receipt = self.published(first)
        descriptor = self.folder / receipt["descriptor"]["path"]
        descriptor.write_bytes(descriptor.read_bytes() + b" ")
        state = read_metadata_state(self.service.index, SID)
        self.assertEqual(state["status"], "UNAVAILABLE", state)
        self.refused(first, code="METADATA_")
        self.refused(self.body("9" * 32), code="METADATA_")
