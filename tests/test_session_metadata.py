"""Generated identities and capture bytes only; no human identity or capture proof."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import session_contract
from session_contract import ROLES, load_session
from session_library import SessionLibrary
from setup_project import register_captures


def confirmed_metadata():
    return {
        "schema": "kinelab.session-metadata.v1",
        "subject_id": "sub-11111111111111111111111111111111",
        "operator_id": "op-22222222222222222222222222222222",
        "task_id": "generated-squat", "protocol_id": "generated-protocol",
        "protocol_version": "1", "laterality": "bilateral",
        "confirmed": True, "confirmed_at": "2026-10-29T10:00:00+00:00",
    }


class SessionMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def raw(self, root):
        (root / "raw").mkdir(exist_ok=True)
        for role in ROLES:
            (root / "raw" / (role + ".mp4")).write_bytes(("generated " + role).encode())

    def test_confirmation_schema_and_opaque_identifiers_are_required(self):
        good = confirmed_metadata()
        self.assertEqual(session_contract.validate_session_metadata(good), good)
        for key, value in (("confirmed", False), ("confirmed", 1),
                           ("subject_id", "Jane Doe"), ("operator_id", "clinician@example.org"),
                           ("schema", "kinelab.session-metadata.v99"),
                           ("confirmed_at", "2026-10-29"), ("laterality", "unknown"),
                           ("task_id", ""), ("protocol_version", 1)):
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(good); bad[key] = value
                with self.assertRaises(ValueError):
                    session_contract.validate_session_metadata(bad)
        bad = {**good, "real_name": "not allowed"}
        with self.assertRaises(ValueError):
            session_contract.validate_session_metadata(bad)

    def test_registration_roundtrips_metadata_without_rewriting_originals(self):
        self.raw(self.root)
        before = {p: p.read_bytes() for p in (self.root / "raw").iterdir()}
        metadata = confirmed_metadata()
        register_captures(self.root, "generated", metadata=metadata)
        self.assertEqual(load_session(self.root)["metadata"], metadata)
        original = (self.root / "session.json").read_bytes()
        with self.assertRaises(ValueError):
            register_captures(self.root, "generated", metadata=metadata)
        self.assertEqual((self.root / "session.json").read_bytes(), original)
        for p, content in before.items():
            self.assertEqual(p.read_bytes(), content)

    def test_legacy_registration_stays_without_manufactured_metadata(self):
        self.raw(self.root)
        register_captures(self.root, "legacy")
        self.assertNotIn("metadata", load_session(self.root))

    def test_library_creation_carries_explicit_metadata_to_draft(self):
        library = SessionLibrary(self.root)
        project = library.create_session("generated", metadata=confirmed_metadata())
        draft = json.loads((project / "session-template.json").read_text())
        self.assertEqual(draft["metadata"], confirmed_metadata())
        self.raw(project)
        # Only hardware readiness is isolated; the real library locks the saved confirmation.
        with patch("session_library._check_readiness_locked", return_value={
                "ready_to_register": True, "issues": [], "missing": []}):
            library.register_session("generated")
        self.assertEqual(load_session(project)["metadata"], confirmed_metadata())

