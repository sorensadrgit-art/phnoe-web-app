"""TEST_ONLY B10 publication boundaries; generated files and real index APIs.

Compose the frozen fixture without inheriting its TestCase or rediscovering its
twenty tests. Checkpoint mutation is software fault injection, not a same-user
security guarantee or native process/power-loss proof. No clinical media is used.
"""

import json
import unittest
from unittest.mock import patch

import test_session_metadata_revisions as fixtures


class SessionMetadataRevisionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = self._new_fixture()
        self.revisions = fixtures.revisions
        self.assertIsNotNone(self.revisions, "Actual B10 module must exist")

    def _new_fixture(self):
        fixture = fixtures.SessionMetadataRevisionTests(methodName="runTest")
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def test_B10_BOUND_01_prospective_cap_refuses_before_write_and_allows_retry(self):
        f = self.fixture
        # A cheap logic boundary; not a512-revision scale/performance test.
        with patch.object(self.revisions, "REVISION_LIMIT", 2):
            first = f._publish()
            second = f._publish(
                operation_id="b" * 32, head=first["descriptor"]["sha256"],
            )
            before = f._bytes(f.root)
            events_before = f._events()
            audit_before = f.index.verify_audit()
            self.assertEqual(
                f._publish(
                    operation_id="b" * 32, head=first["descriptor"]["sha256"],
                ),
                second,
            )
            self.assertEqual(f._bytes(f.root), before)
            with self.assertRaises(ValueError):
                f._publish(
                    operation_id="c" * 32, head=second["descriptor"]["sha256"],
                )
            self.assertEqual(f._events(), events_before, "No over-limit audit commit")
            self.assertEqual(f.index.verify_audit(), audit_before)
            self.assertEqual(f._bytes(f.root), before, "No over-limit intent/candidate")
            current = f._state()
            self.assertEqual(current["status"], "AVAILABLE")
            self.assertEqual(current["head"], second["descriptor"])
            self.assertEqual(
                f._publish(
                    operation_id="b" * 32, head=first["descriptor"]["sha256"],
                ),
                second,
            )
            f._unchanged_originals()

    def _assert_precommit_tamper_refused(self, f, *, phase, target, replace_identity):
        events_before = f._events()
        audit_before = f.index.verify_audit()
        mutation = {}

        def mutate(actual, *context):
            if actual != phase or mutation:
                return
            if target == "candidate":
                path = f.root / context[0]["path"]
            else:
                path = f.root / "metadata-revisions" / ("pending-" + "a" * 32 + ".json")
            original = path.read_bytes()
            before = path.stat()
            saved = None
            if replace_identity:
                # Retain the old inode under this fixture's owned temporary root.
                # Do not introduce a bogus pending filename or a reparse fixture.
                saved = f.base / ("TEST_ONLY-replaced-" + path.name)
                self.assertFalse(saved.exists())
                path.rename(saved)
                path.write_bytes(original)
            else:
                document = json.loads(original)
                if target == "candidate":
                    document["metadata"]["laterality"] = "right"
                else:
                    document["receipt"]["context_sha256"] = "0" * 64
                path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
            after = path.stat()
            mutation.update(
                path=path, expected=path.read_bytes(), original=original, saved=saved,
                old_identity=(before.st_dev, before.st_ino),
                new_identity=(after.st_dev, after.st_ino),
            )

        caught = None
        with patch.object(self.revisions, "_checkpoint", side_effect=mutate):
            try:
                f._publish()
            except ValueError as error:
                caught = error
        self.assertTrue(mutation, "Actual publication checkpoint must be reached")
        if replace_identity:
            self.assertNotEqual(
                mutation["old_identity"], mutation["new_identity"],
                "Fixture must prove ordinary-file identity substitution",
            )
            self.assertEqual(mutation["expected"], mutation["original"])
            self.assertEqual(mutation["saved"].read_bytes(), mutation["original"])
        else:
            self.assertNotEqual(mutation["expected"], mutation["original"])
        self.assertIsNotNone(caught, "Changed publication evidence must refuse before commit")
        self.assertEqual(f._events(), events_before, "Changed evidence must not gain audit authority")
        self.assertEqual(f.index.verify_audit(), audit_before)
        self.assertTrue(mutation["path"].is_file(), "Retain changed pending/candidate evidence")
        self.assertEqual(mutation["path"].read_bytes(), mutation["expected"])
        self.assertEqual(f._state()["status"], "UNAVAILABLE", "Preserved pending state stays fenced")
        f._unchanged_originals()

    def test_B10_BOUND_02_candidate_byte_tamper_refuses_before_audit(self):
        self._assert_precommit_tamper_refused(
            self.fixture, phase="after_descriptor_publish",
            target="candidate", replace_identity=False,
        )

    def test_B10_BOUND_03_pending_intent_byte_tamper_at_both_checkpoints(self):
        for phase in ("after_intent_fsync", "after_descriptor_publish"):
            with self.subTest(phase=phase):
                self._assert_precommit_tamper_refused(
                    self._new_fixture(), phase=phase,
                    target="intent", replace_identity=False,
                )

    def test_B10_BOUND_04_same_byte_candidate_identity_replacement_refuses(self):
        self._assert_precommit_tamper_refused(
            self.fixture, phase="after_descriptor_publish",
            target="candidate", replace_identity=True,
        )

    def test_B10_BOUND_05_same_byte_intent_identity_replacement_refuses(self):
        for phase in ("after_intent_fsync", "after_descriptor_publish"):
            with self.subTest(phase=phase):
                self._assert_precommit_tamper_refused(
                    self._new_fixture(), phase=phase,
                    target="intent", replace_identity=True,
                )

    def test_B10_BOUND_06_recovered_aborted_operation_remains_reserved(self):
        f = self.fixture

        def interrupt(phase, *_context):
            if phase == "after_descriptor_publish":
                raise fixtures.InterruptedPublication("TEST_ONLY precommit interruption")

        with (
            patch.object(self.revisions, "_checkpoint", side_effect=interrupt),
            self.assertRaises(fixtures.InterruptedPublication),
        ):
            f._publish()
        recovered = self.revisions.recover_metadata_revision(f.index, f.session_id)
        self.assertEqual(recovered["status"], "AVAILABLE")
        self.assertIsNone(recovered["head"])
        self.assertEqual(recovered["metadata"], f.initial)
        before = f._bytes(f.root)
        events_before = f._events()
        audit_before = f.index.verify_audit()
        with self.assertRaisesRegex(ValueError, "METADATA_OPERATION_CONFLICT"):
            f._publish()
        self.assertEqual(f._bytes(f.root), before)
        self.assertEqual(f._events(), events_before)
        self.assertEqual(f.index.verify_audit(), audit_before)
        receipt = f._publish(operation_id="b" * 32)
        self.assertEqual(f._state()["head"], receipt["descriptor"])
        self.assertEqual(len(f._events()), len(events_before) + 1)
        f._unchanged_originals()

    def test_B10_BOUND_07_retained_commit_witness_refuses_valid_older_audit(self):
        f = self.fixture
        old_database = f.base / "TEST_ONLY-earlier-index.db"
        # Existing exclusive backup API creates a valid earlier audit prefix.
        # No trigger removal, raw SQL deletion or nonfixture database is used.
        f.index.backup_database(old_database)
        before_database = old_database.read_bytes()
        earlier = fixtures.SessionIndex(old_database, f.projects, read_only=True)
        self.addCleanup(earlier.close)
        self.assertEqual(earlier.verify_audit(), f.audit_before)
        receipt = f._publish()
        self.assertEqual(f._state()["head"], receipt["descriptor"])
        witnesses = list((f.root / "metadata-revisions").glob("resolved-*-committed.json"))
        self.assertEqual(len(witnesses), 1)
        before_session = f._bytes(f.root)
        current_tip = f.index.verify_audit()
        state = self.revisions.read_metadata_state(earlier, f.session_id)
        self.assertEqual(state["status"], "UNAVAILABLE")
        self.assertIsNone(state["metadata"])
        self.assertIn("witness", state["reason"])
        self.assertEqual(old_database.read_bytes(), before_database)
        self.assertEqual(f._bytes(f.root), before_session)
        self.assertEqual(earlier.verify_audit(), f.audit_before)
        self.assertEqual(f.index.verify_audit(), current_tip)
        self.assertEqual(len(f._events()), 1)
        f._unchanged_originals()


if __name__ == "__main__":
    unittest.main()
