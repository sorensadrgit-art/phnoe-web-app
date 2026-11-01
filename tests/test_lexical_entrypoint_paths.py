"""TEST_ONLY lexical entrypoint aliases: real links, ordinary controls, no mocks."""
import errno
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import export_motion
import test_export_motion
import test_session_index
import test_sync_evidence
import test_workflow_controller
from session_index import SessionIndex
from sync_evidence import SyncEvidenceError, normalized_videos, prepare_sync, save_sync, suggested_reference
from workflow_controller import WorkflowBlocked, WorkflowController


@contextmanager
def fixture(case):
    value = case()
    try:
        value.setUp()
        yield value
    finally:
        try:
            value.tearDown()
        finally:
            value.doCleanups()


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


class LexicalEntrypointPathsTests(unittest.TestCase):
    def linked(self, target):
        owned = tempfile.TemporaryDirectory(prefix="TEST_ONLY-entrypoint-alias-")
        self.addCleanup(owned.cleanup)
        alias = Path(owned.name).absolute() / "linked-input"
        try:
            alias.symlink_to(target, target_is_directory=target.is_dir())
        except NotImplementedError as error:
            self.skipTest("real symlink unsupported: " + str(error))
        except OSError as error:
            if getattr(error, "winerror", None) == 1314 or error.errno in (
                    errno.EPERM, errno.EACCES, errno.ENOTSUP):
                self.skipTest("real symlink unavailable on this host: " + str(error))
            raise
        self.addCleanup(alias.unlink, missing_ok=True)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), target.resolve())
        return alias

    def test_index_projects_alias_refused_before_database_creation(self):
        with fixture(test_session_index.SessionIndexTests) as f:
            control = SessionIndex(f.db_path, f.projects, read_only=True)
            try:
                self.assertEqual(control.query_sessions(), [])
            finally:
                control.close()
            alias = self.linked(f.projects)
            before = snapshot(f.root)
            opened = None
            try:
                with self.assertRaisesRegex(ValueError, "TAKE_RECOVERY_UNKNOWN"):
                    opened = SessionIndex(f.root / "must-not-create" / "index.db", alias)
            finally:
                if opened is not None:
                    opened.close()
                self.assertEqual(snapshot(f.root), before)
                self.assertTrue(alias.is_symlink())

    def test_index_database_leaf_and_ancestor_aliases_refused(self):
        with fixture(test_session_index.SessionIndexTests) as f:
            leaf = self.linked(f.db_path)
            ancestor = self.linked(f.root)
            before = snapshot(f.root)
            for spelling in (leaf, ancestor / f.db_path.name):
                with self.subTest(spelling=spelling):
                    opened = None
                    try:
                        with self.assertRaisesRegex(ValueError, "TAKE_RECOVERY_UNKNOWN"):
                            opened = SessionIndex(spelling, f.projects, read_only=True)
                    finally:
                        if opened is not None:
                            opened.close()
                        self.assertEqual(snapshot(f.root), before)
                        self.assertTrue(leaf.is_symlink())
                        self.assertTrue(ancestor.is_symlink())

    def test_workflow_ancestor_alias_refused_with_ordinary_session_control(self):
        with fixture(test_workflow_controller.WorkflowControllerTests) as f:
            self.assertEqual(WorkflowController(f.project).project, f.project.resolve())
            alias = self.linked(f.root)
            before = snapshot(f.root)
            try:
                with self.assertRaisesRegex(WorkflowBlocked, "plain non-link"):
                    WorkflowController(alias / f.project.name)
            finally:
                self.assertEqual(snapshot(f.root), before)
                self.assertTrue(alias.is_symlink())

    def test_sync_entrypoints_preserve_lexical_project_and_original_bytes(self):
        with fixture(test_sync_evidence.SyncEvidenceTests) as f:
            session, videos = normalized_videos(f.project)
            self.assertEqual(session["session_id"], f.session["session_id"])
            self.assertEqual(set(videos), {"cam01", "cam02"})
            self.assertEqual(suggested_reference(f.project), "cam02")
            control = prepare_sync(f.project, f.cues, reference="cam02", operator_confirmed=True)
            self.assertEqual(len(control["source_frame_pairs"]), 4)
            alias = self.linked(f.root)
            project = alias / f.project.name
            before = snapshot(f.root)
            calls = (
                lambda: normalized_videos(project),
                lambda: suggested_reference(project),
                lambda: prepare_sync(project, f.cues, reference="cam02", operator_confirmed=True),
                lambda: save_sync(project, f.cues, reference="cam02", operator_confirmed=True),
            )
            for call in calls:
                with self.subTest(entrypoint=call):
                    try:
                        with self.assertRaisesRegex(SyncEvidenceError, "plain non-link"):
                            call()
                    finally:
                        self.assertEqual(snapshot(f.root), before)
                        self.assertTrue(alias.is_symlink())

    def test_direct_export_manifest_and_explicit_source_aliases_refused(self):
        with fixture(test_export_motion.ExportTests) as f:
            manifest = f.manifest(with_mot=True)
            expected = export_motion.bind_run(manifest, f.trc, f.mot)
            self.assertEqual(expected["quality"]["status"], "passed")
            self.assertEqual(expected["quality"]["mode"], "kinematics")
            root_alias = self.linked(f.root)
            manifest_alias = self.linked(manifest)
            trc_alias = self.linked(f.trc)
            mot_alias = self.linked(f.mot)
            before = snapshot(f.root)
            cases = (
                (root_alias / manifest.relative_to(f.root), f.trc, f.mot),
                (manifest_alias, f.trc, f.mot),
                (manifest, trc_alias, f.mot),
                (manifest, f.trc, mot_alias),
            )
            for paths in cases:
                with self.subTest(paths=paths):
                    try:
                        with self.assertRaisesRegex(ValueError, "ARTIFACT_MISMATCH"):
                            export_motion.bind_run(*paths)
                    finally:
                        self.assertEqual(snapshot(f.root), before)
                        for alias in (root_alias, manifest_alias, trc_alias, mot_alias):
                            self.assertTrue(alias.is_symlink())
