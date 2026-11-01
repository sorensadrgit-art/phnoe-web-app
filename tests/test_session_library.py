"""T1 session lifecycle: independent real sessions, no overwrite, explicit quality gates."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_contract import ROLES, sha256_file
from session_library import SessionError, SessionLibrary


class SessionLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projects"
        self.root.mkdir()
        self.library = SessionLibrary(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_new_sessions_created_and_reopened_without_overwriting(self):
        a = self.library.create_session("squat-test-01")
        b = self.library.create_session("squat-test-02")
        self.assertTrue((a / "Config.toml").is_file())
        self.assertTrue((b / "session-template.json").is_file())
        self.assertEqual(self.library.open_session("squat-test-01"), a)
        self.assertEqual(self.library.open_session("squat-test-02"), b)
        records = self.library.list_sessions()
        self.assertEqual({s["id"] for s in records}, {"squat-test-01", "squat-test-02"})
        self.assertTrue(all(s["status"] == "draft" for s in records))
        old = (a / "Config.toml").read_bytes()
        with self.assertRaises((SessionError, FileExistsError)):
            self.library.create_session("squat-test-01")
        self.assertEqual((a / "Config.toml").read_bytes(), old)

    def test_disallow_bad_ids_and_escape(self):
        for bad in ("../escape", "..", ".", "A/B", r"A\B", "", " space", "x" * 101,
                    "CON", "nul", "Trailing.", "Trailing "):
            with self.subTest(value=bad), self.assertRaises((SessionError, ValueError)):
                self.library.create_session(bad)
        self.assertFalse((self.root.parent / "escape").exists())

    def test_symlink_sessions_cannot_escape_root(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "Config.toml").write_text("should remain unchanged")
        try:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable in current Windows account")
        with self.assertRaises(SessionError):
            self.library.open_session("escape")

    def test_existing_legacy_and_mixed_demo_are_inspectable_but_protected(self):
        legacy = self.root / "legacy-demo"
        legacy.mkdir()
        (legacy / "Config.toml").write_text("legacy")
        mixed = self.library.create_session("mixed-test", kind="demo")
        (mixed / "SAMPLE-PROVENANCE.json").write_text("{}")
        entries = {x["id"]: x for x in self.library.list_sessions()}
        self.assertEqual(entries["legacy-demo"]["status"], "legacy")
        self.assertEqual(entries["mixed-test"]["kind"], "test-only")
        self.assertFalse(entries["mixed-test"]["can_register"])
        with self.assertRaises(SessionError):
            self.library.register_session("mixed-test")
        with self.assertRaises(SessionError):
            self.library.register_session("legacy-demo")

    def test_no_registration_from_incomplete_capture_or_unmeasured_board(self):
        project = self.library.create_session("real-a")
        with self.assertRaises(SessionError):
            self.library.register_session("real-a")
        self.assertFalse((project / "session.json").exists())
        result = self.library.registration_readiness("real-a")
        self.assertEqual(set(result["missing"]), set(ROLES))
        self.assertFalse(result["ready_to_register"])

    def test_registered_session_is_immutable_for_takes_and_re_registration(self):
        project = self.library.create_session("registered-a")
        (project / "session.json").write_text('{"schema":"bad"}')
        with self.assertRaises(SessionError):
            self.library.register_session("registered-a")
        with self.assertRaises(SessionError):
            self.library.stage_take("registered-a", "cam01_board", project / "session.json")

    def test_registered_status_rechecks_source_hashes_not_only_manifest_schema(self):
        project = self.library.create_session("hash-check")
        template = json.loads((project / "session-template.json").read_text())
        template.pop("status", None)
        template["created_at"] = "2026-10-26T12:00:00+00:00"
        template["captures"] = {role: {"path": "raw/" + role + ".mp4", "sha256": "0" * 64}
                                for role in ROLES}
        (project / "session.json").write_text(json.dumps(template))
        described = self.library.describe_session("hash-check")
        self.assertEqual(described["status"], "invalid")
        self.assertFalse(described["can_register"])

    def test_stage_and_explicit_accept_preserve_prior_footage(self):
        project = self.library.create_session("takes-a")
        role = "cam01_board"
        original = project / "raw" / (role + ".mp4")
        original.write_bytes(b"original-camera-clip")
        sample = Path(self.tmp.name) / "new-trial.mp4"
        sample.write_bytes(b"new-camera-clip")
        before = sha256_file(original)
        with patch("session_library.probe_clip", return_value={
            "width": 1280, "height": 720, "rotation": 0, "duration": 15,
            "fps": "30/1", "frame_count": 450,
        }):
            staged = self.library.stage_take("takes-a", role, sample)
        self.assertEqual(sha256_file(original), before)
        self.assertTrue(staged.is_file())
        self.assertEqual(sha256_file(staged), sha256_file(sample))
        self.assertEqual(original.read_bytes(), b"original-camera-clip")
        with patch("session_library.probe_clip", return_value={
            "width": 1280, "height": 720, "rotation": 0, "duration": 15,
            "fps": "30/1", "frame_count": 450,
        }):
            chosen = self.library.accept_take("takes-a", role, staged)
        self.assertEqual(chosen, original)
        self.assertEqual(original.read_bytes(), b"new-camera-clip")
        self.assertEqual(sample.read_bytes(), b"new-camera-clip")
        self.assertEqual(staged.read_bytes(), b"new-camera-clip")
        archives = list((project / "takes" / "archive").glob(role + "-*.mp4"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(sha256_file(archives[0]), before)

    def test_take_acceptance_requires_exact_staged_path_and_role(self):
        project = self.library.create_session("takes-b")
        unrelated = Path(self.tmp.name) / "unrelated.mp4"
        unrelated.write_bytes(b"not-selected")
        with self.assertRaises(SessionError):
            self.library.accept_take("takes-b", "cam01_board", unrelated)
        with self.assertRaises(SessionError):
            self.library.stage_take("takes-b", "cam01_madeup", unrelated)
        self.assertFalse((project / "raw" / "cam01_board.mp4").exists())

    def test_participant_trial_takes_refused_before_any_write(self):
        project = self.library.create_session("takes-trial")
        sample = Path(self.tmp.name) / "generated-trial.mp4"
        sample.write_bytes(b"generated-not-participant-footage")

        def tree():
            return {p.relative_to(project).as_posix(): p.read_bytes()
                    for p in project.rglob("*") if p.is_file()}

        for role in ("cam01_trial", "cam02_trial"):
            staged = project / "takes" / role / ("b" * 32 + ".mp4")
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"generated-pre-existing-take")
            before = tree()
            calls = ((self.library.stage_take, "takes-trial", sample),
                     (self.library.accept_take, "takes-trial", staged),
                     (self.library._stage_take_locked, project, sample),
                     (self.library._accept_take_locked, project, staged))
            with patch("session_library.probe_clip") as probe, \
                 patch("session_library.takes.acceptance_lease") as lease:
                for call, target, source in calls:
                    with self.subTest(role=role, call=call.__name__), \
                         self.assertRaisesRegex(SessionError, "PARTICIPANT_RECORDING_BLOCKED"):
                        call(target, role, source)
                probe.assert_not_called()
                lease.assert_not_called()
            self.assertEqual(tree(), before)
            self.assertFalse((project / "raw" / (role + ".mp4")).exists())
        self.assertEqual(sample.read_bytes(), b"generated-not-participant-footage")

    def test_missing_raw_files_do_not_create_real_registry_or_quality_data(self):
        project = self.library.create_session("immutable-a")
        _ = self.library.list_sessions()
        _ = self.library.registration_readiness("immutable-a")
        self.assertFalse((project / "session.json").exists())
        self.assertFalse((project / "run.json").exists())
        self.assertFalse((project / "sync-observations.json").exists())


if __name__ == "__main__":
    unittest.main()
