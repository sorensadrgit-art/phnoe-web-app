"""B10 wave-one contract: generated TEST_ONLY bytes, never human evidence.

These tests call the actual proposed publisher/resolver, SQLite audit and OS
session lease. The optional module import makes missing callables assertion
failures, rather than collection errors. Publication fault injection is not a
claim that native process-death or disk/power-loss recovery has been verified.
Report/comparison/API/UI integration remains a separately required later wave.
"""

import copy
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from session_contract import ROLES, load_session, validate_session_metadata
from session_index import SessionIndex
from setup_project import register_captures
from take_acceptance import acceptance_lease

revisions: ModuleType | None
try:
    revisions = importlib.import_module("session_metadata_revision")
except ModuleNotFoundError as error:
    if error.name != "session_metadata_revision":
        raise
    revisions = None


class InterruptedPublication(BaseException):
    """Bypass ordinary Exception cleanup at an actual publisher checkpoint."""


def confirmed_metadata():
    return {
        "schema": "kinelab.session-metadata.v1",
        "subject_id": "sub-" + "1" * 32,
        "operator_id": "op-" + "2" * 32,
        "task_id": "test-only-generated-task",
        "protocol_id": "test-only-generated-protocol",
        "protocol_version": "1",
        "laterality": "bilateral",
        "confirmed": True,
        "confirmed_at": "2026-10-29T16:00:00+00:00",
    }


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class SessionMetadataRevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-B10-TEST_ONLY-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.projects = self.base / "projects"
        self.projects.mkdir()
        self.session_id = "generated-B10-a"
        self.root = self.projects / self.session_id
        self.initial = confirmed_metadata()
        self._registered(self.session_id, self.initial)
        self.index = SessionIndex(self.base / "generated-index.db", self.projects)
        self.addCleanup(self.index.close)
        # Generated clip bytes are not codecs; no media probe/device is invoked.
        # All registration, manifest/hash checks, index transactions and audit
        # operations remain real. This double never establishes capture proof.
        with patch("session_index.probe_clip", return_value={
            "width": 640, "height": 480, "fps": 30, "duration": 1,
        }):
            self.index.reindex()
        self.originals = self._bytes(self.root)
        self.origin_sha = sha256((self.root / "session.json").read_bytes())
        self.audit_before = self.index.verify_audit()
        self.changed = copy.deepcopy(self.initial)
        self.changed.update({
            "subject_id": "sub-" + "3" * 32,
            "operator_id": "op-" + "4" * 32,
            "laterality": "left",
            "confirmed_at": "2026-10-29T16:01:00+00:00",
        })

    def _registered(self, session_id, metadata):
        folder = self.projects / session_id
        (folder / "raw").mkdir(parents=True)
        (folder / "Config.toml").write_text(
            '# TEST_ONLY generated fixture; no physical evidence\n[project]\n',
            encoding="utf-8",
        )
        for role in ROLES:
            (folder / "raw" / (role + ".mp4")).write_bytes(
                ("TEST_ONLY generated capture bytes " + role).encode("ascii")
            )
        template = {
            "schema": "kinelab.session-template.v1", "session_id": session_id,
            "kind": "real", "metadata": copy.deepcopy(metadata),
        }
        if metadata is None:
            template.pop("metadata")
        (folder / "session-template.json").write_text(
            json.dumps(template, sort_keys=True), encoding="utf-8"
        )
        register_captures(folder, session_id, kind="real", metadata=metadata)
        self.assertEqual(load_session(folder)["session_id"], session_id)
        return folder

    @staticmethod
    def _bytes(folder):
        return {p.relative_to(folder).as_posix(): p.read_bytes()
                for p in folder.rglob("*") if p.is_file()}

    def _api(self, name):
        self.assertIsNotNone(
            revisions,
            "B10 missing actual session_metadata_revision publisher/resolver module",
        )
        function = getattr(revisions, name, None)
        self.assertTrue(callable(function), "B10 missing callable " + name)
        return function

    def _state(self, session_id=None, index=None):
        return self._api("read_metadata_state")(
            index or self.index, session_id or self.session_id,
        )

    def _publish(self, *, metadata=None, operation_id=None, head=None,
                 origin=None, session_id=None, index=None, confirm=True):
        return self._api("publish_metadata_revision")(
            index or self.index, session_id or self.session_id,
            metadata=copy.deepcopy(self.changed if metadata is None else metadata),
            expected_origin_sha256=self.origin_sha if origin is None else origin,
            expected_head_sha256=head,
            operation_id="a" * 32 if operation_id is None else operation_id,
            reason_code="operator_correction", confirm=confirm,
        )

    def _events(self, session_id=None):
        return [dict(row) for row in self.index.conn.execute(
            "SELECT * FROM audit_events WHERE session_id=? AND event_type=? ORDER BY id",
            (session_id or self.session_id, "METADATA_REVISION_PUBLISHED"),
        )]

    def _unchanged_originals(self):
        for name, before in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), before, name)
        self.assertEqual(load_session(self.root)["metadata"], self.initial)

    def _descriptor(self, receipt):
        path = self.root / receipt["descriptor"]["path"]
        self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))
        raw = path.read_bytes()
        self.assertEqual(sha256(raw), receipt["descriptor"]["sha256"])
        return path, json.loads(raw)

    def test_B10_REV_01_registered_initial_state_binds_original_source(self):
        state = self._state()
        self.assertEqual(state["schema"], "kinelab.session-metadata-state.v1")
        self.assertEqual(state["session_id"], self.session_id)
        self.assertEqual(state["status"], "AVAILABLE")
        self.assertEqual(state["metadata"], self.initial)
        self.assertEqual(state["initial_metadata"], self.initial)
        self.assertEqual(state["origin"], {"path": "session.json", "sha256": self.origin_sha})
        self.assertIsNone(state["head"])
        self.assertRegex(state["context_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(self._events(), [])
        self._unchanged_originals()

    def test_B10_REV_02_actual_publication_commits_audit_and_preserves_origin(self):
        initial = self._state()
        receipt = self._publish()
        self.assertEqual(receipt["schema"], "kinelab.session-metadata-revision-receipt.v1")
        self.assertEqual(receipt["session_id"], self.session_id)
        self.assertEqual(receipt["operation_id"], "a" * 32)
        self.assertRegex(receipt["revision_id"], r"^[0-9a-f]{32}$")
        _, descriptor = self._descriptor(receipt)
        self.assertEqual(descriptor["metadata"], self.changed)
        self.assertEqual(descriptor["initial_metadata"], self.initial)
        self.assertEqual(descriptor["origin"], initial["origin"])
        self.assertIsNone(descriptor["previous"])
        events = self._events()
        self.assertEqual(len(events), 1)
        details = json.loads(events[0]["details_json"])
        self.assertEqual(details["operation_id"], receipt["operation_id"])
        self.assertEqual(details["descriptor"], receipt["descriptor"])
        self.assertNotEqual(self.index.verify_audit(), self.audit_before)
        current = self._state()
        self.assertEqual(current["metadata"], self.changed)
        self.assertEqual(current["initial_metadata"], self.initial)
        self.assertEqual(current["head"]["sha256"], receipt["descriptor"]["sha256"])
        self.assertEqual(current["context_sha256"], receipt["context_sha256"])
        self.assertNotEqual(current["context_sha256"], initial["context_sha256"])
        self._unchanged_originals()

    def test_B10_REV_03_second_revision_keeps_prior_descriptor_and_chain(self):
        first = self._publish()
        path, _ = self._descriptor(first)
        preserved = path.read_bytes()
        newer = copy.deepcopy(self.changed)
        newer["laterality"] = "right"
        second = self._publish(metadata=newer, operation_id="b" * 32,
                               head=first["descriptor"]["sha256"])
        _, descriptor = self._descriptor(second)
        self.assertEqual(descriptor["previous"], first["descriptor"])
        self.assertEqual(path.read_bytes(), preserved)
        self.assertEqual(len(self._events()), 2)
        self.assertEqual(self._state()["metadata"], newer)
        self.index.verify_audit()
        self._unchanged_originals()

    def test_B10_REV_04_exact_operation_retry_returns_same_receipt_once(self):
        first = self._publish()
        before = self._bytes(self.root)
        retry = self._publish()
        self.assertEqual(retry, first)
        self.assertEqual(len(self._events()), 1)
        self.assertEqual(self._bytes(self.root), before)

    def test_B10_REV_05_conflicting_operation_retry_is_refused(self):
        self._publish()
        before = self._bytes(self.root)
        bad = copy.deepcopy(self.changed)
        bad["laterality"] = "right"
        with self.assertRaisesRegex(ValueError, "METADATA_OPERATION_CONFLICT"):
            self._publish(metadata=bad)
        self.assertEqual(self._bytes(self.root), before)
        self.assertEqual(len(self._events()), 1)

    def test_B10_REV_06_stale_head_on_independent_connection_cannot_commit(self):
        other = SessionIndex(self.base / "generated-index.db", self.projects)
        self.addCleanup(other.close)
        stale = self._state(index=other)
        self.assertIsNone(stale["head"])
        self._publish()
        before = self._bytes(self.root)
        with self.assertRaisesRegex(ValueError, "METADATA_CONTEXT_CHANGED"):
            self._publish(index=other, operation_id="b" * 32)
        self.assertEqual(self._bytes(self.root), before)
        self.assertEqual(len(self._events()), 1)
        self.assertEqual(other.verify_audit(), self.index.verify_audit())

    def test_B10_REV_07_wrong_origin_cannot_publish_or_rebaseline(self):
        self._api("publish_metadata_revision")
        before = self._bytes(self.root)
        with self.assertRaisesRegex(ValueError, "METADATA_CONTEXT_CHANGED"):
            self._publish(origin="0" * 64)
        self.assertEqual(self._bytes(self.root), before)
        self.assertEqual(self.index.verify_audit(), self.audit_before)

    def test_B10_REV_08_exact_nine_field_metadata_and_confirmation_required(self):
        self._api("publish_metadata_revision")
        invalid = []
        for field in self.initial:
            missing = copy.deepcopy(self.changed)
            missing.pop(field)
            invalid.append(missing)
        extra = copy.deepcopy(self.changed)
        extra["patient_name"] = "TEST_ONLY forbidden extra field"
        invalid.append(extra)
        for field, value in (("confirmed", False), ("laterality", "unknown"),
                             ("subject_id", "default"), ("operator_id", "operator"),
                             ("confirmed_at", "2026-10-29T16:00:00")):
            bad = copy.deepcopy(self.changed)
            bad[field] = value
            invalid.append(bad)
        before = self._bytes(self.root)
        for position, metadata in enumerate(invalid):
            with self.subTest(case=position), self.assertRaises(ValueError):
                self._publish(metadata=metadata)
        with self.assertRaisesRegex(ValueError, "METADATA_CONFIRMATION_REQUIRED"):
            self._publish(confirm=False)
        self.assertEqual(validate_session_metadata(self.changed), self.changed)
        self.assertEqual(self._bytes(self.root), before)
        self.assertEqual(self._events(), [])

    def test_B10_REV_09_draft_correction_is_explicitly_refused(self):
        self._api("publish_metadata_revision")
        draft = self.projects / "generated-B10-draft"
        draft.mkdir()
        (draft / "session-template.json").write_text(json.dumps({
            "schema": "kinelab.session-template.v1", "session_id": draft.name,
            "kind": "real", "metadata": self.initial,
        }), encoding="utf-8")
        before = self._bytes(draft)
        with self.assertRaisesRegex(ValueError, "METADATA_REGISTERED_SESSION_REQUIRED"):
            self._publish(session_id=draft.name)
        self.assertEqual(self._bytes(draft), before)
        self.assertEqual(self._events(draft.name), [])

    def test_B10_REV_10_unbound_legacy_metadata_is_not_manufactured(self):
        self._api("publish_metadata_revision")
        legacy = self._registered("generated-B10-legacy", None)
        before = self._bytes(legacy)
        state = self._state(legacy.name)
        self.assertEqual(state["status"], "UNAVAILABLE")
        self.assertIsNone(state["metadata"])
        with self.assertRaisesRegex(ValueError, "METADATA_UNAVAILABLE"):
            self._publish(session_id=legacy.name)
        self.assertEqual(self._bytes(legacy), before)

    def test_B10_REV_11_actual_session_lease_excludes_correction(self):
        self._api("publish_metadata_revision")
        with acceptance_lease(self.root), self.assertRaisesRegex(ValueError, "TAKE_BUSY|METADATA_BUSY"):
            self._publish()
        self.assertEqual(self._events(), [])
        self._unchanged_originals()

    def test_B10_REV_12_changed_capture_refuses_without_source_healing(self):
        self._api("publish_metadata_revision")
        capture = next(iter(load_session(self.root)["captures"].values()))
        path = self.root / capture["path"]
        path.write_bytes(b"TEST_ONLY intentionally changed immutable capture")
        changed = self._bytes(self.root)
        self.assertEqual(self._state()["status"], "UNAVAILABLE")
        with self.assertRaises(ValueError):
            self._publish()
        self.assertEqual(self._bytes(self.root), changed)
        self.assertEqual(self._events(), [])

    def test_B10_REV_13_registered_manifest_does_not_fall_back_to_template(self):
        self._api("read_metadata_state")
        (self.root / "session.json").write_bytes(b"{TEST_ONLY invalid registered manifest")
        changed = self._bytes(self.root)
        state = self._state()
        self.assertEqual(state["status"], "UNAVAILABLE")
        self.assertIsNone(state["metadata"])
        with self.assertRaises(ValueError):
            self._publish()
        self.assertEqual(self._bytes(self.root), changed)

    def test_B10_REV_14_tampered_committed_descriptor_is_unavailable(self):
        receipt = self._publish()
        path, descriptor = self._descriptor(receipt)
        descriptor["metadata"]["laterality"] = "right"
        path.write_text(json.dumps(descriptor), encoding="utf-8")
        changed = self._bytes(self.root)
        state = self._state()
        self.assertEqual(state["status"], "UNAVAILABLE")
        self.assertIsNone(state["metadata"])
        with self.assertRaises(ValueError):
            self._publish(operation_id="b" * 32, head=receipt["descriptor"]["sha256"])
        self.assertEqual(self._bytes(self.root), changed)
        self.assertEqual(len(self._events()), 1)

    def test_B10_REV_15_unaudited_sidecar_is_never_current_metadata(self):
        self._api("read_metadata_state")
        candidate = self.root / "metadata-revisions" / ("revision-" + "c" * 32)
        candidate.mkdir(parents=True)
        path = candidate / "revision.json"
        path.write_text(json.dumps({
            "schema": "kinelab.session-metadata-revision.v1",
            "session_id": self.session_id, "metadata": self.changed,
        }), encoding="utf-8")
        before = path.read_bytes()
        state = self._state()
        self.assertTrue(state["status"] == "UNAVAILABLE" or (
            state["status"] == "AVAILABLE" and state["metadata"] == self.initial
            and state["head"] is None))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self._events(), [])

    def test_B10_REV_16_precommit_faults_leave_pending_and_recover_old_head(self):
        publish = self._api("publish_metadata_revision")
        recover = self._api("recover_metadata_revision")
        self.assertTrue(callable(getattr(revisions, "_checkpoint", None)))
        # An injected BaseException tests abrupt interruption fences, not OS death.
        for number, phase in enumerate(("after_intent_fsync", "after_descriptor_publish",
                                        "before_audit_commit")):
            with self.subTest(phase=phase):
                def interrupt(actual, *_args, phase=phase, **_kwargs):
                    if actual == phase:
                        raise InterruptedPublication(phase)

                with (
                    patch.object(revisions, "_checkpoint", side_effect=interrupt),
                    self.assertRaises(InterruptedPublication),
                ):
                    publish(self.index, self.session_id, metadata=self.changed,
                            expected_origin_sha256=self.origin_sha,
                            expected_head_sha256=None,
                            operation_id=(str(number + 1) * 32),
                            reason_code="operator_correction", confirm=True)
                self.assertEqual(self._state()["status"], "UNAVAILABLE")
                self.assertEqual(self._events(), [])
                restored = recover(self.index, self.session_id)
                self.assertEqual(restored["status"], "AVAILABLE")
                self.assertEqual(restored["metadata"], self.initial)
                self.assertIsNone(restored["head"])
                self.assertEqual(self.index.verify_audit(), self.audit_before)
                self._unchanged_originals()

    def test_B10_REV_17_postcommit_fault_recovers_same_receipt_without_second_event(self):
        self._api("publish_metadata_revision")
        recover = self._api("recover_metadata_revision")
        self.assertTrue(callable(getattr(revisions, "_checkpoint", None)))

        def interrupt(phase, *_args, **_kwargs):
            if phase == "after_audit_commit":
                raise InterruptedPublication(phase)

        with (
            patch.object(revisions, "_checkpoint", side_effect=interrupt),
            self.assertRaises(InterruptedPublication),
        ):
            self._publish()
        self.assertEqual(len(self._events()), 1)
        self.assertEqual(self._state()["status"], "UNAVAILABLE")
        restored = recover(self.index, self.session_id)
        self.assertEqual(restored["status"], "AVAILABLE")
        self.assertEqual(restored["metadata"], self.changed)
        retry = self._publish()
        self.assertEqual(restored["context_sha256"], retry["context_sha256"])
        self.assertEqual(len(self._events()), 1)
        self.index.verify_audit()
        self._unchanged_originals()

    def test_B10_REV_18_session_identity_mismatch_is_refused(self):
        self._api("read_metadata_state")
        document = json.loads((self.root / "session.json").read_bytes())
        document["session_id"] = "generated-B10-other"
        (self.root / "session.json").write_text(json.dumps(document), encoding="utf-8")
        changed = self._bytes(self.root)
        self.assertEqual(self._state()["status"], "UNAVAILABLE")
        with self.assertRaises(ValueError):
            self._publish()
        self.assertEqual(self._bytes(self.root), changed)
        self.assertEqual(self._events(), [])

    def test_B10_REV_19_malformed_operation_identity_cannot_create_artifacts(self):
        self._api("publish_metadata_revision")
        before = self._bytes(self.root)
        for operation in ("../outside", "", "a" * 31, "G" * 32):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                self._publish(operation_id=operation)
        self.assertEqual(self._bytes(self.root), before)
        self.assertEqual(self._events(), [])

    def test_B10_REV_20_origin_read_has_explicit_size_refusal(self):
        self._api("read_metadata_state")
        path = self.root / "session.json"
        path.write_bytes(b" " * (65536 + 1))
        before = path.read_bytes()
        state = self._state()
        self.assertEqual(state["status"], "UNAVAILABLE")
        self.assertRegex(state["reason"], "(?i)limit|size|oversize")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self._events(), [])


if __name__ == "__main__":
    unittest.main()
